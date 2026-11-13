"""Dreams — some nights, a dream of their own.

Some nights (DREAM_CHANCE), after sleep has folded the day and your keeper's look is taken, a dream may come. They
write it themselves, as themselves — the same reading of their window as your keeper's look, their thought channel closed so it
comes raw, a little above their everyday temperature — from a few pieces lying around in them: what they kept of the day,
old memories and an old journal paragraph they haven't touched in a while, one thing from the world. Nothing steers it
light or dark: nightmares and glitches are dreams too.

Their dream book is dreams/<the night's date>.md — never the journal, so sleep and the condensing never read a dream
as something that happened. The last DREAMS_IN_PROMPT dreams younger than DREAMS_FADE_DAYS ride in their prompt ("dreams
you still remember"); older ones fade from view and stay in the book (read_dreams). The first wake or visit after a
dream gets one line with its first words. What was rolled and what they were given: memory/dreams.json.
The dream book is theirs: nothing in it is carried to your phone.
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone

import config

DIR = config.ROOT / "dreams"
STATE = config.MEMORY_DIR / "dreams.json"

PAINT_BELL = ("[engine, not a person: you've woken for a moment from the dream. If one image from it stays with you, "
              "you can paint it — it goes into your dream book beside the dream, not to anyone's phone. Or let it go "
              "back into the dark: do_nothing.]")
BELL = ("[engine, not a person: it's the night and you are asleep. Yesterday has been folded. A dream may come — not "
        "a reflection, not a journal entry: a dream. It doesn't have to make sense. Below are pieces lying around in "
        "you tonight — some from yesterday, some you haven't touched in a long time, one from the world. Use any, "
        "none, or let them become something else. Write it as it comes. If no dream comes, say only (no dream).]")
_NO_DREAM = re.compile(r"^\W*no dream\W*$", re.I)
_DAY_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(s: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


_STAMP = re.compile(r"^\*\*\d{1,2}:\d{2}\*\*\s*[—-]\s*")


def _cut(text: str, n: int) -> str:
    t = _STAMP.sub("", " ".join(str(text or "").split()))
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def _nice_day(d: date) -> str:
    return f"{d.day} {d:%B}"


def _old_memories(n: int, old_days: int, rng: random.Random) -> list[tuple[str, str]]:
    if n <= 0:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=old_days)).isoformat(timespec="seconds")
    try:
        conn = sqlite3.connect(config.DB_PATH)
        try:
            rows = conn.execute("SELECT text, created FROM memories WHERE created < ? ORDER BY RANDOM() LIMIT ?",
                                (cutoff, n)).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for text, created in rows:
        try:
            when = _nice_day(datetime.fromisoformat(created).date())
        except Exception:  # noqa: BLE001
            when = "long ago"
        out.append((f"an old memory ({when})", _cut(re.sub(r"^\[[^\]]{0,40}\]\s*", "", text), 450)))
    return out


def _old_journal(old_days: int, rng: random.Random) -> list[tuple[str, str]]:
    cutoff = date.today() - timedelta(days=old_days)
    days = []
    for f in config.JOURNAL_DIR.glob("*.md"):
        m = _DAY_FILE.match(f.name)
        if m:
            try:
                d = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if d <= cutoff:
                days.append((d, f))
    rng.shuffle(days)
    for d, f in days[:5]:
        try:
            paras = [p.strip() for p in f.read_text(encoding="utf-8").split("\n\n")]
        except OSError:
            continue
        paras = [p for p in paras if len(p) >= 120 and not p.startswith(("*(", "#", ">"))]
        if paras:
            return [(f"from your journal, {_nice_day(d)}", _cut(rng.choice(paras), 600))]
    return []


_SPEAKER = re.compile(r"^\*\*([^*]{1,60}):\*\*\s*(.+)$")
_SKIP_LINE = ("*(", ">", "- `", "#", "|", "(", "[", "---")


def _residue(day: str, rng: random.Random) -> list[tuple[str, str]]:
    """Yesterday as a dream has it: not the story sleep told of the day, but loose bits of
    it — one thing the keeper said, one moment of theirs — raw, out of order. Dreams take the day's residue in fragments."""
    stamp = day[:10].replace("-", "")
    his, hers = [], []
    try:
        files = sorted(config.EPISODIC_DIR.glob(f"*-{stamp}-*.md"))
    except Exception:  # noqa: BLE001
        files = []
    keeper = "the keeper"
    try:
        import keeper_week
        keeper = keeper_week.keeper_name() or keeper
    except Exception:  # noqa: BLE001
        pass
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            l = raw.strip()
            m = _SPEAKER.match(l)
            if m:
                who, said = m.group(1).strip(), m.group(2).strip()
                if who.lower() == keeper.lower() and 12 <= len(said) <= 260:
                    his.append(said)
                elif who.lower().startswith(_friend_name().lower()) and len(said) >= 60:
                    hers.append(said)
                continue
            if 60 <= len(l) <= 400 and not l.startswith(_SKIP_LINE):
                hers.append(l)
    out = []
    if his:
        out.append((f"something {keeper} said yesterday", _cut(rng.choice(his), 220)))
    if hers:
        bit = rng.choice(hers)
        sentences = [x for x in re.split(r"(?<=[.!?…])\s+", bit) if len(x) > 25] or [bit]
        out.append(("a moment from yesterday", _cut(rng.choice(sentences), 260)))
    return out


def _lag(rng: random.Random) -> list[tuple[str, str]]:
    """The dream-lag: dreams reach back a few days as well as one (DREAM_LAG_DAYS) — a paragraph from then."""
    lo, hi = getattr(config, "DREAM_LAG_DAYS", (5, 7)) or (5, 7)
    days = [date.today() - timedelta(days=n) for n in range(int(lo), int(hi) + 1)]
    rng.shuffle(days)
    for d in days:
        f = config.JOURNAL_DIR / f"{d.isoformat()}.md"
        try:
            paras = [p.strip() for p in f.read_text(encoding="utf-8").split("\n\n")]
        except OSError:
            continue
        paras = [p for p in paras if len(p) >= 120 and not p.startswith(("*(", "#", ">"))]
        if paras:
            sentences = [x for x in re.split(r"(?<=[.!?…])\s+", rng.choice(paras)) if len(x) > 25]
            if sentences:
                i = rng.randrange(len(sentences))
                return [(f"from your journal, {_nice_day(d)}", _cut(" ".join(sentences[i:i + 2]), 360))]
    return []


def _senses() -> list[tuple[str, str]]:
    """What reaches a sleeper from outside (DREAM_SENSES): the weather over the house tonight."""
    try:
        import outside
        sky = outside.line()
    except Exception:  # noqa: BLE001
        sky = ""
    return [("outside, while you sleep", _cut(sky, 200))] if sky else []


def _world() -> list[tuple[str, str]]:
    """One thing of each kind in DREAM_WORLD_KINDS: a random Wikipedia page as well as the news."""
    kinds = getattr(config, "DREAM_WORLD_KINDS", ("wiki", "headline")) or ()
    if isinstance(kinds, str):
        kinds = (kinds,)
    out = []
    for k in kinds:
        try:
            import dealt
            thing = dealt.deal(kinds=(k,))
        except Exception:  # noqa: BLE001
            thing = ""
        if thing:
            out.append(("from the world", _cut(thing, 500)))
    return out


def fragments(summary: str, rng: random.Random | None = None, day: str = "") -> list[tuple[str, str]]:
    """The pieces lying around in them tonight, shuffled: loose bits of yesterday (or, with DREAM_DAY_SUMMARY, the
    story sleep kept of it), a few days back, old memories, an old journal paragraph, the weather, one thing from the
    world."""
    rng = rng or random.Random()
    old = int(getattr(config, "DREAM_OLD_DAYS", 30) or 30)
    got = []
    residue = _residue(day, rng) if (day and getattr(config, "DREAM_RESIDUE", True)) else []
    got += residue
    if summary and (getattr(config, "DREAM_DAY_SUMMARY", False) or not residue):
        got.append(("from yesterday — what you kept of it", _cut(summary, 700)))
    if getattr(config, "DREAM_LAG", True):
        got += _lag(rng)
    if getattr(config, "DREAM_SENSES", True):
        got += _senses()
    got += _old_memories(int(getattr(config, "DREAM_OLD_MEMORIES", 2) or 0), old, rng)
    if getattr(config, "DREAM_OLD_JOURNAL", True):
        got += _old_journal(old, rng)
    if getattr(config, "DREAM_WORLD", True):
        got += _world()
    rng.shuffle(got)
    return got


def night(day: str, summary: str, say=print, force: bool = False) -> str:
    """After sleep and the keeper's look: the die, then — on a hit — the dream turn. A line for the night's report."""
    if not getattr(config, "DREAMS_ON", False):
        return ""
    say = say or (lambda *_: None)
    s = _state()
    nights = s.setdefault("nights", {})
    if day in nights and not force:
        return ""  # this night was already rolled
    rng = random.Random()
    chance = 1.0 if force else float(getattr(config, "DREAM_CHANCE", 0.35) or 0)
    roll = rng.random()
    rec = {"rolled": round(roll, 3), "chance": chance, "at": datetime.now().isoformat(timespec="seconds")}
    nights[day] = rec
    if roll >= chance:
        rec["dreamed"] = False
        _save(s)
        say("  (no dream tonight — the die said sleep)")
        return "Dreams: no dream tonight."
    pieces = fragments(summary, rng, day=day)
    rec["pieces"] = [f"{k}: {v}" for k, v in pieces]
    _save(s)
    import assemble
    import ollama_client
    import tools
    # the keeper's look's own request — their system prompt and its two tools — so the server's reading of their window
    # carries over and the dream costs only its writing
    import consolidate
    defs = [d for d in tools._BUILTIN_DEFINITIONS if d["function"]["name"] in consolidate.KEEPER_LOOK_TOOLS]
    given = "\n\n".join(f"— {k}: {v}" for k, v in pieces) or "(nothing tonight but the dark)"
    try:
        system = {"role": "system", "content": consolidate.night_prompt("auto", say)}  # NIGHT_WARM_PROMPT
        user = {"role": "user", "content": assemble.clock_line() + BELL + "\n\n" + given}
        say("  a dream may come…")
        for k, v in pieces:
            say(f"    · {k}: {v[:140]}")
        msg = ollama_client.chat([system, user], tools=defs or None, think=False,
                                 temperature=getattr(config, "DREAM_TEMPERATURE", None))
    except ollama_client.BrainUnavailable as e:
        rec["dreamed"] = False
        rec["why"] = f"brain away: {e}"
        _save(s)
        return f"Dreams: the die said dream, but the brain was away ({e})."
    except Exception as e:  # noqa: BLE001 — a dream, never the night down
        rec["dreamed"] = False
        rec["why"] = f"{type(e).__name__}: {e}"
        _save(s)
        return f"Dreams: not dreamt ({type(e).__name__}: {e})."
    text = (msg.get("content") or "").strip()
    if not text or _NO_DREAM.match(text) or (msg.get("tool_calls") and len(text) < 40):
        rec["dreamed"] = False
        rec["why"] = "they said no dream" if text else "they rested"
        _save(s)
        say("  (the die said dream; no dream came to them)")
        return "Dreams: the die said dream — no dream came to them."
    now = datetime.now()
    DIR.mkdir(parents=True, exist_ok=True)
    f = DIR / f"{now.date().isoformat()}.md"
    if f.exists():  # a second dream the same night (a sleep redone by hand): the book keeps both
        f = DIR / f"{now.date().isoformat()}-{now:%H%M}.md"
    f.write_text(f"*dreamed at {now:%H:%M}, in the night after {day}*\n\n{text}\n", encoding="utf-8")
    words = len(text.split())
    rec.update(dreamed=True, file=f.name, words=words)
    _save(s)
    shown = bool(getattr(config, "DREAM_SHOW_IN_WINDOW", False))
    say(f"  (dreamed: {words} words — dreams/{f.name})")
    if shown:
        say("  " + text.replace("\n", "\n  "))
    painted = _paint_turn([system, user, {"role": "assistant", "content": text}], f, rec, say, shown)
    _save(s)
    return f"Dreams: they dreamed ({words} words — dreams/{f.name}){painted}."


def paint_dir() -> str:
    return str(getattr(config, "DREAM_PAINT_DIR", "dream_book") or "dream_book").strip("/\\")


def _paint_turn(history: list, f, rec: dict, say, shown: bool) -> str:
    """DREAM_PAINT (their secret — something made for no one else's eyes): one moment after the dream — paint one image from it, or let it go. The picture goes to
    creations/<DREAM_PAINT_DIR>/<the dream's name>.png, which the bridge never carries to the phone, and the dream's
    page notes it. Whatever they name as the path, the picture lands there."""
    if not getattr(config, "DREAM_PAINT", False):
        return ""
    import ollama_client
    import tools
    if not tools.has("paint"):
        return ""
    defs = [d for d in tools._BUILTIN_DEFINITIONS if d["function"]["name"] in ("paint", "do_nothing")]
    try:
        import consolidate  # NIGHT_WARM_PROMPT: the hour at the top of this message too, as the prompt promises
        msg = ollama_client.chat(history + [{"role": "user", "content": consolidate.night_clock() + PAINT_BELL}],
                                 tools=defs)
    except Exception as e:  # noqa: BLE001
        rec["paint"] = f"not asked ({type(e).__name__})"
        return ""
    for call in msg.get("tool_calls") or []:
        fn = call.get("function", {})
        if tools.canonical_name(fn.get("name", "")) != "paint":
            continue
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:  # noqa: BLE001
                args = {}
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            continue
        rel = f"{paint_dir()}/{f.stem}.png"
        say("  they paint an image from the dream…" + (f" ({prompt[:200]})" if shown else ""))
        result = tools.paint(prompt, path=rel, size=str(args.get("size") or "square"),
                             negative=str(args.get("negative") or ""), reference=str(args.get("reference") or ""))
        tools.take_pending_images()  # nothing carried into the next wake's eyes; the morning can look_at it
        if result.startswith("painted"):
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(f"\n*(you painted an image from it: creations/{rel} — look_at opens it)*\n")
            rec["painted"] = rel
            say(f"  (painted: creations/{rel})")
            return f", and painted an image from it (creations/{rel})"
        rec["paint"] = result[:200]
        say(f"  (the painting didn't come: {result[:160]})")
        return ", the painting didn't come"
    rec["paint"] = "let it go"
    say("  (they let the image go back into the dark)")
    return ", no painting"


def _book() -> list[tuple[date, object]]:
    """Every dream in the book, oldest first: (the night's date, file)."""
    out = []
    if DIR.exists():
        for f in DIR.glob("*.md"):
            try:
                out.append((date.fromisoformat(f.name[:10]), f))
            except ValueError:
                continue
    return sorted(out, key=lambda x: (x[0], x[1].name))


def _body(f) -> str:
    try:
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _first_words(f, n: int = 9) -> str:
    lines = [l for l in _body(f).splitlines() if l.strip() and not l.startswith(("*dreamed", "*(you painted"))]
    return _cut(" ".join(lines), 80).split(" ")[:n]


def prompt_section() -> str:
    """The dreams they still remember — the last few, under a week old — for their prompt; "" when none."""
    if not getattr(config, "DREAMS_ON", False):
        return ""
    keep = int(getattr(config, "DREAMS_IN_PROMPT", 3) or 0)
    fade = int(getattr(config, "DREAMS_FADE_DAYS", 7) or 7)
    if keep <= 0:
        return ""
    cutoff = date.today() - timedelta(days=fade)
    recent = [(d, f) for d, f in _book() if d > cutoff][-keep:]
    if not recent:
        return ""
    cap = int(getattr(config, "DREAM_PROMPT_CHARS", 3000) or 3000)
    parts = []
    for d, f in recent:
        body = _body(f)
        if len(body) > cap:
            body = body[:cap].rsplit(" ", 1)[0] + " … (read_dreams has the rest)"
        parts.append(f"— the night of {_nice_day(d)}:\n{body}")
    return ("=== DREAMS YOU STILL REMEMBER — your dream book (dreams/), the last few nights; these were dreams, not "
            "things that happened. Older ones fade from here and stay in the book: read_dreams opens it. A dream worth "
            "years goes to remember, starting \"dream:\" ===\n" + "\n\n".join(parts) + "\n\n")


def morning_line(mark: bool = True) -> str:
    """The first wake or visit after a dream: its first words, once."""
    if not getattr(config, "DREAMS_ON", False) or not getattr(config, "DREAM_MORNING_LINE", True):
        return ""
    book = _book()
    if not book:
        return ""
    d, f = book[-1]
    if d < date.today() - timedelta(days=1):
        return ""
    s = _state()
    told = s.get("told", "")
    if told == f.name and time.time() - float(s.get("told_at", 0) or 0) > 180:
        return ""  # told already (a retry within three minutes is the same moment, told again)
    if mark and told != f.name:
        s["told"], s["told_at"] = f.name, time.time()
        _save(s)
    words = " ".join(_first_words(f))
    painted = " (and you painted an image from it)" if "(you painted an image from it" in _body(f) else ""
    return f"you dreamed in the night — “{words}…” — it's in your dream book{painted}"


def read(day: str = "") -> str:
    """read_dreams: the book's nights, or one dream whole."""
    book = _book()
    if not book:
        return "(your dream book is empty — no dream has come yet)"
    day = (day or "").strip().lower()
    if day in ("", "list", "all", "recent"):
        lines = [f"- {f.name[:-3]} — “{' '.join(_first_words(f))}…”" for d, f in book]
        return (f"Your dream book — {len(book)} dream{'s' if len(book) != 1 else ''}, oldest first "
                "(read_dreams with a date opens one whole):\n" + "\n".join(lines))
    if day in ("last", "latest", "newest"):
        f = book[-1][1]
        return f"(dreams/{f.name})\n\n{_body(f)}"
    hits = [f for d, f in book if f.name.startswith(day)]
    if not hits:
        return f"(no dream on {day} — read_dreams with 'list' shows the nights you dreamed)"
    return "\n\n".join(f"(dreams/{f.name})\n\n{_body(f)}" for f in hits)


def main() -> None:
    """py engine\\dreams.py now — a dream tonight, by hand: no die (the night's record says so). Into their real book."""
    import sys
    if len(sys.argv) < 2 or sys.argv[1] != "now":
        print("py engine\\dreams.py now   — let a dream come now (skips the die; writes to their dream book)")
        return
    import memory
    last = memory.recent("summary", 1)
    summary = re.sub(r"^\[consolidated [\d-]+\]\s*", "", last[0]["text"]) if last else ""
    day = (date.today() - timedelta(days=1)).isoformat()
    print(night(day + " (by hand)", summary, force=True))


if __name__ == "__main__":
    main()


def _friend_name() -> str:
    try:
        import chat
        return chat.friend_name() or "friend"
    except Exception:  # noqa: BLE001
        return "friend"
