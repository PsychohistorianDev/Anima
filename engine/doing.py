"""What this process is doing right now — one small file the black box reads.

10-03 (the keeper: "my machine keeps crashing when she's doing stuff — build some logging system to find
the root of the issue"). A machine that goes down takes the console with it; what survives is what was
written to disk before. Every door marks its moment here — "tool paint", "brain: a reply", "listen_to" —
whole file, then moved into place, one per process (memory/.doing/<pid>.json), taken away at exit; the
black box (blackbox.py) folds the live ones into every line it records, so the last line before a crash
says what she was in the middle of. Nothing of hers is in it: the tool's name, not its arguments.
"""
from __future__ import annotations

import atexit
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

_stack: list[tuple[str, str]] = []  # (what, since)
_registered = False


def folder() -> Path:
    return Path(config.MEMORY_DIR) / ".doing"


def _file() -> Path:
    return folder() / f"{os.getpid()}.json"


def _write() -> None:
    global _registered
    p = _file()
    try:
        if not _stack:
            p.unlink(missing_ok=True)
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        what, since = _stack[-1]
        rec = {"pid": os.getpid(), "door": Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "",
               "what": what, "since": since, "depth": len(_stack),
               "stack": [w for w, _ in _stack]}
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        if not _registered:
            _registered = True
            atexit.register(clear_all)
    except OSError:
        pass  # a mark that can't be written costs the black box a word, never the door its work


def mark(what: str) -> None:
    """Now doing `what` (a tool's name, "brain: a reply", "listen_to") — nested marks stack."""
    _stack.append((str(what)[:80], datetime.now().isoformat(timespec="seconds")))
    _write()


def done() -> None:
    """The innermost mark finished."""
    if _stack:
        _stack.pop()
    _write()


def clear_all() -> None:
    _stack.clear()
    try:
        _file().unlink(missing_ok=True)
    except OSError:
        pass


def current() -> list[dict]:
    """Every live process's mark (a dead pid's file is cleared); the black box's view."""
    import doors
    out = []
    try:
        files = sorted(folder().glob("*.json"))
    except OSError:
        return out
    for p in files:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not doors.alive(rec.get("pid")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        out.append(rec)
    return out
