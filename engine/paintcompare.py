"""Brushes side by side (10-31): the same two paintings — one from words at full size, one of the two of you with the
"us" reference set — by a few brushes, the same seed each, timed, their peak on the card; laid out on one sheet to
look at before anything is switched in config.

    bat\\paintcompare.bat                       close the bridge and the heartbeat first
    bat\\paintcompare.bat --quick               the painting from words only
    bat\\paintcompare.bat --models Qwen/Qwen-Image-2.1-Turbo,Qwen/Qwen-Image-2.1 --cfg 2.5

The brushes: the one in config (PAINTER_MODEL, with its PAINTER_GUIDANCE and PAINTER_KV_CACHE), then each of
--models; --kv adds each brush again with the prefix KV cache, --cfg <g> each again with that guidance. A brush not on
disk yet is downloaded first (a long wait, the first time). The paintings go to
creations/refsheets/sources/compare-<when>/ (never sent to the phone); the sheet to shared/paint-compare-<when>.png;
the numbers to memory/paintcompare-<when>.md.
"""
from __future__ import annotations

import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

WORDS = ("a person reading a letter by candlelight in an attic room, a round window with moonlight, warm golden light "
         "on their face, photorealistic, fine detail")
LINES: list[str] = []


def say(line: str) -> None:
    print(line, flush=True)
    LINES.append(line)


def _arg(argv: list[str], name: str, default: str = "") -> str:
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default


def variants(argv: list[str]) -> list[tuple[str, str, float, bool]]:
    """(label, model, guidance, kv) — the configured brush first, then each of --models, each with --kv / --cfg twins."""
    base = str(getattr(config, "PAINTER_MODEL", "") or "")
    models = [base] + [m.strip() for m in _arg(argv, "--models").split(",") if m.strip() and m.strip() != base]
    cfg = _arg(argv, "--cfg")
    out = []
    for m in models:
        short = m.split("/")[-1]
        g = float(getattr(config, "PAINTER_GUIDANCE", 0) or 0) if m == base else 0.0
        kv = bool(getattr(config, "PAINTER_KV_CACHE", False)) if m == base else False
        out.append((short, m, g, kv))
        if "--kv" in argv and not kv:
            out.append((short + "+kv", m, g, True))
        if cfg:
            out.append((f"{short} cfg{cfg}", m, float(cfg), kv))
    return out


def main(argv: list[str]) -> None:
    import doors
    busy = [d for d in ("bridge", "heartbeat", "parlor", "chat") if doors.status(d)]
    if busy:
        raise SystemExit(f"close {', '.join(busy)} first — the card must be the painter's alone")
    import ollama_client
    import painter
    import refsheet
    import tools
    tools._painter_rest()  # a sidecar painter, if one is up, leaves; this one paints in this window
    ollama_client.unload(config.CHAT_MODEL)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    folder = config.CREATIONS_DIR / "refsheets" / "sources" / f"compare-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    brushes = variants(argv)
    jobs = [("words", WORDS, None, painter.SIZES["square"])]
    if "--quick" not in argv:
        reference, line, set_name = tools._reference_set("us")
        refs, why = tools._paint_references(reference)
        if why or not set_name:
            say(f"(the two of you skipped: {why or 'no us set in PAINTER_REFERENCE_SETS'})")
        else:
            import selfcheck
            friend, keeper = selfcheck._names()
            us = f"{friend} and {keeper} sitting close on a sofa in a candlelit room, both smiling, photorealistic"
            jobs.append(("us", (line + " " if line else "") + us, refs, (1024, 1024)))
    keep = (painter.MODEL_ID, getattr(config, "PAINTER_GUIDANCE", 0), getattr(config, "PAINTER_KV_CACHE", False))
    done: list[Path] = []
    try:
        for vi, (name, model, guidance, kv) in enumerate(brushes):  # one brush at a time: each loads once
            for ji, (job, prompt, refs, (w, h)) in enumerate(jobs):
                n = ji * len(brushes) + vi + 1  # numbered as the sheet lays them out: a row a painting, a column a brush
                if painter.MODEL_ID != model:
                    painter._unload()
                    painter.MODEL_ID = model
                    import diffusers
                    t0 = time.time()
                    say(f"  ({model}: making sure it's on disk — the first time is a long download)")
                    painter._fetch(getattr(diffusers, painter._CLASSES[painter._family(model)]))
                    say(f"  ({model} ready on disk, {time.time() - t0:.0f}s)")
                config.PAINTER_GUIDANCE, config.PAINTER_KV_CACHE = guidance, kv
                images, why = painter._load_references(refs) if refs else (None, "")
                if why:
                    say(f"{n}. {job} · {name}: skipped — {why}")
                    continue
                ww, hh = painter._fit(model, w, h)
                t0 = time.time()
                try:
                    img, _ = painter.paint(prompt, ww, hh, seed=20261031, images=images)
                except Exception as e:  # noqa: BLE001
                    say(f"{n}. {job} · {name}: stopped after {time.time() - t0:.0f}s — {type(e).__name__}: {e}")
                    painter._unload()
                    continue
                secs = time.time() - t0
                out = folder / f"{n:02d}-{job}-{name.replace(' ', '')}-{secs:.0f}s.png"
                img.save(str(out))
                done.append(out)
                peak = painter._peak
                say(f"{n}. {job} · {name}: {secs:.0f}s, {ww}×{hh}" + (f", peak {peak:.1f} GB" if peak else ""))
                if refs:
                    painter._unload()  # a painting with references loads under offload; the next one starts clean
    finally:
        painter._unload()
        painter.MODEL_ID, config.PAINTER_GUIDANCE, config.PAINTER_KV_CACHE = keep
    done.sort(key=lambda f: f.name)
    if done:
        sheet = config.SHARED_DIR / f"paint-compare-{stamp}.png"
        if refsheet.contact(done, sheet, " · ".join(b[0] for b in brushes) + " — the same seed; the seconds in each name"):
            shutil.copy2(sheet, folder / sheet.name)
            say(f"\nthe sheet: {sheet.relative_to(config.ROOT).as_posix()}")
    report = config.MEMORY_DIR / f"paintcompare-{stamp}.md"
    report.write_text(f"# Paint compare {stamp}\n\n" + "\n".join(f"- {ln}" for ln in LINES) + "\n", encoding="utf-8")
    print(f"the numbers: {report.relative_to(config.ROOT).as_posix()}")


if __name__ == "__main__":
    main(sys.argv[1:])
