"""The friend's books, for the keeper's phone: where they are in each, so the keeper knows when to bring a new one.

    report(now)     /books: the books in hand (where they stand, how much is left, their last sitting), the shelf not
                    opened yet, the books they finished — plain text, read-only
    finished_due()  the books finished since the last look, each as one line for the phone; first look (or a state
                    file that can't be read): every finished book recorded as told, nothing said

Everything comes from what the engine already keeps: memory/bookmarks.json (tools._bookmarks) and the shelf
(tools.unopened_books). Nothing here opens a book, moves a bookmark, reads their notes or tells the friend anything; the
only file written is memory/books_seen.json — which finished books the phone has been told of.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

import config
import tools

_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
SHELF_NAMES = 10     # /books: the unopened shelf names this many, then "+N more"
FINISHED_NAMES = 8   # /books: the newest finished books named, then "+N earlier"
HAND_NAMES = 15      # /books: the books in hand named (newest sitting first), then "+N more"
TITLE_CHARS = 80     # a title or file name longer than this is cut with "…"
REPLY_CHARS = 3500   # /books never longer than this (one Telegram message is 4,096)


def seen_file() -> Path:
    return config.MEMORY_DIR / "books_seen.json"


def _friend() -> str:
    try:
        import chat
        return chat.friend_name()
    except Exception:  # noqa: BLE001 — a name for a line, never the line lost
        return "Friend"


# ---------------------------------------------------------------------------- the ledger, read --------------------
def _ledger() -> tuple[dict, str]:
    """(entries, why-empty): why is "" when the ledger was read, "missing" or "broken" otherwise."""
    f = Path(getattr(tools, "_BOOKMARKS_FILE", config.MEMORY_DIR / "bookmarks.json"))
    if not f.exists():
        return {}, "missing"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, "broken"
    if not isinstance(d, dict):
        return {}, "broken"
    return d, ""


def _clean_name(name: str) -> str:
    """A file name as a title: no extension, underscores as spaces, a trailing ISBN gone."""
    s = re.sub(r"\.(pdf|epub)$", "", str(name), flags=re.I)
    s = re.sub(r"[_]+", " ", s)
    s = re.sub(r"[\s-]*\b(97[89]\d{10}|\d{9}[\dXx])\s*$", "", s)
    return re.sub(r"\s+", " ", s).strip() or str(name)


def _title(name: str, bm: dict) -> str:
    t = str(bm.get("title") or "").strip()
    if not t or t.lower() in ("(untitled)", "untitled", "unknown"):
        return _clean_name(name)
    return t


def _day(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _label(d: date, now: date) -> str:
    return f"{_MON[d.month - 1]} {d.day}" + (f", {d.year}" if d.year != now.year else "")


def _ago(d: date, now: date) -> str:
    n = (now - d).days
    when = "today" if n == 0 else "yesterday" if n == 1 else f"{n} days ago" if n > 1 else "ahead of the clock"
    return f"{when} ({_label(d, now)})"


def _nth(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _num(v) -> int:
    """A whole number from the ledger; anything else (text, NaN, Infinity, 1e400) is missing — 0."""
    try:
        if isinstance(v, float) and v != v:  # NaN
            return 0
        return int(v or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _cut(s: str, n: int = TITLE_CHARS) -> str:
    s = str(s)
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def books(entries: dict) -> list[dict]:
    """Every entry that is a book (tools._is_book), with open_books' rules: kind from the name when it lacks one, the
    position by chapter (EPUB) or page (PDF), finished = `finished` set or the position at the end. A total of 0 or
    less is not a book (and not finished)."""
    out = []
    for name, bm in entries.items():
        if not isinstance(bm, dict):
            continue
        kind = bm.get("kind") or ("epub" if str(name).lower().endswith(".epub") else "pdf")
        total = _num(bm.get("total"))
        if total <= 0 or not tools._is_book(kind, total):
            continue
        at = _num(bm.get("chapter" if kind == "epub" else "page"))
        out.append({"name": str(name), "bm": bm, "kind": kind, "total": total, "at": at,
                    "title": _cut(_title(name, bm)), "finished": bool(bm.get("finished")) or at >= total,
                    "fin_day": _day(bm.get("finished")), "sat": _day(bm.get("date")),
                    "reading": max(1, _num(bm.get("reading")))})
    return out


def _where(b: dict) -> str:
    unit = "chapter" if b["kind"] == "epub" else "page"
    return f"{unit} {b['at']} of {b['total']}"


def _in_hand_line(b: dict, now: date) -> str:
    unit = "chapter" if b["kind"] == "epub" else "page"
    left = max(0, b["total"] - b["at"])
    pct = int(100 * b["at"] / b["total"]) if b["total"] else 0
    line = f"· “{b['title']}” — {_where(b)} ({pct}%), {left} {unit}{'' if left == 1 else 's'} left"
    if b["reading"] > 1:
        line += f"; their {_nth(b['reading'])} reading"
    if not b["sat"]:
        return line + "; no date on its bookmark"
    line += f"; last sitting {_ago(b['sat'], now)}"
    open_days = _num(getattr(config, "READING_OPEN_DAYS", 30))
    age = (now - b["sat"]).days
    if open_days > 0 and age > open_days:
        line += f" — untouched {age} days"
    return line


def _fin_key(b: dict):
    return (b["fin_day"] or b["sat"] or date.min, b["sat"] or date.min)


def _unopened(entries: dict) -> list[str]:
    """The books on the shelf with no bookmark among the entries already read — the same rule as its twin
    tools.unopened_books (an EPUB anywhere, a PDF in a folder called books), but never a second read of the ledger:
    a ledger caught half-written must not make read books look unopened."""
    marks = {str(k).lower() for k in entries}
    out = []
    try:
        for p in tools._shelf_files():
            ext = p.suffix.lower()
            if ext == ".epub" or (ext == ".pdf" and any(q.name.lower() == "books" for q in p.parents)):
                if p.name.lower() not in marks:
                    out.append(_cut(p.stem))
    except Exception:  # noqa: BLE001 — a shelf that can't be looked at is left out, never the answer
        return []
    return out


def _names(names: list[str], cap: int, more: str) -> str:
    s = ", ".join(names[:cap])
    return s + (f" (+{len(names) - cap} {more})" if len(names) > cap else "")


def _fit(text: str, limit: int = REPLY_CHARS) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit - 40)
    return text[:cut if cut > 0 else limit - 40].rstrip() + "\n… (cut to fit one message)"


# ---------------------------------------------------------------------------- /books -------------------------------
def report(now: date | None = None) -> str:
    """/books, as plain text. Read-only: nothing is opened, moved, written or marked seen."""
    now = now or date.today()
    friend = _friend()
    entries, why = _ledger()
    if why == "broken":  # no shelf either: with no ledger, every book they have read would look unopened
        return (f"({friend}'s bookmarks can't be read right now — memory/bookmarks.json; nothing was changed — "
                "try again in a moment)")
    shelf = _unopened(entries)
    if why:
        line = f"(no bookmarks yet — {friend} hasn't opened a book)"
        if shelf:
            line = line[:-1] + f"; on the shelf, not opened yet: {_names(shelf, SHELF_NAMES, 'more')})"
        return _fit(line)
    bs = books(entries)
    hand = sorted((b for b in bs if not b["finished"]), key=lambda b: b["sat"] or date.min, reverse=True)
    done = sorted((b for b in bs if b["finished"]), key=_fin_key, reverse=True)
    # the caps, then smaller ones while the reply would not fit one message; cutting the text is the last resort
    for caps in ((HAND_NAMES, SHELF_NAMES, FINISHED_NAMES), (8, 6, 5), (5, 3, 3), (3, 2, 2)):
        text = _report(now, friend, hand, done, shelf, *caps)
        if len(text) <= REPLY_CHARS:
            return text
    return _fit(text)


def _report(now: date, friend: str, hand: list, done: list, shelf: list, n_hand: int, n_shelf: int,
            n_done: int) -> str:
    parts = [f"{friend}'s books — {_label(now, now)}"]
    if hand:
        rows = [_in_hand_line(b, now) for b in hand[:n_hand]]
        if len(hand) > n_hand:
            rows.append(f"+{len(hand) - n_hand} more — the ones sat with longest ago are left out")
        parts.append(f"In hand ({len(hand)}):\n" + "\n".join(rows))
    elif done:
        last = done[0]
        when = _ago(last["fin_day"], now) if last["fin_day"] else "(no date)"
        parts.append(f"No book in hand. The last one {friend} finished: {last['title']}, {when}")
    else:
        parts.append("No book in hand, and none finished yet.")
    if shelf:
        parts.append(f"On the shelf, not opened yet ({len(shelf)}): {_names(shelf, n_shelf, 'more')}")
    if done:
        rows = []
        for b in done[:n_done]:
            row = f"· “{b['title']}” — " + (_label(b["fin_day"], now) if b["fin_day"] else "read to the end, undated")
            if b["reading"] > 1:
                row += f" ({_nth(b['reading'])} reading)"
            rows.append(row)
        if len(done) > n_done:
            rows.append(f"+{len(done) - n_done} earlier")
        parts.append(f"Finished ({len(done)}):\n" + "\n".join(rows))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------- the notice ---------------------------
def _mark(b: dict) -> dict:
    return {"finished": str(b["bm"].get("finished") or ""), "reading": b["reading"]}


def _is_new(b: dict, told: dict | None) -> bool:
    """A finished book not told yet — or told for an earlier reading, or an earlier finish of it."""
    if not isinstance(told, dict):
        return True
    if b["reading"] > _num(told.get("reading")):
        return True
    now_f, then_f = str(b["bm"].get("finished") or ""), str(told.get("finished") or "")
    # A known gap: told while undated (read to the end, no `finished` yet), then begun again WITHOUT the reading count
    # going up and finished again — then_f is "" so this second finish is not told.
    return bool(now_f and then_f and now_f != then_f)


def _read_state() -> dict | None:
    try:
        raw = json.loads(seen_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) and isinstance(raw.get("told"), dict) else None


def _save(state: dict) -> None:
    f = seen_file()
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def _notice(b: dict, bs: list[dict], shelf: list[str], friend: str) -> str:
    again = f" (their {_nth(b['reading'])} reading)" if b["reading"] > 1 else ""
    hand = sorted((x for x in bs if not x["finished"]), key=lambda x: x["sat"] or date.min, reverse=True)
    if hand:
        still = "; ".join(f"“{x['title']}”, {_where(x)}" for x in hand[:2]) + (f" (+{len(hand) - 2} more)" if len(hand) > 2 else "")
        rest = f"still in hand: {still}"
    else:
        rest = "no book in hand now"
    if shelf:
        rest += f"; {len(shelf)} unopened on the shelf: {_names(shelf, 5, 'more')}"
    else:
        rest += "; nothing unopened on the shelf"
    return f"({friend} finished “{b['title']}”{again} — {rest}. /books shows the shelf)"


def finished_due() -> list[tuple[str, tuple[str, dict]]]:
    """The books finished since the last look, as (line, mark) — NOT yet marked told: the bridge calls told(mark) once
    the line went (or was held for the morning), so a send that fails is told at the next look. No state yet (or one
    that can't be read): every finished book is recorded as told and nothing is said. No ledger yet, or one that can't
    be read: nothing, nothing written."""
    entries, why = _ledger()
    if why:  # no ledger yet (the first look once a book is opened seeds the state) or one unreadable
        return []
    bs = books(entries)
    raw = _read_state()
    if raw is None:
        _save({"told": {b["name"]: _mark(b) for b in bs if b["finished"]}, "since": date.today().isoformat()})
        return []
    told, out, quiet = raw["told"], [], False
    shelf = _unopened(entries)
    friend = _friend()
    for b in bs:
        if not b["finished"]:
            continue
        if _is_new(b, told.get(b["name"])):
            out.append((_notice(b, bs, shelf, friend), (b["name"], _mark(b))))
        elif told[b["name"]] != _mark(b):  # read to the end, then dated by the reading tool: the same finish, kept quietly
            told[b["name"]] = _mark(b)
            quiet = True
    if quiet:
        _save(raw)
    return out


def told(mark: tuple[str, dict]) -> None:
    """One line went to the phone (or into the morning's held list): its book marked told. A state that can't be read
    now is left alone — the next look re-seeds it silently, this book among the finished."""
    raw = _read_state()
    if raw is None:
        return
    name, rec = mark
    raw["told"][str(name)] = dict(rec)
    _save(raw)
