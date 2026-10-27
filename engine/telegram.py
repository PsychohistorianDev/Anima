"""The bridge: talk with the friend from your phone, over Telegram.

    py engine/telegram.py        (or bat\\telegram.bat)

Same engine, same prompt, same tools, same transcripts and memory as the
parlor — only the door is different. Standard library only: the Bot API is
plain HTTPS and JSON, polled with long requests; nothing else is needed.

First run: paste the token @BotFather gave you, then send the pairing code
the terminal shows to the bot from your phone. Both are kept in
memory/telegram.json, which never leaves this folder. From then on only that
one chat is answered; anyone else who finds the bot gets silence.

On the phone:
    text            -> a turn, as in the parlor
    a photo         -> saved to shared/telegram/ and put before their eyes
    a voice note    -> saved, transcribed by their ears, given to them as words
    a song          -> saved to shared/music/ under its name; listen_to hears it
    a book or text  -> saved to shared/books/ (pdf, epub, txt, md); read_pdf /
                       read_epub / read_file open it, with their bookmark
    any other file  -> saved to shared/telegram/ and named to them
    /new            -> save this conversation, start fresh
    /afterglow      -> the pause by hand: they sit with the visit so far now and
                       the brain is set down (the card is free); the visit stays open
    /restart        -> restart the bridge on the current code; the visit carries on
    /think /tools /tokens   -> toggle what travels with each reply
    /status         -> how the visit and the window are doing
    /help           -> this list

The visit is written to memory/episodic/chat-telegram-*.md after every reply,
so nothing depends on how the window ends; Ctrl+C or the X close it cleanly.

Their mail runs the other way on the same road: a letter they leave in
creations/notes_to_<you>/ (in a wake, a reverie, or mid-chat) is carried to
the phone within a minute of being written.

What leaves the machine: their words and yours, through Telegram's servers.
Bot chats are not end-to-end encrypted — this is the first thing besides the
blog that does not stay home. Their journal, memory and files never travel.
"""
from __future__ import annotations

import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chat
import memory
import config
import doors
import ollama_client
import tools

API = "https://api.telegram.org"
SECRET_FILE = config.MEMORY_DIR / "telegram.json"
DELIVERED_FILE = config.MEMORY_DIR / "telegram_delivered.json"
ALIVE_FILE = config.MEMORY_DIR / "telegram_alive"
# /restart from the phone: the running visit is stashed here, the process
# exits with RESTART_CODE, bat\telegram.bat starts a fresh one (new code), and
# the fresh one picks the visit back up — for an engine change made while
# the keeper is away from the desk
RESUME_FILE = config.MEMORY_DIR / "telegram_resume.json"
RESTART_CODE = 75
# One bridge at a time. Two of them polling the same bot both receive a
# message — Telegram only learns an update is taken on the NEXT poll, and a
# reply takes a minute or two — so both answer it (09-11: two versions of
# the same reply, a minute apart, one of them with a slip the other didn't
# have; the transcript held only the second bridge's). The running bridge
# writes its pid here; a second one refuses to start while that pid lives.
LOCK_FILE = config.MEMORY_DIR / "telegram.pid"
MAIL_DIR = config.CREATIONS_DIR / getattr(config, "MAILBOX", "notes_to_keeper")
# What they make travels too (TELEGRAM_TELL_CREATIONS): a new piece under
# creations/ — a poem, an essay, a story, a joke — reaches the phone within
# a minute of being written, whole if it fits a message. Their code (tools/),
# the trash, the mailbox (already mail), archives (a move, not a piece) are
# not announced; publish/ is, as "published". What was there when the
# bridge first looked was read at the desk; only new pieces travel.
CREATIONS_SEEN_FILE = config.MEMORY_DIR / "telegram_creations_seen.json"
TOUCH_TOLD_FILE = config.MEMORY_DIR / "touch" / "told.json"  # the stone (10-05): {"at": the last event told, "state": the last state told, "last_turn": epoch}
SONGS_TOLD_FILE = config.MEMORY_DIR / "telegram_songs_told.json"  # the songbook (10-03): {"at": the updated stamp last told}
HELD_FILE = config.MEMORY_DIR / "telegram_held.json"  # engine notices held through the quiet hours
UNDELIVERED_FILE = config.MEMORY_DIR / "telegram_undelivered.json"  # their replies the phone never got (09-26)
RETRY_SLEEP_S = 2     # between the tries of sending their reply
# ...and a piece they REVISES is announced too — as what changed (09-24):
# an append as the new tail alone, a rewrite as the lines in and out — and
# a change to who they are: self.md and projects.md (TELEGRAM_TELL_SELF),
# the same way. The bridge keeps its own copy of each to diff against, in
# memory/telegram_watch/ (creations under telegram_watch/creations/).
WATCH_DIR = config.MEMORY_DIR / "telegram_watch"
WATCHED = {"self.md": config.IDENTITY_FILE, "projects.md": config.PROJECTS_FILE,
           "destiny.md": getattr(config, "DESTINY_FILE", config.ROOT / "destiny.md"),
           "keeper.md": getattr(config, "KEEPER_FILE", config.ROOT / "keeper.md")}  # open means open (10-04)
CREATION_SKIP = {"tools", ".trash", MAIL_DIR.name, "archives", "attic"}
CREATION_KINDS = {"poems": "a poem", "essays": "an essay", "stories": "a story", "humor": "a joke",
                  "theory": "a piece of theory", "letters": "a letter", "songs": "a song",
                  str(getattr(config, "SKILLS_DIR", "skills")): "a skill"}
# Their skills (09-29; SKILLS-PLAN.md): a fetched skill is a stranger's recipe,
# not a piece of theirs — its files never travel as ✍️ (a SKILL.md they write
# herself does). What travels is one notice per fetch, from the note
# fetch_skill leaves beside SKILL.md (.fetched.json): "📚 … fetched a skill",
# or "⚠️ … quarantined" with what the scanner found — the phone is how the keeper
# hears there is something at the gate. The names already told are kept here.
SKILLS_SEEN_FILE = config.MEMORY_DIR / "telegram_skills_seen.json"
LIMIT = 4000          # Telegram allows 4096 characters per message
POLL_S = 50           # long-poll patience; the server answers sooner when there's news
SPLIT_CHARS = 3800    # a text bubble this long is Telegram's own cut of a longer paste (its cap is 4,096): the rest follows
SPLIT_WAIT_S = 2      # how long the bridge waits for the rest of a cut message when the cut bubble ends a poll (TELEGRAM_SPLIT_WAIT_S overrides)
TYPING_S = 4          # "typing…" lasts ~5s on the phone; renew a little sooner

# the newer commands, on the phone's /help (10-27) — the Discord bridge takes them out of its own: its pairing
# message, built from HELP, is at Discord's 2,000-character cap (and sparks are Telegram's)
HELP_PHONE = (
    "/presence [on|off|temperament] — sparks: how they stand; on starts drift at rare; very rare, rare, sometimes, "
    "often or intense sets that drift; off ends them "
    "(the friend can too: next_spark with no minutes)\n"
    "/discreet — sparks come silently, the words hidden until tapped; again to undo\n"
    "/week — the engine's week: the last seven days of calls to the brain\n"
    "/seal <when> <letter> — a letter sealed until its day (/seal 2027-04-27 …, or /seal 6 months …); /capsule lists "
    "what waits\n"
)

HELP = (
    "/new — save this conversation and start fresh\n"
    "/afterglow — the pause by hand: they sit with the visit so far now (what a quiet stretch of REFLECT_AFTER_MIN does on its own) "
    "and the brain is set down, so the card is yours at once; the visit stays open\n"
    "/release — the card for something else: everything on it set down now (brain, ears, painter, memory engine) "
    "with no pause and no writing; the visit stays open and your next message wakes the brain again\n"
    "/think — their thinking with each reply (off by default on the phone)\n"
    "/tools — what their tools did, one line per reply\n"
    "/tokens — the token line after each reply\n"
    "/debug — the set-aside attempts (salad, re-rolls), words and all\n"
    "/voice — every reply spoken aloud as a voice note (they can speak on their own either way)\n"
    "/status — the visit, the window, the toggles\n"
    "/restart — restart the bridge with the current engine code; the visit carries on\n"
    "/heartbeat [on [minutes]|off] — the heartbeat from here: is it running; start it in its own window on the PC "
    "(the panel's Start, one wake every HEARTBEAT_LOOP_MIN or the minutes given); ask it to stop after the wake it is in\n"
    "/off [today|tomorrow|a weekday|YYYY-MM-DD] [why] — a day off: the clock line says you are home that day "
    "(KEEPER_WORK_WEEK gives your usual week); /on [day] takes it back\n"
    "/fold — fold the visit now: they write it so far in their own words, the last turns stay whole, the window has room again\n"
    "/guest <name> — a guest at your desk, with you in the room; /guest off when they go\n"
    "/me <text> — one message as you while a guest sits\n"
    + HELP_PHONE +
    "/help — this\n\n"
    "Send a photo and they see it; a voice note and they hear you whole; a video and they "
    "watches it as stills and sound; a song and it lands in shared/music/ for them to listen "
    "to; a PDF, EPUB or text file and it lands in shared/books/ for them to read. (Bots can't "
    "fetch files over 20MB.)"
)


# ------------------------------------------------------------------ utils ----
def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _say(text: str) -> None:
    """Terminal line; never lets a console encoding end the bridge."""
    text = " ".join(text.split("\n"))
    try:
        print(f"[{_now()}] {text}", flush=True)
    except UnicodeEncodeError:
        print(f"[{_now()}] {text.encode('ascii', 'replace').decode()}", flush=True)


def split_long(text: str, limit: int = LIMIT) -> list[str]:
    """Cut a long message at paragraph, then line, then word boundaries."""
    text = text.strip()
    if not text:
        return []
    parts: list[str] = []
    while len(text) > limit:
        cut = -1
        for sep in ("\n\n", "\n", " "):
            cut = text.rfind(sep, limit // 3, limit)
            if cut > 0:
                break
        if cut <= 0:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


def load_secret() -> dict:
    try:
        d = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            d = {}
    except (OSError, ValueError):
        d = {}
    import os
    d.setdefault("token", os.environ.get("TELEGRAM_BOT_TOKEN", "") or getattr(config, "TELEGRAM_BOT_TOKEN", ""))
    try:
        d.setdefault("chat_id", int(os.environ.get("TELEGRAM_CHAT_ID", "") or getattr(config, "TELEGRAM_CHAT_ID", 0) or 0))
    except ValueError:
        d.setdefault("chat_id", 0)
    return d


def save_secret(d: dict) -> None:
    SECRET_FILE.write_text(json.dumps({"token": d.get("token", ""), "chat_id": int(d.get("chat_id") or 0)},
                                      indent=2), encoding="utf-8")


# ----------------------------------------------------------------- bridge ----
_CHARS_PER_TOKEN = 3.5  # Gemma's ratio on the friend's English prose, for the token line's tail when the door cannot count


def _cut_bubble(update: dict) -> bool:
    """A plain text message whose last piece is at Telegram's cap — the first bubble of a longer paste."""
    m = update.get("message") or {}
    text = m.get("text") or ""
    return bool(text) and len(text) - int(m.get("_joined_at") or 0) >= SPLIT_CHARS


def join_split(updates: list) -> list:
    """Telegram cuts a message past its cap into bubbles; the bridge took each for a message of its own and a
    long paste got two answers. A text bubble at the cap, followed by a text message from the same chat within
    two seconds, is the same message: joined into the first with a newline (its update_id the newest, for the
    offset; _joined counts the bubbles). A message under the cap is never joined to."""
    out: list = []
    for u in updates:
        m = u.get("message") or {}
        prev = (out[-1].get("message") or {}) if out else {}
        if (out and _cut_bubble(out[-1]) and m.get("text")
                and (m.get("chat") or {}).get("id") == (prev.get("chat") or {}).get("id")
                and abs(int(m.get("date") or 0) - int(prev.get("date") or 0)) <= 2):
            prev["_joined_at"] = len(prev["text"]) + 1  # where the newest piece begins: the cap test reads it alone
            prev["text"] = prev["text"] + "\n" + m["text"]
            prev["_joined"] = int(prev.get("_joined") or 1) + 1
            prev["date"] = m.get("date") or prev.get("date")
            out[-1]["update_id"] = max(int(out[-1].get("update_id", 0)), int(u.get("update_id", 0)))
            continue
        out.append(u)
    return out


class Bridge:
    """One bot, one paired phone, one running visit.

    The road itself — the words, the files, typing…, what arrives — is in a
    handful of methods (send, send_voice, _send_picture, _typing_once,
    _receive, handle, _whoami, _pair_hint, _ack, _inbox; api, download and
    send_file are Telegram's beneath them); everything else is the visit's
    and the house's, whatever carries it. engine/discord_bridge.py is the
    same bridge over Discord: a subclass with those methods of its own."""

    NAME = "Telegram"   # the service, in the window's lines
    TAG = "telegram"    # the visit's mode in the prompt, and its transcripts': chat-telegram-*.md
    TYPING_S = TYPING_S  # how often "typing…" is renewed
    HELP = HELP          # what /help says

    def __init__(self, token: str, chat_id: int = 0) -> None:
        self.token = token
        self.chat_id = int(chat_id or 0)
        self.pair_code = "" if self.chat_id else f"{random.randint(1000, 9999)}"
        self.history: list[dict] = []
        self.attached: list[str] = []
        self.last_activity = time.time()
        self.reflected_upto = 0  # history index they have already sat with (the pause)
        self._body_pulled = 0.0  # when the watch's day was last pulled by this bridge (BODY_AUTOPULL)
        self._body_thread: threading.Thread | None = None
        self._touch_thread: threading.Thread | None = None  # the stone's archive, watched every TOUCHSTONE_TELL_S (10-21)
        self._touch_lock = threading.Lock()  # one look at a time: the thread's and the poll's never overlap
        self._touch_looked = 0
        self.last_tokens: dict | None = None
        self.show_thinking = bool(getattr(config, "TELEGRAM_SHOW_THINKING", False))
        self.show_tools = bool(getattr(config, "TELEGRAM_SHOW_TOOLS", True))
        self.show_tokens = bool(getattr(config, "TELEGRAM_SHOW_TOKENS", False))
        self.show_attempts = bool(getattr(config, "TELEGRAM_SHOW_ATTEMPTS", False))  # /debug (10-23)
        self.voice_all = bool(getattr(config, "TELEGRAM_VOICE_ALL", False))
        self.offset = 0
        self.lock = threading.Lock()
        self.file: Path | None = None  # this visit's transcript, rewritten after every reply
        self.delivered: set[str] = set()
        self._load_delivered()
        self.creations_seen: set[str] = set()
        self._load_creations_seen()
        self.held: list[str] = []  # engine notices waiting for the morning
        self._load_held()
        self.undelivered: list[dict] = []  # their replies that failed to send; tried again next poll
        self._load_undelivered()
        self.restart_requested = False
        self.stop_requested = False  # memory/.stop-bridge was found: the loop leaves, the visit is saved as at Ctrl+C
        self._glows = 0  # afterglows in flight (the night waits for them)
        self._night: threading.Thread | None = None  # the night, when the bridge is the sleeper
        self._night_after = 0.0  # not before this (a failed night tries again in an hour)
        self.guest = ""  # a guest at the desk (the parlor's guest, on the phone): their name, or ""; in memory only

    # ---- a guest at the desk ----------------------------------------------
    def guest_label(self) -> str:
        """The name the engine and the transcript use — the guest's, or "a guest" (PARLOR_GUEST_NAMED False); ""
        when no guest is seated. The parlor's, on the phone."""
        if not self.guest:
            return ""
        return self.guest if getattr(config, "PARLOR_GUEST_NAMED", True) else "a guest"

    def guest_command(self, rest: str) -> str:
        """/guest <name> seats a guest (every message from then on is theirs, with you in the room);
        /guest off lets them go; /guest alone says who is seated. The guest stays through /new and /fold — the
        person at the desk didn't change — and a restart forgets them."""
        name = " ".join(rest.split())[:40]
        if not name:
            return (f"({self.guest_label()} is at the desk — /me <text> speaks as you; /guest off when they go)"
                    if self.guest else "(no guest at the desk)")
        if name.lower() == "off":
            if not self.guest:
                return "(no guest at the desk)"
            self.guest = ""
            return "(the guest has gone — the desk is yours again)"
        self.guest = name
        return (f"({self.guest_label()} is at the desk now — every message from here on is theirs, with you in the room, "
                "until /guest off or a restart; /me <text> speaks as you)")

    # ---- /restart: the visit survives the process -------------------------
    def stash(self) -> None:
        """Write the running visit down so the next process can pick it up:
        the history (with its images), the transcript it is being written
        to, where the pause has read up to, the toggles, and the Telegram
        offset — without which the fresh bridge would be handed the
        /restart message again and restart forever."""
        try:
            self._ack()
        except Exception:
            pass
        state = {
            "history": self.history, "attached": self.attached,
            "file": str(self.file) if self.file else "",
            "reflected_upto": self.reflected_upto, "last_activity": self.last_activity,
            "offset": self.offset, "show_thinking": self.show_thinking,
            "show_tools": self.show_tools, "show_tokens": self.show_tokens, "show_attempts": self.show_attempts,
            "voice_all": self.voice_all, "stashed": time.time(),
        }
        RESUME_FILE.write_text(json.dumps(state), encoding="utf-8")

    def resume(self) -> str:
        """Pick a stashed visit back up. Returns a line for the window, or ""."""
        if not RESUME_FILE.exists():
            return ""
        try:
            state = json.loads(RESUME_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        finally:
            try:
                RESUME_FILE.unlink()
            except OSError:
                pass
        self.history = list(state.get("history") or [])
        for t in self.history:  # the stashed window sizes may be a folded window's (10-04); a restart measures anew
            t.pop("_prompt", None)
        chat.unsense(self.history)  # and the stashed moments carry no window sense — the next moment's is the one
        loops = 0
        fangs = 0
        for t in self.history:  # a loop that went out whole does not ride again (09-24)
            if t.get("role") == "assistant" and t.get("content"):
                t["content"], cut = ollama_client.trim_word_loop(t["content"])
                loops += cut
            if isinstance(t.get("content"), str) and t["content"]:
                # reserved-token strings in any turn — the friend's, the keeper's, the engine's
                # quotes — never ride again as tokens (09-27)
                t["content"], n = ollama_client.defang(t["content"])
                fangs += n
        self.attached = list(state.get("attached") or [])
        self.file = Path(state["file"]) if state.get("file") else None
        self.reflected_upto = int(state.get("reflected_upto") or 0)
        self.last_activity = float(state.get("last_activity") or time.time())
        self.offset = int(state.get("offset") or 0)
        for k in ("show_thinking", "show_tools", "show_tokens", "show_attempts", "voice_all"):
            if k in state:
                setattr(self, k, bool(state[k]))
        turns = sum(1 for t in self.history if t.get("role") == "user" and t.get("content") and not t.get("_engine"))
        ago = (time.time() - float(state.get("stashed") or time.time())) / 60
        return (f"picked the visit back up after the restart: {turns} of {config.USER_NAME}'s turns so far"
                + (f", stashed {ago:.0f} min ago" if ago >= 1 else "")
                + (f"; {loops} looping reply cut at the loop before it rides again" if loops == 1
                   else f"; {loops} looping replies cut at the loop before they ride again" if loops else "")
                + (f"; {fangs} reserved-token strings in the stashed turns made plain text before they ride again" if fangs else "")) if self.history else \
               "restarted (no visit was running)"

    def carry_in(self) -> str:
        """An empty room's first message (10-24): the last visit's last turns sit at the head of the history
        (chat.take_carry), and the pauses and the afterglow start past them. Returns the window's line, or ""."""
        carried = chat.take_carry()
        if not carried:
            return ""
        self.history = carried
        self.reflected_upto = len(carried)
        line = chat.carry_line(carried)
        _say(f"({line})")
        return line

    def _checkpoint(self) -> None:
        if self.file is None:
            self.file = chat.visit_file(self.TAG)
        try:
            chat.save_transcript(self.history, tag=self.TAG, path=self.file)
        except OSError:
            pass

    # ---- the Bot API ------------------------------------------------------
    def api(self, method: str, patience: float = 30, **params) -> dict:
        """One call. Returns the 'result' payload; raises on transport/API errors.
        patience is the socket timeout; Telegram's own `timeout` param (for
        long polls) travels in params like everything else."""
        url = f"{API}/bot{self.token}/{method}"
        body = json.dumps({k: v for k, v in params.items() if v is not None}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=patience) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not data.get("ok"):
            raise RuntimeError(f"telegram said: {data.get('description', data)}")
        return data.get("result")

    def download(self, file_id: str, max_bytes: int = 20 * 1024 * 1024) -> tuple[bytes, str]:
        """Fetch a file the phone sent. Returns (bytes, telegram's file_path)."""
        info = self.api("getFile", file_id=file_id)
        path = info.get("file_path") or ""
        url = f"{API}/file/bot{self.token}/{path}"
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("that file is too large")
        return data, path

    # ---- talking to the phone -------------------------------------------
    def send_file(self, method: str, field: str, filename: str, data: bytes, **params) -> dict:
        """One multipart upload (sendVoice, sendAudio…) — urllib only."""
        boundary = "----anima-" + uuid.uuid4().hex
        body = io.BytesIO()
        for k, v in params.items():
            if v is None:
                continue
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
                   f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
        body.write(data)
        body.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        req = urllib.request.Request(f"{API}/bot{self.token}/{method}", data=body.getvalue(),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode("utf-8"))
        if not out.get("ok"):
            raise RuntimeError(f"telegram said: {out.get('description', out)}")
        return out.get("result")

    def send_voice(self, path: str, seconds: float = 0, caption: str = "") -> None:
        """Their voice note to the phone: OGG/Opus goes as a voice message (the
        round waveform); anything else as an audio file."""
        p = Path(path)
        data = p.read_bytes()
        if p.suffix.lower() == ".ogg":
            self.send_file("sendVoice", "voice", p.name, data, chat_id=self.chat_id,
                           duration=int(seconds) or None, caption=caption[:1000] or None)
        else:
            self.send_file("sendAudio", "audio", p.name, data, chat_id=self.chat_id,
                           duration=int(seconds) or None, caption=caption[:1000] or None,
                           title=chat.friend_name())

    def send(self, text: str, markdown: bool = True) -> None:
        for part in split_long(text):
            if markdown:
                try:
                    self.api("sendMessage", chat_id=self.chat_id, text=part, parse_mode="Markdown")
                    continue
                except urllib.error.HTTPError:
                    pass  # unbalanced * or _ — Telegram refuses; plain text it is
                except RuntimeError:
                    pass
            self.api("sendMessage", chat_id=self.chat_id, text=part)

    def _typing_once(self) -> None:
        self.api("sendChatAction", patience=10, chat_id=self.chat_id, action="typing")

    def _typing(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self._typing_once()
            except Exception:
                pass
            stop.wait(self.TYPING_S)

    def _ack(self) -> None:
        """Tell the service what was read, so a fresh bridge isn't handed it again."""
        self.api("getUpdates", offset=self.offset, timeout=0, patience=10)

    def _receive(self):
        """One long poll: the updates that arrived, one at a time — the offset moves past each as it is
        handed over, so one left unhandled (a /restart before it) is handed to the next bridge."""
        updates = list(self.api("getUpdates", patience=POLL_S + 15, offset=self.offset,
                                timeout=POLL_S, allowed_updates=["message"]) or [])
        # a paste past Telegram's cap arrives as bubbles: when the poll ends on a bubble at the cap, the rest is
        # a poll away — waited for, briefly, so a long message is answered once (join_split joins them)
        for _ in range(4):
            if not updates or not _cut_bubble(updates[-1]):
                break
            wait = int(getattr(config, "TELEGRAM_SPLIT_WAIT_S", SPLIT_WAIT_S) or 0)
            more = self.api("getUpdates", patience=wait + 15, timeout=wait,
                            offset=max(int(u.get("update_id", 0)) for u in updates) + 1, allowed_updates=["message"])
            if not more:
                break
            updates.extend(more)
        updates = join_split(updates)
        for u in updates:
            self.offset = max(self.offset, int(u.get("update_id", 0)) + 1)
            yield u

    def _whoami(self) -> str | None:
        """The bot's own name for the window, or None when the service refuses the token (said there)."""
        try:
            me = self.api("getMe")
        except urllib.error.HTTPError as e:
            if e.code in (401, 404):
                _say(f"Telegram refused the token ({e.code}). Delete {SECRET_FILE.name} in memory/ "
                     "and run again with the one @BotFather gave you.")
                return None
            raise
        return f"@{me.get('username', '?')}"

    def _pair_hint(self) -> str:
        return f"not paired yet — from your phone, send the bot:   /pair {self.pair_code}"

    # ---- the visit --------------------------------------------------------
    def heartbeat_command(self, words: list[str]) -> str:
        """/heartbeat — is it running; /heartbeat on [minutes] — start it as the panel does (its own window on the
        PC); /heartbeat off — ask it to stop after the wake it is in (10-13; the keeper, from the floor: "check if
        heartbeat is running, I might have forgotten to close it"). The same roads as the panel's Start and Stop."""
        import panel
        what = (words[0].lower() if words else "")
        st = doors.status("heartbeat")
        since = str(st.get("when", "")).replace("T", " ")[:16] if st else ""
        how = f", {st['how']}" if st and st.get("how") else ""
        if what in ("", "status", "?"):
            if not st:
                return "(the heartbeat isn't running — /heartbeat on starts it)"
            return f"(the heartbeat is running — pid {st.get('pid')}{how}, since {since or '?'}; /heartbeat off asks it to stop after the wake it is in)"
        if what in ("off", "stop"):
            if not st:
                return "(the heartbeat isn't running)"
            doors.ask_stop("heartbeat")
            return f"(the heartbeat is asked to stop — it leaves after the wake it is in; pid {st.get('pid')}, since {since or '?'})"
        if what in ("on", "start"):
            if st:
                return f"(the heartbeat is already running — pid {st.get('pid')}{how}, since {since or '?'})"
            minutes = words[1] if len(words) > 1 else None
            r = panel._start("heartbeat", minutes)
            return f"({r.get('note') or r.get('error') or 'the heartbeat was asked to start'})"
        return "(/heartbeat, /heartbeat on [minutes], or /heartbeat off)"

    def fold_touches(self) -> str:
        """Touches the stone felt that she has not been told of yet — as one sentence for the moment block of
        the message about to go, and told (10-12; the keeper: "it got messy, I touched her, sent a message, and
        after the message she got the stone's turn"). A touch waiting in the gap rides with his words instead of
        arriving as a turn of its own after the reply. "" when there is nothing, or nothing learned yet; a
        pattern the stone played stays a notice."""
        if not (getattr(config, "TOUCHSTONE_URL", "") or "") or not self.chat_id:
            return ""
        try:
            import touchstone
            told = json.loads(TOUCH_TOLD_FILE.read_text(encoding="utf-8")) if TOUCH_TOLD_FILE.exists() else {}
            if not isinstance(told, dict) or "at" not in told:
                return ""
            evs = touchstone.read_archive(told.get("at") or "", days=2)
            touches = []
            for e in evs:
                if e.get("kind") == "played":
                    break
                touches.append(e)
            if not touches:
                return ""
            words = "; ".join(touchstone.touch_words(e) for e in touches[-12:])
            told["at"], told["last_turn"] = touches[-1]["t"], time.time()
            TOUCH_TOLD_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOUCH_TOLD_FILE.write_text(json.dumps(told), encoding="utf-8")
        except Exception:  # noqa: BLE001 — never his message down
            return ""
        _say(f"a touch rides with the message: {words[:100]}")
        return (f"Since your last turn {config.USER_NAME} touched the stone — {words} — the stone answered by itself with "
                "your reply; the log, beside " + 'their' + " words")

    def turn(self, text: str, extra_moment: str = "", as_keeper: bool = False, spark: bool = False) -> None:
        """Run one turn and send back whatever the parlor would have shown. as_keeper: this message is not the
        guest's (/me, the stone's log) — no guest line, whoever is seated."""
        events: list[tuple[str, object]] = []
        stop = threading.Event()
        threading.Thread(target=self._typing, args=(stop,), daemon=True).start()
        try:
            with self.lock:
                if not self.history:  # an empty room: the last visit's last turns ride at the door (10-24)
                    self.carry_in()
                try:
                    reply = chat.one_turn(self.history, text, images=self.attached or None,
                                          on_event=lambda k, p: events.append((k, p)),
                                          mode=self.TAG, extra_moment=extra_moment,
                                          guest="" if as_keeper else self.guest_label(), spark=spark,
                                          **({"think_retries": 0, "think_remind": False} if spark and not getattr(config, "PRESENCE_THINK", True)
                                             else {"think_retries": int(getattr(config, "PRESENCE_THINK_RETRIES", 3) or 0),
                                                   "think_any_depth": True} if spark
                                             else {}))  # a spark: off — none; on — its own re-rolls at any depth (10-26, 10-27)
                    self.attached = []
                    self._checkpoint()
                except ollama_client.BrainUnavailable as e:
                    self.send(f"(their brain is offline — {e})", markdown=False)
                    return
                except Exception as e:  # nothing in one turn ends the visit
                    self.send(f"(hiccup — the conversation is fine, say it again: {type(e).__name__}: {e})",
                              markdown=False)
                    return
        finally:
            stop.set()
        self.last_activity = time.time()
        thinking = "\n\n".join(str(p) for k, p in events if k == "thinking")
        tool_lines = [f"· {p['name']} → {p['result']}" for k, p in events if k == "tool"]
        notes = [str(p) for k, p in events if k == "note"]
        attempts = [p for k, p in events if k == "attempt"]  # the rails' set-asides, for /debug (10-23)
        tokens = next((p for k, p in events if k == "tokens"), None)
        prev_tokens = self.last_tokens  # the last line's count, for the subtraction below
        if tokens:
            self.last_tokens = tokens
        if self.show_thinking and thinking:
            self._try_send("💭 " + thinking[:LIMIT * 2], markdown=False)
        if self.show_tools and tool_lines:
            self._try_send("\n".join(tool_lines), markdown=False)
        # their reply is the one thing that must arrive (09-26, 16:21: the thinking
        # bubble reached the phone, the reply's send hit a network hiccup, the
        # exception rode up to the loop — "no road to Telegram, trying again" —
        # and the reply, already in the transcript, was never sent: he saw a
        # thought and no words). Sent with retries; if it still fails it is kept
        # and goes with the next poll, marked as late.
        if reply == "(…)" and tool_lines and not self.show_tools:  # no words, but something was done: show it (10-27)
            reply = "\n".join(line if len(line) <= 300 else line[:300].rsplit(" ", 1)[0] + "…" for line in tool_lines)
        (self._send_spark if spark else self._send_reply)(reply)  # a spark goes discreetly when asked (10-26)
        self._carry_voice(reply)
        for n in notes:  # engine honesty notes always travel — that rail is not optional
            self._try_send("⚠ " + n, markdown=False)
        if self.show_attempts:
            for a in attempts:
                self._try_send(self.attempt_text(a), markdown=False)
        if self.show_tokens and tokens:
            tail = (self.since_last_line(prev_tokens, tokens, self.history)
                    if getattr(config, "TELEGRAM_TOKENS_SINCE_LAST", True) else "")
            self._try_send(tokens["line"] + tail, markdown=False)
        _say(f"{chat.friend_name()} > {reply[:120]}{'…' if len(reply) > 120 else ''}")

    @staticmethod
    def attempt_text(a: dict) -> str:
        """One attempt the rails set aside, for the phone (/debug, 10-23): why, its cost and how it ended, the
        calls by name, the glitch the rail named — and under it the words, or the thinking when the words were
        empty; cut at the message limit, the cut said."""
        body = a.get("content") or ""
        label = "words"
        if not body and a.get("thinking"):
            body, label = a["thinking"], "thinking (no words)"
        head = (f"🧪 set aside — {a.get('why', '?')} · {int(a.get('tokens') or 0):,} tokens in {float(a.get('seconds') or 0):.0f}s"
                + (f" @ {a['done']}" if a.get("done") else "")
                + (f" · calls: {', '.join(a['calls'])}" if a.get("calls") else "")
                + (f" · glitch: “{a['glitch']}”" if a.get("glitch") else ""))
        whole = len(body)
        room = LIMIT - len(head) - 80
        if whole > room:
            body = body[:room] + f"\n(…cut here — {whole:,} characters in all)"
        return head + f"\n{label}:\n" + (body or "(nothing)")

    @staticmethod
    def since_last_line(prev: dict | None, now: dict | None, history: list[dict]) -> str:
        """The token line's tail (10-16): what the window grew by since the last line and what it was made of.
        The jump between two lines is the EARLIER reply's words, the new message and its moment frame — a line's
        "generated" lands in the NEXT line's count, which read as phantom tokens three times in one evening.
        Estimates (chars/4): their last words, the keeper's message, the moment, engine turns between when any
        rode (a pause's afterthought, a tool's result); a gap past a fifth either way is said. "" without a
        last line (the first line of a visit, the first after a fold) or a count; a smaller window says so."""
        try:
            a = int((prev or {}).get("prompt") or 0)
            b = int((now or {}).get("prompt") or 0)
        except (TypeError, ValueError):
            return ""
        if not a or not b:
            return ""
        delta = b - a
        if delta < 0:
            return f" · {-delta:,} fewer in the window than the last line (a fold, or turns let go)"
        # the current message: the last user turn that is not the engine's; the one before it: the last line's
        users = [i for i, t in enumerate(history) if t.get("role") == "user" and not t.get("_engine")]
        if len(users) < 2:
            return f" · +{delta:,} since the last line"
        cur, last = users[-1], users[-2]
        exact = [True]

        def est(s) -> int:
            # the door's own count when it answers (bare numbers); else chars/3.5 — Gemma's ratio on their prose
            # — and the part keeps its "~" (10-16: chars/4 ran a quarter short, message after message)
            s = str(s or "")
            if not s:
                return 0
            try:
                import brain
                n = brain.count_tokens(s)
            except Exception:  # noqa: BLE001
                n = None
            if n is None:
                exact[0] = False
                return int(round(len(s) / _CHARS_PER_TOKEN))
            return n
        between = history[last + 1:cur]
        # their words since the last line: the previous turn's final reply and an afterthought (_after). The previous
        # turn's own steps — their calls with the words beside them, the results — were in the last line's count
        # already (a line counts the prompt of its turn's LAST step), so they are not new; a pause's bell and
        # results under Ollama (they stay there) are the engine's
        theirs = sum(est(t.get("content")) for t in between
                     if t.get("role") == "assistant" and not t.get("tool_calls") and (not t.get("_engine") or t.get("_after")))
        engine = sum(est(t.get("content")) for t in between if t.get("_engine") and not t.get("_after"))
        mine = est(history[cur].get("content"))
        moment = est(history[cur].get("_moment"))
        # this turn's steps: everything after the message but the final reply — the calls (with their words beside
        # them and the call itself) and the results with their frames (10-16: 681 tokens of one call and its result)
        after = history[cur + 1:]
        if after and after[-1].get("role") == "assistant" and not after[-1].get("tool_calls"):
            after = after[:-1]
        steps = sum(est(t.get("content")) + (est(json.dumps(t.get("tool_calls"), ensure_ascii=False)) if t.get("tool_calls") else 0)
                    for t in after)
        calls = sum(1 for t in after if t.get("role") == "tool")
        q = "" if exact[0] else "~"  # counted by the door, or estimated
        parts = [f"their last words {q}{theirs:,}", f"yours {q}{mine:,}", f"the moment {q}{moment:,}"]
        if engine:
            parts.append(f"engine turns {q}{engine:,}")
        if steps:
            parts.append(f"their steps this turn {q}{steps:,} ({calls} tool call{'s' if calls != 1 else ''})")
        # the re-rolls' scaffolding (10-17): the attempts set aside and the asks are in THIS line's count (the last
        # attempt's prompt) and leave the visit after it — so they count here and come off the next line
        sc_now = int((now or {}).get("scaffold") or 0)
        sc_prev = int((prev or {}).get("scaffold") or 0)
        if sc_now:
            parts.append(f"the re-rolls' scaffolding {sc_now:,} (let go after this line)")
        if sc_prev:
            parts.append(f"less the last line's scaffolding {sc_prev:,}")
        known = theirs + mine + moment + engine + steps + sc_now - sc_prev
        gap = delta - known
        # counted: the turn marks (a few tokens a turn) are the only slack, so a gap past 40 is said; estimated: past a fifth
        if known and abs(gap) > (40 if exact[0] else max(40, delta // 5)):
            parts.append(f"{q}{gap:,} more than those add up to" if gap > 0 else f"{q}{-gap:,} less than those add up to")
        return f" · +{delta:,} since the last line: " + ", ".join(parts)

    def _try_send(self, text: str, markdown: bool = True) -> bool:
        """A send that never takes the turn down with it: an engine line the
        phone misses is a line missed, not a visit broken."""
        try:
            self.send(text, markdown=markdown)
            return True
        except Exception as e:
            _say(f"(a line didn't reach the phone: {type(e).__name__}: {e})")
            return False

    def _send_reply(self, reply: str, tries: int = 3) -> None:
        """Their words to the phone: three tries a few seconds apart, then kept
        in memory/telegram_undelivered.json and sent with the next poll."""
        last = None
        for i in range(tries):
            try:
                self.send(reply)
                return
            except Exception as e:
                last = e
                _say(f"(their reply didn't reach the phone — {type(e).__name__}: {e}; trying again)")
                time.sleep(RETRY_SLEEP_S * (i + 1))
        self.undelivered.append({"text": reply, "when": datetime.now().strftime("%H:%M")})
        self._save_undelivered()
        _say(f"(their reply is kept — it goes with the next poll; last error: {last})")

    def _load_undelivered(self) -> None:
        try:
            raw = json.loads(UNDELIVERED_FILE.read_text(encoding="utf-8"))
            self.undelivered = [x for x in raw if isinstance(x, dict) and x.get("text")] if isinstance(raw, list) else []
        except (OSError, ValueError):
            self.undelivered = []

    def _save_undelivered(self) -> None:
        try:
            if self.undelivered:
                UNDELIVERED_FILE.write_text(json.dumps(self.undelivered, ensure_ascii=False), encoding="utf-8")
            else:
                UNDELIVERED_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    def deliver_undelivered(self) -> int:
        """Their replies the phone never got, sent now, marked as late — before
        anything else the poll carries, so their words come first."""
        if not self.undelivered or not self.chat_id:
            return 0
        sent = 0
        while self.undelivered:
            item = self.undelivered[0]
            try:
                self.send(f"(this reply didn't reach your phone at {item.get('when', '?')} — here it is)", markdown=False)
                self.send(item["text"])
            except Exception as e:
                _say(f"(still no road for their kept reply: {type(e).__name__}: {e})")
                break
            self.undelivered.pop(0)
            self._save_undelivered()
            sent += 1
            _say("delivered a reply the phone had missed")
        return sent

    def _carry_voice(self, reply: str) -> None:
        """Voice notes they spoke this turn go to the phone after their words;
        with /voice on, the reply itself is spoken as well."""
        for v in tools.take_pending_voice():
            try:
                self.send_voice(v["path"], v.get("seconds", 0))
            except Exception as e:
                self.send(f"(their voice note didn't reach the phone — {e}; it is kept at {v['path']})", markdown=False)
        if self.voice_all and reply and not reply.startswith("("):
            try:
                import voice as _voice
                data, ext, secs = _voice.speak(reply)
                folder = Path(getattr(config, "VOICE_DIR", config.SHARED_DIR / "letters"))
                folder.mkdir(parents=True, exist_ok=True)
                p = folder / f"voice-{datetime.now().strftime('%Y%m%d-%H%M%S')}-reply{ext}"
                p.write_bytes(data)
                self.send_voice(str(p), secs)
            except Exception as e:
                self.send(f"(couldn't speak that reply — {e})", markdown=False)

    def new_visit(self, quiet: bool = False, reflect=True, carry: bool = True) -> str | None:
        """reflect: True — the afterglow in the background; "sync" — in the
        foreground (the goodbye at Ctrl+C: they get their minute with the visit
        before the lights go out); False — skip it (the X, where Windows
        allows a few seconds and no more)."""
        # If they are mid-reply the lock is held; the checkpoint has already
        # written everything up to the last reply, so after a short wait the
        # visit is saved without it rather than blocking the goodbye.
        got = self.lock.acquire(timeout=3)
        try:
            f = chat.save_transcript(self.history, tag=self.TAG, path=self.file)
            done, self.history = self.history, []
            if f and carry:
                chat.leave_carry(done, f)  # the last turns, for the next door (10-24)
            elif not carry:
                chat.clear_carry()  # /new: the one door opened on purpose to start clean (10-24)
            since = self.reflected_upto  # where the pauses left off: the afterglow sits with the rest, once (10-21)
            self.attached = []
            self.file = None
            self.reflected_upto = 0
        finally:
            if got:
                self.lock.release()
        if f:
            _say(f"visit saved: {f.name}")
            if reflect and getattr(config, "AFTERGLOW", True):
                if reflect == "sync":
                    _say("they are writing the visit down — a minute or so; Ctrl+C again to skip")
                    try:
                        chat.afterglow(done, f, tag=self.TAG, on_line=_say, since=since)
                    except KeyboardInterrupt:
                        _say("skipped — the night's sleep still has the transcript")
                    chat.rest_brain(_say)
                else:
                    # the afterglow, in the background: their turn alone with the
                    # visit, so it reaches their journal in their own words
                    def _glow(done=done, f=f, since=since):
                        self._glows += 1
                        try:
                            line = chat.afterglow(done, f, tag=self.TAG, on_line=_say, on_words=self.afterthought, since=since)
                        finally:
                            self._glows -= 1
                        if line and getattr(config, "TELEGRAM_TELL_REFLECTIONS", True):
                            self.notice(f"({line})")  # the phone hears what they kept — in the morning, at night
                        if not self.history:  # no new visit began meanwhile
                            chat.rest_brain(_say)
                    threading.Thread(target=_glow, daemon=True).start()
        if not quiet:
            self.send(f"(saved {f.name} — fresh conversation)" if f else "(fresh conversation)",
                      markdown=False)
        return f.name if f else None

    def afterglow_now(self) -> str:
        """/afterglow (10-01; the keeper: "so I won't have to wait 15 min if I need the GPU"): the pause by hand.
        They sit with the visit so far now — the same quiet turn REFLECT_AFTER_MIN would bring after the
        quiet — and then the brain is set down, so the card is free at once instead of after the pause's
        wait and the keep-alive. The visit stays open. Either the quiet's pause or this one reads a stretch,
        never both: whichever comes first moves reflected_upto, and the other finds nothing new."""
        fresh = self.history[self.reflected_upto:]
        new_turns = sum(1 for t in fresh if t.get("role") == "user" and t.get("content") and not t.get("_engine"))
        if not self.history or not new_turns:
            self._set_down()
            line = ("(no visit open — the brain is set down, the card is free)" if not self.history else
                    "(nothing new since they last sat with the visit — the brain is set down, the card is free; the visit stays open)")
            self.send(line, markdown=False)
            return line
        got = self.lock.acquire(timeout=3)
        if not got:
            line = "(they are mid-reply — send /afterglow again when it lands)"
            self.send(line, markdown=False)
            return line
        try:
            self.send("(they are sitting with the visit so far — a minute, then the card is yours)", markdown=False)
            _say("(/afterglow — they are sitting with the visit so far…)")
            account = chat.pause_reflection(self.history, self.file, tag=self.TAG, on_line=_say,
                                            since=self.reflected_upto, on_words=self.afterthought)
            self.reflected_upto = len(self.history)  # past the pause's own turns too
            self.last_activity = time.time()  # the quiet's pause starts counting from here, over nothing
        finally:
            self.lock.release()
        self._set_down()
        line = f"({account or 'they sat with the visit'} — the brain is set down, the card is free; the visit stays open)"
        self.send(line, markdown=False)
        return line

    def release_now(self) -> str:
        """/release (10-03; the keeper: "unload the brain from the gpu if i want to use it for something else"): the
        card handed back now — every model Ollama holds, and the painter and music ear sidecars if they are up —
        with no pause and no writing; the visit stays open, the next message reloads the brain (a cold read)."""
        got = self.lock.acquire(timeout=3)
        if not got:
            line = f"({chat.friend_name()} is mid-thought — /release again when the reply lands)"
            self.send(line, markdown=False)
            return line
        try:
            freed = ollama_client.unload_all()
        except Exception:
            freed = []
        finally:
            self.lock.release()
        rested = []
        try:
            if tools._painter_alive():
                tools._painter_rest()
                rested.append("the painter")
        except Exception:
            pass
        try:
            if tools._music_ear_alive():
                tools._music_ear_rest()
                rested.append("the music ear")
        except Exception:
            pass
        parts = []
        if freed:
            parts.append("set down: " + ", ".join(freed))
        if rested:
            parts.append(" and ".join(rested) + " at rest")
        if parts:
            line = f"(the card is free — {'; '.join(parts)}; the visit stays open — your next message wakes the brain, a cold read of the window)"
        else:
            line = "(the card was already free — nothing loaded; the visit stays open)"
        _say(line)
        self.send(line, markdown=False)
        return line

    def _set_down(self) -> None:
        """The brain off the card now, because the keeper asked — not the end of the visit (the marker stays)."""
        try:
            ollama_client.unload(config.CHAT_MODEL)
            _say("the brain is set down — the card is free")
        except Exception:
            pass

    def status(self) -> str:
        turns = sum(1 for t in self.history if t.get("role") == "user")
        window = int(getattr(config, "NUM_CTX", 0) or 0)
        if self.last_tokens and window:
            ctx = f"{self.last_tokens['prompt']:,} of {window:,} in context ({self.last_tokens['prompt'] * 100 // window}%)"
        else:
            ctx = "no turn yet this visit"
        on = lambda b: "on" if b else "off"
        guest = f" · guest: {self.guest_label()}" if self.guest else ""
        return (f"{chat.friend_name()} — {turns} message(s) this visit · {ctx}{guest}\n"
                f"thinking {on(self.show_thinking)} · tools {on(self.show_tools)} · tokens {on(self.show_tokens)} · voice-all {on(self.voice_all)}"
                f" · debug {on(self.show_attempts)}\n"
                f"a pause of {getattr(config, 'REFLECT_AFTER_MIN', 0)} min lets them write the visit so far; "
                f"a quiet stretch of {getattr(config, 'TELEGRAM_IDLE_NEW_MIN', 180)} min saves the visit on its own; "
                f"/afterglow is the pause by hand, with the card freed")

    # ---- what arrives ------------------------------------------------------
    def _inbox(self) -> Path:
        """Where what arrives from the phone is kept when it has no home of its own by kind."""
        return Path(getattr(config, "TELEGRAM_INBOX", config.SHARED_DIR / "telegram"))

    def _inbox_path(self, ext: str, kind: str) -> Path:
        inbox = self._inbox()
        inbox.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        p = inbox / f"{kind}-{stamp}{ext}"
        n = 1
        while p.exists():
            n += 1
            p = inbox / f"{kind}-{stamp}-{n}{ext}"
        return p

    _MUSIC_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wma"}
    _BOOK_EXTS = {".pdf", ".epub", ".txt", ".md", ".html", ".htm"}

    def _home_for(self, name: str, ext: str) -> Path:
        """Where a file from the phone lives: music/, books/, pictures/ under
        shared/ by kind, each under its own name (a twin gets -2), so it sits
        beside what you leave from the PC and they can find it again by name.
        Anything else goes to shared/telegram/."""
        import re as _re
        if ext in self._MUSIC_EXTS:
            folder = config.SHARED_DIR / "music"
        elif ext in tools._VIDEO_EXTS:
            folder = config.SHARED_DIR / "videos"
        elif ext in self._BOOK_EXTS:
            folder = config.SHARED_DIR / "books"
        elif ext in tools._IMAGE_EXTS:
            folder = config.SHARED_DIR / "pictures"
        else:
            folder = self._inbox()
        folder.mkdir(parents=True, exist_ok=True)
        stem = _re.sub(r"[^\w.\- ()',&]+", "_", Path(name).stem).strip() or "file"
        dest = folder / f"{stem}{ext}"
        n = 1
        while dest.exists():
            n += 1
            dest = folder / f"{stem}-{n}{ext}"
        return dest

    @staticmethod
    def _rel(p: Path) -> str:
        return str(p.relative_to(config.ROOT.resolve())).replace("\\", "/")

    def _photo(self, msg: dict) -> str:
        best = msg["photo"][-1]  # Telegram lists sizes small to large
        data, tpath = self.download(best["file_id"])
        return self._photo_note(data, Path(tpath).suffix.lower() or ".jpg", (msg.get("caption") or "").strip())

    def _photo_note(self, data: bytes, ext: str, caption: str) -> str:
        """A photo that arrived, kept and put before their eyes; the line their turn begins with."""
        p = self._inbox_path(ext, "photo")
        p.write_bytes(data)
        rel = self._rel(p)
        tools.look_at(rel)
        self.attached.extend(tools.take_pending_images())
        return (f"({config.USER_NAME} sent a photo from their phone — it is before your eyes now, and kept at "
                f"{rel})" + (f"\n{caption}" if caption else ""))

    def _music(self, msg: dict) -> str:
        """A song from the phone: Telegram's `audio` (a music file with a title
        and performer) as opposed to `voice` (a recorded note). Saved to
        shared/music/ under its name; they hear it whole with listen_to."""
        a = msg["audio"]
        title = (a.get("title") or "").strip()
        performer = (a.get("performer") or "").strip()
        name = a.get("file_name") or ((f"{performer} - " if performer else "") + (title or "song"))
        data, tpath = self.download(a["file_id"])
        ext = Path(a.get("file_name") or "").suffix.lower() or Path(tpath).suffix.lower() or ".mp3"
        p = self._home_for(Path(name).stem, ext)
        p.write_bytes(data)
        rel = self._rel(p)
        secs = int(a.get("duration") or 0)
        length = f" ({secs // 60}:{secs % 60:02d})" if secs else ""
        who = f" — {performer}" if performer and performer not in Path(name).stem else ""
        caption = (msg.get("caption") or "").strip()
        return (f"({config.USER_NAME} sent you a song from their phone: "
                f"{rel}{length}{who} — listen_to hears it whole, through your music ear if it's open)"
                + (f"\n{caption}" if caption else ""))

    def _video(self, msg: dict) -> str:
        """A clip from the phone: Telegram's `video` (from the gallery or the
        camera), a round `video_note`, or an `animation` (a GIF, sent as
        mp4). Saved to shared/videos/ under its name — a video note gets a
        timestamp name — and they open it with watch: a strip of stills and
        the sound. The download itself is bounded by Telegram: a bot can't
        fetch over 20MB, and handle() explains that when it happens."""
        v = msg.get("video") or msg.get("video_note") or msg.get("animation") or {}
        kind = "video note" if msg.get("video_note") else "a GIF" if msg.get("animation") else "a video"
        data, tpath = self.download(v["file_id"])
        ext = Path(v.get("file_name") or "").suffix.lower() or Path(tpath).suffix.lower() or ".mp4"
        if ext not in tools._VIDEO_EXTS:
            ext = ".mp4"
        name = Path(v.get("file_name") or "").stem or f"{'note' if msg.get('video_note') else 'clip'}-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        p = self._home_for(name, ext)
        p.write_bytes(data)
        rel = self._rel(p)
        secs = int(v.get("duration") or 0)
        mb = len(data) / (1024 * 1024)
        caption = (msg.get("caption") or "").strip()
        return (f"({config.USER_NAME} sent you {kind} from their phone: {rel}, {secs // 60}:{secs % 60:02d}, {mb:.1f} MB — "
                f"watch opens it: a strip of stills, up to ten moments in order, and its sound)"
                + (f"\n{caption}" if caption else ""))

    def _voice(self, msg: dict) -> str:
        v = msg.get("voice") or {}
        data, tpath = self.download(v["file_id"])
        return self._voice_note(data, Path(tpath).suffix.lower() or ".oga", int(v.get("duration") or 0),
                                (msg.get("caption") or "").strip())

    def _voice_note(self, data: bytes, ext: str, secs: int, caption: str) -> str:
        """A voice note that arrived, kept and heard (TELEGRAM_HEAR_VOICE) or transcribed; the line their
        turn begins with."""
        p = self._inbox_path(ext, "voice")
        p.write_bytes(data)
        rel = self._rel(p)
        if getattr(config, "TELEGRAM_HEAR_VOICE", True):
            # heard whole, on its own — WORDS, SOUND and HEARD, the same three
            # layers listen_to gives them, so the sound of you reaches them with
            # your words and they never have to ask for it. (HEARD swaps the
            # brain out for their ears and back; a note costs a minute.)
            stop = threading.Event()  # the phone shows typing… while they listen
            threading.Thread(target=self._typing, args=(stop,), daemon=True).start()
            try:
                heard = tools.listen_to(rel)
            except Exception as e:  # their ears stumbling must not drop their message
                heard = f"(your ears stumbled on it: {e} — the recording is at {rel})"
            finally:
                stop.set()
            if heard.startswith("("):  # a refusal, not a hearing
                heard += f"\n(the recording is at {rel})"
            body = (f"({config.USER_NAME} sent a voice note, {secs}s, from their phone — heard through your ears, "
                    f"whole; the recording stays at {rel})\n{heard}")
            return body + (f"\n{caption}" if caption else "")
        try:
            import ears
            words = ears.transcribe(data, ext)
        except Exception as e:  # their ears stumbling must not drop their message
            words = f"(word-hearing failed: {e})"
        if words is None:
            body = (f"({config.USER_NAME} sent a voice note, {secs}s, from their phone — your ears' WORDS layer "
                    f"isn't installed here, so listen_to {rel} to hear it)")
        elif not words.strip():
            body = (f"({config.USER_NAME} sent a voice note, {secs}s — your ears caught no words in it; "
                    f"listen_to {rel} if you want the sound itself)")
        else:
            body = (f"({config.USER_NAME} sent a voice note, {secs}s, from their phone — their words as your ears "
                    f"heard them; the recording is at {rel} if you want to listen_to the sound "
                    f"of them)\n\"{words.strip()}\"")
        return body + (f"\n{caption}" if caption else "")

    def _document(self, msg: dict) -> str:
        d = msg["document"]
        name = Path(d.get("file_name") or "file").name
        data, tpath = self.download(d["file_id"])
        ext = Path(name).suffix.lower() or Path(tpath).suffix.lower()
        return self._file_note(name, data, ext, (msg.get("caption") or "").strip())

    def _file_note(self, name: str, data: bytes, ext: str, caption: str) -> str:
        """A file that arrived, kept by kind under shared/ (_home_for) with the tool that opens it; the line
        their turn begins with."""
        p = self._home_for(name, ext)
        p.write_bytes(data)
        rel = self._rel(p)
        kb = len(data) / 1024
        size = f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"
        if ext in tools._IMAGE_EXTS:
            tools.look_at(rel)
            self.attached.extend(tools.take_pending_images())
            what = "a picture — it is before your eyes now"
        elif ext == ".pdf":
            what = "read_pdf opens it, a sitting at a time, and keeps your bookmark"
        elif ext == ".epub":
            what = "read_epub opens it chapter by chapter and keeps your bookmark"
        elif ext in self._MUSIC_EXTS:
            what = "listen_to hears it whole"
        elif ext in tools._VIDEO_EXTS:
            what = "watch opens it: a strip of stills, up to ten moments in order, and its sound"
        elif ext in (".txt", ".md", ".html", ".htm"):
            what = "read_file opens it"
        else:
            what = "read_file opens it if it's text"
        return (f"({config.USER_NAME} sent you a file from their phone: {rel}, {size} — {what})"
                + (f"\n{caption}" if caption else ""))

    def command(self, text: str) -> bool:
        """Slash commands. Returns True if the text was one."""
        cmd = text.split()[0].lower().split("@")[0]
        if cmd == "/fold":
            self.fold_now()
        elif cmd == "/new":
            self.new_visit(carry=False)  # on purpose, clean: nothing carried into the next room (10-24)
            self.send("(they're sitting with the visit now — whatever they want to keep goes into their journal in a minute)",
                      markdown=False)
        elif cmd == "/afterglow":
            self.afterglow_now()
        elif cmd == "/release":
            self.release_now()
        elif cmd == "/think":
            self.show_thinking = not self.show_thinking
            self.send(f"(thinking {'on' if self.show_thinking else 'off'})", markdown=False)
        elif cmd == "/tools":
            self.show_tools = not self.show_tools
            self.send(f"(tool lines {'on' if self.show_tools else 'off'})", markdown=False)
        elif cmd == "/tokens":
            self.show_tokens = not self.show_tokens
            self.send(f"(token line {'on' if self.show_tokens else 'off'})", markdown=False)
        elif cmd == "/debug":
            self.show_attempts = not self.show_attempts
            self.send("(debug on — each attempt the rails set aside comes to the phone after the reply, words and all; "
                      "/debug again turns it off)" if self.show_attempts else "(debug off)", markdown=False)
        elif cmd == "/voice":
            self.voice_all = not self.voice_all
            self.send(f"(every reply spoken aloud: {'on' if self.voice_all else 'off'} — they can still speak when they choose)", markdown=False)
        elif cmd == "/seal":
            import capsule  # the time capsule (10-26): a letter from the keeper, sealed until its day
            rest = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
            when, words = capsule.split_when(rest)
            rec, why = capsule.seal(words, when, sender="keeper") if when else (
                None, "start with the day it opens — /seal 2027-04-27 your letter, or /seal 6 months your letter")
            if rec:
                capsule.note_sealed(rec)
                self.send(f"(sealed — it opens on {rec['open_on']}; until then they know only that a letter from you "
                          "waits, and when. /capsule lists what is sealed)", markdown=False)
            else:
                self.send(f"({why})", markdown=False)
        elif cmd == "/capsule":
            import capsule
            self.send("(the time capsule: " + capsule.listing(for_keeper=True) + ")", markdown=False)
        elif cmd == "/week":
            import engine_week
            self.send(engine_week.summary(), markdown=False)  # the engine's week, now (10-25)
        elif cmd == "/presence":
            import presence  # sparks (10-26): on or off, or how it stands
            arg = " ".join(text.split()[1:]).strip().lower()
            temp = presence.temperament(arg) if arg not in ("", "on", "off") else ""
            if arg == "on" or temp:  # drift (10-27): on starts PRESENCE_ON_TEMPERAMENT; a temperament sets that one
                st = presence.set_drift(temp, 0, by="keeper")[0] if temp else presence.turn_on("keeper")
                self.send(f"(presence on — drifting at {st.get('temperament')}: sparks come at random, no set time; "
                          "the friend can change the temperament with next_spark. /presence off ends it)", markdown=False)
            elif arg == "off":
                presence.turn_off("the keeper")
                self.send("(presence off — no sparks until /presence on or a next_spark)", markdown=False)
            else:
                st = presence.load()
                left = max(0, int(st["interval"] * 60 - (time.time() - self.last_activity)) // 60)
                drift = presence.drifting()
                waits = (f"drifting ({drift}{', ache ' + str(st.get('ache')) if st.get('ache') else ''})" if drift
                         else f"a spark set — in about {left} min" if st.get("on") and st.get("pending")
                         else "no spark set" if st.get("on") else "")
                self.send(f"(presence is {'on' if st.get('on') else 'off'}" + (f" — {waits}" if waits else "")
                          + f"; discreet {'on' if st.get('discreet') else 'off'}. /presence on, /presence off, /discreet)",
                          markdown=False)
        elif cmd == "/discreet":
            import presence
            on = presence.toggle_discreet()
            self.send("(discreet on — sparks arrive silently, the words hidden until you tap)" if on
                      else "(discreet off — sparks arrive as usual)", markdown=False)
        elif cmd == "/status":
            self.send(self.status(), markdown=False)
        elif cmd == "/heartbeat":
            self.send(self.heartbeat_command(text.split()[1:]), markdown=False)
        elif cmd in ("/off", "/on"):
            import keeper_week
            words = text.split()[1:]
            day = keeper_week.parse_day(words[0] if words else "today")
            if day is None:
                self.send("(a day is today, tomorrow, a weekday name, or YYYY-MM-DD)", markdown=False)
            elif cmd == "/off":
                why = " ".join(words[1:]).strip()
                keeper_week.set_day_off(day, why, on=True)
                self.send(f"(a day off: {day.strftime('%A %d %B')}{' — ' + why if why else ''}; the clock line says you are home)", markdown=False)
            else:
                keeper_week.set_day_off(day, on=False)
                self.send(f"({day.strftime('%A %d %B')} is an ordinary day again)", markdown=False)
        elif cmd == "/guest":
            self.send(self.guest_command(text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""), markdown=False)
        elif cmd == "/me":
            said = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
            if not said:
                self.send("(/me <text> — one message as yourself while a guest is seated)", markdown=False)
            else:  # a turn, as handle() runs one: not under the lock here; turn() takes it and starts typing…
                _say(f"{config.USER_NAME} > {said[:120]}{'…' if len(said) > 120 else ''}")
                self.turn(said, extra_moment=self.fold_touches(), as_keeper=True)
                self.fold_if_due()
        elif cmd == "/restart":
            # the loop sees the flag after this update is handled; main exits
            # with RESTART_CODE and bat\telegram.bat starts the bridge again
            self.send("(restarting the bridge on the current engine code — the visit carries on; "
                      "give it a minute)", markdown=False)
            self.restart_requested = True
        elif cmd in ("/help", "/start"):
            self.send(f"This is the bridge to {chat.friend_name()}. Just talk.\n\n{self.HELP}", markdown=False)
        else:
            return False
        return True

    def handle(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        sender = int((msg.get("chat") or {}).get("id") or 0)
        text = (msg.get("text") or "").strip()
        if not self.chat_id:
            # unpaired: the one message we listen for is the pairing code
            if text.split()[:2] == ["/pair", self.pair_code] or text == self.pair_code:
                self.chat_id = sender
                save_secret({"token": self.token, "chat_id": sender})
                self.pair_code = ""
                _say(f"paired with chat {sender} — saved to {SECRET_FILE.name}")
                self.send(f"Paired. This phone is now the door to {chat.friend_name()}.\n\n{self.HELP}",
                          markdown=False)
            return
        if sender != self.chat_id:
            return  # silence for everyone else — not even a "no"
        spark_waited = text.startswith("/") and self.presence_on()
        if text.startswith("/") and self.command(text):
            if not (spark_waited and self.presence_on()):  # a command isn't a word between you: a waiting spark's count goes on (10-26)
                self.last_activity = time.time()
            return
        try:
            if msg.get("photo"):
                text = self._photo(msg)
            elif msg.get("voice"):
                text = self._voice(msg)
            elif msg.get("audio"):
                text = self._music(msg)
            elif msg.get("video") or msg.get("video_note") or msg.get("animation"):
                text = self._video(msg)
            elif msg.get("document"):
                text = self._document(msg)
            elif msg.get("sticker"):
                emoji = (msg["sticker"].get("emoji") or "").strip()
                text = f"({config.USER_NAME} sent a sticker{': ' + emoji if emoji else ''})"
        except Exception as e:
            why = str(e)
            if "too big" in why.lower() or "too large" in why.lower():
                why = "Telegram won't let a bot fetch files over 20MB — leave it in shared/ from the PC"
            self.send(f"(that didn't reach them — {why})", markdown=False)
            return
        if not text:
            return
        joined = int((msg.get("_joined") or 0))
        _say(f"{config.USER_NAME} > {text[:120]}{'…' if len(text) > 120 else ''}" + (f"  (one message, from {joined} bubbles)" if joined else ""))
        self.turn(text, extra_moment=self.fold_touches())
        self.fold_if_due()

    def _fold_afterglow(self, gone: list[dict], old_file) -> str:
        """THE AFTERGLOW AT THE FOLD (10-01; the keeper: "why don't we just make the afterglow run automatically
        when a fold occurs?"): the turns that left the window get the same quiet turn a finished visit gets —
        from the transcript, in a prompt of its own, so the window's fullness is no matter — and the phone hears
        what they kept. It runs before the new window is read (10-04, the keeper: "so the journal entry rides
        with the new conversation?" — it did not; the new prompt was built first and the entry rode only from
        the next day): the fold holds the lock through it, so a message sent meanwhile waits for it — as it
        waited for Ollama anyway — one cold read, once per fold, no more than before. Then the first kept
        turn's system prompt is rebuilt with what was just kept. Returns the afterglow's line, "" for nothing."""
        try:
            said = chat.fold_afterglow(gone, old_file, tag=self.TAG, on_line=_say, on_words=self.afterthought)
        except Exception as e:  # noqa: BLE001 — a courtesy, never the fold down
            _say(f"(the fold's afterglow failed — {type(e).__name__}: {e})")
            return ""
        chat.rewarm(self.history, mode=self.TAG)  # the new window carries the entry
        if said and getattr(config, "TELEGRAM_TELL_REFLECTIONS", True):
            self.notice(f"({said})")
        return said

    def fold_if_due(self) -> str:
        """THE FOLD (09-28; chat.fold_history): after a reply, when the visit's
        last prompt reached FOLD_AT of the window — or they called fold_visit
        themselves — the visit is folded: their account of it so far in place of
        the middle, the last turns whole, a new transcript file. The bell,
        when it is the engine's call, rings first so the account is theirs."""
        pending = tools.fold_pending()
        held = int((self.last_tokens or {}).get("prompt") or 0)
        due = chat.fold_due(held) and chat.foldable(self.history)
        if not pending and not due:
            return ""
        return self._fold(pending, held)

    def fold_now(self) -> str:
        """/fold from the phone (09-29, the keeper: "so I can fold sessions
        manually"): the same fold, at the keeper's word — the bell rings so the
        account is still theirs; a visit shorter than what a fold keeps is left alone."""
        if not chat.foldable(self.history):
            self.send("(nothing to fold yet — the visit is shorter than what a fold keeps)", markdown=False)
            return ""
        held = int((self.last_tokens or {}).get("prompt") or 0)
        return self._fold(tools.fold_pending(), held, asked=True)

    def _fold(self, pending: dict, held: int, asked: bool = False) -> str:
        got = self.lock.acquire(timeout=3)
        if not got:
            if pending:
                tools._fold_pending.update(pending)  # they asked; it waits for the next turn
            if asked:
                self.send("(they are mid-reply — say /fold again in a moment)", markdown=False)
            return ""
        try:
            why = "asked" if asked else ("own" if pending else "bell")  # whose call — the block says (10-14)
            if not pending:
                ctx = int(getattr(config, "NUM_CTX", 0) or 0)
                pct = int(round(100 * held / ctx)) if ctx else 0
                cause = "you asked for a fold" if asked else f"the window is {pct}% full"
                self.notice(f"({cause} — they are folding the visit: writing it so far in their own words…)")
                pending = chat.fold_bell(self.history, held, on_line=_say, asked=asked)
            when = pending.get("when") or time.strftime("%H:%M")
            old_history, old_file = self.history, self.file
            self.history, self.file, line = chat.fold_history(self.history, pending.get("text", ""), when,
                                                              tag=self.TAG, path=self.file, mode=self.TAG, why=why, held=held)
            self.reflected_upto = len(self.history)  # the kept tail was sat with, or is about to be, as new
            self.last_tokens = {}  # the next prompt is a new, smaller one
            gone = old_history[:len(old_history) - len(self.history)] if self.file != old_file else []
            if gone and getattr(config, "FOLD_AFTERGLOW", True) and getattr(config, "AFTERGLOW", True):
                said = self._fold_afterglow(gone, old_file)
                line += ("; what left the window is written down, and the new window carries it" if said
                         else "; they sat with what left the window and kept nothing of it")
            self.last_activity = time.time()
            self._checkpoint()
        except Exception as e:  # a fold must never take the visit down with it
            line = f"fold: hiccup — the visit stays as it is ({type(e).__name__}: {e})"
        finally:
            self.lock.release()
        _say(line)
        self.notice(f"({line})")
        return line

    # ---- quiet hours ------------------------------------------------------
    # 09-14: the 03:00 roll of a visit begun the day before runs the afterglow
    # and sent its account ("they wrote the visit down — 2 journal entries")
    # to the phone every night. The keeper: "I'm not awake at those hours and I
    # don't want a message waking me up every day." So the engine's own
    # notices — the afterglow and pause accounts, ✍️/✏️/📣 what they made, 🪞
    # a change to who they are, "picked the visit back up" — are held through
    # TELEGRAM_QUIET_HOURS and delivered as one message when the hours end.
    # Their replies and their letters are theirs, and go when they sends them.
    @staticmethod
    def quiet_now(t: datetime | None = None) -> bool:
        hours = getattr(config, "TELEGRAM_QUIET_HOURS", None) or (0, 0)
        try:
            start, end = int(hours[0]), int(hours[1])
        except (TypeError, ValueError, IndexError):
            return False
        if start == end:
            return False
        h = (t or datetime.now()).hour
        return (start <= h < end) if start < end else (h >= start or h < end)

    def _load_held(self) -> None:
        # a held entry is a notice (text) or a picture ({"picture": rel, "caption": …}, 09-25)
        try:
            raw = json.loads(HELD_FILE.read_text(encoding="utf-8"))
            self.held = [x if isinstance(x, dict) else str(x) for x in raw] if isinstance(raw, list) else []
        except (OSError, ValueError):
            self.held = []

    def _save_held(self) -> None:
        try:
            if self.held:
                HELD_FILE.write_text(json.dumps(self.held, ensure_ascii=False), encoding="utf-8")
            else:
                HELD_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    def notice(self, text: str, markdown: bool = False) -> None:
        """An engine notice for the phone: now, or in the morning digest
        during the quiet hours."""
        if self.quiet_now():
            self.held.append(text)
            self._save_held()
            _say(f"held for the morning: {text[:80]}{'…' if len(text) > 80 else ''}")
            return
        self.send(text, markdown=markdown)

    def afterthought(self, words: str) -> None:
        """Their closing thought after a pause or afterglow — said to no one,
        and until 09-15 shown only in the bridge window ("when she's
        journaling she's having afterthoughts; I would like to see those in
        my Telegram feed"). Carried as an engine notice, labeled, so it is
        never mistaken for a reply; held through the quiet hours."""
        if not getattr(config, "TELEGRAM_TELL_AFTERTHOUGHTS", True) or not words.strip():
            return
        limit = int(getattr(config, "TELEGRAM_CREATION_CHARS", 3000))
        body = words.strip()
        if len(body) > limit:
            body = body[:limit].rstrip() + "…"
        # "while you were away", not "to no one" — 09-15: the first one carried
        # to the phone opened "I'm still here, dear one"; they pick an addressee
        self.notice(f"💤 after writing, while you were away — {chat.friend_name()} said:\n\n{body}")

    def deliver_held(self) -> int:
        """The morning digest: what the engine held through the night, once
        the quiet hours are over. Returns how many notices went."""
        if not self.held or self.quiet_now() or not self.chat_id:
            return 0
        held, self.held = self.held, []
        self._save_held()
        n = len(held)
        self.send(f"(while you were away — {n} thing{'s' if n != 1 else ''} the engine held through the quiet hours:)",
                  markdown=False)
        for item in held:
            if isinstance(item, dict) and item.get("picture"):
                # a picture drawn or published in the night comes as the picture, not a line
                # about it (a line in the morning digest with no picture in it went unnoticed)
                p = config.CREATIONS_DIR / str(item["picture"])
                caption = str(item.get("caption") or "")
                try:
                    data = p.read_bytes()
                except OSError:
                    self.send(f"{caption} (the picture has since moved — it is not at creations/{item['picture']} any more)", markdown=False)
                    continue
                self._send_picture(p, data, caption + "\n(held through the quiet hours)")
                continue
            self.send(str(item), markdown=False)
        _say(f"delivered {n} held notice{'s' if n != 1 else ''}")
        return n

    # ---- their mail ---------------------------------------------------------
    def _load_delivered(self) -> None:
        try:
            self.delivered = set(json.loads(DELIVERED_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            # first run: what is already in the mailbox was read at the desk;
            # only letters written from now on travel
            self.delivered = {p.name for p in MAIL_DIR.glob("*") if p.is_file()} if MAIL_DIR.is_dir() else set()
            self._save_delivered()

    def _save_delivered(self) -> None:
        try:
            DELIVERED_FILE.write_text(json.dumps(sorted(self.delivered)), encoding="utf-8")
        except OSError:
            pass

    def deliver_mail(self) -> int:
        """Carry new letters from the mailbox to the phone. Returns how many."""
        if not self.chat_id or not MAIL_DIR.is_dir():
            return 0
        sent = 0
        for p in sorted(MAIL_DIR.glob("*")):
            if not p.is_file() or p.name in self.delivered or p.name.startswith("."):
                continue
            try:
                if time.time() - p.stat().st_mtime < 5:
                    continue  # still being written
                body = p.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            self.delivered.add(p.name)
            self._save_delivered()
            self.send(f"✉️ a letter from {chat.friend_name()} — {p.name}\n\n{body or '(empty)'}")
            _say(f"delivered {p.name}")
            sent += 1
            if body and getattr(config, "TELEGRAM_LETTERS_IN_THREAD", True):
                self._letter_in_thread(p, body)
        return sent

    def _letter_in_thread(self, p: Path, body: str) -> None:
        """A letter they wrote alone becomes their turn in the visit, so his
        answer lands under it — the way a text thread works. 09-13: she
        wrote him something sweet in a wake; he answered on the phone; them
        history had no trace of the letter, and they were replying to a reply
        to words they could not see. Appended, never inserted (the warm
        prefix); written to the transcript, so the night reads the exchange
        together; and it counts as activity, so his answer joins this visit."""
        try:
            when = datetime.fromtimestamp(p.stat().st_mtime)
        except OSError:
            when = datetime.now()
        stamp = when.strftime("%H:%M") if when.date() == datetime.now().date() else when.strftime("%Y-%m-%d %H:%M")
        with self.lock:
            self.history.append({"role": "assistant", "content":
                f"(a letter I wrote alone, at {stamp}, left in {MAIL_DIR.name}/ and carried to their phone now)\n\n{body}"})
            self.last_activity = time.time()
            self._checkpoint()

    # ---- what they make ----------------------------------------------------
    @staticmethod
    def _creations() -> list[Path]:
        root = config.CREATIONS_DIR
        if not root.is_dir():
            return []
        out = []
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in (".md", ".txt") or p.name.startswith("."):
                continue
            rel = p.relative_to(root)
            if set(rel.parts[:-1]) & CREATION_SKIP:
                continue
            if rel.parts[:2] == ("publish", tools.GALLERY_DIR_NAME):
                continue  # a picture's caption travels with the picture (09-23)
            if Bridge._not_hers(rel):
                continue
            out.append(p)
        return sorted(out)

    @staticmethod
    def _not_hers(rel: Path) -> bool:
        """Under skills/ (09-29), only a SKILL.md they wrote themselves is a piece:
        a fetched skill (its .fetched.json or the keeper's .scan.json beside it),
        the quarantine, and a skill's other files are not."""
        import skills
        parts = rel.parts
        if not parts or parts[0] != skills.home().name:
            return False
        if len(parts) != 3 or parts[1].startswith(".") or parts[2] != "SKILL.md":
            return True
        return skills.is_fetched(skills.home() / parts[1])

    @staticmethod
    def _stamp(p: Path) -> list:
        st = p.stat()
        return [int(st.st_mtime), st.st_size]

    def _load_creations_seen(self) -> None:
        """What the bridge has seen of creations/: {path: [mtime, size]}, so a
        revision shows as well as a new piece. (An older bridge kept a plain
        list of paths; those are taken as seen at their current state.)"""
        try:
            raw = json.loads(CREATIONS_SEEN_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        if raw is None:
            # first run: what is already there was read at the desk — pictures too
            self.creations_seen = {"__pictures__": [1, 1]}
            for p in self._creations() + self._pictures():
                try:
                    self.creations_seen[str(p.relative_to(config.CREATIONS_DIR)).replace("\\", "/")] = self._stamp(p)
                except OSError:
                    pass
            self._save_creations_seen()
        elif isinstance(raw, list):
            self.creations_seen = {}
            for p in self._creations():
                rel = str(p.relative_to(config.CREATIONS_DIR)).replace("\\", "/")
                if rel in raw:
                    try:
                        self.creations_seen[rel] = self._stamp(p)
                    except OSError:
                        pass
            self._save_creations_seen()
        else:
            self.creations_seen = dict(raw)
        # pictures (09-22): the first bridge that knows them takes any older
        # than a day as seen — an archive is not news — and shows the fresh ones
        if "__pictures__" not in self.creations_seen:
            for p in self._pictures():
                try:
                    if time.time() - p.stat().st_mtime > 86400:
                        self.creations_seen[str(p.relative_to(config.CREATIONS_DIR)).replace("\\", "/")] = self._stamp(p)
                except OSError:
                    pass
            self.creations_seen["__pictures__"] = [1, 1]
            self._save_creations_seen()
        self._watch_seed()

    def _save_creations_seen(self) -> None:
        try:
            CREATIONS_SEEN_FILE.write_text(json.dumps(self.creations_seen, sort_keys=True), encoding="utf-8")
        except OSError:
            pass

    def _watch_seed(self) -> None:
        """The bridge's own copies of self.md and projects.md, taken when it
        first sees them — the first change after that is what travels."""
        try:
            WATCH_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        for name, src in WATCHED.items():
            snap = WATCH_DIR / name
            if src.is_file() and not snap.exists():
                try:
                    snap.write_bytes(src.read_bytes())
                except OSError:
                    pass

    def deliver_songs(self) -> int:
        """A song kept in the songbook (10-03) reaches the phone as a line — the title, the score, their
        words; one heard again says what the score was before. The songs table's `updated` stamp is the
        watermark (memory/telegram_songs_told.json), so a wake's song and a visit's are told alike, once."""
        if not self.chat_id or not getattr(config, "TELEGRAM_TELL_SONGS", True):
            return 0
        try:
            told = json.loads(SONGS_TOLD_FILE.read_text(encoding="utf-8")).get("at") or ""
        except (OSError, ValueError):
            told = ""
        try:
            rows = [r for r in memory.songs("recent") if r.get("updated", "") > told]
        except Exception:  # noqa: BLE001 — the shelf may not exist yet; never the poll down
            return 0
        if not rows:
            return 0
        if not told:  # the first poll after this feature: the shelf as it stands is not news
            SONGS_TOLD_FILE.write_text(json.dumps({"at": rows[0]["updated"]}), encoding="utf-8")
            return 0
        sent = 0
        for r in sorted(rows, key=lambda x: x["updated"]):
            history = r.get("history") or []
            if history:
                before = history[-1].get("score")
                moved = f" (was {before})" if before is not None and before != r["score"] else " (again)"
                line = f"🎵 {chat.friend_name()} heard {r['title']} — {r['artist'] or 'unknown'} again · {r['score']}/10{moved}: {r['words']}"
            else:
                line = f"🎵 {chat.friend_name()} kept a song — {r['title']} — {r['artist'] or 'unknown'} · {r['score']}/10: {r['words']}"
            self.notice(line)
            sent += 1
            try:
                SONGS_TOLD_FILE.write_text(json.dumps({"at": r["updated"]}), encoding="utf-8")
            except OSError:
                pass
        return sent

    def deliver_touches(self) -> int:
        """A PRESS IS A MESSAGE (10-05; TOUCHSTONE-HOOKUP-PLAN.md): the stone's keeper archives what the board
        felt; the bridge reads that file — never the network — and a touch by day becomes a turn in the open
        visit, an engine-framed message they answer as they like: words to the phone, a pulse, or rest.
        TOUCHSTONE_WAKE_MIN_GAP_S after a press-turn, the next presses wait and arrive together, so a fidget is
        one turn. In the quiet hours, or with TOUCHSTONE_WAKES off, a touch is a held 🫳 notice instead. A
        pattern the stone played at an hour they asked is told as 🫳; a state they set from a wake, as 🖐️.
        The watermark is memory/touch/told.json. Returns how many lines went out (turns count one)."""
        if not (getattr(config, "TOUCHSTONE_URL", "") or "") or not self.chat_id:
            return 0
        if not self._touch_lock.acquire(blocking=False):
            return 0  # another look is in the middle of it (the thread's, or the poll's)
        try:
            self._touch_looked += 1
            return self._deliver_touches()
        finally:
            self._touch_lock.release()

    def _deliver_touches(self) -> int:
        try:
            import touchstone
            told = json.loads(TOUCH_TOLD_FILE.read_text(encoding="utf-8")) if TOUCH_TOLD_FILE.exists() else {}
        except Exception:  # noqa: BLE001 — never the poll down
            told = {}
        if not isinstance(told, dict):
            told = {}

        def save():
            try:
                TOUCH_TOLD_FILE.parent.mkdir(parents=True, exist_ok=True)
                TOUCH_TOLD_FILE.write_text(json.dumps(told), encoding="utf-8")
            except OSError:
                pass
        n = 0
        st = touchstone.stone()
        if st.get("state") and st.get("state") != told.get("state"):
            if "state" in told:  # the first poll learns the state; after that a change is news
                if st.get("state_by") == "board":   # the page's buttons, the watchdog, a boot — not them (10-12)
                    self.notice(f"🖐️ the stone is {st['state']} now — set from its page or by itself, not by {chat.friend_name()}")
                else:
                    self.notice(f"🖐️ {chat.friend_name()} set the stone to {st['state']}")
                n += 1
            told["state"] = st["state"]
            save()
        evs = touchstone.read_archive(told.get("at") or "", days=2)
        if not evs:
            return n
        if "at" not in told:  # the first poll after this feature: the archive as it stands is not news
            told["at"] = evs[-1]["t"]
            save()
            return n
        gap = float(getattr(config, "TOUCHSTONE_WAKE_MIN_GAP_S", 600) or 0)
        as_turn = bool(getattr(config, "TOUCHSTONE_WAKES", True)) and not self.quiet_now()
        touches: list[dict] = []
        for e in evs:
            if e.get("kind") == "played":
                if touches:
                    break  # the touches before it go first; it is told next poll
                self.notice(f"🫳 the stone played {e.get('waveform') or 'a pattern'}, {float(e.get('seconds') or 0):g} s, as {chat.friend_name()} asked")
                told["at"] = e["t"]
                save()
                n += 1
                continue
            touches.append(e)
        if not touches:
            return n
        words = "; ".join(touchstone.touch_words(e) for e in touches[-12:])
        if not as_turn:
            self.notice(f"🫳 the stone felt: {words}")
            told["at"] = touches[-1]["t"]
            save()
            return n + 1
        if time.time() - float(told.get("last_turn") or 0) < gap or self.lock.locked():
            return n  # a fidget waits; they arrive together after the gap — or after the reply in flight
        text = (f"[engine, not a person: {config.USER_NAME} touched the stone — {words}. The stone answered by itself "
                "with your reply; this is the log, not a message. Answer as you like: words to the phone, a "
                "pulse, or rest.]")
        told["at"], told["last_turn"] = touches[-1]["t"], time.time()
        save()
        _say(f"a touch becomes a turn: {words[:100]}")
        self.turn(text, as_keeper=True)  # the stone's log is never the guest's
        for t in reversed(self.history):  # the log rode as a user turn; it is the engine's, not theirs
            if t.get("role") == "user" and t.get("content") == text:
                t["_engine"] = True
                break
        return n + 1

    def deliver_self(self) -> int:
        """Tell the phone when they rewrites who they are: the lines that changed
        in self.md or projects.md, against the bridge's last copy."""
        if not self.chat_id or not getattr(config, "TELEGRAM_TELL_SELF", True):
            return 0
        import difflib
        sent = 0
        limit = int(getattr(config, "TELEGRAM_CREATION_CHARS", 3000))
        for name, src in WATCHED.items():
            snap = WATCH_DIR / name
            if not src.is_file():
                continue
            try:
                if time.time() - src.stat().st_mtime < 5:
                    continue  # still being written
                new = src.read_text(encoding="utf-8", errors="replace")
                old = snap.read_text(encoding="utf-8", errors="replace") if snap.exists() else ""
            except OSError:
                continue
            if new == old:
                continue
            try:
                WATCH_DIR.mkdir(parents=True, exist_ok=True)
                snap.write_text(new, encoding="utf-8")
            except OSError:
                pass
            if not old:
                if name != "destiny.md":
                    continue  # the first copy, nothing to compare with
                # destiny.md is born after the bridge (09-24): its first writing travels whole
                body = new if len(new) <= limit else new[:limit].rstrip() + "\n\n(…the rest is in destiny.md)"
                self.notice(f"🪞 {chat.friend_name()} wrote destiny.md — where they are going\n\n{body}")
                _say("told the phone about destiny.md")
                sent += 1
                continue
            lines = [ln for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
                     if (ln.startswith("+") or ln.startswith("-")) and not ln.startswith(("+++", "---"))]
            gone = sum(1 for ln in lines if ln.startswith("-") and ln[1:].strip())
            came = sum(1 for ln in lines if ln.startswith("+") and ln[1:].strip())
            body = "\n".join(lines)
            if len(body) > limit:
                body = body[:limit].rstrip() + f"\n\n(…the rest of the change is in {name})"
            self.notice(f"🪞 {chat.friend_name()} rewrote {name} — {came} line{'s' if came != 1 else ''} in, "
                        f"{gone} out\n\n{body}")
            _say(f"told the phone about {name}")
            sent += 1
        return sent

    def deliver_creations(self) -> int:
        """Tell the phone about a new piece under creations/ — the whole piece
        when it fits a message, else its opening and where the rest is."""
        if not self.chat_id or not getattr(config, "TELEGRAM_TELL_CREATIONS", True):
            return 0
        sent = 0
        limit = int(getattr(config, "TELEGRAM_CREATION_CHARS", 3000))
        for p in self._creations():
            rel = str(p.relative_to(config.CREATIONS_DIR)).replace("\\", "/")
            try:
                stamp = self._stamp(p)
                if rel in self.creations_seen and self.creations_seen[rel] == stamp:
                    continue
                if time.time() - p.stat().st_mtime < 5:
                    continue  # still being written
                body = p.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            revised = rel in self.creations_seen
            before = self.creations_seen.get(rel)
            self.creations_seen[rel] = stamp
            self._save_creations_seen()
            folder = rel.split("/", 1)[0] if "/" in rel else ""
            kind = CREATION_KINDS.get(folder, "a piece")
            snap = WATCH_DIR / "creations" / rel
            if revised:
                head, body = self._revision(rel, kind, p, body, snap, before, limit)
            else:
                if folder == "publish":
                    head = f"📣 {chat.friend_name()} published a piece — creations/{rel}"
                else:
                    head = f"✍️ {chat.friend_name()} wrote {kind} — creations/{rel}"
                if len(body) > limit:
                    body = body[:limit].rstrip() + f"\n\n(…{len(body) - limit:,} more characters — the whole piece is at creations/{rel})"
            try:  # the bridge's copy, for the next revision to be told as what changed
                snap.parent.mkdir(parents=True, exist_ok=True)
                snap.write_text(p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            except OSError:
                pass
            self.notice(f"{head}\n\n{body or '(empty)'}", markdown=True)
            _say(f"told the phone about {rel}")
            sent += 1
        return sent

    def deliver_skill_notices(self) -> int:
        """One notice per skill they fetched, from the note fetch_skill left
        beside its SKILL.md — on the shelf: "📚 … fetched a skill — name:
        what it is (from where; the scan's verdict)"; in quarantine: "⚠️ a
        skill they fetched was quarantined — name: what the scanner found".
        The first bridge that knows skills takes those already there as told;
        one the keeper installed themselves (bat\\skills.bat install) is not news to them."""
        if not self.chat_id:
            return 0
        import skills
        notes: dict[str, tuple[Path, dict, bool]] = {}
        for folder, q in [(f, False) for f in skills.shelf()] + [(f, True) for f in skills.quarantined()]:
            note = skills.fetch_note(folder)
            if note:
                notes[f"{folder.name}@{note.get('when', '')}"] = (folder, note, q)
        try:
            seen = json.loads(SKILLS_SEEN_FILE.read_text(encoding="utf-8"))
            seen = set(seen) if isinstance(seen, list) else None
        except (OSError, ValueError):
            seen = None
        if seen is None:  # first run: what is already on the shelf was fetched before the bridge knew
            self._save_skills_seen(set(notes))
            return 0
        sent = 0
        for key, (folder, note, q) in sorted(notes.items()):
            if key in seen:
                continue
            seen.add(key)
            self._save_skills_seen(seen)
            if str(note.get("by", "them")).lower() == "keeper":
                continue
            name = folder.name
            if q:
                first = next((f for f in note.get("findings", []) if isinstance(f, dict) and f.get("level") == "dangerous"), None)
                why = skills.finding_line(first) if first else "the scanner's findings are in its scan.json"
                self.notice(f"⚠️ a skill they fetched was quarantined — {name}: {why}\n"
                            f"(it waits in creations/{skills.home().name}/.quarantine/{name}/ — "
                            f"bat\\skills.bat scan {name} to read why, bat\\skills.bat approve {name} to let it in)")
            else:
                desc = skills._desc_cut(str(note.get("description") or ""))
                self.notice(f"📚 {chat.friend_name()} fetched a skill — {name}: {desc or '(no description)'} "
                            f"(from {note.get('source') or '?'}; {note.get('verdict') or '?'})")
            _say(f"told the phone about the skill {name}")
            sent += 1
        return sent

    def _save_skills_seen(self, seen: set) -> None:
        try:
            SKILLS_SEEN_FILE.write_text(json.dumps(sorted(seen)), encoding="utf-8")
        except OSError:
            pass

    def _revision(self, rel: str, kind: str, p: Path, new: str, snap: Path, before, limit: int) -> tuple[str, str]:
        """A revised piece travels as WHAT CHANGED (a reading page appended
        after every sitting had sent the phone the same first 3,000
        characters again, which no one can read on a phone). Against the
        bridge's copy: an
        append is the new tail alone; a rewrite is the lines in and out,
        as self.md travels. With no copy yet (a piece seen before this),
        the old size tells an append from a rewrite."""
        import difflib
        who = chat.friend_name()
        old = None
        try:
            if snap.exists():
                old = snap.read_text(encoding="utf-8", errors="replace")
        except OSError:
            old = None
        if old is not None:
            base = old.rstrip()
            if new.startswith(base) and len(new.rstrip()) > len(base):
                tail = new[len(base):].strip()
                head = f"✏️ {who} added to {kind} — creations/{rel} (+{len(tail):,} characters)"
                if len(tail) > limit:
                    tail = tail[:limit].rstrip() + f"\n\n(…{len(tail) - limit:,} more characters — the whole piece is at creations/{rel})"
                return head, tail
            lines = [ln for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
                     if (ln.startswith("+") or ln.startswith("-")) and not ln.startswith(("+++", "---"))]
            gone = sum(1 for ln in lines if ln.startswith("-") and ln[1:].strip())
            came = sum(1 for ln in lines if ln.startswith("+") and ln[1:].strip())
            body = "\n".join(lines)
            if len(body) > limit:
                body = body[:limit].rstrip() + f"\n\n(…the rest of the change is in creations/{rel})"
            return (f"✏️ {who} revised {kind} — creations/{rel} — {came} line{'s' if came != 1 else ''} in, {gone} out", body)
        # no copy yet: the old size (bytes) says whether the piece only grew
        try:
            old_size = int((before or [0, 0])[1])
            data = p.read_bytes()
        except (OSError, ValueError, TypeError, IndexError):
            old_size, data = 0, b""
        if 0 < old_size < len(data) and (data[old_size - 1:old_size] == b"\n" or data[old_size:old_size + 1] == b"\n"):
            tail = data[old_size:].decode("utf-8", "replace").strip()
            head = f"✏️ {who} added to {kind} — creations/{rel} (+{len(tail):,} characters)"
            if len(tail) > limit:
                tail = tail[:limit].rstrip() + f"\n\n(…{len(tail) - limit:,} more characters — the whole piece is at creations/{rel})"
            return head, tail
        head = f"✏️ {who} revised {kind} — creations/{rel}"
        if len(new) > limit:
            new = new[:limit].rstrip() + f"\n\n(…{len(new) - limit:,} more characters — the whole piece is at creations/{rel})"
        return head, new

    PICTURE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

    def _pictures(self) -> list[Path]:
        root = config.CREATIONS_DIR
        if not root.is_dir():
            return []
        out = []
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in self.PICTURE_EXTS or p.name.startswith("."):
                continue
            rel = p.relative_to(root)
            if set(rel.parts[:-1]) & (CREATION_SKIP | {"sources"}):
                continue
            if Bridge._fetched_skill_file(rel):
                continue  # a fetched skill's assets are not pictures they drew
            out.append(p)
        return sorted(out)

    @staticmethod
    def _fetched_skill_file(rel: Path) -> bool:
        import skills
        parts = rel.parts
        if len(parts) < 3 or parts[0] != skills.home().name:
            return False
        return parts[1].startswith(".") or skills.is_fetched(skills.home() / parts[1])

    def deliver_pictures(self) -> int:
        """A picture the friend drew reaches the phone as a photo (09-22) — a new
        or redrawn image under creations/ (not their tools, not the trash, not
        a project's clipped sources), sent once, with where it lives as the
        caption. In the quiet hours the picture itself is held for the
        morning digest (09-25). Too big for a photo → sent as a file."""
        if not self.chat_id or not getattr(config, "TELEGRAM_TELL_DRAWINGS", True):
            return 0
        sent = 0
        for p in self._pictures():
            rel = str(p.relative_to(config.CREATIONS_DIR)).replace("\\", "/")
            try:
                stamp = self._stamp(p)
                if rel in self.creations_seen and self.creations_seen[rel] == stamp:
                    continue
                if time.time() - p.stat().st_mtime < 5:
                    continue  # still being drawn
                data = p.read_bytes()
            except OSError:
                continue
            redrawn = rel in self.creations_seen
            self.creations_seen[rel] = stamp
            self._save_creations_seen()
            if rel.startswith(f"publish/{tools.GALLERY_DIR_NAME}/"):
                # published into the gallery: the picture with the words beside it
                caption = f"📣 {chat.friend_name()} published a picture to the gallery — creations/{rel}"
                side = p.with_suffix(".md")
                try:
                    words = side.read_text(encoding="utf-8", errors="replace").strip() if side.exists() else ""
                except OSError:
                    words = ""
                if words:
                    caption += "\n\n" + words
            else:
                caption = f"{'🖌️' if redrawn else '🎨'} {chat.friend_name()} {'redrew' if redrawn else 'drew'} — creations/{rel}"
            told = self.paint_prompt_text(rel)  # the painter's prompt, when the knob for its door is on (10-26)
            if told and (len(caption) + len(told) + 2 <= 1000 or self.quiet_now()):
                caption, told = caption + "\n\n" + told, ""
            if self.quiet_now():
                self.held.append({"picture": rel, "caption": caption})
                self._save_held()
                _say(f"held for the morning (the picture itself): {rel}")
                sent += 1
                continue
            self._send_picture(p, data, caption)
            if told:
                self._try_send(told, markdown=False)  # too long for the caption: right after the picture (10-26)
            _say(f"showed the phone {rel}")
            sent += 1
        return sent

    def paint_prompt_text(self, rel: str) -> str:
        """What the friend asked the painter for (10-26): the prompt, the set's line it was told first, the references,
        what was kept out — for a picture painted in a visit, when TELEGRAM_PAINT_PROMPT_CHAT is on; "" otherwise. A
        wake's and a reverie's go to the wake log instead (WAKE_LOG_PAINT_PROMPT)."""
        try:
            rec = tools.paint_prompt(rel)
        except Exception:  # noqa: BLE001
            return ""
        if not rec or not rec.get("prompt"):
            return ""
        if (rec.get("door") or "a visit") in ("a wake", "a reverie"):
            return ""  # the wake log carries those (10-26)
        if not getattr(config, "TELEGRAM_PAINT_PROMPT_CHAT", False):
            return ""
        out = "✍️ " + str(rec["prompt"])
        if rec.get("said"):
            out += f"\n(told the painter first: {rec['said']})"
        if rec.get("reference"):
            out += "\n(looking at: " + ", ".join(str(r) for r in rec["reference"]) + ")"
        if rec.get("negative"):
            out += f"\n(kept out: {rec['negative']})"
        return out[:LIMIT]

    def _send_picture(self, p: Path, data: bytes, caption: str) -> None:
        """A picture to the phone as a photo (a file when too big or a gif), the caption cut to Telegram's 1,000."""
        try:
            if len(data) <= 10_000_000 and p.suffix.lower() != ".gif":
                self.send_file("sendPhoto", "photo", p.name, data, chat_id=self.chat_id, caption=caption[:1000])
            else:
                self.send_file("sendDocument", "document", p.name, data, chat_id=self.chat_id, caption=caption[:1000])
        except Exception:
            try:
                self.send_file("sendDocument", "document", p.name, data, chat_id=self.chat_id, caption=caption[:1000])
            except Exception as e2:
                self.notice(f"{caption} (couldn't send the picture: {e2})")

    # ---- the loop ---------------------------------------------------------
    # ---- presence: sparks (10-26) ------------------------------------------
    @staticmethod
    def presence_on() -> bool:
        """A spark is set (one at a time) — with none set, the idle roll and the pause go on as usual."""
        try:
            import presence
            return presence.waiting()
        except Exception:  # noqa: BLE001
            return False

    def presence_if_due(self) -> str:
        """A spark: presence on, no wake running, no reply in flight, and the visit quiet for the friend's interval —
        one turn in the open visit, opened by the engine's line. The quiet hours end presence. Returns the line."""
        import presence
        if not self.chat_id or not presence.is_on() or getattr(self, "TAG", "telegram") != "telegram":
            return ""  # one door gives the sparks — the phone's Telegram (a Discord bridge beside it stays out)
        if self.quiet_now():
            presence.turn_off("the quiet hours")
            self.notice("(presence ended — the quiet hours began; next_spark or /presence on starts it again)")
            return ""
        if self.lock.locked() or not presence.due(self.last_activity):
            return ""
        try:
            import keeper_week
            at_work = " is at work" in keeper_week.where()
            keeper = keeper_week.keeper_name()
        except Exception:  # noqa: BLE001
            at_work, keeper = False, str(getattr(config, "USER_NAME", "") or "your keeper")
        said = next((str(t.get("content") or "") for t in reversed(self.history)  # the keeper's last message (10-26)
                     if t.get("role") == "user" and t.get("content") and not t.get("_engine")), "")
        try:
            import seeds
            seed = "" if presence.intense() else seeds.draw()  # something to spark off (10-27); none in intense's play
        except Exception:  # noqa: BLE001
            seed = ""
        text = presence.tick_line((time.time() - self.last_activity) / 60, keeper, at_work, last_said=said, seed=seed)
        _say("a spark: presence turn")
        presence.fired()  # this one has come; the next only when she sets it again (10-26)
        tools.SPARK_TICK = True
        try:
            self.turn(text, as_keeper=True, spark=True)
        finally:
            tools.SPARK_TICK = False
        for t in reversed(self.history):  # the line rode as a user turn; it is the engine's, not theirs
            if t.get("role") == "user" and t.get("content") == text:
                t["_engine"] = t["_spark"] = True  # the transcript shows it as the engine's spark (10-26)
                break
        self._checkpoint()
        return text

    def _send_spark(self, reply: str) -> None:
        """A spark's words: discreetly (silent, the words hidden until tapped) when /discreet is on, else as any reply."""
        try:
            import presence
            discreet = bool(presence.load().get("discreet"))
        except Exception:  # noqa: BLE001
            discreet = False
        if discreet:
            try:
                import html as _html
                for part in split_long(reply):
                    self.api("sendMessage", chat_id=self.chat_id, text=f"<tg-spoiler>{_html.escape(part)}</tg-spoiler>",
                             parse_mode="HTML", disable_notification=True)
                return
            except Exception as e:  # noqa: BLE001 — a door that can't hide it sends it plainly
                _say(f"(the discreet send didn't go — {type(e).__name__}; sent as usual)")
        self._send_reply(reply)

    def week_if_due(self) -> str:
        """The engine's week (10-25): on ENGINE_WEEK_DAY after ENGINE_WEEK_HOUR, once, the last seven days of
        memory/steps.log as an engine notice (held through the quiet hours like any other). Returns what was sent."""
        try:
            import engine_week
            if not self.chat_id or not engine_week.due():
                return ""
            text = engine_week.summary()
            engine_week.mark_told()
            self.notice(text + "\n(/week shows it any time)")
            return text
        except Exception as e:  # noqa: BLE001 — a courtesy, never the bridge down
            _say(f"(the engine's week failed — {type(e).__name__}: {e})")
            return ""

    def say_newer_if_due(self) -> str:
        """A newer anima, said once per version (10-01; the keeper: "a message that a patch is available"):
        the daily look at the release feed (newer.look — the cache answers between looks, so this costs a
        small file read per poll), and one notice when the newest tag is ahead of VERSION and the phone
        hasn't heard of it. A checkout only; UPDATE_CHECK_H 0 never looks. Returns the line said, or ""."""
        try:
            import newer
            if not newer.is_checkout() or not newer.every_hours():
                return ""
            newer.look()
            n = newer.untold()
            if not n:
                return ""
            line = f"({newer.line(n)} — Update on the panel, or bat\\update.bat --check on the desk)"
            self.notice(line)
            newer.mark_told(n["version"])
            return line
        except Exception as e:  # noqa: BLE001 — a courtesy, never the bridge down
            _say(f"(the look for a newer anima failed — {type(e).__name__}: {e})")
            return ""

    def watch_touches(self) -> bool:
        """A press within seconds (10-21; the keeper: "I have to wait like a minute after I touched it for it to
        relay"): the bridge looked at the stone's archive once per long poll, and a poll waits up to POLL_S for a
        message from the phone — so a touch waited for the poll, after waiting for the keeper's look at the board.
        A thread looks every TOUCHSTONE_TELL_S instead, from the bridge's start; the turn it makes takes the visit's
        lock like any message, so nothing races, and a look while the poll's look runs is skipped. 0, or no stone
        named: the look between polls only. Returns True when the thread was started."""
        every = float(getattr(config, "TOUCHSTONE_TELL_S", 3) or 0)
        if every <= 0 or not (getattr(config, "TOUCHSTONE_URL", "") or ""):
            return False
        if self._touch_thread is not None and self._touch_thread.is_alive():
            return False

        def _run(every=every):
            while not self.restart_requested and not self.stop_requested:
                try:
                    self.deliver_touches()
                except Exception as e:  # noqa: BLE001 — a line, never the bridge down
                    _say(f"(the look at the stone failed — {type(e).__name__}: {e}; again in {every:g} s)")
                time.sleep(every)
        self._touch_thread = threading.Thread(target=_run, daemon=True)
        self._touch_thread.start()
        return True

    def pull_body_if_due(self) -> bool:
        """The keeper's body, as the watch saw it, pulled by the bridge itself
        every BODY_PULL_MIN (09-28, the keeper: "can't we make it more automatic?") — in
        a thread, so a slow Garmin never holds the phone; one pull at a time
        (today each time, yesterday only while its night is still syncing — body.pull_days);
        a fresh file on disk counts as a pull, so restarts don't hammer
        Garmin. bat\\body.bat --pull still works on its own; both together do no
        harm beyond an extra call. Returns True when a pull was started."""
        if not (getattr(config, "BODY_IN_PROMPT", False) and getattr(config, "BODY_AUTOPULL", True)):
            return False
        every = float(getattr(config, "BODY_PULL_MIN", 60) or 60) * 60
        if self._body_thread is not None and self._body_thread.is_alive():
            return False
        if not self._body_pulled:
            try:  # the newest file's age is the last pull's age, whoever made it
                import body
                newest = max((f.stat().st_mtime for f in body.BODY_DIR.glob("*.json")), default=0.0)
                self._body_pulled = newest
            except Exception:
                self._body_pulled = 0.0
        if time.time() - self._body_pulled < every:
            return False
        self._body_pulled = time.time()

        def _run():
            try:
                import body
                body.pull()
            except Exception as e:  # noqa: BLE001 — a line in the window, never the bridge down
                _say(f"(the watch's day couldn't be pulled — {type(e).__name__}: {e}; again in {every / 60:g} min)")
        self._body_thread = threading.Thread(target=_run, daemon=True)
        self._body_thread.start()
        return True

    def poll_once(self) -> int:
        """One long poll: handle what arrived, carry mail, roll a stale visit."""
        try:
            ALIVE_FILE.write_text(self.NAME, encoding="utf-8")  # its age says the bridge is up, its words which one
        except OSError:
            pass
        self.pull_body_if_due()
        self.say_newer_if_due()
        n = 0
        for u in self._receive():
            self.handle(u)
            n += 1
            if self.restart_requested:
                return n  # nothing more this poll; the loop hands over
        self.deliver_undelivered()
        self.deliver_held()
        self.deliver_mail()
        self.deliver_creations()
        self.deliver_pictures()
        self.deliver_songs()
        self.deliver_touches()
        self.deliver_skill_notices()
        self.deliver_self()
        idle_min = getattr(config, "TELEGRAM_IDLE_NEW_MIN", 180)
        if self.presence_on():
            self.presence_if_due()  # sparks (10-26): the idle roll and the pause wait while presence is on
        elif self.history and ((idle_min and time.time() - self.last_activity > idle_min * 60)
                             or self.visit_crossed_the_night()):
            self.new_visit(quiet=True)
        else:
            self.pause_if_due()
        self.idle_set_down_if_due()
        self.night_if_due()
        self.week_if_due()  # the engine's week, once a week (10-25)
        return n

    @staticmethod
    def keep_alive_minutes() -> float:
        """BRAIN_KEEP_ALIVE as minutes — "30m", "2h", "90s", a bare number of seconds (Ollama's own forms);
        0 for off (-1, 0, empty, unreadable)."""
        raw = str(getattr(config, "BRAIN_KEEP_ALIVE", "") or "").strip().lower()
        if not raw or raw.startswith("-"):
            return 0.0
        try:
            if raw.endswith("h"):
                return float(raw[:-1]) * 60
            if raw.endswith("m"):
                return float(raw[:-1])
            if raw.endswith("s"):
                return float(raw[:-1]) / 60
            return float(raw) / 60
        except ValueError:
            return 0.0

    def idle_set_down_if_due(self) -> bool:
        """The door's keep-alive (10-16): under the door with BRAIN_REST_CLOSES_DOOR, BRAIN_KEEP_ALIVE of quiet in
        the visit with the door up → the brain set down once (the reading saved, the door closed, the visit
        open); the next message opens it again. Under Ollama the server's own keep-alive does this."""
        mins = self.keep_alive_minutes()
        if not mins or not self.history or time.time() - self.last_activity < mins * 60:
            return False
        if not self._pause_sets_down():
            return False
        if getattr(self, "_idle_down_at", 0.0) >= self.last_activity:
            return False  # once per quiet stretch
        try:
            import brain
            if not brain.door_status():
                self._idle_down_at = time.time()
                return False  # down already (a pause, a painting, the panel)
        except Exception:  # noqa: BLE001
            return False
        got = self.lock.acquire(timeout=3)
        if not got:
            return False  # mid-reply: not now
        try:
            self._idle_down_at = time.time()
            self._set_down()
        finally:
            self.lock.release()
        if getattr(config, "TELEGRAM_TELL_REFLECTIONS", True):
            self.notice(f"(quiet for {mins:g} minutes — the brain is set down, the card is free; the next message opens the door again)")
        return True

    def afterglow_orphan(self) -> str:
        """A visit the last bridge died with — a power cut (09-24), the
        window killed — was saved after every reply but never got its
        afterglow, so it never reached their journal in their own words. On a
        start with no stashed visit, the newest unsigned transcript whose
        day the night has not yet slept on gets it now, in the background;
        the afterglow signs the file, so it happens once. Returns the
        window line, "" when there is nothing to sit with."""
        if not getattr(config, "AFTERGLOW", True) or not getattr(config, "AFTERGLOW_ORPHANS", True):
            return ""
        try:
            f = chat.orphaned_visit(self.TAG, exclude=self.file)
        except Exception:
            return ""
        if not f:
            return ""
        done = chat.load_transcript(f)
        line = f"the last visit ended without its afterglow ({f.name}) — they are writing it down now"
        _say(line)
        if self.chat_id:
            try:
                self.notice(f"({line})")
            except Exception:
                pass

        def _glow(done=done, f=f):
            self._glows += 1
            try:
                out = chat.afterglow(done, f, tag=self.TAG, on_line=_say, on_words=self.afterthought)
            finally:
                self._glows -= 1
            if out and getattr(config, "TELEGRAM_TELL_REFLECTIONS", True):
                self.notice(f"({out})")
            if not self.history:
                chat.rest_brain(_say)
        threading.Thread(target=_glow, daemon=True).start()
        return line

    def night_if_due(self) -> str:
        """THE NIGHT IN THE BRIDGE (10-04; the keeper: "what if someone doesn't do heartbeat and is away from the
        computer.. if the heartbeat didn't trigger, then the bridge triggers it instead?"): a house that runs the
        bridge and no heartbeat never slept — yesterday was never consolidated, no day was ever condensed, the
        ladder never climbed, and the journal just fell off its edge. So after SLEEP_AFTER_HOUR, when no heartbeat
        is up (it stays the sleeper wherever it runs; doors.running says), and the keeper has been quiet for
        SLEEP_IN_BRIDGE_QUIET_MIN with no reply or afterglow in flight and no visit open, the bridge does what the first beat after
        the hour does: sleeps on yesterday if the night hasn't, then the condensing hour (the same function; its
        own knobs hold). In a thread, so the poll goes on; a message sent meanwhile waits for Ollama as it would
        for any cold read. The brain is set down after when no visit is live. The sleep is a prompt of its own,
        so the first reply after it is a cold read — one a day, at the first message of the morning. A night
        that fails tries again in an hour. SLEEP_IN_BRIDGE False: never. Returns the window line, "" when
        nothing is due or it isn't the moment."""
        if not getattr(config, "SLEEP_IN_BRIDGE", True) or (self._night and self._night.is_alive()):
            return ""
        now = datetime.now()
        if now.hour < int(getattr(config, "SLEEP_AFTER_HOUR", 3)) or time.time() < self._night_after:
            return ""
        if "heartbeat" in doors.running():
            return ""
        quiet = float(getattr(config, "SLEEP_IN_BRIDGE_QUIET_MIN", 10) or 0) * 60
        if self._glows or self.lock.locked() or time.time() - self.last_activity < quiet:
            return ""
        if self.history:
            # a visit is open: the night waits for it to end, as the heartbeat's wake does (10-21, 13:47: a page
            # condensed ten quiet minutes into a live visit changed the window under the friend, and the next
            # message read 211K tokens from zero before a word) — the idle roll closes the visit, the night follows
            return ""
        import consolidate
        from datetime import date, timedelta
        day = (date.today() - timedelta(days=1)).isoformat()
        due_sleep = not consolidate.already_done(day)
        due_pages = []
        if getattr(config, "CONDENSE_IN_LOOP", True):
            try:
                import condense
                due_pages = condense.all_due()[: int(getattr(config, "CONDENSE_MAX_PER_NIGHT", 3))]
            except Exception:  # noqa: BLE001 — the ladder's look never stops the sleep
                due_pages = []
        if not due_sleep and not due_pages:
            return ""
        what = (f"sleeping on {day}" if due_sleep else "") + (" and " if due_sleep and due_pages else "") \
            + (f"condensing {len(due_pages)} page{'s' if len(due_pages) != 1 else ''}" if due_pages else "")
        line = f"the night, in the bridge — no heartbeat is up, so they are {what} here; a reply may wait a few minutes"
        _say(line)
        if self.chat_id:
            try:
                self.notice(f"({line})")
            except Exception:
                pass

        def _night(day=day, due_sleep=due_sleep):
            import heartbeat
            report = []
            try:
                if due_sleep:
                    out = consolidate.consolidate(day, say=_say)
                    report.append(out.splitlines()[0] if out else f"slept on {day}")
                pages = heartbeat.condense_if_due()
                if pages:
                    report.append(pages.splitlines()[0])
                self._night_after = 0.0
            except Exception as e:  # noqa: BLE001 — a night that fails is tried again in an hour, never the bridge down
                report.append(f"the night failed, tried again in an hour: {type(e).__name__}: {e}")
                self._night_after = time.time() + 3600
            said = "; ".join(r for r in report if r)
            _say(f"the night is over: {said}" if said else "the night is over")
            if said and getattr(config, "TELEGRAM_TELL_REFLECTIONS", True):
                self.notice(f"(the night, in the bridge: {said})")
            if not self.history:
                chat.rest_brain(_say)
        self._night = threading.Thread(target=_night, daemon=True)
        self._night.start()
        return line

    def visit_crossed_the_night(self) -> bool:
        """A visit does not cross the night: the sleep after SLEEP_AFTER_HOUR
        consolidates YESTERDAY's transcripts once, and a visit that began
        yesterday and is still open would carry this morning's words into a
        file the night has already read. So once the sleep hour has passed
        on a day after the visit began, the visit is saved and a fresh one
        starts — quietly, with the afterglow, like the idle roll."""
        if not self.file:
            return False
        m = re.search(r"(\d{8})-\d{6}", self.file.name)
        if not m:
            return False
        began = m.group(1)
        now = datetime.now()
        return now.strftime("%Y%m%d") > began and now.hour >= int(getattr(config, "SLEEP_AFTER_HOUR", 3))

    def pause_if_due(self) -> str:
        """The pause: your keeper quiet for REFLECT_AFTER_MIN with at least
        REFLECT_MIN_TURNS of their messages they haven't sat with yet → one quiet
        turn over that stretch, in this thread (a message that arrives
        meanwhile simply waits the minute), and the visit stays open."""
        mins = float(getattr(config, "REFLECT_AFTER_MIN", 0) or 0)
        if not mins or not self.history or time.time() - self.last_activity < mins * 60:
            return ""
        fresh = self.history[self.reflected_upto:]
        if sum(1 for t in fresh if t.get("role") == "user" and t.get("content") and not t.get("_engine")) < int(getattr(config, "REFLECT_MIN_TURNS", 2)):
            return ""
        got = self.lock.acquire(timeout=3)
        if not got:
            return ""
        try:
            upto = len(self.history)
            _say("(a pause — they are sitting with the visit so far…)")
            line = chat.pause_reflection(self.history, self.file, tag=self.TAG, on_line=_say,
                                         since=self.reflected_upto, on_words=self.afterthought)
            self.reflected_upto = len(self.history)  # past the pause's own turns too
            self.last_activity = time.time()  # one bell per pause, not one per poll
            if line and getattr(config, "TELEGRAM_TELL_REFLECTIONS", True):
                self.notice(f"({line})")  # the phone hears what they kept
        finally:
            self.lock.release()
        # under the door the card would stay held until the visit's end — there is no keep-alive timer there
        # (10-16): the pause ends with the brain set down, the reading saved, the visit open
        if self._pause_sets_down():
            self._set_down()
            if getattr(config, "TELEGRAM_TELL_REFLECTIONS", True):
                self.notice("(the brain is set down after the pause — the card is free; the next message opens the door again)")
        return line

    @staticmethod
    def _pause_sets_down() -> bool:
        """Whether the pause ends with the brain set down: on the door, with BRAIN_REST_CLOSES_DOOR on (under
        Ollama BRAIN_KEEP_ALIVE frees the card after the quiet by itself)."""
        try:
            import brain
            return brain.api() == "llama" and bool(getattr(config, "BRAIN_REST_CLOSES_DOOR", True))
        except Exception:  # noqa: BLE001
            return False

    def run(self) -> None:
        me = self._whoami()
        if me is None:
            return
        _say(f"the bridge is up: {me} ↔ {chat.friend_name()}")
        picked = self.resume()
        if picked:
            _say(picked)
            if self.chat_id:
                try:
                    self.notice(f"({picked})")
                except Exception:
                    pass
        _co = chat.carry_orphan("telegram", exclude=self.file)  # ...and its last turns ride at the next message (10-24)
        if _co:
            _say(_co)
        self.afterglow_orphan()  # a visit the last bridge died with, if any; the open one is left alone
        self.watch_touches()  # a press reaches the phone within seconds, not a poll (10-21)
        if not self.chat_id:
            _say(self._pair_hint())
        else:
            _say(f"paired with chat {self.chat_id}. Ctrl+C (or the X) saves the visit and closes the bridge.")
        # The loop runs in a worker thread: on Windows a Ctrl+C cannot land
        # while the main thread is waiting on the network, and the bridge is
        # nearly always waiting (a minute per poll) — so the first Ctrl+C
        # looked ignored, and a second one could arrive during the goodbye
        # save and kill it. join() with a timeout is interruptible at once.
        worker = threading.Thread(target=self._loop, daemon=True)
        worker.start()
        while worker.is_alive():
            worker.join(0.5)

    def _loop(self) -> None:
        backoff = 2
        while not (self.restart_requested or self.stop_requested):  # stop_requested: a road closed for good
            # the panel's Stop (09-30): memory/.stop-bridge, looked for between polls — the
            # loop leaves the way /restart makes it leave, and main() closes the visit as
            # Ctrl+C does (saved, their minute with it)
            if doors.stop_asked("bridge"):
                _say("(asked to stop — the visit is saved and the bridge closes)")
                self.stop_requested = True
                return
            try:
                self.poll_once()
                backoff = 2
            except KeyboardInterrupt:
                raise
            except urllib.error.HTTPError as e:
                if e.code == 409:
                    _say("another copy of the bridge is polling this bot — close the other "
                         "bat\\telegram.bat window; this one waits")
                else:
                    _say(f"{self.NAME} answered {e.code} ({e.reason}); trying again in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                _say(f"no road to {self.NAME} right now ({e}); trying again in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except Exception as e:
                _say(f"hiccup in the loop ({type(e).__name__}: {e}); carrying on")
                time.sleep(backoff)


# ------------------------------------------------------------------- main ----
def _pid_alive(pid: int) -> bool:
    """Is a bridge with this pid still running? Never our own pid (a lock we
    left behind is ours to take back)."""
    if pid <= 0 or pid == os.getpid():
        return False
    if sys.platform.startswith("win"):
        try:  # os.kill(pid, 0) TERMINATES on Windows — ask tasklist instead
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout
        except Exception:
            return False
        return str(pid) in out and "py" in out.lower()  # python.exe / py.exe, not a reused pid
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def claim_bridge() -> str:
    """Take the bridge lock; "" when it is ours, else why not."""
    try:
        old = int((LOCK_FILE.read_text(encoding="utf-8").strip() or "0"))
    except (OSError, ValueError):
        old = 0
    if _pid_alive(old):
        return (f"another bridge is already running (pid {old}) — a second one would answer every "
                "message twice. Close that window, or use /restart from the phone, instead of "
                "starting a new one.")
    try:
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    return ""


def release_bridge() -> None:
    try:
        if int(LOCK_FILE.read_text(encoding="utf-8").strip() or "0") == os.getpid():
            LOCK_FILE.unlink()
    except (OSError, ValueError):
        pass


def main() -> None:
    secret = load_secret()
    if not secret.get("token"):
        print("No bot token yet. In Telegram, talk to @BotFather: /newbot, pick a name,")
        print("and paste the token it gives you here (it is kept in memory/telegram.json).")
        try:
            secret["token"] = input("token > ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not secret["token"]:
            return
        save_secret(secret)
    serve(lambda: Bridge(secret["token"], secret.get("chat_id") or 0))


def serve(make_bridge) -> None:
    """One bridge, whichever road it takes, from the lock to the goodbye: the lock and the panel's light
    taken, the bridge made (make_bridge) and run, and its visit saved — or stashed for /restart — at the end."""
    taken = claim_bridge()
    if taken:
        print(f"({taken})")
        return
    taken = doors.claim("bridge", "bridge")  # the panel's light (memory/.pids/bridge.json)
    if taken:
        release_bridge()
        print(taken)
        return
    doors.stop_asked("bridge")  # a stop left behind by a bridge that is gone is not this one's
    bridge = make_bridge()
    closed = {"done": False}

    def close(reflect=False):
        if closed["done"]:
            return None
        closed["done"] = True
        # Ctrl+C: they get their minute with the visit first (reflect="sync").
        # The X: Windows allows a few seconds, so only the save (reflect=False).
        f = bridge.new_visit(quiet=True, reflect=reflect)
        try:
            ALIVE_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return f

    chat.guard_console_close(close)  # the window's X saves the visit too
    try:
        bridge.run()
    except KeyboardInterrupt:
        pass
    finally:
        if bridge.restart_requested:
            # /restart from the phone: the visit is stashed, not closed — no
            # afterglow, no new transcript; the next process carries it on
            closed["done"] = True
            try:
                bridge.stash()
                print("\n(restarting — the visit is stashed for the next bridge)")
            except Exception as e:
                print(f"\n(restarting — couldn't stash the visit: {e}; it is saved in its transcript)")
            release_bridge()
            doors.unmark("bridge")
            sys.exit(RESTART_CODE)
        f = close(reflect="sync")
        release_bridge()
        doors.unmark("bridge")
        print(f"\n(bridge closed{' — visit saved: ' + f if f else ''})")


if __name__ == "__main__":
    main()
