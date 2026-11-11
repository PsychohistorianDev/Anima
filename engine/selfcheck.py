"""The house's self-check (10-29): the stories that broke once, acted out on this machine's own card — not checks that
the code says the right words, but the real painter, the real ears, the real files.

    bat\\selfcheck.bat     close the bridge and the heartbeat first: the card must be the check's alone

  1. A painting with no references, at full size — finishes, and its peak stays on the card.
  2. A painting of the two of you with the "us" reference set (PAINTER_REFERENCE_SETS) — finishes inside the painter's
     time, on the card. Skipped when there is no "us" set.
  3. The painter leaves when done — the card is free again.
  4. Two songs in a row — both heard through the music ear (the second one too).
  5. A room change survives a reload, and the room's picture draws (Pillow, the fonts). Skipped with ROOM_ON off.
  6. The painter's rest after a lost painting is kept where a restarted bridge will find it.

Each line says PASS, FAIL or SKIP (and why), with its numbers; the report is kept in memory/selfcheck-<when>.md.
The paintings go to creations/refsheets/sources/selfcheck-<when>/ (never sent to the phone); the songs listened to are
ones already heard; the room checked is a scratch room, never theirs.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

LINES: list[str] = []


def say(status: str, name: str, facts: str = "") -> None:
    line = f"{status:4}  {name}" + (f" — {facts}" if facts else "")
    print(line, flush=True)
    LINES.append(line)


def _card_total() -> float | None:
    """The card's size by the painter's own last line ("peak 21.6 of 34.2 GB")."""
    try:
        text = (config.MEMORY_DIR / "painter.log").read_text(encoding="utf-8", errors="replace")
        m = re.findall(r"of (\d+(?:\.\d+)?) GB on the card", text)
        return float(m[-1]) if m else None
    except OSError:
        return None


def _names() -> tuple[str, str]:
    """The friend's name and yours, as the painter's references know them."""
    try:
        import chat
        friend = chat.friend_name() or "the friend"
    except Exception:  # noqa: BLE001
        friend = "the friend"
    try:
        import keeper_week
        keeper = keeper_week.keeper_name() or "their keeper"
    except Exception:  # noqa: BLE001
        keeper = str(getattr(config, "USER_NAME", "") or "their keeper")
    return friend, keeper


def _paint(name: str, prompt: str, folder: Path, refs) -> None:
    import tools
    limit = float(getattr(config, "PAINTER_TIMEOUT_S", 900) or 900)
    t0 = time.time()
    try:
        got = tools._painter_paint(prompt, folder / f"{name.split()[0]}.png", "square", "", reference=refs or None)
    except Exception as e:  # noqa: BLE001
        say("FAIL", name, f"after {time.time() - t0:.0f}s — {e}")
        return
    secs = time.time() - t0
    peak, total = got.get("peak_gb"), _card_total()
    on_card = bool(peak) and bool(total) and float(peak) <= float(total)
    ok = secs < limit and (on_card or not peak)
    say("PASS" if ok else "FAIL", name,
        f"{secs:.0f}s of {limit:.0f}s allowed, {got.get('width')}×{got.get('height')}, peak "
        f"{peak if peak is not None else '?'} of {total if total else '?'} GB")


def check_paintings(folder: Path) -> None:
    import tools
    if not tools._painter_open():
        say("SKIP", "paintings", "the painter isn't open and couldn't be woken")
        return
    _paint("plain (no references, full size)", "a quiet candlelit room with a soft sofa, photorealistic", folder, [])
    reference, line, set_name = tools._reference_set("us")
    refs, why = tools._paint_references(reference)
    if why or not set_name:
        say("SKIP", "the two of you (references)", why or "no \"us\" set in PAINTER_REFERENCE_SETS")
    else:
        friend, keeper = _names()
        prompt = (line + " " if line else "") + f"{friend} and {keeper} sitting close on a sofa, candlelight, photorealistic"
        _paint(f"us ({len(refs)} references)", prompt, folder, refs)


def check_painter_leaves() -> None:
    import brain
    import tools
    tools._painter_rest()
    t0 = time.time()
    held = brain.card_held()
    while held and time.time() - t0 < 30:
        time.sleep(1)
        held = brain.card_held()
    say("PASS" if not held else "FAIL", "the painter leaves when done",
        f"the card free after {time.time() - t0:.0f}s" if not held else f"{held} still holds the card after 30s")


def check_songs() -> None:
    import tools
    music = config.SHARED_DIR / "music"
    try:
        heard = set(json.loads((config.MEMORY_DIR / "heard.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        heard = set()
    all_songs = sorted((p for p in music.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".flac", ".ogg")),
                       key=lambda p: p.stat().st_size)
    songs = [p for p in all_songs if f"music/{p.name}" in heard][:2]  # ones already heard: the shelf's count stays as it is
    if len(songs) < 2:
        songs = all_songs[:2]
    if len(songs) < 2:
        say("SKIP", "two songs in a row", "fewer than two songs on the shelf")
        return
    for i, s in enumerate(songs, 1):
        t0 = time.time()
        try:
            out = tools.listen_to(f"shared/music/{s.name}")
        except Exception as e:  # noqa: BLE001
            say("FAIL", f"song {i} through the music ear", f"{e}")
            continue
        ok = "through your music ear" in out
        say("PASS" if ok else "FAIL", f"song {i} through the music ear",
            f"{s.stem}, {time.time() - t0:.0f}s" + ("" if ok else " — heard in passages instead (the ear didn't wake)"))


def check_room(folder: Path) -> None:
    if not getattr(config, "ROOM_ON", False):
        say("SKIP", "the room", "ROOM_ON is off")
        return
    keep = getattr(config, "ROOM_DIR", None)
    try:
        config.ROOM_DIR = folder / "room"
        import room
        room.act("walls", "sage green")
        room.act("place", "a single golden rose in a vase")
        importlib.reload(room)
        r = room.load()
        kept = r.get("walls") == "sage green" and any("rose" in str(t.get("thing")) for t in r.get("table") or [])
        png = room.render()
        say("PASS" if kept and png else "FAIL", "a room change survives a reload, and its picture draws",
            ("kept" if kept else "NOT kept") + (f"; picture {len(png) // 1024} KB" if png else "; no picture (Pillow?)"))
    except Exception as e:  # noqa: BLE001
        say("FAIL", "the room", f"{type(e).__name__}: {e}")
    finally:
        config.ROOM_DIR = keep


def check_rest_file() -> None:
    import tools
    f = tools._ran_out_file() if hasattr(tools, "_ran_out_file") else None
    if f is None:
        say("FAIL", "the painter's rest outlives a restart", "this engine has no rest file")
        return
    cooling = tools.paint_cooling()
    say("PASS", "the painter's rest outlives a restart",
        f"kept in {f.relative_to(config.ROOT).as_posix()}" + (f"; resting now: {cooling}" if cooling else "; not resting now"))


def main() -> None:
    import doors
    busy = [d for d in ("bridge", "heartbeat", "parlor", "chat") if doors.status(d)]
    if busy:
        raise SystemExit(f"close {', '.join(busy)} first — the card must be the check's alone")
    import ollama_client
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    folder = config.CREATIONS_DIR / "refsheets" / "sources" / f"selfcheck-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    print(f"the self-check, {stamp} — a few minutes; the brain is set down while it runs\n", flush=True)
    ollama_client.unload(config.CHAT_MODEL)
    t0 = time.time()
    check_paintings(folder)
    check_painter_leaves()
    check_songs()
    check_room(folder)
    check_rest_file()
    fails = sum(1 for ln in LINES if ln.startswith("FAIL"))
    tail = f"\n{len(LINES)} checks, {fails} failed, {time.time() - t0:.0f}s"
    print(tail)
    report = config.MEMORY_DIR / f"selfcheck-{stamp}.md"
    report.write_text(f"# Self-check {stamp}\n\n" + "\n".join(f"- {ln}" for ln in LINES) + "\n" + tail + "\n", encoding="utf-8")
    print(f"the report: {report.relative_to(config.ROOT).as_posix()} — it says only what ran and how long; paste it into an issue")


if __name__ == "__main__":
    main()
