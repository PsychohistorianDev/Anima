"""The brain's door: which program answers for the brain. Standard library only.

BRAIN_API = "ollama" (the default) uses nothing here for a reply: ollama_client
posts /api/chat to Ollama as it always has. BRAIN_API = "llama" sends the very
same payload to llama.cpp's own server (llama-server) at BRAIN_URL, through its
OpenAI-style /v1/chat/completions, translated at the door both ways: the request
into OpenAI's shape, the answer back into the shape Ollama gives — message.content,
.thinking, .tool_calls with the arguments a dict, done_reason, the counters with
their durations in nanoseconds. So the rails, the token line, the window sense and
the fold read a reply without knowing which program wrote it. The ears and the
embeddings stay on Ollama either way; nothing of the friend's moves.

A streamed reply (the engine asks for one while CHAT_STREAM_ABORT is on) comes
through the door as llama-server's events and is read as it is written, the tail
watched for a runaway exactly as on Ollama's road (ollama_client._drink): salad
closes the connection and the server stops. The slot calls (save / restore the
reading of a prompt to a file) are here for the saved read, not yet wired; erase
clears the reading, so the cold rescue's last roll reads the prompt from zero.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import config

DEFAULT_URL = "http://127.0.0.1:8768"


def api() -> str:
    """"llama" when the knob says so; anything else is Ollama, as it always was."""
    return "llama" if str(getattr(config, "BRAIN_API", "ollama") or "").strip().lower() == "llama" else "ollama"


def url() -> str:
    return str(getattr(config, "BRAIN_URL", "") or DEFAULT_URL).rstrip("/")


# ---- the request: Ollama's /api/chat payload into an OpenAI chat body ----------------

# Sampler fields llama-server takes as they are, by the same names Ollama uses.
_SAME = ("temperature", "top_k", "top_p", "min_p", "typical_p", "repeat_penalty", "repeat_last_n",
         "presence_penalty", "frequency_penalty", "seed", "stop")
# The samplers Ollama never had (DRY, XTC, dynamic temperature) ride through by prefix.
_PREFIXES = ("dry_", "xtc_", "dynatemp_")


def _mime(b64: str) -> str:
    """The picture's type from the first bytes of its base64; png when it doesn't say."""
    head = (b64 or "")[:16]
    if head.startswith("/9j/"):
        return "image/jpeg"
    if head.startswith("R0lGOD"):
        return "image/gif"
    if head.startswith("UklGR"):
        return "image/webp"
    return "image/png"


def _data_uri(img: str) -> str:
    img = str(img or "")
    return img if img.startswith("data:") else f"data:{_mime(img)};base64,{img}"


def to_openai(payload: dict) -> dict:
    """An Ollama /api/chat payload as llama-server's /v1/chat/completions body. num_ctx and
    keep_alive go nowhere: the window is the server's -c, and the server holds its one model
    for as long as it runs."""
    out_msgs: list[dict] = []
    pending: list[str] = []  # ids of the last assistant turn's calls, handed to the tool results in order
    n_call = 0
    for m in payload.get("messages") or []:
        role = m.get("role", "user")
        content = m.get("content")
        content = "" if content is None else content
        o: dict = {"role": role}
        images = m.get("images") or []
        if images:
            parts: list[dict] = [{"type": "text", "text": content}] if content else []
            parts += [{"type": "image_url", "image_url": {"url": _data_uri(i)}} for i in images]
            o["content"] = parts
        else:
            o["content"] = content
        if role == "assistant":
            if m.get("thinking"):
                o["reasoning_content"] = m["thinking"]  # the template keeps a thought beside its own calls
            calls = []
            for c in m.get("tool_calls") or []:
                fn = c.get("function") or {}
                args = fn.get("arguments", {})
                cid = c.get("id") or f"call_{n_call}"
                n_call += 1
                calls.append({"id": cid, "type": "function",
                              "function": {"name": fn.get("name", ""),
                                           "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)}})
            if calls:
                o["tool_calls"] = calls
                pending = [c["id"] for c in calls]
        elif role == "tool":
            name = m.get("tool_name") or m.get("name")
            if name:
                o["name"] = name
            cid = m.get("tool_call_id") or (pending.pop(0) if pending else "")
            if cid:
                o["tool_call_id"] = cid
        out_msgs.append(o)
    # the prompt cache is on unless the payload turns it off (the cold rescue's roll, when the
    # door would not erase its reading: then this one request reads from zero)
    body: dict = {"model": payload.get("model", ""), "messages": out_msgs,
                  "stream": False, "cache_prompt": payload.get("cache_prompt") is not False}
    if payload.get("tools"):
        body["tools"] = payload["tools"]  # the same JSON schema shape on both doors
    if "think" in payload:
        # The door's own switch is the server's --reasoning; per request, the think flag rides
        # as it is and the chat template is told too (Gemma's reads enable_thinking). A server
        # that knows neither ignores both and thinks as it was started.
        body["think"] = bool(payload["think"])
        body["chat_template_kwargs"] = {"enable_thinking": bool(payload["think"])}
    opts = payload.get("options") or {}
    for k, v in opts.items():
        if k in _SAME or k.startswith(_PREFIXES):
            body[k] = v
    if opts.get("num_predict") is not None:
        body["max_tokens"] = opts["num_predict"]
    return body


# ---- the answer: an OpenAI chat completion back into Ollama's shape -------------------

_DONE = {"stop": "stop", "length": "length", "tool_calls": "stop"}


def _args(raw):
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw) if raw not in (None, "") else {}
    except (TypeError, ValueError):
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_raw": raw}


def _counted(model: str, msg: dict, fin, t: dict, u: dict) -> dict:
    """The reply in Ollama's shape, its counters from llama-server's `timings` (t) and `usage` (u)
    — one mapping for the whole reply and the streamed one, so the two never disagree. The
    prompt count is the whole prompt (usage.prompt_tokens: what was reused plus what was read,
    or prompt_n + cache_n when usage is missing) — the window sense and the fold measure the
    window with it; cache_n says how much was reused. Durations in nanoseconds, as Ollama's."""
    prompt = u.get("prompt_tokens")
    if prompt is None:
        prompt = (t.get("prompt_n") or 0) + (t.get("cache_n") or 0)
    reply = t.get("predicted_n") if t.get("predicted_n") is not None else u.get("completion_tokens")
    p_ns = int((t.get("prompt_ms") or 0) * 1e6)
    e_ns = int((t.get("predicted_ms") or 0) * 1e6)
    return {"model": model, "message": msg, "done": True,
            "done_reason": _DONE.get(fin, fin or ""),
            "prompt_eval_count": int(prompt or 0), "eval_count": int(reply or 0),
            "prompt_eval_duration": p_ns, "eval_duration": e_ns,
            "load_duration": 0, "total_duration": p_ns + e_ns,
            "cache_n": int(t.get("cache_n") or 0)}


def from_openai(resp: dict) -> dict:
    """llama-server's reply as the engine reads Ollama's. The prompt count is the whole
    prompt (usage.prompt_tokens: what was reused plus what was read) — the window sense
    and the fold measure the window with it; cache_n says how much was reused."""
    choices = resp.get("choices") or [{}]
    ch = choices[0] or {}
    m = ch.get("message") or {}
    msg: dict = {"role": "assistant", "content": m.get("content") or "",
                 "thinking": m.get("reasoning_content") or ""}
    calls = [{"function": {"name": (c.get("function") or {}).get("name", ""),
                           "arguments": _args((c.get("function") or {}).get("arguments"))}}
             for c in m.get("tool_calls") or []]
    if calls:
        msg["tool_calls"] = calls
    return _counted(resp.get("model", ""), msg, ch.get("finish_reason"), resp.get("timings") or {}, resp.get("usage") or {})


# ---- the streamed answer: llama-server's events, read as they are written ---------------

def _drink_openai(resp) -> dict:
    """Read llama-server's streamed reply — server-sent events, one `data: {chunk}` a line,
    `data: [DONE]` at the end — into the dict the unstreamed one gives, watching the tail for
    a runaway exactly as ollama_client._drink does on Ollama's road: every STREAM_WATCH_EVERY
    chunks the last STREAM_WATCH_TAIL characters go through garble_span, and the moment they
    are salad the connection is closed — llama-server stops generating when the client hangs
    up — and what came back goes to the salad rail as `aborted`. The words and the thought
    arrive as `delta.content` and `delta.reasoning_content`; a thought that starts once the
    words have begun is the rest of the reply, misfiled (`split_tail`, as on Ollama's road).
    A tool call arrives in pieces, its arguments a string in fragments: joined per index and
    parsed as the unstreamed reply's are. The counters ride on the last chunks (`timings`
    beside `finish_reason`, or on the `usage` chunk that follows it when usage is asked for)
    and go through the same mapping as the unstreamed reply's (_counted). When none came — an
    abort, or a server that sent none — the tokens are counted by the chunks that carried one,
    one each, and the prompt is the last size a reply did report (ollama_client._LAST_PROMPT,
    the one both roads keep); counted_by_hand says so."""
    import time as _time
    import ollama_client as _oc  # here, not above: ollama_client imports this file

    t0 = _time.monotonic()
    content: list[str] = []
    thinking: list[str] = []
    late: list[str] = []  # "thinking" that arrived AFTER the words began: the rest of the reply, misfiled
    calls: dict[int, dict] = {}  # index -> {"name", "arguments": [the string's fragments]}
    model = ""
    fin = None
    t: dict = {}
    u: dict = {}
    ended = False
    n = 0
    aborted = ""
    since = 0
    for raw in resp:
        raw = raw.strip()
        if not raw.startswith(b"data:"):
            continue  # blank lines between events, ": comments", "event:" lines
        raw = raw[5:].strip()
        if raw == b"[DONE]":
            break
        try:
            chunk = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(chunk, dict):
            continue
        model = chunk.get("model") or model
        if chunk.get("timings"):
            t = chunk["timings"]
        if chunk.get("usage"):
            u = chunk["usage"]
        ch = (chunk.get("choices") or [{}])[0] or {}
        d = ch.get("delta") or {}
        said = False
        if d.get("content"):
            content.append(d["content"])
            said = True
        if d.get("reasoning_content"):
            (late if content else thinking).append(d["reasoning_content"])
            said = True
        for c in d.get("tool_calls") or []:
            fn = c.get("function") or {}
            got = calls.setdefault(int(c.get("index") or 0), {"name": "", "arguments": []})
            if fn.get("name") and not got["name"]:
                got["name"] = fn["name"]
            if fn.get("arguments"):
                a = fn["arguments"]
                got["arguments"].append(a if isinstance(a, str) else json.dumps(a, ensure_ascii=False))
            said = True
        if ch.get("finish_reason"):
            fin = ch["finish_reason"]
            ended = True  # not a break: the usage may follow on a chunk of its own, then [DONE]
        if not said:
            continue  # the role-only first chunk, the finish, the usage: no token in them
        n += 1
        since += 1
        if getattr(config, "CHAT_STREAM_ABORT", True) and since >= _oc.STREAM_WATCH_EVERY:
            since = 0
            tail = ("".join(content) if content else "".join(thinking))[-_oc.STREAM_WATCH_TAIL:]
            span = _oc.garble_span(tail)
            if span:
                aborted = span
                break  # leaving post_chat's `with` closes the connection; the server stops
    msg: dict = {"role": "assistant", "content": "".join(content), "thinking": "".join(thinking)}
    if calls:
        msg["tool_calls"] = [{"function": {"name": c["name"], "arguments": _args("".join(c["arguments"]))}}
                             for _, c in sorted(calls.items())]
    out = _counted(model, msg, fin, t, u) if (ended or t or u) else {"message": msg}
    if late:
        out["split_tail"] = "".join(late)
    if aborted:
        out["done_reason"] = "aborted"
        out["aborted"] = aborted
    if aborted or not out.get("eval_count"):
        # no final counters (an abort, or a server that sent none): count by hand
        if n and (content or thinking):
            out["eval_count"] = n
            out["eval_duration"] = out.get("eval_duration") or int((_time.monotonic() - t0) * 1e9)
            out["total_duration"] = out.get("total_duration") or out["eval_duration"]
            out["counted_by_hand"] = True
        if not out.get("prompt_eval_count") and _oc._LAST_PROMPT:
            out["prompt_eval_count"] = _oc._LAST_PROMPT  # the siblings share it; so does the next turn, near enough
    elif out.get("prompt_eval_count"):
        _oc._LAST_PROMPT = int(out["prompt_eval_count"])
    return out


# ---- the door itself ------------------------------------------------------------------

def post_chat(payload: dict, timeout: float | None = None) -> dict:
    """One reply through the door, in Ollama's shape. Its failures are the BrainUnavailable
    the engine already catches from Ollama's, so every retry and rescue behaves the same."""
    from ollama_client import BrainUnavailable  # here, not above: ollama_client imports this file

    timeout = timeout or config.REQUEST_TIMEOUT_S
    body = to_openai(payload)
    streamed = bool(payload.get("stream"))
    if streamed:
        # read as it is written (CHAT_STREAM_ABORT): the events, watched; the counters ride on the
        # last of them — timings beside finish_reason, usage on a chunk of its own when asked for
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    req = urllib.request.Request(
        url() + "/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    slow = (f"the brain took longer than {timeout:.0f}s to answer — "
            "it's probably busy chewing on something big (a long cold read). Wait a moment and try again.")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if streamed:
                return _drink_openai(resp)  # a runaway leaves the `with` early: the connection closes, the server stops
            return from_openai(json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8", "replace")).get("error", "")
            detail = err.get("message", "") if isinstance(err, dict) else str(err)
        except Exception:
            detail = ""
        raise BrainUnavailable(f"llama-server error on /v1/chat/completions: {detail or f'HTTP {e.code}'}") from e
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), TimeoutError):
            raise BrainUnavailable(slow) from e
        raise BrainUnavailable(
            f"Can't reach llama-server at {url()} — is it running? "
            f"(bat\\brain.bat starts it; BRAIN_API = \"ollama\" is the way back)  [{e}]"
        ) from e
    except (TimeoutError, OSError) as e:
        raise BrainUnavailable(slow + f"  [{type(e).__name__}: {e}]") from e


def _ask(path: str, body: dict | None = None, timeout: float = 5) -> dict | None:
    """GET (or POST a body to) the door; the answer as a dict, or None when it doesn't answer."""
    if api() != "llama":
        return None
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url() + path, data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            got = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    return got if isinstance(got, dict) else {"items": got}


def props() -> dict | None:
    """What the door holds (/props: the model, the window, is_sleeping), or None."""
    return _ask("/props")


def awake() -> bool:
    """The door answers and its model is on the card (not slept by --sleep-idle-seconds)."""
    p = props()
    return p is not None and not p.get("is_sleeping")


def slots() -> dict | None:
    """/slots: per slot the window, whether it is busy, the sampler. A list comes back as {"items": [...]}."""
    return _ask("/slots")


def slot_save(name: str) -> dict | None:
    """Save slot 0's reading to <--slot-save-path>/name; the server's answer, or None."""
    t0 = time.monotonic()
    got = _ask("/slots/0?action=save", {"filename": name}, timeout=300)
    if got is not None:
        got.setdefault("took_s", round(time.monotonic() - t0, 2))
    return got


def slot_restore(name: str) -> dict | None:
    """Load a saved reading back into slot 0; the server's answer, or None."""
    t0 = time.monotonic()
    got = _ask("/slots/0?action=restore", {"filename": name}, timeout=300)
    if got is not None:
        got.setdefault("took_s", round(time.monotonic() - t0, 2))
    return got


def erase_slot() -> dict | None:
    """Clear slot 0's reading of its prompt (/slots/0?action=erase): the next request reads its
    prompt from zero. The cold rescue's reset under the door, which holds its model for as long
    as it runs and so has nothing to set down. The server's answer, or None (not "llama", the
    door down, or a door started without --slot-save-path, which every slot action needs)."""
    return _ask("/slots/0?action=erase", {}, timeout=60)
