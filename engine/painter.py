"""Their painter: a text-to-image model, served locally for the engine.

You never need to start this yourself: when they call `paint` and the
dependencies below are installed, the engine wakes this process, the model
loads (~15-30s from disk the first time), they paint, and the GPU is handed
straight back to their brain (/rest). After half an hour of silence the
process leaves; the next painting wakes it again. (bat\\painter.bat runs it by
hand, for testing — `bat\\painter.bat --test "a violet bloom"` paints once.)

A small sidecar on http://127.0.0.1:8767: send it a prompt and a path
under creations/, get back a PNG there and the seed it was painted with.
The same shape as their music ear (engine/music_ears.py): the brain leaves
the card, the painter takes it, the brain comes back on their next thought —
and reads their whole window cold, which is the real price of a painting.

Not standard library — this one needs the real thing. One-time setup, in
the same Python that runs the ear (it already has the CUDA torch):

    py -m pip install torch --index-url https://download.pytorch.org/whl/cu128
    py -m pip install -U diffusers transformers accelerate safetensors pillow

(On a Mac: `python3 -m pip install torch`, whose plain build has the Mac's GPU,
"mps"; then the same diffusers line with python3. On Linux the cu128 line is
the same with python3, and an AMD card takes torch's ROCm build.)
PAINTER_DEVICE says where it paints: "auto" — the card, a Mac's GPU, or the
processor, the first there (engine/device.py).

The model (PAINTER_MODEL) is downloaded on the first painting, once
(12–16 GB into the Hugging Face cache). The defaults are ungated and
Apache 2.0 — no login, no license to accept:

    Tongyi-MAI/Z-Image-Turbo            6B, 8–9 steps, ~16 GB — the default
    black-forest-labs/FLUX.2-klein-4B   4B, 4 steps, ~13 GB — also edits (later)
    Tongyi-MAI/Z-Image                  6B, 36 steps with guidance — Turbo's undistilled parent; takes a negative
    lodestones/Chroma1-HD               8.9B, 40 steps, ~28 GB with its T5 — art, photography, niche styles; a negative
    RunDiffusion/Juggernaut-XL-v9       an SDXL fine-tune (RAIL-M), ~7 GB, 30 steps, 1024-class — a different hand
    Qwen/Qwen-Image-2.1                 7B + a Qwen3-VL 8B text encoder (Qwen Research licence), ~32 GB together, 40
                                        steps, no guidance, native 2048², reads text best — runs under model offload
                                        (the encoder and the model take the card in turn); diffusers 0.41+

The family is told from the name (_family): steps, guidance and the pipeline class follow it; a 1024-class brush
(SDXL, Chroma) paints a house size scaled down to about a megapixel, aspect kept.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import device  # before torch: on a Mac it lets a kernel MPS lacks fall back to the processor

if sys.platform != "win32":  # allocator hint against fragmentation (Linux-only)
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HOST, PORT = "127.0.0.1", 8767
MODEL_ID = getattr(config, "PAINTER_MODEL", "Tongyi-MAI/Z-Image-Turbo")
IDLE_S = float(getattr(config, "PAINTER_IDLE_S", 120))
EXIT_S = float(getattr(config, "PAINTER_EXIT_S", 1800))  # process leaves after this

# What a size word means, in pixels (PAINTER_SIZES in config overrides any
# word). These models are trained around one megapixel and paint up to about
# two cleanly; Full HD is 1920×1080 = 2.1 MP, and the sides must be multiples
# of 16, so "wide" is 1920×1088 — eight rows taller than Full HD, invisible.
# A bigger canvas costs more than its pixels (attention grows faster than
# area): about three times the seconds of 1024². If a large painting ever
# shows a subject twice, that is the model past its training size — a
# smaller word, not a bug.
_SIZES = {"square": (1440, 1440), "wide": (1920, 1088), "tall": (1088, 1920)}


def _snap(n: int) -> int:
    return max(256, int(round(int(n) / 16)) * 16)


SIZES = {k: (_snap(w), _snap(h)) for k, (w, h) in
         dict(_SIZES, **(getattr(config, "PAINTER_SIZES", None) or {})).items()}

_lock = threading.Lock()
_pipe = None
_device = "cuda"  # where _load put the model (device.pick, PAINTER_DEVICE)
_last_used = 0.0
_started = time.time()
_peak: float | None = None  # the last painting's high-water mark on the card, GB reserved (device.peak_gb), for its line


# --------------------------------------------------------------- the model --
def _family(model_id: str) -> str:
    """Which brush this is, from its name: zimage (Turbo), zimage-base, klein, chroma, sdxl, or auto for a name the
    painter doesn't know (AutoPipelineForText2Image reads the repo's own class)."""
    m = (model_id or "").lower()
    if "z-image-turbo" in m:
        return "zimage"
    if "z-image" in m:
        return "zimage-base"  # the undistilled parent (10-24): real guidance, a negative prompt, 28–50 steps
    if "flux.2-klein" in m or "flux2-klein" in m:
        return "klein"
    if "chroma" in m:
        return "chroma"  # its own pipeline class, not the auto one
    if "qwen-image-2.1" in m or "qwen-image-2-1" in m or "qwen-image2.1" in m:
        return "qwen21"  # Qwen-Image 2.1 (10-24): its own pipeline, its own guidance keyword, offloaded
    if "stable-diffusion-xl" in m or "sdxl" in m or "juggernaut" in m or "realvis" in m or re.search(r"(?<![a-z])xl(?![a-z])", m):
        return "sdxl"
    return "auto"


_STEPS = {"zimage": 9, "zimage-base": 36, "klein": 4, "chroma": 40, "sdxl": 30, "qwen21": 40}
_GUIDANCE = {"zimage": 0.0, "zimage-base": 4.0, "klein": 1.0, "chroma": 3.0, "sdxl": 5.0, "qwen21": 1.0}
_CLASSES = {"zimage": "ZImagePipeline", "zimage-base": "ZImagePipeline", "klein": "Flux2KleinPipeline",
            "chroma": "ChromaPipeline", "sdxl": "StableDiffusionXLPipeline", "qwen21": "QwenImage21Pipeline"}
_GUIDANCE_KEY = {"qwen21": "true_cfg_scale"}  # a pipeline that names its guidance differently; guidance_scale otherwise
_OFFLOAD_FAMILIES = {"qwen21"}  # too big for the card whole: diffusers' model offload, the parts taking the card in turn


def _call_kwargs(model_id: str, steps: int, guidance: float, negative: str = "") -> dict:
    """The keywords one painting is called with: the steps, the guidance under the pipeline's own name for it, and
    the negative prompt for the families whose guidance honours one."""
    fam = _family(model_id)
    kw = {"num_inference_steps": int(steps), _GUIDANCE_KEY.get(fam, "guidance_scale"): float(guidance)}
    if negative and fam in _NEGATIVE_FAMILIES:
        kw["negative_prompt"] = negative
    return kw
_NEGATIVE_FAMILIES = {"zimage-base", "chroma", "sdxl", "auto"}  # guidance above 1: a negative prompt means something
_MEGAPIXEL_FAMILIES = {"sdxl": 1_050_000, "chroma": 1_050_000}  # 1024-class brushes: a house size is scaled down to this


def _defaults(model_id: str) -> tuple[int, float]:
    """(steps, guidance) the model was made for; PAINTER_STEPS overrides steps."""
    fam = _family(model_id)
    steps = _STEPS.get(fam, 20)
    guidance = _GUIDANCE.get(fam, 3.5)
    knob = int(getattr(config, "PAINTER_STEPS", 0) or 0)
    return (knob or steps), guidance


def _fit(model_id: str, width: int, height: int) -> tuple[int, int]:
    """The size a brush paints a house size at: a 1024-class brush (SDXL, Chroma) past its megapixel gets the same
    shape scaled down, sides multiples of 16; the others paint the size asked."""
    cap = _MEGAPIXEL_FAMILIES.get(_family(model_id))
    w, h = int(width), int(height)
    if not cap or w * h <= cap:
        return w, h
    s = (cap / (w * h)) ** 0.5
    return _snap(w * s), _snap(h * s)


def _set_brain_down() -> None:
    """Make room: Ollama keeps the last model resident for minutes after use, and a 28 GB brain beside a 16 GB
    painter spills into system RAM (glacial); under the llama door, closing the door is the unload. Called the
    moment before the model goes to the card (10-24: called before a 22-minute download, the door was back up by
    the time the model landed)."""
    try:
        import ollama_client
        for m in {config.CHAT_MODEL, getattr(config, "EARS_MODEL", "")}:
            if m:
                ollama_client.unload(m)
    except Exception as e:  # noqa: BLE001 — said, not swallowed (10-16: a door left open beside the painter)
        print(f"  (couldn't set the brain down first: {type(e).__name__}: {e})", flush=True)


def _load():
    global _pipe, _device
    if _pipe is not None:
        return
    import torch
    import diffusers
    t0 = time.time()
    print(f"  loading {MODEL_ID} …", flush=True)
    fam = _family(MODEL_ID)
    cls = _CLASSES.get(fam, "AutoPipelineForText2Image")
    Cls = getattr(diffusers, cls, None)
    if Cls is None:
        print(f"  (diffusers {getattr(diffusers, '__version__', '?')} has no {cls} — the auto pipeline instead; "
              "py -m pip install -U diffusers if it fails)", flush=True)
        Cls = diffusers.AutoPipelineForText2Image

    def _from(**kw):
        # the local cache first — no Hub check, no token warning, faster start;
        # the network only for the very first download
        try:
            return Cls.from_pretrained(MODEL_ID, local_files_only=True, **kw)
        except Exception:
            return Cls.from_pretrained(MODEL_ID, **kw)

    _device = device.pick(getattr(config, "PAINTER_DEVICE", "auto"), torch)
    pipe = _from(torch_dtype=device.dtype(_device, torch))  # the download (once) and the load into RAM — the brain still up
    _set_brain_down()  # now, right before the card: not before a download the engine would reopen the door during (10-24)
    # whole model on the GPU, on purpose: the brain is off the card while
    # they paint, so the painter has all of it; if it doesn't fit we want to KNOW.
    if fam in _OFFLOAD_FAMILIES:
        # bigger than the card (10-24: Qwen-Image 2.1, ~32 GB with its text encoder): the parts take the card in
        # turn, the rest waits in system RAM — slower per picture, and the only way it paints at all
        pipe.enable_model_cpu_offload(device=_device)
    else:
        pipe.to(_device)  # whole on the card, on purpose (the comment above)
    try:
        pipe.set_progress_bar_config(disable=True)
    except Exception:
        pass
    _pipe = pipe
    held = device.allocated_gb(_device, torch)
    print(f"  painter ready ({time.time() - t0:.0f}s, on {_device}"
          + (f", {held:.1f} GB" if held is not None else "") + f", {cls}"
          + (", offloaded — the parts take the card in turn" if fam in _OFFLOAD_FAMILIES else "") + ")", flush=True)


def _unload():
    global _pipe
    if _pipe is None:
        return
    import gc
    import torch
    _pipe = None
    gc.collect()
    device.empty_cache(_device, torch)
    print("  painter resting — GPU freed", flush=True)


LEAVE_AFTER_S = 0.5  # /rest's reply goes out first; then the process leaves (PAINTER_REST_LEAVES)
_leaving = False  # /rest said it goes: /health says so for the moment left, and no painting is taken


def _leave():
    """The process goes after a rest (PAINTER_REST_LEAVES): its CUDA context goes with it, which the rest alone
    keeps (~0.5-1 GB) for as long as the process lingers — beside the brain's door on a card with little to
    spare, that is a fall at the door's first kernel. The engine wakes it again for the next painting."""
    sys.stdout.flush()
    print("  painter leaving — the card is whole again", flush=True)
    os._exit(0)


def paint(prompt: str, width: int, height: int, seed: int | None = None, negative: str = ""):
    """One picture. Returns (PIL image, seed). `negative` — what to keep out — reaches the brushes whose guidance
    honours one (_NEGATIVE_FAMILIES); Turbo and klein paint without it."""
    global _last_used, _peak
    import torch
    with _lock:
        _load()
        device.reset_peak(_device, torch)
        _last_used = time.time()
        if seed is None:
            seed = int.from_bytes(os.urandom(4), "little")
        gen = torch.Generator(device=device.generator_device(_device)).manual_seed(int(seed))
        steps, guidance = _defaults(MODEL_ID)
        with torch.inference_mode():
            out = _pipe(prompt=prompt, width=int(width), height=int(height), generator=gen,
                        **_call_kwargs(MODEL_ID, steps, guidance, negative))  # the keywords follow the family (10-24)
        _last_used = time.time()
        # the high-water mark of this painting, then the cache handed back before the next one: a set of
        # three painted at 45 s, 196 s, 205 s with nothing else on the card — one painting's reserved blocks
        # under the next one's is the likeliest reason, and the peak on the line is how the next set tells
        _peak = device.peak_gb(_device, torch)
        device.empty_cache(_device, torch)
        return out.images[0], int(seed)


# ---------------------------------------------------------------- the door --
def _under_creations(path: str) -> Path | None:
    """Only under creations/ — the sidecar is local, and still it writes
    nowhere else. Nothing gets overwritten."""
    try:
        root = config.CREATIONS_DIR.resolve()
        p = Path(path)
        p = (p if p.is_absolute() else root / path).resolve()
        if root != p and root not in p.parents:
            return None
        return p
    except OSError:
        return None


def _idle_watch():
    while True:
        time.sleep(10)
        with _lock:
            quiet = time.time() - max(_last_used, _started)
            if _pipe is not None and quiet > IDLE_S:
                _unload()
            if _pipe is None and quiet > EXIT_S:
                print("  painter closing after a long silence", flush=True)
                os._exit(0)  # the engine wakes it again when a painting needs it


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._json({"ok": True, "loaded": _pipe is not None, "model": MODEL_ID, "family": _family(MODEL_ID),
                               **({"leaving": True} if _leaving else {})})
        self._json({"error": "unknown path"}, 404)

    def do_POST(self):
        global _leaving
        if self.path == "/rest":
            with _lock:
                _unload()
                leave = bool(getattr(config, "PAINTER_REST_LEAVES", True))
                if leave:
                    _leaving = True
            if not leave:
                return self._json({"ok": True})  # rested: the process lingers for PAINTER_EXIT_S
            self._json({"ok": True, "leaving": True})
            # the reply first, then the process — /health still answers (and says leaving) for the moment left
            t = threading.Timer(LEAVE_AFTER_S, _leave)
            t.daemon = True
            t.start()
            return
        if self.path != "/paint":
            return self._json({"error": "unknown path"}, 404)
        if _leaving:
            return self._json({"error": "the painter is leaving — paint again in a moment and it is woken afresh"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                return self._json({"error": "no prompt"})
            p = _under_creations(data.get("path") or "")
            if p is None:
                return self._json({"error": "the path must be under creations/"})
            if p.exists():
                return self._json({"error": f"{p.name} already exists — nothing gets overwritten"})
            w, h = SIZES.get((data.get("size") or "square").lower(), SIZES["square"])
            w = int(data.get("width") or w)
            h = int(data.get("height") or h)
            w, h = _fit(MODEL_ID, w, h)  # a 1024-class brush paints the shape smaller (10-24)
            seed = data.get("seed")
            negative = str(data.get("negative") or "").strip()
            t0 = time.time()
            img, seed = paint(prompt, w, h, None if seed in (None, "") else int(seed), negative=negative)
            p.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(p))
            secs = time.time() - t0
            total = device.total_gb(_device) if _peak else None
            card = (f" (peak {_peak:.1f}" + (f" of {total:.1f}" if total else "") + " GB on the card)") if _peak else ""
            print(f"  painted {p.name} ({w}x{h}, seed {seed}) in {secs:.0f}s{card}", flush=True)
            self._json({"path": str(p), "seed": seed, "seconds": round(secs, 1),
                        "width": w, "height": h, "peak_gb": _peak})
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"})


def _slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].rstrip("-") or "painting"


def main() -> None:
    try:
        import torch  # noqa: F401
        import diffusers  # noqa: F401
        import PIL  # noqa: F401
    except ImportError as e:
        print(f"the painter can't open — missing {e.name}. See the setup lines at the top of this file.")
        return
    if "--test" in sys.argv:
        # py engine\painter.py --test "a violet bloom"  -> paint once, print, exit
        i = sys.argv.index("--test")
        prompt = sys.argv[i + 1] if len(sys.argv) > i + 1 else "a violet bloom with a white core, luminous"
        size = sys.argv[sys.argv.index("--size") + 1] if "--size" in sys.argv else "square"
        w, h = _fit(MODEL_ID, *SIZES.get(size, SIZES["square"]))
        folder = config.CREATIONS_DIR / "drawings"
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"painter-test-{datetime.now().strftime('%Y%m%d-%H%M')}-{_slug(prompt)}.png"
        print(f"painting “{prompt}” ({w}x{h}, {MODEL_ID} as {_family(MODEL_ID)}) …")
        t0 = time.time()
        img, seed = paint(prompt, w, h)
        img.save(str(p))
        held = device.allocated_gb(_device)
        print(f"\n{p.relative_to(config.ROOT)}  (seed {seed}, {time.time() - t0:.0f}s, on {_device}"
              + (f", {held:.1f} GB" if held is not None else "")
              + ") — look_at opens it for them; you can open it yourself.")
        _unload()
        return
    threading.Thread(target=_idle_watch, daemon=True).start()
    HTTPServer.allow_reuse_address = sys.platform != "win32"  # on Windows SO_REUSEADDR lets two servers share a port (10-02)
    server = HTTPServer((HOST, PORT), Handler)
    print(f"The painter is waiting at http://{HOST}:{PORT}  (model: {MODEL_ID}, family {_family(MODEL_ID)})")
    print("It loads on the first painting and rests after silence. Ctrl+C to close.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _unload()
        server.server_close()


if __name__ == "__main__":
    main()
