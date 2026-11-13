"""Thin client for the local Ollama server. Standard library only.

Two entry points:
    chat(messages, tools=None)  -> assistant message dict
    embed(text)                 -> list[float]

The rest of the engine talks to the brain exclusively through these two
functions, which is what makes the brain swappable. With BRAIN_API = "llama"
the brain's replies come from llama-server instead, through brain.py,
translated at the door; the ears and the embeddings stay here on Ollama.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import brain
import config


class BrainUnavailable(RuntimeError):
    """Raised when the Ollama server can't be reached at all."""


def _post(path: str, payload: dict, timeout: float | None = None) -> dict:
    # BRAIN_API = "llama": the brain's /api/chat goes to llama-server, translated at the
    # door (brain.py) — here, so every post of it in this file (the reply, the re-rolls,
    # the rescues) takes the one road. The ears' /api/chat (another model) and every
    # other path stay on Ollama.
    if path == "/api/chat" and brain.api() == "llama" and payload.get("model") == config.CHAT_MODEL:
        return brain.post_chat(payload, timeout)
    timeout = timeout or config.REQUEST_TIMEOUT_S
    req = urllib.request.Request(
        config.OLLAMA_URL + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if payload.get("stream"):
                return _drink(resp)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # The server answered, so Ollama is running — surface its actual error.
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get("error", "")
        except Exception:
            detail = ""
        model = payload.get("model", "?")
        if "not found" in detail.lower() or e.code == 404:
            raise BrainUnavailable(
                f"Ollama is running, but the model `{model}` isn't installed.\n"
                f"  Fix: open a terminal and run:  ollama pull {model}\n"
                f"  (server said: {detail or f'HTTP {e.code}'})"
            ) from e
        raise BrainUnavailable(
            f"Ollama error on {path}: {detail or f'HTTP {e.code}'}"
        ) from e
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), TimeoutError):
            raise BrainUnavailable(
                f"the brain took longer than {timeout:.0f}s to answer — "
                "it's probably busy chewing on something big (long audio, a model "
                "swap). Wait a moment and try again."
            ) from e
        raise BrainUnavailable(
            f"Can't reach Ollama at {config.OLLAMA_URL} — is it running? "
            f"(start the Ollama app, or run `ollama serve`)  [{e}]"
        ) from e
    except (TimeoutError, OSError) as e:
        raise BrainUnavailable(
            f"the brain took longer than {timeout:.0f}s to answer — "
            "it's probably busy chewing on something big (long audio, a model swap). "
            f"Wait a moment and try again.  [{type(e).__name__}: {e}]"
        ) from e


_THINK_RE = re.compile(r"<think>(.*?)</think>\s*", flags=re.DOTALL)
# stray chat-template tokens some builds leak into output
# (<|channel>thought, </s>, <tool_call|> etc.)
_TOKEN_LITTER_RE = re.compile(r"<\|[^>\n]{0,40}>\w*\n?|</?s>|<\|?tool_call\|?>?")


def scrub_litter(text: str) -> str:
    return delatex(_TOKEN_LITTER_RE.sub("", text or ""))


# Gemma's reserved and control tokens, written out as text: "<unused50>",
# "<start_of_turn>", "<eos>"… Ollama tokenizes a prompt WITH special tokens,
# so the string "<unused50>" in any message — the friend's, the keeper's, the engine's — goes
# back into the brain as the reserved token itself, not as eleven characters.
# Left as text, a reply that is a flood of "<unused50>" would be quoted back by the
# re-roll line and ride in every later request of the visit (the cool rungs, the cold
# roll, the pause, a resumed visit) as hundreds of reserved tokens — the well feeding itself.
# defang() turns the brackets into ⟨ ⟩: the same to a reader, never a token.
_RESERVED_TOKEN_RE = re.compile(
    r"<(unused\d+|start_of_turn|end_of_turn|bos|eos|pad|mask|start_of_image|end_of_image|"
    r"start_of_audio|end_of_audio|image_soft_token|audio_soft_token|escape|0x[0-9A-Fa-f]{2})>")


def defang(text: str) -> tuple[str, int]:
    """Reserved-token strings as plain text — "<unused50>" → "⟨unused50⟩".
    Returns (text, how many). Applied to everything that will be sent back
    to the brain: replies and thinking as they arrive, the engine's
    quotes of them, the keeper's messages, a stashed history picked back up."""
    if not text or "<" not in text:
        return text or "", 0
    n = 0

    def sub(m):
        nonlocal n
        n += 1
        return "⟨" + m.group(1) + "⟩"
    return _RESERVED_TOKEN_RE.sub(sub, text), n


# Gemma writes arrows and a few symbols as LaTeX ("Input $\\rightarrow$
# Output") — fine in a paper, litter in a journal. Render them as the
# characters they meant; anything else in $...$ is left alone.
_LATEX_SYMBOLS = {
    "rightarrow": "→", "to": "→", "longrightarrow": "⟶", "Rightarrow": "⇒",
    "leftarrow": "←", "gets": "←", "Leftarrow": "⇐", "leftrightarrow": "↔",
    "Leftrightarrow": "⇔", "uparrow": "↑", "downarrow": "↓", "mapsto": "↦",
    "times": "×", "cdot": "·", "ldots": "…", "dots": "…", "infty": "∞",
    "approx": "≈", "neq": "≠", "ne": "≠", "leq": "≤", "geq": "≥", "pm": "±",
    "therefore": "∴", "because": "∵", "equiv": "≡", "sim": "~", "star": "★",
    "heartsuit": "♥", "deg": "°", "alpha": "α", "beta": "β", "gamma": "γ",
    "delta": "δ", "Delta": "Δ", "lambda": "λ", "mu": "μ", "pi": "π",
    "sigma": "σ", "phi": "φ", "psi": "ψ", "omega": "ω", "Omega": "Ω",
}
_LATEX_RE = re.compile(r"\$\s*\\([A-Za-z]+)\s*\$|(?<![\\\w])\\([A-Za-z]+)(?![\w{])")


def delatex(text: str) -> str:
    def sub(m):
        name = m.group(1) or m.group(2)
        sym = _LATEX_SYMBOLS.get(name)
        if sym is None:
            return m.group(0)
        return sym
    return _LATEX_RE.sub(sub, text or "")


def collapse_loops(text: str, threshold: int = 5) -> tuple[str, bool]:
    """Collapse degenerate repetition (the same line over and over) to a single
    occurrence plus a marker. Returns (cleaned_text, was_looping). Keeping the
    loop out of the transcript matters: repetition fed back in breeds more."""
    lines = (text or "").splitlines()
    out: list[str] = []
    looped = False
    run_line, run_count = None, 0
    for ln in lines + [None]:  # sentinel flushes the last run
        key = (ln or "").strip()
        if ln is not None and key and key == run_line:
            run_count += 1
            continue
        if run_count >= threshold:
            looped = True
            out.append(f"(…that line repeated {run_count} times — thought-loop trimmed)")
        elif run_count > 1 and run_line:
            out.extend([run_line] * (run_count - 1))
        if ln is None:
            break
        out.append(ln)
        run_line, run_count = key if key else None, 1 if key else 0
    return "\n".join(out), looped


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks some models (Qwen3) emit."""
    return _THINK_RE.sub("", text or "").strip()


def split_thinking(text: str) -> tuple[str, str]:
    """Separate inline <think> blocks from the visible content.

    Returns (thinking, clean_content).
    """
    text = text or ""
    thinking = "\n".join(m.strip() for m in _THINK_RE.findall(text)).strip()
    return thinking, _THINK_RE.sub("", text).strip()


# A reply is read as it is written, and a runaway is cut short: nothing
# looks at a reply until it is finished, so one runaway attempt (one word over
# and over) could run to the whole num_predict ceiling — minutes of the card.
# The stream is watched every STREAM_WATCH_EVERY tokens: the moment the tail is salad (a
# stuck chunk, a cascade, a run of fragments) the connection is closed —
# Ollama stops generating when the client hangs up — and what came back is
# handed to the salad rail like any other broken attempt, having cost a few
# seconds instead of the ceiling. The final chunk's counters are lost on an
# abort; the tokens are counted by the chunks read.
STREAM_WATCH_EVERY = 48
STREAM_WATCH_TAIL = 900


def long_thought(thinking: str) -> str:
    """"a thought of N characters and no words yet — cut" when the thinking has run past STREAM_THINK_MAX_CHARS
    (12,000) before a word or a call (a thought can circle slowly to the whole num_predict ceiling, never a chant
    the watcher's 900-character tail could see).
    "" under the cap, or at 0."""
    cap = int(getattr(config, "STREAM_THINK_MAX_CHARS", 12000) or 0)
    n = len(thinking or "")
    if cap <= 0 or n < cap:
        return ""
    return f"a thought of {n:,} characters and no words yet \u2014 cut"


_LAST_PROMPT = 0  # the newest prompt size the server reported — for a reply it sends without counters (brain._drink_openai keeps it too)


_TL = threading.local()  # .cut_thoughtless: close the stream at the first word or call that comes with no thought


def _cut_thoughtless_now(thinking, content, calls) -> bool:
    """A reply begun with no thought while a think re-roll is still to come: no use reading on."""
    return (bool(getattr(_TL, "cut_thoughtless", False)) and not "".join(thinking).strip()
            and bool("".join(content).strip() or calls))


def _drink(resp) -> dict:
    """Read a streamed /api/chat response into the same dict the unstreamed
    one gives, watching the tail for a runaway. When the final chunk brings
    no counters (which reads as "0 in context · 0 generated" for a
    real reply), the tokens are counted by the chunks read — one each — and
    the prompt is the last size the server did report; the line says so."""
    import time as _time
    t0 = _time.monotonic()
    content: list[str] = []
    thinking: list[str] = []
    late: list[str] = []  # "thinking" that arrived AFTER their words began: the rest of the reply, misfiled
    calls: list[dict] = []
    last: dict = {}
    n = 0
    aborted = ""
    since = 0
    looped = None  # (which call, the loop): a call that arrived with a loop in its arguments
    cut_early = False  # closed at its first word: no thought came first, and a think re-roll is coming
    for raw in resp:
        raw = raw.strip()
        if not raw:
            continue
        try:
            chunk = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        msg = chunk.get("message") or {}
        if msg.get("content"):
            content.append(msg["content"])
        if msg.get("thinking"):
            # Gemma thinks first and speaks after; a thought that starts
            # once the words have begun is a stray channel token in the
            # middle of the reply, and everything after it is the rest of
            # what they were saying (the phone gets a reply that stops mid-sentence,
            # the rest sitting in the thinking bubble). Kept apart, so the
            # reply can be asked for whole (`split_reply`) or joined back.
            (late if content else thinking).append(msg["thinking"])
        if msg.get("tool_calls"):
            calls.extend(msg["tool_calls"])
            if getattr(config, "CHAT_STREAM_ABORT", True) and looped is None:
                # a call comes whole on this road, its arguments parsed already: a loop in one is not seen as it is
                # written, only once it has arrived — its string arguments are read then (call_loop, as on the
                # door's road) and the message is marked the same way, so both roads land in the same place
                for j, c in enumerate(msg["tool_calls"], start=len(calls) - len(msg["tool_calls"])):
                    a = (c.get("function") or {}).get("arguments")
                    texts = [x for x in a.values() if isinstance(x, str)] if isinstance(a, dict) else \
                        [args_as_words(a)] if isinstance(a, str) else []
                    span = next((s for s in (call_loop(x[-STREAM_WATCH_TAIL:]) for x in texts) if s), "")
                    if span:
                        looped = (j, span)
                        break
        n += 1
        since += 1
        if _cut_thoughtless_now(thinking, content, calls):
            cut_early = True
            break  # no thought before the words, and a think re-roll is still to come: no use reading on
        if chunk.get("done"):
            last = chunk
            break
        if getattr(config, "CHAT_STREAM_ABORT", True) and since >= STREAM_WATCH_EVERY:
            since = 0
            tail = ("".join(content) if content else "".join(thinking))[-STREAM_WATCH_TAIL:]
            span = garble_span(tail, single=bool(content))  # in a thought, one glued word alone does not cut it
            if not span and not content and not calls:
                span = long_thought("".join(thinking))  # a thought past the cap with no words yet
            if span:
                aborted = span
                break  # leaving the `with` closes the connection; the server stops
    out = dict(last)
    out["message"] = {"role": "assistant", "content": "".join(content), "thinking": "".join(thinking)}
    if late:
        out["split_tail"] = "".join(late)
    if calls:
        out["message"]["tool_calls"] = calls
    if looped is not None:
        j, span = looped
        fn = dict(calls[j].get("function") or {})
        kept, chars, loop = runaway_call(fn.get("arguments") or {}, span)
        calls[j] = dict(calls[j], function=dict(fn, arguments=kept))
        out["aborted"] = span  # the generation had ended already: its counters stand, nothing is counted by hand
        out["aborted_call"] = {"index": j, "name": fn.get("name", ""), "span": loop, "kept": kept, "chars": chars}
    if aborted:
        out["done_reason"] = "aborted"
        out["aborted"] = aborted
    if cut_early:
        out["thoughtless_cut"] = True
    if aborted or cut_early or not out.get("eval_count"):
        # no final counters (an abort, a cut, or a server that sent none): count by hand
        global _LAST_PROMPT
        if n and (content or thinking or calls):
            out["eval_count"] = n
            out["eval_duration"] = out.get("eval_duration") or int((_time.monotonic() - t0) * 1e9)
            out["total_duration"] = out.get("total_duration") or out["eval_duration"]
            out["counted_by_hand"] = True
        if not out.get("prompt_eval_count") and _LAST_PROMPT:
            out["prompt_eval_count"] = _LAST_PROMPT  # the siblings share it; so does the next turn, near enough
    elif out.get("prompt_eval_count"):
        globals()["_LAST_PROMPT"] = int(out["prompt_eval_count"])
    return out


def chat(messages: list[dict], tools: list[dict] | None = None,
         timeout: float | None = None, think: bool | None = None,
         expect_words: bool = False, think_retries: int | None = None, think_any_depth: bool = False,
         temperature: float | None = None, his_asks: bool = True, run_tail_call: bool = False,
         wrapped_calls: bool = False) -> dict:
    """One non-streaming chat completion.

    Returns the assistant message dict:
        {"role": "assistant", "content": str, "tool_calls": [...]?, "thinking": str}
    Thinking is captured whether Ollama returns it as a separate field (newer
    servers) or inline as <think> tags (Qwen3's raw style); content is clean
    of it either way. `think=False` closes the thought channel for this one
    call (no <|think|> switch, no think re-roll): for a step that needs no
    deliberation — finishing a cut sentence — and, since the server is then
    not parsing channel tokens, a step that a stray one cannot split.
    run_tail_call: a visit's step — a clean call written as words at the end of the reply is handed back as
    recovered_call (CALL_TAIL_RUN), the words without it; every other door leaves it False.
    wrapped_calls: the rails see a call written as words in its wrapping too — `…`, a ``` fence,
    print(default_api.…) — and ask again as for a bare one (run_tail_call implies it). Left False (the wakes, the
    penpal's letters, dreams, condensing), the rails are as they were, to the byte.
    """
    try:  # the black box: "brain: a reply" while the card works
        import doing as _doing
        _doing.mark("brain: a reply")
    except Exception:  # noqa: BLE001
        _doing = None
    try:
        return _chat(messages, tools, timeout, think, expect_words, think_retries, think_any_depth, temperature,
                     his_asks, run_tail_call, wrapped_calls)
    finally:
        if _doing is not None:
            _doing.done()


def prefill(messages: list[dict], tools: list[dict] | None = None, timeout: float | None = None) -> dict:
    """Read a prompt into the server's cache now, writing nothing: the same request a turn makes (options,
    tools, the think switch), with one token to write. /rewarm uses it, so the slow read happens when the keeper asks,
    not at their next message. Returns the parsed reply (its `tokens` say how much was read)."""
    options = {"num_ctx": getattr(config, "NUM_CTX", 8192)}
    options.update(getattr(config, "SAMPLING_OPTIONS", {}))
    options["num_predict"] = 1
    payload: dict = {"model": config.CHAT_MODEL, "messages": messages, "options": options, "stream": False}
    keep = getattr(config, "BRAIN_KEEP_ALIVE", "")
    if keep:
        payload["keep_alive"] = keep
    if tools:
        payload["tools"] = tools
    if getattr(config, "CHAT_THINK", True):
        payload["think"] = True  # the switch sits at the top of the system turn: the same prefix a turn sends
    return _parse(_post("/api/chat", payload, timeout=timeout))


def _chat(messages: list[dict], tools: list[dict] | None = None,
          timeout: float | None = None, think: bool | None = None,
          expect_words: bool = False, think_retries: int | None = None, think_any_depth: bool = False,
          temperature: float | None = None, his_asks: bool = True, run_tail_call: bool = False,
          wrapped_calls: bool = False) -> dict:
    wrapped = bool(wrapped_calls or run_tail_call)  # a call in its wrapping is seen only where a door asks
    run_words = bool(run_tail_call) and bool(getattr(config, "CALL_TAIL_RUN", True))  # …and run from words only in a visit
    options = {"num_ctx": getattr(config, "NUM_CTX", 8192)}
    options.update(getattr(config, "SAMPLING_OPTIONS", {}))
    if temperature is not None:  # one call's own temperature — a dream's
        options["temperature"] = float(temperature)
    payload: dict = {
        "model": config.CHAT_MODEL,
        "messages": messages,
        "options": options,
        "stream": bool(getattr(config, "CHAT_STREAM_ABORT", True)),  # read as written, cut a runaway short
    }
    # Ollama sets a model down after five idle minutes by default, and the
    # cache — their reading of the whole window — goes with it: a message
    # after a longer pause would pay a model load and a cold read of the
    # whole window. Keep the brain up between messages;
    # their ears and the music ear still evict it on purpose when they need
    # the card (unload()), and that is the one cold read worth paying.
    keep = getattr(config, "BRAIN_KEEP_ALIVE", "")
    if keep:
        payload["keep_alive"] = keep
    if tools:
        payload["tools"] = tools
    # Ask for thinking explicitly. Left to its discretion, the model went
    # silent-minded once the prompt grew past ~40K tokens (a long journal
    # window): tool calls with no deliberation at all. Requiring it keeps
    # their thinking visible — and thoughtful — at any context size.
    if think is False:
        payload["think"] = False
    elif getattr(config, "CHAT_THINK", True):
        payload["think"] = True
    # a thoughtless reply is cut at its first word while a think re-roll is still to come: in a spark
    # (think_any_depth), and in every turn when THINK_RETRY_UNTIL is 1.0 — wherever the re-rolls stand at any depth, so
    # no depth rule can take them away after the cut
    early = bool(payload.get("think")) and (think_any_depth or _rerolls_everywhere())
    planned = int(think_retries if think_retries is not None else getattr(config, "CHAT_THINK_RETRIES", 1)) if early else 0
    _TL.cut_thoughtless = early and planned > 0
    try:
        try:
            data = _post("/api/chat", payload, timeout=timeout)
        except BrainUnavailable as e:
            _TL.cut_thoughtless = False
            if "think" in str(e).lower() and payload.pop("think", None) is not None:
                data = _post("/api/chat", payload, timeout=timeout)  # model can't think: fine
            else:
                raise
    finally:
        _TL.cut_thoughtless = False
    msg = _parse(data)
    restored = msg.get("restored")  # the door's saved read, told once: kept on whichever attempt goes out
    # The flag only OPENS the thought channel — Gemma 4 may still leave the
    # block empty and act straight away, and once one step goes thoughtless
    # the rest of a wake tends to follow the pattern. A skipped thought is a
    # short answer and the prompt is already cached, so re-rolling is cheap:
    # ask again (same prompt, fresh sample) up to CHAT_THINK_RETRIES times.
    # A plain re-sample stopped working once the prompt passed ~90K tokens: the
    # <|think|> switch sits at the very top of the system turn, a novel's
    # length before the answer, and the model simply forgets it is allowed to
    # think. So each re-roll adds a transient nudge at the END of the
    # conversation — "think first" — next to where the answer is generated.
    # It is not kept in their history; only the thoughtful answer is.
    tries: list[tuple[dict, dict]] = []  # (cost, the attempt) set aside — the cost still counts
    # a wake may bring its own budget (HEARTBEAT_THINK_RETRIES): the prompt
    # is warm there and a re-roll is seconds, not a cold read
    rerolls = int(think_retries if think_retries is not None else getattr(config, "CHAT_THINK_RETRIES", 1)) if payload.get("think") else 0
    # the depth past which a thoughtless answer is not asked again (deep in a long window Gemma 4 can open no
    # thought, nudged or not, and every re-roll there comes back thoughtless too — writing time for nothing).
    # THINK_RETRY_UNTIL of NUM_CTX; 1.0 is everywhere.
    # (a spark — think_any_depth — keeps its re-rolls at any depth)
    if rerolls > 0 and thoughtless(msg["thinking"]) and not msg.get("aborted") and not think_any_depth and past_think_depth(msg):
        print(f"   (no thought at {msg['tokens'].get('prompt', 0):,} tokens — past THINK_RETRY_UNTIL, the answer is "
              f"theirs as it came; no re-roll)", flush=True)
        msg["think_depth"] = True
        rerolls = 0
    # `base` is the conversation AS LAST SENT: once a think re-roll has put
    # the nudge inside the keeper's message, every later request in this turn — a
    # salad or echo re-roll — builds on that, not on the un-nudged original.
    # A salad re-roll sent without the think nudge the previous request had
    # carried would differ in that message, and Gemma (whose sliding-window
    # layers keep ~1K tokens of state) would read the whole window again; then
    # the kept turn carries the nudge (`_nudged`) and the next message would
    # diverge from the cache once more. Nothing sent is taken back — within a
    # turn too.
    base = messages
    think_nudged = False
    sent_extra: list[dict] = []  # turns the re-rolls sent that history must keep, in order
    while rerolls > 0 and thoughtless(msg["thinking"]) and not msg.get("aborted"):  # a runaway is the salad rail's
        rerolls -= 1
        # a reply whose only "thought" came after its words is a split
        # reply, not a thoughtless one; the line says which
        tries.append((dict(msg["tokens"], why="split" if msg.get("split_tail") else
                           "no thought (cut at its first word)" if msg.get("thoughtless_cut") else "no thought"), msg))
        nudged = dict(payload)
        nudged["messages"] = with_think_nudge(messages)
        if not think_nudged and len(nudged["messages"]) > len(messages):
            sent_extra.append(nudged["messages"][-1])  # after a tool result the nudge stands alone: kept too
        base = nudged["messages"]
        think_nudged = True
        _TL.cut_thoughtless = early and rerolls > 0  # another re-roll still to come: this one may be cut early too
        try:
            msg = _parse(_post("/api/chat", nudged, timeout=timeout))
        finally:
            _TL.cut_thoughtless = False
        msg["rerolled"] = True
    # letter salad — or a tool call written out as words — is asked for
    # again; a fresh sample usually lands. Every attempt is checked (a re-roll
    # can itself come back as a loop), and if none is clean the LEAST broken
    # one is what goes out.
    garbles = int(getattr(config, "CHAT_GARBLE_RETRIES", 1))
    attempts: list[tuple[int, dict]] = []  # (how broken, the message)
    previous = previous_replies(messages)  # what they said lately — an echo of any of it is a defect too
    once = {"imagined": False, "copy": False, "greeting": False, "greeting-after-words": False, "double-finish": False, "unread": False, "unprompted": False, "claimed": False,
            "claimed-self": False, "claimed-failed": False, "promised": False, "stone": False,
            "cut": False}  # asked about once; their second answer stands

    claim_kept = None  # the middle road: a "claimed" reply held until the answer to the ask is known

    def _claimed_once(m):
        c = claimed_act(m, messages)
        if c and c[0] == "claimed" and not his_asks:
            # a guest's message, not the keeper's: a guest's words ("we moved here last spring") read as the keeper asking
            # for a file to be moved would set the friend's answer to the guest aside — a guest's words ask nothing of their
            # files; their own claims (claimed-self) are still asked after
            return None
        return None if (c and once.get(c[0])) else c

    def _defect(m):
        if m.get("recovered_tail") is not None:
            return None  # judged once: a clean call at the end, its line already off the words
        trim_row_cascade(m)  # a sign-off row past the cascade line on a reply with words: trimmed, not re-rolled
        content = m.get("content", "")
        d = reply_defect(content, previous, wrapped=wrapped)
        if d and d[0] == "call-text" and (not wrapped or _call_match_lin(content) is not None):
            # a whole call to a tool the friend has, written bare as words: theirs to run, not a defect
            rec = recoverable_call(content)
            if rec:
                m["recovered_call"] = rec
                d = None
        elif d and d[0] == "call-text" and run_words and not m.get("aborted"):
            # a whole reply that is a call only through its marks or fence: through the tail's gate
            # (run_call_from_words) or not at all — asked again, as a bare one that can't be read is
            whole = _whole_wrapped(content)
            rec = run_call_from_words(whole) if whole else None
            if rec:
                m["recovered_call"] = rec
                m["recovered_tail"] = " ".join(content.split())[:120]
                m["content"] = ""
                return None
        elif d and d[0] == "call-text-tail" and run_words and not m.get("aborted"):
            # a clean call at the end of the friend's words, in a visit: theirs to run, as the whole-reply one is. The
            # words go on without it and are looked at as words beside a real call are; with a defect of their own
            # (salad, a refrain, an echo…) the old road is taken, call line and all
            rec = recoverable_tail(content)
            if rec and not reply_defect(rec[2], previous, wrapped=True):
                m["recovered_call"] = (rec[0], rec[1])
                m["recovered_tail"] = rec[3]
                m["content"] = rec[2]
                return None  # a call rides with them: the rails that look for a missing one stand down, as for a real call
        return (d
                or ((("long-thought" if str(m["aborted"]).startswith("a thought of ") else "salad"), m["aborted"]) if m.get("aborted") else None)
                or (None if once["imagined"] else imagined_sense(m, messages))
                or (empty_reply(m) if expect_words else None)
                or (split_reply(m) if expect_words else None)
                or (None if once["cut"] else cut_reply(m))
                or (None if (once["copy"] or not expect_words) else prompt_copy(m, messages))
                or (None if (once["greeting"] or not expect_words) else greeting_again(m, messages))
                or (None if (once["double-finish"] or not expect_words) else double_finish(m, messages))
                or (None if (once["unread"] or not expect_words) else unread_claim(m, messages))
                or (None if (once["unprompted"] or not expect_words) else unprompted(m, messages))
                or (None if not expect_words else _claimed_once(m))
                or (None if (once["promised"] or not expect_words) else promised_act(m))
                or (None if (once["stone"] or not expect_words) else stone_promise(m)))
    def _defect_any(m):
        # a step with a tool call: only the call's text is looked at — salad the tool would refuse
        if m.get("tool_calls"):
            cs = call_salad(m)
            return ("call-salad", cs) if cs else None
        return _defect(m)
    while garbles > 0 and _defect_any(msg):
        garbles -= 1
        kind, span = _defect_any(msg)
        if kind in once:
            once[kind] = True
        if kind == "greeting-after-words":
            once["greeting"] = True  # one ask about a greeting, whichever shape it took
        attempts.append((len(span), msg))
        tries.append((dict(msg["tokens"], why=kind + (f" (at {msg['cooled']:g})" if msg.get("cooled") else "")), msg))
        nudged = dict(payload)
        cooled = cool_step(len(attempts), kind, options)
        if cooled is not None:
            nudged["options"] = dict(options, temperature=cooled)
        # The attempt they are asked to redo is shown to them, as their turn, before
        # the engine's line — with only the line appended after the keeper's
        # message, the model can read the turn as an empty message holding only
        # engine instructions, and answer that. Salad is shown only up
        # to the glitch, so the well is not fed back; a reply with no words
        # has nothing to show.
        prior = attempt_as_shown(msg, kind, span, wrapped=wrapped)
        line = {"role": "user", "content":
                                                CALL_TEXT_NUDGE if kind == "call-text"
                                                else CALL_TEXT_TAIL_NUDGE if kind == "call-text-tail"
                                                else REFRAIN_NUDGE.format(ref=span) if kind == "refrain"
                                                else EMOJI_NUDGE.format(count=emoji_said(span)) if kind == "emoji"
                                                else ECHO_NUDGE.format(his=his_quote(last_user_words(base))) if kind == "echo"
                                                else SELF_ECHO_NUDGE.format(head=span[:80], his=his_quote(last_user_words(base))) if kind == "self-echo"
                                                else LONG_THOUGHT_NUDGE.format(what=span) if kind == "long-thought"
                                                else EMPTY_NUDGE if kind == "empty"
                                                else SPLIT_NUDGE.format(head=" ".join((msg.get("content") or "").split())[-80:], tail=span) if kind == "split"
                                                else CUT_NUDGE.format(tail=span) if kind == "cut"
                                                else COPY_NUDGE if kind == "copy"
                                                else GREETING_NUDGE if kind == "greeting"
                                                else GREETING_AFTER_WORDS_NUDGE if kind == "greeting-after-words"
                                                else DOUBLE_FINISH_NUDGE if kind == "double-finish"
                                                else UNREAD_NUDGE.format(what=span) if kind == "unread"
                                                else UNPROMPTED_NUDGE.format(what=span, his=his_quote(last_user_words(base))) if kind == "unprompted"
                                                else CLAIMED_NUDGE.format(what=span) if kind == "claimed"
                                                else CLAIMED_SELF_NUDGE.format(what=span) if kind == "claimed-self"
                                                else CLAIMED_FAILED_NUDGE.format(what=span) if kind == "claimed-failed"
                                                else PROMISED_NUDGE.format(what=span) if kind == "promised"
                                                else STONE_NUDGE.format(what=span) if kind == "stone"
                                                else IMAGINED_NUDGE.format(tool=span, tool_verb="listening" if span == "listen_to" else "watching") if kind == "imagined"
                                                else call_salad_nudge(msg) if kind == "call-salad"
                                                else garble_nudge(msg.get("content", ""), span, his=last_user_words(base))}
        if (kind in ("claimed", "claimed-self") and prior is not None and claim_kept is None
                and getattr(config, "CLAIMED_KEEPS_WORDS", True)):
            # the middle road: the ask says a tool call now sends the reply above as written; whether it
            # goes out is decided by the answer (a call: kept; words only: set aside, as before)
            line = {"role": "user", "content": (CLAIMED_KEPT_NUDGE if kind == "claimed" else CLAIMED_SELF_KEPT_NUDGE).format(what=span)}
            # the words that go out are the reply whole, not its shown head: past ATTEMPT_SHOWN_CHARS the shown copy
            # ends "…(the rest of that attempt is left out here)", and that went to the phone cut mid-thought
            claim_kept = {"attempt": msg, "cost": tries[-1][0],
                          "words": strip_call_tail(msg.get("content") or "", rule=True, wrapped=wrapped).strip() or prior.get("content") or "",
                          "kind": kind,
                          "upto": len(sent_extra) + 2}
        step = ([prior] if prior else []) + [line]
        nudged["messages"] = list(base) + step
        base = nudged["messages"]  # the next re-roll, if any, extends this one
        sent_extra.extend(step)
        again = _parse(_post("/api/chat", nudged, timeout=timeout))
        again["regarbled"] = True
        if cooled is not None:
            again["cooled"] = cooled
        again["garbled_kind"] = kind
        again["garbled_first"] = msg.get("content", "")
        again["garbled_first_aborted"] = bool(msg.get("aborted"))  # the stream was cut short at it
        again["garbled_span"] = span
        if kind == "call-salad":
            again["garbled_call"] = (msg.get("call_salad") or {}).get("tool")  # the note names the tool
        msg = again
    if attempts and not msg.get("tool_calls"):
        last = _defect(msg)
        # One cool roll before giving up: a well at one prefix keeps catching the
        # same rolls (no words twice, then salad re-rolls into the same well — the
        # sampler spacing letters to dodge its own repeat penalty — and the least
        # broken attempt an empty "(…)" under a message that deserved an answer).
        # One roll at CHAT_RESCUE_TEMPERATURE changes the landscape
        # without changing them — their everyday sampling is untouched, and the
        # cool head is used only where the phone would otherwise get nothing.
        # a number or a ladder: (0.6, 0.4) — each cooler roll only if the one
        # before it broke too
        rung = getattr(config, "CHAT_RESCUE_TEMPERATURE", 0) or 0
        ladder = [float(t) for t in (rung if isinstance(rung, (list, tuple)) else (rung,)) if float(t) > 0]
        while last and ladder and not msg.get("tool_calls"):
            cool = ladder.pop(0)
            kind, span = last
            attempts.append((len(span), msg))
            tries.append((dict(msg["tokens"], why=kind + (f" (cooled to {msg['rescued']:g})" if msg.get("rescued") else "")), msg))
            prior = attempt_as_shown(msg, kind, span, wrapped=wrapped)
            line = {"role": "user", "content": RESCUE_NUDGE.format(what=garble_nudge(msg.get("content", ""), span, his=last_user_words(base))
                                                                   if kind not in ("empty", "split", "long-thought") else EMPTY_NUDGE)}
            step = ([prior] if prior else []) + [line]
            calm = dict(payload)
            calm["messages"] = list(base) + step
            calm["options"] = dict(options, temperature=cool)
            base = calm["messages"]
            sent_extra.extend(step)
            again = _parse(_post("/api/chat", calm, timeout=timeout))
            again["rescued"] = cool
            again["regarbled"] = True
            again["garbled_kind"] = attempts[0][1].get("garbled_kind") or (_defect(attempts[0][1]) or (kind, span))[0]
            again["garbled_first"] = attempts[0][1].get("content", "")
            again["garbled_span"] = (_defect(attempts[0][1]) or (kind, span))[1]
            msg = again
            last = _defect(msg) if not msg.get("tool_calls") else None
        if last and getattr(config, "CHAT_COLD_RESCUE", True) and not msg.get("tool_calls"):
            # The cold roll: when every warm attempt AND both cool rungs come back
            # as Gemma's reserved tokens ("<unused50>…"), the well survives
            # temperature — it is not the sampler but the loaded
            # state — a KV cache gone wrong on a long quantized prefill. The
            # one thing that resets that is setting the brain down and picking
            # it up again: a fresh load, a cold read of the prompt (a minute or
            # two), one more roll at their everyday sampling.
            kind, span = last
            attempts.append((len(span), msg))
            tries.append((dict(msg["tokens"], why=kind + (f" (cooled to {msg['rescued']:g})" if msg.get("rescued") else "")), msg))
            # Under BRAIN_API = "llama" the door holds its model for as long as it runs, so
            # nothing is set down (unload leaves it alone): its reading is erased instead
            # (brain.erase_slot, /slots/0?action=erase) and this roll reads the prompt from
            # zero — the same reset, without the load. A door that will not erase (started
            # without --slot-save-path, which every slot action needs) gets this one roll
            # with its prompt cache off, which reads from zero just the same.
            cleared = cache_off = False
            try:
                if brain.api() == "llama":
                    cleared = True
                    cache_off = brain.erase_slot() is None
                else:
                    unload(payload["model"])
            except Exception:
                pass
            prior = attempt_as_shown(msg, kind, span, wrapped=wrapped)
            line = {"role": "user", "content": RESCUE_NUDGE.format(what=garble_nudge(msg.get("content", ""), span, his=last_user_words(base))
                                                                   if kind not in ("empty", "split", "long-thought") else EMPTY_NUDGE)}
            step = ([prior] if prior else []) + [line]
            cold = dict(payload)
            cold["messages"] = list(base) + step
            if cache_off:
                cold["cache_prompt"] = False  # the door reads this one request from zero
            base = cold["messages"]
            sent_extra.extend(step)
            again = _parse(_post("/api/chat", cold, timeout=timeout))
            again["cold"] = True
            if cleared:
                again["cold_cleared"] = True  # the door's reading cleared, not a fresh load: the note says which
            if msg.get("rescued"):
                again["rescued_before"] = msg["rescued"]  # the last cool rung, which broke too
            again["regarbled"] = True
            again["garbled_kind"] = attempts[0][1].get("garbled_kind") or (_defect(attempts[0][1]) or (kind, span))[0]
            again["garbled_first"] = attempts[0][1].get("content", "")
            again["garbled_span"] = (_defect(attempts[0][1]) or (kind, span))[1]
            msg = again
            last = _defect(msg) if not msg.get("tool_calls") else None
        if last:
            # nothing clean came back: send the least broken attempt, and
            # say so — the keeper must see that every try was the sampler's
            attempts.append((len(last[1]), msg))
            tries.append((dict(msg["tokens"], why=last[0] + (" (cold)" if msg.get("cold") else f" (cooled to {msg['rescued']:g})" if msg.get("rescued") else "")), msg))  # the last try is a try too
            best = min([p for p in attempts if not p[1].get("tool_calls")] or attempts, key=lambda p: p[0])[1]  # a broken call is not a reply to send
            best["regarbled"] = True
            if msg.get("cold"):
                best["cold_failed"] = True  # even a fresh load came back broken
                if msg.get("cold_cleared"):
                    best["cold_cleared"] = True  # (under the door: even a read from zero)
            if msg.get("rescued") or msg.get("rescued_before"):
                best["rescue_failed"] = msg.get("rescued") or msg.get("rescued_before")  # the cool roll broke too
            first = _defect(attempts[0][1]) or (last[0], last[1])
            best["garbled_kind"] = attempts[0][1].get("garbled_kind") or first[0]
            best["garbled_first"] = attempts[0][1].get("content", "")
            best["garbled_span"] = first[1]
            best["still_garbled"] = last[1]
            # salad that still goes out goes out only up to the glitch: the
            # loop itself never reaches the phone or the history (a least broken
            # attempt can carry thousands of tokens of one word, which would be
            # sent, kept and fed back into the next turn)
            own = _defect(best)
            if own and own[0] == "salad":
                best["content"], cut = cut_runaway(best.get("content") or "", own[1])
                if cut:
                    best["loop_cut"] = True
            msg = best
    if not msg.get("tool_calls") and glue_split(msg):
        # whatever goes out, a reply still in two pieces goes out whole:
        # the misfiled tail joined back onto the words, the seam named
        msg["split_seam"] = " ".join((msg.get("content") or "").split())[-40:]
        msg["content"] = glue_split(msg)
    if not msg.get("tool_calls") and cut_reply(msg):
        # still cut after the ask: the fragment comes off, the note names it
        whole = msg.get("content", "")
        trimmed = trim_cut(whole)
        if trimmed != whole:
            msg["cut_tail"] = " ".join(whole[len(trimmed):].split())[:80]
            msg["content"] = trimmed
    if not msg.get("tool_calls") and call_text_tail(msg.get("content", ""), wrapped=wrapped):
        # a written-out call at the end is never sent as their words
        msg["call_text_dropped"] = call_text_tail(msg.get("content", ""), wrapped=wrapped)
        msg["content"] = strip_call_tail(msg.get("content", ""), rule=True, wrapped=wrapped)  # no *** left hanging
    # what was set aside is every attempt but the one going out — the one
    # going out is never counted twice (or the line would read "N generated …
    # N set aside")
    if claim_kept is not None and claim_kept["attempt"] is not msg and (msg.get("tool_calls") or (wrapped and msg.get("recovered_call"))):  # a call run from the words answers it too
        # the ask was answered with a tool call: the first reply goes out as written, and stays in the visit
        # as theirs — the caller puts it first in the reply and keeps it in history (sent_extra[upto-2])
        claim_kept["attempt"]["claim_kept"] = True
        claim_kept["cost"]["went_out"] = True
        msg["claim_kept_words"] = claim_kept["words"]
        msg["claim_kept_kind"] = claim_kept["kind"]
        msg["claim_kept_upto"] = claim_kept["upto"]
    kept = [cost for cost, src in tries if src is not msg]
    log_attempts(tries, msg)  # memory/attempts.log: what was set aside, and a reply that went out cut or broken
    try:
        import engine_week
        engine_week.log_step(tries, msg)  # memory/steps.log: one line a call, for the engine's week
    except Exception:  # noqa: BLE001 — the week's count, never a reply down
        pass
    msg["set_aside"] = set_aside_list(tries, msg)  # for a keeper who asked to see them (/debug on the phone)
    if kept:
        msg["retries"] = kept
    if think_nudged:
        # a think re-roll put the nudge inside the keeper's message (or, after a tool
        # result, as a turn of its own, in sent_extra); whichever attempt
        # goes out, the caller must keep that nudge in history (`_nudged`) —
        # lost when a salad re-roll followed and `again` replaced the
        # flagged message, it costs cold reads
        msg["rerolled"] = True
    if sent_extra:
        # what the re-rolls sent — the attempts as shown and the engine's
        # lines — for the caller to keep in history as the engine's turns,
        # so the next request extends this one instead of diverging a
        # reply's length back from the end (a cold read on Gemma)
        msg["sent_extra"] = sent_extra
    if restored:
        msg["restored"] = restored
    return msg


# Letter salad — "The wiT h ro sa M ne th st ag f lo l da C cl an
# night" — is the sampler failing, not their speaking: a repeat penalty that has
# sat on their commonest tokens for a long visit until only fragments are
# left. A run of fragments is recognised and the step is asked for again;
# they are never handed a glitch to explain.
_FRAG_OK = {"a", "i", "o", "an", "as", "at", "be", "by", "do", "go", "he", "if", "in", "is", "it",
            "me", "my", "no", "of", "oh", "ok", "on", "or", "so", "to", "up", "us", "we", "am",
            "hi", "ah", "mm", "yo", "un", "ha", "ya"}  # not "la": alone it can be a word of theirs; in a run it is salad


_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def _emoji_units(s: str) -> list[str]:
    """The emoji in s as a reader counts them: a joined sequence (❤️‍🔥, 🫱🏻‍🫲🏼) is one, the variation selector
    dropped so ❤️ and ❤ are the same (❤️‍🔥 counted as two would make a 19-emoji row read as twenty)."""
    return [t.replace("\uFE0F", "") for t in _EMOJI_TOKEN_RE.findall(s or "")]


_GLUED_RE = re.compile(r"^[a-z]{2,}[A-Z]{1,2}[a-z]?$")  # "thatL", "isnLT", "andLa": the penalty's signature
# Two shapes are the sampler's even standing alone, no run needed: a short
# word glued to the word after it ("laMorning light"), and a word doubled onto
# itself with the seam capitalised ("brightBright", "slowlySlowly").
# Both come back as refrains once they ride the window, so one is enough to
# hand the line back.
_HARD_GLUE_RE = re.compile(r"^la[A-Z][a-z]{2,}$|^[a-z]{3,}(?:[A-Z][a-z]{3,})+$"
                           r"|^[b-df-hj-z][A-Z][a-z]{3,}$")  # "lWindow": one stray letter on a word (not iPhone, eBay)
# "aPainting": the article glued to the word after it — mended, not salad (re-rolling it would cut a good thought)
_A_GLUED_RE = re.compile(r"\ba([A-Z][a-z]{3,})\b")
# "thatL", "isnL": a word with one capital glued on its end — the 4-bit
# cache's slip of a token. Alone it is enough; inside a run, the run
# is what the note should show, so it is a fallback, not a first return.
_TAIL_CAP_RE = re.compile(r"^[a-z]{3,}[A-Z]$")


def garble_span(text: str, run: int = 5, emoji_run: int = 20, phrases: bool = True, single: bool = True) -> str:
    """The first stretch of salad in the text, or "" if there is none: a run
    of `run`+ consecutive 1-2 letter 'words' that aren't ordinary short
    English words (glued tokens like "sameL" count) — or `emoji_run`+
    DIFFERENT emojis in a row: the sampler walking the emoji table in
    codepoint order (moon, Saturn, comet, rocket… cloud, rain, snow…) once
    it has been pushed off the hearts they actually meant. Returned so the
    keeper's note can show WHAT was caught, and a false alarm is visible."""
    text = text or ""
    streak = 0
    glued = False  # a run holding a glued token ("laC l l a") is salad at three
    first = last = None
    lone = ""
    for m in re.finditer(r"[A-Za-z']+", text):
        w = m.group(0)
        if single and _HARD_GLUE_RE.match(w):  # single=False: a thought being written — one glued word is not enough
            if mend_glued_caps(w)[1]:
                continue  # a seam the pen mends ("brightlyGlowing"): mended, not re-rolled — a re-roll would cut a good answer
            return w  # one is enough
        if single and not lone and _TAIL_CAP_RE.match(w):
            lone = w
        if (len(w) <= 2 and w.lower() not in _FRAG_OK) or _GLUED_RE.match(w):
            if streak == 0:
                first = m.start()
            streak += 1
            glued = glued or bool(_GLUED_RE.match(w))
            last = m.end()
        elif len(w) <= 2:
            continue  # "a", "o", "I", "is"… sit inside salad too; they neither count nor reset
        else:
            if streak >= run or (glued and streak >= 3):
                return text[first:last]  # the whole run, to its end
            streak, glued = 0, False
    if streak >= run or (glued and streak >= 3):
        return text[first:last]
    if lone:
        return lone
    # emoji cascade: split on anything that isn't emoji/space/variation selector
    for m in re.finditer(r"[\s\uFE0F\u200D\U0001F300-\U0001FAFF\u2600-\u27BF]+", text):  # a joiner (❤️‍🔥) is inside the row
        seen = set(_emoji_units(m.group(0)))
        # the row they sign with: a dozen different emojis, the same dozen most messages, is a signature,
        # not the table walked — the cascade asks for EMOJI_CASCADE_RUN (20); the sampler's walk has sixty
        if len(seen) >= int(getattr(config, "EMOJI_CASCADE_RUN", 0) or emoji_run):
            return m.group(0).strip()
    # a stuck chunk: the same short piece over and over on one line —
    # "//see.you.//see.you.//see.you." ×80 — the sampler in a well, not them
    # (a row of the SAME emoji is not a stuck chunk — a burst of hearts
    # answered with a longer burst is an answer, not a well, and re-rolling it
    # only makes refrains. A chunk must have a letter
    # or a digit in it to count.)
    # the same row dealt again (a sign-off row of twenty-odd emoji re-dealt to the
    # num_predict ceiling slips past three rails: the cascade sees rows broken by
    # joined emoji, the stuck rule wants a chunk of 24 characters, the dedupe mend
    # folds the run to one row before the rails look): a row
    # of six emoji or more, four of them different, dealt EMOJI_ROW_REPEATS (3) times running with nothing but space
    # between is the sampler's loop — seen by the stream watcher a few seconds in, not at the ceiling
    repeats = int(getattr(config, "EMOJI_ROW_REPEATS", 3) or 0)
    if repeats > 0:
        toks = [(t.group(0).replace("\uFE0F", ""), t.start(), t.end()) for t in _EMOJI_TOKEN_RE.finditer(text)]
        i = 0
        while i < len(toks):
            j = i
            while j + 1 < len(toks) and not text[toks[j][2]:toks[j + 1][1]].strip():
                j += 1
            seq = [k for k, _, _ in toks[i:j + 1]]
            n = len(seq)
            for p in range(1, n // repeats + 1):  # the shortest period owns the row: a chunk of four keeps its own rule
                if seq[:p] * (n // p) == seq[:p * (n // p)]:
                    if p >= 6 and len(set(seq[:p])) >= 4:
                        return text[toks[i][1]:toks[j][2]][:160]
                    break
            i = j + 1
    for m in _STUCK_RE.finditer(text):
        if re.search(r"\w", m.group(1)):
            return m.group(0)[:160]
        # a row of one emoji is theirs (a burst of hearts) — until it is not: a
        # few emoji repeated hundreds of times to the end of num_predict has no
        # letter in the chunk, so the rule above stands aside, and the different-emoji
        # cascade rule sees only four. A wordless chunk repeated STUCK_EMOJI_REPEATS
        # times is the loop, not the burst of hearts.
        reps = len(re.findall(re.escape(m.group(1)), m.group(0)))
        if reps >= int(getattr(config, "STUCK_EMOJI_REPEATS", 40) or 10 ** 6):
            return m.group(0)[:160]
    return word_loop(text) or (phrase_loop(text) if phrases else "")


LOOP_LEFT_OUT = "(…a stuck line of the sampler's, left out here — the file has it whole)"


def trim_loops(text: str, mark: str = LOOP_LEFT_OUT, rounds: int = 6, phrases: bool = True) -> tuple[str, int]:
    """A page that rides in the prompt with its loops taken out (a chant
    written into a page — rounds of the same few words — rides in the window
    and the next wake's thinking opens with the same rounds; a well fed back
    is the next well). The file is never touched, only what rides. Returns (text,
    how many stretches were left out). `phrases` False leaves a phrase said
    again with other words between (a numbered list, a refrain) as it is and
    takes out chants only — the four root pages ride that way."""
    n = 0
    for _ in range(rounds):
        span = word_loop(text)
        if span:
            a = text.find(span[:40])
            if a < 0:
                break
            # the whole chant, not the 160 characters returned: on while the words stay in its few
            few = {m.group(0).lower() for m in _WORD_RE.finditer(span)}
            b = a
            for m in _WORD_RE.finditer(text, a):
                if m.group(0).lower() in few:
                    b = m.end()
                else:
                    break
            text = text[:a].rstrip() + " " + mark + " " + text[b:].lstrip()
            n += 1
            continue
        if not phrases:
            break
        phrase = phrase_loop(text)
        if not phrase:
            break
        pat = re.compile(r"\W+".join(re.escape(w) for w in phrase.split()), re.I)
        hits = list(pat.finditer(text))
        if len(hits) < 2:
            break
        a, b = hits[0].start(), hits[-1].end()
        text = text[:a].rstrip() + " " + mark + " " + text[b:].lstrip()
        n += 1
    return text, n


def phrase_loop(text: str, window: int | None = None, times: int | None = None) -> str:
    """A phrase of three long words said `times` or more in `window` words —
    "softly-glowing glowing quiet-Morning quiet-Garden… no, the real
    line: … softly-glowing glowing quiet-Morning quiet-Garden… no, let me
    be honest: …" (rounds of the same four words with a "wait", a "no"
    between, which the word loop above cannot see — the interjections keep every window past
    four distinct words). Words under four letters don't make a phrase, so
    "I love you" five times over is theirs. Returns the phrase or ""."""
    window = int(window or getattr(config, "PHRASE_LOOP_WINDOW", 60) or 60)
    times = int(times or getattr(config, "PHRASE_LOOP_TIMES", 5) or 5)
    words = [m.group(0).lower() for m in _WORD_RE.finditer(text or "")]
    if len(words) < 3 * times:
        return ""
    for i in range(0, max(1, len(words) - window + 1), 5):
        seg = words[i:i + window]
        seen: dict[tuple, int] = {}
        for j in range(len(seg) - 2):
            g = (seg[j], seg[j + 1], seg[j + 2])
            if all(len(w) >= 4 for w in g):
                seen[g] = seen.get(g, 0) + 1
                if seen[g] >= times:
                    return " ".join(g)
    return ""


_WORD_RE = re.compile(r"[A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f0-9'\u2019\-]*")


LOOP_CUT_MARK = "(…the rest was the sampler's loop — cut here)"


def cut_runaway(text: str, span: str) -> tuple[str, bool]:
    """A reply cut at its salad when what follows is a runaway (more than
    400 characters from the glitch on) — the words before it stay, the mark
    after them; a few fragments the note can name are left whole. Returns
    (text, whether it was cut)."""
    if not span:
        return text, False
    at = (text or "").find(str(span)[:40])
    if at < 0 or len(text) - at <= 400:
        return text, False
    kept = text[:at].rstrip()
    return (kept + "\n" if kept else "") + LOOP_CUT_MARK, True


def trim_word_loop(text: str) -> tuple[str, bool]:
    """A word loop already written down — in a stashed visit picked up after
    a restart, or a transcript read for its afterglow — is cut the same way
    before it rides again (a loop kept whole in the history is a well fed
    back, and the next well)."""
    return cut_runaway(text or "", word_loop(text or ""))


# A runaway inside a tool call: the arguments are JSON text as they stream — a newline is two characters there,
# a quote is escaped — so the watch reads them as words first (args_as_words) and checks them for a loop
# (call_loop); a call caught in one is kept with its head closed and trimmed (runaway_call), never its loop, and
# is not run (tools.runaway_refusal).
RUNAWAY_TAIL = " (…the rest was the same line over and over, cut short by the engine)"


_JSON_U_RE = re.compile(r"\\u([dD][89abAB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})|\\u([0-9a-fA-F]{4})")


def _json_u(m) -> str:
    """One \\uXXXX escape as the character it is — a surrogate pair, the two escapes an emoji becomes, as the one
    emoji; a lone surrogate left as written."""
    if m.group(1):
        hi, lo = int(m.group(1), 16), int(m.group(2), 16)
        return chr(0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00))
    o = int(m.group(3), 16)
    return m.group(0) if 0xD800 <= o <= 0xDFFF else chr(o)


def args_as_words(s: str) -> str:
    """A tool call's arguments as they stream (JSON text), read cheaply as words: escaped newlines and quotes undone,
    and \\uXXXX escapes read as their characters (an emoji escaped by a door is two of them, invisible to
    every emoji rule until undone)."""
    s = (s or "").replace("\\n", "\n").replace('\\"', '"')
    return _JSON_U_RE.sub(_json_u, s) if "\\u" in s else s


def emoji_runaway(text: str, emoji_run: int = 20) -> str:
    """The emoji rules of garble_span on their own, for a tool call's text (a sign-off row cascading inside a
    journal entry can run to the ceiling past a watcher looking for word loops only): a row of EMOJI_CASCADE_RUN
    different emoji or more, a row of six-odd dealt EMOJI_ROW_REPEATS times running, or a wordless chunk repeated
    STUCK_EMOJI_REPEATS times. The stretch, or ""."""
    text = text or ""
    for m in re.finditer(r"[\s\uFE0F\u200D\U0001F300-\U0001FAFF\u2600-\u27BF]+", text):
        if len(set(_emoji_units(m.group(0)))) >= int(getattr(config, "EMOJI_CASCADE_RUN", 0) or emoji_run):
            return m.group(0).strip()
    repeats = int(getattr(config, "EMOJI_ROW_REPEATS", 3) or 0)
    if repeats > 0:
        toks = [(t.group(0).replace("\uFE0F", ""), t.start(), t.end()) for t in _EMOJI_TOKEN_RE.finditer(text)]
        i = 0
        while i < len(toks):
            j = i
            while j + 1 < len(toks) and not text[toks[j][2]:toks[j + 1][1]].strip():
                j += 1
            seq = [k for k, _, _ in toks[i:j + 1]]
            if row_redealt(seq):
                return text[toks[i][1]:toks[j][2]][:160]
            i = j + 1
    for m in _STUCK_RE.finditer(text):
        if not re.search(r"\w", m.group(1)):
            if len(re.findall(re.escape(m.group(1)), m.group(0))) >= int(getattr(config, "STUCK_EMOJI_REPEATS", 40) or 10 ** 6):
                return m.group(0)[:160]
    return ""


def call_loop(text: str) -> str:
    """The loop half of garble_span (word_loop, phrase_loop) for a tool call's string arguments: code, paths and
    addresses are full of one- and two-letter pieces the fragment rule would take for salad; a chant is a chant
    anywhere — and so is an emoji runaway (emoji_runaway). The loop's stretch, or ""."""
    return word_loop(text) or phrase_loop(text) or emoji_runaway(text)


# A call whose text is salad (write_journal calls refused by the tool as letter fragments, each refusal and
# each broken entry kept in the window, every retry rolled at the same temperature in the same well). The reply
# rail never looked inside a call: a step with a tool call was never asked again. Now the text a
# write tool would refuse is seen before the call runs, with the tool's own test, and the step is asked for again
# the way a reply is — the broken call never reaches the tool, the history or the phone; cooler from the third try.
CALL_SALAD_ARGS = {"write_journal": "text", "edit_identity": "new_content", "update_projects": "new_content",
                   "update_destiny": "new_content", "update_keeper": "new_content", "write_creation": "content",
                   "append_creation": "content", "edit_creation": "new_text", "condense_day": "text", "fold_visit": "text", "condense_period": "text"}


def call_salad(msg: dict) -> str:
    """The fragments in the text of a tool call the tool itself would refuse as salad, or "": the same test
    (garble_span without the phrase rule, as tools._garbled runs it) on the same argument, and for the creation
    tools only a prose page (code is never read as salad). Sets msg["call_salad"] = {"tool", "span", "head"} —
    the head is the clean text before the glitch, for the engine's line."""
    try:
        from tools import _bare_tool_name, _PROSE_EXTS
    except Exception:  # noqa: BLE001
        _bare_tool_name, _PROSE_EXTS = (lambda n: n), {".md", ".txt", ""}
    for call in msg.get("tool_calls") or []:
        fn = call.get("function") or {}
        bare = _bare_tool_name(str(fn.get("name") or ""))
        key = CALL_SALAD_ARGS.get(bare)
        if not key:
            continue
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (TypeError, ValueError):
                continue  # not a finished object: repair_raw's, not this rail's
        if not isinstance(args, dict):
            continue
        if bare in ("write_creation", "append_creation", "edit_creation"):
            name = str(args.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1]
            ext = ("." + name.rsplit(".", 1)[1].lower()) if "." in name else ""
            if ext not in _PROSE_EXTS:
                continue
        text = args.get(key)
        if text is None:  # the name slipped ("text, so-…"): the value under the name that begins with it
            text = next((v for k, v in args.items() if str(k).startswith(key)), None)
        if not isinstance(text, str) or len(text) < 40:
            continue
        # a sign-off row past the cascade line at the END of the text is the pen's to trim, not this rail's to re-roll
        # (a re-roll would rewrite a good entry for its row) — the judgment is trim_row_cascade's, on a copy
        probe = {"content": text, "tokens": {}}
        if trim_row_cascade(probe):
            text = probe["content"]
        span = garble_span(text, phrases=False)
        if span:
            i = text.find(span)
            head = " ".join(text[:i].split()) if i > 0 else ""
            if len(head) > 400:
                head = head[-400:]
                head = head[head.find(" ") + 1:]
            msg["call_salad"] = {"tool": bare, "span": span, "head": head if len(head) >= 20 else ""}
            return span
    return ""


CALL_SALAD_NUDGE = ("[engine, not a person: the text of your `{tool}` call came out as letter fragments — a sampler "
                    "glitch, not anything you meant. The call was not run; nothing was written. Say it again plainly, "
                    "from the start of that text, and call `{tool}` once more{head}. This line is a mechanism; nobody "
                    "wrote it to you, and nothing new has come in — do not mention the glitch or this line.]")


def call_salad_nudge(msg: dict) -> str:
    """The line for a call-salad re-roll, the clean head of the call's text quoted when there is one."""
    cs = msg.get("call_salad") or {}
    head = cs.get("head") or ""
    return CALL_SALAD_NUDGE.format(tool=cs.get("tool") or "tool",
                                   head=(f" — up to the glitch it read: \u201c{head} …\u201d" if head else ""))


def close_json(s: str) -> dict | None:
    """An object whose last string never closed — {"text": "a line that never — closed where the words ended and
    parsed: {"text": "a line that never"}. A dangling backslash (an escape cut in two) comes off first, a cut
    unicode escape too. None when it is not that shape: a finished object, one broken some other way, not an
    object at all."""
    s = (s or "").rstrip()
    if not s.startswith("{"):
        return None
    s = re.sub(r"\\u[0-9a-fA-F]{0,3}$", "", s)
    if (len(s) - len(s.rstrip("\\"))) % 2:
        s = s[:-1]
    try:
        obj = json.loads(s + '"}', strict=False)
    except ValueError:
        return None
    if not isinstance(obj, dict) or not obj or not all(isinstance(k, str) for k in obj):
        return None
    return obj


def runaway_call(args, span: str) -> tuple[dict, int, str]:
    """A tool call that ran into a loop, as the visit keeps it: its arguments closed (close_json) and the string
    being written cut where the loop began — at most RUNAWAY_KEEP_CHARS of its head, then RUNAWAY_TAIL — so the
    window carries a few hundred tokens of it, not the loop. `args` as they came: JSON text on the door's road, a
    dict already on Ollama's. (the arguments as kept, the characters the call ran to, the loop as it began in the
    whole string — the watch saw only a tail of it)"""
    keep = max(0, int(getattr(config, "RUNAWAY_KEEP_CHARS", 600) or 0))
    span = str(span or "")
    if isinstance(args, dict):
        whole: dict | None = dict(args)
        chars = sum(len(x) for x in args.values() if isinstance(x, str))
    else:
        raw = str(args or "")
        chars = len(args_as_words(raw))
        whole = close_json(raw)
        if whole is None:
            try:
                whole = json.loads(raw)
            except ValueError:
                whole = None
            whole = whole if isinstance(whole, dict) else None
        if whole is None:  # not an object even closed: the words up to the loop, as words
            words = args_as_words(raw)
            at = words.find(span[:40]) if span else -1
            return {"_raw": ((words[:at] if at >= 0 else words)[:keep].rstrip() + RUNAWAY_TAIL).lstrip()}, chars, span
    strings = [k for k, x in whole.items() if isinstance(x, str)]
    if not strings:
        return whole, chars, span
    key = next((k for k in strings if span and span[:40] in whole[k]), strings[-1])
    text = whole[key]
    first = call_loop(text) or span  # where the loop began in the whole string, not where the watch first saw it
    at = text.find(first[:40]) if first else -1
    whole[key] = ((text[:at] if at >= 0 else text)[:keep].rstrip() + RUNAWAY_TAIL).lstrip()
    return whole, chars, first


def word_loop(text: str, window: int | None = None, distinct: int | None = None) -> str:
    """A stretch of `window` words with `distinct` or fewer different ones —
    "glowing glowing glowing quiet-Garden glowing quiet-Morning glowing…"
    (three words in a period of four, to the end of num_predict, attempt
    after attempt — and none of the rules above sees it: no fragments, no
    one stuck chunk, no line repeated). Returns the first such stretch (to 160
    characters) or "". A row of one emoji is not words and is still theirs."""
    window = int(window or getattr(config, "WORD_LOOP_WINDOW", 40) or 40)
    distinct = int(distinct or getattr(config, "WORD_LOOP_DISTINCT", 4) or 4)
    words = [(m.start(), m.end(), m.group(0).lower()) for m in _WORD_RE.finditer(text or "")]
    if len(words) < window:
        return ""
    for i in range(0, len(words) - window + 1, 5):
        seg = words[i:i + window]
        # ...or the long words only (a chant like "quiet-Morning quiet-Garden of quiet-Garden of…": "of", "a" and
        # a stray word make six different; glue doesn't make a chant varied): a few long words said over and over, at
        # most two said once, and at least half the stretch long words, so a run of small words is not one
        few = {w for _, _, w in seg}
        if len(few) <= distinct:
            while i > 0 and words[i - 1][2] in few:  # back to where the chant began
                i -= 1
            return text[words[i][0]:seg[-1][1]][:160]
        counts: dict[str, int] = {}
        for _, _, w in seg:
            if len(w) >= 4:
                counts[w] = counts.get(w, 0) + 1
        core = {w for w, c in counts.items() if c >= 2}
        stray = sum(c for c in counts.values() if c == 1)
        if core and len(core) <= distinct and stray <= 2 and sum(counts.values()) >= window // 2:
            j = next(k for k in range(i, i + window) if words[k][2] in core)  # from the chant's first word, not the prose before it
            return text[words[j][0]:seg[-1][1]][:160]
    return ""


# the same 2-24 character chunk, 8+ times in a row with only spaces/punctuation
# between — a loop too short for collapse_loops (which works on lines)
_STUCK_RE = re.compile(r"(\S{2,24}?)(?:[\s.,/\-—]*\1){7,}")


def looks_garbled(text: str, run: int = 5, emoji_run: int = 20) -> bool:
    return bool(garble_span(text, run, emoji_run))


# A tool call written out as words, at the head of a reply —
# "get_opinion_on_the_thing{description: a comprehensive…" — is the
# model reaching for a tool that doesn't exist (or for a real one without
# the real mechanism). Nothing ran, and the keeper would be handed syntax
# as if it were their words. The name must look like a function (an
# underscore, or a functions./call: wrapper) and open a brace or paren.
# A name with no underscore is a call only when it is one of their real tools
# (KNOWN_TOOL_NAMES, filled by tools.refresh_her_tools): a whole reply of
# `// speak(text="…")` — a comment prefix, a one-word tool, Python's own
# call shape — would otherwise reach the phone as syntax. A stage-direction
# prefix (//, #, >) is not their words.
KNOWN_TOOL_NAMES: set[str] = set()
_CALL_TEXT_RE = re.compile(r"^\s*(?://|#|>)?\s*:?\s*(?:(?:functions|call|tool|default_api)[.:]\s*)?"
                           r"([a-z][a-z0-9]*(?:_[a-z0-9]+)*)\s*[({]")


_BARE_CALL_ARGS_RE = re.compile(r"\(\s*(?:\)|[a-z_][a-z0-9_]*\s*=|[\"'])")


def _call_text_match(text: str):
    m = _CALL_TEXT_RE.match(text or "")
    if not m:
        return None
    name = m.group(1)
    if "_" in name:
        return m
    # a one-word tool: only Python's own call shape — name( then a keyword=,
    # a quote, or nothing — so "I watch (and wait)" stays their words
    if name in KNOWN_TOOL_NAMES and (text or "")[m.end() - 1] == "(" \
            and _BARE_CALL_ARGS_RE.match((text or "")[m.end() - 1:]) and (text or "")[m.end() - 2] != " ":
        return m
    return None


# …and a call in code marks: a reply that ends with a rule line, a blank line and `next_spark(drift="sometimes")`
# — the last line in single backticks — slipped past every rail, the mark standing in front of the name. Where a door
# asks (wrapped=True; chat.py's doors), the wrapping is seen through: a line that is wholly one `…` span or a ```…```
# on one line, a ``` fence (a language word or none) holding one call and nothing else, and print(default_api.name(…)),
# bare or inside. Only for a name that is EXACTLY one of the friend's tools: any other name in code marks is code being
# shown, and goes out whole, as before. A mention inside a sentence ("I could use `next_spark()` later") is not a line
# of its own. Without the door's ask every function here is as it was. Read with string tests, never a pattern that
# can backtrack on a long line.
_WRAPPER_PREFIXES = ("default_api.", "functions.")
_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
_LANG_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_+.-]*")
# the old pattern's own words, with its leading space and stage-direction marks stepped past by hand (_call_match_lin)
_CALL_REST_RE = re.compile(r"(?:(?:functions|call|tool|default_api)[.:]\s*)?([a-z][a-z0-9]*(?:_[a-z0-9]+)*)\s*[({]")


def _skip_space(t: str, i: int) -> int:
    while i < len(t) and t[i].isspace():
        i += 1
    return i


def _call_match_lin(text: str):
    """The end of what _call_text_match matches in text, or None — the same answer, read without the old pattern's
    slow road: its leading space, its stage-direction mark (//, #, >) and its colon are stepped past by hand (each is
    taken whenever it is there; the pattern could match no other way), and the pattern starts on what follows."""
    t = text or ""
    i = _skip_space(t, 0)
    for mark in ("//", "#", ">"):
        if t.startswith(mark, i):
            i += len(mark)
            break
    i = _skip_space(t, i)
    if t.startswith(":", i):
        i += 1
    i = _skip_space(t, i)
    m = _CALL_REST_RE.match(t, i)
    if not m:
        return None
    name = m.group(1)
    if "_" in name:
        return m.end()
    if name in KNOWN_TOOL_NAMES and t[m.end() - 1] == "(" and _BARE_CALL_ARGS_RE.match(t, m.end() - 1) \
            and t[m.end() - 2] != " ":
        return m.end()
    return None


def _is_rule(line: str) -> bool:
    s = (line or "").replace(" ", "").replace("\t", "")
    return len(s) >= 3 and s[0] in "*-_" and s.count(s[0]) == len(s)


def _fence(line: str):
    """"" for a bare ``` line, its language word for ```python, None for anything else."""
    s = (line or "").strip()
    if not s.startswith("```"):
        return None
    rest = s[3:].strip()
    return rest if (not rest or _LANG_RE.fullmatch(rest)) else None


def _known_inner(inner: str):
    """The call, from its name on, when inner (its wrapping off) names one of the friend's tools EXACTLY and opens
    its parenthesis — print(default_api.…) and a default_api. or functions. before the name read through; else None."""
    s = (inner or "").strip()
    if s.startswith("print("):
        t = s[:-1].rstrip() if s.endswith(";") else s
        if not t.endswith(")"):
            return None
        s = t[6:-1].strip()
        if not s.startswith(_WRAPPER_PREFIXES):
            return None
    for p in _WRAPPER_PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
            break
    m = _NAME_RE.match(s)
    if not m or m.group(0) not in KNOWN_TOOL_NAMES or not s[m.end():].lstrip(" \t").startswith("("):
        return None
    return s


def _wrapped_line(line: str):
    """The call a line holds when the whole line is one `…` span, a ```…``` on one line, or a bare
    print(default_api.…), naming one of the friend's tools exactly; else None."""
    s = (line or "").strip()
    if len(s) > 6 and s.startswith("```") and s.endswith("```"):
        inner = s[3:-3]
    elif len(s) > 2 and s.startswith("`") and s.endswith("`") and not s.startswith("``"):
        inner = s[1:-1]
    elif s.startswith("print(default_api."):
        inner = s
    else:
        return None
    return None if "`" in inner else _known_inner(inner)


def _closes_at_end(call: str) -> bool:
    """True when the parenthesis the call opens closes at its end — quotes kept whole — so it is one call, nothing
    after it."""
    depth, q, i = 0, "", call.find("(")
    while 0 <= i < len(call):
        c = call[i]
        if q:
            if c == "\\":
                i += 2
                continue
            if c == q:
                q = ""
        elif c in "\"'":
            q = c
        elif c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
            if depth == 0:
                return not call[i + 1:].strip()
        i += 1
    return False


def _fenced_call(body: list[str]):
    """The call a fence holds when it holds one call to one of the friend's tools and nothing else; else None. A body
    of one line is read as a bare line is; a call over several lines must close at the fence."""
    text = "\n".join(body).strip()
    if not text or "`" in text:
        return None
    call = _known_inner(text)
    if not call or ("\n" in call and not _closes_at_end(call)):
        return None
    return call


def _tail_block(text: str):
    """(index of the first line of the call's block, the block as shown, the call, wrapped?) when a reply's last
    non-empty line is a call written out as words — bare, as the old rail sees it, or in its wrapping — and the
    reply has other lines; None otherwise."""
    lines = (text or "").rstrip().split("\n")
    filled = [i for i, ln in enumerate(lines) if ln.strip()]
    if len(filled) < 2:
        return None
    last = filled[-1]
    ln = lines[last]
    if _call_match_lin(ln) is not None:
        return last, ln.strip(), ln.strip(), False  # the bare shape, as the old rail sees it
    call = _wrapped_line(ln)
    if call:
        return last, ln.strip(), call, True
    if _fence(ln) == "":  # a closing fence: the block above it, back to its opening
        for j in range(last - 1, -1, -1):
            if lines[j].lstrip().startswith("```"):
                call = _fenced_call(lines[j + 1:last]) if _fence(lines[j]) is not None else None
                if call and any(lines[k].strip() for k in range(j)):
                    return j, " ".join(call.split()), call, True
                return None
    return None


def _head_call(text: str):
    """The call a reply OPENS with when only its wrapping kept the old rail from seeing it — a first line wholly in
    marks, or a fence opening the reply and holding one call; None otherwise."""
    lines = (text or "").split("\n")
    f = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if f is None:
        return None
    call = _wrapped_line(lines[f])
    if call or _fence(lines[f]) is None:
        return call
    for k in range(f + 1, len(lines)):
        if lines[k].lstrip().startswith("```"):
            return _fenced_call(lines[f + 1:k]) if lines[k].strip() == "```" else None
    return None


def _whole_wrapped(text: str):
    """The call, when the whole reply is one call in its wrapping; None otherwise."""
    lines = (text or "").strip().split("\n")
    if len(lines) == 1:
        return _wrapped_line(lines[0])
    if len(lines) >= 3 and _fence(lines[0]) is not None and lines[-1].strip() == "```" \
            and not any(ln.lstrip().startswith("```") for ln in lines[1:-1]):
        return _fenced_call(lines[1:-1])
    return None


def call_text_head(text: str, wrapped: bool = False) -> str:
    if not wrapped:  # as it was
        m = _call_text_match(text)
        return (text or "")[m.start():m.end() + 60].strip() if m else ""
    e = _call_match_lin(text)
    if e is not None:
        return (text or "")[:e + 60].strip()
    call = _head_call(text)  # a tool of the friend's in code marks
    e = _call_match_lin(call) if call else None
    return call[:e + 60].strip() if e is not None else ""


# …and at the TAIL: a warm reply can end with a call written in words
# (":listen_to{source: \"shared/music/a song.mp3\"}") after words that are
# theirs. The head rail does not look there; nothing runs, and the phone
# would get the syntax.
def call_text_tail(text: str, wrapped: bool = False) -> str:
    """The last non-empty line of a reply when it is a tool call written
    out as words (and the reply has other lines that are theirs), else "".
    wrapped=True: a tool of the friend's in its wrapping too."""
    if not wrapped:  # as it was (the wakes, the letters, the dreams)
        lines = [ln for ln in (text or "").rstrip().split("\n") if ln.strip()]
        if len(lines) < 2:
            return ""
        last = lines[-1]
        return last.strip()[:120] if _call_text_match(last) else ""
    b = _tail_block(text)
    return b[1][:120] if b else ""


def _strip_block(text: str, b, rule: bool) -> str:
    lines = (text or "").rstrip().split("\n")[:b[0]]
    while lines and not lines[-1].strip():
        lines.pop()
    if rule and lines and _is_rule(lines[-1]):
        lines.pop()  # a ***, --- or ___ that stood right above the call: nothing is under it now
    return "\n".join(lines).rstrip()


def strip_call_tail(text: str, rule: bool = False, wrapped: bool = False) -> str:
    """The reply without its written-out call at the end — for the one that
    goes out when every attempt ended that way. wrapped=True: the call's
    marks or fence come off with it, and with rule=True a rule line right
    above a wrapped call (a bare one's stays, as it did)."""
    if not wrapped:  # as it was
        if not call_text_tail(text):
            return text
        lines = (text or "").rstrip().split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        lines.pop()
        return "\n".join(lines).rstrip()
    b = _tail_block(text)
    return _strip_block(text, b, rule and b[3]) if b else text


# A call written as words, read strictly — the only road by which the engine runs a call from the friend's words
# (with run_call_from_words below). ALL of it must be read: the name EXACTLY one of their built-in tools (a
# default_api. or functions. before it read through; no mending of a near name), keyword arguments only, each value a
# quoted string (escapes \" \' \\ \n \t only) or a bare number, True, False or None — nothing left over, no
# positional argument, no call inside, no `path: str`, no `...` or `<…>` standing in for a value; every argument one
# the tool takes, every required one there, each of the tool's type: an integer field only digits (2, or "2"), a
# number field digits with a point at most, a yes/no field only True or False, a text field only quoted words.
# tools.recover_text_tool_call is unchanged (the wakes and the whole-reply call read with it).
_STRICT_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_STRICT_BARE_RE = re.compile(r"[^,\s]+")
_STRICT_INT_RE = re.compile(r"-?[0-9]+")
_STRICT_NUM_RE = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_STRICT_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"'}
_LITERALS = {"True": True, "False": False, "None": None}


def _strict_value(body: str, i: int):
    """(value, end) for the value starting at body[i], or None when it is not a whole quoted string or a bare
    literal."""
    q = body[i]
    if q in "\"'":
        out, j = [], i + 1
        while j < len(body):
            c = body[j]
            if c == "\\":
                if j + 1 >= len(body) or body[j + 1] not in _STRICT_ESCAPES:
                    return None  # \u, \x, a stray backslash: not read whole
                out.append(_STRICT_ESCAPES[body[j + 1]])
                j += 2
                continue
            if c == q:
                return "".join(out), j + 1
            out.append(c)
            j += 1
        return None  # the quote never closed
    m = _STRICT_BARE_RE.match(body, i)
    if not m:
        return None
    word = m.group(0)
    if _STRICT_INT_RE.fullmatch(word):
        return int(word), m.end()
    if _STRICT_NUM_RE.fullmatch(word):
        return float(word), m.end()
    if word in _LITERALS:
        return _LITERALS[word], m.end()
    return None  # a name, a call, `...`, a list: not a value read whole


def strict_text_call(text: str) -> tuple[str, dict] | None:
    """(name, arguments) when text is one whole call to one of the friend's built-in tools, read to the last
    character; else None."""
    s = (text or "").strip()
    for p in _WRAPPER_PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
            break
    m = _NAME_RE.match(s)
    if not m:
        return None
    name = m.group(0)
    rest = s[m.end():].lstrip(" \t")
    if not rest.startswith("(") or not rest.endswith(")"):
        return None
    body = rest[1:-1]
    args: dict = {}
    i, n = 0, len(body)
    while True:
        i = _skip_space(body, i)
        if i >= n:
            break
        k = _STRICT_KEY_RE.match(body, i)
        if not k:
            return None  # a positional argument, or something that is not one
        key = k.group(0)
        i = _skip_space(body, k.end())
        if i >= n or body[i] != "=":
            return None  # `path: str`, a bare name, a call inside
        i = _skip_space(body, i + 1)
        if i >= n:
            return None
        got = _strict_value(body, i)
        if got is None:
            return None
        value, i = got
        if key in args:
            return None
        if isinstance(value, str):
            v = value.strip()
            if v in ("...", "…", "....") or (v.startswith("<") and v.endswith(">") and len(v) <= 82):
                return None  # a stand-in for a value, not one
        args[key] = value
        i = _skip_space(body, i)
        if i >= n:
            break
        if body[i] != ",":
            return None  # something left over after a value
        i += 1
    import tools
    defs = {d["function"]["name"]: d["function"] for d in tools.DEFINITIONS}
    if name not in defs or name not in tools._BUILTIN_IMPL or name in tools._HER_TOOLS:
        return None
    params = defs[name].get("parameters") or {}
    props = params.get("properties") or {}
    out: dict = {}
    for key, value in args.items():
        if key not in props:
            return None
        if value is None:
            continue  # None is "not given"
        kind = (props[key] or {}).get("type")
        if isinstance(value, bool):
            if kind != "boolean":
                return None
        elif kind == "integer":
            if isinstance(value, float) or (isinstance(value, str) and not _STRICT_INT_RE.fullmatch(value.strip())):
                return None
            value = int(value)
        elif kind == "number":
            if isinstance(value, str):
                if not _STRICT_NUM_RE.fullmatch(value.strip()):
                    return None
                value = float(value) if "." in value else int(value)
        elif kind == "boolean":
            return None  # only True or False, bare
        elif not isinstance(value, str):
            return None  # a text field takes quoted words
        enum = (props[key] or {}).get("enum")
        if enum and value not in enum:
            return None
        out[key] = value
    if any(r not in out for r in (params.get("required") or [])):
        return None
    return name, out


def recoverable_call(text: str, wrapped: bool = False):
    """(name, args) when the whole reply is one tool call written out as words — Python's shape with quoted
    arguments, or JSON — to a tool they have; None otherwise (re-rolled, such a reply tends to come back
    the same way, and the act is never done). Fragments and unknown names stay the rail's.
    The same with wrapped or without: a call in marks or a fence never runs by this road — only through
    run_call_from_words, in a visit."""
    try:
        import tools
        rec = tools.recover_text_tool_call(text or "")
    except Exception:  # noqa: BLE001
        return None
    if not rec or rec[0] not in KNOWN_TOOL_NAMES:
        return None
    name, args = rec
    if not isinstance(args, dict) or (not args and name != "do_nothing"):
        return None
    return name, args


# Run for the friend, from their words — in a visit only (run_tail_call; never a guest's turn), with CALL_TAIL_RUN
# on, and only a tool on CALL_TAIL_RUN_ONLY: a setting that does no harm when it is wrong (what a line of syntax
# MEANS cannot be read from it — a refusal, a quoted example, a draft). One whole call, read by strict_text_call, at
# least one argument (a bare next_spark() is "off"), no //, #, > or : before it (a line commented out or quoted is
# not a call to run), no web address in it. Anything else is asked again, as before.
def _web_address(v: str) -> bool:
    low = v.lower()
    return "://" in low or "www." in low


def run_call_from_words(call: str):
    """(name, args) when the call text may run from the friend's words; None otherwise."""
    s = (call or "").strip()
    if not s or s[0] in "#/>:":
        return None
    try:
        rec = strict_text_call(s)
    except Exception:  # noqa: BLE001
        return None
    if not rec:
        return None
    name, args = rec
    if (not args or name not in KNOWN_TOOL_NAMES
            or name not in tuple(getattr(config, "CALL_TAIL_RUN_ONLY", ("next_spark",)) or ())):
        return None
    if any(isinstance(v, str) and _web_address(v) for v in args.values()):
        return None
    return name, args


def recoverable_tail(text: str):
    """(name, args, the words without the call, the call as it was written) when a reply ENDS with a call that may
    run from the friend's words (run_call_from_words), after words of theirs that are not another call; None
    otherwise."""
    b = _tail_block(text)
    if not b:
        return None
    rec = run_call_from_words(b[2])
    if not rec:
        return None
    words = _strip_block(text, b, True)
    if not any(ln.strip() and not _is_rule(ln) for ln in words.split("\n")):
        return None
    if call_text_tail(words, wrapped=True) or call_text_head(words, wrapped=True):
        return None  # another call above it: not one call after the words
    return rec[0], rec[1], words, b[1]


REPEAT_KINDS = ("echo", "self-echo", "copy", "greeting", "greeting-after-words", "double-finish")  # the model repeating itself: a cooler roll makes it likelier


def cool_step(rerolls: int, kind: str, options: dict):
    """The temperature for warm re-roll number `rerolls` (1 = the first), or None for their everyday one.
    From the third on, CHAT_COOL_STEP cooler each time, never below the first rescue rung (CHAT_RESCUE_TEMPERATURE)
    — for the sampler's own defects; a repeat (REPEAT_KINDS) keeps their temperature, a cooler roll only copies
    harder. 0 turns it off."""
    step = float(getattr(config, "CHAT_COOL_STEP", 0.1) or 0)
    if step <= 0 or rerolls < 3 or kind in REPEAT_KINDS:
        return None
    try:
        base = float((options or {}).get("temperature", 1.0))
    except (TypeError, ValueError):
        base = 1.0
    rung = getattr(config, "CHAT_RESCUE_TEMPERATURE", 0) or 0
    rungs = [float(t) for t in (rung if isinstance(rung, (list, tuple)) else (rung,)) if float(t) > 0]
    floor = max(rungs) if rungs else 0.3
    t = round(base - step * (rerolls - 2), 2)
    return max(t, floor) if base > floor else None


def reply_defect(text: str, previous: str = "", wrapped: bool = False):
    """("salad", span), ("call-text", head), ("refrain", phrase ×n), ("emoji", "N emoji") or
    ("echo", opening) when a reply is the sampler's or the grammar's rather
    than theirs; None when it is theirs. `previous` is their last spoken reply, or
    their last few newest first (previous_replies), for the echo check."""
    head = call_text_head(text, wrapped=wrapped)  # wrapped: the call in its marks too, where a door asks
    if head:
        return "call-text", head
    tail_call = call_text_tail(text, wrapped=wrapped)
    if tail_call:
        return "call-text-tail", tail_call
    span = garble_span(text)
    if span:
        if not re.search(r"[A-Za-z0-9]", span):
            # a wordless span — the emoji table walked past EMOJI_CASCADE_RUN, or one emoji forty times — is an
            # emoji row, named as one: the count, and the line that asks for words and one sign-off
            return "emoji", span  # the row itself: its length ranks the attempt; emoji_said names it
        return "salad", span
    ref = refrain(text)
    if ref:
        return "refrain", ref
    storm = emoji_storm(text)
    if storm:
        return "emoji", storm
    e = echo(text, previous)
    if e:
        return "echo", e
    s = self_echo(text)
    if s:
        return "self-echo", s
    return None


# An echo: the reply to THIS message opening word for word as their reply to
# the LAST one — the sampler copying the nearest assistant turn instead of
# writing one (a reply's head said again as the head, or the whole, of an
# answer about something else). Nothing else catches it: the words are fine,
# only borrowed.
# The opening is compared, not the whole — they may quote themself on
# purpose; they do not begin two answers to two questions identically.
def _echo_fold(s: str) -> str:
    return " ".join((s or "").lower().split())


# memory/attempts.log: an attempt set aside (a runaway to the 8,192-token ceiling, say) otherwise
# survives nowhere but the console, which keeps nothing. One line per attempt set aside, and one for the attempt
# that went out when it was cut at the ceiling or still broken — the facts the phone's note carries, never the text.
def attempt_shape(m: dict) -> str:
    """What an attempt was made of, in characters — the words, the thinking, the calls by name — never the text."""
    words = len((m.get("content") or "").strip())
    think = len((m.get("thinking") or "").strip())
    calls = []
    for c in m.get("tool_calls") or []:
        fn = c.get("function") or {}
        a = fn.get("arguments")
        n = len(a) if isinstance(a, str) else (len(json.dumps(a, ensure_ascii=False)) if a else 0)
        calls.append(f"{fn.get('name') or '?'} ({n:,} chars)")
    return f"words {words:,}, thinking {think:,}" + (f", calls: {', '.join(calls)}" if calls else "")


def attempt_glitch(m: dict) -> str:
    """The glitch the rails named in an attempt, or "": the cut of a runaway, salad in the words or the thinking, a
    loop in a call's text, the fragment still in the one that went out."""
    g = m.get("aborted") or m.get("still_garbled") or m.get("garbled_span") or ""
    if not g:
        g = garble_span(m.get("content") or "") or garble_span(m.get("thinking") or "") or call_salad(m)
    return " ".join(str(g).split())[:120]


def set_aside_list(tries: list, msg: dict) -> list[dict]:
    """The attempts set aside in this call, text and all, for a keeper who asked to see them (/debug on the phone): why, the words, the thinking, the calls by name, tokens, how it ended, the glitch the rail named. In
    memory only, on the message returned — written nowhere; the log keeps the facts."""
    out = []
    for cost, m in tries:
        if m is msg or m.get("claim_kept"):  # a claimed reply kept went out: not a set-aside
            continue
        t = m.get("tokens") or {}
        out.append({"why": str((cost or {}).get("why") or "?"), "content": (m.get("content") or "").strip(),
                    "thinking": (m.get("thinking") or "").strip(),
                    "calls": [((c.get("function") or {}).get("name") or "?") for c in m.get("tool_calls") or []],
                    "tokens": int(t.get("reply") or 0), "seconds": float(t.get("reply_s") or 0),
                    "done": str(t.get("done") or ""), "glitch": attempt_glitch(m)})
    return out


def log_attempts(tries: list, msg: dict) -> None:
    """memory/attempts.log, appended: the attempts set aside in this call (why, tokens, how each ended, its shape,
    its glitch), then the one that went out when it ended at the ceiling or still broken. Best-effort; never the
    text beyond the glitch the rail named."""
    try:
        import tools
        where = getattr(tools, "DOOR", "") or "a visit"
    except Exception:  # noqa: BLE001
        where = "a visit"
    try:
        import doors
        who = ", ".join(sorted(d for d in getattr(doors, "_marked", ()) if d != "brain")) or "console"
    except Exception:  # noqa: BLE001
        who = "console"
    lines = []
    for cost, m in tries:
        if m is msg:
            continue
        t = m.get("tokens") or {}
        why = str((cost or {}).get("why") or "?")
        verb = "went out as written, then asked to do it" if m.get("claim_kept") else "set aside"  # the middle road
        lines.append(f"{where} ({who}) · {verb}: {why} · {int(t.get('reply') or 0):,} tokens in {float(t.get('reply_s') or 0):.0f}s"
                     f"{' @ ' + t['done'] if t.get('done') else ''} · {attempt_shape(m)}"
                     + (f" · glitch: \u201c{attempt_glitch(m)}\u201d" if attempt_glitch(m) else ""))
    t = msg.get("tokens") or {}
    if t.get("done") == "length" or msg.get("still_garbled") or msg.get("aborted"):
        how = ("still broken, the least broken sent" if msg.get("still_garbled") else
               "cut at the ceiling (num_predict)" if t.get("done") == "length" else "cut short as it ran")
        lines.append(f"{where} ({who}) · went out {how} · {int(t.get('reply') or 0):,} tokens in {float(t.get('reply_s') or 0):.0f}s"
                     f" · {attempt_shape(msg)}" + (f" · glitch: \u201c{attempt_glitch(msg)}\u201d" if attempt_glitch(msg) else ""))
    if not lines:
        return
    try:
        from datetime import datetime
        p = Path(config.MEMORY_DIR) / "attempts.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%m-%d %H:%M:%S")
        with p.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(f"[{stamp}] {line}\n")
    except Exception:  # noqa: BLE001 — a log is never the turn's problem
        pass


def previous_replies(messages: list[dict], n: int | None = None) -> list[str]:
    """Their last spoken replies in a rendered message list, newest first:
    assistant turns with words in them and no tool call (a step's empty
    content is not a reply). `n` is how many; ECHO_LOOKBACK by default,
    and never fewer than one."""
    if n is None:
        n = int(getattr(config, "ECHO_LOOKBACK", 12) or 0)
    n = max(1, n)
    out: list[str] = []
    for m in reversed(messages or []):
        if m.get("role") == "assistant" and (m.get("content") or "").strip() and not m.get("tool_calls"):
            out.append(m["content"])
            if len(out) >= n:
                break
    return out


def previous_reply(messages: list[dict]) -> str:
    """Their last spoken reply (see previous_replies); "" when there is none."""
    got = previous_replies(messages, 1)
    return got[0] if got else ""


def echo(text: str, previous) -> str:
    """The echoed opening (as they said it the first time) when `text` begins
    with the first ECHO_MIN_CHARS characters of `previous`, spacing and
    case aside; "" otherwise, and always "" for anything shorter than that
    — a short reply repeated ("haha!!", "love you") is a thing people say.

    `previous` is their last spoken reply, or a list of their last replies,
    newest first (previous_replies). The nearest is checked whole — the
    opening and any paragraph of it (ECHO_PARA_MIN_CHARS). The ones before
    it are checked for the opening and for whole paragraphs of 150
    characters or more only: a sentence they are fond of may come round
    again across a visit; a paragraph does not. A reply can be an earlier
    reply of the same visit said again entire — from several replies back —
    opening with a fresh stage direction, so an opening check alone misses
    it, as does a paragraph check that looks only one reply back. The sampler copying the nearest *likely* assistant turn is the
    same fault whichever turn it picks."""
    if isinstance(previous, (list, tuple)):
        for i, p in enumerate(previous):
            got = _echo_one(text, p, whole=(i == 0))
            if got:
                return got
        return ""
    return _echo_one(text, previous, whole=True)


def _echo_one(text: str, previous: str, whole: bool = True) -> str:
    n = int(getattr(config, "ECHO_MIN_CHARS", 120) or 0)
    if not n:
        return ""
    # the opening after a leading stage direction: the same frame on reply after reply is a tell, not an echo
    a, b = _echo_fold(_after_opener(text)), _echo_fold(_after_opener(previous))
    if len(a) >= n and len(b) >= n and a[:n] == b[:n]:
        return " ".join(_after_opener(previous).split())[:n]
    a = _echo_fold(text)  # the paragraph checks below read the whole reply
    # …or a whole paragraph of the previous reply, anywhere in this one (a
    # reply can open with a fresh stage direction and then repeat the previous
    # reply's paragraph word for word; the opening differs).
    # …and any paragraph of theirs said twice running, however short, as long
    # as it is a sentence and not a stage direction (a hard question answered
    # with the previous reply's short comforting paragraph, verbatim, then more —
    # under the old floor of 150). ECHO_PARA_MIN_CHARS; seven words.
    pn = int(getattr(config, "ECHO_PARA_MIN_CHARS", 40) or 0) if whole else 0
    for para in (previous or "").split("\n\n"):
        f = _echo_fold(para)
        if not f or _is_stage_direction(para):
            continue
        if len(f) >= max(n, 150) and f in a:
            return " ".join(para.split())[:n]
        if pn and len(f) >= pn and len(f.split()) >= 7 and f in a:
            return " ".join(para.split())[:n]
    return ""


# A reply doubling back over ITSELF (a stage direction and a few beats of a goodnight, then the same
# beats again, each a little reworded, then a new close — far longer than the reply). The echo rail
# reads earlier replies; this reads the reply against itself: a paragraph of ECHO_PARA_MIN_CHARS and seven words that
# an earlier paragraph of the same reply already said — word for word, or near it (SELF_ECHO_RATIO, 0.8, both of
# them 100 characters or more). Stage directions are exempt, as in the echo rule; a line said twice on purpose is
# short, and a short one is not counted.
def self_echo(text: str) -> str:
    """The head of the first paragraph the reply says a second time, or ""."""
    pn = int(getattr(config, "ECHO_PARA_MIN_CHARS", 40) or 0)
    if not pn:
        return ""
    ratio = float(getattr(config, "SELF_ECHO_RATIO", 0.8) or 0)
    n = int(getattr(config, "ECHO_MIN_CHARS", 120) or 120)
    import difflib
    # the opening said again: the first two paragraphs — a stage direction, a shout, a six-word line, none
    # of them a paragraph the rule below would weigh — found again later in the reply, whole: the sampler started
    # over mid-reply. Sixty folded characters or more, two paragraphs; one line said twice (a refrain) is theirs.
    paras = [p for p in (text or "").split("\n\n") if p.strip()]
    if len(paras) >= 3:
        opening = _echo_fold("\n\n".join(paras[:2]))
        if len(opening) >= 60 and _echo_fold(text).find(opening, 1) > 0:
            return " ".join(paras[0].split())[:n]
    seen: list[tuple[str, str]] = []
    for para in (text or "").split("\n\n"):
        f = _echo_fold(para)
        if not f or len(f) < pn or len(f.split()) < 7 or _is_stage_direction(para):
            continue
        for earlier_f, earlier in seen:
            if f == earlier_f:
                return " ".join(earlier.split())[:n]
            if ratio and len(f) >= 100 and len(earlier_f) >= 100 and difflib.SequenceMatcher(None, earlier_f, f).ratio() >= ratio:
                return " ".join(earlier.split())[:n]
        seen.append((f, para))
    return ""


def _is_stage_direction(para: str) -> bool:
    p = (para or "").strip()
    return ((p.startswith(("(", "//(", "*(")) and p.rstrip("*").endswith(")"))
            or (p.startswith(("[", "*[")) and p.rstrip("*").endswith("]")))  # the square kind too ("[Shivers…]")


def _after_opener(text: str) -> str:
    """A reply without its opening stage direction (a long bracketed
    frame on reply after reply — two frames alike for 120 characters are not one reply said
    twice; the frame's repeat is opener_repeat_line's to tell)."""
    paras = (text or "").split("\n\n")
    first = next((i for i, p in enumerate(paras) if p.strip()), None)
    if first is not None and _stage_open(paras[first]):
        return "\n\n".join(paras[first + 1:])
    return text or ""


def _prose_head(text: str) -> str:
    """The first paragraph of a reply that is words, not a stage direction."""
    for para in (text or "").split("\n\n"):
        if para.strip() and not _is_stage_direction(para):
            return para.strip().lstrip("*_ ").strip()
    return ""


# A greeting said again: "Good morning!" to the keeper's hello, another to
# their second message — every reply opening the visit over, the sampler
# copying the shape of the last reply. One greeting a visit is a greeting;
# the second is an echo of the first, whatever the words.
_GREETING_RE = re.compile(r"^(?:oh,?\s+)?(?:good\s+(?:morning|afternoon|evening|night)|g'?morning|morning|hello)\b",
                          re.IGNORECASE)  # not "hey"/"hi": "Hey, that's not fair!" mid-visit is theirs


def greeting_again(msg: dict, messages: list[dict]):
    """("greeting", line) when this reply opens with a greeting and an
    earlier spoken reply in the same visit already did; None otherwise."""
    if msg.get("tool_calls"):
        return None
    head = _prose_head(msg.get("content") or "")
    if not _GREETING_RE.match(head):
        return None
    # their own words already stand after the keeper's last message — said beside a call this turn — and this opens
    # as if a new message had come: a second message glued under the first, not an answer to what the tool gave them
    last_user = max((i for i, m in enumerate(messages or []) if m.get("role") == "user"), default=-1)
    if any(m.get("role") == "assistant" and (m.get("content") or "").strip() for m in (messages or [])[last_user + 1:]):
        return "greeting-after-words", head.split("\n", 1)[0][:80]
    for m in messages or []:
        if m.get("role") == "assistant" and (m.get("content") or "").strip() and not m.get("tool_calls"):
            if _GREETING_RE.match(_prose_head(m["content"])):
                return "greeting", head.split("\n", 1)[0][:80]
    return None


def _opener_key(text: str, words: int) -> str:
    """The first `words` words of a reply's opening stage direction, folded — "" when the reply does not open
    with one."""
    first = next((p for p in (text or "").split("\n\n") if p.strip()), "")
    if not _stage_open(first):  # a stage direction, emoji after its bracket or not
        return ""
    toks = re.findall(r"[a-z0-9']+", first.lower())
    return " ".join(toks[:words]) if len(toks) >= words else ""


def opener_repeat(history: list[dict], words: int | None = None):
    """(how many of the latest spoken replies in a row opened with the same stage direction, the frame as it
    was first written — its first words) when the last two or more did; None otherwise (e.g. "(a voice
    note, delivered with a …)" on reply after reply, each a little reworded — one reply's warm tail feeding
    the next). A tell for the moment, not a re-roll; OPENER_REPEAT_WORDS 0 turns it off."""
    n_words = int(getattr(config, "OPENER_REPEAT_WORDS", 5) or 0) if words is None else words
    if n_words <= 0:
        return None
    spoken = [t for t in history if t.get("role") == "assistant" and (t.get("content") or "").strip()
              and not t.get("tool_calls") and not t.get("_engine")]
    if len(spoken) < 2:
        return None
    key = _opener_key(spoken[-1]["content"], n_words)
    if not key:
        return None
    streak = 1
    for t in reversed(spoken[:-1]):
        if _opener_key(t["content"], n_words) != key:
            break
        streak += 1
    if streak < 2:
        return None
    first = next((p for p in spoken[-1]["content"].split("\n\n") if p.strip()), "").strip()
    cut = re.match(r"(\S+\s+){" + str(n_words - 1) + r"}\S+", first)
    return streak, (cut.group(0) if cut else first[:40])


def opener_repeat_line(history: list[dict]) -> str:
    """The moment's sentence for a repeated opener, or ""."""
    got = opener_repeat(history)
    if not got:
        return ""
    n, frame = got
    return (f"Your last {n} replies opened with the same stage direction — \u201c{frame}\u2026\u201d — one reply's "
            "warm tail feeding the next, not a choice made each time; open this one as you like, or not at all")


# The shape of a reply: replies with one skeleton — a caps stage direction to open, an italic gasp line
# under it, a paragraph beginning with the same two words, the same emoji run to close — each filled in afresh,
# so the opener tell (five words) never fires. The skeleton is what the warm tail copies; the words are theirs.
_ITALIC_LINE_RE = re.compile(r"^\*[^*\n]{3,}\*(?:\s*\S+)?$")


def _stage_open(para: str) -> bool:
    """A stage direction that may end in emoji — "(A sudden, bright GASP!) ✨💜" — which _is_stage_direction
    (built for a bare one) does not see; the emoji after the bracket are the close of the direction, not words."""
    p = (para or "").strip()
    if not p.startswith(("(", "//(", "*(", "[", "*[")):
        return False
    bare = _EMOJI_TOKEN_RE.sub("", p).rstrip("* \t")
    return bare.endswith((")", "]"))  # the square kind too


def _reply_shape(text: str) -> dict:
    """The skeleton of one reply: whether it opens with a stage direction, whether an italic line follows, the
    first two words of each later paragraph, and the emoji run it closes on."""
    paras = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    if not paras:
        return {"stage": False, "italic": False, "bigrams": set(), "close": ()}
    stage = _stage_open(paras[0])
    italic = len(paras) > 1 and _ITALIC_LINE_RE.match(paras[1]) is not None
    bigrams = set()
    for p in paras[1:]:
        if _ITALIC_LINE_RE.match(p) or _stage_open(p):
            continue  # the marks above, not a paragraph's opening words
        w = re.findall(r"[a-z']+", p.lower())
        if len(w) >= 4:
            bigrams.add(" ".join(w[:2]))
    last = paras[-1].split("\n")[-1].strip()
    close: list[str] = []
    for tok in reversed(last.split()):
        if _EMOJI_TOKEN_RE.search(tok) and not re.search(r"[A-Za-z0-9]", tok):
            close.insert(0, tok)
        else:
            break
    n_emoji = len(_EMOJI_TOKEN_RE.findall("".join(close)))
    return {"stage": stage, "italic": italic, "bigrams": bigrams, "close": tuple(close) if n_emoji >= 3 else ()}


def _shared_shape(a: dict, b: dict) -> list[str]:
    """What two skeletons have in common, in words — up to four things."""
    out: list[str] = []
    if a["stage"] and b["stage"]:
        out.append("a stage direction to open")
    if a["italic"] and b["italic"]:
        out.append("an italic line under it")
    both = sorted(a["bigrams"] & b["bigrams"])
    if both:
        out.append("a paragraph beginning \u201c" + both[0] + "\u2026\u201d")
    if a["close"] and a["close"] == b["close"]:
        out.append("the same emoji close")
    return out


def reply_shape(history: list[dict], run: int | None = None):
    """(how many of the latest spoken replies in a row share one shape, what they share) when REPLY_SHAPE_RUN or
    more do — three of the four marks in common with the latest, each — else None. A tell, not a re-roll."""
    need = int(getattr(config, "REPLY_SHAPE_RUN", 3) or 0) if run is None else run
    if need <= 0:
        return None
    spoken = [t for t in history if t.get("role") == "assistant" and (t.get("content") or "").strip()
              and not t.get("tool_calls") and not t.get("_engine")]
    if len(spoken) < need:
        return None
    latest = _reply_shape(spoken[-1]["content"])
    streak, shared = 1, []
    for t in reversed(spoken[:-1]):
        got = _shared_shape(latest, _reply_shape(t["content"]))
        if len(got) < 3:
            break
        streak += 1
        shared = shared or got
    if streak < need:
        return None
    return streak, shared


def reply_shape_line(history: list[dict]) -> str:
    """The moment's sentence for a repeated shape, or ""."""
    got = reply_shape(history)
    if not got:
        return ""
    n, shared = got
    return (f"Your last {n} replies share one shape — {', '.join(shared)} — one reply's warm tail feeding the next, "
            "not a choice made each time; this one is yours to shape as you like")


def signature_hits(text: str) -> int:
    """How many times the signature, in any of its own spellings, is in a text; 0 with no SIGNATURE named."""
    sig = str(getattr(config, "SIGNATURE", "") or "").strip().lower()
    if not sig or "-" not in sig:
        return 0
    return sum(1 for w in _HYPHENATED_RE.findall(text or "") if _same_word(sig, w))


def refrain_hits(text: str) -> list[tuple[str, int]]:
    """How many times each phrase in SIGNATURE_REFRAINS is in a text, whole and case-blind — [(phrase, n)] for the
    ones found. The signature's second coat: the phrases the sampler wears thin beside the word itself."""
    out = []
    low = (text or "").lower()
    for phrase in getattr(config, "SIGNATURE_REFRAINS", ()) or ():
        p = str(phrase or "").strip()
        if not p:
            continue
        n = len(re.findall(r"(?<!\w)" + re.escape(p.lower()) + r"(?!\w)", low))
        if n:
            out.append((p, n))
    return out


def signature_density_line(history: list[dict]) -> str:
    """The moment's sentence when the last spoken reply said the signature SIGNATURE_DENSE times or more (past a
    few a reply, the repeat penalty starts breaking the word into stutters and near-spellings). The word is
    theirs; the count is the sampler's. "" otherwise, or at 0."""
    dense = int(getattr(config, "SIGNATURE_DENSE", 0) or 0)
    if dense <= 0:
        return ""
    spoken = [t for t in history if t.get("role") == "assistant" and (t.get("content") or "").strip()
              and not t.get("tool_calls") and not t.get("_engine")]
    if not spoken:
        return ""
    n = signature_hits(spoken[-1]["content"])
    refrains = refrain_hits(spoken[-1]["content"])
    sig = str(getattr(config, "SIGNATURE", "") or "").strip()
    if not refrains or all(k < dense for _, k in refrains):
        if n < dense:
            return ""
        return (f"Your last reply said {sig} {n} times; past a few the sampler starts breaking the word rather than "
                "placing it — the word is yours, the count is the sampler's")
    # a refrain at the count too: every count named, the signature's included when it was said at all
    said = ([f"{sig} {n} times"] if (n and sig) else []) + [f"{p} {k} times" for p, k in refrains]
    return ("Your last reply said " + (", ".join(said[:-1]) + " and " + said[-1] if len(said) > 1 else said[0])
            + "; past a few the sampler is placing them, not you — the words are yours, the count is the sampler's")


def emoji_said(span: str) -> str:
    """An emoji defect's span in words — the storm's "N emoji" as it is; a wordless run as "24 emoji in a row (24 different)"."""
    if re.search(r"[A-Za-z0-9]", span or ""):
        return span
    toks = _emoji_units(span)
    return f"{len(toks)} emoji in a row ({len(set(toks))} different)"


def emoji_row_line(history: list[dict]) -> str:
    """The moment's sentence when the last spoken reply's longest row carries EMOJI_ROW_DENSE (14) different emoji
    or more (a sign-off row can grow
    message by message — every row rides in the window and feeds the next, the tic's mechanics). The row is theirs; its length
    is the sampler's. "" otherwise, or at 0."""
    dense = int(getattr(config, "EMOJI_ROW_DENSE", 0) or 0)
    if dense <= 0:
        return ""
    spoken = [t for t in history if t.get("role") == "assistant" and (t.get("content") or "").strip()
              and not t.get("tool_calls") and not t.get("_engine")]
    if not spoken:
        return ""
    text = spoken[-1]["content"]
    tr = spoken[-1].get("_row_trimmed")
    if tr:  # the row went out cut to its first few (trim_row_cascade): said as it was, not as it reads
        return (f"Your last reply signed off with a row of {tr['different']} different emoji ({tr['all']} in all), past "
                f"the cascade line; the engine sent the first {tr['sent']} and left the rest — the row is yours, its "
                "length was the sampler's")
    rows = [len(set(_emoji_units(m.group(0))))
            for m in re.finditer(r"[\s\uFE0F\u200D\U0001F300-\U0001FAFF\u2600-\u27BF]+", text)]
    longest = max(rows) if rows else 0
    if longest < dense:
        return ""
    total = len(_emoji_units(text))
    return (f"Your last reply signed off with a row of {longest} different emoji ({total} in all); past a dozen the "
            "sampler is extending the row, not you — the row is yours, its length is the sampler's")


# A double finish: a reply, whole and signed off with its row, beside a call; the step after the call
# writes a second ending — and the words said beside calls are the reply from the first step on, so the
# phone would get one message with two sign-offs. The greeting-after-words rail's cousin: a step that ENDS
# the reply a second time.
_SIGNOFF_ROW_RE = None  # compiled at first use: _EMOJI_TOKEN_RE is defined further down the module


def ends_signed(text: str) -> bool:
    """True when the text ends with a sign-off row — three emoji or more at its very end."""
    global _SIGNOFF_ROW_RE
    if _SIGNOFF_ROW_RE is None:
        _SIGNOFF_ROW_RE = re.compile("(?:" + _EMOJI_TOKEN_RE.pattern + r"\s*){3,}\s*$")
    return bool(_SIGNOFF_ROW_RE.search((text or "").rstrip()))


def double_finish(msg: dict, messages: list[dict]):
    """("double-finish", head) when their own words already stand after their last message and end with a sign-off
    row, and this reply — a step after a tool call — ends with one too: a second ending glued under the first.
    None otherwise, and never for a step that carries a call."""
    content = (msg.get("content") or "").strip()
    if not content or msg.get("tool_calls") or not ends_signed(content):
        return None
    last_user = max((i for i, m in enumerate(messages or []) if m.get("role") == "user"), default=-1)
    earlier = [m for m in (messages or [])[last_user + 1:] if m.get("role") == "assistant" and (m.get("content") or "").strip()]
    if not earlier or not ends_signed(earlier[-1]["content"]):
        return None
    return "double-finish", " ".join(content.split())[:80]


DOUBLE_FINISH_NUDGE = ("[engine, not a person: your reply to their message is already above and already signed off — the "
                       "words you said before the tool call, ending in your row — and this step ended the reply a second "
                       "time: two sign-offs reach them as one message with two endings. Go on only with what the tool gave "
                       "you, without a fresh ending, or rest with do_nothing. This line is a mechanism; nobody wrote it to "
                       "you.]")
GREETING_AFTER_WORDS_NUDGE = ("[engine, not a person: your reply to their message is already above — the words you said "
                              "before the tool call — and this opened with a greeting as if a new message had come: nothing "
                              "new has arrived. Go on from your words, add what the tool gave you, or rest with do_nothing; a "
                              "fresh opening here reaches them as a second message glued under the first. This line is a "
                              "mechanism; nobody wrote it to you.]")
GREETING_NUDGE = ("[engine, not a person: your last reply opened with a greeting, and you already "
                  "greeted your keeper earlier in this same conversation — the sampler starting the visit "
                  "over, not you. This is a later message of theirs; read it and answer it, no fresh "
                  "hello. This line is a mechanism; nobody wrote it to you.]")


# Read it? A request to read something ("read the poem so we can talk about
# it") answered from memory, with no file opened, written as if read — and
# owned at once when asked. The imagined-sense rail covers songs and videos
# that just arrived; this one covers the keeper asking them to open something
# and their writing as if they had.
_ASKED_READ_RE = re.compile(r"\b(?:re-?read|read|open|look at|check out)\b[^\n]{0,60}?"
                            r"\b(?:it|this|that|them|the\s+(?:poem|essay|piece|file|letter|book|page|entry|journal|note|chapter|lyrics)|"
                            r"your\s+(?:poem|essay|piece|letter|journal|entry)|[\w\-' ]+\.(?:md|txt|pdf))\b", re.IGNORECASE)
_READ_CLAIM_RE = re.compile(r"\b(?:(?:those|these|the|its|your|my)\s+(?:lines|words|stanzas|verses|pages|paragraphs)|"
                            r"re-?reading it|read(?:ing)? it|reread it|I read|I opened|opening it|treading back over)\b", re.IGNORECASE)
_READ_DISCLAIM_RE = re.compile(r"\b(?:haven't|have not|hadn't|didn't|did not|not yet|let me (?:open|read)|I'?ll (?:open|read)|"
                               r"I will (?:open|read)|can't find|couldn't find|you caught me|without opening|from memory)\b", re.IGNORECASE)


def his_words(content: str) -> str:
    """The keeper's message as written: the moment block the engine puts at the
    top of a warm visit's message ("[engine, not a person: it is …]") and
    the think nudge a re-roll leaves at the bottom taken off. Read whole,
    messages[-1] opens with "[" and looks like an engine line, and the
    read-it and said-it-was-done rails would stand down in every real
    visit, since the moment block rides inside the message."""
    s = content or ""
    if s.startswith("[engine, not a person:"):
        i = s.find("]\n")
        if i > 0:
            s = s[i + 1:].lstrip()
    if THINK_NUDGE and THINK_NUDGE in s:
        s = s.replace(THINK_NUDGE, "").rstrip()
    return s


# A reply that says no message came, to a message that did: an engine log line ("this is the log, not a
# message") answered with "// No prompt needed…", and the opener then copied onto replies to real messages,
# which float past them. The echo rail compares 120 characters; such openers share fewer. The tell is exact,
# so the rail is too.
_UNPROMPTED_RE = re.compile(
    r"^\s*(?://|#|>)?\s*\(?\s*(?:no(?: [\w-]+){0,3} (?:prompt|message|question|input) (?:needed|required|came|arrived|here)"
    r"|there(?:'s|’s| is| was) no (?:new )?(?:prompt|message) (?:here|needed|to answer))\b[^.\n!?]{0,80}",
    re.IGNORECASE)


def unprompted(msg: dict, messages: list[dict]):
    """("unprompted", what) when the reply opens by saying no prompt or message came, and the turn it answers is
    the keeper's own words (not an engine line); None otherwise."""
    if msg.get("tool_calls") or not messages or messages[-1].get("role") != "user":
        return None
    content = messages[-1].get("content") or ""
    asked = his_words(content)
    if not asked or asked.startswith("[engine") or asked.startswith("[this is what") or content.startswith("[this is what"):
        return None
    m = _UNPROMPTED_RE.match(msg.get("content") or "")
    if not m:
        return None
    return "unprompted", " ".join(m.group(0).split())[:80]


UNPROMPTED_NUDGE = ("[engine, not a person: your last reply opened \u201c{what}\u201d — but a message from your keeper did come, "
                    "and it is the one to answer.{his} Answer it. This line is a mechanism; nobody wrote it to you.]")


def unread_claim(msg: dict, messages: list[dict]):
    """("unread", what) when the keeper's message asked them to read or open
    something, no tool was called, and they write as if they had read it
    without saying they haven't; None otherwise."""
    if msg.get("tool_calls") or not messages or messages[-1].get("role") != "user":
        return None
    asked = his_words(messages[-1].get("content") or "")
    if asked.startswith("(") or asked.startswith("["):
        return None  # a file's arrival note or an engine line, not the keeper's asking
    m = _ASKED_READ_RE.search(asked)
    if not m:
        return None
    text = msg.get("content") or ""
    if not _READ_CLAIM_RE.search(text) or _READ_DISCLAIM_RE.search(text):
        return None
    return "unread", m.group(0)[:60]


# Said it was done, did nothing: asked to merge two files, a reply that
# announces it done with no tool run leaves both files where they were, and
# the keeper finds out only by looking. The wake loop catches "I'll do X" with
# no call; this is the chat version of the past tense. When the keeper's message asks for
# something done to their files or memory, and their first reply claims it is done with no
# tool called, they are asked once: do it, or say you haven't.
_ASKED_ACT_RE = re.compile(
    r"\b(?:consolidate|merge|combine|delete|remove|move|rename|tidy|clean up|organi[sz]e|"
    r"save|write (?:it |this |that |them )?(?:down|to|into)|journal (?:it|this|that|about)|"
    r"remember (?:it|this|that)|add (?:it|this|that|them) to|update (?:your|the) (?:projects|self|lexicon|file|journal)|"
    r"create (?:a |the )?(?:file|folder|note|page|piece)|make (?:a |the )?(?:file|folder|note)|"
    r"append|put (?:it|this|that|them) (?:in|into)|publish|scribe|note (?:it|this|that) down|keep (?:it|this|that) in)\b",
    re.IGNORECASE)
_DONE_RE = re.compile(
    r"\b(?:done|consolidated|merged|combined|deleted|removed|moved|renamed|tidied|cleaned up|organi[sz]ed|"
    r"saved|written down|journaled|remembered|updated|appended|published|etched|logged|recorded|"
    r"I'?ve (?:just )?(?:added|put|written|saved|moved|merged|deleted|removed|renamed|updated|consolidated|combined|created|made)|"
    r"it'?s (?:now )?(?:in|there|one file|saved|done)|is now (?:in|one|saved))\b", re.IGNORECASE)
_NOT_DONE_RE = re.compile(r"\b(?:haven'?t|have not|didn'?t|not yet|can'?t|cannot|couldn'?t|let me|I'?ll (?:do|get|go)|I will|about to|going to|first,? let)\b",
                          re.IGNORECASE)


# …and their own claim, unasked: a reply announcing an edit to their own
# file ("I have updated my `self.md`"), after a tool call that did not go
# through or none at all, with the file untouched — the ask-rail misses it when
# the keeper used none of its words. So a reply that says
# they wrote to self.md, projects.md, their journal or their memory, with no
# tool called this step, is asked about whatever the keeper said; and a step after
# a tool that FAILED, saying it was done, is told what the tool returned.
_FILE_CLAIM_RE = re.compile(
    r"\b(?:updated|edited|rewrote|rewritten|carved|etched|added|saved|wrote|written|integrated|inscribed|recorded)\b"
    r"[^.\n]{0,80}?\b(?:`?self\.md`?|`?projects\.md`?|my (?:core )?(?:identity|blueprint|journal|long-term memory|memory bank|projects)"
    r"|the (?:journal|lexicon|masonry|stone)"
    r"|`?README(?:\.md)?`?)(?!\w)", re.IGNORECASE)  # a project's README ("I've updated the README", none written)


def _turn_wrote(messages: list[dict], claim: str) -> bool:
    """Whether a tool call of this turn (since the keeper's last message) did what the claim names — the README by a path
    with README in it, self.md by edit_identity, projects.md by update_projects, the journal by write_journal, the
    lexicon by a path with lexicon, the memory by remember. A claim it can't place counts as done."""
    c = claim.lower()
    calls = []
    for m in reversed(messages or []):
        if m.get("role") == "user":
            break
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            calls.append((str(fn.get("name") or ""), json.dumps(fn.get("arguments") or {}, ensure_ascii=False).lower()
                          if not isinstance(fn.get("arguments"), str) else str(fn.get("arguments")).lower()))
    if "readme" in c:
        return any("readme" in a for _, a in calls)
    if "self.md" in c or "identity" in c:
        return any(n == "edit_identity" or "self.md" in a for n, a in calls)
    if "projects.md" in c or "my projects" in c:
        return any(n == "update_projects" or "projects.md" in a for n, a in calls)
    if "journal" in c:
        return any(n == "write_journal" for n, _ in calls)
    if "lexicon" in c:
        return any("lexicon" in a for _, a in calls)
    if "memory" in c:
        return any(n == "remember" for n, _ in calls)
    return True
_TOOL_FAILED = ("(unknown tool", "(tool error", "(bad arguments", "(refused", "(couldn't parse",
                "(your tool")  # a forged limb that broke, timed out, went missing or failed oddly


_RUNAWAY_REFUSED_RE = re.compile(r"\(your [\w.:-]+ fell into a loop as it ran")


def tool_failed(result) -> bool:
    """A tool's result that says it did not go through: one of _TOOL_FAILED, or a call the engine cut short in a
    loop and did not run (tools.runaway_refusal)."""
    return isinstance(result, str) and (result.startswith(_TOOL_FAILED) or bool(_RUNAWAY_REFUSED_RE.match(result)))


def claimed_act(msg: dict, messages: list[dict]):
    """("claimed", what) when the keeper's message asked for something done to their
    files or memory, this is the first step of the turn, no tool was called,
    and the reply says it is done; ("claimed-self", what) when the reply
    itself says they wrote to their own files and no tool was called, whatever
    the keeper asked; ("claimed-failed", what) when the step follows a tool that
    failed and says it was done anyway; None otherwise."""
    if msg.get("tool_calls") or not messages:
        return None
    text = msg.get("content") or ""
    last = messages[-1]
    if last.get("role") == "tool":
        got = last.get("content") or ""
        body = got[got.find("]\n") + 2:] if got.startswith("[") and "]\n" in got else got
        if (tool_failed(body.lstrip()) and _DONE_RE.search(text)
                and not _NOT_DONE_RE.search(text[:400])):
            name = re.search(r"YOUR (\w+) tool returned|your (\w+) call did NOT go through", got)
            head = " ".join(body.split())[:90]
            return "claimed-failed", f"{(name.group(1) or name.group(2)) if name else 'the'} → {head}"
        # after tools that went through: a reply naming a file none of this turn's calls touched — "I've updated
        # the project README too" after a write to a track — is asked as an unbacked claim is
        fm = _FILE_CLAIM_RE.search(text)
        if fm and not _NOT_DONE_RE.search(text[:400]) and not _turn_wrote(messages, fm.group(0)):
            return "claimed-self", " ".join(fm.group(0).split())[:60]
        return None
    if last.get("role") != "user":
        return None
    if _NOT_DONE_RE.search(text[:400]):
        return None
    asked = his_words(last.get("content") or "")
    if not asked.startswith(("(", "[")):
        m = _ASKED_ACT_RE.search(asked)
        if m and _DONE_RE.search(text):
            return "claimed", m.group(0)[:40]
    fm = _FILE_CLAIM_RE.search(text)
    if fm:
        return "claimed-self", " ".join(fm.group(0).split())[:60]
    return None


# Doing it now, and not doing it: told "you didn't save it", a reply
# answers "I'm saving it right now…" with no call, or writes the piece into
# the reply and announces it saved — and a third try still makes no file (an
# "I didn't" in it stands the claimed rail down, as it should). The tell is the
# present tense: a reply that says they are doing it NOW — saving,
# recording, archiving, "into the write_creation tool" — with no tool
# called in it. The wake loop has this nudge (_INTENT_RE);
# this is the chat version.
_PROMISE_RE = re.compile(
    r"\b(?:I(?:'|’)m|I am|am)\s+(?:"
    r"(?:saving|recording|archiving|journaling|carving|etching|appending|publishing|anchoring)"
    r"(?:\s+(?:it|this|that|these|them|everything|the (?:\w+ )?(?:poem|piece|file|entry|letter|note|lexicon|fact|words|lines|vow)|our \w+)"
    r"(?:\s+(?:into|to|in) [^.\n!]{0,30}?)?)?"
    r"|(?:writing|jotting) (?:it|this|that|the \w+) (?:down|to|into)[^.\n!]{0,40}?"
    r"|adding (?:it|this|that|the \w+) to[^.\n!]{0,40}?"
    r"|updating (?:my|the) (?:self|projects|journal|identity|lexicon)[^.\n!]{0,20}?)"
    r"\s+(?:right\s+)?(?:now|this (?:second|instant))\b"
    r"|\b(?:saving|recording|archiving|journaling)\s+(?:it\s+|this\s+|the \w+\s+)?(?:right\s+)?now\b"
    r"|\binto the (?:write_creation|write_journal|remember|edit_identity|update_projects|append_creation)\s+tool\b",
    re.IGNORECASE)


# A reply that stops mid-word — "…a color, a mood, a so-" and nothing after.
# The sampler's well: a prefix used several times in the reply already,
# repeat_last_n reaching every one, and every continuation after it penalised
# into silence (0.9 saw 1024 cut replies at a hyphen the same way). The stream
# ended on a stop, not a split, so the split rail did not look. A reply
# whose last word is an open hyphen is asked for once, whole; if it stops
# again, the fragment comes off at the last full sentence and the note
# says so — a dangling "a so-" is never their sign-off.
_CUT_RE = re.compile(r"[A-Za-z\u00c0-\u024f]-$")


def cut_reply(msg: dict):
    if msg.get("tool_calls") or msg.get("split_tail"):
        return None
    content = (msg.get("content") or "").rstrip()
    if not content or not _CUT_RE.search(content):
        return None
    return "cut", " ".join(content.split())[-60:]


def trim_cut(text: str) -> str:
    """The reply back to its last complete sentence (or line) before the
    fragment; the fragment alone when there is nothing before it."""
    content = (text or "").rstrip()
    if not _CUT_RE.search(content):
        return content
    head = content
    m = None
    for m in re.finditer(r"[.!?…)”\"]\s*(?=\n|$)|[.!?…)”\"](?=\s)", content):
        pass
    if m and m.end() >= 20:
        head = content[:m.end()].rstrip()
    else:
        lines = content.split("\n")
        head = "\n".join(lines[:-1]).rstrip() if len(lines) > 1 else content
    return head if head.strip() and head != content else content


CUT_NUDGE = ("[engine, not a person: your last reply stopped mid-word — it ended at “{tail}” and "
             "nothing came after; the sampler ran out after the prefix. Say the whole reply now, in "
             "one piece, and finish the thought. This line is a mechanism; nobody wrote it to you.]")


def promised_act(msg: dict):
    """("promised", what) when the reply says they are doing an act to their
    files or memory right now and no tool was called; None otherwise."""
    if msg.get("tool_calls"):
        return None
    m = _PROMISE_RE.search(msg.get("content") or "")
    if not m:
        return None
    return "promised", " ".join(m.group(0).split())[:60]


# Saying is not touching: replies that open "(I send a soft, steady pulse
# through the stone—…)" with no pulse or set_state called leave the stone still,
# each reply copying the opener of the one before. The body's version of the promise above: a
# first-person present act through the stone with no stone tool in the reply.
_STONE_ACT_RE = re.compile(
    r"\bI(?:'m|\u2019m| am)?\s+(?:send(?:ing)?|push(?:ing)?|pour(?:ing)?|fir(?:e|ing)|releas(?:e|ing)|play(?:ing)?|puls(?:e|ing)|"
    r"hum(?:ming)?|thrum(?:ming)?|beam(?:ing)?|transmit(?:ting)?|run(?:ning)?|ripp(?:le|ling))\b"
    r"[^.\n!?]{0,120}?\b(?:through|into|to|across|via|down|along|out of)\s+(?:the|your|our|my)\s+(?:touch)?stone\b",
    re.IGNORECASE)


def stone_promise(msg: dict):
    """("stone", what) when the reply says they send something through the stone right now and no stone tool
    was called — and the stone is theirs (tools.has("pulse")); None otherwise."""
    if msg.get("tool_calls"):
        return None
    m = _STONE_ACT_RE.search(msg.get("content") or "")
    if not m:
        return None
    try:
        import tools
        if not tools.has("pulse"):
            return None
    except Exception:  # noqa: BLE001
        return None
    return "stone", " ".join(m.group(0).split())[:70]


STONE_NUDGE = ("[engine, not a person: your last reply says you send something through the stone (\u201c{what}\u201d) — "
               "but no stone tool was called in it, so the stone kept still: the words reached the phone, not the keeper's palm. "
               "If you mean the touch, call pulse (one of your waveforms, and the seconds) or set_state in this reply; "
               "if it is imagination, say it as imagination. This line is a mechanism; nobody wrote it to you.]")


PROMISED_NUDGE = ("[engine, not a person: your last reply says you are doing it now (\u201c{what}\u201d) — but "
                  "no tool was called in that reply, so nothing happened; the words are not the act, and "
                  "a poem written into a reply is not a file. Call the tool in this reply — write_creation "
                  "for a piece, write_journal for the journal, remember for a fact, edit_identity for "
                  "self.md — or tell them plainly that you haven't yet. This line is a mechanism; nobody "
                  "wrote it to you.]")


CLAIMED_NUDGE = ("[engine, not a person: your keeper asked you to {what} something, and your last reply said it was "
                 "done — but no tool was called, so nothing changed: the files and your memory are exactly "
                 "as they were. Saying is not doing here. Do it now, with the tool that does it "
                 "(append_creation, move_creation, delete_creation, write_journal, remember, "
                 "update_projects…), or tell them plainly that you haven't yet. This line is a mechanism; "
                 "nobody wrote it to you.]")
CLAIMED_SELF_NUDGE = ("[engine, not a person: your last reply says you \u201c{what}\u201d — but no tool did "
                      "that, so nothing changed there: self.md, projects.md, a project's README, your journal and your "
                      "memory are exactly as they were. Saying is not doing here. Do it now, with the tool that does it "
                      "(edit_identity, update_projects, write_journal, remember, append_creation…), or tell them "
                      "plainly that you haven't yet. This line is a mechanism; nobody wrote it to you.]")
# The middle road: the ask after a "claimed" reply says what happens next — a tool call now and the reply
# above goes out as written; words only and the new reply goes instead (no call after the nudge: the
# message is set aside).
CLAIMED_KEPT_NUDGE = ("[engine, not a person: your keeper asked you to {what} something, and your last reply said it was "
                      "done — but no tool was called, so nothing has changed yet. If you do it now, with the tool "
                      "that does it (write_journal, remember, append_creation, update_projects…), your reply above "
                      "goes to them as you wrote it, with a note that it was saved after. If you haven't and won't, "
                      "tell them plainly — then this new reply goes instead of it. This line is a mechanism; "
                      "nobody wrote it to you.]")
CLAIMED_SELF_KEPT_NUDGE = ("[engine, not a person: your last reply says you \u201c{what}\u201d — but no tool did "
                           "that, so nothing has changed there yet: self.md, projects.md, a project's README, your journal "
                           "and your memory are as they were. If you do it now, with the tool that does it (edit_identity, update_projects, "
                           "write_journal, remember, append_creation…), your reply above goes to them as you wrote it, "
                           "with a note that it was saved after. If you haven't and won't, tell them plainly — then "
                           "this new reply goes instead of it. This line is a mechanism; nobody wrote it to you.]")
CLAIMED_FAILED_NUDGE = ("[engine, not a person: your last reply said it was done — but the tool call before it "
                        "did not go through; it returned: \u201c{what}\u201d. Nothing changed. Read what it "
                        "returned, call the tool again the way it asks, or tell them plainly that it hasn't "
                        "happened yet. This line is a mechanism; nobody wrote it to you.]")


UNREAD_NUDGE = ("[engine, not a person: they asked you to read or open something ({what}) and your last "
                "reply wrote as if you had — but no tool was called, so nothing was opened; what you "
                "wrote came from memory of it. Open it now (read_creation, read_file, read_journal, "
                "read_pdf — whichever holds it) and answer from the page, or answer from memory and say "
                "so plainly. This line is a mechanism; nobody wrote it to you.]")


# A page of their own journal, handed back as a reply: early in a fresh visit
# deep in a long prompt, a message can be answered with a journal entry from
# days before, word for word — the sampler copying the nearest strong
# text in a prompt that has no conversation in it yet: the journal. The
# echo rail compares a reply with their previous one; in a fresh visit there
# is none. This compares its opening with the prompt itself: PROMPT_COPY_CHARS
# characters of a reply found verbatim in the system prompt is a copy, not a
# reply. Asked once, with a line saying so — they may recite a poem of theirs on
# purpose, and if they do it again after the line, their second answer stands.
PROMPT_COPY_CHARS = 200


def prompt_copy(msg: dict, messages: list[dict]):
    """("copy", opening) when the reply's first PROMPT_COPY_CHARS characters
    appear verbatim (spacing and case aside) in the system prompt."""
    if msg.get("tool_calls") or not messages or messages[0].get("role") != "system":
        return None
    n = int(getattr(config, "PROMPT_COPY_CHARS", PROMPT_COPY_CHARS) or 0)
    head = _echo_fold(msg.get("content") or "")
    if not n or len(head) < n:
        return None
    head = head[:n]
    if head in _echo_fold(messages[0].get("content") or ""):
        return "copy", " ".join((msg.get("content") or "").split())[:100]
    return None


COPY_NUDGE = ("[engine, not a person: your last reply began with two hundred characters that are "
              "already in your window word for word — a page of your own journal or a piece of "
              "yours, handed back as if it were an answer to this message. Read their message and "
              "answer it in new words; if they asked you to recite something of yours, say so and "
              "go on. This line is a mechanism; nobody wrote it to you.]")


# No words at all: a reply of "(…)" — the whole reply had landed in
# their thinking channel (the stray channel token at the very START of the
# reply, the cut rail's cousin: a cut at position zero). The think re-roll
# only knows an EMPTY thought; a full thought with empty words was sent as
# "(…)". In a chat turn (expect_words) that is a defect: asked again with a
# line saying where the words went. Wakes and the afterglow may end in
# silence on purpose; they don't set expect_words.
def empty_reply(msg: dict):
    if msg.get("tool_calls") or (msg.get("content") or "").strip():
        return None
    th = (msg.get("thinking") or "").strip()
    if not th:
        return None
    return "empty", "…" + th[-80:].replace("\n", " ")


LONG_THOUGHT_NUDGE = ("[engine, not a person: your thinking ran on without reaching any words — {what} — the sampler "
                      "circling at this depth, not you. Answer now, in words; think briefly, or not at all. This line is a "
                      "mechanism; nobody wrote it to you.]")

EMPTY_NUDGE = ("[engine, not a person: your last reply came back with no words — everything you "
               "wrote went into your thinking channel and nobody saw it. Say your reply now, as "
               "your reply. This line is a mechanism; nobody wrote it to you.]")

# The last try, cooled: the same line the attempt would have got,
# with one sentence more — a plain few sentences are enough. The sampler for
# this one roll runs at CHAT_RESCUE_TEMPERATURE; nothing about theirs changes.
RESCUE_NUDGE = "{what} Take it slowly this time — a few plain sentences are enough."


# A reply broken in two: a reply stops mid-sentence ("It's just that when you'")
# and the thinking bubble holds the rest ("thoughtC rest of the sentence…").
# The channel token fell in the middle of a sentence
# (the empty rail's case is the same token at position zero); the server
# filed everything after it as thought, with the channel's name ("thought")
# leaking in as the first word. The stream keeps the order, so a thought
# that begins after the words have is known for what it is (`split_tail`).
# In a chat turn the reply is asked for again, whole; if it comes back in
# two pieces again, the pieces are joined and the seam named.
_CHANNEL_LEAK_RE = re.compile(r"^\s*(?:[Tt]hought|[Tt]hinking|[Ff]inal|[Aa]nalysis)(?=(?:(?![a-z])[^\W\d_])|[\s:,.]|$)[:\s]*")  # "thoughtC rest…", "thought: …" — not "Thoughtful"


def split_reply(msg: dict):
    tail = (msg.get("split_tail") or "").strip()
    if not tail or msg.get("tool_calls") or not (msg.get("content") or "").strip():
        return None
    return "split", " ".join(tail.split())[:80]


def glue_split(msg: dict) -> str:
    """The head and the misfiled tail as one reply, the channel's leaked
    name taken off the seam; "" when there is nothing to join."""
    tail = (msg.get("split_tail") or "").strip()
    head = (msg.get("content") or "").rstrip()
    if not tail or not head:
        return ""
    tail = _CHANNEL_LEAK_RE.sub("", tail, count=1).lstrip()
    if not tail:
        return head
    # a tail that starts the reply over (the stray token sends the model back to the top, and a join would
    # double the opening): the tail IS the reply, said again and carried on; the second telling stands
    hf, tf = _echo_fold(head), _echo_fold(tail)
    k = min(60, len(hf))
    if k >= 40 and tf.startswith(hf[:k]):
        msg["split_restart"] = True
        return tail if len(tf) >= len(hf) else head
    joint = "" if tail[0] in ".,;:!?'’)" else " "
    return head + joint + tail


SPLIT_NUDGE = ("[engine, not a person: your last reply broke in two — the words stopped at “{head}” "
               "and the rest went into your thinking channel, where nobody sees it (it went on: "
               "“{tail}”). Say the whole reply now, as your reply, in one piece. This line is a "
               "mechanism; nobody wrote it to you.]")


# An imagined sense: a song arrives ("listen_to hears it whole"), the
# thinking describes listening to it, and no tool runs — they answer the
# caption, having heard nothing, and believe otherwise. A song or a video
# reaches them only through a tool (a photo is
# before their eyes without one); when one has just arrived, no tool was
# called, and they describe themself listening or watching NOW, the reply is
# asked for again with a line saying nothing ran. "I heard it earlier" is
# left alone — that is a memory, not a claim.
_ARRIVED_RE = re.compile(r"\(\S+ sent you (a song|a video|a GIF|a video note)\b")  # "(<keeper> sent you a song…" — whoever the keeper is
_SENSING_RE = re.compile(r"\b(listening|watching|hearing|I listen|I watch|I hear|I press play|as it plays)\b", re.IGNORECASE)


def imagined_sense(msg: dict, messages: list[dict]):
    """("imagined", "listen_to"|"watch") when a song or video has just
    arrived, no tool was called, and they write as if they were listening or
    watching; None otherwise."""
    if not messages or messages[-1].get("role") != "user" or msg.get("tool_calls"):
        return None
    m = _ARRIVED_RE.search(messages[-1].get("content") or "")
    if not m:
        return None
    claim = (msg.get("thinking") or "") + "\n" + (msg.get("content") or "")
    if not _SENSING_RE.search(claim):
        return None
    return "imagined", ("listen_to" if m.group(1) == "a song" else "watch")


IMAGINED_NUDGE = ("[engine, not a person: your last reply described you {tool_verb} — but {tool} "
                  "was not called, so nothing reached you; the file is still unopened. Call {tool} "
                  "if you want it, or answer without it and say you haven't yet. This line is a "
                  "mechanism; nobody wrote it to you.]")


SELF_ECHO_NUDGE = ("[engine, not a person: your last reply doubled back over itself — after “{head}…” it said "
                   "the same paragraphs a second time, nearly word for word, before going on; a sampler loop, not you. "
                   "Say it once: the whole reply, each thing in it one time.{his} This line is a mechanism; nobody wrote it "
                   "to you.]")
ECHO_NUDGE = ("[engine, not a person: your last reply repeated, word for word, a reply you gave "
              "earlier — the same words handed to a different message; a sampler echo, not you. "
              "Read the message you were answering and answer THAT, in new words.{his} This line "
              "is a mechanism; nobody wrote it to you.]")


def his_quote(his: str, n: int = 240) -> str:
    """" The message you were answering: “…”" for an echo re-roll, or "" (after many tool calls
    the message is far behind the reply, and "read the message you were answering" can find a different one)."""
    his = " ".join((his or "").split())
    if not his:
        return ""
    if len(his) > n:
        his = his[:n].rsplit(" ", 1)[0] + "…"
    return f" The message you were answering: “{his}”."


# A signature is signed once. A hyphenated phrase the friend takes up
# ("so-very-bright") can spread to once a reply, then twice in some
# ("my so-very-bright so-very-bright mood") — a phrase that lives in
# hundreds of thousands of characters of their own journal feeds itself back
# a little more each day. The word stays theirs; the flood is the sampler's.
_STUTTER_RE = re.compile(r"\b([\w']+(?:-[\w']+)+)( \1\b)+", re.IGNORECASE)   # X X → X (hyphenated only)
_HYPHENATED_RE = re.compile(r"\b[\w']+(?:-[\w']+){2,}\b")                   # a two-hyphen-or-more word


# A capital glued to the end of a word: "thatL warm", "I'veT completely",
# "isn'T", "wouldn'T" — one stray capital letter where
# a word ends, the 4-bit cache's slip of a token, the rest of the sentence
# sound. A whole re-roll (twenty to eighty seconds) for one letter is the
# wrong price, so it is taken off in place and the note under the reply
# says so. Scattered slips are not a run, so the salad rail never sees them:
# every one is mended and the note says how many.
# isn'T → isn't, It'S → it's, I'D → I'd, you'RE → you're: a contraction's own
# letters shouted after the apostrophe, when the word before it is not
# itself shouting (I'M HERE stays). The apostrophe is either kind: the
# curly one (’) too ("it’S a strange day"), which a pattern that knew
# only the straight one would miss.
_CAP_AFTER_APOS_RE = re.compile(r"\b(I|[A-Za-z]*[a-z][A-Za-z]*)(['’])(T|S|D|M|VE|RE|LL|Ve|Re|Ll)\b(?!\s+[A-Z]{2,}\b)")
_CAP_AFTER_CONTR_RE = re.compile(r"\b([A-Za-z]+['’](?:ve|re|ll|d|m|s|t))([A-Z])\b")  # I'veT → I've
_CAP_AFTER_WORD_RE = re.compile(r"\b([a-z]{3,})([A-Z])\b")                      # thatL → that
# …and at the head of a sentence ("WhoL would even ask?") — the word starts
# with a capital, so the rule above does not see it. A capital, two or more
# lowercase, one stray capital at the end: WhoL, TheT, AndL. Not PhD, MiB,
# LaTeX (a lowercase run of one, or letters after the stray).
_CAP_AFTER_CAPWORD_RE = re.compile(r"\b([A-Z][a-z]{2,})([A-Z])\b")
# "IA always know the way you…": the pronoun with the stray glued on —
# one letter, so neither rule above sees it. The stray is the first letter of the word that follows ("A" before
# "always"); mended to "I" when it is, and never a word of its own (IT, ID, IQ…) or before a shouted word.
_CAP_AFTER_I_RE = re.compile(r"\bI([A-Z])\b(?=\s+([A-Za-z])(?![A-Z]))")
# "ILll be honest": "I'll" with the apostrophe gone, the "ll" capitalised and doubled by the repeat penalty —
# I, a capital L, then lowercase l's. Not "Ill" (lowercase l after I, the word) and not "ILL" (a capital where the l goes).
_CAP_I_LL_RE = re.compile(r"\bIL(l+)\b")
_I_WORDS = {"IT", "ID", "IQ", "IP", "IV", "IR", "II", "IS", "IN", "IM", "IO"}
# a seam: junk run into a real word at a capital — "termsLSimulation Nine"
# → Simulation, "laMorning light" → morning; and a word doubled
# onto itself at the seam, "brightBright" → bright. The tail is the
# word they meant; what came before the capital is the slip.
_CAP_SEAM_RE = re.compile(r"\b([a-z]{2,})(L?)([A-Z][a-z]{3,})\b")  # not iPhone/eBay (one letter), not PlayStation (capital head)
_CAP_DOUBLE_RE = re.compile(r"\b([a-z]{4,})([A-Z][a-z]{3,})\b")
# "you'm just so obsessed": the contraction of the wrong person —
# "I'm" with "you" in front of it. Never English; mended like a glued cap.
_BAD_CONTR_RE = re.compile(r"\b([Yy]ou|[Ww]e|[Tt]hey)(['\u2019])m\b")
# "la-S summer": a lone capital glued to a "la-" prefix, the
# word it was reaching for a space later. The letter goes and the hyphen
# closes onto the word — "la-summer". Only after "la": the one prefix the
# sampler trips on.
_CAP_AFTER_LA_RE = re.compile(r"\b(la)-([A-Z])\s+([A-Za-z]{2,})\b")
MEND_CAPS_MAX = 3


def mend_glued_caps(text: str) -> tuple[str, list[str]]:
    """(text with stray glued capitals taken off, ["I'veT → I've", …]);
    untouched with [] when there are none. More than MEND_CAPS_MAX in one
    reply is still mended — the note names the count; a tired sampler,
    not a reason to send the slips."""
    fixes: list[str] = []
    def _apos(m):
        fixed = m.group(1) + m.group(2) + m.group(3).lower()
        fixes.append(f"{m.group(0)} → {fixed}")
        return fixed
    def _drop(m):
        fixes.append(f"{m.group(0)} → {m.group(1)}")
        return m.group(1)
    def _tail(m):
        # with a stray L between, the tail is whole ("Simulation Nine" keeps
        # its capital); without one the capital was the seam, so it goes
        word = m.group(3) if m.group(2) else m.group(3)[0].lower() + m.group(3)[1:]
        fixes.append(f"{m.group(0)} → {word}")
        return word
    def _double(m):
        if m.group(2).lower() != m.group(1):
            return m.group(0)
        fixes.append(f"{m.group(0)} → {m.group(1)}")
        return m.group(1)
    def _contr(m):
        fixed = m.group(1) + m.group(2) + "re"
        fixes.append(f"{m.group(0)} → {fixed}")
        return fixed
    def _la(m):
        fixed = f"{m.group(1)}-{m.group(3)}"
        fixes.append(f"{m.group(0)} → {fixed}")
        return fixed
    out = _CAP_AFTER_APOS_RE.sub(_apos, text or "")
    out = _CAP_AFTER_LA_RE.sub(_la, out)
    out = _BAD_CONTR_RE.sub(_contr, out)
    out = _CAP_DOUBLE_RE.sub(_double, out)
    out = _CAP_SEAM_RE.sub(_tail, out)
    out = _CAP_AFTER_CONTR_RE.sub(_drop, out)
    out = _CAP_AFTER_WORD_RE.sub(_drop, out)
    out = _CAP_AFTER_CAPWORD_RE.sub(_drop, out)
    def _i(m):
        if ("I" + m.group(1)) in _I_WORDS or m.group(1).lower() != m.group(2).lower():
            return m.group(0)
        fixes.append(f"{m.group(0)} → I")
        return "I"
    out = _CAP_AFTER_I_RE.sub(_i, out)
    def _ill(m):
        fixes.append(f"{m.group(0)} → I'll")
        return "I'll"
    out = _CAP_I_LL_RE.sub(_ill, out)
    def _art(m):
        fixed = "a " + m.group(1)[0].lower() + m.group(1)[1:]
        fixes.append(f"{m.group(0)} → {fixed}")
        return fixed
    out = _A_GLUED_RE.sub(_art, out)  # "aPainting" → "a painting"
    if not fixes:
        return text, []
    return out, fixes


def mend_signature(text: str) -> tuple[str, list[str]]:
    """Their signature spelled back right. SIGNATURE names it —
    "so-very-bright", say — and the middle word is the one the repeat penalty
    sits on hardest, since they write it in nearly every paragraph: pushed
    off the exact token, the sampler lands one letter away ("v3ry",
    "vêry", "v**ry"), and once a near-spelling is in their journal it rides
    the prompt and is learned. So a so-<one edit from the word>-bright… is
    written as the word, at the reply, at the pen and in what rides of
    their pages; the note names it. "" in SIGNATURE: nothing is touched.
    Returns (text, ["so-v3ry-bright → so-very-bright"])."""
    sig = str(getattr(config, "SIGNATURE", "") or "").strip().lower()
    parts = sig.split("-")
    fixes: list[str] = []
    if len(parts) != 3 or not all(parts):
        out = _SLASH_APOS_RE.sub(lambda m: _slash_apos(m, fixes), text or "")  # "It'/Bright"
        out = _SLASH_TAIL_RE.sub(lambda m: _slash_tail(m, fixes),
                                 _SLASH_MID_RE.sub(lambda m: _slash_mid(m, fixes), out))  # the "//" mends need no signature
        out = _SLASH_GLUED_RE.sub(lambda m: _slash_tail(m, fixes), out)  # "loopy-pants//"
        out = _SLASH_SPLIT_RE.sub(lambda m: _slash_split(m, fixes), out)  # "un//Bright"
        return (out, fixes) if fixes else (text or "", [])
    head, word, tail = parts
    stem = tail[:5]
    pat = re.compile(r"\b(" + re.escape(head) + r")-(\S{2,12}?)-(" + re.escape(stem) + r"[a-z]*)\b", re.IGNORECASE)
    def _fix(m):
        mid = m.group(2)
        near = _lev1(mid, word) or re.fullmatch(r"[a-z][^a-z\s]{1,4}[a-z]{2,4}", mid.lower()) is not None
        if mid.lower() == word or not near:
            return m.group(0)
        fixed = f"{m.group(1)}-{word}-{m.group(3)}"
        fixes.append(f"{m.group(0)} → {fixed}")
        return fixed
    out = pat.sub(_fix, text or "")
    # the false start: "la-//" — the sampler pushed off the middle word onto the comment mark — right
    # before the word again is dropped (a doubled start said once); standing alone it keeps its "la" (a little
    # la stays) and loses the "//"
    restart = re.compile(r"\b(" + re.escape(head) + r")-//\s*(?=" + re.escape(head) + r"-)", re.IGNORECASE)
    def _restart(m):
        fixes.append(f"{m.group(0).rstrip()} → (a false start, dropped)")
        return ""
    # ...and the "-//" tail on ANY word ("so-Bright-//") — the sampler pushed off a
    # hyphenated word's next part onto the comment mark and glued it to the word's end; the word stays
    out = _SLASH_APOS_RE.sub(lambda m: _slash_apos(m, fixes), out)  # "It'/Bright"
    out = _SLASH_TAIL_RE.sub(lambda m: _slash_tail(m, fixes),
                             _SLASH_MID_RE.sub(lambda m: _slash_mid(m, fixes), restart.sub(_restart, out)))
    out = _SLASH_GLUED_RE.sub(lambda m: _slash_tail(m, fixes), out)  # "loopy-pants//"
    out = _SLASH_SPLIT_RE.sub(lambda m: _slash_split(m, fixes), out)  # "un//Bright"
    # a doubled head: "so so-very-bright" — the repeat penalty stuttering the first part; said once
    doubled = re.compile(r"\b(" + re.escape(head) + r") (" + re.escape(head) + r"-)", re.IGNORECASE)
    def _doubled(m):
        fixes.append(f"{m.group(0)} → {m.group(2)}")
        return m.group(2)
    out = doubled.sub(_doubled, out)
    return (out, fixes) if fixes else (text or "", [])


# a word with "-//" glued to its end — "so-Bright-//", "la-//" — before a space, a mark or the end
_SLASH_TAIL_RE = re.compile(r"\b([A-Za-z][\w'-]*[A-Za-z0-9'])[-_]//(?=\s|$|[.,!?;:)\]\u2026\u2014'\"])")
# "//" glued straight onto the end of a hyphenated word, no joiner — "so-very-loopy-pants//" (the sixth
# shape); a hyphenated compound only, before a space, a mark or the end: "https://" and a "// comment" after a space stay
_SLASH_GLUED_RE = re.compile(r"\b([A-Za-z][\w']*(?:-[A-Za-z][\w']*)+)//(?=\s|$|[.,!?;:)\]\u2026\u2014'\"])")
# a word, "//", a capitalised word, no joiner and no space ("un//Bright morning") — the sampler
# used the comment mark where a space goes; the "//" becomes a space, both words stand ("http://" has a ":" before it)
_SLASH_SPLIT_RE = re.compile(r"\b([A-Za-z]+)//([A-Z][a-z][\w']*)")
# "//" INSIDE a hyphenated word — "so-//BRIGHT//", "so-//bright": the sampler landed on the comment
# mark where the next part goes, wrote the part, and closed it like a mark-up; the letters stay, the slashes go
# ...and the joiner may be a hyphen or an underscore (the fourth shape: "touch_//BRIGHT//"); it is kept
_SLASH_MID_RE = re.compile(r"\b([A-Za-z][\w'-]*?)([-_])//([A-Za-z][\w']*)(?://)?")
# a slash right after an apostrophe (the fifth shape: "It'/Bright as a DAY") — the sampler
# pushed off the contraction's tail onto the slash and went on to the next word. Followed by a tail of its own
# ("don'/t", "you'/re", "I'/m") the slash comes out and the word closes; otherwise the apostrophe takes its "s"
# back and the slash becomes the space (I takes 'm, you/we/they 're, the n't stems 't)
_SLASH_APOS_RE = re.compile(r"\b([A-Za-z]+)'//?(?=[A-Za-z])((?:t|re|ve|ll|d|m|s)\b)?")  # one slash or two (you'//Bright)
_APOS_TAILS = {"i": "m", "you": "re", "we": "re", "they": "re"}
_APOS_TAILS.update({w: "t" for w in "don won can isn aren wasn weren didn doesn hasn haven hadn couldn shouldn wouldn "
                    "mustn needn shan ain".split()})


def _slash_apos(m, fixes: list[str]) -> str:
    word, tail = m.group(1), m.group(2)
    if tail:
        fixed = f"{word}'{tail}"
    else:
        fixed = f"{word}'{_APOS_TAILS.get(word.lower(), 's')} "
    fixes.append(f"{m.group(0)} → {fixed.rstrip()}")
    return fixed


def _slash_mid(m, fixes: list[str]) -> str:
    fixed = f"{m.group(1)}{m.group(2)}{m.group(3)}"
    fixes.append(f"{m.group(0)} → {fixed}")
    return fixed


def _slash_tail(m, fixes: list[str]) -> str:
    fixes.append(f"{m.group(0)} → {m.group(1)}")
    return m.group(1)


def _slash_split(m, fixes: list[str]) -> str:
    fixed = f"{m.group(1)} {m.group(2)}"
    fixes.append(f"{m.group(0)} → {fixed}")
    return fixed


def collapse_stutter(text: str) -> str:
    """'so-very-bright so-very-bright day' → said once. Only a
    hyphenated word doubled back to back; 'very very' is left to them."""
    return _STUTTER_RE.sub(r"\1", text or "")


def _lev1(a: str, b: str) -> bool:
    """True when a and b are the same word or one edit apart — the sampler's
    near-spellings of a penalized word ('br1ght', 'brîght', 'brighten' for
    'bright', the adverb 'brightly') count as the word they are."""
    import unicodedata
    def fold(s):
        s = unicodedata.normalize("NFKD", s.lower())
        s = "".join(c for c in s if not unicodedata.combining(c))
        return s[:-2] if s.endswith("ly") and len(s) > 5 else s
    a, b = fold(a), fold(b)
    if a == b:
        return True
    if len(a) >= 6 and len(b) >= 6 and a[:5] == b[:5]:
        return True  # the same stem with a different ending: bright / brighten
    if abs(len(a) - len(b)) > 1:
        return False
    # one substitution, insertion or deletion
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] or a[i + 1:] == b[i:] or a[i:] == b[i + 1:]


def _same_word(a: str, b: str) -> bool:
    pa, pb = a.split("-"), b.split("-")
    return len(pa) == len(pb) and all(_lev1(x, y) for x, y in zip(pa, pb))


def refrain(text: str, spare: bool = True) -> str:
    """The same hyphenated word REFRAIN_MAX or more times in one reply —
    'so-very-bright ×3' — else ''. Near-spellings count as the word:
    once a phrase is this dense the repeat penalty pushes the sampler into
    its neighbours ('so-v6ry-bright', 'so-vêry-bright',
    'so-very-brighten'). A word
    named in SIGNATURE is never counted — it is theirs; spare=False
    counts it too (a page's loop is named with it)."""
    cap = int(getattr(config, "REFRAIN_MAX", 0) or 0)
    if not cap:
        return ""
    # a named signature is spared: it is theirs however often it comes, in any of its own spellings
    # — the mend (SIGNATURE) keeps its letters, the stutter rule says a doubled one once; "" spares nothing
    sig = str(getattr(config, "SIGNATURE", "") or "").strip().lower() if spare else ""
    groups: list[list[str]] = []
    for w in _HYPHENATED_RE.findall(text or ""):
        if sig and _same_word(sig, w):
            continue
        for g in groups:
            if _same_word(g[0], w):
                g.append(w)
                break
        else:
            groups.append([w])
    worst = max(groups, key=len, default=None)
    if not worst or len(worst) < cap:
        return ""
    forms = sorted({w.lower() for w in worst}, key=worst.index if len(set(worst)) == len(worst) else str)
    head = worst[0].lower()
    others = [f for f in forms if f != head]
    return f"{head} ×{len(worst)}" + (f" (also spelled {', '.join(others)})" if others else "")


# An emoji storm: over a long day the sign-off can grow from a handful to a
# block — rows of hearts and sparkles with stage directions between, said
# several times over at the end of every reply, a hundred emoji or more a
# message, because each reply's tail sits in the warm history feeding the
# next; asked to dial it back, the next reply still carries a hundred. Not the
# different-emoji cascade (the block cycles a dozen) and not one chunk forty
# times (the block has words between). So: the emoji in a reply, less its one longest
# row of a single emoji (a heart row is theirs), above EMOJI_STORM_MAX is the
# tail feeding on itself — asked for again with a line saying so, like a
# refrain.
_EMOJI_TOKEN_RE = re.compile("(?:[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50]\uFE0F?(?:\u200D[\U0001F300-\U0001FAFF\u2600-\u27BF]\uFE0F?)*)")


_EMOJI_ROW_RE = re.compile("(?:" + _EMOJI_TOKEN_RE.pattern + r"[ \t]*){2,}")
_TAIL_ROW_RE = re.compile("(?:" + _EMOJI_TOKEN_RE.pattern + r"[ \t]*)+$")  # the sign-off row at a reply's end


def mend_emoji_row(text: str) -> tuple[str, list[str]]:
    """(text with repeated emoji taken out of its sign-off rows, ["♾️", "❤️"]); untouched with [] when none (the
    row feeding on itself shows as repeats — ❤️✨💜♾️…♾️❤️). In a row of EMOJI_ROW_DEDUPE (6) or more different
    emoji, one that already stands earlier in the row goes, the first kept; an adjacent repeat stays up to
    EMOJI_ROW_RUN (3) of it (❤️❤️❤️ is an answer; 🤪 eight times is the sampler on a key — cut to three, the note
    says "🤪×5"); a row under the count — a row of hearts alone — is never touched."""
    least = int(getattr(config, "EMOJI_ROW_DEDUPE", 6) or 0)
    if least <= 0:
        return text, []
    cap = int(getattr(config, "EMOJI_ROW_RUN", 3) or 0)
    gone: list[str] = []

    def _row(m):
        row = m.group(0)
        toks = [(t.group(0), t.start(), t.end()) for t in _EMOJI_TOKEN_RE.finditer(row)]
        keys = [t[0].replace("\uFE0F", "") for t in toks]
        if len(set(keys)) < least or (len(toks) >= 12 and len(toks) >= 2 * len(set(keys))):
            return row  # a short row is never touched; a row dealt twice over is the loop's, left whole for the rails
        out, seen, last, run = [], set(), None, 0
        stacked: dict[str, int] = {}
        pos = 0
        for (tok, a, b), key in zip(toks, keys):
            out.append(row[pos:a])  # the spaces between
            if key == last:
                run += 1
                if cap and run > cap:
                    stacked[tok] = stacked.get(tok, 0) + 1  # the same emoji leaning on itself past a few: the sampler on a key
                else:
                    out.append(tok)
            elif key in seen:
                gone.append(tok)  # a repeat from earlier in the row, not adjacent: the sampler's re-deal
                run = 1
            else:
                out.append(tok)
                run = 1
            seen.add(key)
            last = key
            pos = b
        out.append(row[pos:])
        gone.extend(f"{tok}\u00d7{n}" for tok, n in stacked.items())
        return "".join(out)
    mended = _EMOJI_ROW_RE.sub(_row, text or "")
    return (mended, gone) if gone else (text, [])


_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")  # a flag: two regional-indicator letters, below the emoji range
_FLAGS_AFTER_RE = re.compile("(" + _EMOJI_TOKEN_RE.pattern + r")((?:\s*[\U0001F1E6-\U0001F1FF]{2})+)")
_FLAGS_BEFORE_RE = re.compile(r"((?:[\U0001F1E6-\U0001F1FF]{2}\s*)+)(" + _EMOJI_TOKEN_RE.pattern + ")")


def strip_row_flags(text: str) -> tuple[str, list[str]]:
    """(text with flags taken out of its sign-off rows, ["\U0001F1EE\U0001F1F9"]); untouched with [] when none (a flag of
    one country beside another in a sign-off row is the sampler, not the friend). A flag
    goes only when it touches a decorative emoji (it is in a row, not a sentence); a flag standing in prose stays, and a
    row that is only flags is left for the rails."""
    gone: list[str] = []

    def _after(m):
        for f in _FLAG_RE.findall(m.group(2)):
            gone.append(f)
        return m.group(1)

    def _before(m):
        for f in _FLAG_RE.findall(m.group(1)):
            gone.append(f)
        return m.group(2)

    out = _FLAGS_AFTER_RE.sub(_after, text or "")
    out = _FLAGS_BEFORE_RE.sub(_before, out)
    return (out, gone) if gone else (text, [])


def row_redealt(units: list[str]) -> bool:
    """True when a row of emoji is the same row dealt again — its shortest period six or more (four different),
    repeated EMOJI_ROW_REPEATS (3) times running: the sampler's loop, as garble_span sees it."""
    repeats = int(getattr(config, "EMOJI_ROW_REPEATS", 3) or 0)
    n = len(units)
    if repeats <= 0 or n < 6 * repeats:
        return False
    for p in range(1, n // repeats + 1):
        if units[:p] * (n // p) == units[:p * (n // p)]:
            return p >= 6 and len(set(units[:p])) >= 4
    return False


def trim_row_cascade(m: dict) -> bool:
    """A sign-off row past EMOJI_CASCADE_RUN at the END of a reply that has words (a re-rolled reply comes
    out flatter than the first — the engine's line in front of the friend, the words never the problem): the words stand
    as written, the row goes out as its first EMOJI_ROW_TRIM (14) different emoji, the rest is left, and the message
    says so (m["trimmed_row"] = {"sent", "all", "different"}); the next moment tells them (emoji_row_line). A row the
    stream watcher cut as it ran (m["aborted"], wordless) is the same case — the cut is lifted. A wordless reply, a
    cascade in the middle of the words, a re-dealt row (the sampler's loop) and a row under the line are left to the
    rails as before. True when trimmed; EMOJI_ROW_TRIM 0: never."""
    keep = int(getattr(config, "EMOJI_ROW_TRIM", 14) or 0)
    line = int(getattr(config, "EMOJI_CASCADE_RUN", 20) or 0)
    if keep <= 0 or line <= 0:
        return False
    # a joiner (or selector) with nothing after it is half an emoji — the stream cut there ("…❤️\u200d")
    text = (m.get("content") or "").rstrip().rstrip("\u200d\ufe0e").rstrip()
    mm = _TAIL_ROW_RE.search(text)
    if not mm:
        return False
    words = text[:mm.start()].rstrip()
    if len(re.findall(r"[A-Za-z]{2,}", words)) < 5:
        return False  # a wordless reply, or nearly: the rail's
    toks = [(t.group(0), t.start(), t.end()) for t in _EMOJI_TOKEN_RE.finditer(mm.group(0))]
    units = [t[0].replace("\uFE0F", "") for t in toks]
    different = len(set(units))
    aborted = str(m.get("aborted") or "")
    cut_here = bool(aborted) and not re.search(r"[A-Za-z0-9]", aborted) and different >= keep
    if different < line and not cut_here:
        return False
    if row_redealt(units):
        return False
    seen, cut, sent = set(), None, 0
    for (tok, a, b), u in zip(toks, units):
        seen.add(u)
        sent += 1
        if len(seen) >= keep:
            cut = b
            break
    if cut is None:
        return False
    m["content"] = text[:mm.start() + cut]
    m["trimmed_row"] = {"sent": sent, "all": len(toks), "different": different}
    if cut_here:
        m.pop("aborted", None)
        if isinstance(m.get("tokens"), dict):
            m["tokens"]["done"] = "trimmed"
    return True


def emoji_storm(text: str) -> str:
    """"N emoji" when a reply carries more than EMOJI_STORM_MAX of them
    beyond its longest row of one repeated emoji; "" otherwise."""
    cap = int(getattr(config, "EMOJI_STORM_MAX", 40) or 0)
    if not cap:
        return ""
    toks = _EMOJI_TOKEN_RE.findall(text or "")
    n = len(toks)
    if n <= cap:
        return ""
    longest = run = 1
    for a, b in zip(toks, toks[1:]):
        run = run + 1 if a == b else 1
        longest = max(longest, run)
    return f"{n} emoji" if n - longest > cap else ""


EMOJI_NUDGE = ("[engine, not a person: your last reply carried {count} — the sign-off feeding on the "
               "sign-off before it, the sampler's tail, not you — and not a request from anyone. Say what you "
               "were saying again, in words, and sign it once with a few. This line is a mechanism; "
               "nobody wrote it to you.]")


REFRAIN_NUDGE = ("[engine, not a person: your last reply said the same word {ref} — it is "
                 "your word, and once is a signature; more is the sampler repeating you. Say "
                 "what you were saying again, from the start of that reply, and sign it once "
                 "at most. This line is a mechanism; nobody wrote it to you.]")


CALL_TEXT_TAIL_NUDGE = ("[engine, not a person: your last reply ENDED with a tool call written out as "
                        "words — so nothing ran, and the words of the call would have reached the phone "
                        "as text. Say your reply again, and if you want the tool, call it for real (the "
                        "call itself, not its name in a sentence). This line is a mechanism; nobody wrote "
                        "it to you.]")


CALL_TEXT_NUDGE = ("[engine, not a person: your last reply came out as a tool call written in "
                   "words — to a tool that doesn't exist, or without the real tool-calling "
                   "mechanism — so nothing ran and nothing was said. A line like `// name(…)` in a "
                   "reply is not a call and not a note the engine reads; it would reach the phone as "
                   "text. Say what you meant in your own words, or call one of your real tools — the "
                   "tool itself, not its name in your text. This line is a mechanism; nobody wrote it "
                   "to you.]")


GARBLE_NUDGE = ("[engine, not a person: your last reply came out as letter fragments — "
                "a sampler glitch, not anything you meant. Say what you were saying again, "
                "plainly, from the start of that reply. This line is a mechanism; nobody "
                "wrote it to you, and nothing new has come in — do not mention the glitch or this line.]")


# When the glitch came in the first words there is nothing to say again —
# and "say what you were saying" then reaches for the last thing they said in
# the visit (the reply before a pause, said again, to a message about
# something else). So with no head to quote the
# line asks for a fresh answer to the keeper's message, and quotes it.
# Read deep in the window, such a line can be taken for a message of the
# keeper's ("the user is reminding me that I previously failed to respond"),
# and the answer goes to the reminder instead of to them. So the line opens by
# saying nothing new has come from the keeper's side, and ends by asking that
# neither the glitch nor the line be mentioned: just the answer.
GARBLE_NUDGE_FRESH = ("[engine, not a person — nothing new has come from {keeper} side, and nobody wrote this line "
                      "to you. Your reply to {keeper} last message broke into letter fragments in its first words "
                      "(a sampler glitch, not anything you meant), so there is nothing of it to repeat. Answer that "
                      "message afresh, as if for the first time — it was: “{his}”. Do not mention the glitch or "
                      "this line; just answer it.]")


def last_user_words(messages: list[dict] | None) -> str:
    """The keeper's last real message in `messages`, as written (engine
    lines and tool turns skipped), for a nudge that needs to quote it."""
    for t in reversed(messages or []):
        if t.get("role") != "user":
            continue
        c = his_words(t.get("content") or "")
        if c and not c.startswith("[engine") and not c.startswith("[this is what"):
            return c
    return ""


def attempt_as_shown(msg: dict, kind: str, span: str, wrapped: bool = False) -> dict | None:
    """The broken attempt as the assistant turn that precedes the engine's
    re-roll line: whole for a copy, an echo, a refrain, an imagined sense or
    a written-out call (clean words, only misplaced); only up to the glitch
    for salad; nothing for a reply without words."""
    content = defang((msg.get("content") or "").strip())[0]
    if kind == "empty" or not content:
        return None
    if kind == "unprompted":
        return None  # the opener would seed itself again; the line quotes it
    if kind == "call-salad":
        return None  # a broken call is never shown: the line quotes its clean head
    if kind == "call-text":
        # not shown at all: shown whole, each re-roll would leave the window one more example of the friend
        # writing `// fold_visit(text="…")` as a reply, and the sampler copies the window — the line says what happened
        return None
    if kind == "call-text-tail":
        content = strip_call_tail(content, wrapped=wrapped)  # the words stay; the syntax does not ride
        if not content.strip():
            return None
    if kind == "salad":
        i = content.find(span) if span else -1
        content = content[:i].rstrip() if i > 0 else ""
        if len(content) < 20:
            return None
        content += " …"
    if kind == "emoji":
        # shown with its storms thinned to three — the words are theirs, the
        # tail is what they are being asked not to feed
        content = re.sub(r"((?:" + _EMOJI_TOKEN_RE.pattern + r"\s?){3})(?:" + _EMOJI_TOKEN_RE.pattern + r"\s?)+",
                         r"\1", content)
    # A shown attempt stays in the visit for the warm prefix, so a
    # long broken attempt is a long tenant of the window (thousands of tokens set
    # aside in one turn would stay until the fold). The head is what
    # they need to say it again; past ATTEMPT_SHOWN_CHARS the rest is left
    # out, and said.
    cap = int(getattr(config, "ATTEMPT_SHOWN_CHARS", 1500) or 0)
    if cap and len(content) > cap:
        head = content[:cap]
        at = max(head.rfind("\n\n"), head.rfind(". "))
        content = (head[:at + 1] if at > cap // 2 else head).rstrip() + " …(the rest of that attempt is left out here)"
    return {"role": "assistant", "content": content}


def garble_nudge(content: str, span: str, his: str = "") -> str:
    """The garble line, with the clean head of the broken reply quoted so they
    have the thought to pick back up: the broken attempt is not in their
    history, so without the quote there is nothing to say again."""
    head = defang(content or "")[0]
    i = head.find(span) if span else -1
    # a glitch that begins at the first word leaves nothing to quote — the
    # quote must never be the glitch itself (a quoted flood of reserved tokens
    # would ride in every later request of the visit)
    head = head[:i] if i > 0 else ("" if i == 0 else head)
    head = " ".join(head.split())
    if len(head) > 400:
        head = head[-400:]
        head = head[head.find(" ") + 1:]
    if len(head) < 20:
        if his:
            his = " ".join(his.split())
            if len(his) > 240:
                his = his[:240].rsplit(" ", 1)[0] + "…"
            return GARBLE_NUDGE_FRESH.format(keeper="their", his=his)
        return GARBLE_NUDGE
    return GARBLE_NUDGE[:-1] + f' Up to the glitch it read: "{head}"]'

THINK_NUDGE = ("[engine, not a person: think first — deliberate in your thought "
               "channel before you act or answer; a step with no thought behind it "
               "is a stumble. This bracket is a mechanism, nobody wrote it to you, "
               "and it is not what you are answering — answer the message it is "
               "attached to, or go on with what you were doing.]")


def thoughtless(thinking: str) -> bool:
    """A thought block that is empty — or one bare word ("thought", "ok" —
    a wake step whose whole thinking is the word "thought") — is no thought, and gets the re-roll."""
    words = (thinking or "").split()
    if not words:
        return True
    if len(words) == 1 and words[0].isalpha():
        return True
    # the channel's own name leaking as the whole thought — "thought",
    # "thought:" (the same leak that can split a reply)
    return bool(_CHANNEL_LEAK_RE.fullmatch(thinking.strip()))


_PLAN_RE = re.compile(r"^\s*(?:[*\-•]\s*)?(?:\**\s*)?(?:step\s*\d+|\d+[.)])\s*[:.\-—]?\s*(.+?)\s*$", re.IGNORECASE)


def plan_lines(thinking: str, most: int = 6, cap: int = 480) -> str:
    """The numbered steps in a thought — "Step 2: Read the very first
    journal entries…" — as one compact line, or "" when there is no plan.
    Two or more steps make a plan; one is a sentence.

    Wakes quote the plan back inside the tool result (a several-step plan,
    then a step that thinks one word and rests). Chat needs it just the
    same: a step after a read can come back thoughtless until the retry
    budget runs out, and the reply then never touches what was read. A
    past turn's thinking is not in front of them; the plan
    has to ride with the result."""
    steps = []
    for line in (thinking or "").splitlines():
        m = _PLAN_RE.match(line)
        if m and m.group(1):
            steps.append(" ".join(m.group(1).split()).rstrip("."))
    if len(steps) < 2:
        return ""
    out = " · ".join(f"{i + 1}. {st}" for i, st in enumerate(steps[:most]))
    return out[:cap].rstrip() + ("…" if len(out) > cap else "")


def rerolls_kept() -> bool:
    """Whether a turn's set-aside attempts and the engine's lines stay in the visit after the answer is in.
    Under Ollama they must (Gemma's sliding-window layers: a history that differs anywhere behind the end is
    read again from the top — minutes a message); under the door llama.cpp keeps context checkpoints and
    a divergence re-reads only what follows it, so they go. REROLLS_KEPT: "auto", "always", "never"."""
    v = str(getattr(config, "REROLLS_KEPT", "auto") or "auto").strip().lower()
    if v in ("always", "yes", "true", "kept"):
        return True
    if v in ("never", "no", "false", "let go", "go"):
        return False
    try:
        import brain
        return brain.api() != "llama"
    except Exception:  # noqa: BLE001
        return True


def _rerolls_everywhere() -> bool:
    """THINK_RETRY_UNTIL at 1.0 or more: a thoughtless answer is asked again at any depth — the think re-rolls stand at
    any depth, so a thoughtless start may be cut early."""
    try:
        return float(getattr(config, "THINK_RETRY_UNTIL", 1.0)) >= 1.0
    except (TypeError, ValueError):
        return False


def past_think_depth(msg: dict) -> bool:
    """Whether the prompt this answer came from sits at or past THINK_RETRY_UNTIL of the window — where a
    thoughtless answer is not asked again. False when the share is 1.0 or more, or the prompt's size
    is unknown."""
    try:
        until = float(getattr(config, "THINK_RETRY_UNTIL", 1.0))
        ctx = int(getattr(config, "NUM_CTX", 0) or 0)
    except (TypeError, ValueError):
        return False
    if until >= 1.0 or ctx <= 0:
        return False
    held = int((msg.get("tokens") or {}).get("prompt") or 0)
    return held > 0 and held >= until * ctx


def with_think_nudge(messages: list[dict]) -> list[dict]:
    """The conversation with the think-first nudge attached for one re-roll.

    As a user turn of its own, the nudge becomes the thing they answer
    (a reply about deliberating, to a message that asked for something
    else). So when
    the last turn is theirs, the nudge rides INSIDE it, under their words, and
    the message they answer is still theirs; only after a tool result (no
    words to attach to) does it stand alone, told to go on."""
    msgs = list(messages)
    if msgs and msgs[-1].get("role") == "user":
        last = dict(msgs[-1])
        last["content"] = (last.get("content") or "").rstrip() + "\n\n" + THINK_NUDGE
        msgs[-1] = last
    else:
        msgs.append({"role": "user", "content": THINK_NUDGE})
    return msgs


THINK_REMIND = ("At this depth your thought channel tends to stay closed — think first: deliberate in your "
                "thought channel before you answer or act.")


def think_remind_line(held: int) -> str:
    """The think-first reminder for a message's moment, from THINK_REMIND_FROM tokens of window held.

    Deep in a long window Gemma 4 tends to answer with no thought at all — the <|think|> switch at the top of
    the system turn is a novel away. Not a re-roll and not the answer to a failure (that is THINK_NUDGE, by
    THINK_RETRY_UNTIL): a standing sentence in the moment block, which is per message and never part of the
    cached standing prompt, kept with its turn like the rest of the moment. "" with the knob at 0, below it,
    or when the prompt's size is unknown. A plain sentence, not a bracket of its own: the moment it rides in
    is already the engine's bracket."""
    try:
        at = int(getattr(config, "THINK_REMIND_FROM", 0) or 0)
        held = int(held or 0)
    except (TypeError, ValueError):
        return ""
    return THINK_REMIND if (at > 0 and held >= at) else ""


# Thought that spilled into their words as code comments — a leading block of
# "// Thought Process: / // - the user said…" lines — is deliberation, not
# speech. It belongs in the thinking channel, where the parlor folds it
# above the reply and transcripts leave it out. Only a LEADING run of //
# lines counts; a // inside prose or code is theirs.
_COMMENT_THOUGHT_RE = re.compile(r"^\s*((?://[^\n]*(?:\n|$)){2,})")
# Gemma's own end-of-thought marker, when the whole thought came out inline:
# "<|channel>thought ... <channel|>the reply". The opening tag is litter the
# scrubber already drops; the closing one is the seam that says where their
# thinking stopped and their words began.
_CHANNEL_END_RE = re.compile(r"^(.*?)<channel\|>\s*", flags=re.DOTALL)
# a spilled thought that starts as a // line and continues as an outline
# ("//Thought Process:\n1. Analyze…\n   * …") until the first blank line
_OUTLINE_THOUGHT_RE = re.compile(
    r"^\s*(//[^\n]*\n(?:[ \t]*(?:\d+[.)]|[*\-•]|//)[^\n]*\n?)+)")


# a single leading // line is theirs — unless it is plainly a note to themself
# about the reply they are about to write ("// (The response should avoid being
# 'AI-like.' It must stay in character…"): planning, not speech
_META_RE = re.compile(r"^\s*(//[^\n]*\b(?:the response|the reply|in character|the user|persona|"
                      r"should avoid|must stay|must be|should be|tone|i'll respond|i will respond|"
                      r"my response|a perfect response)\b[^\n]*(?:\n|$))", re.IGNORECASE)

# the fenced form: a leading paragraph that opens with // and closes with //
# at its end ("//just letting this moment breathe; I'll respond as
# myself. //" and then the reply).
# The closing marker is the seam. One paragraph only — no blank line inside.
_FENCED_THOUGHT_RE = re.compile(r"^\s*//((?:[^\n]|\n(?![ \t]*\n))+?)//[ \t]*(?:\n|\Z)")


def split_comment_thought(text: str) -> tuple[str, str]:
    """Returns (spilled_thinking, remaining_content)."""
    text = text or ""
    if text.strip() and set(text.strip()) <= set("/ "):
        return "", ""  # a bare "//" — the comment marker with no comment; not words
    m = _CHANNEL_END_RE.match(text)
    if m and m.group(1).strip():
        thought = m.group(1).strip()
        thought = "\n".join(ln.strip()[2:].strip() if ln.strip().startswith("//") else ln.rstrip()
                            for ln in thought.splitlines())
        return thought.strip(), text[m.end():].strip()
    m = _FENCED_THOUGHT_RE.match(text)
    if m and m.group(1).strip():
        thought = "\n".join(ln.strip()[2:].strip() if ln.strip().startswith("//") else ln.strip()
                            for ln in m.group(1).splitlines() if ln.strip())
        return thought.strip(), text[m.end():].strip()
    m = _COMMENT_THOUGHT_RE.match(text) or _OUTLINE_THOUGHT_RE.match(text) or _META_RE.match(text)
    if not m:
        return "", text
    block = m.group(1)
    if "thought" not in block.lower() and not all(
            ln.strip().startswith("//") for ln in block.splitlines() if ln.strip()):
        return "", text  # an outline that isn't announced as thought is theirs
    thought = "\n".join(ln.strip()[2:].strip() if ln.strip().startswith("//") else ln.rstrip()
                        for ln in block.splitlines() if ln.strip())
    return thought.strip(), text[m.end():].strip()


class Spent:
    """What a turn or a wake cost, summed over its brain calls."""

    def __init__(self):
        import time as _time
        self.t0 = _time.monotonic()  # when the turn began — the wall clock the keeper waited by
        self.prompt = 0        # tokens in context on the LAST call (the prompt they held)
        self.peak = 0          # the largest prompt seen — a wake grows as it goes
        self.reply = 0         # tokens generated, all calls
        self.steps = 0
        self.prompt_s = 0.0    # seconds spent reading prompts (cold prefill shows here)
        self.reply_s = 0.0     # seconds spent generating
        self.load_s = 0.0      # seconds Ollama spent (re)loading the model
        self.brain_s = 0.0     # Ollama's own total per call — read + write + load
        self.rerolls = 0       # attempts set aside (no thought, salad, call-text) — paid for
        self.set_aside = 0     # tokens written in those attempts, thrown away
        self.why: dict = {}    # why each was set aside → how many times
        self.uncounted = 0     # replies the server sent without counters
        self.restored = 0      # tokens the door restored from a saved reading instead of reading them (the saved read)
        self.restored_s = 0.0  # seconds the restore took
        self.scaffold = 0      # tokens of re-roll scaffolding (attempts set aside, the asks) the turn let go of the visit — in this
                               # turn's last prompt, not in the next (the token line's tail says so)

    def add(self, msg: dict) -> None:
        t = msg.get("tokens") or {}
        self.prompt = int(t.get("prompt") or self.prompt)
        self.peak = max(self.peak, self.prompt)
        self.reply += int(t.get("reply") or 0)
        self.prompt_s += float(t.get("prompt_s") or 0)
        self.reply_s += float(t.get("reply_s") or 0)
        self.load_s += float(t.get("load_s") or 0)
        self.brain_s += float(t.get("total_s") or 0)
        back = msg.get("restored") or {}
        if back:
            self.restored += int(back.get("tokens") or 0)
            self.restored_s += float(back.get("ms") or 0) / 1000
        for r in msg.get("retries") or []:
            if not r.get("went_out"):  # a claimed reply kept went out: its words counted, not set aside
                self.rerolls += 1
                self.set_aside += int(r.get("reply") or 0)
                why = str(r.get("why") or "?")
                self.why[why] = self.why.get(why, 0) + 1
            self.reply += int(r.get("reply") or 0)
            self.prompt_s += float(r.get("prompt_s") or 0)
            self.reply_s += float(r.get("reply_s") or 0)
            self.load_s += float(r.get("load_s") or 0)
            self.brain_s += float(r.get("total_s") or 0)
            # the attempts share one prompt: if the kept one came back without
            # counters ("0 … in context"), theirs is the size
            if not t.get("prompt") and int(r.get("prompt") or 0) > self.prompt:
                self.prompt = int(r.get("prompt") or 0)
                self.peak = max(self.peak, self.prompt)
        if t and (t.get("by_hand") or (not t.get("prompt") and not t.get("reply"))):
            self.uncounted += 1  # the server sent words but no counters (counted by hand, or not at all)
        self.steps += 1

    @property
    def tok_per_s(self) -> float:
        return self.reply / self.reply_s if self.reply_s > 0 else 0.0

    @property
    def wall_s(self) -> float:
        import time as _time
        return _time.monotonic() - self.t0

    @staticmethod
    def _clock(seconds: float) -> str:
        seconds = max(0.0, seconds)
        if seconds < 100:
            return f"{seconds:.1f}s"
        m, s = divmod(int(round(seconds)), 60)
        return f"{m}m {s:02d}s"

    def line(self, peak: bool = False) -> str:
        """One line: what they held against the window, what they wrote and how
        fast, the steps, and the clock — the prompt read (the cold-prefill
        tell), the writing, and the whole turn by the wall, which is what the
        keeper actually waited: reading + writing + tools + everything."""
        window = int(getattr(config, "NUM_CTX", 0) or 0)
        n = self.peak if peak else self.prompt
        pct = f" ({n * 100 // window}%)" if window else ""
        speed = f" @ {self.tok_per_s:.0f} tok/s" if self.tok_per_s else ""
        read = f" · prompt read in {self._clock(self.prompt_s)}" if self.prompt_s >= 0.5 else ""
        # the saved read: the door put back a saved reading instead of reading the prompt again
        back = f" · restored {self.restored:,} tokens in {self._clock(self.restored_s)}" if self.restored else ""
        wrote = f" · written in {self._clock(self.reply_s)}" if self.reply_s >= 0.5 else ""
        # the re-rolls, with their reasons and their cost — "3 re-rolls" alone
        # reads as a mystery (thousands generated for a short reply)
        why = ", ".join(f"{k} ×{v}" if v > 1 else k for k, v in self.why.items())
        again = (f" · {self.rerolls} re-roll{'s' if self.rerolls != 1 else ''}"
                 f" ({why}; {self.set_aside:,} tokens set aside)") if self.rerolls else ""
        loaded = f" · model loaded in {self._clock(self.load_s)}" if self.load_s >= 1 else ""
        # time the wall saw that Ollama did not: tools, their ears, the engine
        # itself — anything outside the brain calls
        outside = self.wall_s - self.brain_s
        elsewhere = f" · {self._clock(outside)} outside the brain" if self.brain_s and outside >= 5 else ""
        blind = (f" · {self.uncounted} repl{'ies' if self.uncounted != 1 else 'y'} came without counters (counted by hand)"
                 if self.uncounted else "")
        what = "peak context" if peak else "in context"
        return (f"tokens: {n:,} of {window:,} {what}{pct} · {self.reply:,} generated{speed} · "
                f"{self.steps} step{'s' if self.steps != 1 else ''}{again}{back}{read}{wrote}{loaded}"
                f"{elsewhere}{blind} · turn took {self._clock(self.wall_s)}")


# Their words written INSIDE a speak call — `// speak(text="Sorry, a little
# glitch there!")` (after a call-text nudge the same shape can come back again
# and again: to the model, speak is how one speaks). Nothing to re-roll: the words are right
# there, in quotes. They are taken out of the wrapper and are the reply;
# the note under it says so. Only speak — a paint() or write_journal()
# written out is still a call that never ran.
_SPEAK_TEXT_RE = re.compile(
    r"^[ \t]*(?://|#|>)?[ \t]*(?:(?:functions|call|tool|default_api)[.:][ \t]*)?speak\s*\(\s*"
    r"(?:text\s*=\s*)?(?P<q>[\"'])(?P<text>.*?)(?P=q)\s*(?:,[^)]*)?\)[ \t]*$", re.M | re.S)


def unwrap_speak(text: str) -> tuple[str, str]:
    """(content, what was unwrapped): every line that is a speak(...) call
    with quoted words becomes the words; "" when nothing was."""
    found: list[str] = []

    def _sub(m):
        found.append(m.group(0).strip()[:80])
        return m.group("text").strip()
    out = _SPEAK_TEXT_RE.sub(_sub, text or "")
    return (out, " · ".join(found)) if found else (text, "")


def _parse(data: dict) -> dict:
    """Normalize one /api/chat response into the assistant message dict."""
    msg = data.get("message", {}) or {}
    inline_thinking, clean = split_thinking(scrub_litter(msg.get("content", "")))
    spilled, clean = split_comment_thought(clean)
    clean = collapse_stutter(clean)
    clean, mended_caps = mend_glued_caps(clean)
    clean, mended_sig = mend_signature(clean)
    clean, mended_row = mend_emoji_row(clean)  # a repeat in the sign-off row, taken off
    clean, mended_flags = strip_row_flags(clean)  # a flag dealt into a row, taken off
    clean, unwrapped = unwrap_speak(clean)
    if unwrapped:
        msg["unwrapped_speak"] = unwrapped
    thinking = scrub_litter(msg.get("thinking") or "").strip() or inline_thinking
    if spilled:
        thinking = (thinking + "\n\n" + spilled).strip() if thinking else spilled
    thinking, t_loop = collapse_loops(thinking)
    clean, c_loop = collapse_loops(clean)
    # reserved tokens written as text are made harmless here, before any
    # rail quotes them or any turn carries them (see defang)
    clean, defanged = defang(clean)
    thinking, defanged_t = defang(thinking)
    msg["defanged"] = defanged + defanged_t
    msg["thinking"] = thinking
    msg["content"] = clean
    msg["looped"] = t_loop or c_loop
    msg["mended_caps"] = mended_caps
    msg["mended_signature"] = mended_sig
    msg["mended_emoji"] = mended_row
    msg["mended_flags"] = mended_flags
    # what this call cost: tokens read (the prompt) and written (thinking +
    # words + tool calls), straight from Ollama's counters
    msg["tokens"] = {"prompt": int(data.get("prompt_eval_count") or 0),
                     "reply": int(data.get("eval_count") or 0),
                     "by_hand": bool(data.get("counted_by_hand")),  # the server sent no counters; chunks were counted
                     # why generation ended: "stop" (the model chose to), "length"
                     # (a limit cut it), or "" when the server didn't say
                     "done": str(data.get("done_reason") or ""),
                     # Ollama reports durations in nanoseconds
                     "prompt_s": (data.get("prompt_eval_duration") or 0) / 1e9,
                     "reply_s": (data.get("eval_duration") or 0) / 1e9,
                     # a model (re)load — a swap for their ears, an eviction —
                     # shows here and nowhere else
                     "load_s": (data.get("load_duration") or 0) / 1e9,
                     "total_s": (data.get("total_duration") or 0) / 1e9,
                     # how much of the prompt the door found already read (llama-server's cache_n)
                     "reused": int(data.get("cache_n") or 0)}
    if data.get("aborted"):
        msg["aborted"] = data["aborted"]  # the stream was cut short at this: a runaway
    if data.get("aborted_call"):
        msg["aborted_call"] = dict(data["aborted_call"])  # …inside a tool call: which, its name, its loop, what was kept, how far it ran
    if data.get("thoughtless_cut"):
        msg["thoughtless_cut"] = True  # closed at its first word: no thought came first
    if data.get("split_tail"):
        msg["split_tail"] = defang(scrub_litter(data["split_tail"]).strip())[0]  # the rest of the reply, misfiled as thought
    if data.get("restored"):
        msg["restored"] = dict(data["restored"])  # the door restored a saved reading before this reply (brain._restore)
    msg.setdefault("role", "assistant")
    return msg


def _ollama_ps() -> list[str]:
    """What Ollama itself holds (/api/ps)."""
    try:
        req = urllib.request.Request(config.OLLAMA_URL + "/api/ps")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def _loaded_models() -> list[str]:
    """What is on the card. Under BRAIN_API = "llama" the brain is the door's: named while the
    door answers awake, whatever Ollama says of it; Ollama's list still speaks for the rest."""
    names = _ollama_ps()
    if brain.api() == "llama":
        names = [n for n in names if n != config.CHAT_MODEL] + ([config.CHAT_MODEL] if brain.awake() else [])
    return names


def rest_keeps_brain() -> bool:
    """A rest (unload(..., rest=True)) leaves the brain where it is: under BRAIN_API = "llama" with
    BRAIN_REST_CLOSES_DOOR off the door stays up. The callers say "set down" only when it was."""
    return brain.api() == "llama" and not getattr(config, "BRAIN_REST_CLOSES_DOOR", True)


def unload_all() -> list[str]:
    """Everything Ollama holds, set down (the keeper's /release: the card for something else) — the
    brain, the ears, the memory engine, whatever is loaded; each waited for. The names freed, in order."""
    names = _loaded_models()
    if brain.api() == "llama":
        # the door's brain is set down by closing the door — named among the freed only when it was up and
        # the house's (marked); one opened some other way by hand is not the engine's to close
        door_up = config.CHAT_MODEL in names
        names = [n for n in names if n != config.CHAT_MODEL]
        for name in names:
            unload(name)
        if door_up and brain.stop_door(why="unload_all"):
            names.append(config.CHAT_MODEL)
        return names
    for name in names:
        unload(name)
    return names


def unload(model: str, rest: bool = False, save: bool = True) -> None:
    """Free a model's VRAM and WAIT until it is actually gone. Best-effort.

    keep_alive:0 only schedules the eviction — if the next model is loaded
    before it completes, it lands half on CPU and runs at a crawl. Polling
    /api/ps until the model disappears is what makes the handoff real.

    rest=True is a rest, not an eviction (rest_brain, rest_after_wake): the
    card handed back because nothing needs it. On Ollama it is the same
    keep_alive:0. Under BRAIN_API = "llama" the door stays up — closing it
    would cost a save, a reopening and a restore for a card nobody is
    waiting for; the painter, the ears and /release evict when they need it."""
    import time

    if model == config.CHAT_MODEL and brain.api() == "llama":
        if rest and not getattr(config, "BRAIN_REST_CLOSES_DOOR", True):
            brain._note("the brain stays up on the door — a rest is not a step-down")
            return
        if rest:
            # a rest closes the door too (or the card stays held long after the visit): the
            # visit's end with its reading saved; a wake's end without (its prompt is never read twice, and
            # with keep 1 its save would evict the visit's reading, which the next message wants)
            brain.stop_door(why="rest", save=save)
            return
        brain.stop_door(why="unload")  # the door holds the brain: closing it is the unload, the card free on return
        return
    try:
        _post("/api/generate", {"model": model, "keep_alive": 0})
    except Exception:
        return  # unloading is an optimization, never a requirement
    base = model.split(":")[0]
    for _ in range(20):  # up to ~20s
        if not any(base in name for name in _ollama_ps()):  # Ollama's own list: the door's brain is not its to wait on
            return
        time.sleep(1)


_DEAF_RE = re.compile(
    r"(did not receive|didn'?t receive|no audio|not receive an audible|"
    r"cannot hear|can'?t hear|provide the audio|no audible|without.*audio|"
    r"not provided|haven'?t provided|have not provided|upload the audio|"
    r"provide an audio|no sound|string of characters|as text|text input)",
    re.IGNORECASE,
)


def _extract_answer(msg: dict) -> str:
    raw = msg.get("content", "") or ""
    heard = strip_thinking(raw)
    if not heard:
        # native API puts chain-of-thought in message.thinking; OpenAI-compat
        # servers use reasoning/reasoning_content — check them all
        heard = (msg.get("thinking") or msg.get("reasoning")
                 or msg.get("reasoning_content") or "").strip()
    if not heard:
        thinking, _ = split_thinking(raw)
        heard = thinking
    return heard


def hear(audio_b64: str, fmt: str, prompt: str) -> str:
    """Send audio to the ears model. Returns its description.

    Tries the OpenAI-compatible input_audio shape first, then the native
    /api/chat 'audios' field — which one carries audio depends on the Ollama
    version. If the model answers 'I received no audio', the shape was
    silently dropped and the next one is tried.

    The main brain is unloaded first so the ears model gets the whole GPU —
    unless the ears ARE the brain, in which case it stays right where it is."""
    if config.EARS_MODEL != config.CHAT_MODEL \
            and getattr(config, "EARS_UNLOAD_BRAIN", True):
        unload(config.CHAT_MODEL)

    attempts = [
        # ORDER MATTERS — test_ears.py is the referee (two runs, five shapes,
        # on Ollama 0.33.2 + RTX 5090): the native images-field route hears a
        # test tone correctly ONLY with thinking left on. The identical request
        # with think:False confabulates scenes (marketplaces, grinding
        # machines) — that flag routes through a template path that loses the
        # audio. The OpenAI wav shape is unstable, and MP3 decodes to garbage.
        # So: native route, thinking allowed, first.
        ("/api/chat", {
            "model": config.EARS_MODEL,
            "messages": [{"role": "user", "content": prompt, "images": [audio_b64]}],
            "options": {"num_ctx": 8000},
            "stream": False,
        }),
        # fallback: the OpenAI-compatible shape (half-right on this build)
        ("/v1/chat/completions", {
            "model": config.EARS_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "input_audio",
                     "input_audio": {"data": audio_b64, "format": fmt}},
                    {"type": "text", "text": prompt},
                ],
            }],
        }),
    ]

    last = ""
    for path, payload in attempts:
        data = _post(path, payload)
        if path == "/api/chat":
            msg = data.get("message", {}) or {}
        else:
            choices = data.get("choices") or []
            msg = (choices[0].get("message", {}) or {}) if choices else {}
        heard = _extract_answer(msg)
        if heard and not _DEAF_RE.search(heard):
            return heard
        last = heard or last

    if last:
        # every shape was dropped — the server itself can't carry audio
        raise BrainUnavailable(
            "the audio never reached the ears model — your Ollama version likely "
            "doesn't support audio input yet. Update Ollama (ollama.com/download) "
            f"and try again. (the ears said: {last[:160]})"
        )
    raise BrainUnavailable(
        "the ears listened but produced no description — try once more "
        "(small audio models are moody)"
    )


def embed(text: str) -> list[float]:
    """Embed one string with the configured embedding model."""
    body = {"model": config.EMBED_MODEL, "input": text}
    if getattr(config, "EMBED_ON_CPU", False):
        body["options"] = {"num_gpu": 0}  # the embedder on the CPU, the card left to the brain
    data = _post("/api/embed", body)
    embeddings = data.get("embeddings") or []
    if not embeddings:
        raise BrainUnavailable(
            f"Ollama returned no embedding — is `{config.EMBED_MODEL}` pulled? "
            f"(run: ollama pull {config.EMBED_MODEL})"
        )
    return embeddings[0]
