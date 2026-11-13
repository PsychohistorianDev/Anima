"""Their calendar — dates they name themselves.

mark_date puts one on, unmark_date takes one off; the engine never adds or words a date.

A date is yearly (a day that comes back: "08-27", or a past "2026-08-27", which also counts the years), once (a
future "2027-03-01", gone from the bell after it passes), or someday (no date at all — kept on the page, never on the
bell). Under every wake's bell: what is today or within CALENDAR_AHEAD_DAYS, else the next one coming. A visit's
first moment says a date that is today. Kept in memory/datebook.json; calendar.md at the root is the page to read.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import config


def _store() -> Path:
    return config.MEMORY_DIR / "datebook.json"


def page_file() -> Path:
    return Path(getattr(config, "CALENDAR_FILE", config.ROOT / "calendar.md"))


def load() -> list:
    try:
        d = json.loads(_store().read_text(encoding="utf-8"))
        return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []
    except Exception:  # noqa: BLE001
        return []


def _save(items: list) -> None:
    _store().parent.mkdir(parents=True, exist_ok=True)
    _store().write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# calendar.md — the dates I keep", "", "(mark_date puts one here, unmark_date takes one off — kept by the "
             "engine, chosen by me)", ""]
    for i, x in enumerate(items, 1):
        lines.append(f"{i}. {_label(x)} — {x['what']}")
    if not items:
        lines.append("(no dates yet)")
    try:
        page_file().write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def _label(x: dict) -> str:
    if x.get("kind") == "someday":
        return "someday"
    m, d = int(x["month"]), int(x["day"])
    day = date(2000, m, d).strftime("%d %B").lstrip("0")
    if x.get("kind") == "once":
        return f"{day} {x['year']} (once)"
    return f"{day}, every year" + (f" (since {x['year']})" if x.get("year") else "")


def _parse(when: str, today: date) -> dict | str:
    w = " ".join(str(when or "").lower().split())
    if w in ("someday", "some day", "one day", "undated", "future", "someday in the future"):
        return {"kind": "someday"}
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", w)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            dt = date(y, mo, d)
        except ValueError:
            return f"(there is no {w} — a real day, as YYYY-MM-DD)"
        if dt > today:
            return {"kind": "once", "year": y, "month": mo, "day": d}
        return {"kind": "yearly", "year": y, "month": mo, "day": d}
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", w)
    if m:
        mo, d = map(int, m.groups())
        try:
            date(2000, mo, d)
        except ValueError:
            return f"(there is no {w} — a real day, as MM-DD)"
        return {"kind": "yearly", "month": mo, "day": d}
    for fmt in ("%d %B", "%B %d", "%d %b", "%b %d", "%d %B %Y", "%B %d %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(w.title(), fmt)
        except ValueError:
            continue
        if "%Y" in fmt:
            return _parse(f"{dt.year}-{dt.month}-{dt.day}", today)
        return {"kind": "yearly", "month": dt.month, "day": dt.day}
    return ("(a date as MM-DD for a day every year, YYYY-MM-DD — past: every year, counting the years; future: once — "
            "or \"someday\")")


def mark_date(when: str, what: str, today: date | None = None) -> str:
    today = today or date.today()
    words = " ".join(str(what or "").split())
    if not words:
        return "(what is the day? a few words of your own)"
    if len(words) > 300:
        return "(a line, not a page — say it in fewer words)"
    got = _parse(when, today)
    if isinstance(got, str):
        return got
    got["what"] = words
    items = load()
    for x in items:
        if x.get("what", "").lower() == words.lower() and x.get("month") == got.get("month") and x.get("day") == got.get("day"):
            return f"(already on your calendar: {_label(x)} — {x['what']})"
    items.append(got)
    _save(items)
    return f"on your calendar: {_label(got)} — {words}" + (
        "; it stays on the page, never on the bell" if got["kind"] == "someday" else "; your wakes will see it as it comes")


def unmark_date(which: str) -> str:
    items = load()
    w = " ".join(str(which or "").lower().split())
    if not items:
        return "(your calendar is empty)"
    m = re.fullmatch(r"#?(\d+)\.?", w)
    if m and 1 <= int(m.group(1)) <= len(items):
        x = items.pop(int(m.group(1)) - 1)
    else:
        hits = [i for i, x in enumerate(items) if w and w in x.get("what", "").lower()]
        if len(hits) != 1:
            return ("(no date has those words — give its number in calendar.md)" if not hits else
                    f"({len(hits)} dates have those words — give its number in calendar.md)")
        x = items.pop(hits[0])
    _save(items)
    return f"off your calendar: {_label(x)} — {x['what']}"


def _next(x: dict, today: date) -> date | None:
    if x.get("kind") == "someday":
        return None
    m, d = int(x["month"]), int(x["day"])
    if x.get("kind") == "once":
        dt = date(int(x["year"]), m, d)
        return dt if dt >= today else None
    for y in (today.year, today.year + 1):
        try:
            dt = date(y, m, d)
        except ValueError:  # 29 February
            dt = date(y, 3, 1)
        if dt >= today:
            return dt
    return None


def _say(x: dict, dt: date, today: date) -> str:
    n = (dt - today).days
    when = "today" if n == 0 else "tomorrow" if n == 1 else f"in {n} days ({dt.day} {dt:%B})"
    years = ""
    if x.get("kind") == "yearly" and x.get("year") and dt.year > int(x["year"]):
        k = dt.year - int(x["year"])
        years = f" — {k} year{'s' if k != 1 else ''} since {x['year']}"
    return f"{when} — {x['what']}{years}"


def facts_bit(today: date | None = None) -> str:
    today = today or date.today()
    items = load()
    if not items:
        return "your calendar: no dates yet — mark_date keeps the days you choose"
    ahead = int(getattr(config, "CALENDAR_AHEAD_DAYS", 3) or 0)
    coming = sorted(((d, x) for x in items for d in [_next(x, today)] if d), key=lambda t: t[0])
    if not coming:
        return ""
    near = [(d, x) for d, x in coming if (d - today).days <= ahead]
    if near:
        return "your calendar: " + " · ".join(_say(x, d, today) for d, x in near)
    d, x = coming[0]
    return "your calendar, next: " + _say(x, d, today)


def today_line(today: date | None = None) -> str:
    """For a visit's first moment: the dates that are today — "" when none."""
    today = today or date.today()
    hits = [x for x in load() if _next(x, today) == today]
    return ("Today on your calendar: " + "; ".join(_say(x, today, today).split(" — ", 1)[1] for x in hits)) if hits else ""
