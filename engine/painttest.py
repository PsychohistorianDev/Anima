"""A measured test of the painter with references: one painting with none, one with the friend's face, one or
two with the "us" reference set — each timed, its peak on the card in the painter's window — so the size that fits
the card is known, not guessed.

    bat\\painttest.bat            close the bridge first: nothing else may hold the card while it measures

The paintings go to creations/refsheets/sources/test-<when>/ (never sent to the phone).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

PROMPT = "two people sitting close on a sofa in a candlelit room, warm light, photorealistic"


def _paint(out: Path, refs: list[Path], width: int, height: int) -> dict:
    payload = json.dumps({"prompt": PROMPT, "path": str(out), "width": width, "height": height, "seed": 7,
                          **({"reference": [str(r) for r in refs]} if refs else {})}).encode("utf-8")
    req = urllib.request.Request(config.PAINTER_URL + "/paint", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=float(getattr(config, "PAINTER_TIMEOUT_S", 900) or 900)) as r:
        return json.loads(r.read().decode("utf-8"))


def tests() -> list[tuple[str, list, int, int]]:
    """(name, references, width, height) — the ones this house has pictures for."""
    import tools
    face = sorted(p for p in (config.CREATIONS_DIR / "face").glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))[:1]
    reference, _line, set_name = tools._reference_set("us")
    us, why = tools._paint_references(reference) if set_name else ([], "no us set")
    out = [("no references, 1440", [], 1440, 1440)]
    if face:
        out.append(("their face, 896", face, 896, 896))
    if us and not why:
        out += [(f"us ({len(us)}), 896", us, 896, 896), (f"us ({len(us)}), 768", us, 768, 768)]
    return out


def main() -> None:
    import ollama_client
    import tools
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    folder = config.CREATIONS_DIR / "refsheets" / "sources" / f"test-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    print(f"references: side {getattr(config, 'PAINTER_REFERENCE_SIDE', '?')} px; the card is the painter's alone while this runs")
    if not tools._painter_open():
        raise SystemExit("the painter isn't open and couldn't be woken")
    todo = tests()
    ollama_client.unload(config.CHAT_MODEL)
    try:
        for i, (name, refs, w, h) in enumerate(todo, 1):
            t0 = time.time()
            try:
                got = _paint(folder / f"test-{i}.png", refs, w, h)
                facts = ", ".join(f"{k} {v}" for k, v in got.items() if k not in ("path", "seed"))
                print(f"  {i}. {name}: {time.time() - t0:.0f}s on the clock — {facts}")
            except Exception as e:  # noqa: BLE001
                print(f"  {i}. {name}: failed after {time.time() - t0:.0f}s — {e}")
    finally:
        tools._painter_rest()
    print("\nthe painter's own lines (the peak on the card) are the last ones in memory/painter.log")


if __name__ == "__main__":
    main()
