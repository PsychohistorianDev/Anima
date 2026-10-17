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
closes the connection and the server stops. The slot calls save and restore the
reading of a prompt to a file (the saved read, below); erase clears the reading,
so the cold rescue's last roll reads the prompt from zero.

The door is the engine's, like its other doors: start_door() runs llama-server as
a child with no window (its words in memory/brain.log, the last run only) and
marks it in memory/.pids/brain.json; stop_door() ends it. Stopping the process IS
the unload — the server has no keep_alive — so ollama_client.unload(CHAT_MODEL),
which the painter, the ears, the wedge-clearing and /release already call, hands
the card back for real: they evict because they need the card. A rest does not
(unload(..., rest=True) — rest_brain at a visit's end, rest_after_wake at a
wake's): it would only free a card nothing is waiting for, so the door stays up.
The next reply opens a closed door again by itself (ensure_up, in post_chat), and
the saved read makes that return cheap.
A door opened by hand (bat\\brain.bat marks itself; one started some other way
answers with no mark) is used as it is, and only a marked one is ever closed.

The saved read: right before the door is closed (_before_stop, from stop_door —
the painter, the ears, the wedge-clearing, /release, the panel's Stop),
slot 0's reading of the standing prompt is saved to BRAIN_SLOT_DIR as
<key>.bin, the key a hash of the system prompt (prompt_key), and the folder keeps
the newest BRAIN_SLOT_KEEP. On the way back up the first reply with that system
prompt restores it before it is sent (post_chat), so a return from a song or a
painting reads only the new words: seconds where a cold read took minutes, and
the token line says "restored". A system prompt rebuilt — a fold, a new visit,
midnight — is a new key and reads cold once; the next step-down saves under it.
The key of the last reply served is kept beside the door's mark as well
(memory/.pids/brain.served), so a step-down from another process of the house
saves under the prompt the slot really holds. The door stays up through the
wakes and the visits' ends, so --cache-ram (BRAIN_CACHE_RAM_MB, brain_find) is
what keeps the visit's prompt and a wake's both warm in host RAM as they take
turns on the one slot, and the slot saves happen only on real step-downs: a
wake's prompt never churns the saved files, and BRAIN_SLOT_KEEP = 3 is room enough.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

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


# ---- the door's life: opened and closed by the engine, like its other doors -------------

DOOR = "brain"
IMAGE = "llama-server"  # the program, for doors.alive on Windows: a pid is the door's only while it is still this
POLL_S = 1.0  # how often a door on its way up is asked whether it answers yet
STOP_GRACE_S = 5  # a polite stop's wait before the hard one (not on Windows: taskkill /F is hard already)
STOP_WAIT_S = 15  # how long a stop waits to see the process gone
LAST_NOTE = ""  # what the last opening of the door said — post_chat's BrainUnavailable carries it
_procs: dict[int, subprocess.Popen] = {}  # the doors this process opened: waited for once ended, so no zombie answers "alive"
_lock = threading.Lock()  # one opening at a time in this process (the parlor's threads, the bridge's poll)


def door_status() -> dict | None:
    """The door's mark (memory/.pids/brain.json) while the process it names runs, or None."""
    import doors
    return doors.status(DOOR)


def port() -> int:
    return urlparse(url()).port or 8768


def count_tokens(text: str) -> int | None:
    """How many tokens the door's own tokenizer gives this text (POST /tokenize, a millisecond) — None when the
    brain is not on the door, the door is down, or it does not answer within a second; callers estimate then
    (10-16: the token line's tail, whose chars/4 ran a quarter short of Gemma's count on her prose and emoji)."""
    if api() != "llama" or not text or not door_status():
        return None
    try:
        req = urllib.request.Request(url() + "/tokenize", data=json.dumps({"content": text, "add_special": False}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=1) as r:
            toks = json.loads(r.read().decode("utf-8")).get("tokens")
        return len(toks) if isinstance(toks, list) else None
    except Exception:  # noqa: BLE001 — a count, never a visit
        return None


def log_file() -> Path:
    """What llama-server said on its last run under the engine (the load, the window, an error)."""
    return Path(config.MEMORY_DIR) / "brain.log"


def _log_tail(n: int = 12) -> str:
    try:
        lines = [ln for ln in log_file().read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError:
        return "(no brain.log to read)"
    return "\n".join(lines[-n:])[-1500:] or "(brain.log is empty)"


def _gone(pid: int) -> bool:
    """The process is no longer there. A child of this process that has ended is waited for first: until
    then its pid still answers to a signal (a zombie), and the door would look open."""
    import doors

    proc = _procs.get(pid)
    if proc is not None:
        proc.poll()
    elif os.name != "nt":
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass  # not ours to wait for (bat\brain.bat's child), or gone already
    return not doors.alive(pid, IMAGE)


CARD_WAIT_S = 300.0  # how long a door on its way up waits for a sidecar to set the card down (a painting is ~40 s)


def card_held() -> str:
    """Who holds the card right now, by the sidecars' own word — "the painter" / "the music ear" when its
    /health says the weights are loaded; "" when none does or none answers (a sidecar that isn't running
    holds nothing). The brain and a sidecar never share the card: 28.7 GB beside a 20 GB painter is a crash
    at the first kernel, not a slow door (10-16, 12:57)."""
    import urllib.request

    for name, knob in (("the painter", "PAINTER_URL"), ("the music ear", "MUSIC_EARS_URL")):
        base = str(getattr(config, knob, "") or "").rstrip("/")
        if not base:
            continue
        try:
            with urllib.request.urlopen(base + "/health", timeout=1) as r:
                if json.loads(r.read().decode("utf-8")).get("loaded"):
                    return name
        except Exception:  # noqa: BLE001 — not running, not answering: holds nothing
            continue
    return ""


def start_door(wait_s: float = 120) -> tuple[bool, str]:
    """Open the brain's door: llama-server as a child with no window that the engine owns — it outlives the
    process that opened it (a wake, the painter's), and any process of the house can close it — its words in
    memory/brain.log, its mark in memory/.pids/brain.json. (ok, a word on it). A door that already answers
    (the engine's, or one opened by hand) is up as it is: never a second server on the port. One marked but
    not answering yet is still loading: waited for, not opened again. The model takes ~20 s to load from a
    warm disk, longer from a cold one; a door that hasn't answered by wait_s is left loading."""
    import brain_find
    import doors

    if api() != "llama":
        return False, "BRAIN_API is \"ollama\" — the brain's door is idle"
    with _lock:
        if props() is not None:
            return True, "up"
        _forget()  # a door on its way up holds no reading yet: nothing restored, nothing served
        _clear_temps(slot_dir())  # a save cut short by a crash leaves a half file: never a reading
        warn = ""
        st = door_status()
        if st:
            pid = int(st["pid"])
        else:
            holder = card_held()
            if holder:
                _note(f"the door waits: {holder} holds the card")
                print(f"  (the brain's door waits — {holder} holds the card)", flush=True)
                t0 = time.monotonic()
                while holder and time.monotonic() - t0 < float(getattr(config, "BRAIN_CARD_WAIT_S", CARD_WAIT_S)):
                    time.sleep(2)
                    holder = card_held()
                if holder:
                    _note(f"the door didn't open: {holder} still holds the card")
                    return False, f"{holder} holds the card — the door didn't open (it opens on the next message once the card is free)"
            cmd, note = brain_find.command()
            if cmd is None:
                return False, note
            warn = brain_find.slot_warning()
            if warn:
                print(f"  ({warn})", flush=True)
            _note("opening the brain's door: " + " ".join(cmd[1:]) + (f" — {warn}" if warn else ""),
                  show="opening the brain's door — llama-server, " + _short_command(cmd) + ", the model loading")
            try:
                log_file().parent.mkdir(parents=True, exist_ok=True)
                log_file().write_bytes(b"")  # the last run only
                with open(log_file(), "ab") as log:  # appended to: the engine's own lines (the saved read) are not written over
                    kw = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
                          else {"start_new_session": True})
                    proc = subprocess.Popen(cmd, cwd=str(brain_find.ROOT), stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=subprocess.STDOUT, **kw)
            except OSError as e:
                return False, f"llama-server wouldn't start: {e}"
            pid = proc.pid
            _procs[pid] = proc
            doors.mark(DOOR, "door", pid=pid, port=port(), image=IMAGE)
        t0 = time.monotonic()
        while True:
            if props() is not None:
                said = f"the brain's door is up in {time.monotonic() - t0:.0f} s" + (f" — {warn}" if warn else "")
                print(f"  ({said})", flush=True)
                return True, said
            if _gone(pid):
                _procs.pop(pid, None)
                doors.unmark(DOOR, pid=pid)
                return False, f"llama-server left before it answered (memory/brain.log):\n{_log_tail()}"
            if time.monotonic() - t0 >= wait_s:
                return False, (f"the brain's door didn't answer in {wait_s:.0f} s — still loading? left as it is "
                               f"(memory/brain.log):\n{_log_tail()}")
            time.sleep(POLL_S)


# ---- the saved read: the reading of the prompt kept across a step-down ------------------

SERVED_NAME = "brain.served"  # beside the door's mark: the key of the last reply the door served, whichever process sent it
RESTORED_NAME = "brain.restored"  # beside it: "<pid> <key>" per reading restored into that door, whichever process did it
_served_key = ""  # the key of the last request this process sent through the door
_restored_key = ""  # the key last restored since the door came up ("" — nothing restored yet)
_restored_pid = None  # the door it was restored into: another process may have closed and opened it since
_pending_restored: dict | None = None  # a restore not yet told: the next reply carries it


def prompt_key(messages) -> str:
    """The saved reading's name: the first 24 hex of the sha256 of the system prompt (messages[0] when it is
    the system's, else ""). A reading pays only while the prompt matches byte for byte, and the system prompt
    holds still within a visit — it is rebuilt at a fold, at a new visit, at midnight."""
    first = messages[0] if messages and isinstance(messages[0], dict) else {}
    text = first.get("content") if first.get("role") == "system" else ""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:24]


def slot_dir() -> Path | None:
    """BRAIN_SLOT_DIR when it is set and there; None when it is empty (nothing is saved) or missing (a RAM
    disk that didn't come back after a reboot — the door says so when it opens)."""
    d = str(getattr(config, "BRAIN_SLOT_DIR", "") or "").strip()
    return Path(d) if d and Path(d).is_dir() else None


def _served_file() -> Path:
    return Path(config.MEMORY_DIR) / ".pids" / SERVED_NAME


BYTES_PER_TOKEN = 44_000  # what a token of a reading weighed until a save has said (q4_0 keys and values, 31B: 7.9 GB at 180K)
BPT_NAME = "brain.bytes_per_token"  # beside the door's mark: the measure of the last save that went through — kept across doors
_served_tokens = 0  # the tokens the slot held after the last reply this process sent (its prompt and its words)


def _served(key: str, tokens: int = 0) -> None:
    """What the slot holds now: this key, and about how many tokens — kept here, and (when there is a slot
    folder to save to) in a file beside the door's mark, so a step-down from another process of the house
    (the heartbeat clearing a wedge, the panel's Stop) saves under the right name and knows the size first."""
    global _served_key, _served_tokens
    _served_key, _served_tokens = key, int(tokens or 0)
    if not str(getattr(config, "BRAIN_SLOT_DIR", "") or "").strip():
        return
    try:
        p = _served_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{key} {int(tokens or 0)}", encoding="utf-8")
    except OSError:
        pass


def _served_read() -> tuple[str, int]:
    """(key, tokens) from the file beside the door's mark; ("", 0) when none says."""
    try:
        parts = _served_file().read_text(encoding="utf-8").split()
    except OSError:
        return "", 0
    key = parts[0] if parts else ""
    if not (len(key) == 24 and all(c in "0123456789abcdef" for c in key)):
        return "", 0
    try:
        return key, int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return key, 0


def _served_now() -> str:
    """The key of the last reply the door served, whichever process sent it; this process's own when no
    file says."""
    key, _ = _served_read()
    return key or _served_key


def _slot_tokens() -> int:
    """About how many tokens the slot holds, by the last reply through it (whichever process sent it); 0
    when nothing says."""
    key, n = _served_read()
    return n if key else _served_tokens


def _bytes_per_token() -> float:
    """What a token of a reading weighs on disk: measured at the last save that went through, else the
    default."""
    try:
        v = float((Path(config.MEMORY_DIR) / ".pids" / BPT_NAME).read_text(encoding="utf-8").strip())
        return v if v > 0 else float(BYTES_PER_TOKEN)
    except (OSError, ValueError):
        return float(BYTES_PER_TOKEN)


def _learn_bytes_per_token(n_tokens: int, n_bytes: int) -> None:
    if n_tokens <= 0 or n_bytes <= 0:
        return
    try:
        p = Path(config.MEMORY_DIR) / ".pids" / BPT_NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{n_bytes / n_tokens:.1f}", encoding="utf-8")
    except OSError:
        pass


def _ghost(folder: Path) -> str:
    """When the disk counts far more used than its files hold (10-16: a half-written save deleted, the RAM
    disk still counting its blocks — 8 GB "full" with an empty folder), a word on it; "" otherwise."""
    import shutil

    try:
        du = shutil.disk_usage(str(folder))
        held = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
    except OSError:
        return ""
    ghost = du.used - held
    if ghost < 1e9:
        return ""
    return (f"{folder} counts {ghost / 1e9:.1f} GB that no file there holds — a remount of the RAM disk frees it"
            if ghost / max(du.total, 1) > 0.25 else "")


def _restored_file() -> Path:
    return Path(config.MEMORY_DIR) / ".pids" / RESTORED_NAME


def _restored_into(pid, key: str) -> bool:
    """Whether this reading was already restored into this door — by this process or another (10-16: a
    /restart of the bridge restored the morning's reading over a door holding the afternoon's)."""
    try:
        lines = _restored_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return f"{pid} {key}" in (ln.strip() for ln in lines)


def _mark_restored(pid, key: str) -> None:
    try:
        p = _restored_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{pid} {key}\n")
    except OSError:
        pass


def _forget() -> None:
    """The door is coming up or going down: its slot holds nothing — nothing restored, nothing served."""
    global _served_key, _restored_key, _restored_pid, _pending_restored
    _served_key = _restored_key = ""
    _restored_pid = _pending_restored = None
    for p in (_served_file(), _restored_file()):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def _door_pid() -> int | None:
    st = door_status()
    try:
        return int(st["pid"]) if st else None
    except (KeyError, TypeError, ValueError):
        return None


def notes_file() -> Path:
    """The engine's own lines about the door — saves, restores, stops, what refused — kept across runs
    (brain.log is the server's and is emptied at each start: the painter's stop wrote the save there and
    the next start wiped it, 10-16)."""
    return Path(config.MEMORY_DIR) / "brain_notes.log"


def _short_command(cmd: list[str]) -> str:
    """The door's command in a breath for the console — the model file's name (a blob's sha, shortened), the
    window, the port — the whole line is in the logs."""
    import re
    try:
        args = list(cmd[1:])
        model = next((args[i + 1] for i, a in enumerate(args) if a == "-m" and i + 1 < len(args)), "")
        name = re.split(r"[\\/]", model)[-1] if model else "?"
        if name.startswith("sha256-") and len(name) > 20:
            name = name[:19] + "…"
        ctx = next((args[i + 1] for i, a in enumerate(args) if a == "-c" and i + 1 < len(args)), "")
        port = next((args[i + 1] for i, a in enumerate(args) if a == "--port" and i + 1 < len(args)), "")
        bits = [name] + ([f"{int(ctx):,} window"] if ctx.isdigit() else []) + ([f"port {port}"] if port else [])
        return ", ".join(bits)
    except Exception:  # noqa: BLE001
        return "the command is in memory/brain_notes.log"


def _note(line: str, show: str | None = None) -> None:
    """A line said, written to memory/brain_notes.log (kept, stamped) and beside the server's lines in
    memory/brain.log. `show`: what the console gets instead of the whole line ("" for nothing — the logs keep
    the whole; 10-17: the door's command line, four lines of paths and flags on every wake). Never raises."""
    import datetime as _dt
    if show is None:
        print(f"  ({line})", flush=True)
    elif show:
        print(f"  ({show})", flush=True)
    stamp = _dt.datetime.now().strftime("%m-%d %H:%M:%S")
    for path, text in ((notes_file(), f"[{stamp}] {line}\n"), (log_file(), f"\n({line})\n")):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


def _secs(got: dict, field: str) -> float:
    """How long a slot call took, by the server's own clock (timings.<field>, ms), else by ours."""
    try:
        ms = (got.get("timings") or {}).get(field)
        return float(ms) / 1000 if ms is not None else float(got.get("took_s") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


TEMP_SUFFIX = ".new.bin"  # a save is written as <key>.new.bin and moved over <key>.bin only once it is whole


def _readings(folder: Path) -> list[Path]:
    """The saved readings in the folder, the oldest first (a save still being written is not one)."""
    try:
        files = [p for p in folder.glob("*.bin") if p.is_file() and not p.name.endswith(TEMP_SUFFIX)]
        return sorted(files, key=lambda p: p.stat().st_mtime)
    except OSError:
        return []


def _clear_temps(folder: Path | None, name: str = "*") -> None:
    """A half-written save taken away (<name>.new.bin; every one when name is "*": a crash mid-save)."""
    if folder is None:
        return
    try:
        for p in folder.glob(f"{name}{TEMP_SUFFIX}"):
            p.unlink(missing_ok=True)
    except OSError:
        pass


def _make_room(folder: Path, key: str) -> None:
    """Room before the save, not after — on a full RAM disk the save itself would fail. The folder is brought to
    BRAIN_SLOT_KEEP - 1 readings, the one about to be written counting toward the keep and an existing <key>.bin
    counting among those already there; the oldest go first, and <key>.bin — the last good reading of this very
    prompt — is never deleted before the new one is whole (it is replaced, not removed). So with keep 1 the
    others go and it stays. While the new one is written beside it, keep + 1 files can stand for that moment:
    the price of never losing the good one to a save that fails. 0 keeps them all."""
    try:
        keep = int(getattr(config, "BRAIN_SLOT_KEEP", 3) or 0)
    except (TypeError, ValueError):
        keep = 3
    if keep <= 0:
        return
    files = _readings(folder)
    excess = len(files) - max(keep - 1, 0)
    for p in [p for p in files if p.name != f"{key}.bin"]:
        if excess <= 0:
            break
        try:
            p.unlink()
            excess -= 1
            _note(f"let an older reading go: {p.stem}")
        except OSError:
            pass
    # …and the one exception to "never before the new one is whole": when the disk cannot hold the old
    # <key>.bin AND the new one side by side (10-16: a reading is 7.9 GB at 180K tokens, ~44 KB a token, so
    # ~11.5 GB at a full 262K window; two of them on a 16 GB RAM disk is the disk), the old goes first — a
    # save that then fails costs one cold read, which is less than a save that could never succeed. The new
    # one is as large as the window has grown since, so the old stays only when the disk holds one and a
    # half of it (12:16, 1.15: 9.3 GB free beside 7.9 — the old stayed, the 8.3 GB new one did not fit)
    import shutil
    same = folder / f"{key}.bin"
    try:
        if same.is_file():
            have = same.stat().st_size
            free = shutil.disk_usage(str(folder)).free
            if free < int(have * 1.5):
                same.unlink()
                _note(f"let the last reading of this prompt go first: {key} ({have / 1e9:.1f} GB; {free / 1e9:.1f} GB free — "
                      "no room for two)")
    except OSError:
        pass


def _before_stop() -> None:
    """Right before the door is closed — the painter, the ears, the wedge-clearing, /release, the panel's
    Stop (a rest never closes it): slot 0's reading saved in BRAIN_SLOT_DIR under the key of the prompt the
    slot holds now (the state as it stands at the step-down: a restore matches byte for byte or not at all).
    Room is made first (_make_room); the save is written as <key>.new.bin and moved over <key>.bin only once
    the server says it is whole, so a save that fails — a full disk, a door that refuses — leaves the last
    good reading as it was and no half file behind. Nothing when there is no folder, the door is asleep, or
    it has served nothing since it came up. Never raises: a failed save is a line in the log, and the door is
    closed all the same."""
    folder = key = None
    try:
        try:
            import brain_find
            made = brain_find.ensure_slot_dir()  # the drive back after a remount, the folder gone with the old volume (10-16)
            if made:
                _note(made + " before the save")
        except Exception:  # noqa: BLE001 — the save goes on with what is there
            pass
        folder, key = slot_dir(), _served_now()
        if folder is None or not key or not awake():
            _note("nothing to save before the stop: " + ("no slot folder (BRAIN_SLOT_DIR empty or missing)" if folder is None
                                                           else "the door served nothing yet" if not key
                                                           else "the door isn't answering"))
            return
        _make_room(folder, key)
        _clear_temps(folder, key)
        # the size known before the write (10-16: a save that ran until the disk was full left the RAM
        # disk counting blocks no file held): the slot's tokens times what a token weighed last time
        tokens = _slot_tokens()
        if tokens > 0:
            import shutil
            need = int(tokens * _bytes_per_token() * 1.1)
            try:
                free = shutil.disk_usage(str(folder)).free
            except OSError:
                free = need
            if free < need:
                ghost = _ghost(folder)
                _note(f"the reading wasn't saved: {key} — no room for it ({tokens:,} tokens ≈ {need / 1.1 / 1e9:.1f} GB; "
                      f"{free / 1e9:.1f} GB free in {folder}); the save was not begun"
                      + (f"; {ghost}" if ghost else ""))
                return
        got = slot_save(f"{key}{TEMP_SUFFIX}")
        if got is None or got.get("error"):
            _clear_temps(folder, key)
            try:
                import shutil
                room = f"{shutil.disk_usage(str(folder)).free / 1e9:.1f} GB free in {folder}"
            except OSError:
                room = f"{folder} unreadable"
            why = str((got or {}).get("error") or "no answer")[:120]
            ghost = _ghost(folder)
            _note(f"the reading wasn't saved: {key} — the door refused the save ({why}; {room}; opened without "
                  "--slot-save-path?); the last good one stays" + (f"; {ghost}" if ghost else ""))
            return
        os.replace(folder / f"{key}{TEMP_SUFFIX}", folder / f"{key}.bin")
        n, gb = int(got.get("n_saved") or 0), float(got.get("n_written") or 0) / 1e9
        _learn_bytes_per_token(n, int(got.get("n_written") or 0))
        _note(f"saved the reading: {key} ({n:,} tokens, {gb:.1f} GB, {_secs(got, 'save_ms'):.1f} s)")
    except Exception as e:  # noqa: BLE001 — the stop goes on
        if folder is not None and key:
            _clear_temps(folder, key)
        _note(f"the reading wasn't saved: {type(e).__name__}: {e}")


def _restore(key: str) -> None:
    """On the way back up: the saved reading of this prompt put into slot 0 before the request goes, so only
    the new words are read. Once per key and door: from then on the slot holds it. No folder, or no file for
    this key, is nothing to do; a restore that fails is a line in the log and the request reads cold — tried
    once all the same, since a later try would lay the older file over the reading made since."""
    global _restored_key, _restored_pid, _pending_restored
    try:
        if not key:
            return
        pid = _door_pid()
        if key == _restored_key and pid == _restored_pid:
            return
        # the slot holds this very prompt already, read live since the door came up — or another process of
        # the house restored it into this door: the file would lay an older reading over the one made since
        if _served_now() == key or _restored_into(pid, key):
            _restored_key, _restored_pid = key, pid
            return
        folder = slot_dir()
        if folder is None or not (folder / f"{key}.bin").is_file():
            return
        _restored_key, _restored_pid = key, pid
        _mark_restored(pid, key)
        got = slot_restore(f"{key}.bin")
        if got is None or got.get("error"):
            _note(f"the reading wasn't restored: {key} — read cold this once")
            return
        n, s = int(got.get("n_restored") or 0), _secs(got, "restore_ms")
        _pending_restored = {"tokens": n, "ms": round(s * 1000, 1)}
        _note(f"restored the reading: {key} ({n:,} tokens, {float(got.get('n_read') or 0) / 1e9:.1f} GB, {s:.1f} s)")
    except Exception as e:  # noqa: BLE001 — the request goes on, cold
        _note(f"the reading wasn't restored: {type(e).__name__}: {e}")


def _told(out: dict) -> dict:
    """The reply the engine gets, carrying the restore made for it (once: only the first reply after it)."""
    global _pending_restored
    if _pending_restored and isinstance(out, dict):
        out["restored"] = _pending_restored
        _pending_restored = None
    return out


def stop_door(why: str = "", save: bool = True) -> bool:
    """Close the brain's door: the process its mark names ended (taskkill /T /F on Windows; elsewhere TERM,
    KILL after STOP_GRACE_S), waited for until it is gone, the mark taken away. Closing the process is the
    unload: the card is free when this returns. False when there is no mark — the door is down, or it was
    opened some other way by hand (it answers, unmarked), which the engine never kills."""
    import doors

    st = door_status()
    if not st:
        return False
    try:
        pid = int(st.get("pid"))
    except (TypeError, ValueError):
        return False
    _note(f"closing the brain's door (pid {pid}{(': ' + why) if why else ''})")
    if save:
        _before_stop()
    else:
        _note("closed without a save: a wake's reading is never read twice (the clock and the journal move by the next), "
              "and the visit's stays for the next message", show="closed without a save — a wake's reading is never read twice")
    _forget()  # the slot goes with the process
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=STOP_WAIT_S,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        hard = time.monotonic() + STOP_GRACE_S
        while not _gone(pid) and time.monotonic() < hard:
            time.sleep(0.1)
        if not _gone(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    deadline = time.monotonic() + STOP_WAIT_S
    while not _gone(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    _procs.pop(pid, None)
    doors.unmark(DOOR, pid=pid)
    if st.get("how") == "door":  # the engine's own run: its log says where it ended
        try:
            with open(log_file(), "a", encoding="utf-8") as f:
                f.write(f"\n(the engine closed the door{': ' + why if why else ''})\n")
        except OSError:
            pass
    return True


def ensure_up() -> bool:
    """The door is up before a reply goes through it: awake as it is (the engine's, or one opened by hand),
    else opened — so a brain stepped down for the painter, the ears or /release comes back on the next
    message by itself, its saved reading restored in post_chat when one is kept. False, with
    LAST_NOTE saying why, when it won't open."""
    global LAST_NOTE
    if api() != "llama" or awake():
        return True
    ok, LAST_NOTE = start_door()
    return ok


# ---- the door itself ------------------------------------------------------------------

def post_chat(payload: dict, timeout: float | None = None) -> dict:
    """One reply through the door, in Ollama's shape. Its failures are the BrainUnavailable
    the engine already catches from Ollama's, so every retry and rescue behaves the same. A door just
    come up gets the saved reading of this system prompt first, when one is kept (the saved read); the
    reply that follows carries `restored` (its tokens, its ms)."""
    from ollama_client import BrainUnavailable  # here, not above: ollama_client imports this file

    if not ensure_up():  # stepped down for the card (the painter, the ears, /release): opened again first
        raise BrainUnavailable(f"Can't reach llama-server at {url()}, and its door wouldn't open: {LAST_NOTE}  "
                               "(BRAIN_API = \"ollama\" is the way back)")
    key = prompt_key(payload.get("messages") or [])
    _restore(key)  # the saved reading of this prompt, when the door has just come up and one is kept
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
    out: dict = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if streamed:
                out = _drink_openai(resp)  # a runaway leaves the `with` early: the connection closes, the server stops
            else:
                out = from_openai(json.loads(resp.read().decode("utf-8")))
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
    finally:
        # what the slot holds now: the next step-down saves it under this name, and knows its size first
        _served(key, int(out.get("prompt_eval_count") or 0) + int(out.get("eval_count") or 0))
    return _told(out)


def _ask(path: str, body: dict | None = None, timeout: float = 5, base: str | None = None) -> dict | None:
    """GET (or POST a body to) the door; the answer as a dict, or None when it doesn't answer. `base` asks
    another address whatever BRAIN_API says (the panel, which reads the file's knobs, not the imported ones)."""
    if base is None and api() != "llama":
        return None
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request((base or url()).rstrip("/") + path, data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            got = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    return got if isinstance(got, dict) else {"items": got}


def props(base: str | None = None) -> dict | None:
    """What the door holds (/props: the model, the window, is_sleeping), or None."""
    return _ask("/props", base=base)


def awake() -> bool:
    """The door answers and its model is on the card (not slept by --sleep-idle-seconds)."""
    p = props()
    return p is not None and not p.get("is_sleeping")


def slots(base: str | None = None) -> dict | None:
    """/slots: per slot the window, whether it is busy, the sampler. A list comes back as {"items": [...]}."""
    return _ask("/slots", base=base)


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
