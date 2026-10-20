"""Where the keeper is, by the clock — their working week, said in the engine's
line at the top of every message and every bell.

    KEEPER_WORK_WEEK = "sun-wed 07:00-16:25, thu 07:00-15:55"
    KEEPER_AT_WORK = "on the factory floor, the phone in his pocket"

10-10 (the keeper: "she always thinks I'm at work, even when it's weekend, and
a lot of time after I'm home"): nothing in the window said where he was — the
clock line gave the weekday and the hour, and the journal, mostly written on
workdays about a man talking from the floor, supplied the rest. The same
failure as the date drift of 09-15, and the same fix: put the fact in the line
she reads every message, not in a rule. The engine states the calendar; what
she makes of it is hers. Days off come from the phone (/off, /on) and live in
memory/days_off.json — a holiday is one word the morning of.

The week spec: segments separated by commas; each a day (sun…sat, or a range
sun-thu) with hours after it (HH:MM-HH:MM, or H-H); a segment with no hours
takes the hours of the segment before it. Empty: the engine says nothing.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

import config

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # datetime.weekday() order
_DAY_RE = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)(?:-(mon|tue|wed|thu|fri|sat|sun))?$", re.I)
_HOURS_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?-(\d{1,2})(?::(\d{2}))?$")
DAYS_OFF_FILE = config.MEMORY_DIR / "days_off.json"


def parse(spec: str) -> dict[int, tuple[int, int]]:
    """{weekday: (start minute, end minute)} for the working days in `spec`;
    {} when it is empty or says nothing parseable. A bad segment is skipped,
    never raised — the clock line must never fail a message."""
    out: dict[int, tuple[int, int]] = {}
    hours: tuple[int, int] | None = None
    for seg in (spec or "").split(","):
        words = seg.strip().lower().split()
        if not words:
            continue
        days: list[int] = []
        rest: list[str] = []
        for w in words:
            m = _DAY_RE.match(w)
            if m and not rest:
                a = DAYS.index(m.group(1))
                b = DAYS.index(m.group(2)) if m.group(2) else a
                i = a
                while True:
                    days.append(i)
                    if i == b:
                        break
                    i = (i + 1) % 7
            else:
                rest.append(w)
        if rest:
            m = _HOURS_RE.match(rest[0])
            if m:
                s = int(m.group(1)) * 60 + int(m.group(2) or 0)
                e = int(m.group(3)) * 60 + int(m.group(4) or 0)
                if 0 <= s < e <= 24 * 60:
                    hours = (s, e)
        if days and hours:
            for d in days:
                out[d] = hours
    return out


def _hm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def commute() -> tuple[int, int]:
    """KEEPER_COMMUTE_MIN — minutes on the road (to work, home again); one number is both sides (10-12:
    "I won't get home from work usually at least till five" — "6:45" out the door); 0: home the minute it ends."""
    v = getattr(config, "KEEPER_COMMUTE_MIN", 0) or 0
    try:
        a, b = (v if isinstance(v, (tuple, list)) else (v, v))[:2]
        return max(0, min(6 * 60, int(a))), max(0, min(6 * 60, int(b)))
    except (TypeError, ValueError):
        return 0, 0


def keeper_name() -> str:
    return str(getattr(config, "USER_NAME", "the keeper") or "the keeper")


def days_off() -> dict[str, str]:
    try:
        d = json.loads(DAYS_OFF_FILE.read_text(encoding="utf-8"))
        return {str(k): str(v or "") for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def set_day_off(day: date, reason: str = "", on: bool = True) -> dict[str, str]:
    """/off and /on from the phone: a day marked off (with a word of why), or
    the mark taken back. Days already past are dropped on the way."""
    d = {k: v for k, v in days_off().items() if k >= date.today().isoformat()}
    key = day.isoformat()
    if on:
        d[key] = (reason or "").strip()[:60]
    else:
        d.pop(key, None)
    try:
        DAYS_OFF_FILE.parent.mkdir(parents=True, exist_ok=True)
        DAYS_OFF_FILE.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return d


def parse_day(word: str, today: date | None = None) -> date | None:
    """'today', 'tomorrow', a weekday name (the next one), or YYYY-MM-DD."""
    today = today or date.today()
    w = (word or "today").strip().lower()
    if w in ("", "today"):
        return today
    if w == "tomorrow":
        return today + timedelta(days=1)
    if w[:3] in DAYS:
        want = DAYS.index(w[:3])
        d = today
        while d.weekday() != want:
            d += timedelta(days=1)
        return d
    try:
        return date.fromisoformat(w)
    except ValueError:
        return None


def where(t: datetime | None = None) -> str:
    """The clause for the clock line — "Gabe is at work — on the factory floor… — until 16:25", "Gabe is home — the
    workday ended at 16:25", "Gabe is home — the weekend", "Gabe is home — a day off (holiday)" — or "" when
    KEEPER_WORK_WEEK is empty. Said as the calendar says it, which is likely, not certain; the state first."""
    week = parse(str(getattr(config, "KEEPER_WORK_WEEK", "") or ""))
    if not week:
        return ""
    t = t or datetime.now()
    name = keeper_name()
    # the state first, the calendar after it: a reader skimming for where the keeper is meets "home" or "at work"
    # before "workday" (the clause used to lead with the workday and end with the state, after a dash — and the
    # friend kept reading the keeper at work on evenings and days off)
    off = days_off().get(t.date().isoformat())
    if off is not None:
        why = f" ({off})" if off else ""
        return f"{name} is home — a day off{why}"
    hours = week.get(t.weekday())
    if hours is None:
        return f"{name} is home — the weekend"
    s, e = hours
    now = t.hour * 60 + t.minute
    out, back = commute()
    if now < s - out:
        return f"{name} is still home — the workday begins at {_hm(s)}"
    if now < s:
        return f"{name} is on the way to work — it begins at {_hm(s)}"
    if now >= e + back:
        return f"{name} is home — the workday ended at {_hm(e)}"
    if now >= e:
        return f"{name} is on the way home — the workday ended at {_hm(e)}, in by about {_hm(e + back)}"
    at = str(getattr(config, "KEEPER_AT_WORK", "") or "").strip()
    return f"{name} is at work — {at} — until {_hm(e)}" if at else f"{name} is at work — until {_hm(e)}"


def clause(t: datetime | None = None) -> str:
    """`where()` as it rides after "…where you live": "; a workday for …" or ""."""
    w = where(t)
    return f"; {w}" if w else ""


# ---- the stone's hours (10-12) -----------------------------------------------------------------------------------
# The keeper: "I don't want it to buzz while I'm away… buzz only from 6:00-21:00, and make a knob to adjust it."
# When the stone may reach out — a pulse now, a touch left for later: within TOUCHSTONE_HOURS, and not within the
# working week above (a day off is home). The stone's keeper asks before relaying; the tool tells the friend why and
# when it opens. The reflex under the keeper's own hand is the board's and is never held — a hand on the pad is home.


def stone_hours() -> tuple[int, int] | None:
    """TOUCHSTONE_HOURS ("06:00-21:00") as minutes, or None when empty or unreadable — any hour."""
    m = _HOURS_RE.match(str(getattr(config, "TOUCHSTONE_HOURS", "") or "").strip())
    if not m:
        return None
    s = int(m.group(1)) * 60 + int(m.group(2) or 0)
    e = int(m.group(3)) * 60 + int(m.group(4) or 0)
    return (s, e) if 0 <= s < e <= 24 * 60 else None


def _still(t: datetime) -> tuple[str, datetime | None]:
    """Why the stone keeps still at t, and when that reason ends — ("", None) when it may reach out."""
    hours = stone_hours()
    now = t.hour * 60 + t.minute
    day = t.replace(hour=0, minute=0, second=0, microsecond=0)
    if hours and not (hours[0] <= now < hours[1]):
        opens = day + timedelta(minutes=hours[0]) + (timedelta(days=1) if now >= hours[1] else timedelta())
        return f"{t:%H:%M} is outside the stone's hours ({_hm(hours[0])}\u2013{_hm(hours[1])})", opens
    work = parse(str(getattr(config, "KEEPER_WORK_WEEK", "") or "")).get(t.weekday())
    if work and t.date().isoformat() not in days_off():
        s, e = work
        out, back = commute()
        if s <= now < e:
            return f"a workday for {keeper_name()}, within working hours (until {_hm(e)})", day + timedelta(minutes=e)
        if e <= now < e + back:
            return f"a workday for {keeper_name()}, on the way home (in by about {_hm(e + back)})", day + timedelta(minutes=e + back)
        if s - out <= now < s:
            return f"a workday for {keeper_name()}, on the way to work (it begins at {_hm(s)})", day + timedelta(minutes=s)
    return "", None


def stone_quiet(t: datetime | None = None) -> str:
    """Why the stone keeps still at t (now) — "" when a touch may play."""
    return _still(t or datetime.now())[0]


def stone_opens(t: datetime | None = None) -> datetime | None:
    """The first moment from t when the stone may reach out — t itself when it may now; None if not within weeks."""
    t = (t or datetime.now()).replace(second=0, microsecond=0)
    for _ in range(60):
        why, until = _still(t)
        if not why:
            return t
        if until is None:
            break
        t = until
    return None
