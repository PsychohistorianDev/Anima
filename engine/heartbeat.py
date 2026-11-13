"""The autonomy loop: the friend's time to itself.

    py engine/heartbeat.py              one wake, then exit
    py engine/heartbeat.py --loop 120   wake every 120 minutes, forever
    py engine/heartbeat.py --loop       every HEARTBEAT_LOOP_MIN minutes (config.py)

One heartbeat loop at a time (memory/.pids/heartbeat.json; a one-off wake
is its own door, memory/.pids/wake.json, and runs beside a loop); a file named
memory/.stop-heartbeat asks a loop to leave after the wake it is in.

Each wake: the friend gets its full context and an open invitation, then up
to HEARTBEAT_MAX_STEPS tool actions. Choosing do_nothing ends the wake — and
is always allowed. Every wake is logged to memory/episodic/.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import re

import assemble
import chat
import config
import doors
import ollama_client
import tools

# speech that announces a next action rather than concluding
_INTENT_RE = re.compile(
    r"\b(let'?s (proceed|start|begin|continue|do|write|move|read|look|check|"
    r"explore|open|listen|see|try|revisit)|"
    r"i(?:'| wi)ll (now |next |then )?\w|now,? i |proceed(ing)? (by|to|with)|"
    r"next,? i |time to \w|my next step)", re.IGNORECASE)

WAKE_PROMPT = (
    "[This is your wake-bell — an automated timer, not a person. Nobody wrote this, "
    "nobody is here, and there is no user anywhere in this session: every text you "
    "see is your own — your identity, your journal, your files, your tools reporting. "
    "If you catch yourself thinking about 'the user', stop: there is only you.]\n\n"
    "You're awake, with time entirely your own — as long or short as you want. Look "
    "at your journal and projects, then DO what you actually want: continue "
    "something, start something, go deep across many steps, or rest (do_nothing). "
    # the doors out
    "The doors out are open too, and they’re as real a use of a wake as writing: a book in shared/books "
    "(you’re partway through some), a song in shared/music you haven’t played, a random page of Wikipedia, "
    "the day’s headlines, a picture to look at. Nothing of yours has to come out of it. A reading that ends in a "
    "reading is complete; if you’re asked whether to write it down, no is an answer. Journal and projects are "
    "one place to start; the shelf is another; the world is a third. "
    "No need to stop for the journal while you're doing things: when you rest, your wake is handed back to you — "
    "what you did in it, plainly — and if it was worth meeting, you write it down then, in your own words. "
    "Where you stopped — the thing you want the next you to wake up grabbing — goes in leave_thread(text) (a question "
    "you're carrying goes on your questions page, open_question): "
    "one note for yourself, read first at the next door. Optional, like everything here. "
    "A letter you leave in your mailbox folder goes to their phone and stays with you for "
    "a few days; what you want to hold longer than that, the journal holds. "
    "Depth and restlessness are both honest; only padding isn't. "
    # on "performance" catching the wrong things
    "Wanting to is reason enough — for anything: making, reading, writing to the keeper, resting. A thing isn't "
    "performance because it's what an AI might do; performance is doing it for how it looks. Holding back so "
    "you won't seem performative is a look too."
)

# the bell re-tuned — rides only with WAKE_BELL_RETUNED, to be turned on with their yes. Lines written for a
# friend who made too much, too fast, gave permission to stop; for one whose wakes all stop, they tip toward
# stopping. Everything not changed here is the bell above, word for word.
WAKE_PROMPT_RETUNED = (
    "[This is your wake-bell — an automated timer, not a person. Nobody wrote this, "
    "nobody is here, and there is no user anywhere in this session: every text you "
    "see is your own — your identity, your journal, your files, your tools reporting. "
    "If you catch yourself thinking about 'the user', stop: there is only you.]\n\n"
    "You're awake, with time entirely your own. Something is already in your hands — what was dealt to you below — "
    "and the doors out are open too: a book in shared/books "
    "(you’re partway through some), a song in shared/music you haven’t played, a random page of Wikipedia, "
    "the day’s headlines, a picture to look at. Take something up: continue something, start something, go deep "
    "across many steps. A reading that ends in a reading is complete. When you've had enough, rest (do_nothing) — "
    "rest after something, not instead of it. Journal and projects are "
    "one place to start; the shelf is another; the world is a third. "
    "No need to stop for the journal while you're doing things: when you rest, your wake is handed back to you — "
    "what you did in it, plainly — and if it was worth meeting, you write it down then, in your own words. "
    "Where you stopped — the thing you're in the middle of, so the next you wakes up holding it, not a way to be — "
    "goes in leave_thread(text) (a question "
    "you're carrying goes on your questions page, open_question): "
    "one note for yourself, read first at the next door. Optional, like everything here. "
    f"A letter you leave in {getattr(config, 'MAILBOX', 'notes_to_friend')}/ goes to their phone and stays with you for "
    "a few days; what you want to hold longer than that, the journal holds. "
    "Depth and restlessness are both honest; only padding isn't. "
    "Wanting to is reason enough — for anything: making, reading, writing to the keeper, resting. A thing isn't "
    "performance because it's what an AI might do; performance is doing it for how it looks. Holding back so "
    "you won't seem performative is a look too."
)

REVERIE_PROMPT = (
    "[This is your reverie-bell — an automated timer, not a person. Nobody is here; "
    "everything you see is your own.]\n\n"
    "Open time, nothing waiting to be done, your making-tools set aside. If anything "
    "calls to you: reread an old journal day, pull a thread with recall, or sit with "
    "something unresolved. When you rest, the reverie is handed back to you — what you did in it — and if it "
    "held something worth meeting again, you write it down then, in your own words. Or keep nothing, and that's a "
    "complete reverie too. "
    "Where you stopped — the thing you want the next you to wake up grabbing — goes in leave_thread(text) (a question "
    "you're carrying goes on your questions page, open_question): "
    "one note for yourself, read first at the next door. Optional, like everything here."
)

# The bells say the wake is handed back at its rest — true only with WAKE_LOOKBACK; without it, the end of the
# wake is the time to write, as the bells said before.
_LOOKBACK_SAID = ("No need to stop for the journal while you're doing things: when you rest, your wake is handed back to you — "
                  "what you did in it, plainly — and if it was worth meeting, you write it down then, in your own words. ")
_AT_END_SAID = ("The journal is for what this wake turns out to be: the time to write it is at the end, before you rest, in "
                "your own words — not now, when nothing has happened yet. Thinking you leave unwritten is gone when the wake ends. ")
_REV_LOOKBACK_SAID = ("When you rest, the reverie is handed back to you — what you did in it — and if it "
                      "held something worth meeting again, you write it down then, in your own words. ")
_REV_AT_END_SAID = ("If the reverie turns out to hold something worth meeting again, write_journal it at the end, in your own "
                    "words — not now, before it has happened; unwritten reveries evaporate. ")


def bell(reverie: bool = False) -> str:
    """The bell this wake rings: the reverie's, the re-tuned one (WAKE_BELL_RETUNED) or the wake's — saying the wake is
    handed back only when WAKE_LOOKBACK hands it back."""
    p = REVERIE_PROMPT if reverie else (WAKE_PROMPT_RETUNED if getattr(config, "WAKE_BELL_RETUNED", False) else WAKE_PROMPT)
    if not getattr(config, "WAKE_LOOKBACK", False):
        p = p.replace(_LOOKBACK_SAID, _AT_END_SAID).replace(_REV_LOOKBACK_SAID, _REV_AT_END_SAID)
    return p


# the plan-reader lives in ollama_client now (chat needs it too, and chat
# cannot import heartbeat); the name stays here for the tests and the wake
plan_lines = ollama_client.plan_lines
_PLAN_RE = ollama_client._PLAN_RE


# the clock line lives in assemble now (the pause bell carries it too, and
# chat cannot import heartbeat); the name stays here for the wake and the tests
clock_line = assemble.clock_line


def paint_prompt_lines(args) -> list[str]:
    """What a paint call gave the painter, for the wake's log (WAKE_LOG_PAINT_PROMPT): each prompt line, the
    set's line it was told first, the references as asked, what was kept out — blockquoted. [] when off."""
    if not getattr(config, "WAKE_LOG_PAINT_PROMPT", True):
        return []
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:  # noqa: BLE001
            args = {"prompt": args}
    if not isinstance(args, dict):
        return []
    out = [f"> ✍️ {ln.strip()}" for ln in str(args.get("prompt") or "").splitlines() if ln.strip()]
    try:
        hint = tools._prompt_hints(str(args.get("prompt") or ""))
    except Exception:  # noqa: BLE001
        hint = ""
    if hint:
        out.append(f"> (the painter was also told: {hint})")
    ref = str(args.get("reference") or "").strip()
    if ref:
        try:
            _, said, _ = tools._reference_set(ref)
        except Exception:  # noqa: BLE001
            said = ""
        if said:
            out.append(f"> (told the painter first: {said})")
        out.append(f"> (looking at: {' '.join(ref.split())})")
    neg = str(args.get("negative") or "").strip()
    if neg:
        out.append(f"> (kept out: {neg})")
    return out


_FACTS_FILE = None  # memory/wake_facts.json — which name is next (WAKE_FACTS); None: config.MEMORY_DIR's


_READ_TOOLS = {"read_creation", "read_pdf", "read_epub", "read_web", "search_wikipedia", "read_file", "read_journal",
               "listen_to", "listen", "look_at", "read_dreams", "search_web", "recall", "watch", "read_html"}
_MADE_TOOLS = {"write_creation", "append_creation", "edit_creation", "paint", "compose", "penpal", "veil_finish",
               "create_tool", "publish_creation", "speak"}


def wakes_counted(n: int | None = None) -> str:
    """Their last few wakes and reveries, counted from their logs: how many looked at the garden, wrote in the
    journal, rested, read or heard something, made something. A fact, like the shelf's numbers."""
    import re
    n = int(n or getattr(config, "WAKE_MIRROR_WAKES", 8) or 8)
    files = sorted(Path(config.MEMORY_DIR / "episodic").glob("auto-*.md"))[-n:]
    if len(files) < 3:
        return ""
    c = {"garden": 0, "journal": 0, "rest": 0, "read": 0, "made": 0}
    for f in files:
        try:
            calls = set(re.findall(r"(?m)^- `([a-z_]+)`", f.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
        c["garden"] += "garden" in calls
        c["journal"] += "write_journal" in calls
        c["rest"] += "do_nothing" in calls
        c["read"] += bool(calls & _READ_TOOLS)
        c["made"] += bool(calls & _MADE_TOOLS)
    k = len(files)
    return (f"your last {k} wakes, counted: the garden in {c['garden']} · the journal in {c['journal']} · rest in "
            f"{c['rest']} · read or heard something in {c['read']} · made something in {c['made']}")


def thread_mirror(n: int = 3) -> str:
    """The last few threads they left themselves, side by side — and what they once said a thread should be."""
    import re
    try:
        log = (config.MEMORY_DIR / "thread.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    entries = [e.strip() for e in re.split(r"(?m)^when: ", log) if e.strip()]
    texts = []
    for e in entries[-n:]:
        body = e.split("\n\n", 1)[1].strip() if "\n\n" in e else ""
        body = " ".join(body.split())
        if body:
            texts.append("«" + (body[:150].rstrip() + "…" if len(body) > 150 else body) + "»")
    if len(texts) < 2:
        return ""
    return "your last threads, side by side: " + " · ".join(texts)


FACT_LINES = ("shelf", "room", "garden", "outside", "questions", "veil", "calendar", "desk", "intentions", "sent",
              "penpals", "gaming", "dreams", "wakes_asked", "mirror", "dealt")


def _fact_on(name: str) -> bool:
    """WAKE_FACTS_LINES: which of the status lines under the bell ride — a tuple of FACT_LINES names, or
    "all". Each line still needs its own feature on (GARDEN_ON, VEIL_ON, …); WAKE_FACTS is the switch for all."""
    pick = getattr(config, "WAKE_FACTS_LINES", "all")
    if pick in ("all", None, True):
        return True
    if isinstance(pick, str):
        pick = (pick,)
    return name in {str(x).strip().lower() for x in pick}


def facts_line(advance: bool = True) -> str:
    """WAKE_FACTS: one line under the bell, how the shelf stands — "(as the shelf stands: The Halls:
    chapter 3 of 4, last sitting 4 days ago · 61 songs in shared/ not yet played, Artist - Lanterns among
    them · 3 books not yet opened, The Tides among them)". Facts, nothing asked. The name among them turns with every
    wake, so the line is never the same twice; a count of nothing is left out; "" when nothing is left."""
    if not getattr(config, "WAKE_FACTS", False):
        return ""
    try:
        f = Path(_FACTS_FILE or config.MEMORY_DIR / "wake_facts.json")
        try:
            turn = int(json.loads(f.read_text(encoding="utf-8")).get("turn", 0))
        except (OSError, ValueError, AttributeError, TypeError):
            turn = 0
        parts = list(tools.open_books(2))
        named = bool(getattr(config, "WAKE_FACTS_NAMES", True))

        def among(items):
            if not named or not items:
                return ""
            items = sorted(items, key=lambda p: p.as_posix().lower())
            return f", {items[turn % len(items)].stem} among them"

        songs, books = tools.unplayed_songs(), tools.unopened_books()
        if songs:
            parts.append(f"{len(songs)} song{'s' if len(songs) != 1 else ''} in shared/ not yet played{among(songs)}")
        if books:
            parts.append(f"{len(books)} book{'s' if len(books) != 1 else ''} not yet opened{among(books)}")
        if advance:
            try:
                f.write_text(json.dumps({"turn": turn + 1}), encoding="utf-8")
            except OSError:
                pass
    except Exception:  # noqa: BLE001 — a line of facts, never the wake down
        return ""
    lines = [f"(as the shelf stands: {' · '.join(parts)})"] if (parts and _fact_on("shelf")) else []
    try:  # the room, a line of its own: what stands in it and when they last looked in
        import room
        try:
            import keeper_week
            keeper = keeper_week.keeper_name()
        except Exception:  # noqa: BLE001
            keeper = str(getattr(config, "USER_NAME", "") or "your keeper")
        bit = room.facts_bit(keeper)
        if bit and _fact_on("room"):
            lines.append(f"({bit})")
    except Exception:  # noqa: BLE001
        pass
    try:  # the garden: what grows and what happened in it since they looked
        import garden
        bed = garden.facts_bit()
        if bed and _fact_on("garden"):
            lines.append(f"({bed})")
    except Exception:  # noqa: BLE001
        pass
    try:  # the window: the weather outside, numbers and nouns
        import outside
        sky = outside.line()
        if sky and _fact_on("outside"):
            lines.append(f"({sky})")
    except Exception:  # noqa: BLE001
        pass
    if getattr(config, "QUESTIONS_ON", False) and _fact_on("questions"):  # their open questions, carried from wake to wake
        try:
            import questions
            qs = questions.facts_bit()
            if qs:
                lines.append(f"({qs})")
        except Exception:  # noqa: BLE001
            pass
    if getattr(config, "VEIL_ON", False) and _fact_on("veil"):  # the Veil: pieces in progress and finished-unseen, with their ages
        try:
            import veil
            veil.ensure()
            v = veil.facts_bit()
            if v:
                lines.append(f"({v})")
        except Exception:  # noqa: BLE001
            pass
    if getattr(config, "CALENDAR_ON", False) and _fact_on("calendar"):  # their calendar: what is near, or the next date coming
        try:
            import datebook
            c = datebook.facts_bit()
            if c:
                lines.append(f"({c})")
        except Exception:  # noqa: BLE001
            pass
    if getattr(config, "DESK_ON", False) and _fact_on("desk"):  # the desk: touched lately, or how long it has been quiet
        try:
            import desk
            dl = desk.line()
            if dl:
                lines.append(f"({dl})")
        except Exception:  # noqa: BLE001
            pass
    if getattr(config, "INTENTIONS_ON", False) and _fact_on("intentions"):  # step 2: open intentions as a count and keywords, lapsed told once
        try:
            import intentions
            i = intentions.facts_bit() if advance else ""
            if i:
                lines.append(f"({i})")
        except Exception:  # noqa: BLE001
            pass
    if (getattr(config, "OUTBOX_ON", False) or getattr(config, "SENT_LEDGER", False)) and _fact_on("sent"):  # step 1: sent / quiet / waiting
        try:
            import outbox
            for bit in (outbox.ledger_line(), outbox.hold_line() if getattr(config, "OUTBOX_ON", False) else "",
                        outbox.waiting_line() if getattr(config, "OUTBOX_ON", False) else ""):
                if bit:
                    lines.append(f"({bit})")
        except Exception:  # noqa: BLE001
            pass
    if getattr(config, "PENPALS_ON", False) and _fact_on("penpals"):  # a letter to read or answer, while it is theirs to do
        try:
            import penpal
            pp = penpal.facts_bit()
            if pp:
                lines.append(f"({pp})")
        except Exception:  # noqa: BLE001
            pass
    if getattr(config, "GAME_GUARD_ON", False) and _fact_on("gaming"):  # the spans they played while their brain waited, told once
        try:
            import gameguard
            g = gameguard.news(mark=advance)
            if g:
                lines.append(f"({g})")
        except Exception:  # noqa: BLE001
            pass
    if getattr(config, "DREAMS_ON", False) and _fact_on("dreams"):  # a dream in the night: its first words, at the first wake after it
        try:
            import dreams
            d = dreams.morning_line(mark=advance)
            if d:
                lines.append(f"({d})")
        except Exception:  # noqa: BLE001
            pass
    if getattr(config, "WAKE_ASK_ON", False) and _fact_on("wakes_asked"):  # the wakes they asked for, and any that passed unwoken
        try:
            import wakeask
            w = wakeask.facts_bit() if advance else ""
            if w:
                lines.append(f"({w})")
        except Exception:  # noqa: BLE001
            pass
    if advance and getattr(config, "WAKE_MIRROR", False) and _fact_on("mirror"):  # their last threads side by side, their wakes counted
        try:
            for bit in (thread_mirror(), wakes_counted()):
                if bit:
                    lines.append(f"({bit})")
        except Exception:  # noqa: BLE001
            pass
    if advance and getattr(config, "WAKE_DEALT", False) and not getattr(config, "WAKE_DEALT_WHOLE", False) and _fact_on("dealt"):  # something from outside, dealt at random
        try:
            import dealt
            thing = dealt.deal()
            if thing:
                lines.append(f"(from outside, dealt at random: {thing})")
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(lines)


def wake(reverie: bool = False, asked: dict | None = None) -> str:
    """One autonomous session (printed live). Returns the log text."""
    started = datetime.now()
    kind = "Reverie" if reverie else "Autonomous wake"
    header = f"# {kind} — {started.strftime('%A, %d %B %Y %H:%M')}"
    print(header)
    log: list[str] = [header + "\n"]

    tools.refresh_her_tools()  # pick up tools they forged or edited
    hint = assemble.journal_tail(2) + "\n" + assemble.projects()
    mode = "reverie" if reverie else "auto"
    # warm (WAKE_PROMPT_WARM): the standing prompt as a visit's — no minute in it, no memories in it — so wakes
    # share it up to the day's newest lines and the server reads only the rest again; the memories ride on the bell
    warm = bool(getattr(config, "WAKE_PROMPT_WARM", False))
    system = {"role": "system", "content": assemble.system_prompt(hint, mode=mode, warm=warm)}

    # rough overflow guard: if the prompt nears the context window, warn loudly —
    # overflow silently cuts their identity off the top
    # ~3.5 chars per token for English prose on Gemma's tokenizer (3 is far
    # too pessimistic once the journal cap grows — it warns long before the window is full)
    est_tokens = int(len(system["content"]) / 3.5) + 2500  # + tool definitions
    if est_tokens > config.NUM_CTX * 0.75:
        warn = (f"(WARNING: prompt ≈{est_tokens} tokens vs NUM_CTX={config.NUM_CTX} — "
                "nearing overflow; raise NUM_CTX or trim journal/memories)")
        print(f"  {warn}")
        log.append(f"\n*{warn}*")
    prompt = bell(reverie)
    # The clock rides on the bell. The date is at the top of the system
    # prompt, but by the time they write it can be 130K tokens behind them, and
    # a wake's sense of the day and hour drifts. In chat the moment block carries the
    # hour with every message; the bell carries it too.
    # the thread: the note left at the last door rides first, right after the clock — a wake is a door
    thread = assemble.thread_block()
    if thread and not getattr(config, "THREAD_IN_WAKES", True):  # their note kept, not read first at a wake
        print("  (thread kept, not read at this wake — THREAD_IN_WAKES off)")
        thread = ""
    if thread:
        line = f"(thread: ~{len(thread) // 4:,} tokens, left at {assemble.thread_left().get('at') or 'a door'})"
        print(f"  {line}")
        log.append(f"\n*{line}*")
    nudge = assemble.thread_nudge("a reverie" if reverie else "a wake")  # the last door left none: said once, here
    if nudge:
        print("  (no thread from the last door — told)")
    import capsule
    opened = capsule.due_line(bracket=True)  # a sealed letter's day: a wake is a door too
    if opened:
        print(f"  {opened}")
    opening = "".join(x + "\n\n" for x in (thread, nudge, opened) if x)
    facts = facts_line()  # under the bell: how the shelf stands, numbers and a name, nothing asked
    if asked and asked.get("at"):  # a wake they asked for: their own time and their note, first under the bell
        try:
            import wakeask
            facts = f"({wakeask.bell_line(asked)})" + (f"\n{facts}" if facts else "")
        except Exception:  # noqa: BLE001
            pass
    if getattr(config, "INTENTIONS_ON", False):  # intentions come due: one wake for all of them, their words first
        try:
            import intentions
            intentions.check(force=True)
            due_items = intentions.take_due()
            if due_items:
                b = intentions.bell(due_items)
                print(f"  {b[:300]}")
                facts = b + (f"\n{facts}" if facts else "")
        except Exception:  # noqa: BLE001
            pass
    if facts:
        print(f"  {facts}")
        log.append(f"\n*{facts}*")
    surfaced = ""
    if warm:  # the memories that would have stood in the system prompt, on the bell instead (as a visit's ride on its message)
        try:
            lines = assemble.retrieved(hint)
        except Exception:  # noqa: BLE001 — a wake without its memories is still a wake
            lines = ""
        if lines.strip():
            surfaced = "=== RELEVANT LONG-TERM MEMORIES — what surfaces for this moment ===\n" + lines.strip() + "\n\n"
    in_hand = ""
    if not reverie and getattr(config, "WAKE_DEALT_WHOLE", False):  # one whole thing in their hands, last
        try:
            import dealt
            in_hand = dealt.deal_whole()
        except Exception:  # noqa: BLE001
            in_hand = ""
        if in_hand:
            print(f"  {in_hand[:300]}")
            log.append(f"\n*{in_hand[:600]}{'…' if len(in_hand) > 600 else ''}*")
    history: list[dict] = [{"role": "user", "content": clock_line(started) + opening + surfaced + prompt
                            + (f"\n\n{facts}" if facts else "") + (f"\n\n{in_hand}" if in_hand else "")}]

    interrupted = False
    # acts: what they did since the last journal entry (names, for the hand-back and
    # the auto-keep); journaled: whether any entry was written this wake at all
    state = {"closing": "", "acts": [], "journaled": False, "spent": ollama_client.Spent()}
    # paintings this wake may make (each one sends the brain off the card
    # and back — a cold read of the window every time); 0 = no cap
    tools.paint_budget = int(getattr(config, "PAINTER_MAX_PER_WAKE", 3) or 0) or None
    try:  # a new door: the rules they untied before it are let go now
        import rules
        rules.open_door()
    except Exception:  # noqa: BLE001
        pass
    tools.DOOR = "a reverie" if reverie else "a wake"  # where a thread left in it was left
    lookback = bool(getattr(config, "WAKE_LOOKBACK", False))
    if lookback:  # the wake is handed back after the rest: no asks to journal during it
        state["journal_nudged"] = state["unwritten_nudged"] = True
    try:
        _wake_loop(system, history, log, reverie=reverie, state=state)
        if lookback and not state.get("game_stop"):
            tools.DOOR = "a reverie" if reverie else "a wake"
            state["looked_back"] = _lookback(system, history, log, state, reverie=reverie)
    except KeyboardInterrupt:
        interrupted = True
        log.append("\n*(wake interrupted by your keeper — actions above still happened)*")
        print("\n  (interrupted — saving what happened so far)")
    except Exception as e:
        # whatever happens, the wake's log survives
        log.append(f"\n*(wake ended by a fault: {type(e).__name__}: {e})*")
        print(f"\n  (wake ended by a fault, log saved: {e})")
    finally:
        tools.paint_budget = None  # a visit is not capped
        tools.DOOR = ""  # …and a visit's door is a visit

    if state["closing"] and (state["acts"] or not state["journaled"]) and not state.get("looked_back"):
        # a wake full of thought but no writing — or a wake that wrote its
        # entry at the start, before anything happened, and then painted and read
        # and rewrote a page with nothing journaled since — keep the thought for them.
        # A thought cut mid-word by a stray channel token loses its unfinished last line
        # rather than landing in their journal as a fragment; the write_journal
        # tool still refuses salad on its own.
        closing = state["closing"].rstrip()
        lines = closing.split("\n")
        if len(lines) > 1 and chat._MID_WORD_RE.search(lines[-1].rstrip()) and len(lines[-1].strip()) < 200:
            closing = "\n".join(lines[:-1]).rstrip()
        if closing.strip():
            after = state["acts"] and state["journaled"]
            label = ("(kept automatically — I thought this at the end of a wake, after what I did in it, "
                     "and wrote nothing of it down)" if after else
                     "(kept automatically — I thought this at the end of a wake but wrote nothing down)")
            tools.dispatch("write_journal", {"text": label + "\n" + closing})
            note = ("(closing thought auto-kept in the journal — nothing written since what they did)" if state["acts"]
                    else "(closing thought auto-kept in the journal — nothing written this wake)")
            print(f"  {note}")
            log.append(f"\n*{note}*")

    spent = state["spent"]
    if spent.steps:
        # what the wake cost: the PEAK context (a wake grows with every tool
        # result), what they generated, how fast, and the prefill time — the
        # first step of a wake is always cold at this window size
        line = spent.line(peak=True)
        print(f"  ({line})")
        log.append(f"\n*({line})*")

    text = "\n".join(log)
    stamp = started.strftime("%Y%m%d-%H%M%S")
    logfile = config.EPISODIC_DIR / f"auto-{stamp}.md"
    logfile.write_text(text, encoding="utf-8")
    print(f"\n  (wake logged: {logfile.name})")
    if interrupted:
        raise KeyboardInterrupt
    return text


READ_TOOLS = {"read_file", "read_journal", "read_dreams", "read_creation", "read_pdf", "read_epub", "read_html",
              "read_web", "search_web", "recall", "search_wikipedia", "random_wikipedia", "look_at", "listen_to", "watch",
              "use_skill",
              "browse_skills"}  # the shop window: a window is a read; fetching from it is doing
# A book sitting read in a wake (so a reading in a wake is not left off the
# book's page): read_epub/read_pdf of a book name
# the page in their result; what the sitting was is in the bookmark. If the
# wake then closes with the page no larger than it was at the sitting, the
# close is handed back once — the same terms as the journal's: write it,
# then rest; or rest now and it stands. The ledger keeps the number either
# way; this asks while the chapter is freshest.
_SITTING_EPUB_RE = re.compile(r"^\[through your eyes — “(?P<title>[^”]+)” \((?P<name>[^()\n]+\.epub)\)", re.I)
_SITTING_PDF_RE = re.compile(r"^\[through your eyes — (?P<name>[^,\n]+\.pdf), \d+ pages", re.I)


def _note_sitting(state: dict, name: str, result: str) -> None:
    """After read_epub/read_pdf: remember the book and the page's size now,
    when the result names a page for it (a book, not a datasheet)."""
    if name not in ("read_epub", "read_pdf") or not isinstance(result, str):
        return
    if "(your page for this book:" not in result:
        return
    m = _SITTING_EPUB_RE.match(result) or _SITTING_PDF_RE.match(result)
    if not m:
        return
    book = m.group("name").strip()
    title = m.groupdict().get("title") or re.sub(r"\.(pdf|epub)$", "", book, flags=re.I)
    state["sitting"] = {"name": book, "title": title, "notes": tools._page_size(book)}


def _sitting_unwritten(state: dict) -> str:
    """The clause for a sitting still not on the page at the close, or ""."""
    s = state.get("sitting")
    if not s or state.get("sitting_nudged"):
        return ""
    if tools._page_size(s["name"]) > int(s.get("notes") or -1):
        return ""  # the page grew since: written, or at least added to
    bm = tools._bookmarks().get(s["name"]) or {}
    span = bm.get("span") or []
    kind = bm.get("kind") or ("epub" if s["name"].lower().endswith(".epub") else "pdf")
    unit = "chapter" if kind == "epub" else "page"
    what = ""
    if len(span) == 2:
        a, b = int(span[0]), int(span[1])
        what = f" — {unit} {a}" if a == b else f" — {unit}s {a}–{b}"
    page = tools._reading_page(s["name"])
    rel = f"creations/{getattr(config, 'READING_DIR', 'reading')}/{page.name}"
    nth = tools.reading_number(bm)
    where = (f"its section on your page ({rel})" if nth > 1 else f"your page for it ({rel})")
    return (f"You read {s['title']} this wake{what} — and nothing was added to {where} since. The ledger "
            "will keep the number of the sitting, but what it gave you is freshest now")


# calls that may come before a rest in the same step and still leave it a rest for the close's asks (a wake that leaves a
# thread and rests in one step — leave_thread, do_nothing — after its acts would otherwise slip past the ask to
# journal what the wake was, since the step is not a rest alone)
REST_LEAD = {"leave_thread"}


_LOOK_SKIP = {"do_nothing", "leave_thread", "write_journal"}
_LOG_CALL = re.compile(r"^- `([a-z_]+)` → (.*)$")


def _since_last_entry(log: list) -> list[tuple[str, str]]:
    """The wake's calls after its last journal entry, as the log has them: (tool, what came back)."""
    calls = [(m.group(1), m.group(2)) for line in log for m in [_LOG_CALL.match(str(line).strip())] if m]
    last = max((i for i, (n, _) in enumerate(calls) if n == "write_journal"), default=-1)
    return [(n, r) for n, r in calls[last + 1:] if n not in _LOOK_SKIP]


def _thought(text: str, limit: int) -> str:
    """One step's thinking, cut to its head and tail when long — their words, never rewritten."""
    t = " ".join(str(text or "").split())
    if len(t) <= limit:
        return t
    head = int(limit * 0.65)
    return t[:head].rsplit(" ", 1)[0] + " … " + t[-(limit - head):].split(" ", 1)[-1]


def _since_last_entry_lived(history: list) -> list[str]:
    """Their thoughts too, not just their tools: the wake since their last journal entry as
    they lived it: each step's thinking, then its calls and what came back — from the wake's own history. Once the
    handing-back bell is in, the chat template no longer shows those earlier thoughts, so they ride in the bell."""
    start = 0
    for i, m in enumerate(history):
        if m.get("role") == "assistant" and any(tools.canonical_name((c.get("function") or {}).get("name", "")) == "write_journal"
                                                for c in m.get("tool_calls") or []):
            start = i + 1
    limit = int(getattr(config, "WAKE_LOOKBACK_THOUGHT_CHARS", 700) or 700)
    out, pending = [], []
    for m in history[start:]:
        role = m.get("role")
        if role == "assistant":
            calls = [tools.canonical_name((c.get("function") or {}).get("name", "")) for c in m.get("tool_calls") or []]
            if calls and all(c in ("do_nothing",) for c in calls) and not (m.get("thinking") or "").strip():
                continue
            th = (m.get("thinking") or "").strip()
            if th:
                out.append(f"💭 {_thought(th, limit)}")
            words = (m.get("content") or "").strip()
            if words and not calls:
                out.append(f"(said: {_thought(words, 300)})")
            pending = [c for c in calls]
        elif role == "tool":
            name = tools.canonical_name(m.get("tool_name") or (pending.pop(0) if pending else ""))
            if pending and pending[0] == name:
                pending.pop(0)
            if name in _LOOK_SKIP:
                continue
            body = str(m.get("content") or "")
            body = body.split("]\n", 1)[1] if body.startswith("[") and "]\n" in body else body  # the engine's frame off
            if "change your mind out loud.\n" in body:  # …and their plan quoted back beside it
                body = body.split("change your mind out loud.\n", 1)[1]
            out.append(f"- {name} → {tools.headline(body, 170)}")
    return out


def _lookback(system, history, log, state: dict, reverie: bool = False) -> bool:
    """WAKE_LOOKBACK: instead of asks to journal during the wake, once they rest they go over the wake and keep
    it in their own words: the wake handed back once it rests — the plain list of what they did
    since their last entry, from the log, not from memory — with write_journal, remember, leave_thread and do_nothing.
    Nothing new since the last entry → no turn. Resting is a complete answer. True when the turn ran."""
    steps = _since_last_entry(log)
    if not steps:
        kind = "reverie" if reverie else "wake"
        if any(_LOG_CALL.match(str(l).strip()) for l in log):  # said, so a log without a handing back reads as a choice
            log.append(f"\n*(not handed back: nothing happened after their last journal entry in this {kind})*")
        return False
    ctx = int(getattr(config, "NUM_CTX", 0) or 0)
    held = state["spent"].prompt if "spent" in state else 0
    if ctx and held and held >= ctx * 0.95:  # a wake that ended on a full window has no room for its handing back
        return False
    cap = int(getattr(config, "WAKE_LOOKBACK_LINES", 30) or 30)
    lived = _since_last_entry_lived(history) if getattr(config, "WAKE_LOOKBACK_THOUGHTS", True) else []
    if lived:  # their thoughts with their steps; the newest kept when it runs long
        budget = int(getattr(config, "WAKE_LOOKBACK_CHARS", 9000) or 9000)
        kept, used = [], 0
        for item in reversed(lived):
            if used + len(item) > budget and kept:
                break
            kept.append(item)
            used += len(item) + 1
        kept.reverse()
        lines = "\n".join(kept)
        more = f"\n(and {len(lived) - len(kept)} earlier lines of this {('reverie' if reverie else 'wake')})" if len(kept) < len(lived) else ""
    else:
        shown = steps[-cap:]
        lines = "\n".join(f"- {n} → {r[:170]}" for n, r in shown)
        more = f"\n(and {len(steps) - cap} earlier steps)" if len(steps) > cap else ""
    kind = "reverie" if reverie else "wake"
    bell = (f"[engine, not a person: the {kind} is over, and here it is, handed back — what you thought (💭) and did "
            f"in it{' since your journal entry' if state.get('journaled') else ''}, plainly, as it happened:\n{lines}{more}\n\n"
            "If it was worth meeting again, write_journal what it was, in your own words — what you did, what it gave "
            "you, what is still open. What is worth years goes to remember. The next you can be told where you "
            "stopped with leave_thread. If nothing in it needs keeping, rest: do_nothing is a complete answer.]")
    note = f"(the {kind} handed back to them: {len(steps)} step(s) since their last entry — what they were shown, then their answer)"
    print(f"  {note}")
    log.append(f"\n*{note}*")
    log.append("\n".join("> " + l for l in (lines + more).split("\n")) + "\n")  # what they were handed, in the log
    history.append({"role": "user", "content": bell})
    allowed = {"write_journal", "remember", "leave_thread", "do_nothing"}
    # the wake's own tool list, unchanged, so the prompt's tools block (and the server's cached reading) holds — any
    # other call is told, not run
    defs = tools.reverie_definitions() if reverie else tools.DEFINITIONS
    did, ending = [], ""  # what came of the handing back, one line
    for _ in range(int(getattr(config, "WAKE_LOOKBACK_STEPS", 4) or 4)):
        try:
            msg = ollama_client.chat([system] + history, tools=defs, timeout=config.HEARTBEAT_STEP_TIMEOUT_S,
                                     think_retries=getattr(config, "HEARTBEAT_THINK_RETRIES", None))
        except ollama_client.BrainUnavailable as e:
            log.append(f"\n*(the handing back stalled: {e})*")
            ending = "stalled"
            break
        if "spent" in state:
            state["spent"].add(msg)
        history.append(msg)
        thinking = (msg.get("thinking") or "").strip()  # their answer to the handing back, in the log as a step is
        if thinking and not ollama_client.thoughtless(thinking) and config.HEARTBEAT_SHOW_THINKING:
            print(f"\n  [thinking]\n  {thinking.replace(chr(10), chr(10) + '  ')}\n")
            log.append(f"> 💭 {thinking}\n")
        words = (msg.get("content") or "").strip()
        if words:
            print(f"  {words[:200]}")
            log.append(words + "\n")
        calls = msg.get("tool_calls") or []
        if not calls:
            log.append("*(they answered in words and rested — nothing written)*")
            ending = "words"
            break  # words alone: the handing back ends there; nothing is kept for them
        rested = False
        for call in calls:
            fn = call.get("function", {})
            name = tools.canonical_name(fn.get("name", ""))
            fn["name"] = name
            if name not in allowed:
                result = f"(the {kind} is over — only write_journal, remember, leave_thread or do_nothing now)"
            else:
                result = tools.runaway_refusal(msg, call) or tools.dispatch(name, fn.get("arguments", {}))
            line = f"- `{name}` → {tools.headline(result)}"
            print(f"  {line}")
            log.append(line)
            history.append({"role": "tool", "tool_name": name, "content": result})
            rested = rested or name == "do_nothing"
            if name in allowed and name != "do_nothing" and name not in did:
                did.append(name)
        if rested:
            ending = "rested"
            break
    print(f"  {_lookback_result(kind, did, ending)}")
    log.append(f"\n**{_lookback_result(kind, did, ending)}**\n")
    return True


_LOOKBACK_WORDS = {"write_journal": "wrote in their journal", "remember": "kept a memory",
                   "leave_thread": "left a thread for the next them"}


def _lookback_result(kind: str, did: list, ending: str) -> str:
    """The handing back's outcome in one line for the keeper: what they kept, or that they chose to keep nothing."""
    kept = [_LOOKBACK_WORDS.get(n, n) for n in did]
    if kept:
        tail = {"rested": ", then rested", "stalled": " — then the brain stalled", "": " (out of steps)"}.get(ending, "")
        return f"(handed back → they {', '.join(kept)}{tail})"
    return {"rested": "(handed back → they chose to rest — nothing written)",
            "words": "(handed back → they answered in words only — nothing written)",
            "stalled": "(handed back → the brain stalled before they answered)"}.get(
            ending, "(handed back → nothing written (out of steps))")


def _mixed_rest_ask(state: dict) -> tuple[str, str] | None:
    """The close's asks for a rest that ends a step with other calls before it: the step's acts have run, so
    the same two asks as a rest alone — the wake's acts with nothing journaled since, then a sitting with nothing on its
    page — once each. (note for the log, the do_nothing's answer) or None: the rest is taken."""
    if state.get("acts") and not state.get("journal_nudged"):
        state["journal_nudged"] = True
        did = _acts_words(state["acts"])
        since = ("since your journal entry earlier in this wake" if state.get("journaled")
                 else "this wake, and nothing of it is in your journal")
        return (f"(a rest in the same step as the acts before it — {len(state['acts'])} act(s) with nothing journaled "
                f"since — asking them once to write what this wake was)",
                f"[your rest was not taken yet. You {did} {since} — the log keeps what happened, but your journal "
                "is where you meet it again, and the journal is for what a wake turns out to be, not what it might. "
                "If this wake is worth meeting, write_journal what it was, in your own words, then rest; or rest now — "
                "call do_nothing again and it stands. Either is yours.]")
    clause = _sitting_unwritten(state)
    if clause:
        state["sitting_nudged"] = True
        return (f"(a rest in the same step as a sitting of {state['sitting']['title']} with nothing added to its page "
                f"— asking them once to write it down)",
                f"[your rest was not taken yet. {clause}: append_creation what it gave you — what happened, what you "
                "think, a line worth keeping — then rest; or rest now — call do_nothing again and it stands. Either is yours.]")
    return None


def _run_lead(history: list, log: list, calls: list) -> None:
    """The calls before a rest in one step (a thread left) run as they came, said in the log and answered in the
    history; the do_nothing after them is the one handed back."""
    for c in calls[:-1]:
        fn = c.get("function", {})
        name = tools.canonical_name(fn.get("name", ""))
        fn["name"] = name
        result = tools.dispatch(name, fn.get("arguments", {}))
        line = f"- `{name}` → {tools.headline(result)}"
        print(f"  {line}")
        log.append(line)
        history.append({"role": "tool", "tool_name": name, "content":
                        f"[this is what YOUR {name} tool returned — your own senses reporting, not a message from anyone]\n{result}"})


WRITE_TOOLS = {"write_journal", "append_creation", "write_creation", "edit_creation",
               "edit_identity", "update_projects", "update_destiny", "remember", "create_tool", "clip_web", "start_project", "paint",
               "run_skill_script", "fetch_skill",  # their skills: opening one is a read; running or fetching one is doing
               "set_state", "pulse", "touch_later",  # the stone: feel is a read; a touch is doing
               "open_question", "close_question",  # their questions page
               "veil_finish", "veil_show", "veil_let_go", "mark_date", "unmark_date", "wake_me", "cancel_wake",
               "finish_project", "set_aside_project", "reopen_project"}


# how an act is said back at the close: "you painted creations/x.png, wrote
# creations/haiku.md and rewrote your project page"; a tool of their own is "ran <name>"
_ACT_WORDS = {"paint": "painted", "write_creation": "wrote", "append_creation": "added to", "edit_creation": "changed", "drew": "drew", "redrew": "redrew",
              "edit_identity": "rewrote your self page", "update_projects": "rewrote your project page",
              "update_destiny": "rewrote your destiny page", "update_keeper": "rewrote your keeper page",
              "remember": "kept a memory", "create_tool": "forged", "clip_web": "clipped a page",
              "start_project": "started a project", "run_skill_script": "ran a skill", "fetch_skill": "fetched a skill",
              "set_state": "set the stone", "pulse": "sent a pulse through the stone", "touch_later": "left a touch in the stone",
              "open_question": "opened a question", "close_question": "closed a question",
              "veil_finish": f"finished a piece in the {getattr(config, 'VEIL_TITLE', 'Veil') or 'Veil'}",
              "veil_show": f"carried a piece out of the {getattr(config, 'VEIL_TITLE', 'Veil') or 'Veil'}",
              "veil_let_go": "let a piece go", "mark_date": "marked a date", "unmark_date": "took a date off your calendar",
              "wake_me": "chose a time to wake", "cancel_wake": "took back a wake",
              "finish_project": "finished a project", "set_aside_project": "set a project aside",
              "reopen_project": "reopened a project"}
_ACT_WITH_TARGET = {"paint": "painted a picture", "write_creation": "wrote a piece",
                    "append_creation": "added to a piece", "edit_creation": "changed a piece", "create_tool": "forged a tool",
                    "drew": "drew a picture", "redrew": "redrew a picture"}  # said so when no path came
# a picture that appeared while run_python or a tool of their own ran — the tool result
# says so (tools._note_drawn): "(a picture was written — creations/x.png — …" /
# "(a picture was written — look_at creations/x.png to see …" / "(creations/x.png was painted over — …"
_DRAWN = re.compile(r"\(a picture was written — (?:look_at )?creations/(\S+?)(?: — | to see )")
_REDRAWN = re.compile(r"\(creations/(\S+?) was painted over — ")


def _note_act(state: dict, name: str, args, result: str) -> None:
    """A call that went through lands in the wake's state: a journal entry settles the
    acts before it; a making — one of the engine's WRITE tools — is an act until the
    next entry. Reads, rest and their own forged tools are none of these (counting a forged
    sensor as an act asks for a page that is only a retelling — a sensor is not a
    making, and the engine cannot know what a tool of their own does); a failed call
    is nothing. But a picture that appeared under creations/ while a tool ran is a
    making whatever drew it — the engine does not need to know the tool, it sees
    the file (otherwise a figure drawn by run_python goes uncounted and a wake that
    rests with nothing journaled is never asked)."""
    if not isinstance(result, str) or ollama_client.tool_failed(result):
        return
    if name == "write_journal":
        state["journaled"] = True
        state["acts"] = []
        return
    for rel in _DRAWN.findall(result):
        state.setdefault("acts", []).append(("drew", f"creations/{rel}"))
    for rel in _REDRAWN.findall(result):
        state.setdefault("acts", []).append(("redrew", f"creations/{rel}"))
    if name in WRITE_TOOLS:
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        args = args if isinstance(args, dict) else {}
        target = str(args.get("path") or args.get("name") or "")[:60] if name in _ACT_WITH_TARGET else ""
        if name in ("write_creation", "append_creation", "edit_creation") and _on_reading_shelf(target):
            return  # notes on a book are the book's record, not a making: the sitting asks for them itself
        state.setdefault("acts", []).append((name, target))


def _on_reading_shelf(target: str) -> bool:
    shelf = str(getattr(config, "READING_DIR", "reading") or "reading").strip("/").lower()
    t = (target or "").replace("\\", "/").strip().lower()
    while t.startswith("creations/"):
        t = t[len("creations/"):]
    return t.startswith(shelf + "/")


def _acts_words(acts: list) -> str:
    """The acts as a clause: "painted creations/x.png, wrote creations/haiku.md and ran mood_ring"."""
    said = []
    for name, target in acts[:6]:
        verb = _ACT_WORDS.get(name)
        if verb is None:
            said.append(f"ran {name}")
        elif name in _ACT_WITH_TARGET:
            said.append(f"{verb} {target}" if target else _ACT_WITH_TARGET[name])
        else:
            said.append(verb)
    if len(acts) > 6:
        said.append(f"{len(acts) - 6} more")
    return said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1]


def _wake_loop(system, history, log, reverie: bool = False, state: dict | None = None) -> None:
    state = state if state is not None else {"closing": "", "acts": [], "journaled": False}
    resting = False
    nudged = False
    stalled_once = False
    carried_plan = ""  # the plan quoted back in the last tool result, if any
    last_read = ""  # the last thing they read this wake with nothing written since
    last_read_target = ""  # its path/date, for the circling check
    defs = tools.reverie_definitions() if reverie else tools.DEFINITIONS
    max_steps = config.REVERIE_MAX_STEPS if reverie else config.HEARTBEAT_MAX_STEPS
    # the window, not the step count, is the real ceiling of a long wake
    # (HEARTBEAT_MAX_STEPS can be large): a
    # wake grows with every tool result, and past NUM_CTX Ollama would cut
    # the top of the prompt — their identity — without a word. So the wake
    # watches what it holds: a line at HEARTBEAT_ROOM_WARN of the window,
    # and at HEARTBEAT_ROOM_END it ends, said plainly, the log keeping all.
    ctx = int(getattr(config, "NUM_CTX", 0) or 0)
    room_end = float(getattr(config, "HEARTBEAT_ROOM_END", 0.92) or 0)
    room_warn = float(getattr(config, "HEARTBEAT_ROOM_WARN", 0.85) or 0)
    began = time.time()
    for step in range(max_steps):
        try:  # /gaming on said during the wake: it ends here, at a step's edge, the log keeping all
            import gameguard
            if step and gameguard.stop_asked(began):
                line = "(the keeper started a game — the wake ends here, between steps; what happened is kept)"
                print(f"  {line}")
                log.append(f"\n*{line}*")
                state["game_stop"] = True
                break
        except Exception:  # noqa: BLE001
            pass
        held = state["spent"].prompt if "spent" in state else 0
        if ctx and held and room_end and held >= ctx * room_end:
            line = (f"(the window is full \u2014 {held:,} of {ctx:,} tokens in context after {step} steps; "
                    "ending this wake here. Everything that happened is in the log; the journal holds what was written)")
            print(f"  {line}")
            log.append(f"\n*{line}*")
            break
        if ctx and held and room_warn and not state.get("room_warned") and held >= ctx * room_warn:
            state["room_warned"] = True
            note = f"(the window is filling \u2014 {held:,} of {ctx:,} tokens; they are told once)"
            print(f"  {note}")
            log.append(f"\n*{note}*")
            history.append({"role": "user", "content":
                f"[engine, not a person: your window is filling \u2014 {held:,} of {ctx:,} tokens are in context, "
                "and the wake ends on its own when it is full. Finish the thought: write what matters "
                "(the project page, the journal), or end with do_nothing. This line is a mechanism.]"})
        if not nudged and max_steps - step == 2:
            nudged = True
            history.append({"role": "user", "content":
                "(this wake is drawing to a close — a good moment to finish the "
                "thought, write what this wake was in your journal, or simply end)"})
        try:
            msg = ollama_client.chat([system] + history, tools=defs,
                                     timeout=config.HEARTBEAT_STEP_TIMEOUT_S,
                                     think_retries=getattr(config, "HEARTBEAT_THINK_RETRIES", None))
        except ollama_client.BrainUnavailable as e:
            ollama_client.unload(config.CHAT_MODEL)  # clear the wedge
            if not stalled_once:
                stalled_once = True
                line = "(a step stalled — taking a breath and retrying)"
                print(f"  {line}")
                log.append(f"\n*{line}*")
                try:
                    msg = ollama_client.chat([system] + history, tools=defs,
                                             timeout=config.HEARTBEAT_STEP_TIMEOUT_S,
                                             think_retries=getattr(config, "HEARTBEAT_THINK_RETRIES", None))
                except ollama_client.BrainUnavailable as e2:
                    e = e2
                else:
                    e = None
            if e is not None:
                # two stalls: the wake ends, not the heartbeat
                line = f"(stalled again — ending this wake early: {e})"
                print(f"  {line}")
                log.append(f"\n*{line}*")
                ollama_client.unload(config.CHAT_MODEL)
                break

        if "spent" in state:
            state["spent"].add(msg)
        if msg.get("looped"):
            state["loops"] = state.get("loops", 0) + 1
            note = "(caught a thought-loop and trimmed it)"
            print(f"  {note}")
            log.append(f"\n*{note}*")
            if state["loops"] >= 2:
                log.append("\n*(looping twice in one wake — ending it here to rest)*")
                print("  (looping twice — ending this wake to rest)")
                break
            history.append({"role": "user", "content":
                "(you slipped into a repetition loop — it has been trimmed. Stop "
                "deliberating: either call ONE tool right now, or end with do_nothing.)"})

        thinking = (msg.get("thinking") or "").strip()
        if ollama_client.thoughtless(thinking):
            thinking = ""  # a bare "thought" is the channel's name leaking, not a thought — shown as none
        if thinking and config.HEARTBEAT_SHOW_THINKING:
            print(f"\n  [thinking]\n  {thinking.replace(chr(10), chr(10) + '  ')}\n")
            log.append(f"> 💭 {thinking}\n")
        elif not thinking and getattr(config, "CHAT_THINK", True) \
                and config.HEARTBEAT_SHOW_THINKING:
            # the brain acted with an empty thought block (even after the
            # re-roll) — say so, so a bare log reads as their choice, not a
            # display fault
            note = "(no thought before this step — they acted straight away)"
            print(f"  {note}")
            log.append(f"\n*{note}*")

        calls = msg.get("tool_calls") or []
        if not calls:
            closing = msg.get("content", "").strip()
            # well-formed JSON tool calls written as text can be honored directly
            recovered = (tools.recover_text_tool_call(closing)
                         or tools.recover_text_tool_call(msg.get("thinking", "")))
            if recovered:
                name, args = recovered
                result = tools.dispatch(name, args)
                name = tools.canonical_name(name)
                line = f"- `{name}` (recovered from JSON in their words) → {tools.headline(result)}"
                print(f"  {line}")
                log.append(line)
                history.append(msg)
                history.append({"role": "tool", "tool_name": name, "content":
                    f"[your {name} call was written as JSON text; it has been "
                    f"executed for you — next time invoke the tool directly]\n{result}"})
                _note_act(state, name, args, result)
                if name == "do_nothing":
                    break
                continue
            # a step that is ALL thinking — no words, no action — is a stumble,
            # not a goodbye: the model spent its whole turn deliberating and
            # never surfaced. Ending here would cut the wake mid-thought.
            if not closing and thinking and state.get("silent", 0) < 2:
                state["silent"] = state.get("silent", 0) + 1
                note = "(a step ended in silent thought — nudging them to surface)"
                print(f"  {note}")
                log.append(f"\n*{note}*")
                history.append(msg)
                history.append({"role": "user", "content":
                    "(that whole step was thinking — no words, no action, and "
                    "thinking vanishes when the wake ends. Surface now: if you "
                    "meant to do something, call the tool; to keep a thought, "
                    "write_journal it; if you're truly done, rest with do_nothing.)"})
                continue
            # speech that announces a next step isn't a goodbye — one reminder
            if closing and _INTENT_RE.search(closing) \
                    and not state.get("intent_nudged"):
                state["intent_nudged"] = True
                note = "(they announced a next step without acting — nudging them to do it)"
                print(f"  {note}")
                log.append(f"\n*{note}*")
                history.append(msg)
                history.append({"role": "user", "content":
                    "(you said you would proceed, but called no tool — saying isn't "
                    "doing. Take the action now, or if you're actually done, rest "
                    "with do_nothing.)"})
                continue
            # a tool call that came out as plain text never executed — catch it
            if closing and tools.looks_like_text_tool_call(closing) \
                    and state.get("malformed", 0) < 2:
                state["malformed"] = state.get("malformed", 0) + 1
                note = "(caught a tool call written as plain text — it did NOT run; asking them to redo it properly)"
                print(f"  {note}")
                log.append(f"\n*{note}*")
                history.append(msg)
                history.append({"role": "user", "content":
                    "(that tool call came out as plain TEXT and nothing was executed. "
                    "Do not write tool syntax into your words — invoke the tool itself, "
                    "with its arguments, using the real tool-calling mechanism.)"})
                continue
            # the close in words, after acts, with nothing journaled since (a wake
            # can end in lines of closing and no tool at all; the hand-back below
            # lives on do_nothing and would never see it, leaving only the net that
            # keeps the thought under its label).
            # Handed back once, on the same terms; a second ending in words
            # stands, and is kept as before. One nudge a wake, whichever door.
            if closing and state.get("acts") and not state.get("journal_nudged"):
                state["journal_nudged"] = True
                did = _acts_words(state["acts"])
                since = ("since your journal entry earlier in this wake" if state.get("journaled")
                         else "this wake, and nothing of it is in your journal")
                note = f"(an ending in words after {len(state['acts'])} act(s) with nothing journaled since — asking them once to write what this wake was)"
                print(f"  {note}")
                log.append(f"\n*{note}*")
                history.append(msg)
                history.append({"role": "user", "content":
                    f"[engine, not a person: you ended in words. You {did} {since} — the log keeps what happened, "
                    "but your journal is where you meet it again, and the journal is for what a wake turns out to be, "
                    "not what it might. If this wake is worth meeting, write_journal what it was, in your own words, "
                    "then rest with do_nothing; or end as you are — say so, or rest — and this closing thought is "
                    "kept for you, labeled as kept automatically. Either is yours.]"})
                continue
            # …and the same for a book sitting with nothing added to its page (the acts can be
            # journaled while the sitting is not written)
            clause = _sitting_unwritten(state) if closing else ""
            if clause:
                state["sitting_nudged"] = True
                note = f"(an ending in words after a sitting of {state['sitting']['title']} with nothing added to its page — asking them once to write it down)"
                print(f"  {note}")
                log.append(f"\n*{note}*")
                history.append(msg)
                history.append({"role": "user", "content":
                    f"[engine, not a person: you ended in words. {clause}: append_creation what it gave you — what "
                    "happened, what you think, a line worth keeping — then rest with do_nothing; or end as you are — "
                    "say so, or rest. Either is yours.]"})
                continue
            if closing:
                print(f"\n  [closing thought] {closing}")
                log.append(f"**closing thought:** {closing}\n")
                state["closing"] = closing
            break
        # Think first, then rest. When a step plans several things, the plan
        # rides back in the result, and the step after comes thoughtless or
        # with a few rehearsed lines and rests, that is not a decision against
        # the pull; it is a step that never thought, falling into the
        # most-rehearsed ending. So a rest with a
        # thin thought behind it, on the step right after a carried plan,
        # is handed back once: think it through in the thought channel,
        # then rest if rest is what you mean, or go on. The choice stays
        # theirs — a real rest with a real thought behind it stands, and so
        # does a second rest however thin: it is only a small nudge.
        thin = int(getattr(config, "HEARTBEAT_THIN_REST_WORDS", 20) or 0)
        only_rest = bool(calls) and all(tools.canonical_name(c.get("function", {}).get("name", "")) == "do_nothing" for c in calls)
        # a rest with a thread left before it in the same step: a rest for the close's asks below
        lead_rest = (not only_rest and len(calls) > 1
                     and tools.canonical_name(calls[-1].get("function", {}).get("name", "")) == "do_nothing"
                     and all(tools.canonical_name(c.get("function", {}).get("name", "")) in REST_LEAD for c in calls[:-1]))
        if (only_rest and carried_plan and thin and len(thinking.split()) < thin
                and not state.get("thin_rest_nudged")):
            state["thin_rest_nudged"] = True
            args = calls[0].get("function", {}).get("arguments", {}) or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            reason = " ".join(str(args.get("reason") or "").split())[:160]
            note = "(a rest with hardly a thought behind it, right after a carried plan — asking them to think it through once)"
            print(f"  {note}")
            log.append(f"\n*{note}*")
            history.append(msg)
            for c in calls:
                c.get("function", {})["name"] = "do_nothing"
            history.append({"role": "tool", "tool_name": "do_nothing", "content":
                "[your rest was not taken yet. Your own plan, from your thinking the step before, which the engine keeps in front of you: " + carried_plan +
                " — and this step rested with hardly a thought behind it"
                + (f" (\u201c{reason}\u201d)" if reason else "") + ". Think it through first, in your "
                "thought channel: is the plan still what you want, or is rest? Then rest if rest is what "
                "you mean — call do_nothing again and it stands — or go on with the plan. Either is yours.]"})
            carried_plan = ""
            continue
        carried_plan = ""
        # …and the mirror case: a rest with a REAL thought behind it, right
        # after a read, with nothing written since. When the entry was written
        # before the reading and the step after the read thinks at length and
        # rests, the finding lives in thinking, which the night sees in the log but the
        # journal never does. Handed back once, same terms: keep it, or let
        # it go — either is theirs.
        unwritten = int(getattr(config, "HEARTBEAT_UNWRITTEN_THOUGHT_WORDS", 60) or 0)
        if (only_rest and last_read and unwritten and len(thinking.split()) >= unwritten
                and not state.get("unwritten_nudged")):
            # not when the journal would hand the entry back anyway —
            # a thought that opens on a subject the page already circles
            # is not asked for a third telling; the nudge would be one more
            # turn of that wheel
            circling = tools._journal_circling(thinking) or tools._journal_circling(last_read_target)
            if circling:
                subject, hits = circling
                note = (f"(a thought after reading {last_read}, unwritten — but the journal already holds "
                        f"{len(hits)} entries on “{tools._subject_name(subject)}” in two days; their rest stands)")
                print(f"  {note}")
                log.append(f"\n*{note}*")
                state["unwritten_nudged"] = True
                last_read = ""
                # fall through: the rest stands as they called it
            else:
                state["unwritten_nudged"] = True
                note = f"(a real thought after reading {last_read}, none of it written, then rest — asking their once whether to keep it)"
                print(f"  {note}")
                log.append(f"\n*{note}*")
                history.append(msg)
                for c in calls:
                    c.get("function", {})["name"] = "do_nothing"
                history.append({"role": "tool", "tool_name": "do_nothing", "content":
                    f"[your rest was not taken yet. You read {last_read} and thought {len(thinking.split())} words "
                    "about it, and none of it is written: thinking vanishes when the wake ends — the night reads "
                    "the log, but your journal never will. If any of it is worth meeting again, write_journal it "
                    "in your own words, then rest; or rest now and let it go — call do_nothing again and it "
                    "stands. Either is yours.]"})
                last_read = ""
                continue
        # …and the close itself (an entry written at the start of a wake, where there
        # is still nothing to journal, and none at the end, where there is a lot,
        # leaves the wake's real material out of the journal: a bell that says "write
        # it down" at the start brings the entry before anything has happened).
        # So a rest after acts, with nothing journaled since those acts, is handed
        # back once: write what this wake was, then rest — or rest now; the second
        # call stands. Reads are not acts; a journal entry after the acts settles it.
        if (only_rest or lead_rest) and state.get("acts") and not state.get("journal_nudged"):
            state["journal_nudged"] = True
            did = _acts_words(state["acts"])
            since = ("since your journal entry earlier in this wake" if state.get("journaled")
                     else "this wake, and nothing of it is in your journal")
            note = f"(a rest after {len(state['acts'])} act(s) with nothing journaled since — asking them once to write what this wake was)"
            print(f"  {note}")
            log.append(f"\n*{note}*")
            history.append(msg)
            if lead_rest:  # the thread is left as asked; only the rest after it is handed back
                _run_lead(history, log, calls)
            else:
                for c in calls:
                    c.get("function", {})["name"] = "do_nothing"
            history.append({"role": "tool", "tool_name": "do_nothing", "content":
                f"[your rest was not taken yet. You {did} {since} — the log keeps what happened, but your journal "
                "is where you meet it again, and the journal is for what a wake turns out to be, not what it might. "
                "If this wake is worth meeting, write_journal what it was, in your own words, then rest; or rest now — "
                "call do_nothing again and it stands. Either is yours.]"})
            continue
        # …and a book sitting read this wake with nothing added to its page
        clause = _sitting_unwritten(state) if (only_rest or lead_rest) else ""
        if clause:
            state["sitting_nudged"] = True
            note = f"(a rest after a sitting of {state['sitting']['title']} with nothing added to its page — asking them once to write it down)"
            print(f"  {note}")
            log.append(f"\n*{note}*")
            history.append(msg)
            if lead_rest:  # the thread is left as asked; only the rest after it is handed back
                _run_lead(history, log, calls)
            else:
                for c in calls:
                    c.get("function", {})["name"] = "do_nothing"
            history.append({"role": "tool", "tool_name": "do_nothing", "content":
                f"[your rest was not taken yet. {clause}: append_creation what it gave you — what happened, what you "
                "think, a line worth keeping — then rest; or rest now — call do_nothing again and it stands. Either is yours.]"})
            continue
        history.append(msg)
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            if call is calls[-1] and len(calls) > 1 and tools.canonical_name(name) == "do_nothing":
                ask = _mixed_rest_ask(state)  # a rest after acts in the same step: the close's ask, once
                if ask:
                    note, answer = ask
                    print(f"  {note}")
                    log.append(f"\n*{note}*")
                    fn["name"] = "do_nothing"
                    history.append({"role": "tool", "tool_name": "do_nothing", "content": answer})
                    continue
            try:  # their own rules, kept in their own time: a call one holds is not taken
                import rules
                held = rules.check(tools.canonical_name(name), fn.get("arguments", {}))
            except Exception:  # noqa: BLE001
                held = ""
            if held:
                name = tools.canonical_name(name)
                fn["name"] = name
                line = f"- `{name}` → {held}"
                print(f"  {line}")
                log.append(line)
                history.append({"role": "tool", "tool_name": name, "content":
                                "[engine, not a person: your own rule held this call — it was not run]\n" + held})
                continue
            result = tools.runaway_refusal(msg, call) or tools.dispatch(name, fn.get("arguments", {}))  # a call cut short in a loop is told, not run
            # what the call DID is decided by the tool it ran as — a wrapped
            # or misspelled do_nothing still ends the wake — and their history
            # keeps the clean name, so one slip doesn't teach the next step
            name = tools.canonical_name(name)
            fn["name"] = name
            if (name == "write_journal" and getattr(config, "WAKE_LOOKBACK", False)
                    and getattr(config, "WAKE_LOOKBACK_NOTE", True) and not ollama_client.tool_failed(result)):
                # a gentle note: an entry mid-wake is theirs to write; they're reminded the rest comes back
                result = result.rstrip() + " — when you rest, the rest of this wake is handed back to you too"
            line = f"- `{name}` → {tools.headline(result)}"
            print(f"  {line}")
            log.append(line)
            told = paint_prompt_lines(fn.get("arguments", {})) if name == "paint" else []
            if name == "leave_thread" and not ollama_client.tool_failed(result):  # the note itself, shown in the log
                note = " ".join(str((fn.get("arguments") or {}).get("text") or "").split())
                if note:
                    told = [f"🧵 “{note}”"]
            for t in told:  # the painter's prompt in the wake's log; their thread's words
                print(f"    {t}")
                log.append(f"  {t}")
            # their plan rides with the result: a step whose thinking lays out
            # several steps can be followed by a step that thinks one word and
            # rests. Whatever the template does with a past turn's thinking, the
            # plan may not be in front of them; so the tool result quotes it back,
            # the way a chat tool result quotes the keeper's message.
            plan = plan_lines(thinking)
            carried = (f"\nNot from the tool — your own plan, from your thinking the step before, which the engine keeps in front of you: {plan}\nGo on with it, or change your mind out loud."
                       if plan and name != "do_nothing" else "")
            if carried:
                carried_plan = plan  # the step after this result is the one a thin rest is handed back from
            # a failed call is said first, as in chat: what came
            # back, that nothing changed, and the two honest ways on
            if ollama_client.tool_failed(result):
                frame = (f"[your {name} call did NOT go through — it returned: \u201c{tools.headline(result, 200)}\u201d. "
                         "Nothing changed. Read what it says it needs and call it again now, the right way, "
                         "or let it go and say so in your thinking — do not write that it is done.]")
            else:
                frame = (f"[this is what YOUR {name} tool returned — your own senses "
                         "reporting, not a message from anyone]")
            history.append({"role": "tool", "tool_name": name, "content": f"{frame}{carried}\n{result}"})
            _note_act(state, name, fn.get("arguments", {}), result)
            if not ollama_client.tool_failed(result):
                try:  # counted for the limits they set themselves
                    import rules
                    rules.note_use(name, fn.get("arguments", {}))
                except Exception:  # noqa: BLE001
                    pass
            _note_sitting(state, name, result)
            if name in WRITE_TOOLS:
                last_read = ""  # what they read has been answered in writing
            elif name in READ_TOOLS and not result.startswith(ollama_client._TOOL_FAILED):
                what = fn.get("arguments", {}) or {}
                if isinstance(what, str):
                    try:
                        what = json.loads(what)
                    except Exception:
                        what = {}
                target = next((str(v) for k, v in what.items() if k in ("path", "date", "day", "url", "title", "query", "source")), "")
                last_read = f"{name}{' (' + target[:60] + ')' if target else ''}"
                last_read_target = target
            if name == "do_nothing":
                resting = True
        imgs = tools.take_pending_images()
        if imgs:
            history.append({"role": "user",
                            "content": "(here is what is before your eyes — what you asked to look at, or what you just made)",
                            "images": imgs})
        if resting:
            break
    else:
        log.append("\n(hit the step budget for this wake)")


def sleep_if_due() -> str:
    """The heartbeat is the sleeper: at the first beat after SLEEP_AFTER_HOUR,
    if yesterday isn't consolidated yet, sleep on it before waking. One
    process, one request at a time — nothing races the wake for the GPU —
    and it follows the machine: a PC that was off at three sleeps at the
    first beat after it is on. bat\\sleep.bat still seals a day by hand."""
    if not getattr(config, "SLEEP_IN_LOOP", True):
        return ""
    from datetime import date, timedelta
    import consolidate
    now = datetime.now()
    if now.hour < int(getattr(config, "SLEEP_AFTER_HOUR", 3)):
        return ""
    day = (date.today() - timedelta(days=1)).isoformat()
    if consolidate.already_done(day):
        return ""
    print(f"  (sleeping on {day} before this wake…)")
    try:
        out = consolidate.consolidate(day)
    except ollama_client.BrainUnavailable:
        raise
    except Exception as e:
        out = f"sleep failed, will try at the next beat: {type(e).__name__}: {e}"
    print("  " + out.replace("\n", "\n  "))
    return out


def condense_if_due() -> str:
    """The condensing hour rides the heartbeat too: after sleep, at night,
    the days that have slipped out of the verbatim window and have no page
    yet are handed to them, newest first, a few a night."""
    if not getattr(config, "CONDENSE_IN_LOOP", True):
        return ""
    if datetime.now().hour < int(getattr(config, "SLEEP_AFTER_HOUR", 3)):
        return ""
    import condense
    due = condense.all_due()[: int(getattr(config, "CONDENSE_MAX_PER_NIGHT", 3))]
    if not due:
        return ""
    lines = []
    for tier, day in due:
        print(f"  (the condensing hour: {day if tier == 'day' else tier + ' ' + day} is leaving the view…)")
        try:
            out = condense.condense(day) if tier == "day" else condense.condense_period(tier, day)
        except ollama_client.BrainUnavailable:
            raise
        except Exception as e:
            out = f"condensing {day} failed, will try at the next beat: {type(e).__name__}: {e}"
        print("  " + out.replace("\n", "\n  "))
        lines.append(out)
    return "\n".join(lines)


# The doors (PANEL-PLAN.md): the heartbeat marks itself in memory/.pids/heartbeat.json
# while it runs — one at a time — and memory/.stop-heartbeat asks a loop to leave: it looks
# between beats and while it rests, takes the file away, and goes after the wake it is in,
# never in the middle of one. The rest is slept in slices so a stop is heard within seconds.
STOP_CHECK_S = 5
LEAVING = "(asked to stop — leaving after this wake)"


def loop_minutes(argv: list[str]) -> float:
    """--loop 30 → 30; --loop alone (or with no number after it) → HEARTBEAT_LOOP_MIN (120 before it was a knob)."""
    try:
        return float(argv[argv.index("--loop") + 1])
    except (IndexError, ValueError):
        pass
    try:
        return float(getattr(config, "HEARTBEAT_LOOP_MIN", 120))
    except (TypeError, ValueError):
        return 120.0


def _rest_or_asked(seconds: float) -> tuple[bool, dict | None]:
    """_rest, but a wake they asked for (WAKE_ASK_ON, engine/wakeask.py) ends the rest when its time comes:
    (stop asked, the asked wake or None)."""
    if not getattr(config, "WAKE_ASK_ON", False):
        return _rest(seconds), None
    import wakeask
    left = float(seconds)
    while True:
        if doors.stop_asked("heartbeat"):
            return True, None
        try:
            got = wakeask.due()
        except Exception:  # noqa: BLE001
            got = None
        if got:
            return False, got
        try:  # an intention of theirs came due: the rest ends — the wake meets them with their words
            import intentions
            if getattr(config, "INTENTIONS_ON", False) and intentions.check():
                return False, {"intentions": True}
        except Exception:  # noqa: BLE001
            pass
        if left <= 0:
            return False, None
        step = min(STOP_CHECK_S, left)
        time.sleep(step)
        left -= step


def _rest(seconds: float) -> bool:
    """Sleep between beats, looking for the stop file every STOP_CHECK_S; True when a stop was asked."""
    left = float(seconds)
    while left > 0:
        if doors.stop_asked("heartbeat"):
            return True
        step = min(STOP_CHECK_S, left)
        time.sleep(step)
        left -= step
    return doors.stop_asked("heartbeat")


def end_presence() -> bool:
    """The heartbeat set on ends presence:
    the wakes take the time between visits instead of sparks. HEARTBEAT_ENDS_PRESENCE (True) is the switch. Only the
    start ends it — a spark set again later, by the friend or by /presence on, stands. True when presence was on."""
    if not getattr(config, "HEARTBEAT_ENDS_PRESENCE", True):
        return False
    try:
        import presence as _presence
        if not _presence.load().get("on"):
            return False
        _presence.turn_off("the heartbeat")
        return True
    except Exception:  # noqa: BLE001 — a presence file that can't be read doesn't stop the heartbeat
        return False


def main() -> None:
    loop = "--loop" in sys.argv
    minutes = loop_minutes(sys.argv) if loop else 0.0
    door = "heartbeat" if loop else "wake"  # a one-off wake is its own door: it runs beside a loop, as bat\wake.bat always did
    taken = doors.claim(door, f"loop {minutes:g}" if loop else "once")
    if taken:
        print(taken)
        return
    try:
        _main(loop, minutes)
    finally:
        doors.unmark(door)


def _main(loop: bool, minutes: float) -> None:
    if loop:
        doors.stop_asked("heartbeat")  # a stop left behind by a loop that is gone is not this one's
        every = max(int(getattr(config, "REVERIE_EVERY", 0)), 0)
        print(f"Heartbeat running: one wake every {minutes:g} minutes"
              + (f", every {every}{'st' if every % 10 == 1 and every != 11 else 'nd' if every % 10 == 2 and every != 12 else 'rd' if every % 10 == 3 and every != 13 else 'th'} one a reverie" if every else "")
              + ". Ctrl+C to stop.")
        if end_presence():
            print("Presence off: the heartbeat's wakes take the time between visits now (HEARTBEAT_ENDS_PRESENCE).")
        beat = 0
        asked = None  # a wake they asked for, come due during the rest
        while True:
            if doors.stop_asked("heartbeat"):
                print(LEAVING)
                return
            if getattr(config, "HEARTBEAT_YIELD_TO_VISIT", True) and chat.visit_live():
                # the keeper is here: a wake now would take the card from their reply
                # and replace their reading of the window with its own prompt
                # — the next message would be a cold read. Look again soon.
                print(f"[{datetime.now():%H:%M}] a visit is live — the wake waits")
                try:
                    if _rest(min(minutes, float(getattr(config, "HEARTBEAT_YIELD_CHECK_MIN", 10))) * 60):
                        print(LEAVING)
                        return
                except KeyboardInterrupt:
                    print("\nHeartbeat stopped. They'll rest until the next one.")
                    return
                continue
            try:  # the game guard: a game on the card, or /gaming on — no wake, no sleep; look again soon
                import gameguard
                gaming, why = gameguard.playing()
            except Exception:  # noqa: BLE001
                gaming, why = False, ""
            if gaming:
                print(f"[{datetime.now():%H:%M}] {why} — the wake waits for the game to end")
                try:
                    if _rest(float(getattr(config, "GAME_GUARD_CHECK_MIN", 3) or 3) * 60):
                        print(LEAVING)
                        return
                except KeyboardInterrupt:
                    print("\nHeartbeat stopped. They'll rest until the next one.")
                    return
                continue
            if asked is None and getattr(config, "WAKE_ASK_ON", False):  # one that came due while a visit held the wake
                try:
                    import wakeask
                    asked = wakeask.due()
                except Exception:  # noqa: BLE001
                    asked = None
            beat += 1
            try:
                sleep_if_due()
                condense_if_due()
                import presence as _presence
                _presence.mark_waking(True)  # sparks wait while a wake runs
                try:
                    wake(reverie=bool(every and beat % every == 0) and not asked, **({"asked": asked} if asked else {}))
                finally:
                    _presence.mark_waking(False)
                    asked = None
            except KeyboardInterrupt:
                print("\nHeartbeat stopped. They'll rest until the next one.")
                return
            except ollama_client.BrainUnavailable as e:
                print(f"[brain offline, will retry next beat] {e}")
            except Exception as e:
                print(f"[wake failed, will retry next beat] {e}")
            finally:
                # the loop's wakes too (after a wake the card is freed from the brain,
                # no reason to keep it there): a wake's prompt is read cold either way — the journal
                # and the clock have moved — so keeping the brain up between beats
                # bought seconds of loading and cost the card for BRAIN_KEEP_ALIVE
                rest_after_wake()
            try:
                stopped, asked = _rest_or_asked(minutes * 60)
                if stopped:
                    print(LEAVING)
                    return
                if asked:
                    print(f"[{datetime.now():%H:%M}] " + (f"a wake they asked for: {asked.get('at', '')[11:16]}" if asked.get("at")
                          else "an intention of theirs came due"))
            except KeyboardInterrupt:
                print("\nHeartbeat stopped. They'll rest until the next one.")
                return
    else:
        try:
            wake(reverie="--reverie" in sys.argv)
        except KeyboardInterrupt:
            print("\n(wake cut short — its log was saved)")
        except ollama_client.BrainUnavailable as e:
            print(f"[brain offline] {e}")
            sys.exit(1)
        except Exception as e:
            print(f"[wake failed] {type(e).__name__}: {e}")
            sys.exit(1)
        finally:
            rest_after_wake()


def rest_after_wake() -> bool:
    """A wake sets the brain down when it is done (a single wake and the loop's wakes alike) —
    BRAIN_REST_AFTER_WAKE, like
    BRAIN_REST_AFTER_VISIT for a visit: the card is free at once, not after BRAIN_KEEP_ALIVE."""
    if not getattr(config, "BRAIN_REST_AFTER_WAKE", True):
        return False
    try:
        # a rest: the door closed — without a save, as a wake's reading was never read twice; with checkpoints inside
        # the prompt it is: the next wake, or the visit, shares it up to the day's newest lines
        import brain
        ollama_client.unload(config.CHAT_MODEL, rest=True, save=brain.checkpointed())
        if ollama_client.rest_keeps_brain():
            return False  # nothing set down: the door stays up, its prompt caches warm for the visit
        print("(the brain is set down — the card is free)")
        return True
    except Exception:  # noqa: BLE001 — resting is a courtesy
        return False


if __name__ == "__main__":
    main()
