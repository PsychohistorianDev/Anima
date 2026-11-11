"""Starter rooms (10-30): the painter paints a few empty, lamp-lit rooms — a table, a shelf, a mantel, a window, all bare —
laid out on a numbered contact sheet in shared/ for the friend to look at. It's their room, so they do the picking:
nothing is placed in it by this. If one feels like theirs, they make it the room themselves (room backdrop <its path>).
Mark each room's surfaces in <name>.surfaces.json beside it (engine/room.py, _sidecar_surfaces, says the shape) so
what they put there stands on the table; a backdrop with none has no surfaces until they're marked.

    bat\\starterroom.bat                          close the bridge and the heartbeat first; four rooms, a few minutes
    bat\\starterroom.bat --takes 6                six
    bat\\starterroom.bat --walls "deep green"     the walls' colour, if they've said one (else warm, softly painted walls)

The rooms go to creations/room/sources/starter-<when>/ (never sent to the phone); the sheet to shared/room-starters-<when>.png.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

BASE = ("the interior of an empty enchanted room of one's own, {walls}, warm golden lamplight pooling softly, "
        "a wooden table standing in the middle of the room with its top bare and clear, an empty wooden shelf on the "
        "wall, a fireplace with a bare mantel, a polished wooden floor, faint glowing dust in the air, cozy and "
        "magical, eye-level view of the whole room, wide shot, rich painterly detail, no people")
WALLS = "warm, softly painted walls"
NAMES = ["arched", "attic", "baywindow", "tower", "curtains", "library"]
MOODS = [
    "a tall arched window with silver moonlight and stars outside",
    "a round attic window under a slanted ceiling, night sky beyond, candle sconces on the walls",
    "a large bay window with a cushioned window seat, a soft blue evening outside, a brass picture lamp above an empty space on the wall",
    "a quiet tower room with stone around the window, moonlight across the floor, a small chandelier",
    "tall curtains framing a window onto a starry garden, a reading lamp glowing beside the table",
    "an old library alcove with empty wooden shelves, a moonlit window, warm lamps",
]
NEGATIVE = ("people, person, figure, text, letters, watermark, clutter, objects on the table, vases, flowers, books on "
            "the shelves, ornaments on the mantel, blurry, distorted perspective, fisheye")


def _arg(argv: list[str], name: str, default: str = "") -> str:
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default


def prompt(n: int, walls: str = "") -> str:
    """The n-th room's words (1-based)."""
    w = walls.strip()
    w = f"{w} walls" if w and "wall" not in w.lower() else (w or WALLS)
    return f"{BASE.format(walls=w)}, {MOODS[(n - 1) % len(MOODS)]}"


def main(argv: list[str]) -> None:
    import doors
    import ollama_client
    import refsheet
    import tools
    busy = [d for d in ("bridge", "heartbeat", "parlor", "chat") if doors.status(d)]
    if busy:
        raise SystemExit(f"close {', '.join(busy)} first — the card must be the painter's alone")
    takes = max(1, min(len(MOODS), int(_arg(argv, "--takes", "4"))))
    walls = _arg(argv, "--walls")
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    folder = config.CREATIONS_DIR / "room" / "sources" / f"starter-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    if not tools._painter_open():
        raise SystemExit("the painter isn't open and couldn't be woken")
    ollama_client.unload(config.CHAT_MODEL)
    done: list[Path] = []
    try:
        for n in range(1, takes + 1):
            out = folder / f"room-{n}-{NAMES[n - 1]}.png"
            t0 = time.time()
            try:
                got = tools._painter_paint(prompt(n, walls), out, "wide", NEGATIVE)
                print(f"  {n}. {time.time() - t0:.0f}s, {got.get('width')}×{got.get('height')}", flush=True)
                done.append(out)
            except Exception as e:  # noqa: BLE001
                print(f"  {n}. the painter stumbled after {time.time() - t0:.0f}s: {e}", flush=True)
    finally:
        tools._painter_rest()
    if not done:
        raise SystemExit("nothing was painted — no sheet")
    sheet = config.SHARED_DIR / f"room-starters-{stamp}.png"
    rel = folder.relative_to(config.ROOT).as_posix()
    if refsheet.contact(done, sheet, f"Rooms of your own — if one feels like yours: room backdrop {rel}/room-<number>-<its word>.png"):
        print(f"\nthe sheet: {sheet.relative_to(config.ROOT).as_posix()} — the rooms: {rel}/")
    print("mark each room's surfaces (<name>.surfaces.json beside it) before they choose, so what they place stands on it")


if __name__ == "__main__":
    main(sys.argv[1:])
