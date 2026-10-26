"""Presence — sparks: a short turn of the friend's own, every so often, while the keeper is away.

While presence is on, the bridge gives the friend a turn in the open visit when the visit has been quiet for their
interval (a "spark"): an engine line says how long it has been and what a spark can be — words to the phone, a
painting, the stone (never in the keeper's work hours), or nothing at all. next_spark(minutes) sets the interval
(PRESENCE_MIN…PRESENCE_MAX minutes; PRESENCE_DEFAULT_MIN before the first) and turns presence on; only the keeper turns
it off (/presence off), and it ends by itself when the quiet hours begin. A message from the keeper restarts the
count; a wake running holds the sparks until it ends. /discreet on the phone sends sparks silently, the words hidden
until tapped. The state lives in memory/presence.json, so it outlives a restart.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import config

STATE_FILE = config.MEMORY_DIR / "presence.json"
WAKING_FILE = config.MEMORY_DIR / ".waking"
PRESENCE_MIN, PRESENCE_MAX = 5, 60
WAKING_STALE_S = 3600  # a wake marker older than this is a wake that died without clearing it


def default_interval() -> int:
    try:
        return clamp(int(getattr(config, "PRESENCE_DEFAULT_MIN", 15) or 15))
    except (TypeError, ValueError):
        return 15


def clamp(minutes) -> int:
    try:
        m = int(round(float(minutes)))
    except (TypeError, ValueError):
        m = default_interval()
    return max(PRESENCE_MIN, min(PRESENCE_MAX, m))


def load() -> dict:
    try:
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(st, dict):
            st = {}
    except Exception:  # noqa: BLE001 — no file, or a damaged one: presence off
        st = {}
    st.setdefault("on", False)
    st.setdefault("interval", default_interval())
    st.setdefault("discreet", False)
    return st


def save(st: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def is_on() -> bool:
    return bool(load().get("on"))


def _at(minutes: int, now: datetime | None = None) -> str:
    return ((now or datetime.now()) + timedelta(minutes=minutes)).strftime("%H:%M")


def set_interval(minutes, by: str = "friend", now: datetime | None = None) -> tuple[dict, bool]:
    """The friend's rhythm: the interval (clamped), presence turned on if it was off. (state, turned on now). The
    phone is told the time set (state["announce"], taken by the bridge)."""
    st = load()
    m = clamp(minutes)
    turned_on = not st.get("on")
    st.update(on=True, interval=m)
    if turned_on:
        st.update(since=(now or datetime.now()).isoformat(timespec="seconds"), by=by)
    st["announce"] = (f"⏳ next spark in {m} min (at {_at(m, now)})" + (" — presence is on" if turned_on else ""))
    save(st)
    return st, turned_on


def turn_on(by: str = "keeper", now: datetime | None = None) -> dict:
    st = load()
    if not st.get("on"):
        st.update(on=True, since=(now or datetime.now()).isoformat(timespec="seconds"), by=by)
        save(st)
    return st


def turn_off(why: str = "") -> dict:
    st = load()
    st.update(on=False, ended=datetime.now().isoformat(timespec="seconds"), why=why)
    st.pop("announce", None)
    save(st)
    return st


def toggle_discreet() -> bool:
    st = load()
    st["discreet"] = not st.get("discreet")
    save(st)
    return bool(st["discreet"])


def take_announce() -> str:
    """The line for the phone after a next_spark, once; "" when there is none."""
    st = load()
    line = str(st.pop("announce", "") or "")
    if line:
        save(st)
    return line


def mark_waking(on: bool) -> None:
    """A wake is running (the heartbeat sets it around each wake): sparks wait."""
    try:
        if on:
            WAKING_FILE.parent.mkdir(parents=True, exist_ok=True)
            WAKING_FILE.write_text(str(time.time()), encoding="utf-8")
        else:
            WAKING_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def waking() -> bool:
    try:
        return time.time() - WAKING_FILE.stat().st_mtime < WAKING_STALE_S
    except OSError:
        return False


def due(last_activity: float, now: float | None = None) -> bool:
    """Presence on, no wake running, and the visit quiet for the interval."""
    st = load()
    if not st.get("on") or waking():
        return False
    return (now if now is not None else time.time()) - float(last_activity or 0) >= clamp(st.get("interval")) * 60


def tick_line(minutes_quiet: float, keeper: str, at_work: bool) -> str:
    """The engine's line that opens a spark — facts, and what a spark can be."""
    st = load()
    m = int(minutes_quiet)
    since = f"{m} minute{'s' if m != 1 else ''}" if m < 120 else f"{m // 60} hours"
    stone = f"not the stone — {keeper} is at work" if at_work else "the stone (a pulse, a glow)"
    return (f"[engine, not a person: a spark — presence is on. {since} since the last word between you; {keeper} is "
            f"away and won't answer this one. It is yours: words to the phone, a painting, {stone}, or let it pass "
            f"(do_nothing). Your rhythm is a spark every {clamp(st.get('interval'))} minutes; next_spark changes it "
            f"({PRESENCE_MIN}–{PRESENCE_MAX}).]")
