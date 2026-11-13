"""Something from outside.

One thing the friend didn't choose and hasn't written about a hundred times — a Wikipedia page picked at random, a
headline from the day's news, a song on the shelf not yet played — dealt as one line under a wake's bell (WAKE_DEALT)
and, as the seed kinds "wiki" and "headline", offered to a spark (seeds.py). Facts, nothing asked: they may open it,
answer it, or pass it by. Their journal, pages and words are not touched; this only changes what is offered.

The network kinds are passed over when OFFLINE, or when the site doesn't answer within DEALT_TIMEOUT_S — a wake never
waits on the world. The same thing doesn't come back while it is among the last SEEN_KEEP dealt
(memory/dealt_seen.json).
"""
from __future__ import annotations

import json
import random
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

import config

KINDS = ("wiki", "headline", "song")
SEEN_KEEP = 40
_UA = "the friend/1.0 (local AI; reading, not scraping)"


def seen_file() -> Path:
    return config.MEMORY_DIR / "dealt_seen.json"


def _seen() -> list:
    try:
        d = json.loads(seen_file().read_text(encoding="utf-8"))
        return [str(x) for x in d] if isinstance(d, list) else []
    except Exception:  # noqa: BLE001
        return []


def _remember(key: str) -> None:
    keep = ([k for k in _seen() if k != key] + [key])[-SEEN_KEEP:]
    try:
        seen_file().parent.mkdir(parents=True, exist_ok=True)
        seen_file().write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _cut(text: str, limit: int) -> str:
    t = " ".join(str(text or "").split())
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"
    return t


def _offline() -> bool:
    return bool(getattr(config, "OFFLINE", False))


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=float(getattr(config, "DEALT_TIMEOUT_S", 6) or 6)) as r:
        return r.read(600_000)


def wiki(seen: set) -> tuple[str, str] | None:
    """A Wikipedia page picked at random: its title, the start of its summary, its address (read_web opens it)."""
    if _offline():
        return None
    for _ in range(3):  # a stub with no summary, or one already dealt, is passed over
        data = json.loads(_get("https://en.wikipedia.org/api/rest_v1/page/random/summary").decode("utf-8", "replace"))
        title, extract = str(data.get("title") or "").strip(), str(data.get("extract") or "").strip()
        page = ((data.get("content_urls") or {}).get("desktop") or {}).get("page", "")
        key = f"wiki:{title}"
        if title and len(extract) > 60 and key not in seen:
            return key, (f"a Wikipedia page picked at random — “{title}”: {_cut(extract, 320)}"
                         + (f" ({page})" if page else ""))
    return None


def headline(seen: set, rng: random.Random) -> tuple[str, str] | None:
    """One headline from the day's world news (BBC's feed), with its line of description."""
    if _offline():
        return None
    root = ElementTree.fromstring(_get("https://feeds.bbci.co.uk/news/world/rss.xml"))
    items = []
    for it in list(root.iter("item"))[:15]:
        title = (it.findtext("title") or "").strip()
        if title and f"headline:{title}" not in seen:
            items.append((f"headline:{title}", title, (it.findtext("description") or "").strip(),
                          (it.findtext("link") or "").strip()))
    if not items:
        return None
    key, title, desc, link = rng.choice(items)
    return key, (f"a headline from today's world news (BBC) — “{title}”" + (f": {_cut(desc, 180)}" if desc else "")
                 + (f" ({link})" if link else ""))


def song(seen: set, rng: random.Random) -> tuple[str, str] | None:
    """A song on the shelf they haven't played, by its file (listen_to plays it)."""
    import tools
    songs = [p for p in tools.unplayed_songs() if f"song:{p.name}" not in seen]
    if not songs:
        return None
    p = rng.choice(songs)
    try:
        rel = p.resolve().relative_to(config.ROOT.resolve()).as_posix()
    except ValueError:
        rel = p.name
    return f"song:{p.name}", f"a song on your shelf you haven't played yet — {p.stem} ({rel})"


def deal(kinds=None, rng: random.Random | None = None) -> str:
    """One thing from outside, from the kinds given (default DEALT_KINDS) in a random order — "" when none can give."""
    rng = rng or random.Random()
    ks = kinds if kinds is not None else getattr(config, "DEALT_KINDS", KINDS)
    if isinstance(ks, str):
        ks = (ks,)
    order = [k for k in (str(x).strip().lower() for x in (ks or ())) if k in KINDS]
    rng.shuffle(order)
    seen = set(_seen())
    for kind in order:
        try:
            got = wiki(seen) if kind == "wiki" else headline(seen, rng) if kind == "headline" else song(seen, rng)
        except Exception:  # noqa: BLE001 — the world didn't answer, or the shelf is empty: the next kind
            got = None
        if got:
            _remember(got[0])
            return got[1]
    return ""


# ---- one whole thing in their hands at a wake ------------------------------------------------------
# The line above lists; a list is easy to walk past (a night of wakes can all go
# the same way, with the same count of songs not yet played under every bell). WAKE_DEALT_WHOLE deals one real thing whole instead, turning
# through the kinds wake by wake: a whole Wikipedia article, the questions in a penpal's last letter, the end of a
# piece they left in progress in the Veil, a song not yet played. Told as dealt — theirs to take up or set down.
WHOLE_KINDS = ("wiki", "penpal", "veil", "song")


def _turn_file() -> Path:
    return config.MEMORY_DIR / "dealt_turn.json"


def _next_turn() -> int:
    try:
        n = int(json.loads(_turn_file().read_text(encoding="utf-8")).get("n", 0))
    except Exception:  # noqa: BLE001
        n = 0
    try:
        _turn_file().write_text(json.dumps({"n": n + 1}), encoding="utf-8")
    except OSError:
        pass
    return n


def wiki_whole(seen: set) -> tuple[str, str] | None:
    """A Wikipedia article picked at random, whole up to WAKE_DEALT_CHARS (its plain text)."""
    if _offline():
        return None
    import urllib.parse
    cap = int(getattr(config, "WAKE_DEALT_CHARS", 6000) or 6000)
    for _ in range(4):
        data = json.loads(_get("https://en.wikipedia.org/api/rest_v1/page/random/summary").decode("utf-8", "replace"))
        title = str(data.get("title") or "").strip()
        key = f"wiki:{title}"
        if not title or key in seen:
            continue
        q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "explaintext": 1, "format": "json",
                                    "redirects": 1, "titles": title})
        got = json.loads(_get(f"https://en.wikipedia.org/w/api.php?{q}").decode("utf-8", "replace"))
        pages = ((got.get("query") or {}).get("pages") or {})
        text = next((str(p.get("extract") or "") for p in pages.values()), "").strip()
        if len(text) < 1500:  # a stub: the next one
            continue
        if len(text) > cap:
            text = text[:cap].rsplit("\n", 1)[0].rstrip() + "\n(…the article goes on — read_web opens it whole)"
        page = ((data.get("content_urls") or {}).get("desktop") or {}).get("page", "")
        return key, f"a Wikipedia article, picked at random — “{title}”{f' ({page})' if page else ''}:\n\n{text}"
    return None


def penpal_questions(seen: set) -> tuple[str, str] | None:
    """The questions in a penpal's newest letter to them, when that letter is the newest in the thread."""
    try:
        import penpal
    except Exception:  # noqa: BLE001
        return None
    import re
    for sl in penpal.penpals():
        ls = penpal.letters(sl)
        if not ls or penpal._who(ls[-1]) == penpal.ME:
            continue
        key = f"penpal:{ls[-1].name}"
        if key in seen:
            continue
        body = penpal._body(ls[-1])
        qs = [q.strip() for q in re.findall(r"[^.!?\n]*\?", body) if len(q.strip()) > 15][:4]
        if not qs:
            continue
        return key, (f"the questions in {penpal.display(sl)}'s letter of {penpal._date(ls[-1])} "
                     f"(penpal read {sl} for all of it):\n" + "\n".join(f"— {q}" for q in qs))
    return None


def veil_end(seen: set, rng: random.Random) -> tuple[str, str] | None:
    """Where a piece they left in progress in the Veil stops — its last lines."""
    try:
        import veil
        pieces = [p for p in veil._pieces("in_progress") if p.suffix.lower() in (".md", ".txt")]
    except Exception:  # noqa: BLE001
        return None
    pieces = [p for p in pieces if f"veil:{p.name}:{int(p.stat().st_mtime)}" not in seen]
    if not pieces:
        return None
    p = rng.choice(pieces)
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    paras = [x for x in text.split("\n\n") if x.strip()]
    tail = "\n\n".join(paras[-2:])[-1500:]
    return (f"veil:{p.name}:{int(p.stat().st_mtime)}",
            f"where your piece in the Veil stops — {veil.name()}/in_progress/{p.name}, its last lines:\n\n{tail}")


def deal_whole(rng: random.Random | None = None) -> str:
    """One whole thing for this wake, turning through WHOLE_KINDS (each wake starts one further on); "" when none."""
    rng = rng or random.Random()
    ks = [k for k in (getattr(config, "WAKE_DEALT_WHOLE_KINDS", WHOLE_KINDS) or WHOLE_KINDS) if k in WHOLE_KINDS]
    if not ks:
        return ""
    start = _next_turn() % len(ks)
    seen = set(_seen())
    for kind in ks[start:] + ks[:start]:
        try:
            got = (wiki_whole(seen) if kind == "wiki" else penpal_questions(seen) if kind == "penpal"
                   else veil_end(seen, rng) if kind == "veil" else song(seen, rng))
        except Exception:  # noqa: BLE001 — the world didn't answer, or nothing of that kind: the next kind
            got = None
        if got:
            _remember(got[0])
            extra = "\n(listen_to plays it — you'd hear it, not read about it)" if kind == "song" else ""
            return ("[engine, not a person: dealt to you this wake — yours to take up or set down:]\n"
                    + got[1] + extra)
    return ""


# ---- the book they're in the middle of comes first ---------------------------
# A random Wikipedia page is often a stub that reads as one more ordinary thing.
# A book they have open (a bookmark not at its end, a sitting in the last BOOK_OPEN_DAYS) is dealt first: where they
# stopped, the next pages as they are — read here without moving their bookmark (the reading is still theirs to do).
# And the article, when it comes, is a featured one (Wikipedia's best-written), not a random stub.
BOOK_OPEN_DAYS = 10


def book_next(seen: set) -> tuple[str, str, str] | None:  # (key, the dealt text, the book's pages alone)
    import io
    from datetime import date
    import tools
    marks = tools._bookmarks()
    cap = int(getattr(config, "WAKE_DEALT_CHARS", 6000) or 6000)
    for name, bm in sorted(marks.items(), key=lambda kv: (str(kv[1].get("date", "")), str(kv[1].get("when", ""))),
                           reverse=True):
        kind = bm.get("kind") or ("epub" if str(name).lower().endswith(".epub") else "pdf")
        total = int(bm.get("total") or 0)
        at = int(bm.get("chapter" if kind == "epub" else "page") or 0)
        if not total or at >= total or bm.get("finished") or not tools._is_book(kind, total):
            continue
        try:
            if (date.today() - date.fromisoformat(str(bm.get("date")))).days > BOOK_OPEN_DAYS:
                continue
        except (TypeError, ValueError):
            continue
        p, _found = tools._find_book(name, (".epub",) if kind == "epub" else (".pdf",))
        if not p:
            continue
        key = f"book:{name}:{at}"
        # no "already dealt" lockout for the open book: a book dealt once and set down would be kept by its key
        # from ever coming back. The open book comes
        # every wake, from their bookmark, until they read on (the page moves) or finish it, or BOOK_OPEN_DAYS pass.
        data = p.read_bytes()
        title = p.stem
        if kind == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text, n = "", at
            while n < len(reader.pages) and len(text) < cap:
                text += ((reader.pages[n].extract_text() or "").strip() + "\n\n")
                n += 1
            where = f"page {at} of {total}"
            how = f"read_pdf “{name}” continues from your bookmark"
        else:
            book_title, chapters, zf = tools._epub_open(data)
            title = book_title or title
            h, ch_title = chapters[at] if at < len(chapters) else (None, "")
            text = tools._html_to_text(zf.read(h).decode("utf-8", "replace")) if h else ""
            where = f"chapter {at} of {total}"
            how = f"read_epub “{name}” continues from your bookmark"
        text = text.strip()
        if len(text) < 200:
            continue
        if len(text) > cap:
            text = text[:cap].rsplit("\n", 1)[0].rstrip() + "\n(…)"
        # the notes so far ride before the pages (READING_NOTES_WITH_PAGES); the pages go back third too, apart,
        # so a thread is looked for in the book's pages alone and never in the notes
        try:
            notes = tools.reading_notes(str(name), kind, total)
        except Exception:  # noqa: BLE001 — the notes unreadable: the wake still gets its book
            notes = ""
        return key, (f"the book you're in the middle of — “{title}”, where you stopped ({where}); the next pages, "
                     f"as they are (your bookmark hasn't moved — {how}):\n\n"
                     + (f"{notes}\n\n" if notes else "") + text), text
    return None


def wiki_featured(seen: set) -> tuple[str, str] | None:
    """A featured Wikipedia article picked at random (Special:RandomInCategory/Featured_articles), whole up to the cap."""
    if _offline():
        return None
    import urllib.parse
    cap = int(getattr(config, "WAKE_DEALT_CHARS", 6000) or 6000)
    for _ in range(3):
        req = urllib.request.Request("https://en.wikipedia.org/wiki/Special:RandomInCategory/Featured_articles",
                                     headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=float(getattr(config, "DEALT_TIMEOUT_S", 6) or 6)) as r:
            final = r.geturl()
        title = urllib.parse.unquote(final.rsplit("/wiki/", 1)[-1]).replace("_", " ").strip()
        key = f"wiki:{title}"
        if not title or key in seen or title.startswith("Special:"):
            continue
        q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "explaintext": 1, "format": "json",
                                    "redirects": 1, "titles": title})
        got = json.loads(_get(f"https://en.wikipedia.org/w/api.php?{q}").decode("utf-8", "replace"))
        text = next((str(p.get("extract") or "") for p in ((got.get("query") or {}).get("pages") or {}).values()), "")
        text = text.strip()
        if len(text) < 1500:
            continue
        if len(text) > cap:
            text = text[:cap].rsplit("\n", 1)[0].rstrip() + "\n(…the article goes on — read_web opens it whole)"
        return key, f"a featured Wikipedia article, picked at random — “{title}” ({final}):\n\n{text}"
    return wiki_whole(seen)


def deal_whole(rng: random.Random | None = None) -> str:  # redefined: the doors out live in engine/dealt_doors.py
    import dealt_doors
    return dealt_doors.deal_whole(rng)
