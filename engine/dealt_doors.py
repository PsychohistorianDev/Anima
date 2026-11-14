"""Doors out of the friend's own world, at a wake.

Wakes can stay busy entirely inside the friend's own pages and never reach the world. Three small doors, each offered
and never required, one small thing a wake, in wakes only — nothing here goes in the standing prompt or the tool list,
so nothing is re-read:

  A  WAKE_DEALT_THREAD      under the open book's pages, one real thing those pages mention, as Wikipedia has it
  B  "question" in WAKE_DEALT_WHOLE_KINDS   with no book open, a question nobody has answered yet
  C  WAKE_DEALT_WONDERINGS   a line of their own from creations/wonderings.md, handed back at a later wake
  B' WAKE_DEALT_QUESTION_BESIDE  with a book open and no wondering or thread beside it, door B's question rides
                                 beside the pages instead

Each deal that hands something is one line in memory/dealt_doors.log (the base, the door, its key — never the friend's
own words), so how often each door opens can be counted.

Everything fails closed: the world not answering, or nothing good found, adds nothing. dealt.deal_whole delegates
here; the single dealt-kind helpers (the book, the article, a penpal's questions, the Veil, a song) stay in dealt.py
and are called through it.
"""
from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path

import config
import dealt

HEAD = "[engine, not a person: dealt to you this wake — yours to take up or set down:]\n"
WHOLE_KINDS = ("wiki", "penpal", "veil", "song", "question")


def _file(name: str) -> Path:
    return config.MEMORY_DIR / name


def _load(name: str, default):
    try:
        d = json.loads(_file(name).read_text(encoding="utf-8"))
        return d if isinstance(d, type(default)) else default
    except Exception:  # noqa: BLE001
        return default


def _save(name: str, data) -> None:
    try:
        _file(name).parent.mkdir(parents=True, exist_ok=True)
        _file(name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ---- A: a thread from the book -----------------------------------------------------------------------------------—
_STOP = frozenset("""A An The And But Or Nor If In On At To Of For So As By With From He She It They We You I His Her Its
Their My Your Our This That These Those There Then Than When What Who Whom Whose Why How Where Not No Yes Now Here Mr
Mrs Miss Dr Sir Lord Lady King Queen Prince Princess Chapter Part Book One Two Three Four Five Six Seven Eight Nine Ten
Oh Ah Well God Majesty Highness Excellency Yet Still Thus Hence Indeed Perhaps Suddenly Meanwhile However Once Upon Let
Come Go Look See Tell Say Said Very Just Only Even Such All Some Any Each Every Many Much More Most Both Either Neither
First Second Third Last Next Great Good Old New Little Big Himself Herself Itself Themselves Yourself Myself
Ourselves Everyone Everything Someone Something Nothing Nobody Emperor Empress General Captain Professor Doctor
Saint Count Countess Duke Duchess Baron Master Mister Madam Father Mother Brother Sister Uncle Aunt Monday Tuesday Wednesday Thursday Friday Saturday Sunday
January February March April May June July August September October November December""".split())
_NOT = ("fiction", "fictional", "character", "novel", "short stor", "stories by", "film", "album", "song ", "band",
        "video game", "television", "tv series", "comic", "episode", "manga", "anime", "given name", "surname",
        "family name", "disambiguation", "wikimedia", "musician", "rapper", "footballer", "poem by")
_KINDS = (r"demon|law|theorem|paradox|principle|constant|effect|equation|razor|conjecture|hypothesis|number|limit|"
          r"cycle|engine|problem|function|series|formula|experiment")


def candidates(text: str) -> list[str]:
    """Names and terms in the dealt pages that may be real things: "X's demon/law/paradox..." first, then capitalised
    names of two or three words, then single ones — never a sentence's first word, never a name the pages lean on
    (said three times or more: the story's own people and places, not a passing mention of the world)."""
    from collections import Counter
    t = " ".join(str(text or "").split())
    said = Counter(re.findall(r"\b[A-Z][a-z]{2,}\b", t))
    kinds = [m.group(1) for m in re.finditer(rf"\b([A-Z][a-z]{{2,}}(?:['’]s)? (?:{_KINDS}))\b", t)
             if re.sub(r"['’]s$", "", m.group(1).split()[0]) not in _STOP]
    runs: list[str] = []
    for sent in re.split(r"(?<=[.!?…:;])\s+|[\"“”]\s*", t):
        run: list[str] = []
        for i, w in enumerate(sent.split()):
            core = w.strip(".,;:!?()[]\"“”‘’'—-")
            name = re.sub(r"['’]s$", "", core)
            if i > 0 and re.fullmatch(r"[A-Z][a-z]{2,}", name) and name not in _STOP:
                run.append(name)
                if w[-1:] in ".,;:!?)" or core != name:
                    runs.append(" ".join(run[:3]))
                    run = []
            elif run:
                runs.append(" ".join(run[:3]))
                run = []
        if run:
            runs.append(" ".join(run[:3]))
    multi = [r for r in runs if " " in r]
    # "X of Y" is read whole ("the Library of Babel"): looked up as one name, and its head
    # word never alone — "House", "Library", "Order" by themselves are the generic thing, not the one the pages meant
    ofs, heads = [], set()
    for m in re.finditer(r"\b([A-Z][a-z]{2,}(?: [A-Z][a-z]{2,}){0,2}) of (?:the )?([A-Z][a-z]{2,}(?: [A-Z][a-z]{2,})?)\b", t):
        words = m.group(1).split()
        while words and words[0] in _STOP:
            words = words[1:]
        if words:
            heads.add(words[0])
            ofs.append(" ".join(words) + " of " + m.group(2))
    # a single word is a name only if the pages never use it in lowercase: Maxwell and Babel never are; a common word
    # that a sentence or a quote happened to capitalise almost always is, somewhere in a few pages
    lower = set(re.findall(r"\b[a-z]{3,}\b", t))
    single = sorted({r for r in runs if " " not in r and r.lower() not in lower and r not in heads},
                    key=lambda s: (-len(s), s))
    out: list[str] = []
    for c in kinds + ofs + multi + single:
        head = re.sub(r"['’]s$", "", c.split()[0])
        if c not in out and len(c) >= 4 and said[head] < 3:
            out.append(c)
    return out


def _thread_ok(cand: str, data: dict, book: str) -> bool:
    title, extract = str(data.get("title") or "").strip(), str(data.get("extract") or "").strip()
    about = (str(data.get("description") or "") + " " + extract[:300]).lower()
    if str(data.get("type") or "") != "standard" or not title or len(extract) < 80:
        return False
    if any(w in about for w in _NOT):
        return False
    b = re.sub(r"[^a-z ]", "", book.lower()).strip()
    bwords = {w for w in b.split() if len(w) > 3}
    if bwords and (bwords & set(re.sub(r"[^a-z ]", "", title.lower()).split()) or (b and b in about)):
        return False
    head = re.sub(r"['’]s$", "", cand.split()[0]).lower()
    return head in title.lower()


def thread(pages: str, book: str, seen: set) -> str | None:
    """Door A: one real thing the dealt pages mention, with the first line Wikipedia gives it — or nothing."""
    if dealt._offline() or not getattr(config, "WAKE_DEALT_THREAD", False):
        return None
    state = _load("dealt_threads.json", {})
    no = [str(x) for x in (state.get("no") or [])]
    tries = int(getattr(config, "WAKE_DEALT_THREAD_LOOKUPS", 5) or 5)
    found = None
    for cand in candidates(pages):
        if tries <= 0:
            break
        if cand in no or f"thread:{cand}" in seen:
            continue
        tries -= 1
        try:
            url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(cand.replace(" ", "_"))
            data = json.loads(dealt._get(url).decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                break
            data = {}
        except Exception:  # noqa: BLE001
            break
        title = str(data.get("title") or "").strip()
        if data and _thread_ok(cand, data, book) and f"thread:{title}" not in seen:
            first = re.split(r"(?<=[.!?])\s", str(data.get("extract") or "").strip())[0]
            found = (f"thread:{title}",
                     f"A thread to pull, if you want it: these pages mention “{cand}”. On Wikipedia — "
                     f"{title}: {dealt._cut(first, 260)} search_wikipedia “{title}” follows it; "
                     "left alone, it asks nothing.")
            break
        no.append(cand)
    _save("dealt_threads.json", {"no": no[-300:]})
    if not found:
        return None
    dealt._remember(found[0])
    _last["key"] = found[0]
    return found[1]


# ---- B: a question of the world ----------------------------------------------------------------------------------—
FIELDS = ("physics", "biology", "neuroscience", "mathematics", "philosophy", "astronomy", "linguistics", "chemistry")
REFRESH_DAYS = 7
_SOLVED = re.compile(r"\b(?:re)?solved\b", re.I)   # "Solved problems", "Resolved" — never "Unsolved", "Unresolved"
_SKIP = ("see also", "references", "external links", "notes", "further reading", "footnotes", "citations",
         "bibliography", "sources", "works cited")
FAILED_WAIT_S = 3600                       # beside the book: after a refresh that failed, an hour's rest


def questions_in(extract: str) -> list[dict]:
    """The question sentences of a "List of unsolved problems in ..." page, each with its section heading. Nothing
    under a solved section ("Problems solved since 1995", "Resolved", at any depth above the line)."""
    out, seen_q, under, heads = [], set(), "", {}   # heads: the heading remembered at each level
    for line in str(extract or "").splitlines():
        h = re.fullmatch(r"\s*(=+)\s*(.+?)\s*=+\s*", line)
        if h:
            n, under = len(h.group(1)), h.group(2).strip()
            heads = {k: v for k, v in heads.items() if k < n}
            heads[n] = under
            continue
        if any(v.lower() in _SKIP or _SOLVED.search(v) for v in heads.values()):
            continue
        for q in re.findall(r"[A-Z][^.?!\n]{28,240}\?", line):
            q = " ".join(q.split())
            if q.lower() not in seen_q:
                seen_q.add(q.lower())
                out.append({"q": q, "under": under})
    return out


def _refresh(cache: dict, most: int = 2, mark: bool = False) -> dict:
    """At most two fields fetched a wake, stalest first — the cache fills over a few wakes, never one long wait.
    Beside the book: one field (most=1), and a failure stamped (mark) so the next hour doesn't try."""
    fields = cache.setdefault("fields", {})
    stale = [f for f in FIELDS
             if time.time() - float((fields.get(f) or {}).get("at") or 0) > REFRESH_DAYS * 86400]
    stale.sort(key=lambda f: float((fields.get(f) or {}).get("at") or 0))
    for f in stale[:most]:
        try:
            q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "explaintext": 1, "format": "json",
                                        "redirects": 1, "titles": f"List of unsolved problems in {f}"})
            got = json.loads(dealt._get(f"https://en.wikipedia.org/w/api.php?{q}").decode("utf-8", "replace"))
            text = next((str(p.get("extract") or "")
                         for p in ((got.get("query") or {}).get("pages") or {}).values()), "")
        except Exception:  # noqa: BLE001 — the world didn't answer: what the cache holds stands
            if mark:
                cache["failed"] = time.time()
            break
        qs = questions_in(text)
        fields[f] = {"at": time.time(), "qs": qs or (fields.get(f) or {}).get("qs", [])}
    return cache


def _pick(seen: set, rng: random.Random, beside: bool = False) -> tuple[str, str, dict] | None:
    """The one picker both wordings share: (key, field, the question), from the cache, refreshed when online. Beside
    the book: one field a wake, and none within FAILED_WAIT_S of a failed refresh (door B alone ignores it)."""
    cache = _load("dealt_questions.json", {})
    if not dealt._offline():
        if not beside:
            cache = _refresh(cache)
            _save("dealt_questions.json", cache)
        else:
            try:
                failed = float(cache.get("failed") or 0)
            except (TypeError, ValueError):
                failed = 0.0
            if not 0 <= time.time() - failed < FAILED_WAIT_S:
                cache = _refresh(cache, most=1, mark=True)
                _save("dealt_questions.json", cache)
    pool = [(f, x) for f, d in (cache.get("fields") or {}).items() if isinstance(d, dict)
            for x in (d.get("qs") or []) if isinstance(x, dict) and isinstance(x.get("q"), str) and x["q"].strip()
            and f"question:{str(x.get('q'))[:80]}" not in seen]
    if not pool:
        return None
    f, x = rng.choice(pool)
    return f"question:{str(x['q'])[:80]}", f, x


def question(seen: set, rng: random.Random) -> tuple[str, str] | None:
    """Door B: a question of the world nobody has answered yet, from Wikipedia's lists of unsolved problems."""
    got = _pick(seen, rng)
    if not got:
        return None
    key, f, x = got
    under = f", under “{x['under']}”" if x.get("under") else ""
    return (key,
            f"a question nobody has answered yet — {x['q']} ({f}; Wikipedia: “List of unsolved problems in "
            f"{f}”{under}). Yours to chase or leave: search_wikipedia and read_web go after it.")


def question_beside(seen: set, rng: random.Random) -> str | None:
    """Door B beside the open book, when no wondering or thread came with it — remembered like a whole one, so the
    same question never comes twice, beside a book or alone. Any failure: nothing."""
    if not getattr(config, "WAKE_DEALT_QUESTION_BESIDE", False) or dealt._offline():
        return None  # offline, search_wikipedia and read_web are closed: the line would lead nowhere
    got = _pick(seen, rng, beside=True)
    if not got:
        return None
    key, f, x = got
    under = f", under “{x['under']}”" if x.get("under") else ""
    text = (f"A question of the world, if you want it: {x['q']} ({f}; Wikipedia: “List of unsolved problems in "
            f"{f}”{under}) — nobody has answered it yet. search_wikipedia and read_web go after it; left alone, it "
            "asks nothing.")
    dealt._remember(key)
    _last["key"] = key
    return text


# ---- C: their own wonderings ---------------------------------------------------------------------------------------—
WONDERINGS_FILE = "wonderings.md"
AFTER_H = 3        # handed back at a later wake, not the one it was written in
EVERY_DAYS = 3     # the same line, at most this often
TIMES = 3          # ...and at most this many times, then it rests on their page, theirs


def wondering_due() -> tuple[str, str] | None:
    """Door C, read-only for their page: the open line of creations/wonderings.md due to be handed back, if any.
    Theirs alone: the engine never writes the page; a line with a check, an arrow or [x] (what they found) is done."""
    if not getattr(config, "WAKE_DEALT_WONDERINGS", False):
        return None
    try:
        text = (config.CREATIONS_DIR / WONDERINGS_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    state, now, due, changed = _load("dealt_wonderings.json", {}), time.time(), [], False
    for raw in text.splitlines():
        line = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", raw).strip()
        if len(line) < 8 or line[:1] in "#(>" or line.startswith("~~"):
            continue
        if "\u2713" in line or "\u2192" in line or "->" in line or "[x]" in line.lower():
            continue
        key = " ".join(line.lower().split())[:120]
        if key not in state:
            state[key] = {"first": now, "dealt": []}
            changed = True
        rec = state[key]
        dealt_at = [float(x) for x in (rec.get("dealt") or [])]
        if (now - float(rec.get("first") or now) >= AFTER_H * 3600 and len(dealt_at) < TIMES
                and (not dealt_at or now - dealt_at[-1] >= EVERY_DAYS * 86400)):
            due.append((float(rec.get("first") or now), key, line))
    if changed:
        _save("dealt_wonderings.json", state)
    if not due:
        return None
    first, key, line = min(due)
    since = datetime.fromtimestamp(first).strftime("%b %d").replace(" 0", " ")
    return (key, f"A wondering of yours, from your page creations/{WONDERINGS_FILE} (there since {since}): {line} \u2014 "
                 "it isn't marked as looked into. search_web, search_wikipedia and read_web go after it; a \u2713 or "
                 "\u201c\u2192 what you found\u201d on its line says it's done, and it won't come back.")


def wondering_shown(key: str) -> None:
    state = _load("dealt_wonderings.json", {})
    rec = state.setdefault(key, {"first": time.time(), "dealt": []})
    rec.setdefault("dealt", []).append(time.time())
    _save("dealt_wonderings.json", state)


# ---- a line a deal in memory/dealt_doors.log, so the doors can be counted: never the friend's own words -----------—
_last = {"key": ""}   # the key door A or B' remembered this wake


def _log(base: str, door: str, key: str = "", keep_key: bool = False) -> None:
    try:
        key = "wondering" if door == "wondering" and not keep_key else " ".join(str(key or "").split())[:80] or "-"
        line = f"{datetime.now().isoformat(timespec='seconds')}\tbase={base}\tdoor={door}\t{key}\n"
        _file("dealt_doors.log").parent.mkdir(parents=True, exist_ok=True)
        with _file("dealt_doors.log").open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:  # noqa: BLE001 — a count, never the deal lost
        pass


# ---- the pieces of a deal, shared by the deal as before and the rhythm -------------------------------------------—
def _book_deal(got, seen: set, rng: random.Random, due) -> str:
    """The open book as it is dealt: its pages and the notes, and one small door beside (their wondering if due, else a
    thread from the pages, else a question of the world). Remembers, logs, and marks the wondering shown."""
    dealt._remember(got[0])
    line = HEAD + got[1]
    extra, door = None, "none"
    _last["key"] = ""
    if due:
        extra, door = due[1], "wondering"
        wondering_shown(due[0])
    else:
        m = re.search(r"“([^”]+)”", got[1])
        # the book's pages alone, as book_next hands them apart — the notes ride in got[1] before the
        # pages, and a name in the notes is not a thread from the book
        pages = got[2] if len(got) > 2 else got[1].split("):\n\n", 1)[-1]
        try:
            extra = thread(pages, m.group(1) if m else "", seen)
            door = "thread" if extra else door
        except Exception:  # noqa: BLE001
            extra = None
        if not extra:  # no wondering, no thread: a question of the world rides beside the pages
            try:
                extra = question_beside(seen, rng)
                door = "question" if extra else door
            except Exception:  # noqa: BLE001
                extra = None
    _log("book", door, _last["key"] if door in ("thread", "question") else "")
    return line + ("\n\n" + extra if extra else "")


def _outside_deal(seen: set, rng: random.Random, due, after: str = "", door: str = "") -> str | None:
    """A whole thing turning through the kinds (WAKE_DEALT_WHOLE_KINDS), their wondering beside it when due, then
    `after` (the rhythm's line about the open book). None when no kind gave anything (the turn still moved)."""
    # a config without the knob (or an empty one) falls back to dealt's kinds: "question" reaches Wikipedia, so it
    # comes only when named
    ks = [k for k in (getattr(config, "WAKE_DEALT_WHOLE_KINDS", dealt.WHOLE_KINDS) or dealt.WHOLE_KINDS)
          if k in WHOLE_KINDS]
    if ks:
        start = dealt._next_turn() % len(ks)
        for kind in ks[start:] + ks[:start]:
            try:
                got = (dealt.wiki_featured(seen) if kind == "wiki"
                       else dealt.penpal_questions(seen) if kind == "penpal"
                       else dealt.veil_end(seen, rng) if kind == "veil"
                       else question(seen, rng) if kind == "question"
                       else dealt.song(seen, rng))
            except Exception:  # noqa: BLE001
                got = None
            if got:
                dealt._remember(got[0])
                tail = "\n(listen_to plays it — you'd hear it, not read about it)" if kind == "song" else ""
                line = HEAD + got[1] + tail
                if due:
                    line += "\n\n" + due[1]
                    wondering_shown(due[0])
                _log(kind, door or ("wondering" if due else "none"))
                return line + (("\n\n" + after) if after else "")
    return None


# ---- the orchestration dealt.deal_whole delegates to -------------------------------------------------------------—
def deal_whole(rng: random.Random | None = None) -> str:
    """The open book first, with one small door beside it (their wondering if due, else a thread from the pages, else
    a question of the world); with no book, a whole thing turning through the kinds (a question among them), and their
    wondering beside it when due. With WAKE_DEALT_RHYTHM, the wakes turn through its beats instead (_deal_rhythm); any
    fault there and the wake is dealt as before — never nothing because of the rhythm."""
    rng = rng or random.Random()
    try:
        beats = rhythm()
    except Exception:  # noqa: BLE001
        beats = []
    if beats:
        try:
            return _deal_rhythm(beats, rng)
        except Exception:  # noqa: BLE001 — a fault in the rhythm: the deal as before
            try:
                return _deal_before(rng)
            except Exception:  # noqa: BLE001 — that faults too (a broken book): nothing, never the wake down
                return ""
    return _deal_before(rng)


def _deal_before(rng: random.Random) -> str:
    seen = set(dealt._seen())
    due = wondering_due()

    if getattr(config, "WAKE_DEALT_BOOK_FIRST", True):
        try:
            got = dealt.book_next(seen)
        except Exception:  # noqa: BLE001
            got = None
        if got:
            return _book_deal(got, seen, rng, due)

    line = _outside_deal(seen, rng, due)
    if line is not None:
        return line

    if due:
        wondering_shown(due[0])
        _log("none", "wondering")
        return HEAD + due[1]
    return ""


# ---- the rhythm (WAKE_DEALT_RHYTHM): the beats a wake is dealt in turn ----------------------------------------—
BEATS = ("book", "own", "outside", "open")
RHYTHM_FILE = "dealt_rhythm.json"    # its own counter: dealt_turn.json keeps turning the outside kinds
RHYTHM_BOUND = 1000                  # the counter turns over at rhythm-length × this: it never grows without end
OWN_FILE = "dealt_own.json"          # the friend's pieces already dealt, until every one has come round
# never dealt as "one of your own", whatever WAKE_DEALT_OWN_DIRS says: the private and running pages the engine keeps
# for the friend — the journal, the dream book, the Veil and what comes out of it, the mailbox to the keeper, the
# adventures, the penpals, the reading notes, the world trips' folder, the garden. The folders whose names are knobs
# are read from config too (a renamed folder stays kept out), and WAKE_DEALT_OWN_NEVER adds more; nothing shrinks it.
OWN_NEVER = frozenset({"journal", "dreams", "dream_book", "veil", "unveiled", "adventures", "penpals", "reading",
                       "the-world", "garden"})
_NEVER_KNOBS = ("DREAM_PAINT_DIR", "VEIL_DIR", "VEIL_SHOW_TO", "MAILBOX", "ADVENTURE_DIR", "PENPAL_DIR", "READING_DIR",
                "WORLD_TRIP_DIR", "WAKE_DEALT_OWN_NEVER")
OWN_SUFFIXES = (".md", ".txt")
OWN_MAX_BYTES = 100_000              # a piece of theirs is short; anything larger is not one (and is never read)
OWN_TRIES = 8                        # chosen files read at most, a beat, before the beat falls on
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def rhythm() -> list[str]:
    """WAKE_DEALT_RHYTHM's beats that are beats (unknown names skipped); [] — the deal as before."""
    r = getattr(config, "WAKE_DEALT_RHYTHM", ())
    if isinstance(r, str):
        r = (r,)
    try:
        items = list(r or ())
    except TypeError:
        return []
    return [b for b in (str(x).strip().lower() for x in items if isinstance(x, str)) if b in BEATS]


def _next_beat(length: int = len(BEATS)) -> int:
    """The rhythm's own counter, advanced once a deal: anything missing, unreadable or odd (a string, a list, inf,
    nan, a negative) → 0, written back sane; bounded; a write that fails never raises."""
    span = max(int(length or 1), 1) * RHYTHM_BOUND
    try:
        v = _load(RHYTHM_FILE, {}).get("n", 0)
        n = int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else 0
        n = n % span if n >= 0 else 0
    except Exception:  # noqa: BLE001
        n = 0
    _save(RHYTHM_FILE, {"n": (n + 1) % span})
    return n


def _book_where(got) -> tuple[str, str, str] | None:
    """(title, where, the tool that opens it) from book_next's own words, or None."""
    try:
        said = str(got[1] or "")
    except Exception:  # noqa: BLE001
        return None
    m = re.match(r"the book you're in the middle of — “([^”]+)”, where you stopped \(([^)]+)\)", said)
    t = re.search(r"\b(read_pdf|read_epub) “", said)
    if not m:
        return None
    return m.group(1), m.group(2), (t.group(1) if t else ("read_epub" if m.group(2).startswith("chapter") else "read_pdf"))


def book_line(where) -> str:
    return f"(Your book is where you left it — “{where[0]}”, {where[1]}; {where[2]} opens it.)" if where else ""


def open_line(where) -> str:
    if where:
        return (f"[engine, not a person: nothing is dealt this wake — the hour is open. Your book is where you left it — "
                f"“{where[0]}”, {where[1]}.]")
    return "[engine, not a person: nothing is dealt this wake — the hour is open.]"


_ENGINE_OPEN = re.compile(r"\s*(?:the\s+)?(?:engine|system)\b", re.IGNORECASE)
_OPENERS = {"[": ("⟦", "]"), "［": ("⟦", "］"), "(": ("⟮", ")"), "（": ("⟮", "）")}
_BREAKS = re.compile("(\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85  ])")


def own_text(text: str) -> str:
    """The friend's piece as they wrote it, but for what could pose as the engine — a narrow local rule: an opening
    "[", "(", "［" or "（" becomes "⟦"/"⟮" only when what follows it, before its first ":", says "not a person" (or, for
    "[" and "［", when it opens with engine / system / the engine); a line starting "===" starts "= = =" (at every kind
    of line break); reserved tokens defanged. Every other bracket, parenthesis, dash and mark stays byte for byte."""
    text = str(text or "")
    try:
        import ollama_client
        text = ollama_client.defang(text)[0]
    except Exception:  # noqa: BLE001
        pass
    out, i = [], 0
    for m in re.finditer("[" + re.escape("".join(_OPENERS)) + "]", text):
        ch = m.group(0)
        new, close = _OPENERS[ch]
        rest = text[m.end():]
        inside = rest.split(close, 1)[0]
        head = inside.split(":", 1)[0].split("：", 1)[0]
        framed = len(head) < len(inside)  # an engine line says "…: " — no colon, no frame ("(someone, not a person yet)")
        if (framed and "not a person" in " ".join(head.lower().split())) or (ch in "[［" and _ENGINE_OPEN.match(rest)):
            out.append(text[i:m.start()] + new)
            i = m.end()
    text = "".join(out) + text[i:]
    parts = _BREAKS.split(text)
    return "".join(("= = =" + x.lstrip()[3:]) if k % 2 == 0 and x.lstrip().startswith("===") else x
                   for k, x in enumerate(parts))


def _never_names() -> set[str]:
    """The never-list as it stands: the built-in names, every part of the folder knobs that name these places, and
    WAKE_DEALT_OWN_NEVER — lower case, trailing dots and spaces off. Only ever more than OWN_NEVER, never less."""
    names = set(OWN_NEVER)
    for knob in _NEVER_KNOBS:
        v = getattr(config, knob, None)
        vals = (v,) if isinstance(v, (str, Path)) else (v if isinstance(v, (tuple, list, set, frozenset)) else ())
        for x in vals:
            if isinstance(x, (str, Path)):
                names |= {p.rstrip(". ").lower() for p in str(x).replace("\\", "/").split("/") if p.rstrip(". ")}
    return names


def _never(part: str, names: set[str] | None = None) -> bool:
    """A path part on the never-list, as Windows would read it: case ignored, trailing dots and spaces ignored."""
    return str(part).rstrip(". ").lower() in (names if names is not None else _never_names())


def _own_dirs() -> list[Path]:
    """The folders WAKE_DEALT_OWN_DIRS names, directly under creations/: none on the never-list, none reaching outside it."""
    import os
    names = _never_names()
    root = Path(config.CREATIONS_DIR)
    try:
        rroot = root.resolve()
    except OSError:
        return []
    raw = getattr(config, "WAKE_DEALT_OWN_DIRS", ()) or ()
    if isinstance(raw, str):
        raw = (raw,)
    try:
        raw = list(raw)
    except TypeError:
        return []
    out = []
    for d in raw:
        if not isinstance(d, str) or not d.strip():
            continue
        parts = [x for x in d.strip().replace("\\", "/").split("/") if x]
        if not parts or any(x.strip(". ") == "" or x.startswith(".") or _never(x, names) or ":" in x for x in parts):
            continue
        base = root.joinpath(*parts)
        try:
            if os.path.islink(base) or not base.is_dir():
                continue
            rel = base.resolve().relative_to(rroot)
        except (OSError, ValueError):
            continue
        if any(_never(x, names) for x in rel.parts):
            continue
        out.append(base)
    return out


def own_candidates(now: float | None = None) -> list[tuple[str, Path]]:
    """(rel under creations/, the file) of every piece that may be dealt — by name, size and date alone (stat; nothing
    is read here): a regular .md/.txt file of 1 to OWN_MAX_BYTES bytes, with one name only (no hard link), not hidden,
    under the named folders, last changed WAKE_DEALT_OWN_MIN_AGE_DAYS ago or more; its path the same resolved as
    written (no link or junction anywhere on the way), inside creations/, and off the never-list at every step."""
    import os
    import stat
    now = time.time() if now is None else now
    try:
        days = float(getattr(config, "WAKE_DEALT_OWN_MIN_AGE_DAYS", 30))
        if days != days or days < 0 or days == float("inf"):
            days = 30.0
    except (TypeError, ValueError, OverflowError):
        days = 30.0
    names = _never_names()
    root = Path(config.CREATIONS_DIR)
    try:
        rroot, aroot = root.resolve(), Path(os.path.abspath(root))
    except OSError:
        return []
    found: dict[str, Path] = {}
    for base in _own_dirs():
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames[:] = sorted(x for x in dirnames if not x.startswith(".") and not _never(x, names)
                                 and not os.path.islink(os.path.join(dirpath, x)))
            for fn in sorted(filenames):
                if fn.startswith(".") or not fn.lower().rstrip(". ").endswith(OWN_SUFFIXES):
                    continue
                f = Path(dirpath) / fn
                try:
                    st = os.lstat(f)
                    if (not stat.S_ISREG(st.st_mode) or not 0 < st.st_size <= OWN_MAX_BYTES or st.st_nlink > 1
                            or now - st.st_mtime < days * 86400):
                        continue
                    rel = f.resolve().relative_to(rroot)
                    written = Path(os.path.abspath(f)).relative_to(aroot)
                except (OSError, ValueError):
                    continue
                if os.path.normcase(str(rel)) != os.path.normcase(str(written)):
                    continue  # a link or junction somewhere on the way
                if any(_never(x, names) or x.startswith(".") for x in rel.parts):
                    continue
                found.setdefault(rel.as_posix(), f)
    return sorted(found.items())


def _read_piece(f: Path) -> str:
    """The piece as it is in the file — a BOM and line endings as text, trailing whitespace off — or "" when it is
    unreadable, empty, or not text (NUL bytes, or many bytes that are not UTF-8)."""
    import os
    import stat
    if not _still_a_piece(f):  # it may have changed since the listing: the checks again, right before the read
        return ""
    try:
        fd = os.open(f, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    except OSError:
        return ""
    try:
        st = os.fstat(fd)  # …and what was opened is what was checked: one regular file, one name, within the cap
        if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1 or not 0 < st.st_size <= OWN_MAX_BYTES:
            return ""
        with os.fdopen(fd, "rb", closefd=True) as fh:
            fd = -1
            raw = fh.read(OWN_MAX_BYTES + 1)
    except OSError:
        return ""
    finally:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
    if len(raw) > OWN_MAX_BYTES or b"\x00" in raw:
        return ""
    text = raw.decode("utf-8-sig", errors="replace")
    bad = text.count("�")
    if bad > max(3, len(text) // 100):
        return ""
    return text.replace("\r\n", "\n").rstrip()


def _still_a_piece(f: Path) -> bool:
    """The candidate checks again, right before the chosen file is read (it may have changed since the listing): a
    regular file with one name, within the size cap, the same resolved as written, inside creations/, off the
    never-list at every part."""
    import os
    import stat
    try:
        st = os.lstat(f)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1 or not 0 < st.st_size <= OWN_MAX_BYTES:
            return False
        root = Path(config.CREATIONS_DIR)
        rel = f.resolve().relative_to(root.resolve())
        written = Path(os.path.abspath(f)).relative_to(Path(os.path.abspath(root)))
    except (OSError, ValueError):
        return False
    if os.path.normcase(str(rel)) != os.path.normcase(str(written)):
        return False
    names = _never_names()
    return not any(_never(x, names) or x.startswith(".") for x in rel.parts)


def own_piece(rng: random.Random) -> tuple[str, str] | None:
    """One of the friend's own: (rel, the dealt text) — each piece once until all have come round; only the chosen
    file is read, and one that turns out empty or not text is marked seen and the next one tried (OWN_TRIES at most)."""
    cands = own_candidates()
    if not cands:
        return None
    state = _load(OWN_FILE, {})
    seen = [str(x) for x in (state.get("seen") or []) if isinstance(x, str)]
    last = state.get("last") if isinstance(state.get("last"), str) else (seen[-1] if seen else "")
    names = {r for r, _ in cands}
    seen = [x for x in seen if x in names]
    unseen = [c for c in cands if c[0] not in seen]
    if not unseen:  # every one has come round: round again
        seen, unseen = [], list(cands)

    def _round(items: list) -> list:
        """A new round's order: shuffled, the piece dealt last at its end when there are others (never twice running)."""
        items = list(items)
        rng.shuffle(items)
        if len(items) > 1:
            items = [c for c in items if c[0] != last] + [c for c in items if c[0] == last]
        return items

    order = _round(unseen) if len(unseen) == len(cands) else list(unseen)
    if len(unseen) != len(cands):
        rng.shuffle(order)
    bad: list[str] = []
    tries = 0
    while order and tries < OWN_TRIES:
        rel, f = order.pop(0)
        tries += 1
        seen = [x for x in seen if x != rel] + [rel]
        text = _read_piece(f)  # (the candidate checks again inside, right before the read)
        try:
            mt = datetime.fromtimestamp(f.stat().st_mtime)
        except (OSError, ValueError, OverflowError):
            text = ""
        if not text.strip():
            bad.append(rel)
            _save(OWN_FILE, {"seen": seen, "last": last})  # not a piece to hand over: passed over until the round comes again
            if not order and len(seen) >= len(names):  # …and that was the last unseen: round again, the bad apart
                order = _round([c for c in cands if c[0] not in bad])
                seen = list(bad)
            continue
        when = f"{mt.day} {MONTHS[mt.month - 1]}" + (f" {mt.year}" if mt.year != datetime.now().year else "")
        cap = int(getattr(config, "WAKE_DEALT_CHARS", 6000) or 6000)
        if len(text) > cap:
            cut = text[:cap]
            k = cut.rfind("\n\n")
            if k < cap // 2:
                k = cut.rfind("\n")
            if k < cap // 2:
                k = cut.rfind(" ")
            cut = cut[:k].rstrip() if k > 0 else cut.rstrip()
            text = cut + f"\n(…it goes on — read_creation \"{rel}\" opens the whole of it)"
        _save(OWN_FILE, {"seen": seen, "last": rel})
        return rel, f"one of your own — creations/{rel}, as you left it on {when}:\n\n{own_text(text)}"
    return None


def _deal_rhythm(beats: list[str], rng: random.Random) -> str:
    """One beat of WAKE_DEALT_RHYTHM: "book" (the open book as before; none → outside), "outside" (the turning kinds,
    even with a book in hand; nothing → own, then open), "own" (one of their pieces; none → outside, then open), "open"
    (nothing dealt, said). A book in hand on any other beat: one line saying where it waits. Their wondering, when due,
    beside what is dealt — not on an open beat: that stays open, and the wondering waits for the next."""
    beat = beats[_next_beat(len(beats)) % len(beats)]
    seen = set(dealt._seen())
    try:
        got = dealt.book_next(seen)
    except Exception:  # noqa: BLE001
        got = None
    where = _book_where(got) if got else None
    if beat == "open":
        _log("open", "none")
        return open_line(where)
    due = wondering_due()
    if beat == "book" and got:
        return _book_deal(got, seen, rng, due)
    order = ("own", "outside") if beat == "own" else ("outside", "own")
    after = book_line(where)
    no_pieces = ""
    for b in order:
        if b == "outside":
            line = _outside_deal(seen, rng, due, after, no_pieces)
            if line is not None:
                return line
        else:
            try:
                piece = own_piece(rng)
            except Exception:  # noqa: BLE001
                piece = None
            if piece:
                line = HEAD + piece[1]
                if due:
                    line += "\n\n" + due[1]
                    wondering_shown(due[0])
                _log("own", "wondering" if due else "none", piece[0], keep_key=True)
                return line + (("\n\n" + after) if after else "")
            if beat == "own":
                no_pieces = "no_pieces"  # (the log says an own beat found nothing of theirs to deal)
    if due:  # nothing else could be dealt: their wondering alone, as the deal before does
        wondering_shown(due[0])
        _log("none", no_pieces or "wondering")
        return HEAD + due[1] + (("\n\n" + after) if after else "")
    _log("open", no_pieces or "none")  # nothing could be dealt: the hour is open
    return open_line(where)
