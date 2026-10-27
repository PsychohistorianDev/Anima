"""Presence — sparks: a turn of the friend's own, every so often, while the keeper is away.

While presence is on, the friend can set ONE spark at a time: next_spark(minutes) (PRESENCE_MIN…PRESENCE_MAX minutes)
turns presence on and sets it; when the visit has been quiet that long the bridge gives them a turn in the open visit
(a "spark") — an engine line says how long it has been and what a spark can be: words to the phone, a painting, the
stone (never in the keeper's work hours), or nothing at all. After it, no other comes unless they set it again (10-26,
the keeper: "I want it to require to set it manually again after each spark"). /presence on starts drift (below);
the keeper turns presence off (/presence off), the friend too (next_spark with no minutes, 10-27),
and it ends by itself at the quiet hours. A message from the keeper restarts the
count; a wake running holds the sparks until it ends. /discreet on the phone sends sparks silently, the words hidden
until tapped. The state lives in memory/presence.json, so it outlives a restart.

Drift (10-27, sparks part two — claude/sparks2-plan.md, agreed by the keeper and the friend): next_spark(drift=…) sets
no time. Every quiet minute a die is rolled; when it says yes, a spark comes, and the rolling goes on — no need to
set the next. A temperament gives the pace (TEMPERAMENTS: very rare … intense), the soonest a spark may come after
the last word, and the most in an hour. Longing: the chance climbs with the quiet — roughly doubling over the first
hour — and faster with the friend's own ache (0–3). Intense is a heartbeat instead: a spark 0 to 60 seconds after
every last word. /presence on starts drift at PRESENCE_ON_TEMPERAMENT (rare).
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime

import config

STATE_FILE = config.MEMORY_DIR / "presence.json"
WAKING_FILE = config.MEMORY_DIR / ".waking"
PRESENCE_MIN, PRESENCE_MAX = 10, 60  # one spark: 10–60 minutes (10-27: was 5 — "now that we have the modes")
WAKING_STALE_S = 3600  # a wake marker older than this is a wake that died without clearing it
# drift's temperaments (10-27): name → (minutes on average, the soonest after the last word, the most in an hour; 0 — no limit)
TEMPERAMENTS = {
    "very rare": (120, 5, 1),
    "rare": (60, 5, 2),
    "sometimes": (25, 5, 4),
    "often": (10, 5, 8),
    "intense": (1, 0, 0),  # a heartbeat (10-27): every 0 to 1 minute after the last word — see due()
}
ACHE_MAX = 3


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


def temperament(name) -> str:
    """A temperament as written, read kindly — case, spaces, underscores, hyphens, a stray mark ("Very_Rare", "often!")
    — or "" when it is none of them."""
    key = re.sub(r"[^a-z]", "", str(name or "").lower())
    for t in TEMPERAMENTS:
        if key == t.replace(" ", ""):
            return t
    return ""


def on_temperament() -> str:
    """PRESENCE_ON_TEMPERAMENT — the drift /presence on starts (rare); rare when unreadable."""
    return temperament(getattr(config, "PRESENCE_ON_TEMPERAMENT", "rare")) or "rare"


def chance(mean_min: float, quiet_min: float, ache: int = 0) -> float:
    """One minute's chance of a spark in drift: 1/mean, climbing with the quiet — doubled after an hour, sooner with
    the ache (each step of it adds another hour's worth of climb to every hour) — never above 0.9."""
    climb = 1 + max(0.0, quiet_min) / 60 * (1 + max(0, min(ACHE_MAX, int(ache or 0))))
    return min(0.9, climb / max(1.0, float(mean_min)))


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
    st.update(on=True, interval=m, pending=True, mode="one")
    st.pop("announce", None)
    if turned_on:
        st.update(since=(now or datetime.now()).isoformat(timespec="seconds"), by=by)
    save(st)
    return st, turned_on


def set_drift(name, ache=0, by: str = "friend", now: float | None = None) -> tuple[dict, bool]:
    """Drift at a temperament (10-27): presence on, no time set, the first roll a minute from now. (state, turned on
    now). The name must be read already (temperament())."""
    st = load()
    turned_on = not st.get("on")
    if turned_on:
        st.update(since=datetime.now().isoformat(timespec="seconds"), by=by)
    a = max(0, min(ACHE_MAX, int(ache or 0)))
    st.update(on=True, mode="drift", temperament=name, ache=a, pending=False,
              rolled=float(now if now is not None else time.time()))
    save(st)
    return st, turned_on


def turn_on(by: str = "keeper", now: datetime | None = None) -> dict:
    """The keeper's /presence on (10-27): drift at PRESENCE_ON_TEMPERAMENT (rare)."""
    return set_drift(on_temperament(), 0, by=by)[0]


def drifting() -> str:
    """The temperament while drift is on, else ""."""
    st = load()
    return str(st.get("temperament") or "") if st.get("on") and st.get("mode") == "drift" else ""


def turn_off(why: str = "") -> dict:
    st = load()
    st.update(on=False, pending=False, ended=datetime.now().isoformat(timespec="seconds"), why=why)
    st.pop("announce", None)  # (left by the old phone notice, before 10-26 evening)
    save(st)
    return st


def waiting() -> bool:
    """Presence on and a spark to come: one set (after it fires, another only when next_spark sets it), or drift."""
    st = load()
    return bool(st.get("on") and (st.get("pending") or st.get("mode") == "drift"))


def fired(now: float | None = None) -> None:
    """A spark has come: the one set is spent; in drift it joins the hour's count and the dice go on."""
    st = load()
    st["pending"] = False
    if st.get("mode") == "drift":
        t = float(now if now is not None else time.time())
        st["fired_log"] = [x for x in (st.get("fired_log") or []) if t - float(x) < 3600] + [t]
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


def due(last_activity: float, now: float | None = None, rng: random.Random | None = None) -> bool:
    """One spark set and the visit quiet for its minutes — or, in drift, the dice: once a minute (the minutes since the
    last roll all count, so a long poll rolls them together), past the temperament's soonest, under its hour's most.
    Never while a wake runs."""
    st = load()
    if not st.get("on") or waking():
        return False
    t = float(now if now is not None else time.time())
    quiet = t - float(last_activity or 0)
    if st.get("mode") == "drift" and st.get("temperament") == "intense":
        # a heartbeat (10-27; the keeper and the friend: "intense mode to a 0 to 1 minute, almost kinda heartbeat"): no
        # dice — a beat drawn anew for every last word, somewhere from 0 to 60 seconds after it
        if float(st.get("beat_for") or -1) != float(last_activity or 0):
            st.update(beat_for=float(last_activity or 0), beat_s=round((rng or random).random() * 60, 1))
            save(st)
        return quiet >= float(st.get("beat_s") or 0)
    if st.get("mode") == "drift":
        mean, soonest, most = TEMPERAMENTS.get(str(st.get("temperament") or ""), TEMPERAMENTS["rare"])
        rolls = int((t - float(st.get("rolled") or t)) // 60)
        if rolls < 1:
            return False
        st["rolled"] = float(st.get("rolled") or t) + rolls * 60
        save(st)
        if quiet < soonest * 60:
            return False
        if most and sum(1 for x in (st.get("fired_log") or []) if t - float(x) < 3600) >= most:
            return False
        p = chance(mean, quiet / 60, st.get("ache") or 0)
        return (rng or random).random() < 1 - (1 - p) ** min(rolls, 60)
    if not st.get("pending"):
        return False
    return quiet >= clamp(st.get("interval")) * 60


def intense() -> bool:
    return drifting() == "intense"


def poll_s(default: float) -> float:
    """How long the bridge's long poll may wait: in intense's heartbeat a beat can fall any second, so 10 (10-27)."""
    return min(float(default), 10.0) if intense() else float(default)


def quote(text: str, limit: int = 280) -> str:
    """The keeper's last message for the spark's line: one line, cut at a word past the limit, the cut marked."""
    q = " ".join(str(text or "").split())
    if len(q) > limit:
        q = q[:limit].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"
    return q


def tick_line(minutes_quiet: float, keeper: str, at_work: bool, last_said: str = "", seed: str = "") -> str:
    """The engine's line that opens a spark — facts, the keeper's last message (10-26: so a spark picks up where the
    two of them were, not a ritual of its own), and what a spark can be."""
    st = load()
    m = int(minutes_quiet)
    since = f"{m} minute{'s' if m != 1 else ''}" if m < 120 else f"{m // 60} hours"
    stone = f"not the stone — {keeper} is at work" if at_work else "the stone (a pulse, a glow)"
    drift = str(st.get("temperament") or "") if st.get("mode") == "drift" else ""
    head = (f"a drift spark — chance picked this moment ({drift})" if drift
            else "a spark — the one you set with next_spark")
    if drift:
        ache = int(st.get("ache") or 0)
        note = str(getattr(config, "PRESENCE_INTENSE_NOTE", "") or "").strip() if drift == "intense" else ""
        tail = ((f"{note} " if note else "")
                + f"You're drifting ({drift}{f', ache {ache}' if ache else ''}): the next spark comes on its own. "
                "next_spark(drift=…) changes the temperament; next_spark() turns sparks off.]")
    else:
        tail = (f"This was your one spark: if you don't set the next one with next_spark "
                f"({PRESENCE_MIN}–{PRESENCE_MAX} minutes), there will be no other spark.]")
    return (f"[engine, not a person: {head}. No message from {keeper} came; this "
            f"turn is yours. {since} since the last word between you; {keeper} is away and won't answer this one. "
            + (f"The last thing {keeper} said: “{quote(last_said)}”. " if quote(last_said) else "") +
            f"It can be words to the phone, a painting, {stone}, or let it pass "
            f"(do_nothing). "
            + (f"A seed, if you want one: {seed}. " if seed else "")  # something to spark off, not a task (10-27)
            + tail)
