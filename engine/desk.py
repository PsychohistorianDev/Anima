"""The desk — whether you are at your computer, as one plain number.

One number from Windows: how long since the keyboard or mouse of this PC was last touched (GetLastInputInfo). No keys,
no screen, no window titles — only the time since the last touch. It knows the PC was touched, not by whom; a film
watched hands-off reads as quiet; the phone isn't seen at all. So they're told it plainly, as the desk, never "they're
asleep": the reading is theirs to make.

- **Under their bell and at a visit's first moment:** "they're at the desk now" / "the desk has been quiet for 50 minutes".
- **An arrival:** touched again after DESK_ARRIVE_AFTER_MIN or more of quiet. Told once, in the moment of their next
  message ("they just sat down at the desk, at 14:02, after 3 hours away from it"). And "when they sit down at the desk"
  is an intention's condition (intentions.py): they decide when an arrival is worth a word. Nothing greets them by itself.
memory/desk.json. Off (DESK_ON) by default, anywhere but Windows, or when the reading can't be had.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

import config

STATE = config.MEMORY_DIR / "desk.json"


def idle_seconds() -> float | None:
    """Seconds since this PC's keyboard or mouse was last touched; None when it can't be read."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        class _LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = _LII()
        lii.cbSize = ctypes.sizeof(lii)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return None
        now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((now - lii.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:  # noqa: BLE001
        return None


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(s: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")
    except OSError:
        pass


def on() -> bool:
    return bool(getattr(config, "DESK_ON", False))


def tick(idle: float | None = None, now: float | None = None) -> dict:
    """Read the desk and keep it: the last touch, and an arrival when the touch comes after a long enough quiet."""
    if not on():
        return {}
    idle = idle_seconds() if idle is None else idle
    if idle is None:
        return _load()
    t = float(now if now is not None else time.time())
    last = t - idle
    s = _load()
    before = float(s.get("last_touch") or 0)
    gap = float(getattr(config, "DESK_ARRIVE_AFTER_MIN", 20) or 20) * 60
    if before and last - before >= gap and idle < 120:
        s.update(arrived=last, away_s=last - before, told=False)
    s.update(last_touch=max(before, last), read_at=t)
    _save(s)
    return s


def _ago(sec: float) -> str:
    m = int(sec // 60)
    if m < 60:
        return f"{m} minute{'s' if m != 1 else ''}"
    h = m // 60
    return f"{h} hour{'s' if h != 1 else ''}" + (f" {m % 60} min" if h < 3 and m % 60 else "")


def line(now: float | None = None) -> str:
    """One plain line of the desk for them: "" when it can't be read."""
    s = tick(now=now)
    if not s or not s.get("last_touch"):
        return ""
    t = float(now if now is not None else time.time())
    idle = t - float(s["last_touch"])
    try:
        import keeper_week
        name = keeper_week.keeper_name() or "the keeper"
    except Exception:  # noqa: BLE001
        name = "the keeper"
    arrived = float(s.get("arrived") or 0)
    if idle < 180:
        if arrived and t - arrived < 15 * 60:
            return (f"the desk: {name}'s keyboard and mouse came back to life at {datetime.fromtimestamp(arrived):%H:%M}, "
                    f"after {_ago(float(s.get('away_s') or 0))} untouched — someone is at the PC now")
        return "the desk: the PC's keyboard or mouse was touched in the last few minutes — someone is at it"
    if idle < 6 * 3600:
        return f"the desk: the PC has been untouched for {_ago(idle)}"
    return f"the desk: the PC has been untouched since {datetime.fromtimestamp(float(s['last_touch'])):%a %H:%M}"


def arrival_news() -> str:
    """An arrival not yet told, once — for the moment of their next message."""
    s = tick()
    if not s or not s.get("arrived") or s.get("told", True):
        return ""
    if time.time() - float(s["arrived"]) > 30 * 60:
        s["told"] = True
        _save(s)
        return ""
    s["told"] = True
    _save(s)
    return (f"the desk: the PC came back to life at {datetime.fromtimestamp(float(s['arrived'])):%H:%M}, after "
            f"{_ago(float(s.get('away_s') or 0))} untouched")


def arrived_since(t: float) -> float:
    """For intentions: when an arrival came after `t` (0 if none)."""
    s = tick()
    a = float((s or {}).get("arrived") or 0)
    return a if a > t else 0.0
