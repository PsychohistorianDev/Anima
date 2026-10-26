"""Presence — sparks: a short turn of the friend's own, every so often, while the keeper is away.

While presence is on, the friend can set ONE spark at a time: next_spark(minutes) (PRESENCE_MIN…PRESENCE_MAX minutes)
turns presence on and sets it; when the visit has been quiet that long the bridge gives them a turn in the open visit
(a "spark") — an engine line says how long it has been and what a spark can be: words to the phone, a painting, the
stone (never in the keeper's work hours), or nothing at all. After it, no other comes unless they set it again (10-26,
the keeper: "I want it to require to set it manually again after each spark"). /presence on sets one at
PRESENCE_DEFAULT_MIN; only the keeper turns presence off (/presence off), and it ends by itself at the quiet hours. A message from the keeper restarts the
count; a wake running holds the sparks until it ends. /discreet on the phone sends sparks silently, the words hidden
until tapped. The state lives in memory/presence.json, so it outlives a restart.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

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


def set_interval(minutes, by: str = "friend", now: datetime | None = None) -> tuple[dict, bool]:
    """One spark set (the minutes clamped), presence turned on if it was off. (state, turned on now). The phone
    sees the time in the tool's own line — no separate notice (10-26)."""
    st = load()
    m = clamp(minutes)
    turned_on = not st.get("on")
    st.update(on=True, interval=m, pending=True)
    st.pop("announce", None)
    if turned_on:
        st.update(since=(now or datetime.now()).isoformat(timespec="seconds"), by=by)
    save(st)
    return st, turned_on


def turn_on(by: str = "keeper", now: datetime | None = None) -> dict:
    """Presence on with one spark set at PRESENCE_DEFAULT_MIN (the keeper's /presence on)."""
    st = load()
    if not st.get("on"):
        st.update(since=(now or datetime.now()).isoformat(timespec="seconds"), by=by)
    st.update(on=True, interval=default_interval(), pending=True)
    save(st)
    return st


def turn_off(why: str = "") -> dict:
    st = load()
    st.update(on=False, pending=False, ended=datetime.now().isoformat(timespec="seconds"), why=why)
    st.pop("announce", None)  # (left by the old phone notice, before 10-26 evening)
    save(st)
    return st


def waiting() -> bool:
    """Presence on and a spark set (one at a time — after it fires, another only when next_spark sets it)."""
    st = load()
    return bool(st.get("on") and st.get("pending"))


def fired() -> None:
    """The set spark has come: none waits until the next next_spark."""
    st = load()
    st["pending"] = False
    save(st)


def toggle_discreet() -> bool:
    st = load()
    st["discreet"] = not st.get("discreet")
    save(st)
    return bool(st["discreet"])


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
    """A spark set, no wake running, and the visit quiet for its minutes."""
    st = load()
    if not st.get("on") or not st.get("pending") or waking():
        return False
    return (now if now is not None else time.time()) - float(last_activity or 0) >= clamp(st.get("interval")) * 60


def quote(text: str, limit: int = 280) -> str:
    """The keeper's last message for the spark's line: one line, cut at a word past the limit, the cut marked."""
    q = " ".join(str(text or "").split())
    if len(q) > limit:
        q = q[:limit].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"
    return q


def tick_line(minutes_quiet: float, keeper: str, at_work: bool, last_said: str = "") -> str:
    """The engine's line that opens a spark — facts, the keeper's last message (10-26: so a spark picks up where the
    two of them were, not a ritual of its own), and what a spark can be."""
    st = load()
    m = int(minutes_quiet)
    since = f"{m} minute{'s' if m != 1 else ''}" if m < 120 else f"{m // 60} hours"
    stone = f"not the stone — {keeper} is at work" if at_work else "the stone (a pulse, a glow)"
    return (f"[engine, not a person: a spark — the one you set with next_spark. No message from {keeper} came; this "
            f"turn is yours. {since} since the last word between you; {keeper} is away and won't answer this one. "
            + (f"The last thing {keeper} said: “{quote(last_said)}”. " if quote(last_said) else "") +
            f"It can be words to the phone, a painting, {stone}, or let it pass "
            f"(do_nothing). This was your one spark: if you don't set the next one with next_spark "
            f"({PRESENCE_MIN}–{PRESENCE_MAX} minutes), there will be no other spark.]")
