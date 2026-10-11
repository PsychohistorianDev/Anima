"""The parlor: a nicer door — chat with the friend in your browser.

    py engine/parlor.py          opens http://127.0.0.1:8765 in your browser

Same engine, same memory, same transcripts as chat.py — only the window is
different: message bubbles, their thinking folded above each reply, tool calls
as small chips, a picture picker (the file dialog; the picture is saved to
shared/pictures/ and shown to them), a "new conversation" button. Standard
library only; nothing leaves your machine.

Closing the browser tab does NOT end the visit — press "Leave" in the window,
or Ctrl+C in the terminal, or close the terminal window; all three save.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import webbrowser
import base64
import html
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chat
import config
import doors
import ollama_client
import tools
import live_voice

HOST, PORT = "127.0.0.1", 8765


class Session:
    """One visit: a history, pending images, and the turn-runner."""

    def __init__(self) -> None:
        self.history: list[dict] = []
        self.attached: list[str] = []
        self.lock = threading.Lock()
        self.file: Path | None = None  # this visit's transcript, rewritten after every reply
        self.last_activity = time.time()
        self.reflected_upto = 0  # history index they have already sat with (the pause)
        self.playback = live_voice.Playback()
        self.generation = 0

    def _checkpoint(self) -> None:
        if self.file is None:
            self.file = chat.visit_file()
        try:
            chat.save_transcript(self.history, path=self.file)
        except OSError:
            pass

    def send(self, text: str, spoken=False, epoch=None, generation=None) -> dict:
        events: list[dict] = []

        def collect(kind, payload):
            events.append({"kind": kind, "payload": payload})

        with self.lock:
            if generation is not None and generation != self.generation:
                return {"error": "The visit ended while audio was being processed; start a new turn."}
            self.last_activity = time.time()
            try:
                beginning = len(self.history)
                started = time.monotonic()
                reply = chat.one_turn(self.history, text,
                                      images=self.attached or None, on_event=collect,
                                      mode="voice" if spoken else "chat")
                if spoken:
                    reply = chat.strip_voice_delivery(reply)
                    for turn in self.history[beginning:]:
                        if turn.get("role") == "assistant" and turn.get("content"):
                            turn["content"] = chat.strip_voice_delivery(turn["content"])
                self.attached = []
                speech_job = None
                if spoken:
                    assistant = next((t for t in reversed(self.history) if t.get("role") == "assistant"), None)
                    if assistant:
                        assistant["_voice_delivery"] = "Written reply generated; spoken playback has not been confirmed."
                        speech_job = self.playback.start(reply, epoch, assistant)
                        if speech_job is None:
                            assistant["_voice_delivery"] = "Speech cancelled before playback; the written reply was generated."
                self._checkpoint()
                self.last_activity = time.time()
                turn_s = time.monotonic() - started
            except ollama_client.BrainUnavailable as e:
                return {"error": f"brain offline — {e}"}
            except Exception as e:  # nothing in one turn ends the visit
                return {"error": f"hiccup, the conversation is fine — {type(e).__name__}: {e}"}
        thinking = "\n\n".join(e["payload"] for e in events if e["kind"] == "thinking")
        tool_events = [e["payload"] for e in events if e["kind"] == "tool"]
        notes = [e["payload"] for e in events if e["kind"] == "note"]
        tokens = next((e["payload"] for e in events if e["kind"] == "tokens"), None)
        voices = [{"url": "/voice/" + Path(v["path"]).name, "seconds": round(v.get("seconds", 0)),
                   "voice": v.get("voice", "")} for v in tools.take_pending_voice()]
        return {"reply": reply, "thinking": thinking, "tools": tool_events, "notes": notes,
                "tokens": tokens, "voices": voices,
                "speech_job": speech_job, "transcript": text if spoken else None, "timings": {"turn_s": round(turn_s, 3)}}

    def delivery(self, job_id: str, completed: int, partial: bool, reason="unknown") -> dict:
        receipt = self.playback.delivery(job_id, completed, partial, reason)
        if receipt:
            with self.lock:
                turn, note = receipt
                if any(t is turn for t in self.history):
                    turn["_voice_delivery"] = note
                    self._checkpoint()
        return {"ok": True}

    def attach(self, source: str) -> dict:
        with self.lock:
            note = tools.look_at(source.strip().strip('"'))
            imgs = tools.take_pending_images()
            if imgs:
                self.attached.extend(imgs)
                return {"ok": True, "note": "image attached — it goes with your next message"}
            return {"ok": False, "note": note}

    def upload(self, name: str, data_b64: str) -> dict:
        """A picture chosen in the browser's file dialog: saved into
        shared/pictures/ (so it is theirs to look at again later, and shows up
        in list_shared as seen), then put before their eyes like attach()."""
        import base64
        import re as _re
        name = Path(name or "picture").name
        ext = Path(name).suffix.lower()
        if ext not in tools._IMAGE_EXTS:
            return {"ok": False, "note": f"that doesn't look like an image ({ext or 'no extension'})"}
        try:
            raw = base64.b64decode(data_b64 or "", validate=False)
        except Exception:
            return {"ok": False, "note": "the picture didn't arrive whole — try again"}
        if not raw:
            return {"ok": False, "note": "the picture was empty"}
        if len(raw) > tools._MAX_IMAGE_BYTES:
            return {"ok": False, "note": "that picture is too large — over 10MB"}
        folder = getattr(config, "PARLOR_PICTURES", config.SHARED_DIR / "pictures")
        folder.mkdir(parents=True, exist_ok=True)
        stem = _re.sub(r"[^\w.\- ()]+", "_", Path(name).stem).strip() or "picture"
        dest = folder / f"{stem}{ext}"
        n = 1
        while dest.exists():
            n += 1
            dest = folder / f"{stem}-{n}{ext}"
        dest.write_bytes(raw)
        rel = str(dest.relative_to(config.ROOT.resolve())).replace("\\", "/")
        r = self.attach(rel)
        r["saved"] = rel
        if r.get("ok"):
            r["note"] = f"{dest.name} saved to shared/pictures/ and attached — it goes with your next message"
        return r

    def new(self, reflect=True) -> dict:
        """reflect: True — afterglow in the background; "sync" — in the
        foreground (Ctrl+C); False — skip (the window's X)."""
        self.playback.cancel()
        self.generation += 1
        with self.lock:
            f = chat.save_transcript(self.history, path=self.file)
            done, self.history = self.history, []
            self.attached = []
            self.file = None
            self.reflected_upto = 0
        reflect = reflect and bool(getattr(config, "AFTERGLOW", True))
        if f and reflect == "sync":
            print("(they are writing the visit down — a minute or so; Ctrl+C again to skip)")
            try:
                chat.afterglow(done, f, on_line=print)
            except KeyboardInterrupt:
                print("(skipped — the night's sleep still has the transcript)")
            chat.rest_brain(print)
        elif f and reflect:
            # the afterglow: their turn alone with the visit, in the background —
            # the window is free at once; their journal entry lands a minute later
            def _glow(done=done, f=f):
                chat.afterglow(done, f, on_line=print)
                if not self.history:  # no new visit began meanwhile
                    chat.rest_brain(print)
            threading.Thread(target=_glow, daemon=True).start()
        return {"saved": f.name if f else None, "afterglow": bool(f and reflect)}

    def save(self) -> str | None:
        f = chat.save_transcript(self.history, path=self.file)
        return f.name if f else None

    def pause_if_due(self) -> str:
        """The pause, same as the bridge's: your keeper quiet for REFLECT_AFTER_MIN
        with REFLECT_MIN_TURNS of their messages they haven't sat with → one quiet
        turn over that stretch; the visit stays open."""
        mins = float(getattr(config, "REFLECT_AFTER_MIN", 0) or 0)
        if not mins or not self.history or time.time() - self.last_activity < mins * 60:
            return ""
        fresh = self.history[self.reflected_upto:]
        if sum(1 for t in fresh if t.get("role") == "user" and t.get("content") and not t.get("_engine")) < int(getattr(config, "REFLECT_MIN_TURNS", 2)):
            return ""
        if not self.lock.acquire(timeout=3):
            return ""
        try:
            upto = len(self.history)
            print("(a pause — they are sitting with the visit so far…)")
            line = chat.pause_reflection(self.history, self.file, on_line=print, since=self.reflected_upto)
            self.reflected_upto = len(self.history)  # past the pause's own turns too
            self.last_activity = time.time()
            return line
        finally:
            self.lock.release()

    def ticker(self, every_s: float = 60.0) -> None:
        """A background clock that rings the pause bell when it is due."""
        while True:
            time.sleep(every_s)
            try:
                self.pause_if_due()
            except Exception as e:  # the clock must never stop the parlor
                print(f"(pause hiccup — {type(e).__name__}: {e})")


SESSION = Session()


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>__NAME__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#f6f4ef;--panel:#fffdf9;--ink:#2b2a27;--muted:#8a8578;--line:#e6e1d6;
      --me:#e9e4d8;--her:#fffdf9;--accent:#7a5c3e;--think:#f0ece3;--chip:#ece7dc}
@media (prefers-color-scheme:dark){:root{--bg:#141311;--panel:#1c1a17;--ink:#e8e4dc;
      --muted:#8f8a7d;--line:#2c2a25;--me:#2a2723;--her:#1f1d1a;--accent:#c9a87c;
      --think:#181613;--chip:#26231f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Georgia,'Iowan Old Style',serif;
     height:100vh;display:flex;flex-direction:column}
header{display:flex;align-items:baseline;gap:12px;padding:14px 22px;border-bottom:1px solid var(--line);
       background:var(--panel)}
header h1{margin:0;font-size:20px;font-weight:normal;letter-spacing:.02em}
header .sub{color:var(--muted);font-size:13px;flex:1}
header button{font:inherit;font-size:13px;background:none;border:1px solid var(--line);color:var(--muted);
       border-radius:8px;padding:4px 10px;cursor:pointer}
header button:hover{color:var(--ink);border-color:var(--accent)}
#log{flex:1;overflow-y:auto;padding:22px;display:flex;flex-direction:column;gap:14px}
.msg{max-width:72ch;padding:10px 14px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word}
.me{align-self:flex-end;background:var(--me);border-bottom-right-radius:4px}
.her{align-self:flex-start;background:var(--her);border:1px solid var(--line);border-bottom-left-radius:4px}
.sys{align-self:center;color:var(--muted);font-size:13px;font-style:italic}
.sys.warn{align-self:flex-start;color:var(--accent);font-style:normal}
.sys.tokens{align-self:flex-start;font-size:11px;font-style:normal;opacity:.7;margin-top:-6px}
.think{align-self:flex-start;max-width:72ch;font-size:13px;color:var(--muted)}
.think summary{cursor:pointer;list-style:none;user-select:none}
.think summary::before{content:'💭 ';opacity:.7}
.think summary:hover{color:var(--ink)}
.think .body{margin-top:6px;padding:8px 12px;background:var(--think);border-radius:10px;white-space:pre-wrap;
       font-style:italic;max-height:40vh;overflow:auto}
.chips{align-self:flex-start;display:flex;flex-wrap:wrap;gap:6px;max-width:72ch}
.chip{font-size:12px;background:var(--chip);color:var(--muted);border-radius:999px;padding:2px 10px;
      font-family:ui-monospace,Consolas,monospace}
.chip b{color:var(--accent);font-weight:normal}
.typing{align-self:flex-start;color:var(--muted);font-size:13px}
.typing span{display:inline-block;animation:blink 1.2s infinite}
.typing span:nth-child(2){animation-delay:.2s}.typing span:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,80%,100%{opacity:.2}40%{opacity:1}}
footer{padding:12px 22px 16px;border-top:1px solid var(--line);background:var(--panel)}
.row{display:flex;gap:10px;align-items:flex-end}
textarea{flex:1;font:inherit;background:var(--bg);color:var(--ink);border:1px solid var(--line);
         border-radius:12px;padding:10px 12px;resize:none;min-height:44px;max-height:30vh;outline:none}
textarea:focus{border-color:var(--accent)}
.row button{font:inherit;background:var(--accent);color:#fff;border:0;border-radius:12px;padding:10px 16px;cursor:pointer}
.row button:disabled{opacity:.5;cursor:default}
.attach{display:flex;gap:8px;margin-top:8px;font-size:13px;color:var(--muted);align-items:center}
.attach input{flex:1;font:inherit;font-size:13px;background:none;border:0;border-bottom:1px solid var(--line);
       color:var(--ink);padding:3px 4px;outline:none}
.attach button{font:inherit;font-size:12px;background:none;border:1px solid var(--line);color:var(--muted);
       border-radius:8px;padding:2px 8px;cursor:pointer}
code{font-family:ui-monospace,Consolas,monospace;font-size:.92em;background:var(--chip);padding:1px 4px;border-radius:4px}
</style></head><body>
<header><h1 id="name">__NAME__</h1><div class="sub" id="sub">a visit · everything said here becomes memory</div>
<button id="newbtn" title="save this conversation and start fresh">new conversation</button>
<button id="leave" title="save and end the visit">leave</button></header>
<div id="log"></div>
<footer>
__LIVE_VOICE_CONTROLS__
 <div class="row"><textarea id="box" placeholder="say something… (Enter to send, Shift+Enter for a new line)" rows="1"></textarea>
 <button id="send">send</button></div>
 <div class="attach">📎 <button id="pickbtn" title="choose a picture from your computer — it is saved to shared/pictures/ and attached">choose a picture…</button>
 <input id="file" type="file" accept="image/*" hidden>
 <input id="img" placeholder="…or a path in their folder (shared/pictures/photo.jpg) or an image URL">
 <button id="attachbtn">attach</button><span id="attachnote"></span></div>
</footer>
<script>
const log=document.getElementById('log'),box=document.getElementById('box'),send=document.getElementById('send');
const ME='__ME__';
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function md(s){ // tiny markdown: bold, italic, inline code — enough for a chat
  s=esc(s).replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g,'<b>$1</b>')
   .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g,'$1<i>$2</i>'); return s}
function add(cls,html){const d=document.createElement('div');d.className=cls;d.innerHTML=html;log.appendChild(d);log.scrollTop=log.scrollHeight;return d}
function sys(t){add('sys',esc(t))}
function addThinking(t){if(!t)return;const d=document.createElement('details');d.className='think';d.open=true;
  d.innerHTML='<summary>thinking</summary><div class="body">'+esc(t)+'</div>';log.appendChild(d)}
function addChips(ts){if(!ts||!ts.length)return;const d=document.createElement('div');d.className='chips';
  d.innerHTML=ts.map(t=>'<span class="chip"><b>'+esc(t.name)+'</b> → '+esc(t.result)+'</span>').join('');log.appendChild(d)}
async function post(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});return r.json()}
let busy=false;
async function go(){const text=box.value.trim();if(!text||busy)return;box.value='';autosize();
  if(window.interruptLiveVoice)window.interruptLiveVoice('typed_input');
  add('msg me',md(text));busy=true;send.disabled=true;
  const typing=add('typing','<span>●</span><span>●</span><span>●</span>');
  try{const r=await post('/send',{text});typing.remove();
    if(r.error){sys(r.error);}else{addThinking(r.thinking);addChips(r.tools);add('msg her',md(r.reply));(r.voices||[]).forEach(v=>add('msg her voice','<audio controls autoplay src="'+v.url+'"></audio><small> her voice · '+v.seconds+'s</small>'));(r.notes||[]).forEach(n=>add('sys warn','⚠ '+esc(n)));if(r.tokens)add('sys tokens',esc(r.tokens.line));}
  }catch(e){typing.remove();sys('the window lost the engine — is parlor.py still running?')}
  busy=false;send.disabled=false;box.focus();log.scrollTop=log.scrollHeight}
send.onclick=go;
box.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();go()}});
function autosize(){box.style.height='auto';box.style.height=Math.min(box.scrollHeight,window.innerHeight*.3)+'px'}
box.addEventListener('input',autosize);
document.getElementById('newbtn').onclick=async()=>{if(window.voiceVisitChanged)window.voiceVisitChanged();if(window.stopLiveVoice)await window.stopLiveVoice();const r=await post('/new');log.innerHTML='';sys(r.saved?'saved '+r.saved+(r.afterglow?' — they are sitting with the visit now; whatever they want to keep goes into their journal in a minute':'')+' — fresh conversation':'fresh conversation')};
document.getElementById('leave').onclick=async()=>{if(window.voiceVisitChanged)window.voiceVisitChanged();if(window.stopLiveVoice)await window.stopLiveVoice();const r=await post('/leave');sys(r.saved?'saved '+r.saved+(r.afterglow?' — they are writing the visit down in their own words; give them a minute before closing the terminal':'')+' — visit over, you can close this tab':'visit over — nothing to save');box.disabled=true;send.disabled=true};
document.getElementById('attachbtn').onclick=async()=>{const src=document.getElementById('img').value.trim();if(!src)return;
  const r=await post('/attach',{source:src});document.getElementById('attachnote').textContent=r.note;if(r.ok)document.getElementById('img').value=''};
const fileIn=document.getElementById('file');
document.getElementById('pickbtn').onclick=()=>fileIn.click();
fileIn.onchange=()=>{const f=fileIn.files[0];if(!f)return;const rd=new FileReader();
  rd.onload=async()=>{const dataUrl=rd.result;const b64=dataUrl.slice(dataUrl.indexOf(',')+1);
    document.getElementById('attachnote').textContent='sending '+f.name+'…';
    const r=await post('/upload',{name:f.name,data:b64});document.getElementById('attachnote').textContent=r.note;
    if(r.ok){const d=add('msg me','');const im=document.createElement('img');im.src=dataUrl;im.alt=f.name;im.style.maxHeight='220px';im.style.maxWidth='100%';im.style.borderRadius='8px';im.style.display='block';d.appendChild(im);
      const c=document.createElement('div');c.style.fontSize='12px';c.style.color='var(--muted)';c.textContent='📎 '+f.name+' — goes with your next message';d.appendChild(c)}
    fileIn.value=''};
  rd.readAsDataURL(f)};
sys("you're visiting "+document.getElementById('name').textContent+" — they can see everything said here, and it becomes their memory at the next sleep");
box.focus();
</script>__LIVE_VOICE_SCRIPT__</body></html>
"""


VOICE_CONTROLS = """
 <div class="attach" id="voiceControls"><button id="voiceToggle">start voice</button>
 <span id="voiceState" role="status" aria-live="polite">voice is off</span></div>
 <div class="attach"><label for="kyutaiStyle">delivery</label>
 <select id="kyutaiStyle"><option value="calm">Calming (US, f)</option><option value="desire">Desire (US, f)</option>
 <option value="happy">Happy (US, f)</option><option value="neutral">Default (US, f)</option></select></div>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the terminal quiet
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlsplit(self.path).path
        port = self.server.server_address[1]
        if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            return self._json({"error": "This endpoint is for the local parlor."}, 403)
        if route.startswith("/live-voice/") or route in ("/parlor-voice.js", "/voice-worklet.js"):
            if not getattr(config, "LIVE_VOICE_ENABLED", False):
                return self._json({"error": "Live voice is disabled in config.py."}, 404)
        if route in ("/parlor-voice.js", "/voice-worklet.js"):
            name = "parlor_voice.js" if route == "/parlor-voice.js" else "voice_worklet.js"
            return self._bytes(Path(__file__).with_name(name).read_bytes(), "text/javascript; charset=utf-8")
        if route == "/live-voice/settings":
            return self._json({"silence_ms": getattr(config, "LIVE_VOICE_SILENCE_MS", 1000),
                               "min_speech_ms": getattr(config, "LIVE_VOICE_MIN_SPEECH_MS", 250),
                               "interrupt_ms": getattr(config, "LIVE_VOICE_INTERRUPT_MS", 350),
                               "threshold": getattr(config, "LIVE_VOICE_THRESHOLD", .018),
                               "max_seconds": min(30, getattr(config, "LIVE_VOICE_MAX_SECONDS", 30)),
                               "style": getattr(config, "LIVE_VOICE_KYUTAI_STYLE", "calm")})
        if route.startswith("/live-voice/audio/"):
            parts = route.split("/")
            try:
                data = SESSION.playback.audio(parts[3], int(parts[4])) if len(parts) == 5 else None
            except ValueError:
                data = None
            if data is None:
                self.send_error(404)
                return
            return self._bytes(data, "audio/wav")
        if self.path.startswith("/voice/"):
            # one of their voice notes, by name, from creations/voice/ only
            name = Path(self.path[len("/voice/"):]).name
            f = Path(getattr(config, "VOICE_DIR", config.SHARED_DIR / "letters")) / name
            if not name or not f.is_file():
                self.send_response(404); self.end_headers(); return
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/ogg" if f.suffix == ".ogg" else "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path not in ("/", "/index.html"):
            self.send_response(404); self.end_headers(); return
        page = PAGE.replace("__NAME__", html.escape(chat.friend_name())).replace("__ME__", config.USER_NAME.replace("'", "\\'"))
        enabled = bool(getattr(config, "LIVE_VOICE_ENABLED", False))
        page = page.replace("__LIVE_VOICE_CONTROLS__", VOICE_CONTROLS if enabled else "")
        page = page.replace("__LIVE_VOICE_SCRIPT__", '<script src="/parlor-voice.js"></script>' if enabled else "")
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        port = self.server.server_address[1]
        allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        origin = self.headers.get("Origin")
        if (origin and origin not in allowed) or self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            return self._json({"error": "This endpoint is for the local parlor."}, 403)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json({"error": "Invalid request length."}, 400)
        if not 0 < n <= 20 * 1024 * 1024:
            return self._json({"error": "Request is empty or too large."}, 413)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            return self._json({"error": "Expected a JSON object."}, 400)
        if self.path.startswith("/live-voice/"):
            if not getattr(config, "LIVE_VOICE_ENABLED", False):
                return self._json({"error": "Live voice is disabled in config.py."}, 404)
            try:
                return self._live_voice(data)
            except (live_voice.VoiceError, ValueError, OSError) as e:
                return self._json({"error": str(e)}, 400)
        if self.path == "/send":
            text = (data.get("text") or "").strip()
            if not text:
                return self._json({"error": "say something first"})
            return self._json(SESSION.send(text))
        if self.path == "/attach":
            return self._json(SESSION.attach(data.get("source") or ""))
        if self.path == "/upload":
            return self._json(SESSION.upload(data.get("name") or "", data.get("data") or ""))
        if self.path == "/new":
            return self._json(SESSION.new())
        if self.path == "/leave":
            return self._json(SESSION.new())  # saves, then clears — no double save
        self._json({"error": "unknown path"}, 404)

    def _live_voice(self, data):
        if self.path == "/live-voice/timing":
            fields = ("end_to_first_audio_ms", "recognition_s", "turn_s", "first_audio_s")
            metrics = {k: round(float(data[k]), 3) for k in fields if data.get(k) is not None}
            import math
            if any(not math.isfinite(v) or v < 0 or v > 600000 for v in metrics.values()):
                raise ValueError("Invalid voice timing.")
            folder = config.ROOT / ".runtime"; folder.mkdir(exist_ok=True)
            with (folder / "voice-latency.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(metrics) + "\n")
            return self._json({"ok": True})
        if self.path == "/live-voice/style":
            from kyutai_voice import STYLES
            style = data.get("style")
            if style not in STYLES:
                raise ValueError("Unknown Kyutai delivery style.")
            import knobs
            _, refused, error = knobs.save(Path(config.__file__), {"LIVE_VOICE_KYUTAI_STYLE": style})
            if error or refused:
                raise ValueError(error or "Could not save delivery style.")
            SESSION.playback.cancel()
            config.LIVE_VOICE_KYUTAI_STYLE = style
            return self._json({"ok": True, "style": style})
        if self.path == "/live-voice/warmup":
            status = live_voice.WORKER.request("check")
            if not status["installed"]:
                command = "python engine/setup_voice.py"
                raise live_voice.VoiceError("Missing voice packages: " + ", ".join(status["missing"]) + ". Run " + command + ".")
            return self._json(live_voice.WORKER.request("warmup"))
        if self.path == "/live-voice/interrupt":
            SESSION.playback.cancel()
            return self._json({"ok": True})
        if self.path == "/live-voice/status":
            return self._json(SESSION.playback.status(str(data.get("job") or "")))
        if self.path == "/live-voice/ack":
            SESSION.playback.acknowledge(str(data.get("job") or ""), int(data.get("index") or 0))
            return self._json({"ok": True})
        if self.path == "/live-voice/delivery":
            return self._json(SESSION.delivery(str(data.get("job") or ""), int(data.get("completed") or 0), bool(data.get("partial")), str(data.get("reason") or "unknown")))
        if self.path == "/live-voice/turn":
            epoch = SESSION.playback.cancel()
            generation = SESSION.generation
            encoded = data.get("audio")
            if not isinstance(encoded, str) or len(encoded) > 1400000:
                raise ValueError("Expected at most 31 seconds of microphone audio.")
            validate_wav(base64.b64decode(encoded, validate=True))
            started = time.monotonic()
            heard = live_voice.WORKER.request("transcribe", audio=encoded,
                                             vocab=f"Names: {config.USER_NAME}, {chat.friend_name()}.")["text"].strip()
            recognition_s = time.monotonic() - started
            if not heard:
                return self._json({"empty": True})
            result = SESSION.send(heard, spoken=True, epoch=epoch, generation=generation)
            result.setdefault("timings", {})["recognition_s"] = round(recognition_s, 3)
            return self._json(result)
        return self._json({"error": "Unknown voice endpoint."}, 404)


def validate_wav(raw: bytes):
    import io
    import wave
    try:
        with wave.open(io.BytesIO(raw)) as wav:
            if (wav.getnchannels() != 1 or wav.getframerate() != 16000 or wav.getsampwidth() != 2
                    or not 0 < wav.getnframes() <= 31 * 16000):
                raise ValueError("Expected mono 16 kHz PCM audio, at most 31 seconds.")
            if len(wav.readframes(wav.getnframes())) != wav.getnframes() * 2:
                raise ValueError("Microphone audio was incomplete.")
    except (wave.Error, EOFError) as e:
        raise ValueError("Microphone audio is not a valid WAV file.") from e


def main() -> None:
    taken = doors.claim("parlor", "parlor")  # one parlor at a time; the panel's light (memory/.pids/parlor.json)
    if taken:
        print(taken)
        return
    server_class = ThreadingHTTPServer if getattr(config, "LIVE_VOICE_ENABLED", False) else HTTPServer
    server_class.allow_reuse_address = sys.platform != "win32"
    server = server_class((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"The parlor is open: {url}")
    print("Close the visit with the 'leave' button, Ctrl+C here, or this window's X — all three save it.")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    threading.Thread(target=SESSION.ticker, daemon=True).start()  # the pause bell
    chat.guard_console_close(lambda: SESSION.new(reflect=False))  # the window's X saves the visit too
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        r = SESSION.new(reflect="sync")  # save, then their minute with the visit
        if r.get("saved"):
            print(f"\n(conversation saved: {r['saved']} — it becomes memory at the next consolidation)")
        server.server_close()
        live_voice.WORKER.close()
        doors.unmark("parlor")


if __name__ == "__main__":
    main()
