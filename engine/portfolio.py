"""The keeper's investment book — the friend keeps it with them (PORTFOLIO_ON; off by default).

The engine keeps the book and does the arithmetic; the friend reads it through the `portfolio` tool, and the keeper
keeps it from the phone with /trade. A model asked for a number it doesn't have will make one up, so every number
comes from here, with its source and date, and the tool tells the friend that one it did not give is not known.

Everything lives in memory/portfolio/ and nowhere else:

    book.json      the real book        paper.json   the PAPER book (for practice; the default)
    prices.json    the price cache      pending.json records the friend wrote, waiting for the keeper's ✅ Keep
    state.json     which book is open, what the friend last saw            backups/   one dated copy of a book a day it changed
    seated.json    who is seated at each door (the book is closed while a guest is)       .lock   the house lock

A book is {"records": [...], "next_id": n}. Records are never deleted: a correction is a new record that `replaces`
the old one, which is `struck`. Each record: id, date (the trade's day), kind (buy, sell, deposit, withdraw, dividend,
fee, split), symbol, qty, price, currency (a three-letter code in its main unit — pence, agorot and cents are never
stored), fx (units of the home currency, PORTFOLIO_HOME_CURRENCY, per one unit of fx_ccy that day: the record's own
currency, or the dollar for a record in the home currency when home is not the dollar), fx_ccy, fx_home, fx_source,
fee, why (the keeper's words), by ("keeper", "friend", "engine"), recorded_at. For deposit, withdraw, dividend and fee
the money is in `price` (qty is 1); for a split, `qty` is the ratio (2.0 for 2-for-1).

Prices: Yahoo's chart feed (no key; unofficial, and it may stop), the last completed daily close with its date; a
quote in a minor unit (pence, agorot, cents) is turned into its main unit, said. A rate: the home currency's official
source when it has one in OFFICIAL, else Yahoo's <CCY>=X (units per dollar; a pair without the dollar is worked out
through it). A price that can't be fetched is the cached one with its date and "(could not be fetched now)" — never a
guess, never zero. Nothing here raises to the caller; a book that can't be read is set aside, never written over.
Nothing here is investment advice, and no money moves: it is a book of what happened.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d&events=div%2Csplits"
TIMEOUT_S = 6          # one fetch; the feed's "down" memory below keeps a view from waiting on it twice
FEED_DOWN_S = 60       # after a failure, the next fetches this long use the cache at once
KINDS = ("buy", "sell", "deposit", "withdraw", "dividend", "fee", "split", "convert")
MONEY_KINDS = ("deposit", "withdraw", "dividend", "fee")
BOOKS = {"paper": "paper.json", "real": "book.json"}
PENDING_LAPSE_H = 24

# what a currency is written with; any other is written as its code after the number
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "ILS": "₪"}
# what Yahoo quotes in a minor unit: its code there -> (the main currency, how many to one, the minor's name, the main's)
MINOR = {"ILA": ("ILS", 100.0, "agorot", "shekels"), "GBp": ("GBP", 100.0, "pence", "pounds"),
         "ZAc": ("ZAR", 100.0, "cents", "rand")}
# words a currency is typed as, besides its code
CURRENCY_WORDS = {"$": "USD", "DOLLARS": "USD", "DOLLAR": "USD", "€": "EUR", "EURO": "EUR", "EUROS": "EUR",
                  "£": "GBP", "POUNDS": "GBP", "POUND": "GBP", "₪": "ILS", "SHEKELS": "ILS", "SHEKEL": "ILS", "NIS": "ILS"}
# a currency's word in a sentence ("dollar cash is below zero while there are euros"); any other is said by its code
CUR_WORD = {"USD": "dollar", "EUR": "euro", "GBP": "pound", "ILS": "shekel"}
# a conversion whose rate is more than this many times away from the fetched rate for that pair (either way) is
# refused as a typo; no fetched rate — no check
CONVERT_BAND = 2.0
# a home currency's exchange suffix, tried after the symbol as typed and upper-cased (never a silent swap)
SUFFIX = {"ILS": ".TA", "GBP": ".L", "ZAR": ".JO"}


def _boi_rates(d) -> dict:
    """The Bank of Israel's public answer: {code: shekels per one unit, "time": …}."""
    out = {}
    for x in (d or {}).get("exchangeRates") or [] if isinstance(d, dict) else []:
        if isinstance(x, dict) and isinstance(x.get("currentExchangeRate"), (int, float)) and x.get("key"):
            unit = x.get("unit")
            unit = float(unit) if isinstance(unit, (int, float)) and unit > 0 else 1.0
            out[str(x["key"]).upper()] = (float(x["currentExchangeRate"]) / unit, str(x.get("lastUpdate") or ""))
    return out


# a home currency's official rates, used only when that is the home currency: name, short name, address, reader
OFFICIAL = {"ILS": {"name": "Bank of Israel", "short": "BoI",
                    "url": "https://boi.org.il/PublicApi/GetExchangeRates?asJson=true", "read": _boi_rates}}


class BookUnreadable(Exception):
    pass


_LOCK = threading.RLock()  # every read-change-write of the book, the paper book, pending, state and prices
_COUNTER = [0]
_FEED = {"down_until": 0.0}  # the feed failed a moment ago: the rest of this look uses the cache at once
_HELD = [0]  # how deep this process holds the house lock (under _LOCK)
LOCK_WAIT_S = 10.0
LOCK_STALE_S = 30.0
LOCK_POLL_S = 0.05
BUSY = "the book is busy — nothing was kept, try again"
LOOK_BUDGET_S = 8
SINCE_MAX = 10


class BookBusy(Exception):
    pass


class OfflineError(RuntimeError):
    pass


def home() -> str:
    """The home currency (PORTFOLIO_HOME_CURRENCY): totals and "put in / worth" are in it. USD when it isn't a code."""
    c = str(getattr(config, "PORTFOLIO_HOME_CURRENCY", "USD") or "USD").strip().upper()
    return c if re.fullmatch(r"[A-Z]{3}", c) else "USD"


def sym(cur: str) -> str:
    return SYMBOLS.get(cur, cur)


def _log(line: str) -> None:
    """Said in the bridge's window, and kept in memory/portfolio/lock.log. Never raises."""
    try:
        print(f"  (book: {line})", flush=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        folder().mkdir(parents=True, exist_ok=True)
        with open(folder() / "lock.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")
    except Exception:  # noqa: BLE001
        pass


def _take_lock(deadline: float) -> bool:
    """memory/portfolio/.lock, made with O_CREAT|O_EXCL (the same on Windows and Linux): pid and time inside. One
    older than LOCK_STALE_S, or one with this process's pid that this process doesn't hold (a crash before a restart
    that got the same pid), is taken over — and said."""
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    lk = d / ".lock"
    while True:
        try:
            fd = os.open(str(lk), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            mine = f"{os.getpid()} {time.time():.3f}"
            try:
                os.write(fd, mine.encode("ascii"))
            finally:
                os.close(fd)
            _MINE[0] = mine
            return True
        except FileExistsError:
            pass
        except PermissionError:  # Windows: the lock file is being deleted by its holder at this moment
            pass
        try:
            raw = lk.read_text(encoding="ascii")
            parts = raw.split()
            pid, t = int(parts[0]), float(parts[1])
        except (OSError, ValueError, IndexError):
            raw, pid, t = None, 0, None
            try:
                t = lk.stat().st_mtime
            except OSError:
                t = None
        if t is not None and (time.time() - t > LOCK_STALE_S or pid == os.getpid()):
            try:
                again = lk.read_text(encoding="ascii") if raw is not None else None
                if raw is None or again == raw:
                    lk.unlink()
                    _log(f"took over a lock left by pid {pid or '?'} "
                         f"({_own_lock_said() if pid == os.getpid() else f'{time.time() - t:.0f} s old'})")
                    continue
            except OSError:
                pass
        if time.time() >= deadline:
            return False
        time.sleep(LOCK_POLL_S)


@contextlib.contextmanager
def _locked():
    """The thread lock and the house lock together, around every read-change-write. BookBusy when the house lock
    can't be had within LOCK_WAIT_S — then nothing is written. Never held across a fetch or a send."""
    with _LOCK:
        if _HELD[0] == 0:
            if not _take_lock(time.time() + LOCK_WAIT_S):
                _log(f"the lock could not be had in {LOCK_WAIT_S:g} s — nothing written")
                raise BookBusy(BUSY)
        _HELD[0] += 1
        try:
            yield
        finally:
            _HELD[0] -= 1
            if _HELD[0] == 0:
                _release_lock()


RELEASE_TRIES = 10       # removing the lock: tries, RELEASE_PAUSE_S apart (0.27 s at most in all)
RELEASE_PAUSE_S = 0.03
_MINE = [""]             # what this process wrote into the lock it took
_RELEASE_STUCK = [False]  # this process's last release did not go through
_RELEASE_SAID = [False]


def _release_lock() -> None:
    """The house lock removed. Windows refuses to delete a file another process has open — a waiter reading
    who holds it, for an instant — so a refusal is tried again a few times, briefly; one already gone is fine. A lock
    that still can't be removed is said once in the book's log, and is taken over once it is stale (or by this process
    at its next write). Never raises."""
    lk = folder() / ".lock"
    for n in range(RELEASE_TRIES):
        try:
            if n and lk.read_text(encoding="ascii") != _MINE[0]:
                return  # not this process's lock any more (taken over meanwhile): left alone
            lk.unlink()
            _RELEASE_STUCK[0] = False
            return
        except FileNotFoundError:
            _RELEASE_STUCK[0] = False
            return
        except PermissionError:
            if n < RELEASE_TRIES - 1:
                time.sleep(RELEASE_PAUSE_S)
        except ValueError:  # what is written there isn't this process's: left alone
            return
        except OSError:
            break
    _RELEASE_STUCK[0] = True
    if not _RELEASE_SAID[0]:
        _RELEASE_SAID[0] = True
        _log("the lock could not be removed after a write (another process had it open) — it is taken over when it "
             "is stale; nothing was lost")


def _own_lock_said() -> str:
    """A lock with this process's pid that it doesn't hold: its own release that didn't go through, or a crash before a
    restart that got the same pid."""
    if _RELEASE_STUCK[0]:
        return "this process's own — its release had not gone through"
    return "this process, before a restart"


DOORS = {"parlor": "at the desk page", "telegram": "on the phone"}
SEAT_OFF = {"parlor": "the page's seat", "telegram": "/guest off here"}
_SEAT_FAILED: dict = {}


def seat(door: str, name: str) -> bool:
    """A door (telegram, parlor) seats a guest (a name) or lets them go (""), in memory/portfolio/seated.json — its
    OWN key only. While anyone is seated the book stays closed, in every turn, the keeper's /me too. False (and said)
    when it couldn't be written; a seat that couldn't be written keeps this process closed."""
    try:
        with _locked():
            d = _read("seated.json", {})
            d = d if isinstance(d, dict) else {}
            if name:
                d[door] = str(name)
            else:
                d.pop(door, None)
            if not _write("seated.json", d):
                raise OSError("not written")
        _SEAT_FAILED.pop(door, None)
        return True
    except (BookBusy, OSError) as e:
        if name:
            _SEAT_FAILED[door] = str(name)
        _log(f"the {door}'s seat could not be written ({e})")
        return False


def seats() -> dict | None:
    """Who is seated at each door, from the seat file every time; None when the file can't be read."""
    f = folder() / "seated.json"
    try:
        if not f.exists():
            d = {}
        else:
            d = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                return None
    except Exception:  # noqa: BLE001
        return None
    d = {str(k): str(v) for k, v in d.items() if v}
    for k, v in _SEAT_FAILED.items():
        d.setdefault(k, v)
    return d


def guest_here() -> str:
    """Who is seated at any door ("" — no one). An unreadable seat file counts as someone: closed, not open."""
    d = seats()
    if d is None:
        return "someone"
    return next(iter(d.values()), "")


def closed_line() -> str:
    """The book is closed: who, where, how to open it."""
    d = seats()
    if d is None:
        return (f"(the book is closed: its seat file could not be read — {folder() / 'seated.json'}; "
                "/trade unseat clears it)")
    who = "; ".join(f"{v}, {DOORS.get(k, k)}" for k, v in d.items()) or "a guest"
    how = " or ".join(SEAT_OFF.get(k, k) for k in d) or "/guest off"
    return f"(the book stays closed while a guest is here — {who}; it opens when they are let go: {how})"


def unseat_all(truth: dict) -> str:
    """(/trade unseat) The seat file rewritten from the doors' true state ({door: name or ""})."""
    try:
        with _locked():
            d = {k: v for k, v in truth.items() if v}
            if not _write("seated.json", d):
                return "(the seat file could not be written — nothing changed)"
        _SEAT_FAILED.clear()
        return ("(the seat file is mended — " + ("; ".join(f"{v}, {DOORS.get(k, k)}" for k, v in d.items()) + " still seated)"
                if d else "no one is seated; the book is open)"))
    except BookBusy as e:
        return f"({e})"


SCRUBBED = "(the book's answer was here — set aside while a guest is seated; the portfolio tool gives it again after)"


def scrub(history: list) -> int:
    """(PORTFOLIO_GUEST_SCRUB) While a guest is seated: the friend's earlier portfolio results in the visit (and turns
    carried in) are set aside, so the book doesn't ride in their context to a guest's turn. Their own words about it
    stay — they're theirs."""
    n = 0
    for m in history or []:
        if isinstance(m, dict) and m.get("role") == "tool" and m.get("tool_name") == "portfolio" \
                and m.get("content") != SCRUBBED:
            m["content"] = SCRUBBED
            n += 1
    return n


# ---- files -------------------------------------------------------------------------------------------------------
def folder() -> Path:
    return Path(config.MEMORY_DIR) / "portfolio"


def _read(name: str, missing):
    try:
        return json.loads((folder() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return missing


def _write(name: str, data) -> bool:
    """Temp file (a name of its own: pid, thread, counter), then rename. False when it could not be written."""
    tmp = None
    try:
        with _LOCK:
            d = folder()
            d.mkdir(parents=True, exist_ok=True)
            _COUNTER[0] += 1
            tmp = d / f".{name}.{os.getpid()}.{threading.get_ident()}.{_COUNTER[0]}.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            for n in range(20):  # Windows: a reader holding the file open makes the replace fail for a moment
                try:
                    os.replace(tmp, d / name)
                    break
                except PermissionError:
                    if n == 19:
                        raise
                    time.sleep(0.05)
        return True
    except Exception:  # noqa: BLE001
        try:
            if tmp is not None and tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


def state() -> dict:
    s = _read("state.json", {})
    return s if isinstance(s, dict) else {}


def state_readable() -> bool:
    """False when state.json is there and can't be read — the menu then says so, and shows PAPER."""
    f = folder() / "state.json"
    if not f.exists():
        return True
    try:
        return isinstance(json.loads(f.read_text(encoding="utf-8")), dict)
    except (OSError, ValueError):
        return False


def save_state(s: dict) -> bool:
    try:
        with _locked():
            return _write("state.json", s)
    except BookBusy:
        return False


def paper_on() -> bool:
    """PORTFOLIO_PAPER: absent or True — the practice book and the real one; False — one book, the real one."""
    return bool(getattr(config, "PORTFOLIO_PAPER", True))


def open_book() -> str:
    if not paper_on():  # one book: whatever state.json says (a stale "paper" is ignored)
        _maybe_adopt()
        _maybe_settle()
        return "real"
    _maybe_settle()
    b = str(state().get("open") or "paper")
    return b if b in BOOKS else "paper"


_ADOPT_LOOKED = [False]


def _maybe_adopt() -> None:
    """Once per process: if a practice book is lying there, adopt() decides (under the lock)."""
    if _ADOPT_LOOKED[0]:
        return
    _ADOPT_LOOKED[0] = True
    try:
        if (folder() / BOOKS["paper"]).exists():
            adopt()
    except Exception as e:  # noqa: BLE001
        _log(f"adoption: {type(e).__name__}: {e}")


ADOPT_PHONE = "the practice book is now the book — {n} record{s} carried over, nothing changed in them"
ADOPT_FRIEND = "the practice book is now the book: the same records, no longer marked PAPER"
ADOPT_BOTH = "both the practice book and the book have records — they were not merged; this is the book"
ADOPT_UNREADABLE = "the practice book's file could not be read — nothing was moved; this is the book"


def adopt() -> str:
    """(PORTFOLIO_PAPER False) The practice book's records become the book's, unchanged (ids, dates, by, fx, why), when
    the book has none — book.json written, paper.json renamed paper.adopted-<stamp>.json (never deleted), pending
    records retagged real, the friend's last-seen id carried so their next look doesn't list them as news. Both books
    with records: nothing merged. An unreadable paper.json: nothing moved. Under the lock; safe twice and from two
    processes (the second finds it done). Returns "adopted", "both", "unreadable", "busy" or "" (nothing to do)."""
    try:
        with _locked():
            f = folder() / BOOKS["paper"]
            if not f.exists():
                return ""
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(d, dict) or not isinstance(d.get("records"), list) or \
                        not all(isinstance(r, dict) and not _bad_field(r) for r in d["records"]):
                    raise ValueError("not a book")
            except (OSError, ValueError):
                _note_state("adopt_problem", "unreadable")
                _log("adoption: paper.json could not be read — nothing was moved")
                return "unreadable"
            if not d["records"]:
                return ""
            real = folder() / BOOKS["real"]
            if real.exists():
                try:
                    rd = json.loads(real.read_text(encoding="utf-8"))
                    has = bool(rd.get("records")) if isinstance(rd, dict) else True
                except (OSError, ValueError):
                    has = True  # an unreadable book is not written over
                if has:
                    _note_state("adopt_problem", "both")
                    _log("adoption: both books have records — nothing was merged")
                    return "both"
            if not _save_locked("real", d):
                _log("adoption: the book couldn't be written — nothing was moved")
                return ""
            os.replace(f, f.with_name(f"paper.adopted-{datetime.now():%Y%m%d-%H%M%S}.json"))
            items = pending()
            if any(x.get("book") == "paper" for x in items):
                for x in items:
                    if x.get("book") == "paper":
                        x["book"] = "real"
                _save_pending(items)
            s_ = state()
            ids = s_.get("last_id") if isinstance(s_.get("last_id"), dict) else {}
            if "paper" in ids:
                ids["real"] = ids["paper"]
            s_["last_id"] = ids
            s_["open"] = "real"
            s_["adopted"] = {"n": len(d["records"]), "at": time.time(), "phone": False, "friend": False}
            s_.pop("adopt_problem", None)
            _write("state.json", s_)
            _log(f"adoption: the practice book is now the book — {len(d['records'])} records carried over unchanged")
            return "adopted"
    except BookBusy:
        _ADOPT_LOOKED[0] = False  # tried again at the next use
        return "busy"


def _note_state(key: str, value) -> None:
    s_ = state()
    s_[key] = value
    _write("state.json", s_)


def adoption_news(who: str, standing: bool = True) -> str:
    """The adoption said once to "phone" or to "friend"; for the phone, a standing problem (both books, an unreadable
    practice book) is said each time. "" when there is nothing to say."""
    if paper_on():
        return ""
    _maybe_adopt()
    s_ = state()
    a = s_.get("adopted") if isinstance(s_.get("adopted"), dict) else None
    if a and not a.get(who):
        try:
            with _locked():
                s2 = state()
                a2 = s2.get("adopted") if isinstance(s2.get("adopted"), dict) else None
                if not a2 or a2.get(who):
                    return ""
                a2[who] = True
                _write("state.json", s2)
        except BookBusy:
            return ""
        n = int(a.get("n") or 0)
        return ADOPT_PHONE.format(n=n, s="" if n == 1 else "s") if who == "phone" else ADOPT_FRIEND
    if who == "phone" and standing and (folder() / BOOKS["paper"]).exists():
        prob = s_.get("adopt_problem")
        return ADOPT_BOTH if prob == "both" else ADOPT_UNREADABLE if prob == "unreadable" else ""
    return ""


def set_open(which: str) -> bool:
    if not paper_on():
        which = "real"
    try:
        with _locked():
            s = state()
            s["open"] = which if which in BOOKS else "paper"
            return save_state(s)
    except BookBusy:
        return False


def _broken(which: str) -> list[Path]:
    stem = BOOKS[which][:-5]
    return sorted(folder().glob(f"{stem}.broken-*.json"))


def _bad_field(r: dict) -> str:
    """The first field of a record that isn't what it must be — "" when the record reads right."""
    try:
        int(r["id"])
    except (TypeError, ValueError, KeyError):
        return f"id {r.get('id')!r}"
    if r.get("kind") not in KINDS:
        return f"kind {r.get('kind')!r}"
    try:
        date.fromisoformat(str(r.get("date")))
    except ValueError:
        return f"date {r.get('date')!r}"
    if r.get("kind") == "convert":  # money moved between two currencies' cash
        if not re.fullmatch(r"[A-Z]{3}", str(r.get("currency") or "")) \
                or not re.fullmatch(r"[A-Z]{3}", str(r.get("to_currency") or "")) or r.get("currency") == r.get("to_currency"):
            return f"currencies {r.get('currency')!r} → {r.get('to_currency')!r}"
        v = r.get("to_amount")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) == float("inf"):
            return f"to_amount {v!r}"
    optional = {"fx", "fee"} | ({"price"} if r.get("kind") == "split" else set())
    for f in ("qty", "price", "fee", "fx"):
        v = r.get(f)
        if v is None and f in optional:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) == float("inf"):
            return f"{f} {v!r}"
    return ""


def load(which: str | None = None) -> dict:
    """The book's {"records", "next_id"}. A file that doesn't parse, or isn't a book's shape, is set aside (never written
    over) and BookUnreadable raised; while a set-aside book is there and none in its place, the book stays unreadable.
    A file that can't be read just now (a lock, a permission) is left where it is. A record with a field that isn't
    right makes the book unreadable as it stands — named, not set aside, not skipped."""
    which = which or open_book()
    with _LOCK:
        f = folder() / BOOKS[which]
        if not f.exists():
            if _broken(which):
                raise BookUnreadable(f"the book could not be read — it was set aside as {_broken(which)[-1].name}; "
                                     "nothing was written in its place (it needs a look by hand)")
            return {"records": [], "next_id": 1}
        try:
            raw = f.read_text(encoding="utf-8")
        except OSError as e:
            raise BookUnreadable(f"the book could not be read just now ({type(e).__name__}) — nothing was moved; it is "
                                 "tried again next time") from None
        try:
            d = json.loads(raw)
            if not isinstance(d, dict) or not isinstance(d.get("records"), list) or \
                    not all(isinstance(r, dict) for r in d["records"]):
                raise ValueError("not a book")
        except ValueError:
            aside = f.with_name(f"{BOOKS[which][:-5]}.broken-{datetime.now():%Y%m%d-%H%M%S}.json")
            try:
                os.replace(f, aside)
            except OSError:
                pass
            raise BookUnreadable(f"the book could not be read — it was set aside as {aside.name}; nothing was written "
                                 "in its place (it needs a look by hand)") from None
        for r in d["records"]:
            bad = _bad_field(r)
            if bad:
                raise BookUnreadable(f"the book is unreadable: record #{r.get('id')} has {bad} — nothing was changed; "
                                     "no totals until it is mended")
        d.setdefault("next_id", 1 + max((int(r["id"]) for r in d["records"]), default=0))
        return d


def _save(which: str, book: dict) -> bool:
    try:
        with _locked():
            return _save_locked(which, book)
    except BookBusy:
        return False


def _save_locked(which: str, book: dict) -> bool:
    if not _write(BOOKS[which], book):
        return False
    try:  # one dated copy a day it changed, the newest PORTFOLIO_BACKUPS of each book
        b = folder() / "backups"
        b.mkdir(parents=True, exist_ok=True)
        stem = BOOKS[which][:-5]
        shutil.copyfile(folder() / BOOKS[which], b / f"{stem}-{date.today().isoformat()}.json")
        keep = int(getattr(config, "PORTFOLIO_BACKUPS", 30) or 30)
        old = sorted(b.glob(f"{stem}-*.json"))
        for p in old[:-keep]:
            p.unlink()
    except Exception:  # noqa: BLE001
        pass
    return True


# ---- numbers -----------------------------------------------------------------------------------------------------
def num(text) -> float | None:
    """A number as the keeper types it: "1,250.50", "€133.3", "$210", "1 250", "0.5", "210 USD". None when it isn't
    one — no exponents, no underscores, no digits of other scripts, and no lone decimal comma ("1,25" is asked again,
    not guessed)."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        v = float(text)
        return v if v == v and abs(v) != float("inf") else None
    t = str(text or "").strip()
    for s in SYMBOLS.values():
        t = t.replace(s, "")
    t = re.sub(r"^[A-Z]{3}|[A-Z]{3}$", "", t.strip(), flags=re.ASCII)
    t = t.replace(" ", "").replace(" ", "").strip()
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", t, re.ASCII):
        t = t.replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?|-?\.\d+", t, re.ASCII):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v == v and abs(v) != float("inf") else None


def money(v: float, cur: str) -> str:
    sign = "-" if v < 0 else ""
    s = SYMBOLS.get(cur, "")
    return f"{sign}{s}{abs(v):,.2f}" + ("" if s else f" {cur}")


def currency_of(text) -> str:
    """A currency as typed — a code, a sign or a word — as its three-letter code; "" when it isn't one."""
    c = str(text or "").strip().upper()
    c = CURRENCY_WORDS.get(c, c)
    return c if re.fullmatch(r"[A-Z]{3}", c) else ""


def _day(d) -> str:
    try:
        dd = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
        return f"{dd:%b} {dd.day}"
    except ValueError:
        return str(d)


def parse_date(text, today: date | None = None) -> date | None:
    today = today or date.today()
    t = str(text or "").strip().lower()
    if t in ("", "today"):
        return today
    if t == "yesterday":
        return today - timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d/%m/%y", "%d.%m.%y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})", t)
    if m:
        try:
            d = date(today.year, int(m.group(2)), int(m.group(1)))
            return d if d <= today else date(today.year - 1, d.month, d.day)
        except ValueError:
            return None
    return None


# ---- the feed ----------------------------------------------------------------------------------------------------
def _get(url: str) -> dict:
    """Every fetch: none at all while the house is offline (OFFLINE) — the cache answers."""
    if getattr(config, "OFFLINE", False):
        raise OfflineError("this house is offline (OFFLINE) — the feed isn't asked")
    return _http_get(url)


def _http_get(url: str, timeout: float = TIMEOUT_S) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _chart(symbol: str, rng: str = "5d", until: float | None = None) -> dict:
    """The chart feed's result[0] for a symbol; raises with a short reason. A feed that failed in the last FEED_DOWN_S
    seconds is not asked again (the cache answers at once)."""
    if time.time() < _FEED["down_until"]:
        raise RuntimeError("the feed didn't answer a moment ago — not asked again yet")
    if until is not None and time.time() > until:
        raise RuntimeError("this look's time for fetching is spent — the cache answers")
    try:
        d = _get(CHART.format(sym=urllib.parse.quote(symbol, safe=""), rng=rng))
    except OfflineError as e:
        raise RuntimeError(str(e)) from None
    except Exception as e:  # noqa: BLE001
        if getattr(e, "code", None) == 404:
            raise LookupError(_why(e)) from None
        _FEED["down_until"] = time.time() + FEED_DOWN_S
        raise RuntimeError(_why(e)) from None
    res = ((d or {}).get("chart") or {}).get("result") if isinstance(d, dict) else None
    if not res or not isinstance(res, list) or not isinstance(res[0], dict) or not res[0].get("meta"):
        err = (((d or {}).get("chart") or {}).get("error") or {}) if isinstance(d, dict) else {}
        raise LookupError(str((err or {}).get("description") or "the feed doesn't know it"))
    return res[0]


def _why(e: Exception) -> str:
    code = getattr(e, "code", None)
    if code == 404:
        return "the feed doesn't know it (404)"
    if code:
        return f"the feed answered {code}"
    if isinstance(e, ValueError):
        return "the feed's answer wasn't readable"
    n = type(e).__name__
    return "the feed didn't answer in time" if "timeout" in (n + str(e)).lower() else f"the feed didn't answer ({n})"


def _bars(res: dict) -> list[tuple[date, float, int]]:
    meta = res.get("meta") or {}
    off = int(meta.get("gmtoffset") or 0)
    ts = res.get("timestamp") or []
    q = (((res.get("indicators") or {}).get("quote") or [{}])[0] or {}).get("close") or []
    out = []
    for t, c in zip(ts, q):
        if c is None or t is None:
            continue
        try:
            out.append((datetime.fromtimestamp(int(t) + off, timezone.utc).date(), float(c), int(t)))
        except (TypeError, ValueError, OverflowError):
            continue
    return out


def _parse_quote(asked: str, res: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    meta = res.get("meta") or {}
    raw = str(meta.get("currency") or "").strip()
    minor = MINOR.get(raw)  # before upper-casing: GBp (pence) is not GBP
    cur = minor[0] if minor else raw.upper()
    div = minor[1] if minor else 1.0
    bars = _bars(res)
    period = ((meta.get("currentTradingPeriod") or {}).get("regular") or {})
    off = int(meta.get("gmtoffset") or 0)
    today_ex = datetime.fromtimestamp(now + off, timezone.utc).date()
    end = period.get("end")
    done = bars
    if bars and bars[-1][0] >= today_ex and not (isinstance(end, (int, float)) and now >= end):
        done = bars[:-1]  # today's bar is not a completed day yet
    q = {"symbol": str(meta.get("symbol") or asked), "asked": asked, "currency": cur or "?",
         "minor": minor[2] if minor else "", "major": minor[3] if minor else "", "source": "Yahoo", "fetched_at": now,
         "name": str(meta.get("longName") or meta.get("shortName") or "").strip(),
         "exchange": str(meta.get("exchangeName") or "")}
    if done:
        q["close"], q["close_date"] = round(done[-1][1] / div, 6), done[-1][0].isoformat()
        # when that session ended: the feed's session end on that day, else the last trade of that day, else the
        # end of that day — for an alert set after a close (it must not fire on it)
        lt_ = meta.get("regularMarketTime")
        cd_ = done[-1][0]
        if isinstance(end, (int, float)) and datetime.fromtimestamp(int(end) + off, timezone.utc).date() == cd_:
            q["close_end"] = int(end)
        elif isinstance(lt_, (int, float)) and datetime.fromtimestamp(int(lt_) + off, timezone.utc).date() == cd_:
            q["close_end"] = int(lt_)
        else:
            q["close_end"] = int(datetime(cd_.year, cd_.month, cd_.day, 23, 59, 59, tzinfo=timezone.utc).timestamp()) - off
        if len(done) > 1:
            q["prev_close"], q["prev_date"] = round(done[-2][1] / div, 6), done[-2][0].isoformat()
    # no completed daily bar: no close — a price without its date is not shown
    last = meta.get("regularMarketPrice")
    lt = meta.get("regularMarketTime")
    if isinstance(last, (int, float)) and isinstance(lt, (int, float)):
        q["last"], q["last_time"] = round(float(last) / div, 6), int(lt)
        ld = datetime.fromtimestamp(int(lt) + off, timezone.utc).date()
        q["last_date"] = ld.isoformat()
        # a last trade newer than the last daily bar, while the market is not open now, IS that session's close (a
        # feed can be late with the day's bar; its last trade then is called "now" though the session ended)
        if "close_date" not in q or ld.isoformat() > q["close_date"]:
            age = now - int(lt)
            if ld < today_ex:  # an earlier day's last trade, the market not trading it now
                closed = age > 20 * 60
            else:  # dated today: the close only once the session has ended (no end in the feed: never — "now")
                closed = isinstance(end, (int, float)) and now >= end
            if closed:
                if "close" in q:
                    q["prev_close"], q["prev_date"] = q["close"], q["close_date"]
                else:
                    q.pop("prev_close", None)
                    q.pop("prev_date", None)
                q["close"], q["close_date"], q["close_from_trade"] = q["last"], ld.isoformat(), True
                q["close_end"] = int(lt)
    ev = res.get("events") or {}
    splits = []
    for v in ((ev.get("splits") or {}).values() if isinstance(ev.get("splits"), dict) else []):
        try:
            n_, d_ = float(v.get("numerator") or 0), float(v.get("denominator") or 0)
            if n_ > 0 and d_ > 0:
                splits.append({"date": datetime.fromtimestamp(int(v["date"]) + off, timezone.utc).date().isoformat(),
                               "ratio": n_ / d_, "text": str(v.get("splitRatio") or f"{n_:g}:{d_:g}")})
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
            continue
    divs = []
    for v in ((ev.get("dividends") or {}).values() if isinstance(ev.get("dividends"), dict) else []):
        try:
            divs.append({"date": datetime.fromtimestamp(int(v["date"]) + off, timezone.utc).date().isoformat(),
                         "amount": round(float(v["amount"]) / div, 6)})
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
            continue
    q["splits"], q["dividends"] = sorted(splits, key=lambda x: x["date"]), sorted(divs, key=lambda x: x["date"])
    jump_limit = float(getattr(config, "PORTFOLIO_JUMP", 0.25) or 0.25)
    if q.get("close") and q.get("prev_close"):
        split_between = any(q["prev_date"] < s["date"] <= q["close_date"] for s in splits)
        q["jump"] = (not split_between) and abs(q["close"] / q["prev_close"] - 1) > jump_limit
    return q


def quote(symbol: str, refresh: bool = False, until: float | None = None) -> dict:
    """The quote for a symbol as asked (no guessing at other forms): {"ok", close, close_date, currency, …}. A fetch
    that fails gives the cached quote with "stale" and the reason; none cached — {"ok": False, "error"}. Never raises."""
    symbol = str(symbol or "").strip()
    if not symbol:
        return {"ok": False, "asked": symbol, "error": "no symbol"}
    cache = _read("prices.json", {})
    cache = cache if isinstance(cache, dict) else {}
    key = symbol.upper()
    c = cache.get(key) if isinstance(cache.get(key), dict) else None
    fresh_s = float(getattr(config, "PORTFOLIO_PRICE_CACHE_MIN", 30) or 30) * 60
    if c and not refresh and time.time() - float(c.get("fetched_at") or 0) < fresh_s:
        return dict(c, ok=True, cached=True)
    try:
        q = _parse_quote(symbol, _chart(symbol, until=until))
        if "close" not in q:
            if q.get("last") is None or not q.get("last_time"):
                raise LookupError("no close in the feed's answer")
            q["no_close"] = True  # a first day of trading: the last trade with its time, no close yet
    except LookupError as e:
        if c:
            return dict(c, ok=True, stale=True, error=str(e))
        return {"ok": False, "asked": symbol, "error": str(e), "unknown": True}
    except Exception as e:  # noqa: BLE001
        if c:
            return dict(c, ok=True, stale=True, error=str(e))
        return {"ok": False, "asked": symbol, "error": str(e)}
    q["asked_at"] = time.time()
    keep = _held_symbols()  # read before the lock: the books aren't changed by this
    try:
        with _locked():
            cache = _read("prices.json", {})
            cache = cache if isinstance(cache, dict) else {}
            cache[key] = q
            _write("prices.json", _pruned(cache, keep))
    except BookBusy:
        pass  # a cache that wasn't written is asked again next time
    return dict(q, ok=True)


def _held_symbols() -> set:
    keep = set()
    for which in (BOOKS if paper_on() else ("real",)):
        try:
            keep |= {str(r.get("symbol") or "").upper() for r in load(which)["records"]}
        except BookUnreadable:
            pass
    return keep


def _pruned(cache: dict, keep: set | None = None) -> dict:
    """The price cache keeps the rates, symbols in either book, and those asked in the last 7 days."""
    keep = _held_symbols() if keep is None else keep
    week = time.time() - 7 * 86400
    return {k: v for k, v in cache.items()
            if k.startswith("__fx__") or k in keep
            or (isinstance(v, dict) and float(v.get("asked_at") or v.get("fetched_at") or 0) > week)}


def find(symbol: str) -> dict:
    """A symbol as typed, then upper-cased, then with the home currency's exchange suffix (SUFFIX), if it has one:
    {"ok", "quote", "tried", "same"} — "same" False when the one that answered is not the form asked (the keeper must
    confirm it; never a silent swap)."""
    s = str(symbol or "").strip()
    suf = SUFFIX.get(home(), "")
    forms = []
    for f in (s, s.upper(), (s.upper() + suf) if suf and s and not s.upper().endswith(suf) and not s.startswith("^") else ""):
        if f and f not in forms:
            forms.append(f)
    tried = []
    for f in forms:
        q = quote(f)
        tried.append(f)
        if q.get("ok"):
            return {"ok": True, "quote": q, "tried": tried, "same": f.upper() == s.upper()}
        if not q.get("unknown"):
            return {"ok": False, "tried": tried, "error": q.get("error") or "no answer"}
    return {"ok": False, "tried": tried, "error": "the feed knows none of them"}


def at_trade(q: dict) -> bool:
    """True when the feed's last trade is newer than its last completed daily close (a market open, or a first-day
    share): then the holding is valued at that trade. A last trade older than the newest close is not used."""
    last, lt, close = q.get("last"), q.get("last_time"), q.get("close")
    if last is None or not lt:
        return False
    try:
        ld = q.get("last_date") or datetime.fromtimestamp(int(lt)).date().isoformat()
        return close is None or str(ld) > str(q.get("close_date"))
    except (TypeError, ValueError, OverflowError, OSError):
        return False


def price_of(q: dict) -> float | None:
    """The price a holding is valued at, one rule everywhere (the book, the friend's look, /trade <symbol>, the
    brief): the latest the feed has — the last trade when it is newer than the last completed close, otherwise that
    close."""
    if at_trade(q):
        return float(q["last"])
    if q.get("close") is not None:
        return float(q["close"])
    return None


def _at(ts) -> str:
    t = datetime.fromtimestamp(int(ts))
    return f"{t:%b} {t.day} {t:%H:%M}"


def quote_line(q: dict) -> str:
    """One line for a quote: "ACME $212.30 (close Nov 18, Yahoo)" with what else is true of it."""
    if not q.get("ok"):
        return f"{q.get('asked') or '?'}: no price — {q.get('error') or 'not known'}"
    cur = q.get("currency") or "?"
    minor = f"; quoted in {q['minor']}" if q.get("minor") else ""
    if q.get("close") is None:  # no completed daily close yet: the last trade, with its time — said so
        line = (f"{q['symbol']} {money(float(q['last']), cur)} (last trade {_at(q['last_time'])}, "
                f"{q.get('source', 'Yahoo')}{minor}) · no completed daily close yet")
        return (f"{q['name']} · " if q.get("name") else "") + line + (" · (could not be fetched now)" if q.get("stale") else "")
    bits = [f"{q['symbol']} {money(float(q['close']), cur)} (close {_day(q.get('close_date'))}, {q.get('source', 'Yahoo')}"
            + ("; from the last trade — the day's bar isn't in the feed yet" if q.get("close_from_trade") else "")
            + minor + ")"]
    if q.get("name"):
        bits[0] = f"{q['name']} · " + bits[0]
    if q.get("last") is not None and q.get("last_time"):
        t = datetime.fromtimestamp(int(q["last_time"]))
        bits.append(f"last {money(float(q['last']), cur)} at {t:%b} {t.day} {t:%H:%M}")
    if q.get("stale"):
        bits.append("(could not be fetched now)")
    if q.get("jump"):
        bits.append(f"⚠ check this — {abs(q['close'] / q['prev_close'] - 1):.0%} from the close of {_day(q.get('prev_date'))}")
    return " · ".join(bits)


# ---- rates -------------------------------------------------------------------------------------------------------
def _yahoo_syms(h: str, ccy: str) -> list[str]:
    """The <CCY>=X symbols (units per dollar) that give h per one ccy: one when either is the dollar, else both."""
    if ccy == "USD":
        return [f"{h}=X"]
    if h == "USD":
        return [f"{ccy}=X"]
    return [f"{h}=X", f"{ccy}=X"]


def _per_usd(res: dict) -> tuple[float | None, object]:
    meta = res.get("meta") or {}
    r = meta.get("regularMarketPrice")
    if not isinstance(r, (int, float)):
        bars = _bars(res)
        r = bars[-1][1] if bars else None
    return (float(r) if isinstance(r, (int, float)) and r > 0 else None), meta.get("regularMarketTime")


def rate(ccy: str = "USD", until: float | None = None) -> dict:
    """Units of the home currency per one ccy now: {"ok", "rate", "source", "time", "home", "ccy"}. The home
    currency's official source first (OFFICIAL), Yahoo's <CCY>=X as the fallback, the cached one with its time when
    neither answers. Never raises."""
    h = home()
    ccy = str(ccy or "USD").upper()
    if ccy == h:
        return {"ok": True, "rate": 1.0, "source": "the same currency", "time": "", "home": h, "ccy": ccy}
    key = f"__fx__{h}/{ccy}"
    cache = _read("prices.json", {})
    cache = cache if isinstance(cache, dict) else {}
    c = cache.get(key) if isinstance(cache.get(key), dict) else None
    fresh_s = float(getattr(config, "PORTFOLIO_PRICE_CACHE_MIN", 30) or 30) * 60
    if c and time.time() - float(c.get("fetched_at") or 0) < fresh_s:
        return dict(c, ok=True)
    got = None
    off = OFFICIAL.get(h)
    if off:
        try:
            if time.time() < _FEED.get("official_down_until", 0.0) or (until is not None and time.time() > until):
                raise RuntimeError("down a moment ago, or this look's time is spent")
            have = off["read"](_get(off["url"]))
            if ccy in have:
                got = {"rate": have[ccy][0], "source": off["name"], "time": have[ccy][1], "fetched_at": time.time()}
        except Exception:  # noqa: BLE001
            _FEED["official_down_until"] = time.time() + FEED_DOWN_S
            got = None
    if got is None:
        try:
            syms = _yahoo_syms(h, ccy)
            vals = [_per_usd(_chart(s, until=until)) for s in syms]
            if all(v is not None for v, _ in vals):
                if ccy == "USD":
                    r = vals[0][0]
                elif h == "USD":
                    r = 1.0 / vals[0][0]
                else:
                    r = vals[0][0] / vals[1][0]
                t = vals[0][1]
                got = {"rate": float(r), "source": "Yahoo " + " and ".join(syms),
                       "time": datetime.fromtimestamp(int(t), timezone.utc).isoformat() if isinstance(t, (int, float)) else "",
                       "fetched_at": time.time()}
        except Exception:  # noqa: BLE001
            got = None
    if got is None:
        if c:
            return dict(c, ok=True, stale=True)
        return {"ok": False, "home": h, "ccy": ccy,
                "error": f"neither the {off['name']} nor Yahoo answered" if off else "Yahoo didn't answer"}
    got.update(home=h, ccy=ccy)
    try:
        with _locked():
            cache = _read("prices.json", {})
            cache = cache if isinstance(cache, dict) else {}
            cache[key] = got
            _write("prices.json", cache)
    except BookBusy:
        pass
    return dict(got, ok=True)


def rate_line(r: dict) -> str:
    if not r.get("ok"):
        return "rate: not known — " + str(r.get("error") or "")
    t = str(r.get("time") or "")
    when = ""
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone()
        when = f", {dt:%b} {dt.day} {dt:%H:%M}"
    except ValueError:
        pass
    pair = f"{sym(r.get('home') or home())}/{sym(r.get('ccy') or 'USD')}"
    return f"{r['rate']:.4f} {pair} ({r['source']}{when})" + (" (could not be fetched now)" if r.get("stale") else "")


def _short_rate_line(r: dict) -> str:
    """The compact block's rate: the source's short name between dots."""
    rl = rate_line(r)
    if "(" not in rl or r.get("stale"):
        return rl
    for o in OFFICIAL.values():
        rl = rl.replace(f" ({o['name']}, ", f" · {o['short']} · ")
    return re.sub(r" \(Yahoo [^,()]*, ", " · Yahoo · ", rl).rstrip(")")


def rate_on(day: date, ccy: str = "USD") -> tuple[float | None, str]:
    """Units of the home currency per one ccy on a day: today's rate for today; else Yahoo's daily closes of that day
    or the nearest earlier one. (None, why) when not known."""
    h = home()
    if day >= date.today():
        r = rate(ccy)
        return (r["rate"], r["source"]) if r.get("ok") else (None, "not known")
    days = (date.today() - day).days
    rng = "1mo" if days < 25 else "3mo" if days < 85 else "1y" if days < 360 else "5y"
    syms = _yahoo_syms(h, ccy)
    got = []
    try:
        for s in syms:
            before = [b for b in _bars(_chart(s, rng)) if b[0] <= day]
            if not before:
                return None, "not known"
            got.append(before[-1])
    except Exception:  # noqa: BLE001
        return None, "not known"
    if ccy == "USD":
        v = got[0][1]
    elif h == "USD":
        v = 1.0 / got[0][1] if got[0][1] else None
    else:
        v = got[0][1] / got[1][1] if got[1][1] else None
    if not v:
        return None, "not known"
    return v, f"Yahoo {' and '.join(syms)} close of {_day(got[0][0])}"


def _ref_ccy(cur: str) -> str:
    """The currency a record's rate is for: its own when it isn't the home currency; the dollar for one in the home
    currency when home isn't the dollar; "" — no rate — when both are the dollar."""
    h = home()
    if cur != h:
        return cur
    return "USD" if h != "USD" else ""


# ---- the record --------------------------------------------------------------------------------------------------
def make_record(kind: str, symbol: str = "", qty=None, price=None, day=None, fee=None, why: str = "",
                currency: str | None = None, fx=None, by: str = "keeper", which: str | None = None) -> tuple[dict | None, str]:
    """A record checked against the book and the feed — (record, "") or (None, the plain reason). Nothing written."""
    kind = str(kind or "").strip().lower()
    kind = {"withdrawal": "withdraw", "div": "dividend", "bought": "buy", "sold": "sell"}.get(kind, kind)
    if kind not in KINDS or kind == "split":
        return None, "kind is one of: buy, sell, deposit, withdraw, dividend, fee"
    d = parse_date(day) if not isinstance(day, date) else day
    if d is None:
        return None, f"the date “{day}” isn't one — YYYY-MM-DD, today or yesterday"
    if d > date.today():
        return None, "that date hasn't come yet"
    f = num(fee) if fee not in (None, "") else 0.0
    if f is None or f < 0:
        return None, f"the fee “{fee}” isn't a number"
    rec = {"date": d.isoformat(), "kind": kind, "symbol": "", "qty": 1.0, "price": None, "currency": "",
           "fx": None, "fx_source": "", "fee": round(f, 6), "why": " ".join(str(why or "").split())[:200], "by": by}
    if kind in ("deposit", "withdraw", "fee"):
        cur = currency_of(currency or symbol)
        if not cur:
            return None, (f"a deposit, withdrawal or fee is in one currency — give its three-letter code as symbol "
                          f"(\"{home()}\", \"USD\", \"EUR\" …)")
        amt = num(price if price not in (None, "") else qty)
        if amt is None or amt <= 0:
            return None, "the amount isn't a number above zero (give it as price)"
        rec.update(currency=cur, price=round(amt, 6))
    else:
        found = find(symbol)
        if not found["ok"]:
            return None, (f"no price for “{symbol}” — tried {', '.join(found['tried']) or 'nothing'}: "
                          f"{found.get('error') or 'not known'}")
        q = found["quote"]
        if not found["same"]:
            return None, (f"“{symbol}” isn't known to the feed; {q['symbol']} is ({quote_line(q)}) — if that is the one, "
                          f"record it as {q['symbol']}")
        rec["symbol"], rec["currency"] = q["symbol"].upper(), q["currency"]
        if not re.fullmatch(r"[A-Z]{3}", rec["currency"] or ""):
            return None, f"{q['symbol']} is quoted in “{q['currency']}” — not a currency the book can keep"
        if kind == "dividend":
            amt = num(price if price not in (None, "") else qty)
            if amt is None or amt <= 0:
                return None, "the dividend's amount isn't a number above zero (give the total received as price)"
            rec["price"] = round(amt, 6)
            try:
                no = _div_fits(load(which)["records"], rec)
            except BookUnreadable as e:
                return None, str(e)
            if no:
                return None, no
        else:
            n = num(qty)
            p = num(price)
            if n is None or n <= 0:
                return None, f"qty “{qty}” isn't a number of shares above zero"
            if p is None or p <= 0:
                return None, f"price “{price}” isn't a price above zero"
            close = float(price_of(q) or 0)
            if close and 50 <= p / close <= 200 and q.get("minor"):
                said = (f"closed at {money(close, q['currency'])} ({_day(q.get('close_date'))})" if not at_trade(q)
                        else f"last traded at {money(close, q['currency'])} ({_at(q['last_time'])})")
                return None, f"{p:,.2f} looks like {q['minor']} — {q['symbol']} {said}; give the price in {q.get('major') or q['currency']}"
            rec["qty"], rec["price"] = round(n, 6), round(p, 6)
            if kind == "sell":
                try:
                    no = _sell_fits(load(which)["records"], rec)
                except BookUnreadable as e:
                    return None, str(e)
                if no:
                    return None, no
    ref = _ref_ccy(rec["currency"])
    if fx not in (None, ""):
        v = num(fx)
        if v is None or v <= 0:
            return None, f"the rate “{fx}” isn't a number"
        if not ref:
            return None, f"a rate isn't needed — the book and this record are both in {rec['currency']}"
        rec["fx"], rec["fx_source"] = round(v, 6), "given"
    elif ref:
        v, src = rate_on(d, ref)
        rec["fx"], rec["fx_source"] = (round(v, 6) if v else None), src
    if ref:
        rec["fx_ccy"], rec["fx_home"] = ref, home()
    return rec, ""


def pair_rate(from_ccy: str, to_ccy: str, until: float | None = None) -> dict:
    """Units of to_ccy per one from_ccy now, from the home currency's rates (rate()): {"ok", "per"} or {"ok": False,
    "error"}. Never raises."""
    rf, rt = rate(from_ccy, until=until), rate(to_ccy, until=until)
    if not (rf.get("ok") and rt.get("ok")) or not rt.get("rate"):
        return {"ok": False, "error": (rf if not rf.get("ok") else rt).get("error") or "no rate"}
    return {"ok": True, "per": float(rf["rate"]) / float(rt["rate"])}


def conv_shown(from_ccy: str, to_ccy: str, per: float) -> tuple[float, str]:
    """A conversion's rate as it is said: home per the other currency when one side is home, else to per from."""
    h = home()
    if from_ccy == h and per:
        return 1.0 / per, f"{sym(h)}/{sym(to_ccy)}"
    return per, f"{sym(to_ccy)}/{sym(from_ccy)}"


def make_convert(from_ccy: str, from_amt, to_ccy: str, to_amt, day=None, fee=None, fee_ccy: str | None = None,
                 why: str = "", by: str = "keeper") -> tuple[dict | None, str]:
    """A conversion: from_amt of one currency's cash became to_amt of another's (what the broker really gave). Its
    rate is to_amt/from_amt; one more than CONVERT_BAND times away from the fetched rate for the pair is refused as a
    typo (no fetched rate: not checked). Nothing written."""
    fc, tc = currency_of(from_ccy), currency_of(to_ccy)
    if not fc or not tc:
        return None, "a conversion is between two currencies — give each by its three-letter code"
    if fc == tc:
        return None, f"a conversion is between two currencies — both are {fc}"
    a, b = num(from_amt), num(to_amt)
    if a is None or a <= 0:
        return None, f"the amount converted “{from_amt}” isn't a number above zero"
    if b is None or b <= 0:
        return None, f"the amount that arrived “{to_amt}” isn't a number above zero"
    d = parse_date(day) if not isinstance(day, date) else day
    if d is None:
        return None, f"the date “{day}” isn't one — YYYY-MM-DD, today or yesterday"
    if d > date.today():
        return None, "that date hasn't come yet"
    f = num(fee) if fee not in (None, "") else 0.0
    if f is None or f < 0:
        return None, f"the fee “{fee}” isn't a number"
    fcc = currency_of(fee_ccy or fc)
    if fcc not in (fc, tc):
        return None, f"the fee is in {fc} or {tc}"
    per = b / a
    known = pair_rate(fc, tc)
    if known.get("ok") and known["per"] > 0 and not (1 / CONVERT_BAND <= per / known["per"] <= CONVERT_BAND):
        shown, label = conv_shown(fc, tc, per)
        now_, _ = conv_shown(fc, tc, known["per"])
        return None, f"that is a rate of {shown:.4f} {label}, and today's is {now_:.4f} — check the two amounts"
    return {"date": d.isoformat(), "kind": "convert", "symbol": "", "qty": 1.0, "price": round(a, 6), "currency": fc,
            "to_amount": round(b, 6), "to_currency": tc, "fx": round(per, 6), "fx_source": "the conversion itself",
            "fee": round(f, 6), "fee_currency": fcc, "why": " ".join(str(why or "").split())[:200], "by": by}, ""


def _div_fits(records: list[dict], rec: dict) -> str:
    """A dividend comes from a holding: refused when the symbol was never held on or before its date."""
    if any(r.get("kind") == "buy" and r.get("symbol") == rec["symbol"] and str(r.get("date")) <= rec["date"]
           for r in live(records)):
        return ""
    return (f"the book never held {rec['symbol']} on or before {_day(rec['date'])}, so a dividend from it can't be "
            "counted — if the money came in, record it as a deposit")


def timeline_error(records: list[dict]) -> str:
    """The first record at which a holding goes below zero, in the book's order (date; within a day buys, deposits
    and splits before sells and withdrawals; then the record's place) — "" when none. A record marked "_cand" is the
    one being checked, and is named as "that"."""
    held: dict[str, float] = {}
    for r in live(records):
        s = r.get("symbol") or ""
        try:
            q = float(r.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if r.get("kind") == "buy":
            held[s] = held.get(s, 0.0) + q
        elif r.get("kind") == "split" and q > 0:
            held[s] = held.get(s, 0.0) * q
        elif r.get("kind") == "sell":
            if q > held.get(s, 0.0) + 1e-9:
                if r.get("_cand"):
                    return (f"it would sell {q:g} {s} on {_day(r.get('date'))}, and only {held.get(s, 0.0):g} "
                            "would be held then")
                return (f"#{r['id']} sold {q:g} {s} on {_day(r.get('date'))} — only {held.get(s, 0.0):g} would "
                        "have been held then")
            held[s] = held.get(s, 0.0) - q
    return ""


_NEW_ID = 10 ** 12  # a record not yet kept: last in its day's group


def _sell_fits(records: list[dict], rec: dict) -> str:
    """A new sell against the book: what was held on its date, and every later sell still covered. "" when it fits."""
    held = 0.0
    s = rec["symbol"]
    for r in live(records):  # a new sell comes last on its day: every buy that day counts before it
        if str(r.get("date")) > rec["date"]:
            break
        if r.get("symbol") != s:
            continue
        if r.get("kind") == "buy":
            held += float(r.get("qty") or 0)
        elif r.get("kind") == "sell":
            held -= float(r.get("qty") or 0)
        elif r.get("kind") == "split" and float(r.get("qty") or 0) > 0:
            held *= float(r["qty"])
    if rec["qty"] > held + 1e-9:
        later = [r for r in live(records) if r.get("symbol") == s and r.get("kind") == "buy" and str(r.get("date")) > rec["date"]]
        first = f"; the first buy is {_day(later[0]['date'])}" if later and held <= 1e-9 else ""
        return (f"that sells {rec['qty']:g} {s} on {_day(rec['date'])}, but on {_day(rec['date'])} the book held "
                f"{held:g} {s}{first} — a sell can't be more than is held")
    after = timeline_error(records + [dict(rec, id=_NEW_ID, _cand=True)])
    if after:
        return f"that sell would leave a later one short: {after}"
    return ""


def _fx_ccy(r: dict) -> str:
    """The currency a record's rate is for (older records name none: their own, or the dollar in the home currency)."""
    return str(r.get("fx_ccy") or _ref_ccy(r.get("currency") or "USD") or "USD")


def record_line(r: dict) -> str:
    """The record read back in one line."""
    k, cur = r.get("kind"), r.get("currency") or ""
    when = _day(r.get("date"))
    fee = f" + fee {money(float(r['fee']), cur)}" if float(r.get("fee") or 0) else ""
    why = f" — “{r['why']}”" if r.get("why") else ""
    if k in ("buy", "sell"):
        tot = float(r["qty"]) * float(r["price"])
        s = (f"{'bought' if k == 'buy' else 'sold'} {float(r['qty']):g} {r['symbol']} at {money(float(r['price']), cur)} "
             f"on {when} = {money(tot, cur)}{fee}")
    elif k == "split":
        s = f"{r['symbol']} split {float(r['qty']):g}-for-1 on {when}"
    elif k == "dividend":
        s = f"dividend from {r['symbol']}: {money(float(r['price']), cur)} on {when}"
    elif k == "convert":
        a, b, tc = float(r["price"]), float(r.get("to_amount") or 0), r.get("to_currency") or ""
        shown, label = conv_shown(cur, tc, b / a if a and b else 0.0)
        fee = f" + fee {money(float(r['fee']), r.get('fee_currency') or cur)}" if float(r.get("fee") or 0) else ""
        auto = f" — automatic, for #{r['for']}" if r.get("auto") and r.get("for") else ""
        return f"converted {money(a, cur)} to {money(b, tc)} (at {shown:.4f} {label}) on {when}{fee}{auto}" + why
    else:
        s = {"deposit": "deposited", "withdraw": "withdrew", "fee": "a fee of"}[k] + f" {money(float(r['price']), cur)} on {when}{fee}"
    if r.get("fx"):
        s += f" (rate {float(r['fx']):.4f} {sym(str(r.get('fx_home') or home()))}/{sym(_fx_ccy(r))})"
    return s + why


def add(rec: dict, which: str | None = None) -> tuple[dict | None, str]:
    """Into the book: (the record as kept, "") or (None, why). Read fresh under the lock — an unreadable book refuses;
    a sell the book can't cover, or a dividend from a symbol never held, refuses; a busy book refuses."""
    which = which or open_book()
    if not isinstance(rec, dict) or which not in BOOKS:
        return None, "no record to keep"
    try:
        with _locked():
            return _add_locked(rec, which)
    except BookBusy as e:
        return None, str(e)


def _add_locked(rec: dict, which: str) -> tuple[dict | None, str]:
    try:
        book = load(which)
    except BookUnreadable as e:
        return None, str(e)
    r = dict(rec)
    r.pop("_cand", None)
    if r.get("kind") == "sell":
        no = _sell_fits(book["records"], r)
        if no:
            return None, no
    if r.get("kind") == "dividend" and r.get("by") != "engine":
        no = _div_fits(book["records"], r)
        if no:
            return None, no
    r["id"] = int(book.get("next_id") or 1)
    r["recorded_at"] = datetime.now().isoformat(timespec="seconds")
    book["records"].append(r)
    book["next_id"] = r["id"] + 1
    if auto_on():
        _auto_settle(book, r)  # paid from another currency at the record's own rate, in the same save
    if not _save_locked(which, book):
        return None, "the book couldn't be written — nothing was kept"
    return r, ""


# ---- PORTFOLIO_AUTO_CONVERT: the book converts by itself -----------------------------------------------------------
# A kept record that leaves its currency's cash below zero, while another currency covers the shortfall at the record's
# own rate, is paid from that currency: a `convert` record by the engine, dated as the record, marked auto and linked
# (for: <id>). Which pays: the home currency first, then the largest other pile — among those the record's own rate
# reaches (home per the record's currency, or the dollar for a record in the home currency). Not enough anywhere:
# nothing is converted (the warning stays).
_SPENDS = ("buy", "fee", "withdraw")


def auto_on() -> bool:
    return bool(getattr(config, "PORTFOLIO_AUTO_CONVERT", False))


def _cost(r: dict) -> float:
    try:
        if r.get("kind") == "buy":
            return float(r["qty"]) * float(r["price"]) + float(r.get("fee") or 0)
        return float(r.get("price") or 0) + float(r.get("fee") or 0)
    except (TypeError, ValueError, KeyError):
        return 0.0


def _record_per(r: dict, other: str) -> float | None:
    """Units of `other` per one unit of the record's currency, at the record's own rate — when its rate reaches."""
    h, cur = home(), r.get("currency") or ""
    try:
        fx = float(r.get("fx") or 0)
    except (TypeError, ValueError):
        return None
    if fx <= 0 or str(r.get("fx_home") or h) != h:
        return None
    ref = _fx_ccy(r)
    if cur != h and ref == cur and other == h:
        return fx
    if cur == h and other == ref:
        return 1.0 / fx
    return None


def _auto_settle(book: dict, r: dict) -> dict | None:
    """In the open book (under the lock, before its save): the conversion this record needs, appended — or None."""
    if r.get("kind") not in _SPENDS or r.get("struck"):
        return None
    cur = r.get("currency")
    if not cur:
        return None
    if any(x.get("auto") and x.get("for") == r["id"] and not x.get("struck") for x in book["records"]):
        return None
    cash = replay(book["records"])["cash"]
    if cash.get(cur, 0.0) >= -1e-9:
        return None
    short = round(min(-cash[cur], _cost(r)), 2)
    if short <= 0:
        return None
    h = home()
    piles = sorted((c for c, v in cash.items() if c != cur and v > 1e-9), key=lambda c: (c != h, -cash[c]))
    for other in piles:
        per = _record_per(r, other)
        if not per:
            continue
        pay = round(short * per, 2)
        if pay <= 0 or cash.get(other, 0.0) + 1e-9 < pay:
            continue
        c = {"date": r["date"], "kind": "convert", "symbol": "", "qty": 1.0, "price": pay, "currency": other,
             "to_amount": short, "to_currency": cur, "fx": round(short / pay, 6), "fx_source": "the record's own rate",
             "fee": 0.0, "fee_currency": other, "why": "", "by": "engine", "auto": True, "for": r["id"],
             "id": int(book.get("next_id") or 1), "recorded_at": datetime.now().isoformat(timespec="seconds")}
        book["records"].append(c)
        book["next_id"] = c["id"] + 1
        return c
    return None


def auto_for(which: str, rid: int) -> dict | None:
    """The engine's conversion for a record (not struck), if there is one."""
    try:
        return next((x for x in load(which)["records"] if x.get("auto") and x.get("for") == int(rid) and not x.get("struck")), None)
    except BookUnreadable:
        return None


def paid_clause(c: dict | None) -> str:
    """" · paid from euros at 0.9200: €378.35" — for the phone's kept line."""
    if not c:
        return ""
    shown, _ = conv_shown(c["currency"], c["to_currency"], float(c["fx"]))
    return f" · paid from {cur_word(c['currency'], True)} at {shown:.4f}: {money(float(c['price']), c['currency'])}"


def _strike_auto(book: dict, rid: int) -> dict | None:
    """The engine's conversion linked to #rid, struck with it (by the engine)."""
    for x in book["records"]:
        if x.get("auto") and x.get("for") == int(rid) and not x.get("struck"):
            x["struck"] = datetime.now().isoformat(timespec="seconds")
            x["struck_by"] = "engine"
            return x
    return None


_SETTLE_LOOKED = [False]
SETTLE_PHONE = "the shortfalls already in the book were paid from another currency at each record's own rate — {n} conversion{s} written"
SETTLE_FRIEND = "the book now pays a record from another currency at its own rate when one runs short: "


def _maybe_settle() -> None:
    """Once per process with the knob on: a shortfall already in the open book is settled, record by record, at each
    record's own rate — under the lock; the second process finds it done."""
    if _SETTLE_LOOKED[0] or not auto_on():
        return
    _SETTLE_LOOKED[0] = True
    st0 = state()
    which = "real" if not paper_on() else (str(st0.get("open") or "paper") if str(st0.get("open") or "paper") in BOOKS else "paper")
    try:
        with _locked():
            s_ = state()
            if (s_.get("auto_settled") or {}).get(which):
                return
            try:
                book = load(which)
            except BookUnreadable:
                _SETTLE_LOOKED[0] = False
                return
            made = []
            for r in live(book["records"]):
                c = _auto_settle(book, r)
                if c:
                    made.append(c)
            if made and not _save_locked(which, book):
                _SETTLE_LOOKED[0] = False
                return
            s_ = state()
            s_.setdefault("auto_settled", {})[which] = {"n": len(made), "at": time.time(), "phone": not made,
                                                       "friend": not made, "lines": [record_line(c) for c in made]}
            _write("state.json", s_)
            if made:
                _log(f"auto convert: {len(made)} conversion(s) written for the shortfall already in the book")
    except BookBusy:
        _SETTLE_LOOKED[0] = False


def settle_news(who: str) -> str:
    """The one-time settle, said once to "phone" or to "friend"."""
    if not auto_on():
        return ""
    _maybe_settle()
    try:
        with _locked():
            s_ = state()
            for which, a in (s_.get("auto_settled") or {}).items():
                if isinstance(a, dict) and a.get("n") and not a.get(who):
                    a[who] = True
                    _write("state.json", s_)
                    n = int(a["n"])
                    if who == "phone":
                        return SETTLE_PHONE.format(n=n, s="" if n == 1 else "s")
                    return SETTLE_FRIEND + "; ".join(a.get("lines") or [])
    except BookBusy:
        pass
    return ""


def strike(rid: int, which: str | None = None) -> tuple[dict | None, str]:
    which = which or open_book()
    try:
        with _locked():
            try:
                book = load(which)
            except BookUnreadable as e:
                return None, str(e)
            r = next((x for x in book["records"] if int(x["id"]) == int(rid)), None)
            if r is None:
                return None, f"no record #{rid}"
            if r.get("struck"):
                return None, f"#{rid} is struck already"
            after = timeline_error([x for x in book["records"] if x is not r])
            if after:
                return None, f"striking #{rid} would leave {after}"
            r["struck"] = datetime.now().isoformat(timespec="seconds")
            if r.get("auto"):  # the keeper struck the engine's conversion: it is their decision now
                r["struck_by"] = "keeper"
            _strike_auto(book, rid)
            if not _save_locked(which, book):
                return None, "the book couldn't be written — nothing changed"
            return r, ""
    except BookBusy as e:
        return None, str(e).replace("nothing was kept", "nothing changed")


def correct(rid: int, field: str, value, which: str | None = None) -> tuple[dict | None, str]:
    """A new record that replaces #rid with one field changed (checked as a new record), the old one struck; it keeps
    the old one's place in its day. A new date takes that day's rate unless one was typed. Refused when the book
    would then sell more than it held. The new record is made (the feed asked) before the lock; under the lock the
    book is read again, and a record that changed meanwhile refuses."""
    which = which or open_book()
    try:
        book = load(which)
    except BookUnreadable as e:
        return None, str(e)
    old = next((r for r in book["records"] if int(r["id"]) == int(rid)), None)
    if old is None:
        return None, f"no record #{rid}"
    if old.get("struck"):
        return None, f"#{rid} is struck — nothing to correct"
    key = {"date": "day", "rate": "fx", "amount": "price", "sent": "price", "arrived": "to", "from": "price"}.get(field, field)
    if old["kind"] == "convert":
        if key not in ("price", "to", "day", "fee", "why"):
            return None, f"“{field}” isn't a field of a conversion that can be corrected (sent, arrived, date, fee, why)"
        c = {"price": old.get("price"), "to": old.get("to_amount"), "day": old.get("date"), "fee": old.get("fee"),
             "why": old.get("why")}
        c[key] = value
        rec, why = make_convert(old.get("currency"), c["price"], old.get("to_currency"), c["to"], c["day"], c["fee"],
                                old.get("fee_currency"), c["why"] or "", by="keeper" if old.get("auto") else old.get("by", "keeper"))
        if rec is None:
            return None, why
        return _replace(rid, old, rec, which)
    if key not in ("qty", "price", "day", "fee", "why", "fx"):
        return None, f"“{field}” isn't a field that can be corrected"
    args = {"symbol": old.get("symbol") or old.get("currency"), "qty": old.get("qty"), "price": old.get("price"),
            "day": old.get("date"), "fee": old.get("fee"), "why": old.get("why"), "currency": old.get("currency"),
            "fx": old.get("fx")}
    args[key] = value
    if key == "day" and old.get("fx_source") != "given":
        args["fx"] = None  # the new day's own rate
    kind = old["kind"]
    rec, why = make_record("buy" if kind == "sell" else kind, args["symbol"] or "", args["qty"],
                           args["price"], args["day"], args["fee"], args["why"] or "", args["currency"], args["fx"],
                           by=old.get("by", "keeper"), which=which)
    if rec is None:
        return None, why
    rec["kind"] = kind
    if key not in ("fx", "day") and old.get("fx") and old.get("fx_source"):
        rec["fx"], rec["fx_source"] = old.get("fx"), old.get("fx_source")
        for k_ in ("fx_ccy", "fx_home"):
            if old.get(k_):
                rec[k_] = old[k_]
    return _replace(rid, old, rec, which)


def _replace(rid: int, old: dict, rec: dict, which: str) -> tuple[dict | None, str]:
    """Under the lock: the book read again; the old record struck and the new one kept in its place."""
    try:
        with _locked():
            try:
                book = load(which)
            except BookUnreadable as e:
                return None, str(e)
            now_old = next((r for r in book["records"] if int(r["id"]) == int(rid)), None)
            if now_old is None or now_old != old:
                return None, f"#{rid} changed while this was made — nothing changed; try again"
            rec["place"] = _place(old)
            rest = [r for r in book["records"] if r is not now_old]
            after = timeline_error(rest + [dict(rec, id=_NEW_ID, _cand=True)])
            if after:
                return None, (f"correcting #{rid} that way: {after}" if after.startswith("it would")
                              else f"correcting #{rid} that way would leave {after}")
            now_old["struck"] = datetime.now().isoformat(timespec="seconds")
            _strike_auto(book, now_old["id"])  # its automatic conversion goes with it, and is made again below
            rec["replaces"] = now_old["id"]
            rec["id"] = int(book.get("next_id") or 1)
            rec["recorded_at"] = datetime.now().isoformat(timespec="seconds")
            book["records"].append(rec)
            book["next_id"] = rec["id"] + 1
            if auto_on():
                _auto_settle(book, rec)
            if not _save_locked(which, book):
                return None, "the book couldn't be written — nothing changed"
            return rec, ""
    except BookBusy as e:
        return None, str(e).replace("nothing was kept", "nothing changed")


_LATER_IN_DAY = ("sell", "withdraw")
_FIRST_IN_DAY = ("deposit", "convert")


def _place(r: dict) -> int:
    """A record's place among its day's group: a correction keeps the place of the record it replaced."""
    try:
        return int(r.get("place") or r.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def live(records: list[dict]) -> list[dict]:
    """The records not struck, in the book's order: date; within a day deposits and conversions first, then buys,
    splits, dividends and fees, then sells and withdrawals; then each record's place (its id, or for a correction the
    id it replaced)."""
    return sorted([r for r in records if not r.get("struck")],
                  key=lambda r: (str(r.get("date")), 2 if r.get("kind") in _LATER_IN_DAY else 0 if r.get("kind") in _FIRST_IN_DAY
                                 else 1, _place(r)))


def replay(records: list[dict]) -> dict:
    """Positions, cash per currency, net put in (in the home currency, at each record's rate), realised gains,
    dividends — from the records not struck, in date order. Never raises on a record that doesn't add up (it is
    counted as it is)."""
    h = home()
    pos: dict[str, dict] = {}
    cash = {"USD": 0.0, h: 0.0}
    put = {"USD": 0.0, h: 0.0}
    put_home = 0.0
    put_unknown_fx = False
    for r in live(records):
        k, cur = r.get("kind"), r.get("currency") or "USD"
        try:
            q, p, fee = float(r.get("qty") or 0), float(r.get("price") or 0), float(r.get("fee") or 0)
        except (TypeError, ValueError):
            continue
        s = r.get("symbol") or ""
        hd = pos.setdefault(s, {"qty": 0.0, "cost": 0.0, "realised": 0.0, "dividends": 0.0, "currency": cur,
                                "first": r.get("date")}) if s else None
        if k == "buy":
            hd["qty"] += q
            hd["cost"] += q * p + fee
            cash[cur] = cash.get(cur, 0.0) - (q * p + fee)
        elif k == "sell":
            avg = hd["cost"] / hd["qty"] if hd["qty"] > 0 else 0.0
            hd["realised"] += q * p - fee - avg * q
            hd["cost"] -= avg * min(q, hd["qty"])
            hd["qty"] -= q
            cash[cur] = cash.get(cur, 0.0) + q * p - fee
        elif k == "split" and hd is not None and q > 0:
            hd["qty"] *= q
        elif k == "dividend":
            hd["dividends"] += p
            cash[cur] = cash.get(cur, 0.0) + p - fee
        elif k in ("deposit", "withdraw"):
            sign = 1 if k == "deposit" else -1
            cash[cur] = cash.get(cur, 0.0) + sign * p - fee
            put[cur] = put.get(cur, 0.0) + sign * p
            fx = r.get("fx")
            if cur == h:
                put_home += sign * p
            elif fx and _fx_ccy(r) == cur and str(r.get("fx_home") or h) == h:
                put_home += sign * p * float(fx)
            else:
                put_unknown_fx = True
        elif k == "fee":
            cash[cur] = cash.get(cur, 0.0) - p
        elif k == "convert":  # one currency's cash to another's; "put in" unchanged
            try:
                to = float(r.get("to_amount") or 0)
            except (TypeError, ValueError):
                to = 0.0
            tc = r.get("to_currency") or cur
            cash[cur] = cash.get(cur, 0.0) - p
            cash[tc] = cash.get(tc, 0.0) + to
            fc = r.get("fee_currency") or cur
            cash[fc] = cash.get(fc, 0.0) - fee
    for hd in pos.values():
        if abs(hd["qty"]) < 1e-9:  # float dust is zero — never a "realised $0.00" ghost
            hd["qty"] = 0.0
            hd["cost"] = 0.0
        if abs(hd["realised"]) < 1e-6:
            hd["realised"] = 0.0
        # a holding below zero (a hand-edited book) stays below zero: the statement says so, never "sold out"
    return {"positions": pos, "cash": cash, "put": put, "put_home": put_home, "put_unknown_fx": put_unknown_fx}


# ---- a conversion offered after a buy -----------------------------------------------------------------------------
def shortfall(which: str) -> dict | None:
    """After a buy: a currency's cash below zero while another has cash — {"cur", "short", "other", "have"} (the
    other: the home currency when it has cash, else the one with the most); None otherwise."""
    try:
        cash = replay(load(which)["records"])["cash"]
    except BookUnreadable:
        return None
    for cur, v in cash.items():
        if v < -1e-9:
            have = {c: w for c, w in cash.items() if c != cur and w > 1e-9}
            if have:
                other = home() if home() in have else max(have, key=lambda c: have[c])
                return {"cur": cur, "short": round(-v, 2), "other": other, "have": round(have[other], 2)}
    return None


def convert_present(which: str, from_ccy: str, from_amt, to_ccy: str, to_amt, day) -> tuple[dict | None, str, float]:
    """The one-tap convert, under the lock: the PRESENT shortfall of the currency it fills is read again. ("gone")
    when that cash is no longer below zero; ("changed", present shortfall) when it is another amount than the button
    said — nothing kept then; else the conversion kept ("kept")."""
    tc = currency_of(to_ccy)
    want = float(num(to_amt) or 0)
    rec, no = make_convert(from_ccy, from_amt, tc, to_amt, day, by="keeper")  # the feed asked before the lock
    try:
        with _locked():
            try:
                cash = replay(load(which)["records"])["cash"]
            except BookUnreadable as e:
                return None, str(e), 0.0
            v = cash.get(tc, 0.0)
            if v >= -1e-9:
                return None, "gone", 0.0
            short = round(-v, 2)
            if abs(short - want) > 0.005:
                return None, "changed", short
            if rec is None:
                return None, no, short
            got, no = _add_locked(rec, which)
            return (got, "kept", short) if got else (None, no, short)
    except BookBusy as e:
        return None, str(e), 0.0


def live_offer(which: str, mid: int | None = None) -> int:
    """The message id of the one live convert offer in a book (0: none); with mid, it is set (and the old one returned)."""
    if mid is None:
        return int((state().get("cv_live") or {}).get(which) or 0)
    try:
        with _locked():
            s = state()
            old = int((s.get("cv_live") or {}).get(which) or 0)
            s.setdefault("cv_live", {})[which] = int(mid)
            _write("state.json", s)
            return old
    except BookBusy:
        return 0


def offer_once(which: str, cur: str, short: float) -> bool:
    """True the first time this shortfall (book, currency, amount) is offered; it is never offered twice."""
    key = f"{which}:{cur}:{short:.2f}"
    try:
        with _locked():
            s = state()
            seen = s.get("convert_offered") or []
            if key in seen:
                return False
            s["convert_offered"] = (seen + [key])[-50:]
            return _write("state.json", s)
    except BookBusy:
        return False


def cur_word(cur: str, plural: bool = False) -> str:
    w = CUR_WORD.get(cur)
    return (w + "s" if plural else w) if w else (f"{cur} in cash" if plural else cur)


# ---- splits from the feed ----------------------------------------------------------------------------------------
def apply_splits(which: str | None = None, quotes: dict | None = None) -> list[str]:
    """A split the feed reports for a held symbol, dated after the first buy of it and not yet in the book: a `split`
    record by the engine. The lines that say so."""
    which = which or open_book()
    said = []
    try:
        book = load(which)
    except BookUnreadable:
        return said
    rp = replay(book["records"])
    have = {(r.get("symbol"), r.get("date")) for r in book["records"] if r.get("kind") == "split"}
    for s_, hd in rp["positions"].items():
        q = (quotes or {}).get(s_) or {}
        for sp in q.get("splits") or []:
            if (s_, sp["date"]) in have or not hd.get("first") or sp["date"] <= str(hd["first"]):
                continue
            rec = {"date": sp["date"], "kind": "split", "symbol": s_, "qty": float(sp["ratio"]), "price": None,
                   "currency": hd.get("currency") or "", "fx": None, "fx_source": "", "fee": 0.0,
                   "why": f"the feed reports a {sp.get('text') or sp['ratio']} split", "by": "engine"}
            got, why = add(rec, which)
            if got:
                said.append(f"{s_} split {float(sp['ratio']):g}-for-1 on {_day(sp['date'])}: counts adjusted")
                have.add((s_, sp["date"]))
    return said


# ---- the statement -----------------------------------------------------------------------------------------------
def block(which: str | None = None, compact: bool = False, refresh: bool = False, for_friend: bool = False) -> str:
    """The book as it stands, in plain text: each holding (count, average cost, price with date and source, value,
    gain, share), cash, totals in the home currency (and in dollars when home isn't the dollar) at the stated rates,
    put in — worth. PAPER on every line of the paper book."""
    which = which or open_book()
    try:
        book = load(which)
    except BookUnreadable as e:
        return f"({e})"
    tag = "PAPER " if which == "paper" else ""
    # this look's own time for fetching, passed down — a slow feed never holds a look much longer
    return _block(which, book, tag, compact, refresh, time.time() + LOOK_BUDGET_S, for_friend)


def _block(which, book, tag, compact, refresh, until=None, for_friend=False) -> str:
    h = home()
    quotes = {}
    rp = replay(book["records"])
    for s_, hd in rp["positions"].items():
        if hd["qty"] > 0:
            quotes[s_] = quote(s_, refresh=refresh, until=until)
    said = apply_splits(which, quotes)
    if said:
        book = load(which)
        rp = replay(book["records"])
    held = [(s_, hd) for s_, hd in sorted(rp["positions"].items()) if hd["qty"] > 0]
    # the rates this look needs: every currency held or in cash that isn't home, and the dollar (for the total in
    # dollars) when home isn't the dollar — none at all for a dollar book of dollar holdings
    need = {hd["currency"] for _, hd in held} | {c for c, v in rp["cash"].items() if abs(v) > 1e-9}
    need.discard(h)
    if h != "USD":
        need.add("USD")
    order = (["USD"] if "USD" in need else []) + sorted(need - {"USD"})
    rates = {c: rate(c, until=until) for c in order}
    fx_ok = all(r.get("ok") for r in rates.values())
    fx_err = next((r.get("error") for r in rates.values() if not r.get("ok")), "") or "no rate"
    lines: list[str] = []
    title = "the paper book" if which == "paper" else "the book"
    lines.append(f"{title}, {datetime.now():%b} {datetime.now().day} {datetime.now():%H:%M}")
    for s_ in said:
        lines.append(s_)
    vals = {}
    doubt = 0
    for s_, hd in held:
        q = quotes.get(s_) or quote(s_, until=until)
        if q.get("ok"):
            vals[s_] = hd["qty"] * price_of(q)
            if q.get("jump"):
                doubt += 1

    def to_home(v, cur):
        if cur == h:
            return v
        r = rates.get(cur) or {}
        return v * r["rate"] if r.get("ok") else None
    total_home = 0.0
    total_known = True
    for s_, hd in held:
        v = vals.get(s_)
        x = to_home(v, hd["currency"]) if v is not None else None
        if x is None:
            total_known = False
        else:
            total_home += x
    cash_home = 0.0
    for cur, v in rp["cash"].items():
        x = to_home(v, cur)
        if x is None:
            total_known = total_known and abs(v) < 1e-9
        else:
            cash_home += x
    whole = total_home + cash_home
    below = any(v < -1e-9 for v in rp["cash"].values())
    mix_ok = total_known and whole > 0 and not below  # shares of the whole only when the whole is a whole
    for s_, hd in held:
        q = quotes.get(s_) or {}
        cur = hd["currency"]
        avg = hd["cost"] / hd["qty"] if hd["qty"] else 0.0
        if compact:
            lines.append(f"{s_}  {hd['qty']:g} @ {money(avg, cur)}")
        else:
            lines.append(f"{s_}: {hd['qty']:g} at an average {money(avg, cur)} (cost {money(hd['cost'], cur)})")
        if q.get("ok"):
            stale = " (could not be fetched now)" if q.get("stale") else ""
            mn = q.get("minor") or ""
            if at_trade(q):  # valued at the last trade — said, with the close beside it
                ag = ((f" · {mn}" if compact else f"; in {mn}") if mn else "")
                lt = int(q["last_time"])
                hm = _hm(lt) if datetime.fromtimestamp(lt).date() == date.today() else _at(lt)
                if compact:
                    lines.append(f"  {money(price_of(q), cur)} · {hm} · {q.get('source', 'Yahoo')} · last trade{ag}{stale}")
                    if q.get("close") is None:
                        lines.append("  no completed close yet")
                else:
                    beside = (f" · close {_day(q.get('close_date'))} {money(float(q['close']), cur)}" if q.get("close") is not None
                              else " · no completed daily close yet")
                    lines.append(f"  {money(price_of(q), cur)} (last trade {_at(lt)}, {q.get('source', 'Yahoo')}{ag}){beside}{stale}")
            elif compact:
                src = f"{_day(q.get('close_date'))} · {q.get('source', 'Yahoo')}" + (f" · {mn}" if mn else "") \
                    + (" · last trade" if q.get("close_from_trade") else "")
                lines.append(f"  {money(float(q['close']), cur)} · {src}{stale}" + (" ⚠ check this" if q.get("jump") else ""))
            else:
                src = f"close {_day(q.get('close_date'))}, {q.get('source', 'Yahoo')}" + (f"; in {mn}" if mn else "") \
                    + ("; from the last trade — the day's bar isn't in the feed yet" if q.get("close_from_trade") else "")
                lines.append(f"  {money(float(q['close']), cur)} ({src}){stale}" + (" ⚠ check this" if q.get("jump") else ""))
            v = vals[s_]
            gain = v - hd["cost"]
            pct = (gain / hd["cost"] * 100) if hd["cost"] else 0.0
            x = to_home(v, cur)
            share = (f" {x / whole * 100:.0f}%" if compact else f"  {x / whole * 100:.0f}% of the book") \
                if (x is not None and mix_ok) else ""
            sign = "+" if gain >= 0 else "-"
            if compact:
                lines.append(f"  {money(v, cur)} {sign}{money(abs(gain), cur)} {sign}{abs(pct):.1f}%{share}")
            else:
                lines.append(f"  worth {money(v, cur)}  {sign}{money(abs(gain), cur)} {sign}{abs(pct):.1f}%{share}")
        else:
            lines.append(f"  no price — {q.get('error') or 'not known'}")
        if hd["realised"]:
            lines.append(f"  realised {money(hd['realised'], cur)}")
        if hd["dividends"]:
            lines.append(f"  dividends {money(hd['dividends'], cur)}")
        for d in (q.get("dividends") or [])[-1:]:
            lines.append(f"  the feed shows a dividend on {_day(d['date'])} — record it if you received it")
    negative = [(s_, hd) for s_, hd in sorted(rp["positions"].items()) if hd["qty"] < -1e-9]
    for s_, hd in negative:
        lines.append(f"{s_}: ⚠ more sold than bought ({hd['qty']:g}) — the book has an error")
    for s_, hd in sorted(rp["positions"].items()):
        if abs(hd["qty"]) < 1e-9 and (hd["realised"] or hd["dividends"]):
            lines.append(f"{s_}: sold out — realised {money(hd['realised'], hd['currency'])}")
    cash_bits = [money(v, cur) for cur, v in rp["cash"].items() if abs(v) > 1e-9]
    lines.append("cash  " + (" · ".join(cash_bits) if cash_bits else "none"))
    for cur, v in rp["cash"].items():
        if v < -1e-9:
            other = [c for c, w in rp["cash"].items() if c != cur and w > 1e-9]
            if other:  # the broker may have converted: say so, and how to record it
                lines.append(f"  ⚠ {cur_word(cur)} cash is below zero while there are {cur_word(other[0], True)} — if money "
                             "was converted, record the conversion "
                             + ("(your keeper records a conversion on their phone)" if for_friend else "(/trade → Record → Convert)"))
            else:
                lines.append(f"  {cur} below zero: more was bought than deposited — a deposit may be missing")
    if held and not mix_ok:
        lines.append("mix: not given — " + ("cash is below zero" if below else "the total isn't above zero"
                                             if total_known else "a price or the rate is missing"))
    old = [q for s_, q in quotes.items() if q.get("ok") and q.get("stale") and s_ in dict(held)]
    attrade = [s_ for s_, q in quotes.items() if q.get("ok") and at_trade(q) and s_ in dict(held)]
    firstday = [s_ for s_ in attrade if quotes[s_].get("close") is None]
    usd = rates.get("USD") or {}
    in_usd = f" · {money(whole / usd['rate'], 'USD')}" if h != "USD" and usd.get("ok") else ""
    if fx_ok and negative:
        lines.append(f"total: not given — the book has an error (more sold than bought: {', '.join(s_ for s_, _ in negative)})")
    elif fx_ok:
        notes = []
        if not total_known:
            notes.append("a price is missing")
        if attrade:  # one clause for both: markets open, and a first day with no close yet
            notes.append(f"{len(attrade)} at {'its' if len(attrade) == 1 else 'their'} last trade — markets open"
                         + (f"; {', '.join(firstday)} with no close yet" if firstday else ""))
        if old:
            notes.append(f"{len(old)} price{'s are' if len(old) != 1 else ' is'} from "
                         f"{', '.join(sorted({_day(q.get('close_date') or q.get('last_time') and datetime.fromtimestamp(int(q['last_time'])).date().isoformat()) for q in old}))} — could not be fetched now")
        lines.append(f"total {money(whole, h)}{in_usd}" + (f" ({'; '.join(notes)})" if notes else ""))
    else:
        lines.append(f"total: not known — {fx_err}")
    for r in rates.values():
        lines.append("  at " + (_short_rate_line(r) if compact and r.get("ok") else rate_line(r)))
    if doubt:
        lines.append(f"  {doubt} price{'s are' if doubt != 1 else ' is'} in doubt (⚠) — the total counts {'them' if doubt != 1 else 'it'} as given")
    if rp["put_home"] or any(rp["put"].values()):
        put = money(rp["put_home"], h) + (" (a deposit's rate unknown)" if rp["put_unknown_fx"] else "")
        if compact:
            lines.append(f"put in {put}")
            if fx_ok:
                lines.append(f"  worth {money(whole, h)}")
        else:
            lines.append(f"put in {put} — worth {money(whole, h)}" if fx_ok else f"put in {put}")
    if not book["records"]:
        lines.append("(nothing recorded yet)")
    return "\n".join(tag + ln for ln in lines)


def history(which: str | None = None, n: int = 30, before: int | None = None) -> str:
    """The records, newest first, struck ones marked: the newest n (before=<id>: the n before it)."""
    which = which or open_book()
    try:
        book = load(which)
    except BookUnreadable as e:
        return f"({e})"
    tag = "PAPER " if which == "paper" else ""
    allr = sorted(book["records"], key=lambda r: int(r["id"]), reverse=True)
    if before:
        allr = [r for r in allr if int(r["id"]) < int(before)]
    rs = allr[:n]
    if not rs:
        return tag + "(nothing recorded yet)"
    out = []
    for r in rs:
        mark = " [struck]" if r.get("struck") else ""
        rep_ = f" (replaces #{r['replaces']})" if r.get("replaces") else ""
        out.append(f"{tag}#{r['id']}{mark} {record_line(r)} — by {r.get('by', '?')}{rep_}")
    if len(allr) > n:
        out.append(f"{tag}({len(allr) - n} older — ask history with before={rs[-1]['id']})")
    return "\n".join(out)


# ---- pending (the friend's records, waiting for the keeper's tap) ------------------------------------------------
def pending() -> list[dict]:
    p = _read("pending.json", [])
    return [x for x in p if isinstance(x, dict) and isinstance(x.get("rec"), dict)] if isinstance(p, list) else []


def _save_pending(items: list[dict]) -> bool:
    return _write("pending.json", items)


def add_pending(rec: dict, which: str) -> dict | None:
    """The friend's record, waiting for the keeper's Keep. None when it couldn't be written (a busy book included)."""
    try:
        with _locked():
            items = pending()
            pid = max((int(x.get("pid") or 0) for x in items), default=0) + 1
            x = {"pid": pid, "book": which, "rec": rec, "made_at": time.time(), "told": False}
            items.append(x)
            return x if _save_pending(items) else None
    except BookBusy:
        return None


def mark_told(pid: int) -> bool:
    """After the send (outside the lock): the one pending record marked told, read fresh, by its id."""
    try:
        with _locked():
            items = pending()
            hit = False
            for x in items:
                if int(x.get("pid") or 0) == int(pid):
                    x["told"], hit = True, True
            return _save_pending(items) if hit else False
    except BookBusy:
        return False


def note_for_friend(line: str) -> None:
    try:
        with _locked():
            _note_locked(line)
    except BookBusy:
        _log(f"a note for the friend was not kept (busy): {line[:80]}")


def _note_locked(line: str) -> None:
    s = state()
    s.setdefault("for_friend", []).append({"t": time.time(), "line": line})
    s["for_friend"] = s["for_friend"][-30:]
    _write("state.json", s)


def resolve_pending(pid: int, keep: bool) -> str:
    """The keeper's ✅ Keep / ✖ Drop on a record the friend wrote — into the book it was written for, whichever is
    open now."""
    try:
        with _locked():
            items = pending()
            x = next((i for i in items if int(i.get("pid") or 0) == int(pid)), None)
            if x is None:
                return "(that record isn't waiting any more)"
            items = [i for i in items if i is not x]
            if keep:
                bk = (x.get("book") or "paper") if paper_on() else "real"
                got, why = _add_locked(x["rec"], bk)
                if got is None:
                    return f"(not kept — {why})"
                _save_pending(items)
                _note_locked(f"your keeper kept: {record_line(got)}")  # the friend's look says it, once
                return ("PAPER · " if bk == "paper" else "") + f"✓ kept #{got['id']}: {record_line(got)}"
            _save_pending(items)
            _note_locked(f"your keeper dropped: {record_line(x['rec'])}")
            return f"✖ dropped: {record_line(x['rec'])}"
    except BookBusy as e:
        return f"({e})"


def lapse_pending(now: float | None = None) -> list[str]:
    """Records the friend wrote that waited more than PENDING_LAPSE_H hours: gone, said to both (the lines for the
    phone, sent by the caller after the lock is let go)."""
    now = time.time() if now is None else now
    try:
        with _locked():
            items = pending()
            keep, gone = [], []
            for x in items:
                (gone if now - float(x.get("made_at") or 0) > PENDING_LAPSE_H * 3600 else keep).append(x)
            if gone:
                if not _save_pending(keep):
                    return []
                for x in gone:
                    _note_locked(f"lapsed (not kept — your keeper didn't tap Keep within a day): {record_line(x['rec'])}")
            return [f"⌛ lapsed — not kept: {record_line(x['rec'])}" for x in gone]
    except BookBusy:
        return []


def since_last_look(which: str) -> list[str]:
    """For the friend's look: what happened to the book on the phone since they last looked (the keeper's records and
    corrections, their records the keeper dropped or that lapsed) — said once; at most SINCE_MAX lines and how many
    more. The first look starts from now (nothing old is listed). A busy book: what was found is said, and found again
    next time."""
    try:
        with _locked():
            out = _since_locked(which)
    except BookBusy:
        return []
    if len(out) > SINCE_MAX:
        out = out[-SINCE_MAX:] + [f"and {len(out) - SINCE_MAX} more — history shows them"]
    return out


def _since_locked(which: str) -> list[str]:
    s = state()
    a = (s.get("auto_settled") or {}).get(which) if isinstance(s.get("auto_settled"), dict) else None
    news = []
    if isinstance(a, dict) and a.get("n") and not a.get("friend"):
        a["friend"] = True
        _write("state.json", s)
        news = [SETTLE_FRIEND + "; ".join(a.get("lines") or [])]
        s = state()
    first = "last_look" not in s
    last = float(s.get("last_look") or 0)
    seen = (s.get("last_id") or {}).get(which)  # the last record the friend saw, by id — a clock's second is too coarse
    out = list(news)
    if not first:
        try:
            book = load(which)
            for r in sorted(book["records"], key=lambda r: int(r["id"])):
                try:
                    t = datetime.fromisoformat(str(r.get("recorded_at"))).timestamp()
                except ValueError:
                    t = 0
                new = int(r["id"]) > int(seen) if isinstance(seen, int) else t > last
                if new and r.get("by") == "keeper":
                    out.append(f"your keeper recorded #{r['id']}: {record_line(r)}"
                               + (f" (replacing #{r['replaces']})" if r.get("replaces") else ""))
                st = r.get("struck")
                if st:
                    try:
                        if datetime.fromisoformat(str(st)).timestamp() > last and not any(
                                x.get("replaces") == r["id"] for x in book["records"]):
                            out.append(f"your keeper struck #{r['id']}: {record_line(r)}")
                    except ValueError:
                        pass
        except BookUnreadable:
            pass
        for x in s.get("for_friend") or []:
            if float(x.get("t") or 0) > last:
                out.append(str(x.get("line")))
    s = state()
    s["last_look"] = time.time()
    try:
        s.setdefault("last_id", {})[which] = max((int(r["id"]) for r in load(which)["records"]), default=0)
    except (BookUnreadable, TypeError, ValueError, KeyError):
        pass
    s["for_friend"] = []
    _write("state.json", s)
    return out


# ---- the morning brief: the engine's, nothing of it the friend's --------------------------------------------------
# /trade → 🌅 Brief, or /brief. Prices with their dates and sources as the book gives them, the day's move, the
# yardsticks (PORTFOLIO_INDICES), each rate's move, the book's own warnings, and — PORTFOLIO_BRIEF_NEWS — a couple of
# headlines a holding is named in (Brave's news search; the key from memory/web_search.json, never shown).
BRIEF_PRICE_S = 6.0   # the feed's share of the brief's time; a fetch started inside it may take its 6 s timeout
BRIEF_TOTAL_S = 12.0  # headlines only while the brief is inside this
NEWS_URL = "https://api.search.brave.com/res/v1/news/search?"
NEWS_FAIL_S = 300     # a failed search is remembered this long, per company, so 🔄 doesn't hammer
BRIEF_LIMIT = 4096
_SUFFIX = re.compile(r"(,?\s+(inc\.?|incorporated|corp\.?|corporation|co\.?|company|ltd\.?|limited|plc|pbc|"
                     r"n\.?v\.?|s\.?a\.?|ag|se|holdings?|group|b\.?m\.?))+\s*$", re.I)
NAME_STOP = {"bank", "group", "holdings", "holding", "international", "global", "technologies", "technology", "industries",
             "pharmaceutical", "pharmaceuticals", "systems", "financial", "capital", "trust", "fund", "etf", "the", "of",
             "and", "corp", "corporation", "inc", "ltd", "limited", "plc", "company", "co", "sa", "ag", "nv"}
TICKER_WORDS = {"ALL", "NOW", "ON", "IT", "ARE", "CAT", "KEY", "REAL", "WELL", "FAST", "LOVE", "LIFE", "OPEN",
                "PLAY", "RUN", "SEE", "TWO", "ONE", "CAN", "BIG", "CAR", "FUN", "GOOD", "HAS", "JOB", "MAN", "NEW",
                "OUT", "PAY", "SAVE", "SO", "TRUE", "WAY", "WIN", "YOU", "AIR", "ARM", "BOX", "EAT", "GO"}


def _minus(x: float) -> str:
    return "+" if x >= 0 else "−"


def _pct(x: float) -> str:
    return f"{_minus(x)}{abs(x) * 100:.1f}%"


def _signed(v: float, cur: str) -> str:
    return f"{_minus(v)}{money(abs(v), cur)}"


def _hm(ts) -> str:
    t = datetime.fromtimestamp(int(ts))
    return f"{t:%H:%M}"


def _move(q: dict, avg: float | None = None) -> dict:
    """The day's move of a quote: {"price", "base", "pct", "line", "first", …} — the latest price the feed has against
    the close before it; a first day (no close before) against the buy price (avg), if given."""
    cur = q.get("currency") or ""
    last, lt, close = q.get("last"), q.get("last_time"), q.get("close")
    newer = at_trade(q)
    if newer:
        price, said = float(last), f"now {money(float(last), cur)} ({_hm(lt)})"
        base, since = (float(close), f"since the close of {_day(q.get('close_date'))}") if close is not None else (None, "")
    else:
        price = float(close) if close is not None else None
        said = (f"close {_day(q.get('close_date'))} {money(price, cur)}"
                + (" (from the last trade — the day's bar isn't in the feed yet)" if q.get("close_from_trade") else "")
                if price is not None else "no price")
        base, since = ((float(q["prev_close"]), f"from {_day(q.get('prev_date'))}") if q.get("prev_close") else (None, ""))
    first = base is None
    if first and avg:
        base, since = float(avg), f"since the buy at {money(float(avg), cur)} — first day, no close before"
    pct = (price / base - 1) if (price is not None and base) else None
    if pct is None:
        line = said
    elif newer:
        line = f"{said} {_pct(pct)} {since}"
    else:
        line = f"{said}, {_pct(pct)} {since}"
    return {"price": price, "base": base, "pct": pct, "line": line, "first": first, "said": said, "since": since,
            "newer": bool(newer)}


def _plain(v: float) -> str:
    return f"{v:,.2f}"


def _clean_name(name: str, symbol: str) -> str:
    n = " ".join(str(name or "").split())
    for _ in range(3):
        n = _SUFFIX.sub("", n).strip(" ,")
    return n or re.sub(r"\.[A-Z]+$", "", str(symbol or "")).lstrip("^")


def _news_http(url: str, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _brave_key() -> str:
    """The search key through the web search's own secret reader (memory/web_search.json) — never config."""
    try:
        import web
        return web._secret("brave_key")
    except Exception:  # noqa: BLE001
        return ""


def _headlines(symbol: str, name: str, until: float) -> list[dict] | None:
    """Headlines naming a holding today: [{"title", "host", "age"}], newest first, at most PORTFOLIO_BRIEF_NEWS_MAX;
    None when they couldn't be fetched (offline, no key, a refusal, garbage, no time). Cached per company. Never
    raises; the key goes only into the request's header — never into a log, a message or a file. Only the company's
    name is asked: never a quantity, a price or anything of the book."""
    query = _clean_name(name, symbol)
    ck = query.lower()
    hours = float(getattr(config, "PORTFOLIO_BRIEF_NEWS_CACHE_H", 3) or 3)
    cache = _read("news.json", {})
    cache = cache if isinstance(cache, dict) else {}
    c = cache.get(ck) if isinstance(cache.get(ck), dict) else None
    if c and c.get("failed") and time.time() - float(c.get("t") or 0) < NEWS_FAIL_S:
        return None  # a search that failed a moment ago isn't tried again yet
    if c and not c.get("failed") and time.time() - float(c.get("t") or 0) < hours * 3600 and isinstance(c.get("items"), list):
        return c["items"]
    if getattr(config, "OFFLINE", False):
        return None
    key = _brave_key()
    left = until - time.time()
    if not key or left < 0.5:
        return None
    try:
        data = _news_http(NEWS_URL + urllib.parse.urlencode({"q": query, "count": 8, "freshness": "pd"}),
                          {"Accept": "application/json", "X-Subscription-Token": key, "User-Agent": UA},
                          min(4.0, left))
        res = data.get("results") if isinstance(data, dict) else None
        if not isinstance(res, list):
            raise ValueError("not the news shape")
    except Exception:  # noqa: BLE001 — its text may carry the request; nothing of it is kept
        _news_keep(ck, {"t": time.time(), "failed": True})
        return None
    skip = [str(h).lower() for h in (getattr(config, "PORTFOLIO_BRIEF_NEWS_SKIP", None) or [])]
    items = []
    for r in res:
        if not isinstance(r, dict):
            continue
        title = " ".join(str(r.get("title") or "").split())
        host = str(((r.get("meta_url") or {}) if isinstance(r.get("meta_url"), dict) else {}).get("hostname") or "")
        if not host:
            host = urllib.parse.urlparse(str(r.get("url") or "")).hostname or ""
        host = host.lower()
        host = host[4:] if host.startswith("www.") else host
        if not title or not names_holding(title, query, symbol) or quote_page(title, query, symbol):
            continue
        if any(host == h or host.endswith("." + h) for h in skip):
            continue
        items.append({"title": title, "host": host, "age": str(r.get("age") or "").strip(),
                      "when": str(r.get("page_age") or "")})
    items.sort(key=lambda x: x["when"], reverse=True)
    items = [{k: v for k, v in x.items() if k != "when"} for x in items[:int(getattr(config, "PORTFOLIO_BRIEF_NEWS_MAX", 2) or 2)]]
    _news_keep(ck, {"t": time.time(), "items": items})
    return items


def _news_keep(ck: str, entry: dict) -> None:
    try:
        with _locked():
            cache = _read("news.json", {})
            cache = cache if isinstance(cache, dict) else {}
            cache[ck] = entry
            cache = {k: v for k, v in cache.items() if isinstance(v, dict) and time.time() - float(v.get("t") or 0) < 24 * 3600}
            _write("news.json", cache)
    except BookBusy:
        pass


_QUOTE_WORDS = {"ordinary", "shares", "share", "class", "a", "b", "c", "stock", "stocks", "price", "prices", "quote", "quotes",
                "common", "inc", "ltd", "pbc", "plc", "corp", "chart", "and", "the", "today", "live", "news", "history", "nyse",
                "nasdaq", "lse", "adr", "ads", "s"}


def quote_page(title: str, name: str, symbol: str) -> bool:
    """A title that is a security's quote page, not news ("Acme Widgets, Inc. Ordinary Shares - Class A (ACME)"): the
    title less the company's name, its ticker and quote-page words leaves fewer than 3 words."""
    drop = {w.lower() for w in re.findall(r"[A-Za-z0-9']+", str(name or ""))}
    bare = re.sub(r"\.[A-Z]+$", "", str(symbol or "")).lstrip("^").lower()
    rest = [w for w in re.findall(r"[A-Za-z0-9']+", str(title or ""))
            if w.lower() not in drop and w.lower() != bare and w.lower() != str(symbol or "").lower() and w.lower() not in _QUOTE_WORDS]
    return len(rest) < 3


def names_holding(title: str, name: str, symbol: str) -> bool:
    """Does a headline name the holding? The whole cleaned name; or one distinctive word of it (4+ letters, not a
    common company word), whole and case-blind; or the bare ticker — 3+ letters, whole, case-sensitive, and not an
    English word."""
    t = str(title or "")
    n = " ".join(str(name or "").split())
    if n and re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", t, re.I):
        return True
    for w in re.findall(r"[A-Za-z][A-Za-z'&-]*", n):
        if len(w) >= 4 and w.lower() not in NAME_STOP and re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", t, re.I):
            return True
    bare = re.sub(r"\.[A-Z]+$", "", str(symbol or "")).lstrip("^")
    return bool(len(bare) >= 3 and bare.upper() not in TICKER_WORDS and re.search(rf"(?<![\w-]){re.escape(bare)}(?![\w-])", t))


def _pair_close(ccy: str, until: float | None) -> tuple[float | None, str, str]:
    """Yahoo's last completed close (not today's) of the home currency per one ccy: (value, its day, the symbols)."""
    syms = _yahoo_syms(home(), ccy)
    vals, day_ = [], ""
    for sy in syms:
        fq = quote(sy, until=until)
        base = fq.get("close") if fq.get("ok") else None
        bday = fq.get("close_date")
        if base is not None and bday == date.today().isoformat() and fq.get("prev_close"):
            base, bday = fq["prev_close"], fq.get("prev_date")
        if not base:
            return None, "", " and ".join(syms)
        vals.append(float(base))
        day_ = day_ or str(bday)
    if ccy == "USD":
        v = vals[0]
    elif home() == "USD":
        v = 1.0 / vals[0]
    else:
        v = vals[0] / vals[1]
    return v, day_, " and ".join(syms)


def brief(which: str | None = None, now: datetime | None = None) -> str:
    """The morning brief, plain text for the phone. Never raises."""
    try:
        return _brief(which or open_book(), now or datetime.now())
    except BookUnreadable as e:
        return f"🌅 Brief\n({e})"
    except Exception as e:  # noqa: BLE001
        return f"🌅 Brief\n(the brief could not be made: {type(e).__name__})"


def _brief(which: str, now: datetime) -> str:
    t0 = time.time()
    until_p, until_all = t0 + BRIEF_PRICE_S, t0 + BRIEF_TOTAL_S
    h0 = home()
    tag = "PAPER " if which == "paper" and paper_on() else ""
    book = load(which)
    rp = replay(book["records"])
    held = [(s_, hd) for s_, hd in sorted(rp["positions"].items()) if hd["qty"] > 0]
    quotes = {s_: quote(s_, until=until_p) for s_, hd in held}
    need = {hd["currency"] for _, hd in held} | {c for c, v in rp["cash"].items() if abs(v) > 1e-9}
    need.discard(h0)
    if h0 != "USD":
        need.add("USD")
    order = (["USD"] if "USD" in need else []) + sorted(need - {"USD"})
    rates = {c: rate(c, until=until_p) for c in order}
    fx_ok = all(r.get("ok") for r in rates.values())
    fx_err = next((r.get("error") for r in rates.values() if not r.get("ok")), "") or "no rate"
    move_lim = float(getattr(config, "PORTFOLIO_BRIEF_MOVE", 0.03) or 0.03)

    def to_home(v, cur):
        if cur == h0:
            return v
        r = rates.get(cur) or {}
        return v * r["rate"] if r.get("ok") else None

    out = [f"🌅 Brief — {now:%a} {now:%b} {now.day}, {now:%H:%M}"]
    movers, lines, day_home, left_out, worth_home, missing = [], [], 0.0, [], 0.0, []
    today_iso = date.today().isoformat()
    for s_, hd in held:
        q = quotes.get(s_) or {}
        if not q.get("ok"):
            lines.append(f"{s_} ×{hd['qty']:g}  no price — {q.get('error') or 'not known'}")
            missing.append(s_)
            continue
        cur = hd["currency"]
        m = _move(q)  # the share's own move: its latest price against the close before it
        P, C = m["price"], m["base"]
        # the SESSION of the latest price (its date S): shares held before S move from the close before S; shares
        # bought on S (or after) from their buy price; shares sold on S up to the sale price — the keeper's real day
        S = str((q.get("last_date") or (datetime.fromtimestamp(int(q["last_time"])).date().isoformat() if q.get("last_time") else ""))
                if m.get("newer") else (q.get("close_date") or ""))
        mine = [r for r in live(book["records"]) if r.get("symbol") == s_]
        lots = [r for r in mine if S and str(r.get("date")) >= S]
        buys = [(float(r["qty"]), float(r["price"])) for r in lots if r.get("kind") == "buy"]
        sells = [(float(r["qty"]), float(r["price"])) for r in lots if r.get("kind") == "sell"]
        bq, sq = sum(x for x, _ in buys), sum(x for x, _ in sells)
        try:
            before = max(0.0, float(replay([r for r in mine if not S or str(r.get("date")) < S])["positions"].get(s_, {}).get("qty") or 0))
        except Exception:  # noqa: BLE001
            before = max(0.0, hd["qty"] - bq + sq)
        bdays = sorted({str(r.get("date")) for r in lots if r.get("kind") == "buy"})
        when = ("today" if bdays == [today_iso] else "that day" if bdays == [S] else
                f"on {', '.join(_day(x) for x in bdays)}")
        sdays = sorted({str(r.get("date")) for r in lots if r.get("kind") == "sell"})
        swhen = ("today" if sdays == [today_iso] else "that day" if sdays == [S] else f"on {', '.join(_day(x) for x in sdays)}")
        lines.append(f"{s_} ×{hd['qty']:g}")
        amount, parts_left = 0.0, False
        if P is None:
            lines.append(f"  {m['line']}")
            missing.append(s_)
            continue
        if before > 1e-9:
            if C is None:
                parts_left = True
            else:
                amount += before * (P - C)
        amount += sum(x * (P - b) for x, b in buys)
        amount += sum(x * (sp - P) for x, sp in sells)
        share = f"{_pct(m['pct'])} {m['since']}" if m["pct"] is not None else ""
        sold = (f"; {sq:g} sold {swhen} at {money(sum(x * sp for x, sp in sells) / sq, cur)}" if sq else "")
        if buys and before <= 1e-9:
            bavg = sum(x * b for x, b in buys) / bq
            own = P / bavg - 1
            tail = f"(the share itself is {share})" if share else "(first day — no close before)"
            lines.append(f"  {m['said']} · bought {when} at {money(bavg, cur)}: {_pct(own)} · {_signed(amount, cur)} {tail}"
                         + (f" ({sold[2:]})" if sold else ""))
        elif buys:
            bavg = sum(x * b for x, b in buys) / bq
            lines.append(f"  {m['said']} {share} · {_signed(amount, cur)} ({before:g} held before, {bq:g} bought {when} at "
                         f"{money(bavg, cur)}{sold})")
        elif parts_left:
            lines.append(f"  {m['said']} — no close before, so its day isn't known; not in the day's sum")
        else:
            lines.append(f"  {m['line']} · {_signed(amount, cur)}" + (f" ({sold[2:]})" if sold else ""))
        if parts_left:
            left_out.append(s_)
        x = to_home(amount, cur)
        if x is None:
            missing.append(s_)
        else:
            day_home += x
        wv = to_home(hd["qty"] * P, cur)
        if wv is None:
            missing.append(s_)
        else:
            worth_home += wv
        mv = m["pct"]
        if mv is None and buys:
            mv = P / (sum(x * b for x, b in buys) / bq) - 1
        if mv is not None and abs(mv) >= move_lim:
            movers.append(f"{'▲' if mv > 0 else '▼'} {s_} {_pct(mv)}" + (f" (bought {when})" if buys else ""))
    cash_home = 0.0
    for cur, v in rp["cash"].items():
        x = to_home(v, cur)
        if x is None and abs(v) > 1e-9:
            missing.append(cur)
        elif x is not None:
            cash_home += x
    out += movers
    out.append("the book")
    usd = rates.get("USD") or {}
    worth = worth_home + cash_home
    if fx_ok:
        in_usd = f" · {money(worth / usd['rate'], 'USD')}" if h0 != "USD" and usd.get("ok") else ""
        out.append(f"worth now {money(worth, h0)}{in_usd}" + (" (a price is missing)" if missing else ""))
    else:
        out.append(f"worth now: not known — {fx_err}")
    out += lines
    if held:
        if fx_ok:
            out.append(f"the day {_signed(day_home, h0)} (prices only — deposits and buys not counted)")
        else:
            out.append("the day: not known — no rate")
        if left_out:
            out.append(f"  {', '.join(left_out)}: the shares held before that day left out — no close before")
    if rp["put_home"] and fx_ok:
        out.append(f"put in {money(rp['put_home'], h0)} — worth {money(worth, h0)}")
    idx = list(getattr(config, "PORTFOLIO_INDICES", None) or [])
    if idx:
        out.append("yardsticks")
        for s_ in idx:
            q = quote(s_, until=until_p)
            if not q.get("ok"):
                out.append(f"{s_}  no price — {q.get('error') or 'not known'}")
                continue
            line = _move(q)["line"]
            for v in (q.get("close"), q.get("last")):  # an index is points, not money
                if v is not None:
                    line = line.replace(money(float(v), q.get("currency") or ""), _plain(float(v)))
            out.append(f"{s_}  {line}")
    for c, r in rates.items():
        if not r.get("ok"):
            out.append(f"rate: {rate_line(r)}")
            continue
        mv = ""
        try:
            base, bday, syms = _pair_close(c, until_p)
            if base:
                mv = f", {_pct(r['rate'] / base - 1)} from Yahoo's {syms} close of {_day(bday)} ({base:.4f})"
        except Exception:  # noqa: BLE001
            mv = ""
        out.append(f"rate {rate_line(r)}{mv}")
    warn = [ln.strip() for ln in _block(which, book, "", True, False, until_p).splitlines()
            if ("⚠" in ln or "below zero" in ln or "could not be fetched" in ln or "in doubt" in ln)
            and not ln.strip().startswith("mix:")]
    seen = set()
    warn = [w for w in warn if not (w in seen or seen.add(w))]
    if warn:
        out.append("the book says")
        out += ["  " + w for w in warn]
    if getattr(config, "PORTFOLIO_WATCH", False):  # the watch list: movers only, an alert that fired, the friend's adds
        try:
            import bookwatch
            if bookwatch.on():
                out += bookwatch.section(bookwatch.check_alerts(), until_all, news=bool(getattr(config, "PORTFOLIO_BRIEF_NEWS", False)))
        except Exception as e:  # noqa: BLE001 — the brief stands without it
            out.append(f"watching: not known just now ({type(e).__name__})")
    news = []
    if getattr(config, "PORTFOLIO_BRIEF_NEWS", False) and held:
        if getattr(config, "OFFLINE", False):
            news = ["(headlines: this house is offline — not asked)"]
        else:
            failed = False
            for s_, hd in held:
                q = quotes.get(s_) or {}
                got = _headlines(s_, q.get("name") or "", until_all)
                if got is None:
                    failed = True
                    continue
                for it in got:
                    t = it["title"] if len(it["title"]) <= 90 else it["title"][:89].rstrip() + "…"
                    news.append(f"· {t} — {it['host']}" + (f", {it['age']}" if it.get("age") else ""))
            if news or failed:
                news = ["said today (headlines as found — not checked facts)"] + news + \
                       (["(headlines could not be fetched)"] if failed else [])
    body = [tag + ln for ln in out]
    text = "\n".join(body + [tag + ln for ln in news])
    if len(text) > BRIEF_LIMIT:
        text = "\n".join(body)
        if len(text) > BRIEF_LIMIT - 20:
            text = text[:BRIEF_LIMIT - 20].rsplit("\n", 1)[0]
        text += "\n(shortened)"
    return text
