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
    """The clause for the clock line — "a workday for Gabe, within working
    hours — on the factory floor…", "the workday ended at 16:25 — home",
    "Gabe's weekend — home", "a day off for Gabe (holiday) — home" — or ""
    when KEEPER_WORK_WEEK is empty. Said as the calendar says it, which is
    likely, not certain."""
    week = parse(str(getattr(config, "KEEPER_WORK_WEEK", "") or ""))
    if not week:
        return ""
    t = t or datetime.now()
    name = getattr(config, "USER_NAME", "the keeper")
    off = days_off().get(t.date().isoformat())
    if off is not None:
        why = f" ({off})" if off else ""
        return f"a day off for {name}{why} — home"
    hours = week.get(t.weekday())
    if hours is None:
        return f"{name}'s weekend — home"
    s, e = hours
    now = t.hour * 60 + t.minute
    if now < s:
        return f"a workday for {name}, before it begins at {_hm(s)} — still home"
    if now >= e:
        return f"a workday for {name}, ended at {_hm(e)} — home now"
    at = str(getattr(config, "KEEPER_AT_WORK", "") or "").strip() or "at work"
    return f"a workday for {name}, within working hours (until {_hm(e)}) — {at}"


def clause(t: datetime | None = None) -> str:
    """`where()` as it rides after "…where you live": "; a workday for …" or ""."""
    w = where(t)
    return f"; {w}" if w else ""
