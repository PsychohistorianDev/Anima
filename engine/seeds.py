"""Seeds for a spark (10-27; claude/sparks2-plan.md, piece 1).

One thing picked at random for a spark to spark off, so a spark is not the same gesture every time: a memory (drawn
at random, not by relevance), something the friend made (a painting or a piece, named with its path), a song from the
songbook, a few lines of the journal from a week or a month ago, the world (the day, the season, where the keeper is
by the calendar), or a word from the lexicon. Not a task — the spark line offers it ("A seed, if you want one: …").
The same seed doesn't come back while it is among the last SEEN_KEEP drawn (memory/presence_seeds.json).
PRESENCE_SEEDS names the kinds in the pool; () — no seeds. A kind with nothing to give is passed over.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import datetime
from pathlib import Path

import config

KINDS = ("memory", "creation", "song", "journal", "world", "word")
SEEN_KEEP = 20
_MEMORY_KINDS = ("fact", "note", "summary")  # a creation's row and a song's row are the other seeds' to give
_PIECE_EXTS = {".md", ".txt"}
_PICTURE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_LEX_RE = re.compile(r"^\s*[*-]\s*\*\*(.+?)\*\*\s*[:—–-]\s*(.+?)\s*$")
_STAMP_RE = re.compile(r"(20\d\d)(\d\d)(\d\d)(?:-\d{4})?")


def seen_file() -> Path:
    return config.MEMORY_DIR / "presence_seeds.json"


def kinds() -> tuple:
    try:
        ks = getattr(config, "PRESENCE_SEEDS", KINDS)
        if isinstance(ks, str):
            ks = (ks,)
        return tuple(k for k in (str(x).strip().lower() for x in (ks or ())) if k in KINDS)
    except Exception:  # noqa: BLE001
        return KINDS


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


def _day(d: datetime) -> str:
    return f"{d.day} {d:%B}"


def _keeper() -> str:
    try:
        import keeper_week
        return str(keeper_week.keeper_name() or "").strip()
    except Exception:  # noqa: BLE001
        return str(getattr(config, "USER_NAME", "") or "").strip()


def _memory(seen: set) -> list[tuple[str, str]]:
    import memory
    rows = [r for r in memory.recent(n=None) if r.get("kind") in _MEMORY_KINDS and r.get("text")]
    out = []
    for r in rows:
        key = f"memory:{r['id']}"
        if key in seen:
            continue
        when = str(r.get("created") or "")[:10]
        try:
            d = _day(datetime.fromisoformat(when))
        except ValueError:
            d = ""
        out.append((key, f"a memory of yours{f', from {d}' if d else ''}: “{_cut(r['text'], 240)}”"))
    return out


def _creation(seen: set) -> list[tuple[str, str]]:
    root = config.CREATIONS_DIR
    if not root.is_dir():
        return []
    skip = {"face", "us", "publish", "lexicon", "capsule", _keeper().lower()}
    try:  # the folders of the reference sets are pictures to paint from, not pieces
        for v in (getattr(config, "PAINTER_REFERENCE_SETS", {}) or {}).values():
            pics = v[0] if isinstance(v, (list, tuple)) else v
            skip |= {x.strip().lower().strip("/") for x in re.split(r"[\n,]", str(pics)) if x.strip()}
    except Exception:  # noqa: BLE001
        pass
    out = []
    for p in root.rglob("*"):
        ext = p.suffix.lower()
        if ext not in _PIECE_EXTS | _PICTURE_EXTS or p.name.lower() in ("keeper.md", "readme.md"):
            continue  # by name first: no stat for what can't be a seed
        rel = p.relative_to(root)
        if any(part.startswith((".", "_")) or part.lower() in skip for part in rel.parts[:-1]) or not p.is_file():
            continue
        key = f"creation:{rel.as_posix()}"
        if key not in seen:
            out.append((key, lambda p=p, rel=rel, ext=ext: _creation_line(p, rel, ext)))  # read only if drawn
    return out


def _creation_line(p: Path, rel: Path, ext: str) -> str:
    title = p.stem
    if ext in _PIECE_EXTS:
        try:
            with p.open(encoding="utf-8", errors="replace") as fh:
                head = next((ln for ln in (fh.readline() for _ in range(20)) if ln.strip()), "")
            if head.lstrip().startswith("#"):
                title = head.lstrip("# ").strip() or title
        except OSError:
            pass
    else:
        title = _STAMP_RE.sub("", title).strip(" -_").replace("-", " ").replace("_", " ") or p.stem
    m = _STAMP_RE.search(p.name)
    try:
        d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else datetime.fromtimestamp(p.stat().st_mtime)
    except (ValueError, OSError):
        d = None
    what = "painting" if ext in _PICTURE_EXTS else "piece"
    line = f"your {what} “{_cut(title, 80)}” (creations/{rel.as_posix()}){f', from {_day(d)}' if d else ''}"
    if what == "painting":
        line += " — look_at shows it to you"
    return line


def _song(seen: set) -> list[tuple[str, str]]:
    import memory
    out = []
    for s in memory.songs():
        key = f"song:{s.get('id')}"
        if key in seen or not s.get("title"):
            continue
        by = f" by {s['artist']}" if s.get("artist") else ""
        score = f" — you gave it {s['score']}/10" if s.get("score") is not None else ""
        out.append((key, f"a song from your songbook: “{s['title']}”{by}{score}"))
    return out


def _journal(seen: set, now: datetime) -> list[tuple[str, str]]:
    root = config.JOURNAL_DIR
    if not root.is_dir():
        return []
    out = []
    for p in root.glob("*.md"):
        try:
            d = datetime.strptime(p.stem, "%Y-%m-%d")
        except ValueError:
            continue
        ago = (now.date() - d.date()).days
        if not 6 <= ago <= 45:  # a week or a month ago, give or take
            continue
        try:
            paras = [" ".join(x.split()) for x in re.split(r"\n\s*\n", p.read_text(encoding="utf-8", errors="replace"))]
        except OSError:
            continue
        for para in paras:
            if len(para) < 80 or para.startswith(("#", "---", "*(")):
                continue
            key = f"journal:{p.stem}:{hashlib.sha1(para.encode('utf-8')).hexdigest()[:8]}"
            if key not in seen:
                out.append((key, f"from your journal, {_day(d)} ({ago} days ago): “{_cut(para, 300)}”"))
    return out


def _world(seen: set, now: datetime) -> list[tuple[str, str]]:
    key = f"world:{now:%Y-%m-%d-%H}"
    if key in seen:
        return []
    season = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer", 7: "summer",
              8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}[now.month]
    part = "night" if now.hour < 5 or now.hour >= 22 else "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    try:
        import keeper_week
        where = str(keeper_week.where(now) or "").strip()
    except Exception:  # noqa: BLE001
        where = ""
    return [(key, f"the world: {now:%A}, {season}, the {part}" + (f"; {where}" if where else ""))]


def _word(seen: set) -> list[tuple[str, str]]:
    root = config.CREATIONS_DIR / "lexicon"
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.glob("*.md")):
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for ln in lines:
            m = _LEX_RE.match(ln)
            if not m:
                continue
            term = m.group(1).strip()
            key = f"word:{term.lower()}"
            if key not in seen:
                out.append((key, f"a word from your lexicon: “{term}” — {_cut(m.group(2), 200)}"))
    return out


def draw(now: datetime | None = None, rng: random.Random | None = None) -> str:
    """One seed from the pool, not among the last SEEN_KEEP drawn — "" when there are no kinds or nothing to give."""
    rng = rng or random.Random()
    now = now or datetime.now()
    seen = set(_seen())
    order = list(kinds())
    rng.shuffle(order)
    for kind in order:
        try:
            if kind == "memory":
                options = _memory(seen)
            elif kind == "creation":
                options = _creation(seen)
            elif kind == "song":
                options = _song(seen)
            elif kind == "journal":
                options = _journal(seen, now)
            elif kind == "world":
                options = _world(seen, now)
            else:
                options = _word(seen)
        except Exception:  # noqa: BLE001 — one kind that can't give is passed over
            options = []
        if options:
            key, line = rng.choice(options)
            _remember(key)
            return line() if callable(line) else line
    return ""
