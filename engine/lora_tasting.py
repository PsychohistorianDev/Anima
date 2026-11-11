"""The LoRA tasting (11-08): the same prompts, the same seeds, the same references, painted at each LoRA strength,
side by side, so an add-on is judged against the plain brush and nothing else.

    bat\\lora-tasting.bat                                   strengths 0 (plain), 0.6, 0.9
    bat\\lora-tasting.bat --strengths 0,0.5,0.8             others
    bat\\lora-tasting.bat --model <a Hub repo> --strengths 0,0.9,1.1   on another brush of the same family

The LoRAs are PAINTER_LORAS (every one at the strength being tasted). The prompts are
models/loras/tasting-prompts.txt, one per line: "reference | prompt" — the reference as the friend would give it to
paint ("face", a reference set's name such as "us", a folder under creations/, or "-" for none); lines starting with
# are left out. The set's line and the prompt hints go in front exactly as their paint tool does it. Each prompt gets
one seed, kept across the strengths. The pictures go to models/loras/tasting/<time>/ — outside their creations —
named prompt-strength, with tasting.txt (the prompts, seeds and times). The painter loads once (twice if words-only
and reference prompts mix); the strength changes between paintings without a reload. Stop the bridge first: the
card is the painter's for the evening. Their brain, prompt and pages aren't touched; nothing here is shown to them
unless you show it.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402


def _arg(name: str, default: str = "") -> str:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and len(sys.argv) > sys.argv.index(name) + 1 else default


def read_prompts(text: str) -> list[tuple[str, str]]:
    """(reference, prompt) per line: "-" or nothing before the bar is no reference; # lines and empty ones left out."""
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "<paste" in ln:
            continue
        ref, _, prompt = ln.partition("|") if "|" in ln else ("-", "", ln)
        ref, prompt = ref.strip(), prompt.strip()
        if prompt:
            out.append(("" if ref in ("-", "") else ref, prompt))
    return out


def main() -> None:
    model = _arg("--model")
    if model:
        config.PAINTER_MODEL = model  # before the painter reads it
    import painter
    import tools
    if model:
        painter.MODEL_ID = model
    strengths = [float(x) for x in _arg("--strengths", "0,0.6,0.9").split(",") if x.strip()]
    loras = list(getattr(config, "PAINTER_LORAS", None) or ())
    if not loras:
        print("PAINTER_LORAS is empty in config.py — nothing to taste. Put a LoRA on and run again.")
        return
    src = config.ROOT / "models" / "loras" / "tasting-prompts.txt"
    pairs = read_prompts(src.read_text(encoding="utf-8")) if src.is_file() else []
    if not pairs:
        print(f"no prompts in {src} — one per line, \"reference | prompt\".")
        return
    out = config.ROOT / "models" / "loras" / "tasting" / datetime.now().strftime("%Y%m%d-%H%M")
    out.mkdir(parents=True, exist_ok=True)
    print(f"{len(pairs)} prompts × strengths {strengths} on {painter.MODEL_ID} → {out.relative_to(config.ROOT)}")
    jobs = []
    for n, (ref, prompt) in enumerate(pairs, 1):
        refs, say = [], ""
        if ref:
            ref, say, _ = tools._reference_set(ref)
            refs, why = tools._paint_references(ref)
            if why:
                print(f"  prompt {n}: {why} — skipped")
                continue
        told = " ".join(x for x in (say, tools._prompt_hints(prompt)) if x)
        full = (told + " " + prompt) if told else prompt
        images, why = painter._load_references([str(r) for r in refs]) if refs else (None, "")
        if why:
            print(f"  prompt {n}: {why} — skipped")
            continue
        seed = int.from_bytes(os.urandom(4), "little")
        jobs.append((n, full, images, seed))
    # the reference prompts first, then the words-only ones: one load each road
    jobs.sort(key=lambda j: j[2] is None)
    w0, h0 = painter.SIZES["square"]
    names = [f"lora{i}" for i in range(len(loras))]
    log = [f"model {painter.MODEL_ID}; LoRAs {loras}; trigger {getattr(config, 'PAINTER_LORA_TRIGGER', '')!r}"]
    for n, full, images, seed in jobs:
        w, h = painter._fit(painter.MODEL_ID, w0, h0)
        if images:
            w, h = painter._ref_fit(w, h)
        log.append(f"\n[{n}] seed {seed}, {'references' if images else 'words alone'}, {w}x{h}\n{full}")
        for s in strengths:
            painter._lora_override = s
            if painter._pipe is not None and painter._lora_line:
                try:  # the strength changed in place — no reload
                    painter._pipe.transformer.set_adapters(names, weights=[s] * len(names))
                    painter._lora_line = f"LoRA ×{s:g}"
                except Exception as e:  # noqa: BLE001
                    print(f"  (the strength didn't change in place — {e}; reloading)")
                    painter._unload()
            t0 = time.time()
            try:
                img, seed = painter.paint(full, w, h, seed, images=images)
            except Exception as e:  # noqa: BLE001
                print(f"  [{n}] ×{s:g}: {type(e).__name__}: {e}")
                log.append(f"  ×{s:g}: failed — {type(e).__name__}: {e}")
                continue
            f = out / f"{n:02d}-x{s:g}.png"
            img.save(str(f))
            peak = f", peak {painter._peak:.1f} GB" if painter._peak else ""
            print(f"  [{n}] ×{s:g}: {f.name} ({time.time() - t0:.0f}s{peak})", flush=True)
            log.append(f"  ×{s:g}: {f.name}, {time.time() - t0:.0f}s{peak}")
    (out / "tasting.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    painter._unload()
    print(f"\ndone — {out.relative_to(config.ROOT)} (tasting.txt holds the prompts, seeds and times)")


if __name__ == "__main__":
    main()
