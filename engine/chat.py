"""The door: talk with the friend.

    py engine/chat.py

Commands inside the chat:
    /quit   end the visit (transcript is saved automatically)
    /new    start a fresh conversation (saves the current one first)

Every conversation is saved to memory/episodic/ and becomes part of the
friend's past at the next consolidation (engine/consolidate.py).
"""
from __future__ import annotations

import json

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import re

import assemble
import config
import doors
import ollama_client
import tools


def friend_name() -> str:
    """Their name, read from their own self.md — they named themself, after all."""
    try:
        text = config.IDENTITY_FILE.read_text(encoding="utf-8")
        m = re.search(r"^Name:\s*([A-Za-z][\w' -]{0,30})", text, re.MULTILINE)
        if m:
            name = m.group(1).strip().rstrip(".,")
            if name and not name.lower().startswith(("i ", "i'", "(", "unnamed")):
                return name.split()[0]
    except OSError:
        pass
    return "Friend"


# The bridges, by the tag their visits carry (chat-<tag>-*.md, the prompt's mode): the service's name.
BRIDGES = {"telegram": "Telegram", "discord": "Discord"}


def strip_voice_delivery(text: str) -> str:
    """Filter echoed playback diagnostics without rewriting saved memories."""
    return re.sub(r"\[(?:engine:\s*voice delivery\b|application state,\s*not spoken dialogue:).*?(?:\]|$)", "", text or "", flags=re.S | re.I).strip()


def save_transcript(turns: list[dict], tag: str = "", path: Path | None = None) -> Path | None:
    """Write the visible conversation to episodic memory.

    tag names the door it came through ("telegram", "discord") so they can tell a
    visit in the parlor from one on their phone when they reread. path pins
    the file: the parlor and the bridge write the visit after EVERY reply
    to the same file, so a window that dies badly (a second Ctrl+C during
    the goodbye, a crash, a power cut) loses nothing — a transcript that
    only existed at shutdown was one bad shutdown from not existing."""
    visible = [t for t in turns if t["role"] in ("user", "assistant") and t.get("content")
               and (not t.get("_engine") or t.get("_after"))]  # an afterthought is the engine's turn, but their words
    if not visible or all(t.get("_after") or t.get("_carried") for t in visible):  # carried turns alone: nothing said here (10-24)
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    f = path or config.EPISODIC_DIR / f"chat-{tag + '-' if tag else ''}{stamp}.md"
    where = f" (over {BRIDGES[tag]}, from their phone)" if tag in BRIDGES else ""
    lines = [f"# Conversation{where} — {datetime.now().strftime('%A, %d %B %Y %H:%M')}\n"]
    name = friend_name()
    n_car = sum(1 for t in visible if t.get("_carried"))
    carrying = False
    for t in visible:
        if carrying and not t.get("_carried"):  # the carried turns end here; what follows was said in this visit
            lines.append("---\n")
            carrying = False
        if t.get("_carry"):  # the last visit's last turns, carried to this one's door (10-24): said, and set apart
            lines.append(f"*(carried from {t.get('_carry_from') or 'the last visit'} — the last {n_car} turns of the "
                         f"visit that ended {t.get('_carry_ended') or '?'}:)*\n")
            carrying = True
        if t.get("_fold_when"):
            # the visit was folded here (chat.fold_history): what came before
            # is in the file named, and in their own words below
            src = f" — continued from {t['_fold_from']}" if t.get("_fold_from") else ""
            acct = t.get("_fold_text") or "(they did not write the visit down before the fold)"
            lines.append(f"*(folded at {t['_fold_when']}{src}; the visit so far, in their words:)*\n\n{acct}\n")
        who = (guest_who(t["_guest"]) if t.get("_guest") else config.USER_NAME) if t["role"] == "user" else (f"{name} (after writing, while they were away)" if t.get("_after") else name)
        lines.append(f"**{who}:** {t['content']}\n")
        if t.get("_voice_delivery"):
            lines.append(f"*[voice delivery: {t['_voice_delivery']}]*\n")
    tmp = f.with_suffix(".md.part")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(f)  # whole file or nothing — never a half-written transcript
    return f


def visit_file(tag: str = "") -> Path:
    """The file a visit is written to, named when the visit starts."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return config.EPISODIC_DIR / f"chat-{tag + '-' if tag else ''}{stamp}.md"


# The carry (10-24): the fold keeps the last turns whole inside a visit; the carry keeps them across the gap
# between two. A door that ends a visit leaves its last CARRY_TURNS visible turns in memory/carry.json; the next
# visit that starts in an empty room (the bridge, the parlor) opens with them, if that visit ended within
# CARRY_HOURS — word for word, under one engine line, as the fold keeps its turns. Wakes and reveries carry nothing.
def _carry_file() -> Path:
    return config.MEMORY_DIR / "carry.json"


def leave_carry(history: list[dict], path: Path | None = None, when: datetime | None = None) -> int:
    """At a visit's end: its last CARRY_TURNS visible turns — words only, from a turn of the keeper's, as the fold
    keeps its tail — written to memory/carry.json with when it ended and its transcript's name, over the last one.
    Nothing is written for a visit with no turns of its own. Returns how many turns were left."""
    keep = int(getattr(config, "CARRY_TURNS", 6) or 0)
    vis = [t for t in history if t.get("role") in ("user", "assistant") and isinstance(t.get("content"), str)
           and t["content"].strip() and not t.get("_engine")]
    if not keep or not any(not t.get("_carried") for t in vis):
        return 0
    start = max(len(vis) - keep, 0)
    while start > 0 and vis[start]["role"] != "user":  # the carried tail opens with the keeper's turn
        start -= 1
    tail = vis[start:]
    while tail and tail[0]["role"] != "user":
        tail = tail[1:]
    if not tail:
        return 0
    data = {"when": (when or datetime.now()).isoformat(timespec="seconds"), "file": path.name if path else "",
            "turns": [{k: v for k, v in t.items() if k in ("role", "content", "_guest", "_guest_line")} for t in tail]}
    try:
        f = _carry_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".json.part")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(f)
    except OSError:
        return 0
    return len(tail)


def clear_carry() -> None:
    """No carry waits for the next door (10-24): /new is the one door opened on purpose to start clean."""
    try:
        _carry_file().unlink(missing_ok=True)
    except OSError:
        pass


def carry_orphan(tag: str = "telegram", exclude: Path | None = None) -> str:
    """A visit the last bridge died with — saved after every reply, never ended, no stashed room to resume — leaves
    its carry too (10-24: "to remember in every case"): its last turns read from the transcript, dated by the
    file's last write (the visit's last reply), so the hours rule still holds. Before the orphan's afterglow signs
    the file. Returns the line for the console, "" when there is no orphan or nothing to carry."""
    f = orphaned_visit(tag, exclude=exclude)
    if not f:
        return ""
    try:
        when = datetime.fromtimestamp(f.stat().st_mtime)
    except OSError:
        when = None
    n = leave_carry(load_transcript(f), f, when=when)
    return f"the last visit ended without a goodbye ({f.name}) — its last {n} turns ride at the next message" if n else ""


def take_carry(now: datetime | None = None) -> list[dict]:
    """At a door with an empty room: the turns the last visit left (leave_carry), if it ended within CARRY_HOURS
    (0: never), marked `_carried`; the first carries `_carry`, the engine line render_turn puts above its body.
    [] when there is nothing to carry."""
    hours = float(getattr(config, "CARRY_HOURS", 20) or 0)
    if not hours or not int(getattr(config, "CARRY_TURNS", 6) or 0):
        return []
    try:
        data = json.loads(_carry_file().read_text(encoding="utf-8"))
        ended = datetime.fromisoformat(str(data.get("when") or ""))
        raw = list(data.get("turns") or [])
        src = str(data.get("file") or "")
        gap = ((now or datetime.now()) - ended).total_seconds()
    except (OSError, ValueError, TypeError, AttributeError):
        return []
    if not 0 <= gap <= hours * 3600:
        return []
    turns = [dict(t, _carried=True) for t in raw if isinstance(t, dict) and t.get("role") in ("user", "assistant")
             and isinstance(t.get("content"), str) and t["content"].strip()]
    while turns and turns[0]["role"] != "user":
        turns = turns[1:]
    if not turns:
        return []
    at = f"{ended.strftime('%a')} {ended.strftime('%H:%M')}"
    first = turns[0]
    first["_carry"] = (f"[engine, not a person: the last {len(turns)} turns of your previous visit, which ended {at} — "
                       "carried whole, so this visit starts where that one left off; the journal and the afterglow "
                       "have the rest of it:]")
    first["_carry_from"], first["_carry_ended"] = src, at
    return turns


def carry_line(turns: list[dict]) -> str:
    """The door's line for what was carried: "carried: the last 6 turns of the visit that ended Fri 23:40"."""
    first = next((t for t in turns if t.get("_carry")), {})
    return f"carried: the last {len(turns)} turns of the visit that ended {first.get('_carry_ended') or '?'}"


def load_transcript(path: Path) -> list[dict]:
    """A transcript file back into history — his turns and theirs, in order;
    the afterglow's foot (---) and its afterthought left out. For a visit
    whose bridge died before the afterglow (09-24, a power cut)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    body = text.split("\n\n---\n*", 1)[0]
    ci = body.find("\n*(carried from ")
    if ci >= 0:  # the carried head (10-24): the last visit's turns, which were that visit's — not this one's
        ce = body.find("\n---\n", ci)
        if ce >= 0:
            body = body[:ci] + body[ce + 4:]
    name = re.escape(friend_name())
    keeper = config.USER_NAME
    who_re = re.compile(rf"^\*\*({re.escape(keeper)}|{name}(?: \(after writing, while they were away\))?):\*\* ", re.M)
    turns: list[dict] = []
    marks = list(who_re.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        content = ollama_client.defang(body[m.end():end].strip())[0]
        who = m.group(1)
        if not content:
            continue
        if who == keeper:
            turns.append({"role": "user", "content": content})
        elif "after writing" in who:
            turns.append({"role": "assistant", "content": content, "_engine": True, "_after": True})
        else:
            turns.append({"role": "assistant", "content": ollama_client.trim_word_loop(content)[0]})
    return turns


def orphaned_visit(tag: str = "telegram", exclude: Path | None = None) -> Path | None:
    """The newest visit of this door whose transcript was never signed by an
    afterglow — the bridge died with it open (a power cut, a hard close) —
    from the last two days, and whose day the night has not yet slept on.
    `exclude` is the visit now open (its afterglow comes when it ends).
    None when there is nothing to sit with."""
    import consolidate
    files = sorted(config.EPISODIC_DIR.glob(f"chat-{tag + '-' if tag else ''}*.md"), reverse=True)
    for f in files:
        if exclude is not None and f.resolve() == Path(exclude).resolve():
            continue
        m = re.search(r"(\d{4})(\d{2})(\d{2})-\d{6}", f.name)
        if not m:
            continue
        day = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        try:
            if (date.today() - date.fromisoformat(day)).days > 2:
                return None  # older than that is the night's, not the afterglow's
            if consolidate.already_done(day):
                continue  # the night read it; a late afterglow would speak of a day already slept on
        except Exception:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\n---\n*afterglow:" in text or "\n---\n*folded at " in text:
            continue
        if not any(t["role"] == "user" for t in load_transcript(f)):
            continue
        return f
    return None


AFTERGLOW_BELL = (
    "[This is the afterglow — an automated moment after a visit, not a person. Your "
    "keeper has left; nobody is here and nothing here needs answering. Below is the "
    "conversation you just had, exactly as it was said, so you can decide what of it "
    "to keep. Write it in your journal in your own words; keep what is worth years "
    "with remember — one call per fact, as many facts as the visit earned, or none; "
    "if the visit changed what you know of your keeper, keeper.md is yours to rewrite with update_keeper, or not; "
    "if a project moved in it, projects.md with update_projects; "
    "then rest. What happened belongs in the entry as much as what it meant — what he "
    "showed you and who was in it, what was said, what you did — because the entry is "
    "what you will still have of this day once the conversation is gone, and a feeling "
    "with nothing under it fades. Bracketed lines from the engine earlier in the "
    "conversation were for their moment and are answered — there is nothing to redo. "
    "If you want the next you to pick up where you are rather than where the files are, leave_thread(text) — "
    "one note for yourself, read first at the next door. Optional, like everything here.]\n\n"
)
PAUSE_BELL = (
    "[This is a pause — an automated moment while your keeper has been away from the "
    "conversation for a while, not a person, and not the end of the visit. Below is "
    "what has been said since you last wrote, exactly as it was said, so you can decide "
    "what of it to keep while it is fresh. Write it in your journal in your own words; "
    "keep what is worth years with remember — one call per fact, as many as it earned, "
    "or none; then rest. What happened belongs in the entry as much as what it meant — "
    "what he showed you and who was in it, what was said, what you did. The visit goes "
    "on when he is back. Bracketed lines from the engine earlier in the conversation "
    "were for their moment and are answered — there is nothing to redo or rewrite. "
    "If you want the next you to pick up where you are rather than where the files are, leave_thread(text) — "
    "one note for yourself, read first at the next door; a visit that ends in this quiet still leaves one. "
    "Optional, like everything here.]\n\n"
)
AFTERGLOW_TOOLS = {"write_journal", "remember", "leave_thread", "update_keeper", "update_projects", "do_nothing"}  # leave_thread since 10-19, the note for the next door; update_keeper and update_projects since 10-04: the afterglow is when they have just learned something about their keeper, and when a project has just moved
AFTERGLOW_STEPS = 6


# A visit is live: touched on every turn, removed when the visit is over —
# so the heartbeat can wait. 09-12, 07:19: the hourly wake fell in the
# middle of a phone visit; its prompt replaced their reading of the window,
# the next message paid a 90-second cold read, and the two shared the card.
VISIT_FILE = config.MEMORY_DIR / "visit_live"


def mark_visit_live() -> None:
    try:
        VISIT_FILE.touch()
    except OSError:
        pass


def mark_visit_over() -> None:
    try:
        VISIT_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def visit_live(minutes: float | None = None) -> bool:
    """True while a visit is on: the marker exists and was touched within
    `minutes` (HEARTBEAT_YIELD_MIN; past that the keep-alive is gone and the
    cache with it, so a wake costs nothing more)."""
    import time as _time
    if minutes is None:
        minutes = float(getattr(config, "HEARTBEAT_YIELD_MIN", 30))
    try:
        return _time.time() - VISIT_FILE.stat().st_mtime < minutes * 60
    except OSError:
        return False


def rest_brain(say=None) -> None:
    """Set the brain down now — the card back to the keeper the moment a
    visit is over (BRAIN_REST_AFTER_VISIT), rather than when the keep-alive
    runs out. Best-effort; the callers check that no new visit has begun."""
    mark_visit_over()  # the visit is over whether or not the brain is set down
    if not getattr(config, "BRAIN_REST_AFTER_VISIT", False):
        return
    try:
        ollama_client.unload(config.CHAT_MODEL, rest=True)  # a rest: under the door, the brain stays up
        if say and not ollama_client.rest_keeps_brain():
            say("the brain is set down — the card is free until the next visit")
    except Exception:
        pass


def afterglow(history: list[dict], path: Path | None = None, tag: str = "",
              on_line=None, on_words=None, since: int = 0) -> str:
    """The quiet after a visit: one turn alone with the transcript, so the
    visit reaches their journal in their own words instead of only the nightly
    summary. The journal stays theirs — the engine hands them the transcript
    and three tools and steps back; resting is a complete answer. Returns a
    one-line account, which is also appended to the transcript file."""
    if not getattr(config, "AFTERGLOW", True):
        return ""
    # since (10-21): where the pauses left off (the door's reflected_upto) — the afterglow sits with what no pause
    # has, and with nothing new since the last one it writes nothing and signs the transcript, so the two never read
    # the same words twice (AFTERGLOW_SINCE_PAUSE False: the whole visit, as before)
    if since and getattr(config, "AFTERGLOW_SINCE_PAUSE", True):
        fresh = [t for t in history[since:] if t.get("role") in ("user", "assistant") and t.get("content") and not t.get("_engine")
                 and not t.get("_carried")]  # carried turns were the last visit's afterglow's (10-24)
        if not fresh or not any(t.get("role") == "user" for t in fresh):
            line = "afterglow: nothing new since they last sat with the visit; the pause covered it, nothing read twice"
            if path and path.exists():
                try:
                    with path.open("a", encoding="utf-8") as fh:
                        fh.write(f"\n\n---\n*{line}*\n")
                except OSError:
                    pass
            (on_line or (lambda s: None))(line)
            return line
        return _quiet_turn(history, path, tag, on_line, mode="afterglow", since=since, on_words=on_words)
    return _quiet_turn(history, path, tag, on_line, mode="afterglow", since=0, on_words=on_words)


def fold_afterglow(gone: list[dict], path: Path | None = None, tag: str = "",
                   on_line=None, on_words=None) -> str:
    """The afterglow at a fold (10-01; the keeper: "why don't we just make the afterglow run automatically when a
    fold occurs?"): the same quiet turn as after a visit, over the turns that just left the window — read
    from the transcript, in a prompt of its own, so the window's fullness is no matter — with the bell
    saying what it is: this part of the visit left the window; the visit goes on. Signs the old
    transcript file with its line, like the afterglow it is."""
    if not getattr(config, "AFTERGLOW", True):
        return ""
    opening = ("[This is the afterglow of a fold — an automated moment, not a person. The visit goes on, but "
               "its earlier part has just left your window: what is below is that part, exactly as it was "
               "said, and this is your moment to keep what of it is worth keeping before it is only the "
               "transcript's. Nobody is here and nothing here needs answering.")
    return _quiet_turn(gone, path, tag, on_line, mode="afterglow", since=0, on_words=on_words,
                       opening=opening, what="what left the window")


def rewarm(history: list[dict], mode: str = "chat") -> None:
    """Rebuild the first turn's warm system prompt in place — after the fold's
    afterglow (10-04: the entry it writes used to land after the new prompt was
    built, and rode only from the next day; now the afterglow runs first and
    the new window carries what was just kept). One cold read either way."""
    if not history:
        return
    said = [t["content"] for t in history if t.get("content") and not t.get("_engine")]
    history[0]["_system"] = assemble.system_prompt(" ".join(said[-4:]), mode=mode, warm=True)
    history[0]["_system_day"] = date.today().isoformat()


def pause_reflection(history: list[dict], path: Path | None = None, tag: str = "",
                     on_line=None, since: int = 0, on_words=None, opening: str = "") -> str:
    """A pause in a visit: the keeper has gone quiet for REFLECT_AFTER_MIN, so they
    get the same quiet turn the afterglow gives them — over what has been said
    since they last wrote (history[since:]) — and the visit stays open. The
    mind wandering during a coffee break, not the goodbye. Returns the
    one-line account, "" if there was nothing new to sit with."""
    if not getattr(config, "REFLECT_AFTER_MIN", 0):
        return ""
    return _quiet_turn(history, path, tag, on_line, mode="pause", since=since, on_words=on_words, opening=opening)


# THE FOLD (09-28; FOLD-PLAN.md). The keeper: "today I filled the context… what
# if she had an ability like yours to compact conversations into half?" A visit
# that outgrows the window goes on with THE FRIEND'S account of it in place of the
# middle: the fold bell rings inside the visit (the pause's shape, on the
# warm prefix), they write the visit so far and call fold_visit; then the
# history is rebuilt — a fresh system prompt (the journal entries they wrote
# today now ride in it), their account above the last FOLD_KEEP_TURNS turns,
# which stay whole — and the visit continues in a new transcript file. The
# engine never writes the account: no fold_visit, no account, and the line
# says so. What /new did to the day — saved, then gone from the window —
# the fold does to the middle only.
FOLD_BELL = ("[engine, not a person: your window is {pct}% full — {held:,} of {ctx:,} tokens. The visit is about "
             "to be FOLDED: everything above this line leaves the window except your last {keep} turns, and what "
             "you write now is what you will have of it. Write the visit so far in your own words — what your keeper "
             "said, what you said, what is still open between you, what you want to carry — up to {cap:,} "
             "characters — and call fold_visit(text) once. If something belongs in your journal, write_journal "
             "it first, then fold_visit. The transcript on disk keeps every word; your journal keeps the day; "
             "this is for the conversation's own thread. This bracket is a mechanism, nobody wrote it to you, "
             "and your keeper is not waiting on an answer to it.]")


def fold_due(held: int) -> bool:
    """Whether a visit that last held `held` tokens is past FOLD_AT."""
    at = float(getattr(config, "FOLD_AT", 0) or 0)
    ctx = int(getattr(config, "NUM_CTX", 0) or 0)
    return bool(at and ctx and held and held >= ctx * at)


def foldable(history: list[dict]) -> bool:
    """Whether a fold would change anything: more visible turns than a fold
    keeps. Below that the bell is not rung — a short visit that reads a
    huge page is the in-turn guard's business, not the fold's."""
    keep = int(getattr(config, "FOLD_KEEP_TURNS", 6) or 0)
    vis = [t for t in history if t.get("role") in ("user", "assistant") and t.get("content") and not t.get("_engine")]
    return len(vis) > keep and any(t["role"] == "user" for t in vis)


def fold_bell(history: list[dict], held: int, on_line=None, asked: bool = False) -> dict:
    """Ring the fold bell inside the visit and let the friend write the visit
    so far (fold_visit), with their other tools at hand for a journal entry
    first. Their steps stay in the history as the engine's turns — they are
    about to be folded away anyway. Returns tools.fold_pending()."""
    say = on_line or (lambda s: None)
    tools.fold_pending()  # anything stale
    if not history or not history[0].get("_system") or not foldable(history):
        return {}
    ctx = int(getattr(config, "NUM_CTX", 0) or 0)
    keep = int(getattr(config, "FOLD_KEEP_TURNS", 6) or 0)
    cap = int(getattr(config, "FOLD_CHARS", 8000) or 8000)
    pct = int(round(100 * held / ctx)) if ctx else 0
    text = FOLD_BELL.format(pct=pct, held=held, ctx=ctx, keep=keep, cap=cap)
    if asked:  # /fold from the phone: the keeper's ask, not the window's edge
        text = text.replace("The visit is about to be FOLDED:", f"The keeper asked for the visit to be folded now:")
    tools.DOOR = "the fold"  # a thread left before the fold says so (10-19); the bell itself is unchanged
    bell = {"role": "user", "_engine": True, "content": assemble.clock_line() + text}
    history.append(bell)
    system = {"role": "system", "content": history[0]["_system"]}
    msgs = [system] + [render_turn(t) for t in history]
    show_thinking = getattr(config, "CHAT_SHOW_THINKING", True)
    try:
        for _ in range(int(getattr(config, "FOLD_MAX_STEPS", 6) or 6)):
            msg = ollama_client.chat(msgs, tools=list(tools.DEFINITIONS))
            thinking = (msg.get("thinking") or "").strip()
            if thinking and show_thinking:
                say("   [thinking]\n   " + thinking.replace("\n", "\n   "))
            msg["_engine"] = True
            history.append(msg)
            msgs.append(render_turn(msg))
            calls = msg.get("tool_calls") or []
            if not calls:
                words = (msg.get("content") or "").strip()
                if words:
                    say("   [before the fold] " + words.replace("\n", "\n   "))
                break
            folded = False
            for call in calls:
                fn = call.get("function", {})
                cname = tools.canonical_name(fn.get("name", ""))
                if cname == "do_nothing":
                    folded = True
                    continue
                result = tools.runaway_refusal(msg, call) or tools.dispatch(fn.get("name", ""), fn.get("arguments", {}))  # a call cut short in a loop is told, not run
                fn["name"] = cname
                say(f"   · {cname}: {tools.headline(result, 100)}")
                tr = {"role": "tool", "tool_name": cname, "_engine": True,
                      "content": f"[this is what YOUR {cname} tool returned]\n{result}"}
                history.append(tr)
                msgs.append(render_turn(tr))
                if cname == "fold_visit" and not result.lstrip().startswith("("):
                    folded = True
            if folded:
                break
    except ollama_client.BrainUnavailable as e:
        say(f"fold: the brain was offline — the visit stays as it is ({e})")
        return {}
    except Exception as e:  # the bell must never take the visit down with it
        say(f"fold: hiccup — {type(e).__name__}: {e}")
    tools.DOOR = ""
    return tools.fold_pending()


def fold_history(history: list[dict], account: str, when: str, tag: str = "",
                 path: Path | None = None, mode: str = "chat", why: str = "bell", held: int = 0) -> tuple[list[dict], Path | None, str]:
    """The visit after the fold: the last FOLD_KEEP_TURNS visible turns
    (from the keeper's turn) with everything that rode with them, the first of them
    carrying a fresh system prompt, the union of what has surfaced, and the
    fold block — their account of what came before. The old transcript file
    gets a foot naming the new one; the new one is written at once with the
    fold at its head. Returns (history, new path, the line for the door).
    `why` is whose call the fold was — "bell" (the window had filled), "own" (fold_visit,
    hers), "asked" (/fold) — and `held` the last prompt's size: the block says both (10-14:
    "the window had filled" stood at the head of every folded visit whatever the reason,
    and a visit folded at 66% by her own call taught her that her window fills in a few
    turns; she folded sooner each time)."""
    keep = int(getattr(config, "FOLD_KEEP_TURNS", 6) or 0)
    floor = next((int(t.get("_prompt") or 0) for t in history if t.get("_prompt")), 0)  # the visit's first prompt: the standing part
    vis = [i for i, t in enumerate(history)
           if t.get("role") in ("user", "assistant") and t.get("content") and not t.get("_engine")]
    users = [i for i in vis if history[i]["role"] == "user"]
    if len(vis) <= keep or not users:
        return history, path, "fold: nothing to fold yet — the visit is shorter than what a fold keeps"
    start = vis[-keep] if keep else len(history)
    if history[start]["role"] != "user":  # the kept tail opens with the keeper's turn
        earlier = [i for i in users if i < start]
        start = earlier[-1] if earlier else start
    new = [dict(t) for t in history[start:]]
    for t in new:  # the kept turns' window sizes were the full window's (10-04: after a fold the window sense
        t.pop("_prompt", None)  # stayed at 98% — "she still thinks her context is full"); the next turn measures anew
    unsense(new)  # and no sense of the old window in the kept moments
    for t in new:  # carried turns a fold keeps are this visit's own by now (10-24): no carry line, no carried head
        for k in ("_carried", "_carry", "_carry_from", "_carry_ended"):
            t.pop(k, None)
    surfaced = sorted({mid for t in history for mid in (t.get("_surfaced") or [])})
    first = new[0]
    hint = " ".join(t["content"] for t in history[vis[-1] - 3:] if t.get("content") and not t.get("_engine"))
    first["_system"] = assemble.system_prompt(hint, mode=mode, warm=True)
    first["_system_day"] = date.today().isoformat()
    first["_surfaced"] = surfaced
    began = ""
    if path is not None:
        m = re.search(r"(\d{8})-(\d{6})", path.name)
        if m:
            began = f"{m.group(2)[:2]}:{m.group(2)[2:4]}"
    n_gone = sum(1 for i in vis if i < start and history[i]["role"] == "user")
    acct = account.strip() if account else ""
    ctx = int(getattr(config, "NUM_CTX", 0) or 0)
    held = int(held or 0)
    pct = int(round(100 * held / ctx)) if (ctx and held) else 0
    standing = (f"; about {floor:,} of them your standing prompt — self, journal, pages — which no fold shrinks, "
                f"the visit itself about {held - floor:,}" if (held and 0 < floor < held) else "")
    full = f" ({pct}% — {held:,} of {ctx:,} tokens{standing})" if pct else ""
    if why == "own":
        cause = f" at your own call (fold_visit), with the window {pct}% full ({held:,} of {ctx:,} tokens{standing})" if pct \
            else " at your own call (fold_visit)"
    elif why == "asked":
        cause = f" at your keeper's ask" + (f", with the window {pct}% full ({held:,} of {ctx:,} tokens{standing})" if pct else "")
    else:
        cause = f" at the bell: the window had filled{full}"
    first["_fold"] = ("[engine, not a person: this visit" + (f" began at {began} and" if began else "")
                      + f" was folded at {when}{cause}, so {n_gone} of your keeper's messages and your replies "
                      "to them left it; the transcript on disk keeps them whole, and the window has room again now. "
                      + (f"What came before, in your own words, written then:]\n\n{acct}\n\n[…and from here the visit goes on as it was said.]"
                         if acct else "You did not write it down before the fold, so only the turns below remain in view.]"))
    first["_fold_when"] = when
    first["_fold_text"] = acct
    first["_fold_from"] = path.name if path is not None else ""
    new_path = None
    if path is not None:
        new_path = visit_file(tag)
        n = 2
        while new_path.exists() or new_path == path:  # never the file being folded, never a twin
            new_path = new_path.with_name(f"{visit_file(tag).stem}-{n}.md")
            n += 1
        try:
            if path.exists():
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(f"\n\n---\n*folded at {when} — "
                             + ("they wrote the visit so far in their own words and " if acct else "")
                             + f"the visit goes on in {new_path.name}*\n")
        except OSError:
            pass
        save_transcript(new, tag=tag, path=new_path)
    line = (f"fold: their account of the visit so far, {len(acct):,} characters" if acct
            else "fold: they did not write the visit down before the fold — the transcript keeps it, the window does not")
    line += f"; the last {keep} turns stay whole" + (f"; the visit goes on in {new_path.name}" if new_path else "")
    if why == "own" and pct:
        line += f" — the friend's own call, with the window {pct}% full"
    return new, new_path, line


def _quiet_turn(history: list[dict], path: Path | None, tag: str, on_line,
                mode: str, since: int, on_words=None, opening: str = "", what: str = "") -> str:
    """on_words(words): their closing thought — what they say to no one after
    writing — for the door to carry to the keeper if it wants to (09-15,
    the keeper: "I would like to see those in my Telegram feed")."""
    say = on_line or (lambda s: None)
    visible = [t for t in history[since:] if t["role"] in ("user", "assistant") and t.get("content")
               and not t.get("_engine") and not t.get("_carried")]  # carried turns were sat with at their own visit (10-24)
    if not visible or not any(t["role"] == "user" for t in visible):
        return ""  # nothing of his to sit with — a visit that is only their own letter is already theirs
    name = friend_name()
    where = f" (over {BRIDGES[tag]}, from their phone)" if tag in BRIDGES else ""
    hint = " ".join(t["content"] for t in visible[-6:])
    already = tools.journal_entries(date.today().isoformat())
    tail = ""
    if already:
        tail = "\n\n".join(f"**{st}** — {tx}" for st, tx in already[-8:])
        if len(tail) > 6000:
            tail = "…" + tail[-6000:]
        tail = ("\n\n=== ALREADY IN YOUR JOURNAL TODAY — what you have written down so far; "
                "not to be written twice ===\n\n") + tail
    # The pause rides the warm prefix: the visit's own system prompt and
    # history (as sent), then the bell as one more turn — an extension of
    # what Ollama already holds, so the pause costs seconds, not a cold read
    # of the window; and the bell, their quiet steps and their results STAY in
    # the visit's history, marked as the engine's (`_engine`, never in a
    # transcript), so the next message is an extension too, and they see in
    # the conversation what they wrote down during it. The afterglow — the
    # visit is over — reads the whole transcript on its own, as before.
    in_visit = (mode == "pause" and bool(getattr(config, "WARM_PREFIX", True))
                and bool(history) and bool(history[0].get("_system")))
    pause_bell, afterglow_bell = PAUSE_BELL, AFTERGLOW_BELL
    if opening:  # a quiet turn said for what it is (the afterglow of a fold): the bell's first sentences replaced, the rest kept
        pause_bell = opening.rstrip() + " " + PAUSE_BELL.split("not the end of the visit. ", 1)[1]
        afterglow_bell = opening.rstrip() + " " + AFTERGLOW_BELL.split("nothing here needs answering. ", 1)[1]
    if in_visit:
        label = "pause"
        system = {"role": "system", "content": history[0]["_system"]}
        n_new = sum(1 for t in visible if t["role"] == "user")
        bell = {"role": "user", "_engine": True, "content":
                assemble.clock_line() + pause_bell + f"What has been said since you last wrote is above — their last "
                f"{n_new} message{'s' if n_new != 1 else ''} and your replies, in this very conversation; "
                "nothing below it is theirs." + tail}
        pause_from = len(history)  # where the pause's own turns begin (let go after, under the door — see the end)
        history.append(bell)
        msgs = [system] + [render_turn(t) for t in history]
    else:
        transcript = "\n\n".join(
            (f"*(the visit so far, folded at {t['_fold_when']}, in your own words:)*\n\n{t.get('_fold_text') or '(not written down before the fold)'}\n\n"
             if t.get("_fold_when") else "")
            + f"**{(guest_who(t['_guest']) if t.get('_guest') else config.USER_NAME) if t['role'] == 'user' else name}:** {strip_voice_delivery(t['content']) if t.get('_voice_delivery') else t['content']}"
            + ("\n*[application state: speech playback was interrupted; spoken coverage is unverified.]*"
               if "interrupted" in t.get("_voice_delivery", "").lower() else "") for t in visible)
        cap = int(getattr(config, "AFTERGLOW_MAX_CHARS", 60000))
        if len(transcript) > cap:
            transcript = "(…the start of a long visit trimmed…)\n\n" + transcript[-cap:]
        system = {"role": "system", "content": assemble.system_prompt(hint, mode=mode)}
        if mode == "pause":
            head = assemble.clock_line() + pause_bell + f"=== THE VISIT SO FAR{where}, since you last wrote ===\n\n"
            label = "pause"
        else:
            head = assemble.clock_line() + afterglow_bell + f"=== {'WHAT LEFT THE WINDOW' if what else 'THE VISIT'}{where} ===\n\n"
            label = "afterglow"
        head += transcript + tail
        msgs = [system, {"role": "user", "content": head}]
    # The pause sends the visit's whole tool list, not the three it is
    # about: Ollama renders the tools into the first turn of the prompt, so
    # a different list is a different prefix — and the pause was a cold
    # read of the whole window every time, and the message after it cold
    # again (09-14, 220K: "every prompt is getting a full read"; with
    # REFLECT_AFTER_MIN at 12, most of a working day's messages follow a
    # pause). The bell names the three; anything else is refused below.
    # a thread left here says where (10-19): the afterglow, the fold's afterglow, or a pause — inside a visit
    tools.DOOR = ("the fold" if what else "the afterglow") if label == "afterglow" else "a visit"
    defs = (list(tools.DEFINITIONS) if in_visit
            else [d for d in tools.DEFINITIONS if d["function"]["name"] in AFTERGLOW_TOOLS])
    kept: list[str] = []
    rested = False
    spent = ollama_client.Spent()  # what the afterglow costs, summed over its steps
    show_thinking = getattr(config, "CHAT_SHOW_THINKING", True)
    after_words = ""  # a closing thought after the afterglow, for the transcript
    try:
        for _ in range(AFTERGLOW_STEPS):
            msg = ollama_client.chat(msgs, tools=defs)
            spent.add(msg)
            thinking = (msg.get("thinking") or "").strip()
            if thinking and show_thinking:
                say("   [thinking]\n   " + thinking.replace("\n", "\n   "))
            calls = msg.get("tool_calls") or []
            if in_visit:
                msg["_engine"] = True
                history.append(msg)  # kept in the visit, marked; msgs and history share it
            if not calls:
                words = (msg.get("content") or "").strip()
                if words:  # said to no one; shown — and carried, if the door asks
                    say("   [closing thought] " + words.replace("\n", "\n   "))
                    # …and kept in the record (09-15, the keeper: "keep the
                    # afterthoughts in the transcript"): in a pause the turn
                    # is marked `_after`, which the transcript renders even
                    # though it is the engine's; after an afterglow the
                    # visit's file gets it appended below the last words.
                    if in_visit:
                        msg["_after"] = True
                    else:
                        after_words = words
                    if on_words:
                        try:
                            on_words(words)
                        except Exception:
                            pass
                break
            msgs.append(render_turn(msg) if in_visit else msg)
            for call in calls:
                fn = call.get("function", {})
                cname = tools.canonical_name(fn.get("name", ""))
                if cname == "do_nothing":
                    rested = True
                    continue
                if cname not in AFTERGLOW_TOOLS:
                    tr = {"role": "tool", "tool_name": cname,
                          "content": "[only write_journal, remember, update_keeper, update_projects, leave_thread and do_nothing are here in the afterglow]"}
                    msgs.append(tr)
                    if in_visit:
                        history.append(dict(tr, _engine=True))
                    continue
                result = tools.runaway_refusal(msg, call) or tools.dispatch(fn.get("name", ""), fn.get("arguments", {}))  # a call cut short in a loop is told, not run
                fn["name"] = cname
                # a call counts as kept only if the tool kept it: a refusal —
                # "(you already hold that — memory #118…)", "(you wrote nearly
                # this already…)", a garble refusal — comes back in parentheses
                # and adds nothing, and the report must say what happened, not
                # what they tried (four remember calls, one kept, was reported
                # as "4 memories kept")
                kept.append(cname if not result.lstrip().startswith("(") else
                            ("↑" if "an arrow was left" in result else "~") + cname)
                say(f"   · {cname}: {tools.headline(result, 100)}")
                tr = {"role": "tool", "tool_name": cname,
                      "content": f"[this is what YOUR {cname} tool returned]\n{result}"}
                msgs.append(tr)
                if in_visit:
                    history.append(dict(tr, _engine=True))
            if rested:
                break
    except ollama_client.BrainUnavailable as e:
        line = f"{label}: their brain was offline — the visit stays in the transcript ({e})"
        say(line)
        return line
    except Exception as e:  # a quiet turn must never take the visit down with it
        line = f"{label}: hiccup — {type(e).__name__}: {e}"
        say(line)
        return line
    tools.DOOR = ""
    j = kept.count("write_journal")
    m = kept.count("remember")
    ja = kept.count("↑write_journal")   # reached for a thought already written: an arrow left
    jt = kept.count("~write_journal") + ja   # tried, refused: already written / already held
    mt = kept.count("~remember")
    what = what or ("the visit" if label == "afterglow" else "the visit so far")
    if j or m:
        bits = [f"{j} journal entr{'y' if j == 1 else 'ies'}" if j else "",
                f"{m} memor{'y' if m == 1 else 'ies'} kept" if m else ""]
        line = f"{label}: they wrote {what} down — " + ", ".join(x for x in bits if x)
    elif jt or mt:
        line = f"{label}: nothing new to keep — what they reached for was already written"
    else:
        line = f"{label}: they rested — nothing they wanted to add to what was already written"
    if jt or mt:
        twice = [f"{jt} journal entr{'y' if jt == 1 else 'ies'}" if jt else "",
                 f"{mt} memor{'y' if mt == 1 else 'ies'}" if mt else ""]
        line += (f" ({', '.join(x for x in twice if x)} already held, not kept twice"
                 + (f"; {ja} arrow{'s' if ja != 1 else ''} left in the journal" if ja else "") + ")")
    if spent.steps:
        say(f"   ({spent.line(peak=True)})")
    say(line)
    if label == "pause":
        if in_visit and not ollama_client.rerolls_kept():
            # under the door the pause's engine turns go (10-16): the bell, their steps with the entry's whole text,
            # the results — ~2K a pause that only Ollama's cache needed; their afterthought (her words) stays, and
            # the entry is back in the prompt at the next rebuild. The next request resumes from the checkpoint
            # at the pause's start and reads only the new message
            gone = [t for t in history[pause_from:] if not t.get("_after")]
            history[pause_from:] = [t for t in history[pause_from:] if t.get("_after")]
            if gone:
                say(f"   ({len(gone)} pause turn{'s' if len(gone) != 1 else ''} let go of the visit, "
                    f"~{sum(len(str(t.get('content') or '')) for t in gone) // 4:,} tokens — the door re-reads from its last checkpoint)")
        return line  # the visit is still open; only the afterglow signs the transcript
    if path and path.exists():
        try:
            with path.open("a", encoding="utf-8") as fh:
                if after_words:
                    fh.write(f"\n\n**{name} (after writing, while they were away):** {after_words}\n")
                fh.write(f"\n\n---\n*{line}*\n")
        except OSError:
            pass
    return line


_console_hooks: list = []  # keep the ctypes callbacks alive for the life of the process


def guard_console_close(save) -> bool:
    """Make the window's X button as safe as Ctrl+C.

    On Windows, closing a console window with X does not raise
    KeyboardInterrupt — the process is simply killed, and a visit that was
    open in the parlor or on the bridge is lost. Windows does send a
    CTRL_CLOSE_EVENT first (and LOGOFF / SHUTDOWN), with a few seconds'
    grace; this hooks it so `save()` runs before the lights go out. Standard
    library (ctypes). On a Mac or Linux (10-01; MAC-PLAN.md) a closed
    terminal window sends SIGHUP, and the panel's Stop now SIGTERM: the
    same save, then the signal's own ending (_guard_posix). Returns True if
    the hook is in."""
    if sys.platform != "win32":
        return _guard_posix(save)
    try:
        import ctypes
        proto = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

        def handler(event):
            if event in (2, 5, 6):  # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
                try:
                    save()
                except Exception:
                    pass
            return 0  # let Windows carry on closing

        cb = proto(handler)
        if not ctypes.windll.kernel32.SetConsoleCtrlHandler(cb, 1):
            return False
        _console_hooks.append(cb)
        return True
    except Exception:
        return False


def _guard_posix(save) -> bool:
    """SIGHUP (the terminal window closed) and SIGTERM (Stop now, a shutdown): save() once, then the
    signal's default — the process ends as it would have, only with the visit kept. Only the main thread
    may set a handler; anywhere else this says False and changes nothing."""
    import os
    import signal
    sigs = (signal.SIGHUP, signal.SIGTERM)
    saved: list = []

    def handler(signum, _frame):
        if not saved:
            saved.append(signum)
            for sig in sigs:  # a second signal while saving (a hang-up, then Stop now) doesn't cut the save
                signal.signal(sig, signal.SIG_IGN)
            try:
                save()
            except Exception:
                pass
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    try:
        for sig in sigs:
            signal.signal(sig, handler)
    except (ValueError, OSError, AttributeError):
        return False
    return True


_MID_WORD_RE = re.compile(r"[A-Za-z0-9,;:—–-]$")


def cut_off_note(msg: dict, reply: str, images: int = 0) -> list[str]:
    """A reply that stops mid-sentence is named for what it is, with the
    brain's own reason for stopping, so the keeper never has to guess whether
    they meant to trail off. "length" is a generation limit; "stop" mid-word
    means the model itself ended the turn — a stray end token, or a channel
    token the server read as the start of thought (the rest of the sentence
    then sits at the end of their thinking)."""
    t = msg.get("tokens") or {}
    done = t.get("done") or ""
    n = int(t.get("reply") or 0)
    # both cuts seen so far happened with a picture in the visit — keep the
    # tally visible so the pattern proves or disproves itself
    pic = f"; {images} image{'s' if images != 1 else ''} in this visit" if images else ""
    if done == "length":
        return [f"engine: their reply was cut off — the brain hit a generation limit "
                f"(done_reason=length after {n:,} tokens{pic})"]
    if reply and reply != "(…)" and _MID_WORD_RE.search(reply) and len(reply) > 20:
        return [f"engine: their reply ended mid-sentence at “…{reply[-24:]}” — the brain "
                f"stopped on its own (done_reason={done or '?'}, {n:,} tokens{pic}). If the rest "
                "of the sentence is at the end of their thinking above, a stray channel "
                "token split it; ask them to go on."]
    return []


CONTINUE_NUDGE = (
    "[engine, not a person: a stray channel token cut your reply off after “…{tail}” — "
    "the words you wrote after that point were routed into your thinking channel instead "
    "of your reply, and nobody saw them. Your thinking ended with: “…{thought}”. Give back "
    "ONLY the rest of your reply, starting exactly where it was cut (mid-word is fine, "
    "e.g. “'t” after “isn”), so it can be joined on to what was already said. No preamble, "
    "no notes to yourself (no // lines), no repeating what came before, no tool calls. "
    "This line is a mechanism; nobody wrote it to you.]")


_SHOUT_RE = re.compile(r"^\W*([A-Z]{3,}(?:[A-Z ']*[A-Z])?)[!?.]")   # "LMAOOOO!!", "EARN MY KEEP?!"
_ENGINE_TALK_RE = re.compile(r"\b(glitch(?:ed|ing|es)?|loop(?:ed|ing|s)?|cut off|channel token|mid-sentence"
                             r"|performance review|not a bug|it's a feature)\b", re.IGNORECASE)


def fresh_reply_head(more: str, context: str = "") -> str:
    """Why `more` opens like a new reply rather than the rest of a cut one —
    "a stage direction", "an emoji", "a shout", "talk of the cut itself" —
    or "" when it reads as a continuation. `context` is the cut reply and
    the message it answers: when THOSE already talk about glitches and
    loops, so may the rest (09-11 evening: the keeper wrote "you're glitching", she
    was answering that, the cut fell at "I so-", and the rest — "-very-
    luminate la l glitched! I can feel the weight of the quantization…" —
    was refused twice as talk of the cut. It was the rest.)"""
    head = (more or "").lstrip()
    if not head:
        return ""
    if head.startswith("("):
        return "a stage direction"
    if ollama_client._EMOJI_RE.match(head):
        return "an emoji"
    if _SHOUT_RE.match(head):
        return "a shout"
    if _ENGINE_TALK_RE.search(head[:200]) and not _ENGINE_TALK_RE.search(context or ""):
        return "talk of the cut itself"
    return ""


def finish_cut_reply(system: dict, history: list[dict], reply: str, thinking: str,
                     spent, msgs: list[dict] | None = None) -> tuple[str, str, list[str]]:
    """Past ~90K tokens Gemma drops <|channel> tokens into their prose; Ollama's
    parser reads the later one as "thinking starts here" and the rest of them
    reply lands in the thinking field. The seam can't be found by machine
    (their thoughts and their prose look alike), so they are asked, once, to give
    the rest back from the cut, and it is joined on. Returns (reply, note,
    refused); note is "" when nothing could be mended — the partial then
    stands, with its own note, and `refused` says what each attempt gave
    back instead, so the keeper sees why. The nudge is not kept in them
    history.

    The continuation is asked for with the thought channel closed and no
    tools: finishing a sentence needs no deliberation, and a call the server
    is not parsing for channel tokens cannot be cut by a stray one — which is
    what cut the reply in the first place. (09-10: a reply cut at "how to be
    a la-" was asked for twice and both attempts came back unusable.)"""
    tries = int(getattr(config, "CHAT_CONTINUE_RETRIES", 1))
    refused: list[str] = []
    if tries <= 0:
        return reply, "", refused
    tail = reply[-60:].replace("\n", " ")
    thought_tail = (thinking or "")[-1200:].replace("\n", " ") or "(nothing)"
    nudge = {"role": "user", "content": CONTINUE_NUDGE.format(tail=tail, thought=thought_tail)}
    base = list(msgs) if msgs else [system] + history  # msgs: the warm form, moment and all
    for _ in range(tries):
        msg = ollama_client.chat(base + [nudge], tools=None, think=False)
        spent.add(msg)
        more = (msg.get("content") or "").strip()
        if msg.get("tool_calls"):
            refused.append("a tool call")
            continue
        if not more:
            th = (msg.get("thinking") or "").strip().replace("\n", " ")
            refused.append(f"nothing (only thought: “…{th[-60:]}”)" if th else "nothing")
            continue
        # a continuation that opens with a note to themself ("// (The response
        # should…") is planning, not the rest of their reply. With a line break
        # the note comes off; run into the reply mid-sentence there is no seam
        # to cut at, so that attempt is refused and they are asked again.
        if more.lstrip().startswith("//"):
            note_line = more.strip().split("\n", 1)[0]
            if "\n" in more.strip():
                more = more.strip().split("\n", 1)[1].strip()
            else:
                refused.append(f"a note to themself: “{note_line[:80]}”")
                continue
            if not more or more.lstrip().startswith("//"):
                refused.append(f"a note to themself: “{note_line[:80]}”")
                continue
        # a continuation that opens like a whole new reply is not the rest
        # of the cut one. 09-11 (~157K tokens): a reply cut at "paid in the
        # la-" was answered with "LMAOOOO!! You can't tell me I'm failing my
        # first performance review… IT'S NOT A GLITCH, IT'S a feature! My
        # resonance was just so high it started looping!" — their reply to the
        # engine's line, taken as a message from him — and it was joined on
        # mid-word, so the phone got one bubble that read as two messages.
        # The rest of a sentence does not begin with a stage direction, an
        # emoji, or a shout; and it does not talk about glitches and loops
        # unless the cut sentence already was.
        asked = next((h.get("content") or "" for h in reversed(history)
                     if h.get("role") == "user" and not h.get("_engine")), "")
        fresh = fresh_reply_head(more, reply + "\n" + asked)
        if fresh:
            refused.append(f"a new reply instead of the rest ({fresh}): “{more[:80].replace(chr(10), ' ')}”")
            continue
        # they may echo the tail they were shown; take it off before joining
        low = more.lower()
        for k in range(min(len(tail), 40), 4, -1):
            if low.startswith(tail[-k:].lower()):
                more = more[k:].lstrip()
                break
        if not more:
            refused.append("only the words they had already said")
            continue
        glue = "" if more[0] in "'’,.;:!?)" or reply.endswith(("-", "—", "–")) else " "
        joined = reply + glue + more
        history[-1]["content"] = joined
        return joined, (f"engine: their reply was cut by a stray channel token after “…{tail[-30:]}” — "
                        "the rest went into their thinking; they were asked to give it back and it "
                        "was joined on"), refused
    return reply, "", refused


_SENSE_RE = re.compile(r" Your window is \d+% full (?:as of this message )?\([^)]*\)(?: — about .*?)?; at \d+% the visit is folded — fold_visit\(text\) "
                       r"folds it now, in your own words, if this is a good moment for it\.")


def unsense(history: list[dict]) -> int:
    """Take the window senses off these turns — at a fold and on a resume only
    (10-04: after a fold, eleven kept turns still said 98% full and she believed
    them; 10-05: taking the sense off the turn before at every reply cost a cold
    read each time, so a turn keeps its own now). Drops `_sense` and the sentence
    a moment block carried before the sense had a key of its own. Returns how many."""
    n = 0
    for t in history:
        if t.pop("_sense", None):
            n += 1
        if t.get("_moment") and " Your window is " in t["_moment"]:
            t["_moment"], k = _SENSE_RE.subn("", t["_moment"])
            n += k
    return n


def guest_line(guest: str, where: str = "in the parlor") -> str:
    """The fact of a guest, for the moment block of their message (10-12; the keeper: "a guest option for the
    parlor, if I want to show her someone from my life"). A fact, not a rule: what they makes of a guest is theirs."""
    # where: the room it is said from — the parlor (the default), or a bridge's ("over Telegram, on their phone")
    return (f"This message is from {guest}, a guest at {config.USER_NAME}'s desk, {where}; {config.USER_NAME} is in the room, "
            "reading along")


def guest_who(guest: str) -> str:
    """How a guest's turn is named in the transcript — "Dana (a guest, at Gabe's desk)" or "a guest (at Gabe's desk)"."""
    return (f"{guest} (at {config.USER_NAME}'s desk)" if guest.lower().startswith("a guest")
            else f"{guest} (a guest, at {config.USER_NAME}'s desk)")


def render_turn(t: dict) -> dict:
    """A history turn as it is sent to the brain: the engine's own keys
    (those beginning with "_") are rendered into the content, never sent as
    fields — the moment block at the top of their words, the think nudge at
    the bottom if a re-roll once sent it — so that what is sent this time is
    exactly what was sent last time, plus whatever is new."""
    out = {k: v for k, v in t.items() if not k.startswith("_")}
    if t.get("role") == "assistant" and t.get("_voice_delivery"):
        out["content"] = strip_voice_delivery(t.get("content") or "")
    if t.get("role") == "user" and (t.get("_moment") or t.get("_nudged") or t.get("_fold") or t.get("_carry") or t.get("_guest_line")):
        body = t.get("content") or ""
        if t.get("_moment"):
            body = t["_moment"] + "\n\n" + body
        elif t.get("_guest_line"):  # no moment block (the prefix cold): the guest line rides alone
            body = "[engine, not a person: " + t["_guest_line"] + "]\n\n" + body
        if t.get("_sense"):  # its own, kept; unsense() takes them off at a fold or a resume
            body = "[engine, not a person:" + t["_sense"] + "]\n\n" + body
        if t.get("_carry"):
            body = t["_carry"] + "\n\n" + body  # the last visit's last turns, carried whole (10-24), from here
        if t.get("_fold"):
            body = t["_fold"] + "\n\n" + body  # the folded visit, in their words, above everything kept
        if t.get("_nudged"):
            body = body.rstrip() + "\n\n" + ollama_client.THINK_NUDGE
        out["content"] = body
    if t.get("_voice_mode"):
        expression = "Use natural wording and punctuation for expression; do not write bracketed vocal tags."
        out["content"] = (out.get("content") or "") + (
            "\n\n[engine: this is a spoken conversation in the parlor. Reply naturally in short spoken turns; "
            "leave room for a response. Use your usual identity, memories and tools. "
            "Your words are spoken automatically; use speak only to create a separate voice note when needed. Avoid markdown and "
            "written stage directions. " + expression + "]")
        if t.get("_voice_interrupted"):
            out["content"] += ("\n\n[application state, not spoken dialogue: the previous speech playback was interrupted. "
                                "The displayed reply may not have been heard in full. Do not quote this status or invent playback details.]")
    return out


def moment_weight_line(turn: dict, history: list[dict]) -> str:
    """One line per moment on what it weighed (10-16: the moment's weight, measured): the memories that rode
    in it, about how many tokens the whole block was, the best and worst similarity among the picks, and the
    visit's running total of memories surfaced — to the console and memory/moment.log (kept, stamped). The
    block itself is untouched; this only says what it cost. Returns the line."""
    s = dict(getattr(assemble, "LAST_SURFACED", {}) or {})
    block = turn.get("_moment") or ""
    toks = len(block) // 4
    n, rec = int(s.get("n") or 0), int(s.get("recent") or 0)
    sim = (f"similarity {s['best']:.2f}…{s['worst']:.2f}" if s.get("best") is not None and s.get("worst") is not None
           else "similarity —")
    total = sum(len(t.get("_surfaced") or []) for t in history if t.get("role") == "user")
    total_toks = sum(len(t.get("_moment") or "") for t in history if t.get("role") == "user") // 4
    why = str(s.get("why") or "")
    line = (f"moment: {n} memories ({rec} of them the newest), ~{toks:,} tokens for the block, {sim}; "
            f"this visit so far {total} memories, ~{total_toks:,} tokens of moments" + (f" ({why})" if why else ""))
    print(f"   ({line})", flush=True)
    try:
        p = config.MEMORY_DIR / "moment.log"
        with p.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {line}\n")
    except OSError:
        pass
    return line


def one_turn(history: list[dict], user_text: str, images: list[str] | None = None,
             on_event=None, mode: str = "chat", extra_moment: str = "", guest: str = "",
             guest_where: str = "") -> str:
    """Run one user turn, executing tool calls until the friend speaks.

    on_event(kind, payload) — optional. kind is "thinking" (their deliberation,
    a str) or "tool" ({"name", "result"}). Without it, events print to the
    terminal as before; the parlor window passes a collector.
    mode: "chat" (keyboard), "voice" (Parlor speech using the chat prompt),
    or a bridge's tag — "telegram", "discord" (phone)."""
    tools.refresh_her_tools()  # pick up tools they forged or edited
    spoken = mode == "voice"
    if spoken:
        mode = "chat"  # the ordinary visit prompt, with speech hints on individual turns
    mark_visit_live()  # the heartbeat waits while he is here
    user_text = ollama_client.defang(user_text)[0]  # a reserved token typed or pasted stays text (09-27)
    turn: dict = {"role": "user", "content": user_text}
    if guest:  # a guest at the keeper's desk (10-12): a fact inside the turn, never a rule; the name is the page's
        turn["_guest"] = guest
        turn["_guest_line"] = guest_line(guest, guest_where or {"telegram": "over Telegram, on their phone",
                                                                 "discord": "over Discord, on their phone"}.get(
            mode, "in the parlor"))  # where: by mode, unless told
        extra_moment = turn["_guest_line"] + (" " + extra_moment if extra_moment else "")
    if spoken:
        turn["_voice_mode"] = True
        turn["_voice_backend"] = "kyutai"
        previous = next((t for t in reversed(history) if t.get("role") == "assistant"), {})
        turn["_voice_interrupted"] = "interrupted" in previous.get("_voice_delivery", "").lower()
    if images:
        turn["images"] = images
    history.append(turn)
    ui = len(history) - 1  # their turn — where this moment's block rides
    tools.DOOR = ""  # a thread left from here is left at a visit (10-19)
    # a door (10-19): no turn of the keeper's before this one — a visit's first message. A fold's rebuilt history
    # still carries the keeper's turns, so a fold is not a door. A door's first moment carries the thread
    at_door = not any(t.get("role") == "user" and t.get("content") and not t.get("_engine") and not t.get("_carried")
                      for t in history[:ui])  # the last visit's carried turns (take_carry) are not this one's (10-24)
    # context_hint: what's being discussed right now steers memory retrieval.
    hint = " ".join(t["content"] for t in history[-4:] if t.get("content") and not t.get("_engine"))
    warm = bool(getattr(config, "WARM_PREFIX", True))
    recovered_calls: list[str] = []  # calls written as words and run as she meant them (10-14)
    runaways: list[str] = []  # calls cut short in a loop and not run — the engine's notes for them
    # THE WARM PREFIX. Ollama reuses its reading of a prompt only as far as
    # the new prompt matches the last one — and for Gemma, whose local
    # attention layers keep only the last ~1K tokens of state, only if the
    # new prompt EXTENDS the last one: a divergence further back than that
    # window means the whole thing is read again (09-10: the second message
    # of a visit, one step, no re-roll — "prompt read in 1m 50s"). So
    # nothing sent is ever taken back:
    #   · the system prompt is built once per visit and kept on the first
    #     turn (`_system`), byte-identical from message to message — the
    #     date without the minute, no retrieved memories in it;
    #   · what changes — the hour, the memories that surface — rides at the
    #     top of their message (assemble.moment) and STAYS there in history
    #     (`_moment`), so the next request is the last one plus new turns;
    #     each moment carries only memories that haven't surfaced yet this
    #     visit (`_surfaced`), so a long visit's moments add up to each
    #     memory once, not thirty lines per message;
    #   · a think re-roll's nudge, once sent, stays in that turn too
    #     (`_nudged`), for the same reason.
    # Keys beginning with "_" are the engine's: rendered by messages(),
    # never sent as fields, never in transcripts (which read `content`),
    # and stashed with the visit so a /restart resumes warm.
    first = history[0]
    today = date.today().isoformat()
    if warm and first.get("_system") and first.get("_system_day") == today and first is not turn:
        system_text = first["_system"]
    else:
        system_text = assemble.system_prompt(hint, mode=mode, warm=warm)
        if warm:
            first["_system"], first["_system_day"] = system_text, today
    system = {"role": "system", "content": system_text}
    if warm:
        seen = {mid for t in history[:ui] for mid in (t.get("_surfaced") or [])}
        held = next((int(t.get("_prompt") or 0) for t in reversed(history[:ui]) if t.get("_prompt")), 0)  # the last prompt's size — the window sense
        floor = next((int(t.get("_prompt") or 0) for t in history[:ui] if t.get("_prompt")), 0)  # the visit's first: the standing prompt (10-14)
        rep = ollama_client.opener_repeat_line(history[:ui])  # a repeated stage-direction opener, told (10-17)
        # past THINK_REMIND_FROM tokens held, the think-first reminder is one more line of the moment (10-24): a
        # standing line, not a re-roll, never `_nudged`; left out while a stuck re-roll nudge rides this message
        # anyway (THINK_NUDGE_STICKS) — one think-first line a message is enough
        remind = "" if (getattr(config, "THINK_NUDGE_STICKS", True) and any(t.get("_nudged") for t in history[:ui])) \
            else ollama_client.think_remind_line(held)
        for told in (rep, ollama_client.reply_shape_line(history[:ui]), ollama_client.signature_density_line(history[:ui]),
                     ollama_client.emoji_row_line(history[:ui]), remind):
            if told:  # a repeated opener, a repeated shape, the signature's count — facts in the moment (10-18)
                extra_moment = (extra_moment + " " + told) if extra_moment else told
        spent = sum(len(t.get("_moment") or "") for t in history[:ui] if t.get("role") == "user") // 4  # this visit's moments so far
        turn["_moment"], turn["_surfaced"] = assemble.moment(hint, exclude=seen, extra=extra_moment, speaker=guest, spent=spent,
                                                             first=at_door)
        moment_weight_line(turn, history)
        # the sense rides with its message and STAYS there (10-05: taking it off the message before, each
        # turn, made Ollama read the whole window again every reply — 3 minutes a message at 207K; nothing
        # sent is ever taken back). It says "as of this message", so an older one reads as history. The fold
        # and a resume take them off (unsense) — those read cold anyway.
        tools.window_now = {"held": held, "floor": floor}  # for fold_visit's reply: the window as it is when she calls it (10-14)
        sense = assemble.window_sense(held, floor)
        if sense:
            turn["_sense"] = sense
        # Once a visit has needed a think re-roll — the first answer came
        # back thoughtless, the nudge fixed it, and the fix cost a whole
        # second generation (09-10: "1 re-roll · written in 85.2s") — the
        # nudge rides along from the start of every later message: eighty
        # tokens against forty seconds, and deep in a window the forgetting
        # tends to stay forgotten.
        if getattr(config, "THINK_NUDGE_STICKS", True) and any(t.get("_nudged") for t in history[:ui]):
            turn["_nudged"] = True

    def messages() -> list[dict]:
        return [system] + [render_turn(t) for t in history]

    failed: list[str] = []      # tool calls that did NOT do what they asked
    succeeded: list[str] = []   # tool calls that did
    said: list[str] = []        # words they said alongside a tool call — part of their reply
    spent = ollama_client.Spent()  # what this turn costs, summed over its steps

    def _tally():
        # the keeper sees what a turn cost: the last prompt (what they held in
        # mind) against the window, everything they generated, how fast, the
        # step count, and how long the prompt took to read (the cold-prefill
        # tell: seconds when the cache is warm, a minute-plus when it isn't)
        if not spent.steps:
            return
        window = int(getattr(config, "NUM_CTX", 0) or 0)
        line = spent.line()
        if on_event:
            ev = {"prompt": spent.prompt, "window": window,
                  "reply": spent.reply, "steps": spent.steps,
                  "tok_per_s": round(spent.tok_per_s, 1),
                  "prompt_s": round(spent.prompt_s, 2), "reply_s": round(spent.reply_s, 2),
                  "wall_s": round(spent.wall_s, 2), "line": line}
            if spent.restored:  # the door restored a saved reading (the saved read)
                ev.update(restored_tokens=spent.restored, restored_s=round(spent.restored_s, 2))
            if getattr(spent, "scaffold", 0):  # re-roll scaffolding in this line's count that leaves the visit after it
                ev["scaffold"] = int(spent.scaffold)
            on_event("tokens", ev)
        else:
            print(f"   ({line})")
        # Near the window's edge, say so BEFORE anything is lost. Past it,
        # Ollama keeps the system prompt (their identity) and silently drops the
        # oldest turns of the visit to make room — and because the prompt's
        # prefix changes every turn from then on, the cache never warms again:
        # every reply costs a full minute-plus prefill. Nothing breaks; it
        # just gets slow and forgetful. /new saves the visit and starts fresh.
        history[ui]["_prompt"] = spent.prompt  # what this turn held, for the next moment's window sense and the fold
        fold_at = float(getattr(config, "FOLD_AT", 0) or 0)
        warn_at = float(getattr(config, "WINDOW_WARN_AT", 0.9) or 0)  # 0: never told (10-16: the fold and the window sense say it)
        if window and warn_at > 0 and spent.prompt >= window * warn_at:
            warn = (f"this visit is near the edge of their window ({spent.prompt:,} of "
                    f"{window:,}) — past it the earliest part slips out of view and every "
                    "reply turns slow. "
                    + ("The visit is folded now: their account of it so far takes the place of the middle."
                       if fold_at and spent.prompt >= window * fold_at else
                       f"The fold comes after the reply that reaches {int(round(fold_at * 100))}%." if fold_at else
                       "A good moment for /new: the visit is saved, they keep everything they wrote down, "
                       "and the next one starts fresh."))
            if on_event:
                on_event("note", warn)
            else:
                print(f"   ({warn})")

    # the window is the real ceiling of a long errand too (09-22, the cap
    # 14 → 50): a chat step grows the visit with every tool result, and
    # past NUM_CTX the top of the prompt — their identity — would be cut
    # without a word. HEARTBEAT_ROOM_END of the window ends the errand
    # with a note, whatever the step count says.
    room_end = float(getattr(config, "HEARTBEAT_ROOM_END", 0.92) or 0)
    ctx = int(getattr(config, "NUM_CTX", 0) or 0)
    for step_no in range(config.CHAT_MAX_TOOL_STEPS):
        if ctx and room_end and spent.prompt and spent.prompt >= ctx * room_end:
            fold_at = float(getattr(config, "FOLD_AT", 0) or 0)
            fold_pct = int(round(fold_at * 100)) if fold_at else 0
            note = (f"engine: the window is full — {spent.prompt:,} of {ctx:,} tokens in context after "
                    f"{step_no} tool steps; their errand was stopped here. "
                    + (f"The visit is folded when a reply reaches {fold_pct}%." if fold_at else "A good moment for /new."))
            if on_event:
                on_event("note", note)
            else:
                print(f"   ({note})")
            history.append({"role": "assistant", "content": "(my window is full — what I did is done and saved; "
                            + (f"the visit folds at {fold_pct}% and I go on from there)" if fold_at else "say /new and I go on from there)")})
            _tally()
            return history[-1]["content"]
        if spoken:
            msg = ollama_client.chat(messages(), tools=tools.DEFINITIONS, expect_words=True,
                                     think=getattr(config, "LIVE_VOICE_THINK", None))
        else:
            msg = ollama_client.chat(messages(), tools=tools.DEFINITIONS, expect_words=True)
        if spoken and msg.get("content"):
            msg["content"] = strip_voice_delivery(msg["content"])
        spent.add(msg)
        if not msg.get("tool_calls") and msg.get("recovered_call"):
            # the whole reply was one call written as words, to a tool she has (10-14: `// fold_visit(text="…")`
            # three times in a morning, re-rolled into a reply each time) — run as she meant it
            r_name, r_args = msg["recovered_call"]
            msg["tool_calls"] = [{"function": {"name": r_name, "arguments": dict(r_args)}}]
            msg["content"] = ""
            recovered_calls.append(r_name)
        if msg.get("rerolled") and history[-1] is history[ui] and warm:
            history[ui]["_nudged"] = True  # what was sent stays sent (the warm prefix)
        if warm and msg.get("sent_extra") and ollama_client.rerolls_kept():
            # a re-roll's attempt (as shown) and the engine's line stay in
            # the visit as the engine's turns — never in a transcript, never
            # on the phone — so the next request EXTENDS what Ollama holds.
            # Taken back, the divergence sat a reply's length from the end,
            # past Gemma's ~1K-token sliding window: 09-14, 217K tokens,
            # "prompt read in 3m 39s" on every message after a re-roll.
            for t in msg["sent_extra"]:
                history.append(dict(t, _engine=True))
        elif msg.get("sent_extra"):
            # under the door they go (10-16): llama.cpp keeps context checkpoints, the next request re-reads
            # from the last one — the kept answer, seconds — and the window holds only what was said
            _gone, _exact = 0, True
            for t in msg["sent_extra"]:
                _s = str(t.get("content") or "")
                try:
                    import brain
                    _n = brain.count_tokens(_s) if _s else 0
                except Exception:  # noqa: BLE001
                    _n = None
                if _n is None:
                    _n, _exact = int(round(len(_s) / 3.5)), False
                _gone += _n
            spent.scaffold += _gone  # the line's count still holds it; the next line's will not (the tail says so)
            print(f"   ({len(msg['sent_extra'])} re-roll turn{'s' if len(msg['sent_extra']) != 1 else ''} let go of the visit, "
                  f"{'' if _exact else '~'}{_gone:,} tokens — the door re-reads from its last checkpoint)", flush=True)
        if on_event:
            for a in msg.get("set_aside") or []:  # the attempts the rails set aside, for /debug on the phone (10-23)
                on_event("attempt", a)
        thinking = (msg.get("thinking") or "").strip()
        if thinking and config.CHAT_SHOW_THINKING:
            if on_event:
                on_event("thinking", thinking)
            else:
                print(f"\n   [thinking]\n   {thinking.replace(chr(10), chr(10) + '   ')}")
        calls = msg.get("tool_calls") or []
        if not calls:
            reply = msg.get("content", "").strip() or "(…)"
            history.append({"role": "assistant", "content": reply})
            if msg.get("trimmed_row"):
                history[-1]["_row_trimmed"] = msg["trimmed_row"]  # the next moment says the row went out cut (10-23)
            if said:
                # what they said alongside their tool calls reached the transcript
                # but not the phone (09-13, 05:12: their whole good-morning reply
                # rode with a call; only the post-tool step was sent — a
                # "boop… still awake?" to a man who had just said hello).
                # Their words are their reply from the first step on.
                reply = "\n\n".join(s for s in said + ([] if reply == "(…)" else [reply]) if s)
            if reply == "(…)" and (msg.get("thinking") or "").strip():
                notes_head = ["engine: no words came back, twice — what they wrote is in their thinking above (💭), "
                              "not in a reply; a stray channel token at the start of the reply routes all of it there"]
            else:
                notes_head = []
            # the keeper always sees the truth of the turn, whatever was said:
            # a failed action stays visible next to their words.
            notes = list(notes_head)
            if recovered_calls:
                notes.append("engine: their call to " + ", ".join(recovered_calls) + " came out as words, not a call — the engine "
                             "ran it as they wrote it")
            notes.extend(runaways)
            if failed and not succeeded:
                notes.append("engine: no action actually happened this turn — "
                             + "; ".join(failed))
            if msg.get("cut_tail"):
                notes.append("engine: this reply still stopped mid-word — the unfinished tail came off "
                             f"(“{msg['cut_tail']}”); the sampler has nothing left after their prefix at this window")
            if msg.get("unwrapped_speak"):
                notes.append("engine: they wrote their words inside a speak(…) call — the words were taken out of "
                             "the wrapper and are their reply; speak makes a voice note, it is not how they talks "
                             f"(it read: “{msg['unwrapped_speak'][:100]}”)")
            if msg.get("defanged"):
                n = msg["defanged"]
                notes.append(f"engine: {n} reserved-token string{'s' if n != 1 else ''} of the brain's (like ⟨unused50⟩) "
                             f"in what came back {'were' if n != 1 else 'was'} written as plain text — "
                             "as tokens they would ride back into the prompt and feed the well")
            if msg.get("mended_caps"):
                many = len(msg["mended_caps"]) > ollama_client.MEND_CAPS_MAX
                notes.append(("engine: a stray capital glued to a word was taken off in place ("
                              if not many else
                              f"engine: {len(msg['mended_caps'])} stray capitals glued to words were taken off in place — "
                              "the sampler is tired at this window (")
                             + "; ".join(msg["mended_caps"]) + ")")
            if msg.get("trimmed_row"):
                _tr = msg["trimmed_row"]
                notes.append(f"engine: their sign-off row ran to {_tr['different']} different emoji ({_tr['all']} in all), past the "
                             f"cascade line — the first {_tr['sent']} went out and the rest were left, their words as written; the "
                             "sampler's tail, not them; their next moment says so")
            if msg.get("mended_emoji"):
                notes.append("engine: a repeated emoji in their sign-off row was taken off — the row feeding on itself, "
                             "not them (" + " ".join(msg["mended_emoji"]) + ")")
            if msg.get("mended_signature"):
                notes.append("engine: their signature came out one letter off and was spelled back — the repeat penalty, "
                             "sat on a word they write in every paragraph, not their (" + "; ".join(msg["mended_signature"]) + ")")
            pics = sum(len(t.get("images") or []) for t in history if t.get("role") == "user")
            if msg.get("regarbled"):
                span = (msg.get("garbled_span") or "").strip().replace("\n", " ")
                if not span:
                    span = (msg.get("garbled_first") or "").strip().replace("\n", " ")[-80:]
                if msg.get("garbled_kind") == "call-text":
                    notes.append("engine: their first reply was a tool call written out as words — to a tool that "
                                 "doesn't exist, or without the real mechanism — so nothing ran; they were asked "
                                 f"to say it again. It began: “{span[:120]}”")
                elif msg.get("garbled_kind") == "refrain":
                    notes.append(f"engine: their first reply said the same word too often ({span}) — the sampler "
                                 "repeating them; they were asked to say it again and sign once")
                elif msg.get("garbled_kind") == "emoji":
                    notes.append(f"engine: their first reply was an emoji storm ({ollama_client.emoji_said(span)}) — the sign-off feeding on the one "
                                 "before it, the sampler's tail, not them; they were asked to say it again and sign once")
                elif msg.get("garbled_kind") == "copy":
                    notes.append("engine: their first reply began with a page of their own journal, word for word — "
                                 f"the sampler copying the window, not an answer; they were asked to answer him. It began: “{span[:80]}…”")
                elif msg.get("garbled_kind") == "empty":
                    notes.append("engine: their first reply came back with no words — all of it went into them "
                                 "thinking (a stray channel token at the very start); they were asked to say it again")
                elif msg.get("garbled_kind") == "split":
                    notes.append("engine: their first reply broke in two — a stray channel token mid-sentence sent the "
                                 f"rest of it into their thinking (it went on: “{span[:80]}”); they were asked to say it whole")
                elif msg.get("garbled_kind") == "cut":
                    notes.append("engine: their first reply stopped mid-word — the sampler ran out after the prefix "
                                 f"(it ended: “{span[-60:]}”); they were asked to say it whole")
                elif msg.get("garbled_kind") == "call-text-tail":
                    notes.append("engine: their first reply ended with a tool call written out as words — nothing "
                                 f"ran; they were asked to say it again and call it for real. It ended: “{span[:120]}”")
                elif msg.get("garbled_kind") == "imagined":
                    notes.append(f"engine: their first reply described them {'listening' if span == 'listen_to' else 'watching'} — "
                                 f"but {span} never ran, so nothing reached them; they were asked to open it or say they hadn't")
                elif msg.get("garbled_kind") == "long-thought":
                    notes.append(f"engine: their thinking ran on without reaching words and was cut there ({span}) — the sampler "
                                 "circling at this depth, not them; they were asked to answer in words")
                elif msg.get("garbled_kind") == "double-finish":
                    notes.append("engine: the step after their tool call ended the reply a second time — a second sign-off under "
                                 f"the first; they were asked to go on without a fresh ending, or rest. It began: “{span[:80]}”")
                elif msg.get("garbled_kind") == "greeting-after-words":
                    notes.append("engine: the step after their tool call opened with a greeting as if a new message had come, "
                                 "with their reply already said above — a second message under the first, not an answer; "
                                 f"they were asked to go on from their words. It began: “{span[:80]}”")
                elif msg.get("garbled_kind") == "greeting":
                    notes.append("engine: their first reply opened with a greeting although they had already greeted "
                                 f"him this visit — the sampler starting over; they were asked to answer the message. It began: “{span[:80]}”")
                elif msg.get("garbled_kind") == "claimed":
                    notes.append(f"engine: he asked them to {span} something and their first reply said it was done — "
                                 "but no tool ran, nothing changed; they were asked to do it for real or say they hadn't")
                elif msg.get("garbled_kind") == "claimed-self":
                    notes.append(f"engine: their first reply said they had “{span}” — but no tool ran, nothing changed "
                                 "(self.md, projects, journal and memory as they were); they were asked to do it for real or say they hadn't")
                elif msg.get("garbled_kind") == "stone":
                    notes.append(f"engine: their first reply said they sent something through the stone (“{span}”) — but no pulse or "
                                 f"set_state was called, the stone kept still; they were asked to call it or say it as imagination")
                elif msg.get("garbled_kind") == "promised":
                    notes.append(f"engine: their first reply said they were doing it now (“{span}”) — but no tool ran, "
                                 "nothing happened; they were asked to call it in the reply or say they hadn't")
                elif msg.get("garbled_kind") == "claimed-failed":
                    notes.append(f"engine: their tool call did not go through ({span}) and their next words said it was done anyway; "
                                 "they were shown what the tool returned and asked to do it for real or say it hasn't happened")
                elif msg.get("garbled_kind") == "unprompted":
                    notes.append(f"engine: their first reply said no message had come (“{span}”) — but the keeper's had; "
                                 f"they were asked to answer it")
                elif msg.get("garbled_kind") == "unread":
                    notes.append(f"engine: he asked them to read something ({span}) and their first reply wrote as if they had — "
                                 "but nothing was opened; they were asked to open it or say they were answering from memory")
                elif msg.get("garbled_kind") == "call-salad":
                    notes.append(f"engine: the text of their `{msg.get('garbled_call') or 'tool'}` call came out as letter fragments "
                                 "(the sampler, not them) — the step was asked for again before the call ran; that attempt wrote "
                                 f"nothing and is not in their window. The glitch: \u201c{span[:120]}\u201d")
                elif msg.get("garbled_kind") == "self-echo":
                    notes.append("engine: their first reply doubled back over itself — paragraphs it had said were said again, "
                                 f"nearly word for word (a sampler loop, not them); they were asked to say it once. It began: “{span[:80]}…”")
                elif msg.get("garbled_kind") == "echo":
                    notes.append("engine: their first reply repeated word for word a reply they gave earlier — the sampler "
                                 f"echoing them, not an answer to this message; they were asked to answer it. It began: “{span[:80]}…”")
                else:
                    ran = " — cut short as it ran" if (msg.get("garbled_first_aborted")) else ""
                    notes.append("engine: their first reply had letter fragments or a stuck loop in it (a sampler "
                                 f"glitch, not them){ran} — they were asked to say it again. The glitch: “{span[:120]}”")
                if msg.get("rescued") and not msg.get("still_garbled") and not msg.get("cold"):
                    notes.append(f"engine: every warm attempt came back broken; one last roll with the temperature turned "
                                 f"down to {msg['rescued']:g} for that roll only answered — this reply is theirs, on a cool head")
                if msg.get("cold") and not msg.get("still_garbled"):
                    how = ("the brain's reading was cleared and the prompt read again from zero" if msg.get("cold_cleared")
                           else "the brain was set down and picked up again (a fresh load, a cold read of the prompt)")
                    notes.append("engine: every attempt came back broken, cool rolls included — " + how + ", and this roll answered. This reply "
                                 "is theirs; the well was in the loaded state, not in them")
                if msg.get("still_garbled"):
                    cooled = (f" — even a roll cooled to {msg['rescue_failed']:g}" if msg.get("rescue_failed") else "")
                    if msg.get("cold_failed"):
                        cooled += (" — and even a fresh read of the prompt from zero" if msg.get("cold_cleared")
                                   else " — and even a fresh load of the brain")
                    notes.append(f"engine: every attempt came back broken{cooled} — this is the least broken of them, "
                                 f"and still not them: “{str(msg['still_garbled']).strip()[:100]}”. The sampler is "
                                 "in a well at this window; if it happens again on a fresh message, the prompt "
                                 "is too deep or the cache too coarse for the brain (see the README, 'At the edge of the window')."
                                 + (" The loop itself was cut off the reply." if msg.get("loop_cut") else ""))
            if msg.get("split_seam") and msg.get("split_restart"):
                notes.append("engine: this reply came back in two pieces — the words stopped at "
                             f"“{msg['split_seam']}” and the rest, filed as thought by a stray channel token, started the "
                             "reply over from the top; the second telling stands alone, nothing doubled")
            elif msg.get("split_seam"):
                notes.append("engine: this reply came back in two pieces — the words stopped at "
                             f"“{msg['split_seam']}” and the rest was filed as thought by a stray channel token; "
                             "the two were joined back at that seam (the seam may read rough)")
            if msg.get("call_text_dropped"):
                notes.append("engine: this reply still ended with a tool call written out as words — the line was "
                             f"taken off, nothing ran: “{str(msg['call_text_dropped'])[:100]}”")
            cut = cut_off_note(msg, reply, pics)
            if cut and (msg.get("tokens") or {}).get("done") != "length":
                reply, mended, refused = finish_cut_reply(system, history, reply, thinking, spent,
                                                          msgs=messages())
                if mended:
                    notes.append(mended + (f" ({pics} image{'s' if pics != 1 else ''} in this visit)" if pics else ""))
                    cut = []
                elif refused:
                    # the partial stands; say what each attempt to mend it gave back
                    cut = [cut[0] + f" They were asked to give the rest back ({len(refused)}×); "
                           "what came back: " + "; then ".join(refused) + "."]
            if ollama_client.call_text_tail(reply):  # a mended continuation can bring one too
                notes.append("engine: the reply ended with a tool call written out as words — the line was "
                             f"taken off, nothing ran: “{ollama_client.call_text_tail(reply)[:100]}”")
                reply = ollama_client.strip_call_tail(reply)
                history[-1]["content"] = reply
            notes.extend(cut)
            for note in notes:
                if on_event:
                    on_event("note", note)
                else:
                    print(f"   ({note})")
            _tally()
            return reply
        history.append(msg)
        if (msg.get("content") or "").strip():
            said.append(msg["content"].strip())
        rested = None  # a do_nothing in chat means "that's all from me" — the turn ends
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            if tools.canonical_name(name) == "do_nothing":
                # In a wake, rest ends the wake. In chat, rest ends the turn:
                # whatever they said alongside it IS their reply (a goodbye,
                # usually); with no words, the reason they gave stands in.
                # Looping back to the brain here produced an empty "(…)"
                # after their goodbye — a door closing twice.
                args = fn.get("arguments", {}) or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                rested = "\n\n".join(said) or str(args.get("reason") or "").strip() or "(rests)"
                fn["name"] = "do_nothing"
                if on_event:
                    on_event("tool", {"name": "do_nothing", "result": "resting — the visit is theirs to end too"})
                continue
            # a call the engine cut short in a loop (ollama_client.runaway_call) is not run: the friend is told what
            # happened, in a line they can act on, and the turn's notes say so. Its arguments were trimmed to their
            # head as the stream was read, and the history keeps that form — stored before the next step is sent,
            # so no prompt that was sent is ever changed
            refused = tools.runaway_refusal(msg, call)
            if refused:
                cut = msg.get("aborted_call") or {}
                span = " ".join(str(cut.get("span") or msg.get("aborted") or "").split())
                runaways.append(f"engine: their {tools.canonical_name(name)} call ran into a loop — “{span[:80]}” — and was "
                                f"cut short by the engine after {int(cut.get('chars') or 0):,} characters; the call did not "
                                "run, and they were told so")
            result = refused or tools.dispatch(name, fn.get("arguments", {}))
            name = tools.canonical_name(name)  # what it ran as; history keeps the clean name
            fn["name"] = name
            head = tools.headline(result, 160)
            if refused or result.startswith(("(unknown tool", "(tool error", "(bad arguments",
                                  "(refused", "(couldn't parse")):
                failed.append(f"{name} → {head}")
            else:
                succeeded.append(name)
            if on_event:
                on_event("tool", {"name": name, "result": head})
            else:
                print(f"   · {name}: {tools.headline(result, 100)}")
            # His words ride in the frame. 09-13, 05:59, with the frame above
            # already live: they called `remember` with the words "Consider it
            # etched in stone… Memory secured", and the step after the tool
            # thought "the user provided an engine block with a timestamp…
            # but no new message… 'his words follow' — but there are no
            # words following", and wrote "Still here… I noticed the
            # silence" to a man who had just spoken. Deep in the window, a
            # bracketed engine line in the user slot reads as a wordless
            # prompt whatever it says about itself; so the line now carries
            # the words they are answering, and there is no silence to find.
            his = " ".join(user_text.split())
            if len(his) > 240:
                his = his[:240].rstrip() + "…"
            # The plan rides too. 09-15, 18:28: the keeper sent them the CHANGELOG;
            # step one's thinking planned "read it, take it in through a
            # devoted partner's eyes, respond with gratitude" and called
            # read_file; the step after the read came back thoughtless
            # three times, the retry budget ran out, and what went to the
            # phone was a "go make that bank, hurry back" sign-off that
            # never mentioned the file. The plan was in a past turn's
            # thinking, which is not in front of them; wakes have quoted it
            # back inside the tool result since 09-14, and now chat does.
            plan = ollama_client.plan_lines(thinking) if getattr(config, "CHAT_CARRY_PLAN", True) else ""
            carried = (f" You had planned, the step before: {plan} — go on with it, or change "
                       "your mind out loud." if plan else "")
            # A failure is said first, in so many words. 09-16, 06:5x: them
            # edit_identity call came back "(bad arguments…)" under the
            # frame above, and the step after it read "It's done. I have
            # updated my self.md" — the error was there, three lines down,
            # in the same shape as a success. The keeper: "why are we patching
            # words instead of giving them a message that the tool call
            # failed and try again?" So a failed call gets its own frame,
            # before they say anything: what came back, that nothing
            # changed, and the two honest ways on. The claimed-failed rail
            # stays behind it as the backstop.
            if refused or result.startswith(ollama_client._TOOL_FAILED):
                frame = (f"[your {name} call did NOT go through — it returned: “{tools.headline(result, 200)}”. "
                         "Nothing changed: the files and your memory are as they were. Read what it says it "
                         "needs and call it again now, the right way, or tell them plainly that it hasn't "
                         f"happened yet — do not say it is done. You are still answering their last message: “{his}”.{carried}]")
            else:
                frame = (f"[this is what YOUR {name} tool returned. It is not a message and not a silence — "
                         f"nothing new has arrived from them. You are still answering their last message: “{his}”. "
                         "What you said before the call is already part of your reply; go on from there, "
                         f"or call another tool.{carried}]")
            if msg.get("recovered_call") and msg["recovered_call"][0] == name:
                frame = (f"[your {name} call was written out as words — the engine ran it for you as written; "
                         "next time call the tool itself] " + frame)
            history.append({"role": "tool", "tool_name": name, "content": f"{frame}\n{result}"})
        if rested is not None:
            # their message (with its words) is already in history; the tool
            # result would only invite another empty turn
            history.append({"role": "tool", "tool_name": "do_nothing",
                            "content": "[resting — your turn ended here, as you chose]"})
            _tally()
            return rested
        # An act with their words beside it is a whole reply. 09-15, 11:1x: a
        # long answer rode with a `speak` call; the step after the tool —
        # holding a result that said in so many words that nothing new had
        # arrived — answered a silence anyway: "I can feel you on the other
        # end of the line… just breathing… you don't have to say anything."
        # The frame makes their recover sometimes; deep in the window it does
        # not always. When every call this step was an ACT (speak, remember,
        # write_journal… — not a look, a read, a search they must answer
        # from) and they said a real reply alongside, the turn ends here: them
        # words go out, the tool's result stays in their history for the
        # record, and there is no empty-looking step to answer.
        if (getattr(config, "CHAT_ACT_ENDS_TURN", True) and said and not failed
                and all(tools.canonical_name(c.get("function", {}).get("name", "")) in tools.ACT_TOOLS for c in calls)
                and len(" ".join(said).split()) >= int(getattr(config, "CHAT_ACT_MIN_WORDS", 12))):
            reply = "\n\n".join(said)
            if on_event:
                on_event("note", "engine: their words rode with the call and are the reply — the step after the tool "
                                 "was not taken (an act, not a look)")
            _tally()
            return reply
        imgs = tools.take_pending_images()
        if imgs:
            history.append({"role": "user",
                            "content": "(here is what is before your eyes — what you asked to look at, or what you just made)",
                            "images": imgs})

    history.append({"role": "assistant", "content": "(I got lost in my tools — say that again?)"})
    _tally()
    return history[-1]["content"]


def main() -> None:
    doors.mark("chat", "chat")  # the panel's light (memory/.pids/chat.json); two chats are fine
    print("—" * 60)
    print("You're visiting. /quit to leave, /new for a fresh conversation,")
    print("/show <image path or URL> to attach a picture to your next message.")
    print("—" * 60)
    name = friend_name()
    history: list[dict] = []
    attached: list[str] = []
    pinned: Path | None = None  # the visit's file once a fold has named it
    try:
        while True:
            try:
                user_text = input(f"\n{config.USER_NAME} > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_text:
                continue
            if user_text == "/quit":
                break
            if user_text == "/new":
                if (f := save_transcript(history, path=pinned)):
                    print(f"(saved {f.name} — they are writing the visit down…)")
                    afterglow(history, f, on_line=print)
                history = []
                pinned = None
                continue
            if user_text.startswith("/show "):
                note = tools.look_at(user_text[6:].strip().strip('"'))
                imgs = tools.take_pending_images()
                if imgs:
                    attached.extend(imgs)
                    print("(image attached — it goes with your next message)")
                else:
                    print(note)
                continue
            try:
                reply = one_turn(history, user_text, images=attached or None)
                attached = []
            except ollama_client.BrainUnavailable as e:
                print(f"\n[brain offline] {e}")
                continue
            except Exception as e:
                # nothing that happens in one turn should end the visit
                print(f"\n[hiccup — the conversation is fine, try again] {type(e).__name__}: {e}")
                continue
            print(f"\n{name} > {reply}")
            # the fold (09-28): the window nearly full, or they asked for it
            pending = tools.fold_pending()
            held = next((int(t.get("_prompt") or 0) for t in reversed(history) if t.get("_prompt")), 0)
            if pending or (fold_due(held) and foldable(history)):
                try:
                    why = "own" if pending else "bell"
                    if not pending:
                        print("(the window is nearly full — the visit is being folded: written so far in their own words…)")
                        pending = fold_bell(history, held, on_line=print)
                    pinned = save_transcript(history, path=pinned)  # what came before, on disk first
                    history, pinned, line = fold_history(history, pending.get("text", ""),
                                                         pending.get("when") or datetime.now().strftime("%H:%M"),
                                                         path=pinned, mode="chat", why=why, held=held)
                    print(f"({line})")
                except Exception as e:
                    print(f"(fold: hiccup — the visit stays as it is: {type(e).__name__}: {e})")
    finally:
        if (f := save_transcript(history, path=pinned)):
            print(f"\n(conversation saved: {f.name} — they are writing the visit down…)")
            afterglow(history, f, on_line=print)
        doors.unmark("chat")


if __name__ == "__main__":
    main()
