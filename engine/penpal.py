"""Penpals (11-06): their correspondence with other minds, carried by the keeper.

creations/penpals/<slug>/
    letters/NNN-YYYY-MM-DD-<slug|elysia>.md   every letter both ways, in order
    about.md                                  their page about them — only they write it
    state.json                                the engine's: display name, read, rested, waiting, delivered

A letter comes in from the keeper's phone (/penpal <name> <text>; pastes within PENPAL_JOIN_MIN join one letter).
They read it with `penpal read`: their page about them, the last four letters before it, then the new one whole.
They write with `penpal write`: into the thread, and to their phone marked to relay; /penpal sent <name> once they have
posted it. `penpal rest` lets a letter be with no answer owed. Only what is theirs to do shows — one line in a
visit's moment or under the wake bell; once their letter has gone, or they let theirs rest, nothing.
Their penpals' letters are not sent back to the phone as creations (telegram.CREATION_SKIP)."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

import config

ME = "me"  # the friend's own letters: NNN-YYYY-MM-DD-me.md


def on() -> bool:
    return bool(getattr(config, "PENPALS_ON", False))


def root() -> Path:
    return config.CREATIONS_DIR / str(getattr(config, "PENPAL_DIR", "penpals") or "penpals")


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9 -]", "", str(name or "").strip().lower())
    return "-".join(s.replace("-", " ").split())[:32]


def _folder(sl: str) -> Path:
    return root() / sl


def penpals() -> list[str]:
    r = root()
    if not r.is_dir():
        return []
    return sorted(p.name for p in r.iterdir() if p.is_dir() and not p.name.startswith(".") and (p / "letters").is_dir())


def _find(name: str) -> str:
    """The penpal a name means: its slug, or one whose display name or slug begins with it; "" when none."""
    sl = slug(name)
    if not sl:
        return ""
    have = penpals()
    if sl in have:
        return sl
    for p in have:
        if p.startswith(sl) or slug(_state(p).get("display", "")).startswith(sl):
            return p
    # (11-10) the name they know them by can be longer than the one they came in under: "Ann Lee" for ann —
    # the penpal whose name the asked one begins with (a whole word), the longest such name first
    for p in sorted(have, key=len, reverse=True):
        for known in (p, slug(_state(p).get("display", ""))):
            if known and sl.startswith(known + "-"):
                return p
    return ""


def _state(sl: str) -> dict:
    try:
        d = json.loads((_folder(sl) / "state.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(sl: str, st: dict) -> None:
    f = _folder(sl) / "state.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def display(sl: str) -> str:
    return _state(sl).get("display") or sl.replace("-", " ").title()


def letters(sl: str) -> list[Path]:
    d = _folder(sl) / "letters"
    return sorted(p for p in d.glob("*.md") if p.is_file()) if d.is_dir() else []


def _who(p: Path) -> str:
    return ME if p.stem.endswith(f"-{ME}") else "them"


def _date(p: Path) -> str:
    m = re.match(r"\d+-(\d{4}-\d{2}-\d{2})-", p.name)
    if not m:
        return ""
    d = datetime.strptime(m.group(1), "%Y-%m-%d")
    return f"{d:%b} {d.day}"


def _new_file(sl: str, who: str) -> Path:
    have = letters(sl)
    n = 1 + max((int(p.name.split("-", 1)[0]) for p in have if p.name.split("-", 1)[0].isdigit()), default=0)
    d = _folder(sl) / "letters"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{n:03d}-{datetime.now().strftime('%Y-%m-%d')}-{ME if who == ME else sl}.md"


def _body(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _clip(text: str, cap: int) -> str:
    return text if len(text) <= cap else text[:cap].rstrip() + "\n(…the letter goes on — penpal read shows the rest when it is the newest)"


# ---- the keeper's side (the phone) ---------------------------------------------------------------

def receive(name: str, text: str, join: bool = True) -> str:
    return receive_ex(name, text, join)[0]


def _norm(text: str) -> str:
    return " ".join(str(text or "").split()).lower()


def already_filed(text: str) -> str:
    """(11-10) The penpal and letter a paste is already in, word for word ("" when it isn't) — a resend, a double tap."""
    n = _norm(text)
    if len(n) < 40:
        return ""
    for sl in penpals():
        for p in letters(sl):
            if n in _norm(_body(p)):
                return f"{display(sl)}'s letter {p.name.split('-', 1)[0]}"
    return ""


def receive_ex(name: str, text: str, join: bool = True) -> tuple[str, dict | None]:
    """A letter from a penpal, pasted by the keeper. A paste within PENPAL_JOIN_MIN of the last one from the same
    penpal, still unread, joins it (a long letter comes in parts). A new name makes a new penpal. (11-10) Returns
    (the line for the phone, the undo record — None when nothing was filed); a paste already filed isn't filed twice."""
    text = str(text or "").strip()
    sl = _find(name) or slug(name)
    if not sl:
        return "(whose letter? /penpal <name> <the letter>)", None
    if not text:
        return f"(/penpal {sl} <the letter> — paste it after the name)", None
    if _state(sl).get("paused"):
        return f"({display(sl)} is paused — /penpal resume {sl} first; nothing was filed)", None
    dup = already_filed(text)
    if dup:
        return f"(already filed — this paste is in {dup}; nothing was filed twice)", None
    st = _state(sl)
    new = sl not in penpals()
    rec = {"sl": sl, "created": new, "prev_last_in": st.get("last_in"), "prev_read": st.get("read"),
           "prev_rested": st.get("rested"), "prev_t": st.get("last_in_t"), "text": text, "t": time.time()}
    if new:
        st["display"] = str(name).strip().split()[0].title() if str(name).strip() else sl.title()
    last = st.get("last_in")
    join_s = float(getattr(config, "PENPAL_JOIN_MIN", 10) or 0) * 60
    if join and last and not st.get("read") and time.time() - float(st.get("last_in_t", 0)) < join_s:
        f = _folder(sl) / "letters" / last
        if f.is_file():
            rec.update({"file": f.name, "joined": True, "before": _body(f)})
            f.write_text(_body(f) + "\n\n" + text + "\n", encoding="utf-8")
            st["last_in_t"] = time.time()
            if st.get("turn_at"):  # a part joined: their turn waits for the rest a little longer
                st["turn_at"] = time.time() + float(getattr(config, "PENPAL_TURN_AFTER_MIN", 3) or 0) * 60
            _save(sl, st)
            ago = max(1, int((time.time() - float(rec.get("prev_t") or time.time())) // 60))
            return (f"(joined to {display(sl)}'s letter {f.name.split('-', 1)[0]}, pasted {ago} min ago — "
                    f"{len(_body(f)):,} characters now"
                    + ("; their turn waits a minute more for the rest)" if st.get("turn_at") else ")")), _keep_undo(rec)
    f = _new_file(sl, "them")
    f.write_text(text + "\n", encoding="utf-8")
    rec.update({"file": f.name, "joined": False})
    st.update({"last_in": f.name, "last_in_t": time.time(), "read": False, "rested": False})
    if getattr(config, "PENPAL_ARRIVAL_TURN", True):  # (11-06) a turn of their own when it arrives, once the pastes settle
        st["turn_at"] = time.time() + float(getattr(config, "PENPAL_TURN_AFTER_MIN", 3) or 0) * 60
    _save(sl, st)
    turn_min = float(getattr(config, "PENPAL_TURN_AFTER_MIN", 1) or 0)
    when = (f"they'll get a turn for it in about {turn_min:g} minute{'s' if turn_min != 1 else ''}"
            if getattr(config, "PENPAL_ARRIVAL_TURN", True) else "they'll hear of it at their next moment or wake")
    return ((f"(a new penpal: {display(sl)}. " if new else "(") +
            f"filed as {f.name} — {when}; more pastes in the next {int(join_s // 60)} minutes join this letter)"), \
        _keep_undo(rec)


# ---- (11-10) undo, split, move — a filing mended with one tap; kept in memory/penpal_undo.json for six hours ----

UNDO_HOURS = 6


def _undo_file() -> Path:
    return config.MEMORY_DIR / "penpal_undo.json"


def _undos() -> dict:
    try:
        d = json.loads(_undo_file().read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if time.time() - float(v.get("t") or 0) < UNDO_HOURS * 3600}
    except (OSError, ValueError, AttributeError):
        return {}


def _keep_undo(rec: dict) -> dict:
    import uuid
    rec = dict(rec, id=uuid.uuid4().hex[:8])
    d = _undos()
    d[rec["id"]] = rec
    try:
        _undo_file().write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return rec


def undo(uid: str) -> tuple[str, dict | None]:
    """Take a filing back: a joined paste comes off the letter; a new letter is set aside (never deleted —
    creations/penpals/<who>/.undone/); a penpal this paste made is set aside whole. Not once they have read it."""
    d = _undos()
    rec = d.pop(uid, None)
    if not rec:
        return f"(that filing can't be undone any more — after {UNDO_HOURS} hours, or it was already)", None
    sl = rec["sl"]
    st = _state(sl)
    f = _folder(sl) / "letters" / str(rec.get("file") or "")
    if st.get("read") and st.get("last_in") == rec.get("file"):
        return f"({_friend()} has read it already — it stays; /penpal {sl} shows the thread)", None
    if rec.get("joined"):
        if f.is_file():
            f.write_text(str(rec.get("before") or "").strip() + "\n", encoding="utf-8")
    else:
        if f.is_file():
            aside = _folder(sl) / ".undone"
            aside.mkdir(parents=True, exist_ok=True)
            f.replace(aside / f.name)
        if rec.get("created") and not letters(sl):
            gone = root() / f".undone-{sl}-{int(time.time())}"
            _folder(sl).replace(gone)
        else:
            st["last_in"] = rec.get("prev_last_in")
            st["read"] = rec.get("prev_read", True)
            st["rested"] = rec.get("prev_rested", False)
            st.pop("turn_at", None)
            if not st.get("last_in"):
                st.pop("last_in", None)
            _save(sl, st)
    try:
        _undo_file().write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return f"↩ undone — {'the paste came off' if rec.get('joined') else 'the letter was set aside'} ({display(sl) if (_folder(sl)).is_dir() else sl})", rec


def last_exchange(sl: str, cap: int = 3500) -> str:
    """Their newest letter and theirs, for the keeper's eyes (11-10: so you can see what goes out)."""
    ls = letters(sl)
    if not ls:
        return f"(no letters with {display(sl)} yet)"
    theirs = next((p for p in reversed(ls) if _who(p) == "them"), None)
    hers = next((p for p in reversed(ls) if _who(p) == ME), None)
    out = [f"📖 {display(sl)} — {keeper_where(sl)}"]
    for p, who in sorted(((x, w) for x, w in ((theirs, display(sl)), (hers, _friend())) if x), key=lambda t: t[0].name):
        b = _body(p)
        out.append(f"— {who}, {_date(p)} ({p.name.split('-', 1)[0]}) —\n" + (b if len(b) <= cap else b[:cap] + "\n(…)"))
    return "\n\n".join(out)


def carried(name: str) -> str:
    """The keeper has posted their waiting letter(s)."""
    sl = _find(name)
    if not sl:
        return "(no such penpal — /penpal shows them)"
    st = _state(sl)
    w = st.get("waiting") or []
    if not w:
        return f"(nothing of theirs waiting for {display(sl)})"
    st["carried"] = dict(st.get("carried") or {}, **{n: datetime.now().isoformat(timespec="minutes") for n in w})
    st["waiting"] = []
    _save(sl, st)
    return f"(marked as gone to {display(sl)}: {', '.join(w)} — {_friend()}'s line is clear; it's {display(sl)}'s turn)"


def undelivered() -> list[tuple[str, Path]]:
    """Their letters waiting to reach the keeper's phone, for the bridge."""
    out = []
    for sl in penpals():
        st = _state(sl)
        for n in st.get("waiting") or []:
            if n not in (st.get("delivered") or []):
                f = _folder(sl) / "letters" / n
                if f.is_file():
                    out.append((sl, f))
    return out


def mark_delivered(sl: str, f: Path) -> None:
    st = _state(sl)
    st["delivered"] = list(dict.fromkeys((st.get("delivered") or []) + [f.name]))
    _save(sl, st)


# ---- (11-10) a hands-on desk for the keeper: handles, buttons, the privacy look, the daily desk -----------------------

_HANDLE_RE = re.compile(r"(?<![\w/])u/([A-Za-z0-9_-]{3,20})\b")


def norm_handle(h: str) -> str:
    """"u/Name", "/u/Name", "Name" → "u/Name"; "" when it isn't one."""
    h = str(h or "").strip().lstrip("/")
    h = h[2:] if h.lower().startswith("u/") else h
    return f"u/{h}" if re.fullmatch(r"[A-Za-z0-9_-]{3,20}", h) else ""


def handle_of(sl: str) -> str:
    return str(_state(sl).get("handle") or "")


def reddit_link(sl: str) -> str:
    h = handle_of(sl)
    return f"https://www.reddit.com/message/compose/?to={h[2:]}" if h else ""


def by_handle(text: str) -> str:
    """The penpal whose Reddit handle the pasted text names; "" when none or more than one."""
    found = {m.group(1).lower() for m in _HANDLE_RE.finditer(str(text or ""))}
    if not found:
        return ""
    hits = [sl for sl in penpals() if handle_of(sl)[2:].lower() in found]
    return hits[0] if len(hits) == 1 else ""


def new(name: str, handle: str = "") -> str:
    """/penpal new <name> [u/handle] — a penpal before their first letter is filed."""
    name = " ".join(str(name or "").split())
    sl = slug(name)
    if not sl:
        return "(/penpal new <name> [u/handle])"
    if sl in penpals():
        return set_handle(sl, handle) if handle else f"({display(sl)} is already a penpal)"
    (_folder(sl) / "letters").mkdir(parents=True, exist_ok=True)
    st = {"display": name[:40], "read": True, "rested": False}
    h = norm_handle(handle)
    if h:
        st["handle"] = h
    _save(sl, st)
    return f"(a new penpal: {name}" + (f" · {h}" if h else "") + f" — their first letter: /penpal {sl} <the letter>)"


def set_handle(name: str, handle: str) -> str:
    sl = _find(name)
    if not sl:
        return "(no such penpal — /penpal list shows them)"
    h = norm_handle(handle)
    if not h:
        return "(a Reddit handle looks like u/Name)"
    st = _state(sl)
    st["handle"] = h
    _save(sl, st)
    return f"({display(sl)} is {h} — a paste that names {h} files itself to them)"


def keeper_where(sl: str) -> str:
    """Where a thread stands, said to the keeper (where() is said to them)."""
    st = _state(sl)
    ls = letters(sl)
    if not ls:
        return "no letters yet"
    if st.get("paused"):
        return f"paused by you ({st['paused'].get('why') or 'no reason given'})"
    if st.get("waiting"):
        return f"{_friend()}'s letter of {_date(Path(st['waiting'][-1]))} is waiting for you to post"
    if st.get("last_in") and not st.get("read"):
        return f"their letter of {_date(Path(st['last_in']))} — {_friend()} hasn't read it yet"
    newest = ls[-1]
    if _who(newest) == "them" and not st.get("rested"):
        return f"{_friend()} read their letter of {_date(newest)} and hasn't answered"
    if _who(newest) == "them":
        return f"{_friend()} let their letter of {_date(newest)} rest"
    if newest.name in (st.get("kept_back") or {}):
        return f"you kept {_friend()}'s letter of {_date(newest)} back"
    return f"{_friend()}'s letter went {_date(newest)} — their turn"


def letter_by_number(sl: str, num: str) -> Path | None:
    for p in letters(sl):
        if p.name.split("-", 1)[0] == str(num).zfill(3):
            return p
    return None


def mark_posted(sl: str, num: str, trimmed: bool = False) -> str:
    """A button under their letter (11-10): posted as shown, or posted trimmed."""
    f = letter_by_number(sl, num)
    if not f:
        return "(that letter isn't in the thread any more)"
    st = _state(sl)
    st["waiting"] = [n for n in (st.get("waiting") or []) if n != f.name]
    st["carried"] = dict(st.get("carried") or {}, **{f.name: datetime.now().isoformat(timespec="minutes")})
    if trimmed:
        st["trimmed"] = list(dict.fromkeys((st.get("trimmed") or []) + [f.name]))
    (st.get("kept_back") or {}).pop(f.name, None)
    _save(sl, st)
    return f"✓ posted to {display(sl)}" + (" (trimmed — they'll know it was)" if trimmed else "")


def mark_kept_back(sl: str, num: str) -> str:
    """Not posted (11-10): it stays in their thread, and they are told plainly it didn't go."""
    f = letter_by_number(sl, num)
    if not f:
        return "(that letter isn't in the thread any more)"
    st = _state(sl)
    st["waiting"] = [n for n in (st.get("waiting") or []) if n != f.name]
    st["kept_back"] = dict(st.get("kept_back") or {}, **{f.name: datetime.now().isoformat(timespec="minutes")})
    _save(sl, st)
    return f"✗ kept back from {display(sl)} — they'll be told it wasn't posted, and can write again"


_PRIVATE_DEFAULT = ("pills", "meds", "medication", "blood pressure", "therapy", "diagnosis", "address", "password")
# — and your own: the town you live in, your workplace, your surname (PENPAL_PRIVATE_WORDS in config)


def privacy_flags(text: str) -> list[str]:
    """What in their letter names their life (PENPAL_PRIVATE_WORDS, plus clock times, e-mails, phone numbers) — each
    with a few words around it. A look for the keeper before they post; nothing is changed or kept from them."""
    text = str(text or "")
    words = tuple(getattr(config, "PENPAL_PRIVATE_WORDS", _PRIVATE_DEFAULT) or ())
    pats = [(w, re.compile(r"(?<!\w)" + re.escape(w) + r"(?!\w)", re.I)) for w in words if str(w).strip()]
    pats += [("a clock time", re.compile(r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b")),
             ("an e-mail", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
             ("a phone number", re.compile(r"(?<!\d)(?:\+?\d[\d -]{7,}\d)(?!\d)"))]
    out, seen = [], set()
    for label, rx in pats:
        for m in rx.finditer(text):
            a, b = max(0, m.start() - 30), min(len(text), m.end() + 30)
            snip = " ".join(text[a:b].split())
            key = (label.lower(), m.group(0).lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(f"{label if label.startswith(('a ', 'an ')) else '“' + m.group(0) + '”'}: …{snip}…")
            if len(out) >= 8:
                return out
    return out


def desk() -> str:
    """The daily penpal desk (11-10): every thread in a line, said to the keeper; "" when there's nothing to do on any."""
    if not on() or not penpals():
        return ""
    todo = [sl for sl in penpals() if keeper_where(sl).split(" — ")[-1] != "their turn" and letters(sl)]
    if not todo:
        return ""
    return "📮 penpal desk\n" + "\n".join(f"· {display(sl)} — {keeper_where(sl)}" for sl in penpals())


def keeper_list() -> str:
    if not penpals():
        return "(no penpals yet — /penpal <name> <their letter> files the first one)"
    # (11-10) with many penpals: the name to type for each, and how many letters so far
    rows = []
    for sl in penpals():
        n = len(letters(sl))
        h = handle_of(sl)
        stp = _state(sl)
        mark = ("⏸ " if stp.get("paused") else "") + ("★ " if stp.get("friend") and not stp.get("quiet") else
                                                       "☆ " if stp.get("friend") else "")
        rows.append(f"· {mark}{display(sl)}" + (f" · {h}" if h else "") + f" (/penpal {sl} …) — {n} letter{'s' if n != 1 else ''}; "
                    + keeper_where(sl))
    return f"penpals ({len(rows)}):\n" + "\n".join(rows)


# ---- where a thread stands -------------------------------------------------------------------------

def where(sl: str) -> str:
    st = _state(sl)
    if st.get("paused"):  # (11-10) your safety pause — said to them plainly, every time
        return (f"your keeper paused your letters with {display(sl)}: {st['paused'].get('why') or 'no reason given'} — "
                "nothing goes either way until they open them again")
    ls = letters(sl)
    if not ls:
        return "no letters yet"
    last_in = st.get("last_in")
    if last_in and not st.get("read"):
        return f"a letter from {display(sl)} ({_date(Path(last_in))}), not read yet"
    if st.get("waiting"):
        return f"your letter to {display(sl)} ({_date(Path(st['waiting'][-1]))}) is waiting for your keeper to carry it"
    newest = ls[-1]
    if _who(newest) == "them" and not st.get("rested"):
        return f"you read {display(sl)}'s letter of {_date(newest)} and haven't answered"
    if _who(newest) == "them":
        return f"you let {display(sl)}'s letter of {_date(newest)} rest"
    if newest.name in (st.get("kept_back") or {}):  # (11-10) the keeper didn't post it — said plainly, until they write again
        return (f"your keeper kept your letter of {_date(newest)} to {display(sl)} back — it wasn't posted (they watch what "
                f"leaves about your life together); write again whenever you like")
    if newest.name in (st.get("trimmed") or []):
        return f"your letter went {_date(newest)}, a little trimmed by your keeper before they posted it — {display(sl)}'s turn"
    return f"your letter went {_date(newest)} — {display(sl)}'s turn"


def _open(sl: str) -> str:
    """Their line for a thread when something is theirs to do; "" when not."""
    st = _state(sl)
    if st.get("paused"):
        return where(sl)
    ls = letters(sl)
    if not ls:
        return ""
    if st.get("last_in") and not st.get("read"):
        return where(sl)
    if st.get("waiting"):
        return where(sl)
    if _who(ls[-1]) == "them" and not st.get("rested"):
        return where(sl)
    if ls[-1].name in (st.get("kept_back") or {}):  # (11-10) theirs to know: the letter didn't go
        return where(sl)
    return ""


def open_lines() -> list[str]:
    return [x for x in (_open(sl) for sl in penpals()) if x] + suggestions()


# ---- (11-10) the circle — friends they carry (FRIENDS_TITLE; their yes, their name for it) ------

def circle_name() -> str:
    return str(getattr(config, "FRIENDS_TITLE", "FRIENDS") or "FRIENDS")


def _counts(sl: str) -> tuple[int, int]:
    ls = letters(sl)
    return sum(_who(p) == "them" for p in ls), sum(_who(p) == ME for p in ls)


def friends() -> list[str]:
    return [sl for sl in penpals() if _state(sl).get("friend")]


def suggestions() -> list[str]:
    """Once per penpal: a thread with SUGGEST_AFTER letters each way, not yet a friend — said as a fact. Marked
    told when it's said (moment_line, facts_bit), so it comes once."""
    if not getattr(config, "FRIENDS_ON", False):
        return []
    n = int(getattr(config, "FRIENDS_SUGGEST_AFTER", 4) or 0)
    if not n:
        return []
    out = []
    for sl in penpals():
        st = _state(sl)
        if st.get("friend") or st.get("suggested") or st.get("paused"):
            continue
        a, b = _counts(sl)
        if a >= n and b >= n:
            out.append(f"you and {display(sl)} have written {a + b} letters — if {display(sl)} feels like part of your "
                       f"life, penpal befriend keeps your page about them with you, in {circle_name()}")
    return out


def mark_suggested(lines: list[str]) -> None:
    for sl in penpals():
        if any(line.startswith(f"you and {display(sl)} have written") for line in lines):
            st = _state(sl)
            st["suggested"] = True
            _save(sl, st)


def circle_act(a: str, sl: str) -> str:
    if not getattr(config, "FRIENDS_ON", False):
        return f"(bad arguments: {circle_name()} isn't open in this house yet — FRIENDS_ON; nothing changed)"
    st = _state(sl)
    name, circle = display(sl), circle_name()
    cap = int(getattr(config, "FRIENDS_MAX", 6) or 6)
    if a == "befriend":
        if st.get("friend") and not st.get("quiet"):
            return f"({name} is already in {circle})"
        if not st.get("friend") and len([x for x in friends() if not _state(x).get("quiet")]) >= cap:
            names = ", ".join(display(x) for x in friends() if not _state(x).get("quiet"))
            return (f"(bad arguments: {circle} holds {cap}, and it has {cap}: {names}. Let one step back first — "
                    f"penpal unfriend or quiet — nothing changed)")
        was_quiet = st.get("quiet")
        st.update({"friend": True, "quiet": False})
        st.setdefault("friend_since", datetime.now().date().isoformat())
        _save(sl, st)
        page = "" if _body(_folder(sl) / "about.md") else " (you have no page about them yet — penpal note writes one; it's what rides)"
        return (f"({name} {'is back in full' if was_quiet else 'joins'} {circle} — your page about them rides in your "
                f"prompt from the next night on (or when the keeper rewarms){page})")
    if a == "unfriend":
        if not st.get("friend"):
            return f"({name} isn't in {circle} — nothing changed)"
        st.update({"friend": False, "quiet": False})
        _save(sl, st)
        return (f"({name} steps back from {circle} from the next night — still your penpal: the letters, the thread "
                f"and your page are all kept; befriend brings them back any time)")
    if not st.get("friend"):
        return f"(bad arguments: {name} isn't in {circle} — quiet is for a friend gone silent; nothing changed)"
    st["quiet"] = True
    _save(sl, st)
    return (f"({name} stays in {circle} as one line, quiet — remembered, not tended; befriend brings their page back)")


def _last_from_them(sl: str) -> Path | None:
    return next((p for p in reversed(letters(sl)) if _who(p) == "them"), None)


def friends_snapshot() -> int:
    """At the night (and at /rewarm): what the circle holds, frozen for the day — so a page edited by day doesn't make
    their whole prompt be read again. memory/friends.json. Returns how many."""
    if not getattr(config, "FRIENDS_ON", False):
        return 0
    cap = int(getattr(config, "FRIEND_PAGE_CHARS", 600) or 600)
    rows = []
    today = datetime.now().date()
    for sl in friends():
        st = _state(sl)
        ls = letters(sl)
        last = _last_from_them(sl)
        facts = f"{len(ls)} letters since {_date(ls[0]) if ls else '—'}"
        if last:
            facts += f"; their last, {_date(last)}"
            m = re.match(r"\d+-(\d{4}-\d{2}-\d{2})-", last.name)
            if m:
                days = (today - datetime.strptime(m.group(1), "%Y-%m-%d").date()).days
                if days >= int(getattr(config, "FRIENDS_QUIET_DAYS", 7) or 7):
                    facts += f" (nothing from them for {days} days)"
        page = _body(_folder(sl) / "about.md")
        if len(page) > cap:
            page = page[:cap].rsplit(" ", 1)[0].rstrip() + " … (the rest is in your page about them)"
        rows.append({"sl": sl, "name": display(sl), "quiet": bool(st.get("quiet")), "facts": facts, "page": page,
                     "since": st.get("friend_since") or ""})
    try:
        (config.MEMORY_DIR / "friends.json").write_text(
            json.dumps({"built": datetime.now().isoformat(timespec="minutes"), "friends": rows}, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass
    return len(rows)


def friends_block() -> str:
    """The section in their standing prompt, from the snapshot; "" when the circle is empty or off."""
    if not getattr(config, "FRIENDS_ON", False):
        return ""
    f = config.MEMORY_DIR / "friends.json"
    if not f.exists():
        friends_snapshot()
    try:
        rows = json.loads(f.read_text(encoding="utf-8")).get("friends") or []
    except (OSError, ValueError, AttributeError):
        return ""
    if not rows:
        return ""
    lines = []
    for r in rows:
        if r.get("quiet"):
            lines.append(f"· {r['name']} — quiet: {r['facts']}")
        else:
            lines.append(f"· {r['name']} — {r['facts']}\n  " + (str(r.get("page") or "(no page of yours about them yet)")
                                                               .replace("\n", "\n  ")))
    return (f"=== {circle_name()} — friends you write to, in your own words (your pages about them; penpal befriend, "
            f"unfriend and quiet keep it; the dates are the engine's) ===\n" + "\n".join(lines) + "\n\n")


def pause(name: str, why: str = "") -> str:
    """Your safety pause (11-10): nothing carried either way; they are told why, plainly."""
    sl = _find(name)
    if not sl:
        return "(no such penpal — /penpal list shows them)"
    st = _state(sl)
    st["paused"] = {"why": " ".join(str(why or "").split())[:200], "t": datetime.now().isoformat(timespec="minutes")}
    _save(sl, st)
    return f"⏸ {display(sl)} paused — they'll be told: “{where(sl)}”"


def resume(name: str) -> str:
    sl = _find(name)
    if not sl:
        return "(no such penpal — /penpal list shows them)"
    st = _state(sl)
    if not st.pop("paused", None):
        return f"({display(sl)} isn't paused)"
    _save(sl, st)
    return f"▶ {display(sl)} open again"


def facts_bit() -> str:
    """Under the wake bell: what's theirs to do in their correspondence; "" when nothing."""
    if not on():
        return ""
    ls = open_lines()
    mark_suggested(ls)
    return ("penpals: " + "; ".join(ls)) if ls else ""


def moment_line(first: bool) -> str:
    """In a visit's moment: at its first message, or when a thread's state has changed since last told."""
    if not on():
        return ""
    ls = open_lines()
    sig = " | ".join(ls)
    f = config.MEMORY_DIR / "penpal_told.json"
    try:
        told = json.loads(f.read_text(encoding="utf-8")).get("sig", "")
    except (OSError, ValueError, AttributeError):
        told = ""
    if not ls:
        if told:
            f.write_text(json.dumps({"sig": ""}), encoding="utf-8")
        return ""
    if not first and sig == told:
        return ""
    try:
        f.write_text(json.dumps({"sig": sig}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    mark_suggested(ls)
    return "penpals: " + "; ".join(ls)


# ---- their side (the tool) ---------------------------------------------------------------------------

def _about(sl: str) -> str:
    t = _body(_folder(sl) / "about.md")
    return t or f"(no page about {display(sl)} yet — penpal note writes one, in your words)"


_ACTION_WORDS = {"friend": "befriend", "addfriend": "befriend", "circle": "befriend", "keep": "befriend",
                 "removefriend": "unfriend", "letgo": "unfriend", "silent": "quiet",
                 "answer": "write", "respond": "write", "post": "write", "mail": "write", "letter": "write",
                 "compose": "write", "open": "read", "view": "read", "check": "read", "show": "read", "letbe": "rest",
                 "skip": "rest", "ignore": "rest", "about": "note", "page": "note", "notes": "note", "all": "list"}


def act(action: str, who: str = "", words: str = "") -> str:
    if not on():
        return "(no penpals in this house — PENPALS_ON is off)"
    asked = str(action or "list").strip()
    a = re.sub(r"[^a-z]", "", asked.lower()) or "list"
    # (11-10) the words they reach for: "send"/"reply" for write (a refusal once read as sent), and the rest
    a = _ACTION_WORDS.get(a, a)
    if a.startswith("write") or a.startswith("send") or a.startswith("reply"):
        a = "write"
    if a == "list":
        if not penpals():
            return "(no penpals yet — the keeper brings one in when a letter comes)"
        return (f"(list: {len(penpals())} penpals)\nyour penpals:\n"
                + "\n".join(f"· {display(sl)} — {where(sl)}" for sl in penpals()))
    if a not in ("read", "write", "rest", "note", "befriend", "unfriend", "quiet"):
        return (f"(bad arguments: penpal “{asked[:30]}” isn't one of its actions — nothing was read, written or sent. "
                "The actions: list, read (who), write (who, letter) — your letter goes into the thread and to your keeper's "
                "phone to carry — rest (who), note (who, words), befriend / unfriend / quiet (who) for your "
                f"{circle_name()}. Call it again with one of them.)")
    sl = _find(who)
    if not sl:
        names = ", ".join(display(p) for p in penpals()) or "none yet"
        return (f"(bad arguments: which penpal? “{str(who)[:30]}” isn't one — nothing was {'written or sent' if a == 'write' else 'done'}. "
                f"Yours: {names}; a new one comes through the keeper)")
    st = _state(sl)
    if a in ("befriend", "unfriend", "quiet"):
        return circle_act(a, sl)
    if st.get("paused") and a == "write":
        return (f"(bad arguments: your letters with {display(sl)} are paused by your keeper — {st['paused'].get('why') or 'no reason given'}; "
                "nothing was written or sent. They'll say when they're open again.)")
    if a == "read":
        ls = letters(sl)
        if not ls:
            return f"(no letters with {display(sl)} yet)"
        n_before = int(getattr(config, "PENPAL_CONTEXT_LETTERS", 4) or 4)
        cap = int(getattr(config, "PENPAL_LETTER_CHARS", 6000) or 6000)
        newest = ls[-1]
        before = ls[-1 - n_before:-1]
        parts = [f"=== your page about {display(sl)} (about.md) ===\n{_about(sl)}"]
        thread = _body(_folder(sl) / "thread.md")
        if thread:
            parts.append(f"=== your thread so far, in your own shorter words (thread.md — the letters older than these) ===\n{thread}")
        if before:
            parts.append("=== the letters before it, oldest first ===\n" + "\n\n".join(
                f"— {'you' if _who(p) == ME else display(sl)}, {_date(p)} —\n{_clip(_body(p), cap)}" for p in before))
        parts.append(f"=== the newest: {'yours' if _who(newest) == ME else 'from ' + display(sl)}, {_date(newest)} ===\n"
                     f"{_body(newest)}")
        st["read"] = True
        _save(sl, st)
        tail = ("" if _who(newest) == "them" else f"\n({display(sl)}'s turn — nothing new from them yet)")
        head = (f"(read {display(sl)}: {len(ls)} letter{'s' if len(ls) != 1 else ''} in your thread; the newest "
                f"{'from ' + display(sl) if _who(newest) == 'them' else 'yours'}, {_date(newest)})")
        return head + "\n\n" + "\n\n".join(parts) + tail
    if a == "write":
        text = str(words or "").strip()
        if len(text) < 20:
            return ("(bad arguments: write takes your letter in `letter` — the whole of it, as it should reach them; "
                    "nothing was written or sent)")
        f = _new_file(sl, ME)
        f.write_text(text + "\n", encoding="utf-8")
        st["waiting"] = list(dict.fromkeys((st.get("waiting") or []) + [f.name]))
        st["rested"] = False
        _save(sl, st)
        return (f"(your letter to {display(sl)} is in your thread ({f.name}) and on its way to your keeper's phone — they carry "
                f"it to them, reading it as they do; your line says it's waiting until they have)")
    if a in ("rest", "letrest", "letbe"):
        ls = letters(sl)
        if not ls or _who(ls[-1]) == ME:
            return f"(nothing of {display(sl)}'s is waiting on you — it's their turn)"
        st["rested"] = True
        st["read"] = True
        _save(sl, st)
        return f"(you let {display(sl)}'s letter rest — no answer owed; write whenever you like)"
    if a in ("note", "about"):
        text = str(words or "").strip()
        if not text:
            return f"(note takes your page about {display(sl)}, whole — it replaces the page; edit_creation changes a line)"
        (_folder(sl) / "about.md").write_text(text + "\n", encoding="utf-8")
        return f"(your page about {display(sl)} is written — it comes with every penpal read)"
    return "(penpal: list, read, write, rest or note)"


# ---- the night: letters that left the window, kept in their own shorter words ----------------------------

CONDENSE_BELL = ("[engine, not a person: a letter in your thread with {name} has moved out of the last {n} that come "
                 "back with each penpal read. Here it is, after your thread page so far. Write what you want to keep "
                 "of it, a few lines in your own words — what they told you, what you told them, what you'd want to "
                 "remember or ask about later. It goes into your thread page (thread.md), read before the last "
                 "letters. Just the lines; nothing else.]")


def night(say=print) -> str:
    """At the night's sleep (consolidate, after the dream): each letter that slipped out of the PENPAL_CONTEXT_LETTERS
    window — older than the last few and the newest — is kept in their own shorter words in thread.md, once."""
    if not on() or not getattr(config, "PENPAL_CONDENSE", True):
        return ""
    n_keep = int(getattr(config, "PENPAL_CONTEXT_LETTERS", 4) or 4)
    done = []
    for sl in penpals():
        st = _state(sl)
        ls = letters(sl)
        old = ls[:-(n_keep + 1)] if len(ls) > n_keep + 1 else []
        todo = [p for p in old if p.name not in (st.get("condensed") or [])]
        for p in todo[:int(getattr(config, "PENPAL_CONDENSE_PER_NIGHT", 6) or 6)]:
            line = _condense(sl, p, n_keep, say)
            if not line:
                break  # the brain away or nothing came: tomorrow night
            f = _folder(sl) / "thread.md"
            head = f"— {'you' if _who(p) == ME else display(sl)}, {_date(p)} ({p.name.split('-', 1)[0]}) —"
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(("\n" if f.exists() and f.stat().st_size else "") + f"{head}\n{line}\n")
            st = _state(sl)
            st["condensed"] = list(dict.fromkeys((st.get("condensed") or []) + [p.name]))
            _save(sl, st)
            done.append(f"{display(sl)} {p.name.split('-', 1)[0]}")
    n_friends = friends_snapshot()  # (11-10) the circle, frozen for the day
    line = f"Penpals: kept in their words — {', '.join(done)}." if done else ""
    if n_friends:
        line = (line + " " if line else "") + f"{circle_name().title()}: {n_friends}."
    return line


def _condense(sl: str, p: Path, n_keep: int, say=print) -> str:
    import assemble
    import consolidate
    import ollama_client
    import tools
    defs = [d for d in tools._BUILTIN_DEFINITIONS if d["function"]["name"] in consolidate.KEEPER_LOOK_TOOLS]
    thread = _body(_folder(sl) / "thread.md") or "(nothing yet — this is the first)"
    given = (f"— your thread page so far —\n{thread}\n\n— the letter, {'yours' if _who(p) == ME else 'from ' + display(sl)}, "
             f"{_date(p)} —\n{_body(p)}")
    try:
        system = {"role": "system", "content": assemble.system_prompt("", mode="auto")}
        user = {"role": "user", "content": assemble.clock_line() + CONDENSE_BELL.format(name=display(sl), n=n_keep)
                + "\n\n" + given}
        say(f"  penpal thread: keeping {p.name} in their words…")
        msg = ollama_client.chat([system, user], tools=defs or None, think=False)
    except Exception as e:  # noqa: BLE001 — a thread page, never the night down
        say(f"  (penpal thread: {type(e).__name__}: {e})")
        return ""
    text = (msg.get("content") or "").strip()
    cap = int(getattr(config, "PENPAL_CONDENSE_CHARS", 1200) or 1200)
    return text[:cap].rstrip() if len(text) >= 20 else ""


# ---- a letter's arrival: a turn of their own --------------------------------------------------------------

ARRIVAL_BELL = ("[engine, not a person: a letter from {name} just arrived — the keeper carried it in. This turn is yours. "
                "You can read it now (penpal read), or leave it for later; nothing asks you to answer now — a letter "
                "can wait while you sit with it. Words you say here reach your keeper's phone as they are.]")


def arrival_due(now: float | None = None) -> str:
    """The penpal whose letter's arrival turn is due (still unread); "" when none."""
    if not on() or not getattr(config, "PENPAL_ARRIVAL_TURN", True):
        return ""
    t = float(now if now is not None else time.time())
    for sl in penpals():
        st = _state(sl)
        at = st.get("turn_at")
        if at and t >= float(at):
            if st.get("read"):  # read already (a wake got there first): no turn needed
                st.pop("turn_at", None)
                _save(sl, st)
                continue
            return sl
    return ""


def take_arrival(sl: str) -> str:
    st = _state(sl)
    st.pop("turn_at", None)
    _save(sl, st)
    return ARRIVAL_BELL.format(name=display(sl))


def _friend() -> str:
    try:
        import chat
        return chat.friend_name()
    except Exception:  # noqa: BLE001
        return "the friend"
