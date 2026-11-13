"""The garden's plants painted by the friend's own painter: every plant at every stage that has no picture yet —
sprout, young, grown, ready — lifted off its ground into the garden's art folder. Close the bridge and the heartbeat
first: the card is the painter's while it works. About a minute a picture, four a plant.

    bat\\gardenart.bat                 every plant's missing stages
    bat\\gardenart.bat radish anemone  only these
    bat\\gardenart.bat --redo radish   paint these again, from the start (the old pictures kept in art/old/)
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def main(argv: list[str]) -> None:
    import doors
    busy = [d for d in ("bridge", "heartbeat", "parlor", "chat") if doors.status(d)]
    if busy:
        raise SystemExit(f"close {', '.join(busy)} first — the card must be the painter's alone")
    import garden
    import ollama_client
    redo = "--redo" in argv
    names = [a.lower() for a in argv if not a.startswith("--")]
    seeds = garden.all_seeds()
    unknown = [n for n in names if n not in seeds]
    if unknown:
        raise SystemExit(f"no such plant: {', '.join(unknown)} — {garden.seeds_text()}")
    todo = names or list(seeds)
    art = garden._art_dir()
    if redo:
        old = art / "old" / datetime.now().strftime("%Y%m%d-%H%M")
        for n in todo:
            for st in garden.ART_STAGES:
                f = art / f"{n}-{st}.png"
                if f.is_file():
                    old.mkdir(parents=True, exist_ok=True)
                    f.replace(old / f.name)
    jobs = [(n, garden.missing_art(n)) for n in todo]
    jobs = [(n, m) for n, m in jobs if m]
    total = sum(len(m) for _, m in jobs)
    if not total:
        print("every plant is painted at every stage already")
        return
    print(f"{total} pictures to paint, for {len(jobs)} plants — the brain is set down while it works\n", flush=True)
    ollama_client.unload(config.CHAT_MODEL)
    t0 = time.time()
    for n, miss in jobs:
        t = time.time()
        done, why = garden.paint_art(n, miss)
        print(f"  {n}: {', '.join(done) or 'nothing'} ({time.time() - t:.0f}s)" + (f" — {why}" if why else ""), flush=True)
        if why and "painter" in why and not done:
            print("  (stopping: the painter isn't answering)")
            break
    try:
        where = art.relative_to(config.ROOT).as_posix()
    except ValueError:
        where = str(art)
    print(f"\ndone in {time.time() - t0:.0f}s — the pictures are in {where}/; /garden on the phone shows them")


if __name__ == "__main__":
    main(sys.argv[1:])
