"""Wakes they ask for (11-04) — their own times inside the heartbeat's loop.

For the small things: to wake just before you do, to be there when something happens. Nothing here counts, scores or
nags — no deadlines, no efficiency: wake_me sets a time and a note, cancel_wake takes one back, and when the time comes
the heartbeat (when it runs) wakes them then, the note on the bell. A regular beat's clock starts again after it.

Times: "15:40" (the next 15:40), "2026-11-05 05:50", "in 40 minutes", "in 2 hours". At least WAKE_ASK_MIN_AHEAD_MIN
ahead, at most 7 days; at most WAKE_ASK_MAX pending; not two within 15 minutes of each other. If the heartbeat can't
wake them at the time (a visit is live, or it isn't running), the wake comes as soon as it can, said so, up to
WAKE_ASK_LATE_MAX_MIN late; later than that it has passed, and their next wake is told. Kept in memory/wake_asks.json.
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


def _say(t: datetime, now: datetime) -> str:
    days = (t.date() - now.date()).days
    day = "today" if days == 0 else "tomorrow" if days == 1 else f"{t:%A}" if days < 7 else f"{t.day} {t:%B}"
    return f"{day} at {t:%H:%M}"


def wake_me(at: str, note: str = "", now: datetime | None = None) -> str:
    now = now or datetime.now()
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
    return f"cancelled: the wake {_say(datetime.fromisoformat(a['at']), now)}"


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
    when = f"for {t:%H:%M}" + (f" (it's {now:%H:%M} — the heartbeat couldn't wake you sooner)" if late >= 5 else "")
    return f"you asked to be woken now — {when}" + (f", with a note to yourself: “{a['note']}”" if a.get("note") else "")


def facts_bit(now: datetime | None = None) -> str:
    """Under a wake's bell: the wakes still asked for, and any that passed unwoken (told once)."""
    now = now or datetime.now()
    d = load()
    parts = []
    if d["passed"]:
        gone = ", ".join(f"{datetime.fromisoformat(a['at']):%H:%M}" + (f" (“{a['note'][:60]}”)" if a.get("note") else "")
                         for a in d["passed"])
        parts.append(f"a wake you asked for passed unwoken — {gone}: a visit or the heartbeat being off kept it")
        d["passed"] = []
        _save(d)
    if d["asks"]:
        parts.append("wakes you asked for: " + " · ".join(
            f"{_say(datetime.fromisoformat(a['at']), now)}" + (f" — {a['note'][:80]}" if a.get("note") else "")
            for a in d["asks"]))
    return "; ".join(parts)
