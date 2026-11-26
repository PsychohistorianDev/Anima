"""The watch list (PORTFOLIO_WATCH) — names the keeper and the friend are considering, kept by the book beside the
holdings.

Alerts at the close (checked when fresh closes are in hand — the morning's numbers, and when the keeper opens Book,
Brief or Watch; no polling); both add names (the friend's go straight in, and the keeper is told in the next brief);
the friend's notes are dated and headed with that day's price, and their ledger is a condensed page of at most
PORTFOLIO_LEDGER_CHARS, which they are asked to fold their notes into when those reach PORTFOLIO_CONDENSE_AT; the
brief and the desk's bell show movers only (beyond PORTFOLIO_WATCH_MOVE, or an alert that fired).

Files, all under memory/portfolio (fenced from the friend's file tools and code like the book):
  watch.json                    the list — under the book's lock, written whole (temp + rename); one that doesn't
                                parse is set aside, never written over
  history.json                  a year of daily closes per name, for the day (watched, held and yardstick names only)
  names/n_<SYMBOL>/notes.jsonl  the friend's notes, append-only: time, the engine's head (date and that day's price),
                                their text — the folder is never the raw ticker (folder_name)
  names/n_<SYMBOL>/ledger.md    the ledger, exactly as written (newline kept), with the time it was written;
                                ledger_history.jsonl keeps every page it replaced; meta.json the real symbol
Nothing here changes the book's records or totals. A watched name never wakes the desk by itself.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import config
import portfolio as pf

WATCH = "watch.json"
HISTORY = "history.json"


class WatchUnreadable(Exception):
    pass


def on() -> bool:
    return bool(getattr(config, "PORTFOLIO_WATCH", False)) and bool(getattr(config, "PORTFOLIO_ON", False))


def cap() -> int:
    return int(getattr(config, "PORTFOLIO_WATCH_MAX", 15) or 15)


def ledger_cap() -> int:
    return int(getattr(config, "PORTFOLIO_LEDGER_CHARS", 2000) or 2000)


def condense_at() -> int:
    return int(getattr(config, "PORTFOLIO_CONDENSE_AT", 4000) or 4000)


def move_at() -> float:
    return float(getattr(config, "PORTFOLIO_WATCH_MOVE", 0.03) or 0.03)


def _day_y(d) -> str:
    """"Nov 18", or "Nov 18 2025" for another year."""
    d = d if isinstance(d, (date, datetime)) else date.fromisoformat(str(d)[:10])
    return pf._day(d) + (f" {d.year}" if d.year != date.today().year else "")


def _friend() -> str:
    try:
        import chat
        return chat.friend_name()
    except Exception:  # noqa: BLE001
        return "the friend"


def _sym(s: str) -> str:
    """A symbol as a folder name: upper-case letters, digits and . ^ = - only."""
    return re.sub(r"[^A-Z0-9.^=\-]", "", str(s or "").strip().upper())[:24]


# ---- the list ----------------------------------------------------------------------------------------------------
def load() -> dict:
    """{"names": [entry…]}. A file that doesn't parse is set aside as watch.broken-<stamp>.json and WatchUnreadable
    raised; nothing is written in its place."""
    f = pf.folder() / WATCH
    if not f.exists():
        broken = sorted(pf.folder().glob("watch.broken-*.json"))
        if broken:  # set aside and nothing in its place: unreadable until someone looks (as the book)
            raise WatchUnreadable(f"the watch list could not be read — it was set aside as {broken[-1].name}; nothing was "
                                  "written in its place (it needs a look by hand)")
        return {"names": []}
    try:
        raw = f.read_text(encoding="utf-8")
    except OSError as e:
        raise WatchUnreadable(f"the watch list could not be read just now ({type(e).__name__}) — nothing was moved") from None
    try:
        d = json.loads(raw)
        if not isinstance(d, dict) or not isinstance(d.get("names"), list) or not all(isinstance(x, dict) for x in d["names"]):
            raise ValueError("not a watch list")
    except ValueError:
        aside = f.with_name(f"watch.broken-{datetime.now():%Y%m%d-%H%M%S}.json")
        try:
            os.replace(f, aside)
        except OSError:
            pass
        raise WatchUnreadable(f"the watch list could not be read — it was set aside as {aside.name}; nothing was written "
                              "in its place (it needs a look by hand)") from None
    return d


def _save(d: dict) -> bool:
    return pf._write(WATCH, d)


def watching(d: dict | None = None) -> list[dict]:
    try:
        d = d if d is not None else load()
    except WatchUnreadable:
        return []
    return [x for x in d["names"] if x.get("state") == "watching"]


def entry(sym: str) -> dict | None:
    s = _sym(sym)
    return next((x for x in watching() if x.get("symbol") == s), None)


def _held() -> set:
    try:
        rp = pf.replay(pf.load(pf.open_book())["records"])
        return {s for s, h in rp["positions"].items() if h["qty"] > 1e-9}
    except pf.BookUnreadable:
        return set()


def add(symbol: str, why: str = "", by: str = "keeper", confirmed: bool = False) -> tuple[dict | None, str, dict | None]:
    """A name added: (entry, "", None); refused: (None, why, None); the feed offers another form: (None, "", quote) —
    the keeper confirms it on the phone (confirmed=True with that symbol); the friend is told to ask and use it."""
    s = str(symbol or "").strip()
    if not s:
        return None, "which symbol? (the share's or index's symbol as the price feed knows it, like ^GSPC)", None
    found = pf.find(s)
    if not found["ok"]:
        return None, (f"no price for “{s}” — tried {', '.join(found['tried']) or 'nothing'}: "
                      f"{found.get('error') or 'not known'}"), None
    q = found["quote"]
    if not found["same"] and not confirmed:
        return None, "", q
    sym = _sym(q["symbol"])
    if sym in _held():
        return None, f"{sym} is in the book already — a holding, not a name to watch", None
    try:
        with pf._locked():
            d = load()
            names = watching(d)
            if any(x.get("symbol") == sym for x in names):
                return None, f"{sym} is on the watch list already", None
            if len(names) >= cap():
                return None, f"the watch list is full — {len(names)} names, the most it holds is {cap()}; nothing was added", None
            price = pf.price_of(q)
            e = {"symbol": sym, "name": q.get("name") or "", "added": date.today().isoformat(), "added_at": time.time(),
                 "price": price, "currency": q.get("currency") or "",
                 "price_date": (q.get("last_date") if pf.at_trade(q) else q.get("close_date")) or "",
                 "price_said": _price_said(q), "source": q.get("source") or "Yahoo",
                 "why": " ".join(str(why or "").split())[:300], "by": by, "alert": None, "state": "watching",
                 "seen": by == "keeper", "briefed": by == "keeper"}
            d["names"].append(e)
            if not _save(d):
                return None, "the watch list couldn't be written — nothing was added", None
            return e, "", None
    except pf.BookBusy as e:
        return None, str(e).replace("nothing was kept", "nothing was added"), None
    except WatchUnreadable as e:
        return None, str(e), None


def _change(sym: str, fn) -> tuple[dict | None, str]:
    """Under the lock: the watching entry for sym changed by fn(entry) → "" or a refusal."""
    s = _sym(sym)
    try:
        with pf._locked():
            d = load()
            e = next((x for x in d["names"] if x.get("symbol") == s and x.get("state") == "watching"), None)
            if e is None:
                return None, f"{s} isn't on the watch list"
            no = fn(e)
            if no:
                return None, no
            if not _save(d):
                return None, "the watch list couldn't be written — nothing changed"
            return e, ""
    except pf.BookBusy as e:
        return None, str(e).replace("nothing was kept", "nothing changed")
    except WatchUnreadable as e:
        return None, str(e)


def drop(sym: str) -> tuple[dict | None, str]:
    """Kept in the record, marked dropped (the notes and ledger stay)."""
    def fn(e):
        e["state"] = f"dropped {date.today().isoformat()}"
        return ""
    return _change(sym, fn)


def set_alert(sym: str, kind: str, value) -> tuple[dict | None, str]:
    v = pf.num(value)
    if kind not in ("below", "above"):
        return None, "an alert is below or above a price"
    if v is None or v <= 0:
        return None, f"“{value}” isn't a price above zero"

    def fn(e):
        e["alert"] = {"kind": kind, "value": round(v, 6), "set": datetime.now().isoformat(timespec="seconds"), "fired": None}
        return ""
    return _change(sym, fn)


def clear_alert(sym: str) -> tuple[dict | None, str]:
    def fn(e):
        e["alert"] = None
        return ""
    return _change(sym, fn)


def mark_seen(sym: str) -> None:
    def fn(e):
        e["seen"] = True
        return ""
    _change(sym, fn)


def on_buy(rec: dict | None) -> str:
    """A buy of a watched name kept in the book: it leaves the list ("bought <date>"); the notes and ledger stay. The
    clause for the kept line, "" when it wasn't watched."""
    if not on() or not rec or rec.get("kind") != "buy":
        return ""
    sym = _sym(rec.get("symbol"))

    def fn(e):
        e["state"] = f"bought {rec.get('date')}"
        e["bought_id"] = rec.get("id")
        return ""
    got, _no = _change(sym, fn)
    return f" · {sym} leaves the watch list — {_friend()}'s notes stay with it" if got else ""


def was_bought(rec: dict | None) -> bool:
    """For Fix: was this buy the one that took a name off the watch list?"""
    if not on() or not rec or rec.get("kind") != "buy":
        return False
    try:
        d = load()
    except WatchUnreadable:
        return False
    return any(x.get("symbol") == _sym(rec.get("symbol")) and str(x.get("state", "")).startswith("bought")
               and x.get("bought_id") == rec.get("id") for x in d["names"])


# ---- the facts ---------------------------------------------------------------------------------------------------
def _price_said(q: dict) -> str:
    """"close Nov 19, Yahoo" or "last trade Nov 20 19:46, Yahoo" — the price's own date and source."""
    src = q.get("source") or "Yahoo"
    if pf.at_trade(q):
        return f"last trade {pf._at(q['last_time'])}, {src}"
    return f"close {pf._day(q.get('close_date'))}, {src}" + ("; from the last trade" if q.get("close_from_trade") else "")


def year_bars(sym: str, refresh: bool = False) -> tuple[list[tuple[str, float]], str, str]:
    """A year of daily closes [(date, close)] for a name, cached for the day in history.json: (bars, the day they were
    fetched, "" or "(could not be fetched now)"). Nulls and gaps skipped; a minor-unit quote in its main unit; a share
    with one bar has one."""
    s = _sym(sym)
    today = date.today().isoformat()
    cache = pf._read(HISTORY, {})
    cache = cache if isinstance(cache, dict) else {}
    c = cache.get(s) if isinstance(cache.get(s), dict) else None
    if c and c.get("day") == today and not refresh:
        return [tuple(x) for x in c.get("bars") or []], c["day"], ""
    try:
        res = pf._chart(s, rng="1y", until=time.time() + pf.BRIEF_PRICE_S)
        meta = res.get("meta") or {}
        minor = pf.MINOR.get(str(meta.get("currency") or "").strip())  # pence, cents, agorot: the main unit
        div = minor[1] if minor else 1.0
        bars = [(d_.isoformat(), round(c_ / div, 6)) for d_, c_, _t in pf._bars(res)]
        bars = sorted({d_: c_ for d_, c_ in bars}.items())  # one close a day
    except Exception:  # noqa: BLE001 — a feed that doesn't answer: the cached year, said
        if c:
            return [tuple(x) for x in c.get("bars") or []], str(c.get("day") or ""), "(could not be fetched now)"
        return [], "", "(could not be fetched now)"
    keep = {x.get("symbol") for x in watching()} | _held() | {s}
    keep |= {_sym(x) for x in (getattr(config, "PORTFOLIO_INDICES", None) or [])}
    try:
        with pf._locked():
            cache = pf._read(HISTORY, {})
            cache = cache if isinstance(cache, dict) else {}
            cache[s] = {"day": today, "bars": [list(b) for b in bars], "fetched_at": time.time()}
            pf._write(HISTORY, {k: v for k, v in cache.items() if k in keep})
    except pf.BookBusy:
        pass
    return bars, today, ""


def _back(bars: list, ref: str, days: int) -> tuple[str, float] | None:
    """The close nearest `days` before the date ref: the last bar on or before that day."""
    target = (date.fromisoformat(ref) - timedelta(days=days)).isoformat()
    older = [b for b in bars if b[0] <= target]
    return tuple(older[-1]) if older else None


_SPANS = (("1 month", 30, 3), ("1 year", 365, 7))  # (label, days back, how many days after the anchor a first bar may fall)


def _anchor(bars: list, ref: str, days: int, slack: int) -> tuple[str, float] | None:
    """The close at or before `days` before ref; else, when the history starts just after that day (the feed's year
    begins a year before TODAY while the latest close is yesterday's), its first bar if within `slack` days after it."""
    b = _back(bars, ref, days)
    if b or not bars:
        return b
    target = date.fromisoformat(ref) - timedelta(days=days)
    first = date.fromisoformat(bars[0][0])
    return tuple(bars[0]) if target < first <= target + timedelta(days=slack) and bars[0][0] < ref else None


def _span_list(bars: list, ref: str) -> list[tuple[str, tuple[str, float]]]:
    """[(label, anchor bar)] — "1 month", "1 year", or ("since", first bar) for a shorter history; one bar: since it."""
    out = []
    for label, days, slack in _SPANS:
        b = _anchor(bars, ref, days, slack)
        if b:
            out.append((label, b))
        elif bars:
            if not (out and out[-1][1][0] == bars[0][0]):  # the month already reaches back to its first bar
                out.append(("since", tuple(bars[0])))
            break
    return out


def _spans(bars: list, price: float, ref: str) -> list[str]:
    """"1 month (close Oct 20 $X): +5.2%", "1 year (…)" — or "since its first bar, <date>" for a shorter history."""
    out = []
    for label, b in _span_list(bars, ref):
        if label == "since":
            out.append(f"since its first bar, {_day_y(b[0])}: {pf._pct(price / b[1] - 1)}")
        else:
            out.append(f"{label} (close {_day_y(b[0])}): {pf._pct(price / b[1] - 1)}")
    return out


def _full_year(bars: list) -> bool:
    """The bars span a year (at least 358 days, first to last)."""
    try:
        return len(bars) > 1 and (date.fromisoformat(bars[-1][0]) - date.fromisoformat(bars[0][0])).days >= 358
    except (TypeError, ValueError):
        return False


def yardstick_for(cur: str) -> str:
    idx = [str(x) for x in (getattr(config, "PORTFOLIO_INDICES", None) or [])]
    if not idx:
        return ""
    for s in idx:
        q = pf.quote(s)
        if q.get("ok") and q.get("currency") == cur:
            return s
    return idx[0]


def facts(sym: str) -> dict:
    """The engine's facts for a name: {"ok", "lines", "quote", "move"} — every figure with its date; a failed fetch →
    the cached facts with their date and "(could not be fetched now)", or "not known"."""
    s = _sym(sym)
    q = pf.quote(s)
    if not q.get("ok"):
        return {"ok": False, "lines": [f"{s}: not known — {q.get('error') or 'no price'}"], "quote": q, "move": None}
    cur = q.get("currency") or ""
    m = pf._move(q)
    price = m["price"]
    lines = [f"{s}" + (f" · {q['name']}" if q.get("name") else "")]
    lines.append(f"  {m['line']}" + (" (could not be fetched now)" if q.get("stale") else ""))
    e = entry(s)
    if e and e.get("price"):
        lines.append(f"  since added ({_day_y(e['added'])}, {pf.money(float(e['price']), e.get('currency') or cur)}): "
                     f"{pf._pct(price / float(e['price']) - 1)}")
    bars, day, note = year_bars(s)
    if bars and price:
        ref = (q.get("last_date") if m["newer"] else q.get("close_date")) or bars[-1][0]
        sp = _spans(bars, price, ref)
        if sp:
            lines.append("  " + " · ".join(sp) + (f" {note} — the year as of {_day_y(day)}" if note else ""))
        year = [b for b in bars if b[0] > (date.fromisoformat(ref) - timedelta(days=365)).isoformat()] or bars
        hi = max(year, key=lambda b: b[1])
        lo = min(year, key=lambda b: b[1])
        lines.append(f"  52 weeks: high {pf.money(hi[1], cur)} ({_day_y(hi[0])}), {pf._pct(price / hi[1] - 1)} from it · "
                     f"low {pf.money(lo[1], cur)} ({_day_y(lo[0])}), {pf._pct(price / lo[1] - 1)} from it"
                     + (" (from the closes since its first bar)" if not _full_year(bars) else ""))
        y = yardstick_for(cur)
        if y and _sym(y) != s:
            yb, _yd, ynote = year_bars(y)
            end = [b for b in yb if b[0] <= ref]  # the yardstick to the same end date: its close at or before it
            if end:
                yr, yp = end[-1]
                ysp = []
                slack = {lb: sl for lb, _dd, sl in _SPANS}
                for label, nb in _span_list(bars, ref):  # the yardstick over the NAME's spans
                    if label == "since":
                        if nb[0] >= ref:
                            break  # a name with one bar: no span to put it beside
                        older = [x for x in yb if x[0] <= nb[0]]
                        b = tuple(older[-1]) if older else None
                        if b and b[0] < yr:
                            ysp.append(f"since {_day_y(nb[0])}: {pf._pct(yp / b[1] - 1)}")
                        break
                    days = 30 if label == "1 month" else 365
                    b = _anchor(yb, yr, days, slack[label])
                    if b:
                        ysp.append(f"{label} {pf._pct(yp / b[1] - 1)}")
                if ysp:
                    lines.append(f"  {y} beside it: " + " · ".join(ysp) + (f" (to its close of {_day_y(yr)})" if yr != ref else "")
                                 + (f" {ynote}" if ynote else ""))
    elif note:
        lines.append(f"  the year: not known {note}")
    return {"ok": True, "lines": lines, "quote": q, "move": m}


# ---- the friend's notes and ledger ----------------------------------------------------------------------------------------
def folder_name(sym: str) -> str:
    """A name's folder, never the raw ticker: "n_" + the symbol with every character outside A-Z0-9 written as
    _XX (hex) — PRN, CON, "BRK.B.", "^GSPC", "ILS=X", ".." all get distinct, Windows-safe names."""
    return "n_" + "".join(c if ("A" <= c <= "Z" or "0" <= c <= "9") else "".join(f"_{b:02X}" for b in c.encode("utf-8"))
                          for c in _sym(sym))


def _dir(sym: str) -> Path:
    return pf.folder() / "names" / folder_name(sym)


def _meta(sym: str) -> None:
    """The real symbol, kept inside its folder."""
    f = _dir(sym) / "meta.json"
    if not f.exists():
        f.write_text(json.dumps({"symbol": _sym(sym)}, ensure_ascii=False), encoding="utf-8")


def notes(sym: str) -> list[dict]:
    out = []
    try:
        for line in (_dir(sym) / "notes.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                x = json.loads(line)
                if isinstance(x, dict):
                    out.append(x)
            except ValueError:
                continue
    except OSError:
        pass
    return out


def ledger(sym: str) -> dict | None:
    """{"text", "written"} — the ledger exactly, and when it was written."""
    f = _dir(sym) / "ledger.md"
    try:
        with open(f, encoding="utf-8", newline="") as fh:  # \r\n and \n come back exactly as written
            raw = fh.read()
    except OSError:
        return None
    m = re.match(r"<!-- written (\S+) -->\n", raw)  # (the header line is the engine's, always "\n")
    return {"text": raw[m.end():] if m else raw, "written": m.group(1) if m else ""}


def _known(sym: str) -> bool:
    s = _sym(sym)
    return s in _held() or entry(s) is not None or (_dir(s)).exists()


def since_ledger(sym: str) -> list[dict]:
    led = ledger(sym)
    w = (led or {}).get("written") or ""
    return [n for n in notes(sym) if not w or str(n.get("at")) > w]


def condense_line(sym: str) -> str:
    n = sum(len(x.get("text") or "") for x in since_ledger(sym))
    if n >= condense_at():
        return (f"{_sym(sym)} has {n:,} characters of notes since its ledger was written — fold them in when you choose."
                if ledger(sym) else
                f"{_sym(sym)} has {n:,} characters of notes and no ledger yet — fold them into one when you choose.")
    return ""


def add_note(sym: str, text: str) -> str:
    s = _sym(sym)
    words = str(text or "")
    if not words.strip():
        return "(bad arguments: note needs symbol and text — your note, in your own words; nothing was written)"
    if not (s in _held() or entry(s) is not None):
        return f"(refused: {s} isn't watched or held — watch it first; nothing was written)"
    q = pf.quote(s)
    if q.get("ok"):
        head = f"{pf._day(date.today())} · {pf.money(pf.price_of(q), q.get('currency') or '')} ({_price_said(q)})"
    else:
        head = f"{pf._day(date.today())} · price not known"
    before = condense_line(s)
    rec = {"at": datetime.now().isoformat(timespec="microseconds"), "head": head, "text": words}
    try:
        with pf._locked():
            _dir(s).mkdir(parents=True, exist_ok=True)
            _meta(s)
            w = (ledger(s) or {}).get("written") or ""
            if w and rec["at"] <= w:  # a note in the tick its ledger was written is still a note since it
                try:
                    rec["at"] = (datetime.fromisoformat(w) + timedelta(microseconds=1)).isoformat(timespec="microseconds")
                except ValueError:
                    pass
            with open(_dir(s) / "notes.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except (pf.BookBusy, OSError) as e:
        return f"(the note couldn't be written — {e}; nothing was written)"
    after = condense_line(s)
    return f"noted on {s} — {head}" + (f"\n({after})" if after and not before else "")


def write_ledger(sym: str, text: str) -> str:
    s = _sym(sym)
    words = str(text or "")
    if not words.strip():
        return "(bad arguments: ledger needs symbol and text — your page, in your own words; nothing was written)"
    if not (s in _held() or entry(s) is not None):
        return f"(refused: {s} isn't watched or held — watch it first; nothing was written)"
    if len(words) > ledger_cap():
        return (f"(your ledger is {len(words):,} characters — the page holds {ledger_cap():,}; nothing was written)")
    stamp = datetime.now().isoformat(timespec="microseconds")
    replaced = False
    try:
        with pf._locked():
            _dir(s).mkdir(parents=True, exist_ok=True)
            _meta(s)
            old = ledger(s)
            if old is not None:  # a rewritten ledger never loses the old page: kept in the record, whole
                with open(_dir(s) / "ledger_history.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"written": old.get("written") or "", "replaced": stamp, "text": old["text"]},
                                        ensure_ascii=False) + "\n")
                replaced = True
            tmp = _dir(s) / f".ledger.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write(f"<!-- written {stamp} -->\n" + words)
            os.replace(tmp, _dir(s) / "ledger.md")
    except (pf.BookBusy, OSError) as e:
        return f"(the ledger couldn't be written — {e}; nothing was written)"
    return (f"ledger written for {s} — {len(words):,} of {ledger_cap():,} characters; from now on only notes newer than it "
            "are put in front of you" + (" (the page it replaces is kept in the record)" if replaced else ""))


def name_view(sym: str, all_notes: bool = False, last_notes: int | None = None, cut: int | None = None,
              voice: str = "keeper") -> str:
    """The name: the facts, the ledger, the notes since it (all_notes: every one; last_notes: the last n, for the
    keeper's phone), the condense line. voice "friend": the friend's tool ("your ledger"); "keeper": the phone."""
    s = _sym(sym)
    f = facts(s)
    lines = list(f["lines"])
    e = entry(s)
    to_friend = voice == "friend"  # the friend's tool speaks to them: "your ledger", "added by you"; the phone names them
    who = "your" if to_friend else f"{_friend()}'s"
    if e:
        by_k = e.get("by") == "keeper"
        lines.append(f"  watched since {_day_y(e['added'])}, added by "
                     + (("your keeper" if to_friend else "you") if by_k else ("you" if to_friend else _friend()))
                     + (f" — {e['why']}" if e.get("why") else ""))
        a = e.get("alert")
        if a:
            lines.append(f"  🔔 {a['kind']} {pf.money(float(a['value']), e.get('currency') or '')}"
                         + (f" — fired {a['fired'][:10]}" if a.get("fired") else ""))
    led = ledger(s)
    lines.append("")
    if led:
        lines.append(f"{who} ledger (written {_day_y(led['written'][:10]) if led.get('written') else '—'}):")
        lines.append(led["text"])
    else:
        lines.append(f"{who} ledger: none yet")
    ns = notes(s) if all_notes else since_ledger(s)
    if last_notes is not None:
        more = len(ns) > last_notes
        ns = ns[-last_notes:]
    else:
        more = False
    lines.append("")
    label = f"{who} notes" if all_notes else (f"{who} notes since the ledger" if led else f"{who} notes")
    if ns:
        lines.append(f"{label}:")
        for n in ns:
            body = n.get("text") or ""
            if cut and len(body) > cut:
                body = body[:cut].rsplit(" ", 1)[0] + "…"
            lines.append(f"· {n.get('head')}: {body}")
        if more:
            lines.append(f"(more in {who} notes)")
    else:
        lines.append(f"{label}: none")
    c = condense_line(s)
    if c:
        lines += ["", c]
    return "\n".join(lines)


def list_lines(compact: bool = True) -> list[str]:
    """The watch list, one line a name: price, the day's move, since added, 🔔 with its level, "added by <friend>" until
    the keeper has opened it once."""
    out = []
    for e in watching():
        q = pf.quote(e["symbol"])
        if not q.get("ok"):
            out.append(f"{e['symbol']}  not known — {q.get('error') or 'no price'}")
            continue
        m = pf._move(q)
        p = m["price"]
        day = f" {pf._pct(m['pct'])}" if m["pct"] is not None else ""
        since = f" · {pf._pct(p / float(e['price']) - 1)} since added" if e.get("price") and p else ""
        a = e.get("alert")
        bell = f" · 🔔 {a['kind']} {pf.money(float(a['value']), e.get('currency') or '')}" if a and not a.get("fired") else ""
        by_f = f" · added by {_friend()}" if e.get("by") != "keeper" and not e.get("seen") else ""
        out.append(f"{e['symbol']}  {pf.money(p, q.get('currency') or '')}{day}{since}{bell}{by_f}")
    return out


# ---- alerts at the close -----------------------------------------------------------------------------------------
def check_alerts() -> list[str]:
    """An alert fires when the latest COMPLETED close, dated after it was set, is at/below (or at/above) its level —
    once: marked fired, it waits to be set again. The lines, for whoever is showing numbers now."""
    if not on():
        return []
    out = []
    for e in watching():
        a = e.get("alert")
        if not a or a.get("fired"):
            continue
        q = pf.quote(e["symbol"])
        if not q.get("ok") or q.get("close") is None or not q.get("close_date"):
            continue
        try:  # the close counts when its session ENDED after the alert was set
            set_ts = datetime.fromisoformat(str(a.get("set"))).timestamp()
        except ValueError:
            continue
        if float(q.get("close_end") or 0) <= set_ts:
            continue
        c, v = float(q["close"]), float(a["value"])
        if (a["kind"] == "below" and c <= v) or (a["kind"] == "above" and c >= v):
            line = (f"🔔 {e['symbol']} closed at {pf.money(c, q.get('currency') or '')} on {pf._day(q['close_date'])} — "
                    f"{a['kind']} the alert at {pf.money(v, e.get('currency') or q.get('currency') or '')}")

            def fn(x, line=line):
                if x.get("alert") and not x["alert"].get("fired"):
                    x["alert"]["fired"] = datetime.now().isoformat(timespec="seconds")
                    x["alert"]["line"] = line
                    return ""
                return "fired already"
            got, _no = _change(e["symbol"], fn)
            if got:
                out.append(line)
    return out


# ---- the brief's "watching" ---------------------------------------------------------------------------------------
def section(fired: list[str], until: float | None = None, news: bool = False) -> list[str]:
    """Movers only: a watched name whose day move is beyond PORTFOLIO_WATCH_MOVE, or whose alert fired; the friend's adds
    since the last brief, once; headlines for the movers. [] when there is nothing to say."""
    rows, movers = [], []
    for e in watching():
        q = pf.quote(e["symbol"], until=until)
        if not q.get("ok"):
            continue
        m = pf._move(q)
        if m["pct"] is not None and abs(m["pct"]) >= move_at():
            since = (f" · {pf._pct(m['price'] / float(e['price']) - 1)} since added" if e.get("price") and m["price"] else "")
            rows.append(f"  {'▲' if m['pct'] > 0 else '▼'} {e['symbol']} {m['line']}{since}")
            movers.append((e, q))
    rows += ["  " + x for x in fired]
    adds = [e for e in watching() if e.get("by") != "keeper" and not e.get("briefed")]
    for e in adds:
        rows.append(f"  added by {_friend()} since the last brief: {e['symbol']}" + (f" — {e['why']}" if e.get("why") else ""))
    if not rows:
        return []
    out = ["watching"] + rows
    if news and movers:
        found, failed = [], False
        for e, q in movers:
            got = pf._headlines(e["symbol"], q.get("name") or e.get("name") or "", until or (time.time() + 4))
            if got is None:
                failed = True
                continue
            for it in got:
                t = it["title"] if len(it["title"]) <= 90 else it["title"][:89].rstrip() + "…"
                found.append(f"· {t} — {it['host']}" + (f", {it['age']}" if it.get("age") else ""))
        if found or failed:
            out += ["  said today about them (headlines as found — not checked facts)"] + ["  " + x for x in found] + \
                   (["  (headlines could not be fetched)"] if failed else [])
    return out


def mark_briefed() -> None:
    """The friend's adds were in a brief that was kept (the morning's numbers): not said again."""
    try:
        with pf._locked():
            d = load()
            ch = False
            for e in d["names"]:
                if e.get("state") == "watching" and not e.get("briefed"):
                    e["briefed"] = True
                    ch = True
            if ch:
                _save(d)
    except (pf.BookBusy, WatchUnreadable):
        pass


def look_list() -> str:
    """For the friend's look: "watching: ACME $43.25 (+0.0% since added) 🔔, …" — "" when the list is empty."""
    names = watching()
    if not names:
        return ""
    bits = []
    for e in names:
        q = pf.quote(e["symbol"])
        p = pf.price_of(q) if q.get("ok") else None
        since = f" ({pf._pct(p / float(e['price']) - 1)} since added)" if p and e.get("price") else ""
        bell = " 🔔" if e.get("alert") and not e["alert"].get("fired") else ""
        bits.append(f"{e['symbol']} {pf.money(p, q.get('currency') or '') if p else 'not known'}{since}{bell}")
    return "watching: " + ", ".join(bits)


def condense_bell_lines() -> list[str]:
    out = []
    for s in sorted({e["symbol"] for e in watching()} | _held()):
        c = condense_line(s)
        if c:
            out.append(c)
    return out
