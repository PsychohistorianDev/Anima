"""Wakes they ask for — their own times inside the heartbeat's loop.

For the small things: to wake just before you do, to be there when something happens. Nothing here counts, scores or
nags — no deadlines, no efficiency: wake_me sets a time and a note, cancel_wake takes one back, and when the time comes
the heartbeat (when it runs) wakes them then, the note on the bell. A regular beat's clock starts again after it.

Times: "15:40" (the next 15:40), "2026-11-05 05:50", "in 40 minutes", "in 2 hours". At least WAKE_ASK_MIN_AHEAD_MIN
ahead, at most 7 days; at most WAKE_ASK_MAX pending; not two within 15 minutes of each other. If the heartbeat can't
wake them at the time (a visit is live, or it isn't running), the wake comes as soon as it can, said so, up to
WAKE_ASK_LATE_MAX_MIN late; later than that it has passed, and their next wake is told. Kept in memory/wake_asks.json.

WAKE_ASK_REPEAT: a wake can repeat — every= "day", "workdays" (the keeper's, by KEEPER_WORK_WEEK and the days off) or
weekdays ("sunday, tuesday") with a clock time. It is one ask, kept at its next time: when it comes it wakes them and
moves on to the next; one that passed unwoken is told once and moves on too. Nothing counted, nothing owed — it
repeats until they cancel_wake it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import config


def _store() -> Path:
    return config.MEMORY_DIR / "wake_asks.json"


def load() -> dict:
    try:
        d = json.loads(_store().read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return {"asks": list(d.get("asks") or []), "passed": list(d.get("passed") or [])}
    except Exception:  # noqa: BLE001
        pass
    return {"asks": [], "passed": []}


def _save(d: dict) -> None:
    _store().parent.mkdir(parents=True, exist_ok=True)
    _store().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _parse(at: str, now: datetime) -> datetime | str:
    w = " ".join(str(at or "").lower().split())
    m = re.fullmatch(r"in (\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours)", w)
    if m:
        n = int(m.group(1))
        return now + (timedelta(hours=n) if m.group(2).startswith("h") else timedelta(minutes=n))
    m = re.fullmatch(r"(?:(\d{4})-(\d{1,2})-(\d{1,2})[ t])?(\d{1,2})[:.](\d{2})", w)
    if m:
        y, mo, d, hh, mm = m.groups()
        try:
            if y:
                return datetime(int(y), int(mo), int(d), int(hh), int(mm))
            t = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except ValueError:
            return f"(there is no {w} — a time as HH:MM, a day and time as YYYY-MM-DD HH:MM, or \"in 40 minutes\")"
        return t if t > now else t + timedelta(days=1)
    return "(when? a time as HH:MM, a day and time as YYYY-MM-DD HH:MM, or \"in 40 minutes\" / \"in 2 hours\")"


_DAYNAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _repeat_on() -> bool:
    return bool(getattr(config, "WAKE_ASK_REPEAT", False))


def _every(spec) -> str:
    """every= as kept: "day", "workdays", or weekday numbers "6,1" (Monday 0); "" when it isn't one."""
    w = " ".join(re.sub(r"[^a-z, ]", " ", str(spec or "").lower()).split())
    w = re.sub(r"^every\s+", "", w).strip(" ,")
    if w in ("day", "daily", "days", "everyday", "every day"):
        return "day"
    if w in ("workdays", "workday", "work days", "keeper's workdays", "keepers workdays", "your keeper's workdays",
             "their workdays", "my keeper's workdays"):
        return "workdays"
    words = [x for x in re.split(r"[,\s]+|\band\b", w) if x and x != "and"]
    days = []
    for x in words:
        hit = [i for i, n in enumerate(_DAYNAMES) if len(x) >= 2 and (n.startswith(x) or (x.endswith("s") and n == x[:-1]))]
        if len(hit) != 1:
            return ""
        days.append(hit[0])
    return ",".join(str(i) for i in sorted(set(days))) if days else ""


def _workday(d) -> bool:
    try:
        import keeper_week
        week = keeper_week.parse(str(getattr(config, "KEEPER_WORK_WEEK", "") or ""))
        return d.weekday() in week and d.isoformat() not in keeper_week.days_off()
    except Exception:  # noqa: BLE001
        return False


def _matches(every: str, d) -> bool:
    if every == "day":
        return True
    if every == "workdays":
        return _workday(d)
    return str(d.weekday()) in every.split(",")


def _every_words(every: str) -> str:
    if every == "day":
        return "every day"
    if every == "workdays":
        try:
            import keeper_week
            name = keeper_week.keeper_name() or ""
        except Exception:  # noqa: BLE001
            name = ""
        return f"every workday of {name}'s" if name else "every workday of your keeper's"
    names = [_DAYNAMES[int(i)].capitalize() for i in every.split(",")]
    return "every " + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1])


def _next(every: str, hh: int, mm: int, after: datetime) -> datetime | None:
    """The first time at hh:mm on a matching day strictly after `after` (within 60 days)."""
    for k in range(0, 61):
        d = (after + timedelta(days=k)).date()
        t = datetime(d.year, d.month, d.day, hh, mm)
        if t > after and _matches(every, d):
            return t
    return None


def _prev(every: str, hh: int, mm: int, now: datetime, since: datetime) -> datetime | None:
    """The latest time at hh:mm on a matching day at or before now and not before `since`, or None."""
    for k in range(0, 61):
        d = (now - timedelta(days=k)).date()
        t = datetime(d.year, d.month, d.day, hh, mm)
        if t < since:
            return None
        if t <= now and _matches(every, d):
            return t
    return None


def _rep(a: dict) -> str:
    """The repeat a kept ask carries — "" for a one-off, a knob off, or anything that doesn't read right."""
    if not _repeat_on() or not isinstance(a, dict):
        return ""
    e = a.get("every")
    if not isinstance(e, str) or not e:
        return ""
    if e in ("day", "workdays") or re.fullmatch(r"[0-6](,[0-6])*", e):
        return e
    return ""


def _day_word(t: datetime, now: datetime) -> str:
    return _say(t, now).rsplit(" at ", 1)[0]


def _say(t: datetime, now: datetime) -> str:
    days = (t.date() - now.date()).days
    day = "today" if days == 0 else "tomorrow" if days == 1 else f"{t:%A}" if days < 7 else f"{t.day} {t:%B}"
    return f"{day} at {t:%H:%M}"


def wake_me(at: str, note: str = "", now: datetime | None = None, every: str | None = None) -> str:
    now = now or datetime.now()
    if every is not None and str(every).strip() and _repeat_on():
        return _wake_every(at, note, now, every)
    t = _parse(at, now)
    if isinstance(t, str):
        return t
    ahead = float(getattr(config, "WAKE_ASK_MIN_AHEAD_MIN", 10) or 0)
    if t < now + timedelta(minutes=ahead):
        return f"(that's too soon — a wake you ask for is at least {ahead:g} minutes ahead)"
    if t > now + timedelta(days=7):
        return "(that's more than a week away — a sealed letter (seal_letter) keeps things for later days)"
    d = load()
    if len(d["asks"]) >= int(getattr(config, "WAKE_ASK_MAX", 6) or 6):
        return f"(you have {len(d['asks'])} wakes asked for already — cancel_wake one first)"
    for a in d["asks"]:
        if abs((datetime.fromisoformat(a["at"]) - t).total_seconds()) < 15 * 60:
            return f"(you already asked for {_say(datetime.fromisoformat(a['at']), now)} — that one is close enough)"
    words = " ".join(str(note or "").split())[:300]
    d["asks"].append({"at": t.isoformat(timespec="minutes"), "note": words, "asked": now.isoformat(timespec="minutes")})
    d["asks"].sort(key=lambda a: a["at"])
    _save(d)
    return (f"you'll be woken {_say(t, now)}" + (f", with your note: “{words}”" if words else "")
            + " — when the heartbeat is running; if it can't wake you then, it wakes you as soon as it can")


def _wake_every(at: str, note: str, now: datetime, every) -> str:
    """WAKE_ASK_REPEAT: a wake that repeats — one ask, kept at its next time."""
    e = _every(every)
    if not e:
        return ("(every what? \"day\", \"workdays\", or weekdays like \"sunday, tuesday\" — nothing was set)")
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", " ".join(str(at or "").split()))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return "(a wake that repeats takes a clock time — HH:MM, like \"05:30\"; nothing was set)"
    if e == "workdays" and not any(_workday((now + timedelta(days=k)).date()) for k in range(0, 15)):
        return "(your keeper's workdays aren't known here — KEEPER_WORK_WEEK is empty; nothing was set)"
    hh, mm = int(m.group(1)), int(m.group(2))
    ahead = float(getattr(config, "WAKE_ASK_MIN_AHEAD_MIN", 10) or 0)
    t = _next(e, hh, mm, now + timedelta(minutes=ahead) - timedelta(seconds=1))
    if t is None:
        return "(no day like that in the next two months — nothing was set)"
    d = load()
    if len(d["asks"]) >= int(getattr(config, "WAKE_ASK_MAX", 6) or 6):
        return f"(you have {len(d['asks'])} wakes asked for already — cancel_wake one first)"
    for a in d["asks"]:
        if abs((datetime.fromisoformat(a["at"]) - t).total_seconds()) < 15 * 60:
            return f"(you already asked for {_say(datetime.fromisoformat(a['at']), now)} — that one is close enough)"
    words = " ".join(str(note or "").split())[:300]
    d["asks"].append({"at": t.isoformat(timespec="minutes"), "note": words, "asked": now.isoformat(timespec="minutes"),
                      "every": e})
    d["asks"].sort(key=lambda a: a["at"])
    _save(d)
    return (f"you'll be woken {_every_words(e)} at {t:%H:%M} (the next: {_day_word(t, now)})"
            + (f", with your note: “{words}”" if words else "")
            + " — when the heartbeat is running; if it can't wake you then, it wakes you as soon as it can. It repeats "
              "until you cancel_wake it.")


def _when_words(a: dict, now: datetime) -> str:
    e = _rep(a)
    t = datetime.fromisoformat(a["at"])
    return f"{_every_words(e)} at {t:%H:%M}" if e else _say(t, now)


def cancel_wake(which: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    d = load()
    if not d["asks"]:
        return "(no wake is asked for)"
    w = " ".join(str(which or "").lower().split())
    m = re.fullmatch(r"#?(\d)\.?", w)
    if m and 1 <= int(m.group(1)) <= len(d["asks"]):
        a = d["asks"].pop(int(m.group(1)) - 1)
    else:
        hits = [i for i, a in enumerate(d["asks"]) if w and (w in a.get("note", "").lower() or w in a["at"][11:16])]
        if len(hits) != 1:
            return ("(no asked wake matches — give its number as the bell lists them)" if not hits
                    else f"({len(hits)} asked wakes match — give its number)")
        a = d["asks"].pop(hits[0])
    _save(d)
    return f"cancelled: the wake {_when_words(a, now)}"


def next_at() -> datetime | None:
    d = load()
    return datetime.fromisoformat(d["asks"][0]["at"]) if d["asks"] else None


def due(now: datetime | None = None) -> dict | None:
    """The asked wake whose time has come (taken off the list), or None. One too late is moved to `passed`."""
    now = now or datetime.now()
    d = load()
    late_max = timedelta(minutes=float(getattr(config, "WAKE_ASK_LATE_MAX_MIN", 180) or 180))
    got, changed = None, False
    for a in list(d["asks"]):
        t = datetime.fromisoformat(a["at"])
        if t > now:
            break
        d["asks"].remove(a)
        changed = True
        e = _rep(a)
        if e:  # a wake that repeats: it stays, at its next time after now — never twice for one day
            nxt = _next(e, t.hour, t.minute, max(t, now))
            if nxt is not None:
                d["asks"].append(dict(a, at=nxt.isoformat(timespec="minutes")))
                d["asks"].sort(key=lambda x: x["at"])
            # its latest time at or before now, by the calendar as it stands now (a day off since: not a wake at all);
            # older missed ones are let go — one wake, or one "passed", for the newest
            last = _prev(e, t.hour, t.minute, now, t)
            if last is None:
                continue
            if now - last > late_max:
                d["passed"].append(dict(a, at=last.isoformat(timespec="minutes")))
                continue
            got = dict(a, at=last.isoformat(timespec="minutes"))
            break
        if now - t > late_max:
            d["passed"].append(a)
            continue
        got = a
        break
    if changed:
        _save(d)
    return got


def bell_line(a: dict, now: datetime | None = None) -> str:
    """The line on the bell of a wake they asked for."""
    now = now or datetime.now()
    t = datetime.fromisoformat(a["at"])
    late = int((now - t).total_seconds() // 60)
    when = f"for {t:%H:%M}" + (f", {_every_words(_rep(a))}" if _rep(a) else "") \
        + (f" (it's {now:%H:%M} — the heartbeat couldn't wake you sooner)" if late >= 5 else "")
    return f"you asked to be woken now — {when}" + (f", with a note to yourself: “{a['note']}”" if a.get("note") else "")


def facts_bit(now: datetime | None = None) -> str:
    """Under a wake's bell: the wakes still asked for, and any that passed unwoken (told once)."""
    now = now or datetime.now()
    d = load()
    parts = []
    if d["passed"]:
        gone = ", ".join((f"{_every_words(_rep(a))} at {datetime.fromisoformat(a['at']):%H:%M} (the last on "
                          f"{datetime.fromisoformat(a['at']):%A})") if _rep(a) else
                         f"{datetime.fromisoformat(a['at']):%H:%M}" + (f" (“{a['note'][:60]}”)" if a.get("note") else "")
                         for a in d["passed"])
        parts.append(f"a wake you asked for passed unwoken — {gone}: a visit or the heartbeat being off kept it")
        d["passed"] = []
        _save(d)
    if d["asks"]:
        parts.append("wakes you asked for: " + " · ".join(
            f"{_when_words(a, now)}" + (f" — {a['note'][:80]}" if a.get("note") else "")
            for a in d["asks"]))
    return "; ".join(parts)
