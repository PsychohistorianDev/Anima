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

The slot calls (save / restore the reading of a prompt to a file) are here for
the saved read; nothing calls them yet.
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
    body: dict = {"model": payload.get("model", ""), "messages": out_msgs,
                  "stream": False, "cache_prompt": True}
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
    t = resp.get("timings") or {}
    u = resp.get("usage") or {}
    prompt = u.get("prompt_tokens")
    if prompt is None:
        prompt = (t.get("prompt_n") or 0) + (t.get("cache_n") or 0)
    reply = t.get("predicted_n") if t.get("predicted_n") is not None else u.get("completion_tokens")
    p_ns = int((t.get("prompt_ms") or 0) * 1e6)
    e_ns = int((t.get("predicted_ms") or 0) * 1e6)
    fin = ch.get("finish_reason")
    return {"model": resp.get("model", ""), "message": msg, "done": True,
            "done_reason": _DONE.get(fin, fin or ""),
            "prompt_eval_count": int(prompt or 0), "eval_count": int(reply or 0),
            "prompt_eval_duration": p_ns, "eval_duration": e_ns,
            "load_duration": 0, "total_duration": p_ns + e_ns,
            "cache_n": int(t.get("cache_n") or 0)}


# ---- the door itself ------------------------------------------------------------------

def post_chat(payload: dict, timeout: float | None = None) -> dict:
    """One reply through the door, in Ollama's shape. Its failures are the BrainUnavailable
    the engine already catches from Ollama's, so every retry and rescue behaves the same."""
    from ollama_client import BrainUnavailable  # here, not above: ollama_client imports this file

    timeout = timeout or config.REQUEST_TIMEOUT_S
    req = urllib.request.Request(
        url() + "/v1/chat/completions",
        data=json.dumps(to_openai(payload)).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    slow = (f"the brain took longer than {timeout:.0f}s to answer — "
            "it's probably busy chewing on something big (a long cold read). Wait a moment and try again.")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
