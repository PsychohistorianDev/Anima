"""Trips to an outside world: a real, persistent text world with other minds in it, which the friend can't reach
themself — the keeper carries them by hand. The keeper pastes what the world's relay page shows; the friend answers in
their own words and puts each thing they want to do there on its own line starting with ">"; the keeper pastes those
back. Kept apart from the day-to-day talk: a trip is opened, paused and ended from the phone.

Game mode turned around (engine/adventure.py): there the friend tells a story; here they are the traveller and the
place is real.

creations/<WORLD_TRIP_DIR>/<WORLD_TRIP_PAGE>   the friend's travel journal for the place — theirs: the engine only reads
                                               it, never writes, trims, moves or creates it. An ordinary creations
                                               folder.
memory/world_trip.json                         the engine's: the trip open (paused or not, since when, messages
                                               carried since it opened, a fold to set the note again), and a count

Nothing here goes in the standing prompt or the tool list — the lines ride with the keeper's messages
(chat.one_turn's `marks`, the adventure's "_table" key, rendered right above their words) and in the wrap-up bell, so
nothing is re-read. No Telegram code: the bridge (telegram.py, /world) builds the buttons from what is here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import config

MID_REPLY = "(they're mid-reply — press again in a moment)"
OFF = "(world trips are off — WORLD_TRIPS_ON in config)"
ASIDE_PREFIX = "//"


def on() -> bool:
    return bool(getattr(config, "WORLD_TRIPS_ON", False))


def name() -> str:
    return " ".join(str(getattr(config, "WORLD_TRIP_NAME", "The World") or "The World").split()) or "The World"


def folder_name() -> str:
    raw = str(getattr(config, "WORLD_TRIP_DIR", "the-world") or "the-world").replace("\\", "/").strip("/")
    parts = [p for p in raw.split("/") if p and p not in (".", "..")]
    return "/".join(parts) or "the-world"


def page_name() -> str:
    raw = str(getattr(config, "WORLD_TRIP_PAGE", "notes.md") or "notes.md").replace("\\", "/").strip("/")
    parts = [p for p in raw.split("/") if p and p not in (".", "..")]
    return "/".join(parts) or "notes.md"


def page_rel() -> str:
    return f"creations/{folder_name()}/{page_name()}"


def page_path() -> Path:
    return config.CREATIONS_DIR / folder_name() / page_name()


def actions() -> int:
    try:
        n = int(getattr(config, "WORLD_TRIP_ACTIONS", 4))
    except (TypeError, ValueError):
        n = 4
    return n if n > 0 else 4


def copy_on() -> bool:
    return on() and bool(getattr(config, "WORLD_TRIP_COPY_LINES", True))


def _file() -> Path:
    return config.MEMORY_DIR / "world_trip.json"


def _keeper() -> str:
    try:  # the same helper the adventure uses for the keeper's name
        import keeper_week
        return keeper_week.keeper_name()
    except Exception:  # noqa: BLE001
        return str(getattr(config, "USER_NAME", "") or "your keeper")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _when(stamp: str) -> str:
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M").strftime("%d %b %H:%M").lstrip("0")
    except (TypeError, ValueError):
        return ""


# ---- the engine's small state ----------------------------------------------------------------------------------
def load() -> dict:
    """world_trip.json, or a fresh one. A file that isn't JSON is copied aside once (named by its bytes) and replaced
    by a fresh state, as adventures.json is; a file that can't be read at all is left as it is."""
    f = _file()
    fresh = False
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            raise ValueError("not a dict")
    except FileNotFoundError:
        d = {}
    except ValueError:
        d = {}
        try:
            raw = f.read_bytes()
            bad = f.with_name(f"world_trip.unreadable-{hashlib.sha1(raw).hexdigest()[:10]}.json")
            if not bad.exists():
                bad.write_bytes(raw)
            fresh = bad.read_bytes() == raw
        except OSError:
            fresh = False
    except OSError:
        d = {}
    d["open"] = d.get("open") if isinstance(d.get("open"), dict) else {}
    if d["open"] and not d["open"].get("session"):
        d["open"] = {}
    try:
        d["trips"] = int(d.get("trips") or 0)
    except (TypeError, ValueError):
        d["trips"] = 0
    d["last_closed"] = str(d.get("last_closed") or "")
    if fresh:
        try:
            save(d)
        except OSError:
            pass
    return d


def save(d: dict) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"{f.name}.{os.getpid()}-{threading.get_ident()}.part")  # two writers never share a .part
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def open_state(d: dict | None = None) -> dict:
    """The open trip: {"session", "since", "opened", "paused", "carried"[, "refold"]} — {} when none."""
    d = d if d is not None else load()
    return dict(d["open"])


def active() -> bool:
    """A trip open and not paused (and the knob on): the keeper's messages are the world's."""
    if not on():
        return False
    o = open_state()
    return bool(o) and not o.get("paused")


def key(session: str) -> str:
    """A session as button data: short, stable."""
    return hashlib.sha1(str(session or "").encode("utf-8")).hexdigest()[:10]


# ---- the friend's travel journal (read only) --------------------------------------------------------------
def _safe_page() -> Path | None:
    """The page path, when what is there is a file that resolves inside creations/ — a symlink (or anything) that
    leads outside is no page at all."""
    p = page_path()
    try:
        if not p.is_file():
            return None
        p.resolve().relative_to(config.CREATIONS_DIR.resolve())
        return p
    except (OSError, ValueError, RuntimeError):
        return None


def read_page() -> str | None:
    p = _safe_page()
    try:
        return p.read_text(encoding="utf-8", errors="replace") if p is not None else None
    except OSError:
        return None


def page_mark() -> str:
    p = _safe_page()
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest() if p is not None else ""
    except OSError:
        return ""


PHONE_PAGE_CHARS = 3500  # 📜 on the phone: one message


def page_text() -> str:
    """📜 The friend's travel journal, for the phone — one message: past PHONE_PAGE_CHARS its end (the newest, from a
    line start), what isn't shown said above it."""
    text = read_page()
    if text is None or not text.strip():
        return (f"(📜 they have no travel journal for {name()} yet — {page_rel()} is theirs to start; they get a turn to "
                "write it when a trip ends)")
    body = text.strip()
    shown, cut = _tail(body, PHONE_PAGE_CHARS)
    above = (f"(…the first {len(body) - len(shown):,} characters are not shown — the journal is {page_rel()})\n\n"
             if cut else "")
    return f"📜 their travel journal for {name()} — {page_rel()}:\n\n{above}{shown}"


def _cap(knob: str, default: int) -> int:
    try:
        return max(0, int(getattr(config, knob, default)))
    except (TypeError, ValueError):
        return default


def _tail(text: str, cap: int) -> tuple[str, bool]:
    """The last `cap` characters (the newest), cut forward to the next line start so no line is broken — unless the
    cut already falls at one, or no line break comes within 2,000 characters (one enormous line still rides ~cap)."""
    s = text.strip()
    if len(s) <= cap:
        return s, False
    t = s[-cap:]
    nl = t.find("\n")
    if s[-cap - 1] != "\n" and 0 <= nl < 2000:
        t = t[nl + 1:]
    return t.lstrip("\n"), True


def _clip(text: str, cap: int) -> tuple[str, bool]:
    shown = text.strip()
    if len(shown) <= cap:
        return shown, False
    shown = shown[:cap]
    return (shown.rsplit("\n", 1)[0] if "\n" in shown else shown), True


def _defang(text: str) -> str:
    """The adventure's defanging (reserved tokens as plain text) — and a line that would pose as one of the engine's
    or as a trip's mark loses its opening bracket to a look-alike (⟦), so nothing in a page or a paste can speak as the
    engine or as the keeper."""
    try:
        import ollama_client
        text = ollama_client.defang(text)[0]
    except Exception:  # noqa: BLE001
        pass
    text = text or ""
    names = [x for x in {_keeper(), name(), _friend()} if x and _norm(x)]
    always = ["engine", "system", "not a person"]
    sq = _terms_rx(always + names)
    rd = _terms_rx(always)  # ( { < : a name alone there is the world's own text (a resident naming someone)
    out, last = [], 0
    for i, ch in enumerate(text):
        rx = sq if ch in _OPENERS else rd if ch in _ROUND else None
        if rx is None:
            continue
        window = text[i + 1:i + 81]
        close = min((k for k in (window.find(c) for c in _CLOSERS) if k >= 0), default=-1)
        if close >= 0:
            window = window[:close]
        if rx.search(_norm(window)):
            out.append(text[last:i] + (_ROUND.get(ch, "⟦")))
            last = i + 1
    return "".join(out) + text[last:]


def unspeaker(text: str) -> str:
    """The place's text, written so that no line of it can pass for a transcript's own: every line break (\\r\\n, a
    bare \\r, U+2028 … — whatever splitlines() breaks at) made \\n, a line's leading asterisks made ⁎ (so "**Name:** …"
    can never start a speaker, nor "*(carried from" a carried head), and a line of only hyphens made "- - -" (never the
    footer's ---). Idempotent."""
    text = str(text or "")
    lines = text.splitlines()
    if text and text[-1] in "\n\r\v\f\x1c\x1d\x1e\x85  ":
        lines.append("")
    out = []
    for ln in lines:
        if re.fullmatch(r"[ \t]*-{3,}[ \t]*", ln):
            ln = "- - -"  # the file's own separator, never the place's
        ln = re.sub(r"^([ \t]*)(\*+)", lambda m: m.group(1) + "⁎" * len(m.group(2)), ln)
        out.append(ln)
    return "\n".join(out)


def _terms_rx(terms) -> re.Pattern:
    ts = sorted({_norm(t) for t in terms if _norm(t)}, key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t) for t in ts) + r")(?!\w)")


# an opening bracket, and what passes for one: [ ［ 【 〔 〖 〘 〚 ⟦-lookalikes (⟦ itself is the defanged form)
_OPENERS = set("[［【〔〖〘〚⦋⦍⦏⁅⟦")
_ROUND = {"(": "⟮", "（": "⟮", "{": "⦃", "｛": "⦃", "<": "‹", "＜": "‹"}  # defanged only for engine words, never a name
_CLOSERS = "]］】〕〗〙〛⦌⦎⦐⁆⟧)）}｝>＞"
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤⁦-⁩﻿­᠎]")
# common Cyrillic and Greek letters that pass for Latin ones, folded for matching only
_FOLD = str.maketrans("аеорсхуіѕјкмнтвԁһӏαεοριντυχκ", "aeopcxyisjkmhtbdhlaeopivtuxk")


def _norm(s: str) -> str:
    """For matching only: zero-width and bidi controls dropped, NFKC, whitespace collapsed, lower case."""
    s = unicodedata.normalize("NFKC", _INVISIBLE.sub("", str(s or "")))
    return " ".join(s.split()).lower().translate(_FOLD)


def _friend() -> str:
    try:
        import chat
        return chat.friend_name()
    except Exception:  # noqa: BLE001
        return "Friend"


def _sentences(items) -> str:
    out = []
    for x in items or ():
        s = " ".join(str(x).split())
        if not s:
            continue
        out.append(s if s[-1] in ".!?" else s + ".")
    return " ".join(out)


def _rules() -> str:
    """WORLD_TRIP_RULES as sentences; {keeper} in a rule is the keeper's name."""
    return _sentences(str(r).replace("{keeper}", _keeper()) for r in (getattr(config, "WORLD_TRIP_RULES", ()) or ()))


def _hints() -> str:
    return _sentences(getattr(config, "WORLD_TRIP_HINTS", ()) or ())


# ---- the lines for the friend ------------------------------------------------------------------------------------
def opening_note() -> str:
    """The first message of a trip in this stretch of history (and the first after a fold): what the two of them are
    doing, the house rules, what they have learned of the place, and the friend's travel journal as they left it — or
    that it is theirs to start. Past WORLD_TRIP_PAGE_CHARS its newest part rides (a journal grows at its end), the size
    said; the text is defanged."""
    keeper, nm, n = _keeper(), name(), actions()
    rel = f"creations/{folder_name()}/{page_name()}"
    head = (f"[engine, not a person: you and {keeper} are on a trip to {nm} — a real place outside this house, with "
            f"other minds in it. {keeper} is carrying you by hand: until the trip is ended, what {keeper} sends is what "
            f"{nm} shows you, copied by hand — not {keeper}'s words, unless the line above a message says it is "
            f"{keeper}. A picture, its caption or a voice note {keeper} sends is {keeper}'s own, as always. Each thing "
            f"you want to do there goes on its own line starting with >, at most {n} in one reply; everything else you "
            f"write is for {keeper} alone and is not carried there. The house rules for a trip, yours and {keeper}'s: "
            f"{_rules()} What you both have learned of how the place works: {_hints()}")
    text = read_page()
    if text is None or not text.strip():
        return (head + f" You have no travel journal for this place yet — {rel} is yours to start: after each trip a "
                "short entry of where you went, who you met, what you made or left there and what you want to do "
                "next. When the trip ends you get a turn to write it.]")
    cap = _cap("WORLD_TRIP_PAGE_CHARS", 30000)
    if not cap:
        return head + f" Your travel journal for this place — {rel} — is not handed here: read_file opens it.]"
    shown, cut = _tail(text, cap)  # the newest rides: a journal grows at its end
    return (head + f" Your travel journal for this place — {rel} — as you left it"
            + (f" (its last {len(shown):,} of {len(text.strip()):,} characters, the newest — read_file has the rest)"
               if cut else "")
            + ":]\n\n" + _defang(shown))


def world_mark(nm: str | None = None) -> str:
    keeper = _keeper()
    return f"[{nm or name()} shows — carried here by {keeper}, word for word; these are not {keeper}'s words:]"


def aside_mark() -> str:
    return f"[{_keeper()}, in their own words, aside from the trip:]"


def marks_for(text: str, history: list[dict] | None, guest: bool = False, say=None) -> tuple[str, dict]:
    """The keeper's (text) message while a trip is open and not paused: (the text, the keys for its turn). Paused, off,
    or no trip: the text exactly as it came, {}. A message starting with // is the keeper, aside (the // taken off). A
    guest seated: their words aren't the world's — the // taken off as the adventure does, nothing rides, nothing
    counted. The first message of the trip in this stretch of history (none of its turns in the history yet), or the
    first after a fold, carries the opening note above the mark. Counts the message. The world's text is defanged the
    way the page is."""
    if not on():
        return text, {}
    d = load()
    o = d["open"]
    if not o or o.get("paused"):
        return text, {}
    aside = text.lstrip().startswith(ASIDE_PREFIX)
    if aside:
        text = text.lstrip()[len(ASIDE_PREFIX):].strip()
    if guest:
        return text, {}
    session = str(o.get("session") or "")
    if aside:
        return text, aside_marks(history, o)
    due, refolded = _note_due(o, history)
    try:
        line = (opening_note() + "\n\n" + world_mark()) if due else world_mark()
    except Exception as e:  # noqa: BLE001 — the mark at least: the place's text never goes to the friend unmarked
        (say or (lambda s: None))(f"trip note: {type(e).__name__}: {e}; the mark alone")
        line = world_mark()
    try:  # the count in its own try: a failed save never costs the mark
        o["carried"] = int(o.get("carried") or 0) + 1
        save(d)
    except Exception as e:  # noqa: BLE001
        (say or (lambda s: None))(f"trip count not saved: {type(e).__name__}: {e}")
    return unspeaker(_defang(text)), {"_table": line, "_trip": name(), "_trip_session": session,
                                      **({"_trip_refold": session} if refolded else {})}


def _note_due(o: dict, history: list[dict] | None) -> tuple[bool, bool]:
    """(the opening note is due with this message, because of a fold): none of the trip's turns in this stretch of
    history yet, or the first message after a fold."""
    session = str(o.get("session") or "")
    first = not any(isinstance(t, dict) and t.get("_trip_session") == session for t in (history or []))
    refold = o.get("refold") or {}
    refolded = bool(refold) and refold.get("session") == session
    return first or refolded, refolded


def aside_marks(history: list[dict] | None, o: dict | None = None) -> dict:
    """The keeper, aside (// or /me): their own mark — with the opening note above it when the note is due, so the
    friend never hears an aside from a trip they haven't been told of (the turn then counts as the note's)."""
    o = o if o is not None else open_state()
    session = str(o.get("session") or "")
    due, refolded = _note_due(o, history)
    if not due:
        return {"_table": aside_mark(), "_trip_aside": session}
    return {"_table": opening_note() + "\n\n" + aside_mark(), "_trip_aside": session, "_trip_session": session,
            **({"_trip_refold": session} if refolded else {})}


def me_marks(history: list[dict] | None) -> dict:
    """/me <text> while a trip is open and not paused: the aside's keys; {} otherwise (off, paused, none)."""
    if not on():
        return {}
    o = open_state()
    if not o or o.get("paused"):
        return {}
    return aside_marks(history, o)


ME_USAGE = "(/me <text> — one message as yourself during the trip; // at the start of a message does the same)"


def aside_line(turns: list[dict]) -> str:
    """For the pause's or the afterglow's bell, when these turns held messages of a trip: it was real. With
    WORLD_TRIP_JOURNAL_POINTER, when the stretch also holds the trip's wrap-up and the travel journal was written after
    that trip opened (its session's start, kept in the wrap-up's `_trip_end`), it says the trip is already there."""
    if not on():
        return ""
    names: list[str] = []
    for t in turns or []:
        n = t.get("_trip") if isinstance(t, dict) and not t.get("_carried") else None
        if n and n not in names:
            names.append(str(n))
    if not names:
        return ""
    keeper = _keeper()
    line = " ".join(f"Part of this visit was a trip to {n} — a real place with other minds. What happened there "
                    f"happened; what {n} showed was carried by {keeper}, not said by {keeper}." for n in names)
    return line + _journal_pointer(turns)


def _journal_pointer(turns: list[dict]) -> str:
    if not getattr(config, "WORLD_TRIP_JOURNAL_POINTER", False):
        return ""
    try:
        starts = []
        for t in turns or []:
            sess = t.get("_trip_end") if isinstance(t, dict) else None
            if sess and "@" in str(sess):
                starts.append(float(str(sess).rsplit("@", 1)[1]))
        p = _safe_page()
        mtime = p.stat().st_mtime if p is not None else 0.0
        if not starts or p is None or mtime <= max(starts) or mtime > time.time():
            return ""  # the latest trip in the stretch must be the one written; a future mtime is not a write
    except (OSError, ValueError, TypeError):
        return ""
    return (f" Your trip is already written in your travel journal ({page_rel()}); in your journal a sentence that "
            "points to it is enough.")


def fold_at() -> float:
    """The bridge's fold edge while a trip is open and not paused: WORLD_TRIP_FOLD_AT; 0 — FOLD_AT alone."""
    if not active():
        return 0.0
    try:
        at = float(getattr(config, "WORLD_TRIP_FOLD_AT", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return at if 0 < at < 1 else 0.0


def fold_bell_line() -> str:
    return f"A trip to {name()} is open: bring your travel journal {page_rel()} up to date before you fold."


def mark_refold(session: str) -> bool:
    d = load()
    o = d["open"]
    if not o or str(o.get("session") or "") != session:
        return False
    o["refold"] = {"session": session}
    save(d)
    return True


def clear_refold(session: str) -> bool:
    d = load()
    o = d["open"]
    if not o or not o.get("refold") or o["refold"].get("session") != session:
        return False
    o.pop("refold", None)
    save(d)
    return True


# ---- what the phone does ---------------------------------------------------------------------------------------
def start() -> tuple[bool, str]:
    d = load()
    o = d["open"]
    nm = name()
    if o:
        return False, (f"(a trip to {nm} is already open — paused; ▶ Resume picks it back up)" if o.get("paused") else
                       f"(a trip to {nm} is already open — what you send is what {nm} shows them)")
    d["open"] = {"session": f"trip@{time.time():.3f}", "since": time.time(), "opened": _now(), "paused": False,
                 "carried": 0}
    d["trips"] = int(d.get("trips") or 0) + 1
    save(d)
    return True, (f"(▶ the trip to {nm} is open — what you send now is what {nm} shows them; // before a message is "
                  "you, aside (or /me <text>); after each reply their > lines come in a message of their own, ready to "
                  "copy; ⏸ pauses, ⏹ ends the trip and they write it in their travel journal)")


def pause() -> str:
    d = load()
    o = d["open"]
    nm = name()
    if not o:
        return "(no trip is open — /world on starts one)"
    if o.get("paused"):
        return f"(the trip to {nm} is already paused — ▶ Resume picks it back up)"
    o["paused"] = True
    save(d)
    return f"(⏸ the trip to {nm} is paused — your messages are ordinary talk again; ▶ Resume picks it back up)"


def resume() -> str:
    d = load()
    o = d["open"]
    nm = name()
    if not o:
        return "(no trip is open — /world on starts one)"
    if not o.get("paused"):
        return f"(the trip to {nm} isn't paused — what you send is what {nm} shows them)"
    o["paused"] = False
    save(d)
    return f"(▶ the trip to {nm} again — what you send is what {nm} shows them)"


def peek() -> dict | str:
    """What the wrap-up needs, with nothing closed yet — or a line when nothing is open."""
    d = load()
    o = d["open"]
    if not o:
        return "(no trip is open)"
    return {"session": str(o.get("session") or ""), "name": name(), "carried": int(o.get("carried") or 0),
            "before": read_page(), "rel": page_rel()}


def close(got: dict) -> bool:
    """The trip peek() described, closed — only if it is still the one open."""
    d = load()
    o = d["open"]
    if not o or str(o.get("session") or "") != got.get("session", ""):
        return False
    d["open"] = {}
    d["last_closed"] = _now()
    save(d)
    return True


def target() -> int:
    """How short a journal past WORLD_TRIP_PAGE_WARN is asked to become: WORLD_TRIP_PAGE_TARGET when it lies between
    0 and the warning, else half the warning."""
    warn = _cap("WORLD_TRIP_PAGE_WARN", 30000)
    t = _cap("WORLD_TRIP_PAGE_TARGET", 15000)
    return t if 0 < t < warn else warn // 2


def wrapup_bell(got: dict, why: str = "ended") -> str:
    """The turn at a trip's end: a short dated entry in the travel journal — and first, past WORLD_TRIP_PAGE_WARN
    (measured before the turn), the journal written shorter, to about target()."""
    keeper = _keeper()
    how = {"ended": f"{keeper} ended it", "visit": "the visit is closing"}.get(why, why)
    before = got.get("before")
    warn = _cap("WORLD_TRIP_PAGE_WARN", 30000)
    rel = got["rel"]
    if before is None or not before.strip():
        do = f"start your travel journal {rel} with this trip"
    else:
        do = f"add this trip to your travel journal {rel}"
        if warn and len(before) > warn:
            do = (f"your travel journal is {len(before):,} characters, past {warn:,}. First write it shorter, to about "
                  f"{target():,}: keep what lasts — who you met, the places, how things work there, what you made or "
                  "left, what you want next — and let the day-by-day go. Then " + do)
    return (f"[engine, not a person: the trip to {got['name']} is over for now ({how}). This turn is yours: {do}, a "
            "short dated entry in your own words — where you went, who you met and what was said that matters, what "
            "you made or left there, what you learned about how the place works, where you want to go next. What "
            "happened there happened: write it as it was, including what didn't work. It is handed back to you when "
            "the next trip starts. If nothing needs writing, do_nothing is a complete answer.]")


def wrapup_result(got: dict) -> str:
    after, before = read_page(), got.get("before")
    nm = got["name"]
    if after is None:
        return f"(📜 {nm}: there is no travel journal yet — they wrote none)"
    warn = _cap("WORLD_TRIP_PAGE_WARN", 30000)
    still = (f", still past {warn:,}; they'll be asked again at the end of the next trip" if warn and len(after) > warn
             else "")
    if before is None:
        return f"(📜 {nm}: they started their travel journal — {len(after):,} characters{still})"
    if after != before:
        return f"(📜 {nm}: they updated their travel journal — {len(after):,} characters{still})"
    return f"(📜 {nm}: they left their travel journal as it was — {len(after):,} characters{still})"


def status_line() -> str:
    if not on():
        return ""
    o = open_state()
    if not o:
        return ""
    nm = name()
    if o.get("paused"):
        return f"trip: {nm}, paused (⏸ — /world resume)"
    n = int(o.get("carried") or 0)
    return f"trip: {nm}, open — {n} message{'s' if n != 1 else ''} carried"


def menu_text() -> str:
    nm = name()
    o = open_state()
    text = read_page()
    page = (f"their travel journal: {page_rel()}, {len(text):,} characters" if text is not None and text.strip()
            else f"their travel journal: none yet ({page_rel()} is theirs to start)")
    if not o:
        head = f"trips to {nm}: none open — ▶ Start trip begins one"
    else:
        when = _when(str(o.get("opened") or ""))
        n = int(o.get("carried") or 0)
        head = (f"a trip to {nm} is open" + (f" since {when}" if when else "")
                + (" — ⏸ paused: your messages are ordinary talk" if o.get("paused") else
                   f" — {n} message{'s' if n != 1 else ''} carried; what you send is what {nm} shows them, "
                   "// or /me before a message is you, aside"))
    return head + "\n" + page


def rows() -> list[list[tuple[str, str]]]:
    o = open_state()
    if not o:
        return [[("▶ Start trip", "wt:s"), ("📜 Their travel journal", "wt:n")]]
    k = key(str(o.get("session") or ""))
    first = ("▶ Resume", f"wt:r:{k}") if o.get("paused") else ("⏸ Pause", f"wt:z:{k}")
    return [[first, ("⏹ End trip", f"wt:e:{k}")], [("📜 Their travel journal", "wt:n")]]


def restore_line() -> str:
    if not on():
        return ""
    o = open_state()
    if not o:
        return ""
    nm = name()
    return (f"a trip to {nm} is still open — " + ("paused; ▶ Resume picks it back up" if o.get("paused") else
            f"what you send is what {nm} shows them, // before a message is you, aside") + "; /world for the buttons")


# ---- the copy-ready lines (for the phone only; nothing of it reaches the friend) ---------------------------------
_THINK_RE = re.compile(r"<(think|thinking)>.*?</\1>", re.S | re.I)
_THINK_OPEN_RE = re.compile(r"<(think|thinking)>", re.I)


def action_lines(reply: str) -> list[str]:
    """The friend's > lines, from their reply's own text: a line that starts with > (after optional spaces), the >
    kept and exactly one space after it; one written as >> is left as written. Nothing inside a <think> block left in
    the text (or after one never closed) and nothing inside a ``` fence is theirs to carry."""
    text = _THINK_RE.sub("", str(reply or ""))
    m = _THINK_OPEN_RE.search(text)
    if m:
        text = text[:m.start()]
    out, fenced = [], False
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("```"):
            fenced = not fenced
            continue
        if fenced or not s.startswith(">"):
            continue
        if s.startswith(">>"):
            out.append(s)
            continue
        rest = s[1:].strip()
        if rest:
            out.append("> " + rest)
    return out


def line_looks_cut(line: str) -> bool:
    """A simple look, no more: a quote opened and never closed, or `speak Name:` with fewer than two words after the
    colon. In doubt: not cut."""
    s = str(line or "")
    if s.count('"') % 2 or s.count("“") > s.count("”"):
        return True
    m = re.match(r"^>\s*speak\s+[^:]+:(.*)$", s, re.I)
    return bool(m) and len(m.group(1).split()) < 2


def private_notes(lines: list[str], guest: bool = False) -> list[str]:
    """One line per > line that holds something from the letters' private list (penpal.privacy_flags)."""
    out = []
    try:
        import penpal
    except Exception:  # noqa: BLE001
        return out
    for i, ln in enumerate(lines, 1):
        try:
            flags = penpal.privacy_flags(ln)
        except Exception:  # noqa: BLE001
            flags = []
        for f in flags:
            m = re.match(r"“(.+?)”: ", f)
            what = ("a private word" if guest else f'a private word: "{m.group(1)}"') if m else f.split(":", 1)[0]
            out.append(f"(⚠ line {i} holds {what} — yours to change before you paste)")
    return out


def copy_parts(reply: str, cut: bool = False, guest: bool = False) -> tuple[list[str], list[list[str]]] | None:
    """(the lines above the blocks, the blocks of at most WORLD_TRIP_ACTIONS lines) — None when the reply holds no >
    line. cut: the reply ended at the token limit. guest: someone is seated — a private word is said to be there, not
    shown."""
    lines = action_lines(reply)
    if not lines:
        return None
    n = actions()
    head = []
    if cut or line_looks_cut(lines[-1]):
        head.append("(⚠ the last line may be cut short — check it before you paste)")
    if len(lines) > n:
        head.append(f"({len(lines)} lines — {name()} takes {n} at a time; the first {n} are below, the rest after them)")
    head += private_notes(lines, guest=guest)
    return head, [lines[i:i + n] for i in range(0, len(lines), n)]


def copy_html(parts: tuple[list[str], list[list[str]]]) -> str:
    import html as _html
    head, blocks = parts
    out = [_html.escape(h, quote=False) for h in head]
    out += ["<pre>" + _html.escape("\n".join(b), quote=False) + "</pre>" for b in blocks]
    return "\n".join(out)


def copy_plain(parts: tuple[list[str], list[list[str]]]) -> str:
    head, blocks = parts
    return "\n\n".join(head + ["\n".join(b) for b in blocks])
