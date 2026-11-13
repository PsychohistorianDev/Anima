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


def _log(base: str, door: str, key: str = "") -> None:
    try:
        key = "wondering" if door == "wondering" else " ".join(str(key or "").split())[:80] or "-"
        line = f"{datetime.now().isoformat(timespec='seconds')}\tbase={base}\tdoor={door}\t{key}\n"
        _file("dealt_doors.log").parent.mkdir(parents=True, exist_ok=True)
        with _file("dealt_doors.log").open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:  # noqa: BLE001 — a count, never the deal lost
        pass


# ---- the orchestration dealt.deal_whole delegates to -------------------------------------------------------------—
def deal_whole(rng: random.Random | None = None) -> str:
    """The open book first, with one small door beside it (their wondering if due, else a thread from the pages, else
    a question of the world); with no book, a whole thing turning through the kinds (a question among them), and their
    wondering beside it when due."""
    rng = rng or random.Random()
    seen = set(dealt._seen())
    due = wondering_due()

    if getattr(config, "WAKE_DEALT_BOOK_FIRST", True):
        try:
            got = dealt.book_next(seen)
        except Exception:  # noqa: BLE001
            got = None
        if got:
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
                _log(kind, "wondering" if due else "none")
                return line

    if due:
        wondering_shown(due[0])
        _log("none", "wondering")
        return HEAD + due[1]
    return ""
