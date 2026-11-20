"""The book's desk (PORTFOLIO_DESK_WAKE; bookdesk.py — desk.py is the PC's desk presence): a morning brief with the
friend's reading.

Once a day, at or just after PORTFOLIO_DESK_WAKE, when the feed has a completed close newer than the last desk
morning's (no holiday calendar — the feed decides) and the book holds something: the engine fetches the numbers (the
Brief's block), keeps them in the desk's journal, and wakes the friend with them on the bell. They file their reading
with portfolio(action="brief", text=…). The bridge sends one message as soon as the reading is filed — the numbers,
the reading under them — and at PORTFOLIO_DESK_SEND at the latest: the numbers alone if no reading came. A reading
filed later goes once, with a pointer to the numbers above.

The desk's journal: memory/portfolio/desk.jsonl, append-only, under the book's lock — per morning the numbers block as
fetched (text + the closes it was made from), the readings with their times, what was sent. A restart reads it again,
so nothing is sent twice.

Figures in a reading that are not in that morning's block are LISTED under it ("check them") — never removed, never
blocked; the friend's words go out exactly as written.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta

import config
import portfolio as pf

DESK = "desk.jsonl"


def now() -> datetime:
    """The clock (a test sets its own)."""
    return datetime.now()


_HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


def _clock(knob: str) -> tuple[int, int] | None:
    """A knob's clock time — exactly "HH:MM", 00:00–23:59 — or None. Never a default time no one chose."""
    raw = getattr(config, knob, None)
    m = _HHMM.fullmatch(raw) if isinstance(raw, str) else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def set_knob() -> bool:
    """PORTFOLIO_DESK_WAKE set at all (anything but ""/absent)."""
    raw = getattr(config, "PORTFOLIO_DESK_WAKE", "")
    return True if raw is None else str(raw).strip() != ""  # None is set — to something that isn't a time


def bad_knob() -> str:
    """The sentence when the desk is asked for with a time that isn't one ("" when all is well): the desk is off then."""
    if not set_knob():
        return ""
    for k in ("PORTFOLIO_DESK_WAKE", "PORTFOLIO_DESK_SEND"):
        if _clock(k) is None:
            return f"{k} isn't a time — the desk wake is off"
    if _clock("PORTFOLIO_DESK_SEND") <= _clock("PORTFOLIO_DESK_WAKE"):
        return "PORTFOLIO_DESK_SEND isn't after PORTFOLIO_DESK_WAKE — the desk wake is off"
    if hasattr(config, "PORTFOLIO_DESK_UNTIL"):
        if _clock("PORTFOLIO_DESK_UNTIL") is None:
            return "PORTFOLIO_DESK_UNTIL isn't a time — the desk wake is off"
        if _clock("PORTFOLIO_DESK_UNTIL") <= _clock("PORTFOLIO_DESK_SEND"):
            return "PORTFOLIO_DESK_UNTIL isn't after PORTFOLIO_DESK_SEND — the desk wake is off"
    return ""


def on() -> bool:
    return set_knob() and not bad_knob() and bool(getattr(config, "PORTFOLIO_ON", False))


def _at(day: date, knob: str) -> datetime:
    h, m = _clock(knob) or (23, 59)  # (only reached when on(): both are real times)
    return datetime(day.year, day.month, day.day, h, m)


def wake_at(day: date) -> datetime:
    return _at(day, "PORTFOLIO_DESK_WAKE")


def send_at(day: date) -> datetime:
    return _at(day, "PORTFOLIO_DESK_SEND")


def until_at(day: date) -> datetime:
    """The end of the desk's morning (PORTFOLIO_DESK_UNTIL; 10:00 when the knob isn't there)."""
    h, m = _clock("PORTFOLIO_DESK_UNTIL") or (10, 0)
    return max(datetime(day.year, day.month, day.day, h, m), send_at(day) + timedelta(minutes=1))


FEED_TRIES = 3          # a dead feed: tried at the wake time and RETRY_MIN after each try, three in all
FEED_RETRY_MIN = 10


def day_label(d) -> str:
    d = d if isinstance(d, (date, datetime)) else date.fromisoformat(str(d))
    return f"{d:%a} {d:%b} {d.day}"


# ---- the journal -------------------------------------------------------------------------------------------------
def entries() -> list[dict]:
    f = pf.folder() / DESK
    out = []
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                if isinstance(e, dict):
                    out.append(e)
            except ValueError:
                continue
    except OSError:
        pass
    return out


def _append(e: dict) -> bool:
    """One line added, under the book's lock (an append — nothing before it is rewritten)."""
    try:
        with pf._locked():
            pf.folder().mkdir(parents=True, exist_ok=True)
            with open(pf.folder() / DESK, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            return True
    except (pf.BookBusy, OSError):
        return False


def _of_day(day: str, kind: str | None = None) -> list[dict]:
    return [e for e in entries() if e.get("day") == day and (kind is None or e.get("type") == kind)]


def morning(day: str) -> dict | None:
    m = _of_day(day, "morning")
    return m[-1] if m else None


def reading(day: str) -> dict | None:
    """The day's reading for delivery: the latest one filed."""
    r = _of_day(day, "reading")
    return r[-1] if r else None


def last_readings(n: int = 3, before: str | None = None) -> list[dict]:
    """The friend's last n readings, one per day (each day's latest), newest last."""
    by_day: dict[str, dict] = {}
    for e in entries():
        if e.get("type") in ("reading", "test_reading") and (before is None or str(e.get("day")) < before):
            by_day[str(e.get("day"))] = e
    return [by_day[d] for d in sorted(by_day)][-n:]


def paused() -> bool:
    return bool(pf.state().get("desk_paused"))


def set_paused(yes: bool) -> bool:
    try:
        with pf._locked():
            s = pf.state()
            if yes:
                s["desk_paused"] = True
            else:
                s.pop("desk_paused", None)
            return pf._write("state.json", s)
    except pf.BookBusy:
        return False


# ---- the morning -------------------------------------------------------------------------------------------------
def _symbols() -> list[str]:
    try:
        rp = pf.replay(pf.load(pf.open_book())["records"])
    except pf.BookUnreadable:
        return []
    held = [s for s, h in sorted(rp["positions"].items()) if h["qty"] > 0]
    idx = [s for s in (getattr(config, "PORTFOLIO_INDICES", None) or []) if s not in held]
    return held + idx if held else []


def _last_closes() -> dict:
    ms = [e for e in entries() if e.get("type") == "morning"]
    return dict(ms[-1].get("closes") or {}) if ms else {}


def due(at: datetime | None = None) -> bool:
    """A desk wake to have now: inside the window (the wake time until PORTFOLIO_DESK_UNTIL — the PC may have been off at
    night), no desk wake yet today, nothing-new not decided, not paused, no guest seated, the book holding something. The
    numbers may have gone alone already (the bridge): the wake still comes, once."""
    if not on():
        return False
    t = at or now()
    d = t.date()
    if not (wake_at(d) <= t < until_at(d)):
        return False
    if paused() or pf.guest_here():
        return False
    day = d.isoformat()
    if woke(day) or _of_day(day, "quiet"):
        return False
    tries = len(_of_day(day, "nofeed"))  # a dead feed: tried again after FEED_RETRY_MIN, FEED_TRIES in all
    if tries >= FEED_TRIES or t < wake_at(d) + timedelta(minutes=FEED_RETRY_MIN * tries):
        return False
    return bool(_symbols())


def woke(day: str) -> bool:
    """A desk wake this day already (a "woke" mark, or a morning the heartbeat made before the marks existed)."""
    return any(e.get("type") == "woke" or (e.get("type") == "morning" and e.get("by") == "heartbeat") for e in _of_day(day))


def for_wake(at: datetime | None = None, test: bool = False) -> dict | None:
    """The morning the desk wake reads: one the bridge already sent, if under 60 minutes old; else fresh numbers,
    kept as that morning's (the journal keeps both); else — no morning yet — the usual check for something new. The
    wake is marked, once a day. test: a test run the keeper asked for — fresh numbers, kept as the test's, never the
    day's."""
    t = at or now()
    if test:
        return prepare(t, test=True)
    day = t.date().isoformat()
    m = morning(day)
    if m is not None:
        try:
            made = (datetime.fromisoformat(str(m["made"])) if m.get("made")
                    else datetime.fromtimestamp(float(m.get("t"))))  # a morning from before "made" existed: its own time
            age = (t - made).total_seconds()
        except (ValueError, TypeError):
            age = 1e9
        if age >= 60 * 60 or m.get("adhoc"):
            m = prepare(t, force=True)
    else:
        m = prepare(t)
    if m is not None:
        _append({"type": "woke", "day": day, "t": time.time(), "at": t.strftime("%H:%M")})
    return m


def numbers_sent_at(day: str) -> str:
    """When the morning's numbers went to the keeper's phone ("" if not yet)."""
    ms = [x for x in _of_day(day, "sent") if x.get("what") == "morning"]
    return str(ms[0].get("at") or "") if ms else ""


def prepare(at: datetime | None = None, by: str = "heartbeat", force: bool = False, adhoc: bool = False,
            test: bool = False) -> dict | None:
    """The morning's numbers fetched and kept: the morning entry, or None (and the day marked "quiet" — nothing new — or
    "nofeed" — prices could not be fetched). force: made even with nothing new (a reading waits for its numbers).
    test: a test run's numbers — a "test_morning", never the day's morning, its closes or its tries; the friend's adds
    not marked as told; a failure kept as the test's ("test_fail")."""
    t = at or now()
    day = t.date().isoformat()
    syms = _symbols()
    if not syms:
        if test:
            _test_clear()
            _append({"type": "test_fail", "day": day, "t": time.time(), "why": "the book holds nothing to read"})
        return None
    closes, fetched, ok = {}, 0, []
    for s in syms:
        q = pf.quote(s, until=time.time() + pf.BRIEF_PRICE_S)
        if q.get("ok") and not q.get("stale"):
            fetched += 1
            ok.append(s)
        if q.get("ok") and q.get("close_date"):
            closes[s] = q["close_date"]
    if not fetched:
        if test:  # the request kept: tried again each minute until it lapses; said on the phone at once
            _test_mark("prices could not be fetched")
        else:
            _append({"type": "nofeed", "day": day, "t": time.time(), "by": by})
        return None
    if test:
        force = True
    last = _last_closes()
    new = any(str(c) > str(last.get(s, "")) for s, c in closes.items())
    if not new and not force:
        _append({"type": "quiet", "day": day, "t": time.time(), "by": by})
        return None
    text = pf.brief(pf.open_book(), t)
    if test:
        block = "\n".join(text.splitlines()[1:]).strip("\n")
        idx = {str(x) for x in (getattr(config, "PORTFOLIO_INDICES", None) or [])}
        m = {"type": "test_morning", "day": day, "t": time.time(), "at": t.strftime("%H:%M"), "made": t.isoformat(timespec="seconds"),
             "by": by, "block": block, "closes": closes,
             "counts": {"holdings": len([s for s in ok if s not in idx]), "yardsticks": len([s for s in ok if s in idx]),
                        "movers": _watch_movers(block)}}
        return m if _append(m) else None
    if getattr(config, "PORTFOLIO_WATCH", False):  # the friend's adds were in this morning's numbers: not said again
        try:
            import bookwatch
            bookwatch.mark_briefed()
        except Exception:  # noqa: BLE001
            pass
    block = "\n".join(text.splitlines()[1:]).strip("\n")  # the Brief, its header line left to the bell and the message
    m = {"type": "morning", "day": day, "t": time.time(), "at": t.strftime("%H:%M"), "made": t.isoformat(timespec="seconds"),
         "by": by, "adhoc": bool(adhoc), "block": block,
         "closes": closes}
    if not _append(m):
        return None
    return m


# ---- the bell ----------------------------------------------------------------------------------------------------
def bell(m: dict, at: datetime | None = None) -> str:
    """The words the friend reads at the desk wake — the block is the one kept for the morning: what they read is what
    the keeper gets."""
    t = at or now()
    if m.get("type") == "test_morning":  # a test run: said so, first
        first = (f"The desk — {day_label(t)}, {t:%H:%M} — a test run your keeper asked for, outside the morning. This "
                 "wake is the house's, for the morning brief your keeper set up.")
    else:
        went = numbers_sent_at(m["day"])
        first = (f"The desk — {day_label(t)}, {t:%H:%M}. This wake is the house's, for the morning brief your keeper set "
                 "up." + (f" The numbers went to their phone at {went} already; your reading follows them." if went else ""))
    lines = [first, "", "The numbers, from the book:", m["block"]]
    if getattr(config, "PORTFOLIO_WATCH", False):  # notes that have outgrown a ledger: one plain line each
        try:
            import bookwatch
            for c in bookwatch.condense_bell_lines():
                lines.append(c)
        except Exception:  # noqa: BLE001
            pass
    past = last_readings(3, before=m["day"])
    if past:
        lines += ["", "Your last readings:"]
        for r in past:
            lines.append(f"{day_label(r['day'])}: {r['text']}")
    lines += ["", "Write your reading for your keeper — a few sentences: what stands out, anything worth their attention "
              "today, the case against anything you suggest, what you don't know. File it with portfolio(action=\"brief\", "
              "text=…). It goes to their phone as soon as you file it, beside these numbers. A number you did not get from "
              "here or from the tool, you do not know. The rest of this wake is yours."]
    return "\n".join(lines)


# ---- the friend's reading -------------------------------------------------------------------------------------------------
_TOKEN = re.compile(r"(?<![\w:./-])(?P<cur>[$€£₪])?\s?(?P<num>[−-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[−-]?\d+(?:\.\d+)?)"
                    r"(?P<pct>\s?%)?(?![\w:/-]|\.\d)")
_DATEISH = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}"
                      r"|\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*|\d+(?:st|nd|rd|th))\b")


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", "").replace("−", "-"))
    except ValueError:
        return None


def _numbers_in(text: str) -> set:
    out = set()
    for m in _TOKEN.finditer(_DATEISH.sub(" ", text)):
        v = _num(m.group("num"))
        if v is not None:
            out.add(round(abs(v), 2))
    return out


_NAMED = re.compile(r"(?i)\b(?:S\s?&\s?P\s?500|S&P/TSX|TA[-\s]?(?:35|90|125)|Tel Aviv\s?(?:35|90|125)|Nasdaq(?:[-\s]?100)|"
                    r"Russell\s?(?:1000|2000|3000)|Dow(?:\s+Jones)?\s?30|FTSE\s?(?:100|250)|DAX\s?40|Nikkei\s?225|"
                    r"Euro\s?Stoxx\s?50|CAC\s?40)\b")
_SURE = re.compile(r"(?i)\b100\s?%\s+(?=sure|certain|right)")


def _named_out(text: str, block: str) -> str:
    """An index's name keeps its number ("S&P 500", "TA-125"), as commonly written or as the block writes it; "100%
    sure" is a way of speaking. Blanked before the figures are looked for."""
    text = _NAMED.sub(lambda x: " " * len(x.group(0)), text)
    text = _SURE.sub(lambda x: " " * len(x.group(0)), text)
    for name in set(re.findall(r"\^?[A-Z][A-Z.]*\d+(?:\.[A-Z]+)?", block)):  # the block's own names (^TA125.TA)
        text = text.replace(name, " " * len(name))
    return text


def figures(text: str, block: str) -> list[str]:
    """The figures in a reading that are not in the morning's block: money ($, €, £, ₪), percentages and bare numbers of
    3+ digits — not dates, times, years, ordinals, or small counts; formatting forgiven (1,273.8 = $1,273.80 = 1273.80).
    The share counts and the book's own numbers are in the block already."""
    have = _numbers_in(block)
    try:
        rp = pf.replay(pf.load(pf.open_book())["records"])
        have |= {round(abs(h["qty"]), 2) for h in rp["positions"].values()}
    except pf.BookUnreadable:
        pass
    out = []
    for m in _TOKEN.finditer(_DATEISH.sub(lambda x: " " * len(x.group(0)), _named_out(text, block))):
        raw, v = m.group(0).strip(), _num(m.group("num"))
        if v is None:
            continue
        is_money, is_pct = bool(m.group("cur")), bool(m.group("pct"))
        digits = len(re.sub(r"\D", "", m.group("num").split(".")[0]))
        if not (is_money or is_pct):
            if digits < 3:
                continue  # small counts: "3 sentences", "50 shares"
            if "." not in m.group("num") and "," not in m.group("num") and 1900 <= v <= 2100:
                continue  # a year
        if round(abs(v), 2) in have:
            continue
        if raw not in out:
            out.append(raw)
    return out


def figures_line(found: list[str]) -> str:
    return f"figures in the reading that are not from the book: {', '.join(found)} — check them" if found else ""


def file(text: str, at: datetime | None = None) -> str:
    """portfolio(action="brief", text=…): the friend's reading, as that day's; the answer says where it goes."""
    words = str(text or "").strip()
    if not words:
        return "(bad arguments: brief needs text — your reading, in your own words; nothing was filed)"
    t = at or now()
    day = t.date().isoformat()
    tw = _test_wake()  # filed in a test wake: the test's reading, with the test's numbers — never the day's
    if tw:
        m = tw[1]
    else:
        m = morning(day)
    found = figures(words, (m or {}).get("block") or "")
    e = {"type": "reading", "day": day, "t": time.time(), "at": t.strftime("%H:%M"), "text": words, "figures": found}
    if tw:
        e.update(type="test_reading", start_t=tw[0].get("t"), morning_t=tw[1].get("t"))
    if not _append(e):
        return "(the book is busy — nothing was filed, try again)"
    # the heartbeat can't know whether the bridge is running: one wording, true either way
    return "filed — it goes to your keeper's phone with the numbers" + (f"\n({figures_line(found)})" if found else "")


# ---- the phone ---------------------------------------------------------------------------------------------------
def _friend() -> str:
    try:
        import chat
        return chat.friend_name()
    except Exception:  # noqa: BLE001
        return "the friend"


def _reading_part(r: dict, late: bool) -> list[str]:
    head = f"— {_friend()}'s reading, {r.get('at')} —" if late else f"— {_friend()}'s reading —"
    out = [head] + (["(the numbers are in the desk's message above)"] if late else []) + [r["text"]]
    if r.get("figures"):
        out.append(f"({figures_line(r['figures'])})")
    return out


def outbox(at: datetime | None = None) -> list[tuple[str, dict]]:
    """What the bridge sends now: [(text, mark)], each mark appended (after the send) by sent(). Nothing while paused
    or a guest is seated; nothing twice. The numbers and the reading go as soon as it is filed; PORTFOLIO_DESK_SEND is
    the latest — then the numbers go alone if nothing was filed (only until PORTFOLIO_DESK_UNTIL: a late start sends
    nothing and makes no morning), and a reading filed after that goes when filed. Outside the desk's morning, only a
    reading the friend files: "From the desk", numbers as of now."""
    if not on() or paused() or pf.guest_here():
        return []
    t = at or now()
    d = t.date()
    day = d.isoformat()
    marks = _of_day(day, "sent")
    m = morning(day)
    r = reading(day)
    head = f"📊 The desk — {day_label(d)}"
    in_window = send_at(d) <= t < until_at(d)
    if t < send_at(d) and not (m is not None and r is not None):
        return []  # before the send time: only a morning with its reading in goes early
    if not any(x.get("what") in ("morning", "nofeed") for x in marks):
        if m is not None and m.get("adhoc"):
            m = None
        nofeed, quiet = _of_day(day, "nofeed"), _of_day(day, "quiet")
        if r is None:
            if not in_window:
                return []  # outside the desk's morning: nothing desk-like, no morning made
            if m is None:
                if nofeed:  # the heartbeat's tries failed: said at the send time
                    return [("no brief this morning — prices could not be fetched", {"what": "nofeed"})]
                if quiet:
                    return []
                m = prepare(t, by="bridge")  # the heartbeat was off: the numbers never wait for the friend
                if m is None:
                    return ([("no brief this morning — prices could not be fetched", {"what": "nofeed"})]
                            if _of_day(day, "nofeed") else [])
        elif t >= until_at(d) or (m is None and not in_window):
            # a reading outside the desk's morning (filed in a visit): "From the desk", numbers fetched now
            m = prepare(t, by="bridge", force=True, adhoc=True)
            if m is None:
                return []
        elif m is None:
            m = prepare(t, by="bridge", force=True)
            if m is None:
                return []
        if m.get("adhoc"):
            lines = [f"📊 From the desk — {day_label(d)}, {t:%H:%M}", "(numbers as of now)", m["block"], ""]
        else:
            lines = [head, m["block"]] + [x for x in [_as_of(m, t)] if x] + [""]
        lines += _reading_part(r, False) if r else [f"(no reading from {_friend()} yet this morning)"]
        return [("\n".join(lines), {"what": "morning", "reading_t": (r or {}).get("t")})]
    told = {x.get("reading_t") for x in marks if x.get("reading_t")}
    first = min(float(x.get("t") or 0) for x in marks if x.get("what") == "morning") if any(
        x.get("what") == "morning" for x in marks) else None
    out = []
    if m is not None and first is not None:
        fresh = float(m.get("t") or 0) > first  # the wake read newer numbers than went alone: they go with the reading
        for e in _of_day(day, "reading"):  # a reading filed after the morning's message: sent when filed, once
            if e.get("t") not in told and float(e.get("t") or 0) > first:
                body = ([m["block"]] + [x for x in [_as_of(m, t)] if x] + [""]) if fresh else []
                part = _reading_part(e, True)
                if fresh:
                    part = [x for x in part if x != "(the numbers are in the desk's message above)"]
                out.append(("\n".join([head] + body + part), {"what": "reading", "reading_t": e.get("t")}))
    return out


def _as_of(m: dict, t: datetime) -> str:
    """Numbers older than 30 minutes at the send: "(numbers as of 05:00)"."""
    try:
        made = datetime.fromisoformat(str(m.get("made")))
    except ValueError:
        return ""
    return f"(numbers as of {made:%H:%M})" if (t - made).total_seconds() > 30 * 60 else ""


def _mark_key(mark: dict) -> str:
    return json.dumps(mark, sort_keys=True, ensure_ascii=False)


def parts_sent(mark: dict, at: datetime | None = None) -> set:
    """The parts of a long desk message already sent (by index) — so a failed part two never re-sends part one."""
    t = at or now()
    k = _mark_key(mark)
    return {int(e.get("i") or 0) for e in _of_day(t.date().isoformat(), "part") if e.get("key") == k}


def part_sent(mark: dict, i: int, at: datetime | None = None) -> None:
    t = at or now()
    _append({"type": "part", "day": t.date().isoformat(), "key": _mark_key(mark), "i": int(i), "t": time.time()})


def sent(mark: dict, at: datetime | None = None) -> None:
    t = at or now()
    _append(dict(mark, type="sent", day=t.date().isoformat(), t=time.time(), at=t.strftime("%H:%M")))


def today_reading(at: datetime | None = None) -> str:
    """For /trade → 🌅 Brief: "<friend>'s reading this morning (05:41): …" when there is one."""
    t = at or now()
    r = reading(t.date().isoformat())
    if not r:
        return ""
    return f"{_friend()}'s reading this morning ({r.get('at')}): {r['text']}"


# ---- a test run of the desk wake, asked from the keeper's phone --------------------------------------------------
# A keeper may not be awake at the desk's hour to see whether it works. /trade test writes a request (desk_test.json); the heartbeat's minute tick starts the same desk wake with test=True: no window, no
# "something new", no once-a-day — but a guest, the pause, a live visit or a game still block it. Nothing of a test
# counts as the day's morning, its "woke", its "sent" or the last morning's closes. The bridge reports each step once.
TEST = "desk_test.json"
TEST_MIN = 30         # a request lapses after this
TEST_NUDGE_MIN = 3    # not picked up by then: said once
NOT_PICKED = "the heartbeat did not pick it up in 30 minutes — is it running?"
WAKING = "desk_test_wake.json"  # the heartbeat's CURRENT wake is a test: {pid, t, start_t} — set at its start, cleared in finally
WAKING_MIN = 90       # older than this: stale
TAKEN_S = 300         # a request taken by another heartbeat process: left to it this long
TEST_PLAIN = ("test_wait", "test_nudge", "test_fail")  # status lines with nothing of the book in them


def _watch_movers(block: str) -> int:
    """The watched movers in a block: the ▲/▼ lines of its "watching" section."""
    n, inside = 0, False
    for line in block.splitlines():
        if line.strip() == "watching":
            inside = True
            continue
        if inside:
            if not line.strip():
                break
            if line.lstrip().startswith(("▲", "▼")):
                n += 1
    return n


def test_asked() -> bool:
    """A test request on file — the heartbeat's one cheap check."""
    try:
        return (pf.folder() / TEST).exists()
    except Exception:  # noqa: BLE001
        return False


def _test_req() -> dict | None:
    r = pf._read(TEST, None)
    return r if isinstance(r, dict) else ({} if test_asked() else None)


def _age_min(req: dict, t: datetime) -> float:
    try:
        return (t - datetime.fromisoformat(str(req.get("asked")))).total_seconds() / 60
    except (TypeError, ValueError):
        return 1e9  # unreadable: lapsed


def _test_clear() -> None:
    try:
        (pf.folder() / TEST).unlink()
    except OSError:
        pass


def _lapse(req: dict, t: datetime) -> None:
    _test_clear()
    _append({"type": "test_fail", "day": t.date().isoformat(), "t": time.time(), "why": str(req.get("why") or NOT_PICKED),
             "asked": req.get("asked")})


def ask_test(at: datetime | None = None) -> str:
    """/trade test: the request written (under the book's lock), answered at once. One at a time."""
    if not on():
        return f"(the desk is off — {bad_knob() or 'the book is off'}; no test was asked)"
    t = at or now()
    try:
        with pf._locked():
            req = _test_req()
            if req is not None:
                age = _age_min(req, t)
                if 0 <= age < TEST_MIN:
                    when = str(req.get("asked") or "")[11:16]
                    return (f"🧪 a desk test is asked already ({when}) — the heartbeat picks it up within about a minute; "
                            "nothing new was asked. I'll report here.")
                _lapse(req, t)
            if not pf._write(TEST, {"asked": t.isoformat(timespec="seconds"), "t": time.time()}):
                return "(the book is busy — nothing was asked, try again)"
    except pf.BookBusy:
        return "(the book is busy — nothing was asked, try again)"
    return ("🧪 desk test asked — the heartbeat picks it up within about a minute. It needs: the heartbeat running, no visit "
            "or game open, no guest. I'll report here.")


def _test_mark(why: str, **detail) -> None:
    """The heartbeat saw the request and can't start now: the reason (and its detail) kept in it, the time it saw it."""
    try:
        with pf._locked():
            req = _test_req()
            if req is not None:
                pf._write(TEST, dict({k: v for k, v in req.items() if k not in ("left", "game", "taken_by", "taken_t")},
                                     seen=time.time(), why=why, **detail))
    except pf.BookBusy:
        pass


def test_take(at: datetime | None = None, blocked: str = "", **detail) -> bool:
    """The heartbeat, a request on file: True — start the test wake now (the request is cleared when it starts);
    False — blocked (kept, with why, until it lapses) or lapsed (cleared, kept in the journal for the report)."""
    if not on():
        return False
    t = at or now()
    try:
        with pf._locked():
            req = _test_req()
            if req is None:
                return False
            age = _age_min(req, t)
            if not (-5 <= age < TEST_MIN):
                _lapse(req, t)
                return False
            taken = req.get("taken_by")
            if taken and taken != os.getpid() and time.time() - float(req.get("taken_t") or 0) < TAKEN_S:
                return False  # another heartbeat process has it: one test wake, never two
            why = ("the desk is paused" if paused() else "a guest is seated" if pf.guest_here() else blocked)
            if why:
                _test_mark(why, **(detail if why == blocked else {}))
                return False
            return pf._write(TEST, dict(req, taken_by=os.getpid(), taken_t=time.time()))
    except pf.BookBusy:
        return False


def end_unfinished(why: str, at: datetime | None = None) -> None:
    """A test wake killed mid-wake left no end mark: ended now, said ("ended by the morning's wake"); the
    running-test marker cleared. Called when a real desk wake (or another test) starts. Never raises."""
    try:
        t = at or now()
        es = entries()
        ended = {e.get("start_t") for e in es if e.get("type") == "test_end"}
        for st in [e for e in es if e.get("type") == "test_start" and e.get("t") not in ended]:
            _append({"type": "test_end", "day": t.date().isoformat(), "t": time.time(), "at": t.strftime("%H:%M"),
                     "start_t": st.get("t"), "why": why})
        (pf.folder() / WAKING).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def test_started(m: dict, at: datetime | None = None) -> dict:
    t = at or now()
    end_unfinished("ended by the next test", t)
    _test_clear()
    e = {"type": "test_start", "day": t.date().isoformat(), "t": time.time(), "at": t.strftime("%H:%M"),
         "morning_t": m.get("t"), "counts": m.get("counts") or {}}
    _append(e)
    pf._write(WAKING, {"pid": os.getpid(), "t": time.time(), "start_t": e["t"]})
    return e


def test_ended(start: dict | None, at: datetime | None = None) -> None:
    t = at or now()
    try:
        (pf.folder() / WAKING).unlink(missing_ok=True)
    except OSError:
        pass
    _append({"type": "test_end", "day": t.date().isoformat(), "t": time.time(), "at": t.strftime("%H:%M"),
             "start_t": (start or {}).get("t")})


def _test_wake() -> tuple[dict, dict] | None:
    """The test wake this process is in now: (its start, its numbers), or None. Only while the heartbeat's CURRENT
    wake is that test — the marker is this process's (a visit's tool runs elsewhere: an ordinary reading), under
    WAKING_MIN old, its start not ended."""
    w = pf._read(WAKING, None)
    if not isinstance(w, dict):
        return None
    try:
        if int(w.get("pid")) != os.getpid() or time.time() - float(w.get("t")) > WAKING_MIN * 60:
            return None
    except (TypeError, ValueError):
        return None
    es = entries()
    if any(e.get("type") == "test_end" and e.get("start_t") == w.get("start_t") for e in es):
        return None
    st = next((e for e in es if e.get("type") == "test_start" and e.get("t") == w.get("start_t")), None)
    m = next((e for e in es if e.get("type") == "test_morning" and e.get("t") == (st or {}).get("morning_t")), None) if st else None
    return (st, m) if st and m else None


def _wait_hint(req: dict) -> str:
    """What starts it — in the keeper's words, from the heartbeat's own rule."""
    why = str(req.get("why") or "")
    if why == "a visit is open":
        n, left = req.get("yield_min"), req.get("left")
        if not isinstance(n, (int, float)):
            return "(the test starts once the visit is over)"
        rest = TEST_MIN - _age_min(req, now())
        more = ""
        if isinstance(left, (int, float)) and left > 0:
            more = (f" — about {left} more" + (", longer than this test waits" if left >= rest else ""))
        return (f"(the test starts once the visit has been quiet for {n:g} minutes — no message between you{more}; "
                f"/new ends the visit sooner, once {_friend()} has written it down)")
    if why == "a game is open":
        return f"({req.get('game') or 'the game guard holds the brain'}; /gaming off lets the test start)"
    if why == "a guest is seated":
        return "(/guest off)"
    if why == "the desk is paused":
        return "(/trade resume)"
    if why == "prices could not be fetched":
        return f"(it tries again each minute until the {TEST_MIN} minutes run out)"
    return ""


def _n(k: int, one: str, many: str) -> str:
    return f"{k} {one if k == 1 else many}"


def test_outbox(at: datetime | None = None) -> list[tuple[str, dict]]:
    """The test's report for the keeper's phone — engine-only messages, each once (marked by sent()): the bell given,
    the reading as the desk's message, the wake's end, a test that did not start; the request not picked up after
    TEST_NUDGE_MIN (once), and lapsed after TEST_MIN (the bridge sees that even with the heartbeat off)."""
    if not on():
        return []
    t = at or now()
    es = entries()
    done = {(x.get("what"), x.get("key")) for x in es if x.get("type") == "sent" and str(x.get("what") or "").startswith("test")}
    out = []
    if test_asked():
        try:
            with pf._locked():
                req = _test_req()
                if req is not None:
                    age = _age_min(req, t)
                    if not (-5 <= age < TEST_MIN):
                        _lapse(req, t)
                        es = entries()
                    elif req.get("seen") and req.get("why"):
                        key = f"{req.get('asked')}|{req.get('why')}"
                        if ("test_wait", key) not in done:  # once per reason
                            out.append((f"🧪 the heartbeat saw the request; waiting — {req.get('why')} {_wait_hint(req)}",
                                        {"what": "test_wait", "key": key}))
                    elif age >= TEST_NUDGE_MIN and ("test_nudge", req.get("asked")) not in done:
                        out.append(("🧪 not picked up yet — is the heartbeat running?", {"what": "test_nudge", "key": req.get("asked")}))
        except pf.BookBusy:
            pass
    mornings = {e.get("t"): e for e in es if e.get("type") == "test_morning"}
    for e in es:
        k = e.get("type")
        if k == "test_start" and ("test_start", e.get("t")) not in done:
            c = e.get("counts") or {}
            out.append((f"🧪 the desk bell was given at {e.get('at')} (numbers fetched: {_n(int(c.get('holdings') or 0), 'holding', 'holdings')}, "
                        f"{_n(int(c.get('yardsticks') or 0), 'yardstick', 'yardsticks')}, "
                        f"{_n(int(c.get('movers') or 0), 'watched mover', 'watched movers')})", {"what": "test_start", "key": e.get("t")}))
        elif k == "test_reading" and ("test_reading", e.get("t")) not in done:
            m = mornings.get(e.get("morning_t")) or {}
            lines = [f"📊 The desk — test run, {e.get('at')}", m.get("block") or "", ""] + _reading_part(e, False)
            out.append(("\n".join(lines), {"what": "test_reading", "key": e.get("t")}))
        elif k == "test_end" and ("test_end", e.get("t")) not in done:
            rs = [r for r in es if r.get("type") == "test_reading" and r.get("start_t") == e.get("start_t")]
            if any(("test_reading", r.get("t")) not in done for r in rs):
                continue  # the reading goes first; the end follows it
            said = (f"{_friend()}'s reading was filed at {rs[0].get('at')} and sent" if len(rs) == 1 else
                    f"{_friend()}'s readings were filed at {', '.join(str(r.get('at')) for r in rs)} and sent" if rs else
                    "no reading was filed in this wake")
            out.append((f"🧪 test wake ended {e.get('at')}" + (f" ({e.get('why')})" if e.get("why") else "") + f" — {said}",
                        {"what": "test_end", "key": e.get("t")}))
        elif k == "test_fail" and ("test_fail", e.get("t")) not in done:
            out.append((f"🧪 the test did not start: {e.get('why')}", {"what": "test_fail", "key": e.get("t")}))
    return out
