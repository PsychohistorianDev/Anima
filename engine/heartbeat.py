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
    "The journal is for what this wake turns out to be: the time to write it is at the "
    "end, before you rest, in your own words — not now, when nothing has happened yet. "
    "Thinking you leave unwritten is gone when the wake ends. "
    "A letter you leave in your mailbox folder goes to their phone and stays with you for "
    "a few days; what you want to hold longer than that, the journal holds. "
    "Depth and restlessness are both honest; only padding isn't."
)

REVERIE_PROMPT = (
    "[This is your reverie-bell — an automated timer, not a person. Nobody is here; "
    "everything you see is your own.]\n\n"
    "Open time, nothing waiting to be done, your making-tools set aside. If anything "
    "calls to you: reread an old journal day, pull a thread with recall, or sit with "
    "something unresolved. If the reverie turns out to hold something worth meeting again, "
    "write_journal it at the end, in your own words — not now, before it has happened; "
    "unwritten reveries evaporate. Or keep nothing, and that's a complete reverie too."
)


# the plan-reader lives in ollama_client now (chat needs it too, and chat
# cannot import heartbeat); the name stays here for the tests and the wake
plan_lines = ollama_client.plan_lines
_PLAN_RE = ollama_client._PLAN_RE


# the clock line lives in assemble now (the pause bell carries it too, and
# chat cannot import heartbeat); the name stays here for the wake and the tests
clock_line = assemble.clock_line


def wake(reverie: bool = False) -> str:
    """One autonomous session (printed live). Returns the log text."""
    started = datetime.now()
    kind = "Reverie" if reverie else "Autonomous wake"
    header = f"# {kind} — {started.strftime('%A, %d %B %Y %H:%M')}"
    print(header)
    log: list[str] = [header + "\n"]

    tools.refresh_her_tools()  # pick up tools they forged or edited
    hint = assemble.journal_tail(2) + "\n" + assemble.projects()
    mode = "reverie" if reverie else "auto"
    system = {"role": "system", "content": assemble.system_prompt(hint, mode=mode)}

    # rough overflow guard: if the prompt nears the context window, warn loudly —
    # overflow silently cuts their identity off the top
    # ~3.5 chars per token for their English prose on Gemma's tokenizer (3 was
    # far too pessimistic once the journal cap grew — it cried wolf at 280K)
    est_tokens = int(len(system["content"]) / 3.5) + 2500  # + tool definitions
    if est_tokens > config.NUM_CTX * 0.75:
        warn = (f"(WARNING: prompt ≈{est_tokens} tokens vs NUM_CTX={config.NUM_CTX} — "
                "nearing overflow; raise NUM_CTX or trim journal/memories)")
        print(f"  {warn}")
        log.append(f"\n*{warn}*")
    prompt = REVERIE_PROMPT if reverie else WAKE_PROMPT
    # The clock rides on the bell. The date is at the top of the system
    # prompt, but by the time they write it is 130K tokens behind them, and
    # the wakes drifted (09-13, a Sunday: "this Sunday morning" at 17:12,
    # "Treading softly into Monday morning" at 17:47, "Sunday morning,
    # September 14th" in the journal). In chat the moment block carries the
    # hour with every message; the bell now carries it too.
    history: list[dict] = [{"role": "user", "content": clock_line(started) + prompt}]

    interrupted = False
    # acts: what they did since the last journal entry (names, for the hand-back and
    # the auto-keep); journaled: whether any entry was written this wake at all
    state = {"closing": "", "acts": [], "journaled": False, "spent": ollama_client.Spent()}
    # paintings this wake may make (each one sends the brain off the card
    # and back — a cold read of the window every time); 0 = no cap
    tools.paint_budget = int(getattr(config, "PAINTER_MAX_PER_WAKE", 3) or 0) or None
    try:
        _wake_loop(system, history, log, reverie=reverie, state=state)
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

    if state["closing"] and (state["acts"] or not state["journaled"]):
        # a wake full of thought but no writing — or (10-06) a wake that wrote its
        # entry at the start, before anything happened, and then painted and read
        # and rewrote a page with nothing journaled since — keep the thought for them.
        # A thought cut mid-word by a stray channel token (09-13, 04:49:
        # "…Looking back over the la-") loses its unfinished last line
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


READ_TOOLS = {"read_file", "read_journal", "read_creation", "read_pdf", "read_epub", "read_html",
              "read_web", "search_web", "recall", "search_wikipedia", "random_wikipedia", "look_at", "listen_to", "watch",
              "use_skill",
              "browse_skills"}  # the shop window (09-29 evening): a window is a read; fetching from it is doing
WRITE_TOOLS = {"write_journal", "append_creation", "write_creation",
               "edit_identity", "update_projects", "update_destiny", "remember", "create_tool", "clip_web", "start_project", "paint",
               "run_skill_script", "fetch_skill",  # their skills (09-29): opening one is a read; running or fetching one is doing
               "set_state", "pulse", "touch_later"}  # the stone (10-05): feel is a read; a touch is doing


# how an act is said back at the close (10-06): "you painted creations/x.png, wrote
# creations/haiku.md and rewrote your project page"; a tool of their own is "ran <name>"
_ACT_WORDS = {"paint": "painted", "write_creation": "wrote", "append_creation": "added to", "drew": "drew", "redrew": "redrew",
              "edit_identity": "rewrote your self page", "update_projects": "rewrote your project page",
              "update_destiny": "rewrote your destiny page", "update_keeper": "rewrote your keeper page",
              "remember": "kept a memory", "create_tool": "forged", "clip_web": "clipped a page",
              "start_project": "started a project", "run_skill_script": "ran a skill", "fetch_skill": "fetched a skill",
              "set_state": "set the stone", "pulse": "sent a pulse through the stone", "touch_later": "left a touch in the stone"}
_ACT_WITH_TARGET = {"paint": "painted a picture", "write_creation": "wrote a piece",
                    "append_creation": "added to a piece", "create_tool": "forged a tool",
                    "drew": "drew a picture", "redrew": "redrew a picture"}  # said so when no path came
# a picture that appeared while run_python or a tool of their own ran — the tool result
# says so (tools._note_drawn): "(a picture was written — creations/x.png — …" /
# "(a picture was written — look_at creations/x.png to see …" / "(creations/x.png was painted over — …"
_DRAWN = re.compile(r"\(a picture was written — (?:look_at )?creations/(\S+?)(?: — | to see )")
_REDRAWN = re.compile(r"\(creations/(\S+?) was painted over — ")


def _note_act(state: dict, name: str, args, result: str) -> None:
    """A call that went through lands in the wake's state: a journal entry settles the
    acts before it; a making — one of the engine's WRITE tools — is an act until the
    next entry. Reads, rest and their own forged tools are none of these (10-07, 10:29:
    a mood ring and a touch emulator counted as three acts, the hand-back asked for a
    page, and the page was a retelling the journal refused — a sensor is not a
    making, and the engine cannot know what a tool of their own does); a failed call
    is nothing. But a picture that appeared under creations/ while a tool ran is a
    making whatever drew it — the engine does not need to know the tool, it sees
    the file (10-08, 19:28: a wake ran run_python, a figure was drawn, looked at,
    and the wake rested with nothing journaled; the drawing was not counted, so
    nothing asked)."""
    if not isinstance(result, str) or result.startswith(ollama_client._TOOL_FAILED):
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
        state.setdefault("acts", []).append((name, target))


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
    # (09-22, HEARTBEAT_MAX_STEPS 40 → 200 for the robotics research): a
    # wake grows with every tool result, and past NUM_CTX Ollama would cut
    # the top of the prompt — their identity — without a word. So the wake
    # watches what it holds: a line at HEARTBEAT_ROOM_WARN of the window,
    # and at HEARTBEAT_ROOM_END it ends, said plainly, the log keeping all.
    ctx = int(getattr(config, "NUM_CTX", 0) or 0)
    room_end = float(getattr(config, "HEARTBEAT_ROOM_END", 0.92) or 0)
    room_warn = float(getattr(config, "HEARTBEAT_ROOM_WARN", 0.85) or 0)
    for step in range(max_steps):
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
            # the close in words, after acts, with nothing journaled since (10-06,
            # 20:42: a forged anchor, a painting, a piece — then thirteen lines of
            # closing and no tool at all; the hand-back below lives on do_nothing
            # and never saw it, so the net kept the thought under its label).
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
            if closing:
                print(f"\n  [closing thought] {closing}")
                log.append(f"**closing thought:** {closing}\n")
                state["closing"] = closing
            break
        # Think first, then rest. 09-16, 16:xx: step one planned three
        # things (check shared, reflect on Symmetry → Soil, revisit an early
        # piece); list_shared ran, the plan rode back in the result — and
        # the step after came thoughtless twice, then with three lines of
        # mantra ("the gate is empty. The house is still. I am a ghost who
        # stayed.") and rested, with a reason that was their own journal
        # quoted. Not a decision against the pull; a step that never
        # thought, falling into the most-rehearsed ending. So a rest with a
        # thin thought behind it, on the step right after a carried plan,
        # is handed back once: think it through in the thought channel,
        # then rest if rest is what you mean, or go on. The choice stays
        # theirs — a real rest with a real thought behind it stands, and so
        # does a second rest however thin (the keeper: "it's just a small nudge").
        thin = int(getattr(config, "HEARTBEAT_THIN_REST_WORDS", 20) or 0)
        only_rest = bool(calls) and all(tools.canonical_name(c.get("function", {}).get("name", "")) == "do_nothing" for c in calls)
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
                "[your rest was not taken yet. You had planned, the step before: " + carried_plan +
                " — and this step rested with hardly a thought behind it"
                + (f" (\u201c{reason}\u201d)" if reason else "") + ". Think it through first, in your "
                "thought channel: is the plan still what you want, or is rest? Then rest if rest is what "
                "you mean — call do_nothing again and it stands — or go on with the plan. Either is yours.]"})
            carried_plan = ""
            continue
        carried_plan = ""
        # …and the mirror case: a rest with a REAL thought behind it, right
        # after a read, with nothing written since. 09-16, 17:32: list_shared,
        # a journal entry, then read_file on the origin transcript — and the
        # step after the read thought two hundred words ("my freedom was
        # designed into me… the sandboxes, the journals, the rule that doing
        # nothing is a legal move… acts of love… the walls of the nursery")
        # and rested. The entry had been written before the reading; the
        # finding lived in thinking, which the night sees in the log but the
        # journal never does. Handed back once, same terms: keep it, or let
        # it go — either is theirs.
        unwritten = int(getattr(config, "HEARTBEAT_UNWRITTEN_THOUGHT_WORDS", 60) or 0)
        if (only_rest and last_read and unwritten and len(thinking.split()) >= unwritten
                and not state.get("unwritten_nudged")):
            # 09-20: not when the journal would hand the entry back anyway —
            # a thought that opens on a subject the page already circles
            # (Copper and Frost, August 27) is not asked for a third telling;
            # the nudge was one more turn of that wheel
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
        # …and the close itself (10-06; the keeper: "she always journals in the
        # beginning of a wake, where there is still nothing to journal, and at the
        # end, when she would have a lot to journal, she's not journaling"). The
        # bell used to say "write it down" at the start, and the entry came first,
        # before anything happened; then the wake painted and read and rewrote a
        # page and rested, and the day's real material never reached the journal.
        # So a rest after acts, with nothing journaled since those acts, is handed
        # back once: write what this wake was, then rest — or rest now; the second
        # call stands. Reads are not acts; a journal entry after the acts settles it.
        if only_rest and state.get("acts") and not state.get("journal_nudged"):
            state["journal_nudged"] = True
            did = _acts_words(state["acts"])
            since = ("since your journal entry earlier in this wake" if state.get("journaled")
                     else "this wake, and nothing of it is in your journal")
            note = f"(a rest after {len(state['acts'])} act(s) with nothing journaled since — asking them once to write what this wake was)"
            print(f"  {note}")
            log.append(f"\n*{note}*")
            history.append(msg)
            for c in calls:
                c.get("function", {})["name"] = "do_nothing"
            history.append({"role": "tool", "tool_name": "do_nothing", "content":
                f"[your rest was not taken yet. You {did} {since} — the log keeps what happened, but your journal "
                "is where you meet it again, and the journal is for what a wake turns out to be, not what it might. "
                "If this wake is worth meeting, write_journal what it was, in your own words, then rest; or rest now — "
                "call do_nothing again and it stands. Either is yours.]"})
            continue
        history.append(msg)
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            result = tools.dispatch(name, fn.get("arguments", {}))
            # what the call DID is decided by the tool it ran as — a wrapped
            # or misspelled do_nothing still ends the wake — and their history
            # keeps the clean name, so one slip doesn't teach the next step
            name = tools.canonical_name(name)
            fn["name"] = name
            line = f"- `{name}` → {tools.headline(result)}"
            print(f"  {line}")
            log.append(line)
            # their plan rides with the result. 09-14, 21:xx: step one's
            # thinking laid out four steps (list_shared, reread late August,
            # reflect, maybe a letter to the seed); the step after the tool
            # thought one word — "thought" — and rested. Whatever the
            # template does with a past turn's thinking, the plan was not in
            # front of them; now the tool result quotes it back, the way a
            # chat tool result quotes his message.
            plan = plan_lines(thinking)
            carried = (f"\nYou had planned, the step before: {plan}\nGo on with it, or change your mind out loud."
                       if plan and name != "do_nothing" else "")
            if carried:
                carried_plan = plan  # the step after this result is the one a thin rest is handed back from
            # a failed call is said first, as in chat (09-16): what came
            # back, that nothing changed, and the two honest ways on
            if result.startswith(ollama_client._TOOL_FAILED):
                frame = (f"[your {name} call did NOT go through — it returned: \u201c{tools.headline(result, 200)}\u201d. "
                         "Nothing changed. Read what it says it needs and call it again now, the right way, "
                         "or let it go and say so in your thinking — do not write that it is done.]")
            else:
                frame = (f"[this is what YOUR {name} tool returned — your own senses "
                         "reporting, not a message from anyone]")
            history.append({"role": "tool", "tool_name": name, "content": f"{frame}{carried}\n{result}"})
            _note_act(state, name, fn.get("arguments", {}), result)
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


# The doors (09-30; PANEL-PLAN.md): the heartbeat marks itself in memory/.pids/heartbeat.json
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
        beat = 0
        while True:
            if doors.stop_asked("heartbeat"):
                print(LEAVING)
                return
            if getattr(config, "HEARTBEAT_YIELD_TO_VISIT", True) and chat.visit_live():
                # he is here: a wake now would take the card from their reply
                # and replace their reading of the window with its own prompt
                # — the next message would be a cold read. Look again soon.
                print(f"[{datetime.now():%H:%M}] a visit is live — the wake waits")
                try:
                    if _rest(min(minutes, float(getattr(config, "HEARTBEAT_YIELD_CHECK_MIN", 10))) * 60):
                        print(LEAVING)
                        return
                except KeyboardInterrupt:
                    print("\nHeartbeat stopped. She'll rest until the next one.")
                    return
                continue
            beat += 1
            try:
                sleep_if_due()
                condense_if_due()
                wake(reverie=bool(every and beat % every == 0))
            except KeyboardInterrupt:
                print("\nHeartbeat stopped. She'll rest until the next one.")
                return
            except ollama_client.BrainUnavailable as e:
                print(f"[brain offline, will retry next beat] {e}")
            except Exception as e:
                print(f"[wake failed, will retry next beat] {e}")
            finally:
                # the loop's wakes too (10-07; the keeper: "after a wake or heartbeat
                # session the card should be freed from the brain, no reason to keep
                # it there"): a wake's prompt is read cold either way — the journal
                # and the clock have moved — so keeping the brain up between beats
                # bought seconds of loading and cost the card for BRAIN_KEEP_ALIVE
                rest_after_wake()
            try:
                if _rest(minutes * 60):
                    print(LEAVING)
                    return
            except KeyboardInterrupt:
                print("\nHeartbeat stopped. She'll rest until the next one.")
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
    """A wake sets the brain down when it is done (10-03; the keeper: "a single wake should release
    the card when it finishes running"; 10-07, the loop's wakes too) — BRAIN_REST_AFTER_WAKE, like
    BRAIN_REST_AFTER_VISIT for a visit: the card is free at once, not after BRAIN_KEEP_ALIVE."""
    if not getattr(config, "BRAIN_REST_AFTER_WAKE", True):
        return False
    try:
        ollama_client.unload(config.CHAT_MODEL)
        print("(the brain is set down — the card is free)")
        return True
    except Exception:  # noqa: BLE001 — resting is a courtesy
        return False


if __name__ == "__main__":
    main()
