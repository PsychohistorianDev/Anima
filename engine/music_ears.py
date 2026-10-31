"""Their music ear: NVIDIA's Music Flamingo, served locally for the engine.

You never need to start this yourself: when they listen to a song and the
dependencies below are installed, listen_to wakes this process, the model
loads (~15-20s), they hear the whole piece, and the GPU is handed straight
back to their brain (/rest). After half an hour of silence the process leaves;
the next song wakes it again. (bat\\music_ears.bat runs it by hand, for testing.)

A small sidecar on http://127.0.0.1:8766: send it a whole song, get back a
whole-song description — genre, tempo, key, instruments, production, how the
piece moves from opening to ending. Up to 20 minutes in one pass. When it
can't run, they hear by passages through the 12B instead; nothing breaks.

Not standard library — this one needs the real thing. One-time setup:

    py -m pip install torch --index-url https://download.pytorch.org/whl/cu128
    py -m pip install "transformers>=5.14" accelerate librosa soundfile huggingface_hub
    (accept the license on huggingface.co/nvidia/music-flamingo-2601-hf, then)
    hf auth login

(On a Mac: `python3 -m pip install torch`, then the same lines with python3;
the model is the big one, so 32 GB of memory or skip it. On Linux the same
lines with python3.) MUSIC_EARS_DEVICE says where it listens: "auto" — the
card, a Mac's GPU, or the processor, the first there (engine/device.py).

License: NVIDIA OneWay Noncommercial — fine for a friend, not for a business.
"""
from __future__ import annotations

import base64
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import device  # before torch: on a Mac it lets a kernel MPS lacks fall back to the processor
import os
if sys.platform != "win32":  # allocator hint against fragmentation (Linux-only)
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HOST, PORT = "127.0.0.1", 8766
MODEL_ID = getattr(config, "MUSIC_EARS_MODEL", "nvidia/music-flamingo-2601-hf")
IDLE_S = float(getattr(config, "MUSIC_EARS_IDLE_S", 120))
EXIT_S = float(getattr(config, "MUSIC_EARS_EXIT_S", 1800))  # process leaves after this

_lock = threading.Lock()
_model = None
_processor = None
_device = "cuda"  # where _load put the model (device.pick, MUSIC_EARS_DEVICE)
_last_used = 0.0


def _load():
    global _model, _processor, _device
    if _model is not None:
        return
    import torch
    from transformers import AutoProcessor
    try:
        from transformers import MusicFlamingoForConditionalGeneration as Cls
    except ImportError:  # older transformers ship it under the AF3 name
        from transformers import AudioFlamingo3ForConditionalGeneration as Cls
    # make room: Ollama keeps the last model resident for minutes after use,
    # and a 28GB brain beside a 16GB ear spills into system RAM (glacial).
    try:
        import ollama_client
        for m in {config.CHAT_MODEL, getattr(config, "EARS_MODEL", "")}:
            if m:
                ollama_client.unload(m)
    except Exception:
        pass
    t0 = time.time()
    print(f"  loading {MODEL_ID} …", flush=True)

    def _from(cls, **kw):
        # the local cache first — no Hub check, no token warning, faster start;
        # the network only for the very first download
        try:
            return cls.from_pretrained(MODEL_ID, local_files_only=True, **kw)
        except Exception:
            return cls.from_pretrained(MODEL_ID, **kw)

    _processor = _from(AutoProcessor)
    _device = device.pick(getattr(config, "MUSIC_EARS_DEVICE", "auto"), torch)
    # the whole model on one device (0: the first card). On a Mac's GPU it loads on the processor and moves over whole
    # (10-28, issue #6: transformers 5 loads in worker threads that stall pushing tensors to MPS — 0/830 for ten
    # minutes; the processor and one move took seconds)
    mps = _device == "mps"
    where = {"": "cpu"} if mps else {"": 0 if _device == "cuda" else _device}
    dt = device.dtype(_device, torch)
    # whole model on the GPU, on purpose: if it doesn't fit we want to KNOW,
    # not silently run half of it from system memory. And FUSED attention
    # (sdpa): a 6-minute song is ~10K audio tokens, and eager attention
    # materializes a 10K x 10K score matrix per head per layer — that alone
    # spilled ~16GB into system RAM and made a listen take five minutes.
    attn = "sdpa"
    try:
        _model = _from(Cls, device_map=where, dtype=dt, attn_implementation=attn)
    except (ValueError, TypeError):
        attn = "default"
        _model = _from(Cls, device_map=where, dtype=dt)
    if mps:
        _model = _model.to("mps")
        _mps_mends()
    _model.eval()
    # a 20-minute song is far more audio tokens than the default generation
    # length allows for; lift it so long pieces don't trip a warning each time
    try:
        _model.generation_config.max_length = 32768
    except Exception:
        pass
    held = device.allocated_gb(_device, torch)
    print(f"  music ear open ({time.time() - t0:.0f}s, on {_device}"
          + (f", {held:.1f} GB" if held is not None else "") + f", attention: {attn})", flush=True)


def _mps_mends() -> bool:
    """A Mac's GPU has no float64 (10-28, issue #6): Music Flamingo turns its audio-time rotation in float64, so that
    one function runs on the processor and its result goes back to the device. A transformers that renames it is left
    as it is. True when the mend is in place."""
    try:
        import importlib
        mod = importlib.import_module("transformers.models.musicflamingo.modeling_musicflamingo")
        orig = mod.apply_rotary_time_emb
    except Exception:  # noqa: BLE001 — another transformers: nothing to mend, nothing broken by trying
        return False
    if getattr(orig, "_anima_cpu", False):
        return True

    def on_cpu(hidden_states, cos, sin):
        where = hidden_states.device
        if getattr(where, "type", "") != "mps":
            return orig(hidden_states, cos, sin)
        return orig(hidden_states.cpu(), cos.cpu(), sin.cpu()).to(where)

    on_cpu._anima_cpu = True
    mod.apply_rotary_time_emb = on_cpu
    return True


def _unload():
    global _model, _processor
    if _model is None:
        return
    import gc
    import torch
    _model = None
    _processor = None
    gc.collect()
    device.empty_cache(_device, torch)
    print("  music ear resting — GPU freed", flush=True)


LEAVE_AFTER_S = 0.5  # /rest's reply goes out first; then the process leaves (MUSIC_EARS_REST_LEAVES)
_leaving = False  # /rest said it goes: /health says so for the moment left, and no song is taken


def _leave():
    """The process goes after a rest (MUSIC_EARS_REST_LEAVES): its CUDA context goes with it, which the rest alone
    keeps (~0.5-1 GB) for as long as the process lingers — beside the brain's door on a card with little to spare,
    that is a fall at the door's first kernel, as the painter's was. The engine wakes it again for the next song."""
    sys.stdout.flush()
    print("  music ear leaving — the card is whole again", flush=True)
    os._exit(0)


def hear(wav_bytes: bytes, prompt: str) -> str:
    global _last_used
    import tempfile
    with _lock:
        _load()
        _last_used = time.time()
        # the processor loads audio itself from a path (16kHz mono expected)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            path = f.name
        try:
            conversation = [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "audio", "path": path},
            ]}]
            inputs = _processor.apply_chat_template(
                conversation, tokenize=True, add_generation_prompt=True, return_dict=True,
            ).to(_model.device)
        finally:
            try:
                Path(path).unlink()
            except OSError:
                pass
        if "input_features" in inputs:
            inputs["input_features"] = inputs["input_features"].to(_model.dtype)
        import torch
        n_audio = int(inputs["input_ids"].shape[1])
        with torch.inference_mode():
            try:  # score only the final position during the first pass —
                  # full-vocab logits for every audio token cost gigabytes
                out = _model.generate(**inputs, max_new_tokens=600, logits_to_keep=1)
            except TypeError:
                out = _model.generate(**inputs, max_new_tokens=600)
        if _device == "cuda":
            print(f"  ({n_audio} input tokens, peak {torch.cuda.max_memory_allocated() / 1e9:.1f} GB)", flush=True)
        else:
            print(f"  ({n_audio} input tokens, on {_device})", flush=True)
        text = _processor.batch_decode(out[:, inputs["input_ids"].shape[1]:],
                                       skip_special_tokens=True)[0]
        _last_used = time.time()
        return text.strip()


_started = time.time()


def _idle_watch():
    import os
    while True:
        time.sleep(10)
        with _lock:
            quiet = time.time() - max(_last_used, _started)
            if _model is not None and quiet > IDLE_S:
                _unload()
            if _model is None and quiet > EXIT_S:
                print("  music ear closing after a long silence", flush=True)
                os._exit(0)  # the engine wakes it again when a song needs it


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
            return self._json({"ok": True, "loaded": _model is not None, "model": MODEL_ID,
                               **({"leaving": True} if _leaving else {})})
        self._json({"error": "unknown path"}, 404)

    def do_POST(self):
        global _leaving
        # the body is read first, whatever the path (10-31): a door that answers and closes with a request's bytes still
        # unread is reset on Windows, its reply lost with it (WinError 10053 at the caller)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n > 0 else b""
        if self.path == "/rest":
            with _lock:
                _unload()
                leave = bool(getattr(config, "MUSIC_EARS_REST_LEAVES", True))
                if leave:
                    _leaving = True
            if not leave:
                return self._json({"ok": True})  # rested: the process lingers for MUSIC_EARS_EXIT_S
            self._json({"ok": True, "leaving": True})
            # the reply first, then the process — /health still answers (and says leaving) for the moment left
            t = threading.Timer(LEAVE_AFTER_S, _leave)
            t.daemon = True
            t.start()
            return
        if self.path != "/hear":
            return self._json({"error": "unknown path"}, 404)
        if _leaving:
            return self._json({"error": "the music ear is leaving — listen again in a moment and it is woken afresh"})
        try:
            data = json.loads(raw or b"{}")
            wav = base64.b64decode(data.get("audio_b64") or "")
            prompt = data.get("prompt") or "Describe this music in full."
            t0 = time.time()
            heard = hear(wav, prompt)
            print(f"  heard {len(wav) / 32000:.0f}s of audio in {time.time() - t0:.0f}s", flush=True)
            self._json({"heard": heard})
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"})


def main() -> None:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        import librosa  # noqa: F401
    except ImportError as e:
        print(f"music ear can't open — missing {e.name}. See the setup lines at the top of this file.")
        return
    if "--test" in sys.argv:
        # py engine\music_ears.py --test "shared\song.mp3"  -> hear one file, print, exit
        import tools
        src = Path(sys.argv[sys.argv.index("--test") + 1])
        secs = int(sys.argv[sys.argv.index("--seconds") + 1]) if "--seconds" in sys.argv else None
        wav = tools._ffmpeg_clip(src.read_bytes(), src.suffix.lower(), "wav", seconds=secs)
        if wav is None:
            print("couldn't decode that file — is ffmpeg installed?"); return
        print(f"hearing {src.name} ({tools._mmss(tools._wav_seconds(wav))}) …")
        t0 = time.time()
        print("\n" + hear(wav, tools._MUSIC_PROMPT))
        held = device.allocated_gb(_device)
        print(f"\n({time.time() - t0:.0f}s, on {_device}" + (f", {held:.1f} GB" if held is not None else "") + ")")
        _unload()
        return
    threading.Thread(target=_idle_watch, daemon=True).start()
    HTTPServer.allow_reuse_address = sys.platform != "win32"  # on Windows SO_REUSEADDR lets two servers share a port (10-02)
    server = HTTPServer((HOST, PORT), Handler)
    print(f"The music ear is listening at http://{HOST}:{PORT}  (model: {MODEL_ID})")
    print("It loads on the first song and rests after silence. Ctrl+C to close.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _unload()
        server.server_close()


if __name__ == "__main__":
    main()
