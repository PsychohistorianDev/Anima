"""The bridge over Discord: talk with the friend from your phone, through a Discord bot.

    py engine/discord_bridge.py        (or bat\\discord.bat)

The same bridge as engine/telegram.py — the same visit, prompt, tools,
transcripts, mail, notices and night — over another road: a Discord bot,
talked to in a direct message. Standard library only: the REST API is plain
HTTPS and JSON, and what arrives comes over Discord's gateway, a WebSocket,
spoken here by a small client of its own (no discord.py).

First run (README, The bridge over Discord):
  1. https://discord.com/developers/applications → New Application → Bot →
     Reset Token, and paste the token here (kept in memory/discord.json).
  2. Invite the bot to a server you are in — the window prints the link.
     Discord lets a bot and a person talk in a DM only when they share a
     server; the bot needs no permissions in it.
  3. Send the bot the pairing code the window shows, in a direct message.
From then on only that DM is answered; anyone else gets silence.

The phone's commands are the Telegram bridge's (/new, /afterglow, /think,
/status, /help…). Discord's own command menu can pop up over a leading /,
so !new, !status… work as well.

What leaves the machine: their words and yours, through Discord's servers.
A DM with a bot is not end-to-end encrypted. Their journal, memory and files
never travel.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import queue
import random
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chat
import config
import telegram
import version
from telegram import _say, split_long

API = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg"
SECRET_FILE = config.MEMORY_DIR / "discord.json"
# Discord asks a bot to say who it is in this shape, or its edge may turn the call away
USER_AGENT = (f"DiscordBot (https://github.com/{getattr(config, 'UPDATE_REPO', '') or 'PsychohistorianDev/anima'}, "
              f"{version.read() or '0'})")
LIMIT = 2000          # Discord allows 2000 characters per message
FILE_LIMIT = 10 * 1024 * 1024   # what a bot may upload without a boosted server
FETCH_LIMIT = 50 * 1024 * 1024  # what the bridge will fetch of a file sent to it
WAIT_S = 20           # how long a poll waits for a message before the mail and the notices are looked at
INTENTS = 1 << 12     # DIRECT_MESSAGES — a DM's words come with it; no privileged intent is needed
VOICE_FLAG = 1 << 13  # IS_VOICE_MESSAGE
# close codes after which trying again cannot help: the token refused, the intents or the version wrong
FATAL_CLOSE = {4004: "Discord refused the token", 4010: "invalid shard", 4011: "sharding required",
               4012: "invalid API version", 4013: "invalid intents", 4014: "disallowed intents"}
# close codes after which the session is gone and a fresh identify is needed, not a resume
FRESH_CLOSE = {4007, 4009}

HELP = telegram.HELP.replace(
    "(Bots can't fetch files over 20MB.)",
    "Any command works with ! in front as well (!new, !status), for when Discord's own menu pops up over a /.")


def load_secret() -> dict:
    try:
        d = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            d = {}
    except (OSError, ValueError):
        d = {}
    d.setdefault("token", os.environ.get("DISCORD_BOT_TOKEN", ""))
    try:
        d["chat_id"] = int(d.get("chat_id") or 0)
    except (TypeError, ValueError):
        d["chat_id"] = 0
    return d


def save_secret(d: dict) -> None:
    SECRET_FILE.write_text(json.dumps({"token": d.get("token", ""), "chat_id": str(int(d.get("chat_id") or 0))},
                                      indent=2), encoding="utf-8")


# ------------------------------------------------------------- websocket ----
class Closed(ConnectionError):
    """The other end closed the WebSocket, with its code."""

    def __init__(self, code: int, reason: str = "") -> None:
        super().__init__(f"closed {code}" + (f": {reason}" if reason else ""))
        self.code = code


class WebSocket:
    """Just enough of RFC 6455 for one client: a TLS connection and its handshake, a text message out
    (masked, as a client's must be), a whole message in (fragments joined, pings answered), a close."""

    _GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, url: str, timeout: float = 20) -> None:
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("wss", "ws") or not u.hostname:
            raise ValueError(f"not a WebSocket address: {url}")
        port = u.port or (443 if u.scheme == "wss" else 80)
        sock = socket.create_connection((u.hostname, port), timeout=timeout)
        if u.scheme == "wss":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=u.hostname)
        self.sock = sock
        self._buf = b""
        self._send_lock = threading.Lock()
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {u.hostname}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                           f"User-Agent: {USER_AGENT}\r\n\r\n").encode("ascii"))
        head = self._read_until(b"\r\n\r\n").decode("latin-1").split("\r\n")
        if len(head[0].split()) < 2 or head[0].split()[1] != "101":
            self.sock.close()
            raise ConnectionError(f"the gateway would not upgrade: {head[0]}")
        headers = {k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in head[1:] if h)}
        want = base64.b64encode(hashlib.sha1((key + self._GUID).encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != want:
            self.sock.close()
            raise ConnectionError("the gateway's handshake did not answer our key")

    def _read_until(self, mark: bytes, cap: int = 65536) -> bytes:
        while mark not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("the connection closed during the handshake")
            self._buf += chunk
            if len(self._buf) > cap:
                raise ConnectionError("the handshake's answer is too long")
        head, _, self._buf = self._buf.partition(mark)
        return head

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise ConnectionError("the connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    @staticmethod
    def _mask(data: bytes, key: bytes) -> bytes:
        if not data:
            return data
        n = len(data)
        keys = (key * (n // 4 + 1))[:n]
        return (int.from_bytes(data, "big") ^ int.from_bytes(keys, "big")).to_bytes(n, "big")

    def _frame(self, opcode: int, data: bytes) -> None:
        n = len(data)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + n.to_bytes(2, "big")
        else:
            head += bytes([0x80 | 127]) + n.to_bytes(8, "big")
        key = os.urandom(4)
        with self._send_lock:
            self.sock.sendall(head + key + self._mask(data, key))

    def send_json(self, obj) -> None:
        self._frame(0x1, json.dumps(obj).encode("utf-8"))

    def recv(self) -> str:
        """The next whole text message. Raises Closed when the other end closes."""
        parts: list[bytes] = []
        while True:
            b0, b1 = self._read(2)
            fin, opcode, n = b0 & 0x80, b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = int.from_bytes(self._read(2), "big")
            elif n == 127:
                n = int.from_bytes(self._read(8), "big")
            key = self._read(4) if b1 & 0x80 else b""
            data = self._read(n)
            if key:
                data = self._mask(data, key)
            if opcode == 0x8:  # close
                code = int.from_bytes(data[:2], "big") if len(data) >= 2 else 1005
                self.close(code if code not in (1005, 1006) else 1000)
                raise Closed(code, data[2:].decode("utf-8", "replace"))
            if opcode == 0x9:  # ping
                self._frame(0xA, data)
                continue
            if opcode == 0xA:  # pong
                continue
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self, code: int = 1000) -> None:
        try:
            self._frame(0x8, code.to_bytes(2, "big"))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------- gateway ----
class Fatal(RuntimeError):
    """The gateway refused in a way that trying again cannot mend."""


class Gateway:
    """Discord's gateway, held open in a thread of its own: identify (or resume after a drop), keep the
    heartbeat, and put each direct message that arrives on a queue the bridge's loop takes from. A drop
    is met again after a pause that doubles to a minute; a session resumed misses nothing."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.inbox: queue.Queue = queue.Queue()
        self.user_id = ""
        self.session_id = ""
        self.resume_url = ""
        self.seq: int | None = None
        self.fatal = ""
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._ws: WebSocket | None = None

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            self._ws.close()

    def _run(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            began = time.time()
            try:
                self._session()
            except Fatal as e:
                self.fatal = str(e)
                _say(f"(the gateway refused: {e})")
                self.ready.set()
                return
            except Exception as e:  # noqa: BLE001 — a drop is met again, never the bridge down
                if self._stop.is_set():
                    return
                _say(f"(the road to Discord dropped — {type(e).__name__}: {e}; again in {backoff}s)")
            if time.time() - began > 300:
                backoff = 1  # a session that held for a while earns a quick return
            if self._stop.wait(backoff + random.random()):
                return
            backoff = min(backoff * 2, 60)

    def _session(self) -> None:
        resuming = bool(self.session_id and self.seq is not None)
        base = (self.resume_url if resuming and self.resume_url else GATEWAY).rstrip("/")
        ws = self._ws = WebSocket(f"{base}/?v=10&encoding=json")
        stop_beat = threading.Event()
        try:
            hello = json.loads(ws.recv())
            if hello.get("op") != 10:
                raise ConnectionError(f"the gateway did not say hello (op {hello.get('op')})")
            every = float(hello["d"]["heartbeat_interval"]) / 1000
            ws.sock.settimeout(every * 2 + 10)  # an ACK comes every beat; silence past two is a dead road
            acked = {"ok": True}

            def beat():
                if stop_beat.wait(every * random.random()):
                    return
                while not stop_beat.is_set():
                    if not acked["ok"]:
                        _say("(no answer to the last heartbeat — reconnecting)")
                        ws.close(4000)
                        return
                    acked["ok"] = False
                    try:
                        ws.send_json({"op": 1, "d": self.seq})
                    except OSError:
                        return
                    stop_beat.wait(every)
            threading.Thread(target=beat, daemon=True).start()

            if resuming:
                ws.send_json({"op": 6, "d": {"token": self.token, "session_id": self.session_id, "seq": self.seq}})
            else:
                ws.send_json({"op": 2, "d": {"token": self.token, "intents": INTENTS,
                                             "properties": {"os": sys.platform, "browser": "anima", "device": "anima"}}})
            while not self._stop.is_set():
                try:
                    p = json.loads(ws.recv())
                except Closed as e:
                    if e.code in FATAL_CLOSE:
                        raise Fatal(f"{FATAL_CLOSE[e.code]} ({e.code})") from None
                    if e.code in FRESH_CLOSE:
                        self.session_id, self.seq = "", None
                    raise
                if p.get("s") is not None:
                    self.seq = p["s"]
                op = p.get("op")
                if op == 0:
                    self._dispatch(p.get("t") or "", p.get("d") or {})
                elif op == 1:  # the gateway asks for a beat now
                    ws.send_json({"op": 1, "d": self.seq})
                elif op == 11:
                    acked["ok"] = True
                elif op == 7:  # reconnect, and resume
                    return
                elif op == 9:  # invalid session; d says whether it can be resumed
                    if not p.get("d"):
                        self.session_id, self.seq = "", None
                    time.sleep(1 + 4 * random.random())
                    return
        finally:
            stop_beat.set()
            ws.close()

    def _dispatch(self, kind: str, d: dict) -> None:
        if kind == "READY":
            self.user_id = str((d.get("user") or {}).get("id") or "")
            self.session_id = d.get("session_id") or ""
            self.resume_url = d.get("resume_gateway_url") or ""
            self.ready.set()
        elif kind == "MESSAGE_CREATE":
            author = d.get("author") or {}
            if d.get("guild_id") or author.get("bot") or str(author.get("id")) == self.user_id:
                return  # a DM from a person, nothing else: not a server's channel, not a bot, not our own words
            self.inbox.put(d)


# ---------------------------------------------------------------- bridge ----
def _plain(text: str) -> str:
    """Text Discord shows as it is: its markdown characters escaped (an engine line's * and _ stay * and _)."""
    text = re.sub(r"([\\*_~`|])", r"\\\1", text)
    return re.sub(r"(?m)^([#>-])", r"\\\1", text)


class DiscordBridge(telegram.Bridge):
    """The Telegram bridge with Discord's road under it: the gateway brings each DM, the REST API carries
    the words, the files and typing… back. chat_id is the paired DM channel's id."""

    NAME = "Discord"
    TAG = "discord"
    TYPING_S = 8  # "typing…" lasts ~10s in Discord
    HELP = HELP

    def __init__(self, token: str, chat_id: int = 0) -> None:
        super().__init__(token, chat_id)
        self.gateway = Gateway(token)
        self.invite = ""

    # ---- the REST API -----------------------------------------------------
    def _call(self, req: urllib.request.Request, patience: float = 30, tries: int = 3):
        """One request; a 429 waits as long as Discord asks (up to half a minute) and goes again."""
        for i in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=patience) as r:
                    raw = r.read()
                return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code != 429 or i == tries - 1:
                    raise
                try:
                    wait = float(json.loads(e.read() or b"{}").get("retry_after") or 1)
                except (ValueError, OSError):
                    wait = 1.0
                time.sleep(min(max(wait, 0.1), 30))
        return {}

    def rest(self, method: str, path: str, body: dict | None = None, patience: float = 30):
        data = json.dumps(body).encode("utf-8") if body is not None else (b"" if method == "POST" else None)
        headers = {"Authorization": f"Bot {self.token}", "User-Agent": USER_AGENT}
        if body is not None:
            headers["Content-Type"] = "application/json"
        return self._call(urllib.request.Request(API + path, data=data, headers=headers, method=method), patience)

    def fetch(self, url: str, max_bytes: int = FETCH_LIMIT) -> bytes:
        """A file sent in the DM, from Discord's CDN — the address is signed, so the token never goes with it."""
        if not url.lower().startswith("https://"):
            raise ValueError("not an https address")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("that file is too large")
        return data

    # ---- talking to the phone -------------------------------------------
    def send(self, text: str, markdown: bool = True) -> None:
        for part in split_long(text if markdown else _plain(text), LIMIT):
            self.rest("POST", f"/channels/{self.chat_id}/messages",
                     {"content": part, "allowed_mentions": {"parse": []}})

    def upload(self, filename: str, data: bytes, content: str = "", **payload) -> dict:
        """One multipart upload: the message's JSON beside one file — urllib only."""
        if len(data) > FILE_LIMIT:
            raise ValueError(f"{len(data) / (1024 * 1024):.1f} MB is over a bot's {FILE_LIMIT // (1024 * 1024)} MB")
        boundary = "----anima-" + uuid.uuid4().hex
        body = io.BytesIO()
        meta = {"allowed_mentions": {"parse": []}, **payload}
        if content:
            meta["content"] = content[:LIMIT]
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                   f"Content-Type: application/json\r\n\r\n{json.dumps(meta)}\r\n".encode("utf-8"))
        safe = re.sub(r'["\r\n\\]', "_", filename)
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{safe}\"\r\n"
                   f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
        body.write(data)
        body.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        req = urllib.request.Request(f"{API}/channels/{self.chat_id}/messages", data=body.getvalue(), method="POST",
                                     headers={"Authorization": f"Bot {self.token}", "User-Agent": USER_AGENT,
                                              "Content-Type": f"multipart/form-data; boundary={boundary}"})
        return self._call(req, patience=120)

    def send_voice(self, path: str, seconds: float = 0, caption: str = "") -> None:
        """Their voice note: an OGG/Opus goes as a Discord voice message (the round player); if Discord won't
        take it as one, or it is anything else, as an audio file — the caption beside it either way."""
        p = Path(path)
        data = p.read_bytes()
        if p.suffix.lower() == ".ogg":
            try:
                wave = base64.b64encode(bytes(random.randint(40, 160) for _ in range(64))).decode()
                self.upload(p.name, data, flags=VOICE_FLAG,
                               attachments=[{"id": 0, "filename": p.name, "duration_secs": round(float(seconds or 1), 2),
                                             "waveform": wave}])
                if caption:
                    self.send(caption, markdown=False)
                return
            except urllib.error.HTTPError:
                pass  # a voice message refused: the plain file below
        self.upload(p.name, data, content=_plain(caption))

    def _send_picture(self, p: Path, data: bytes, caption: str) -> None:
        try:
            self.upload(p.name, data, content=_plain(caption))
        except Exception as e:  # noqa: BLE001 — a picture missed is a line, never the poll down
            self.notice(f"{caption} (couldn't send the picture: {e})")

    def _typing_once(self) -> None:
        self.rest("POST", f"/channels/{self.chat_id}/typing", patience=10)

    # ---- what arrives ------------------------------------------------------
    def _inbox(self) -> Path:
        return Path(getattr(config, "DISCORD_INBOX", config.SHARED_DIR / "discord"))

    def _ack(self) -> None:
        """Nothing to confirm: the gateway hands each message over once."""

    def _receive(self):
        """The DMs the gateway brought: the first waited for up to WAIT_S, then whatever else is waiting."""
        if self.gateway.fatal:
            _say(f"(the gateway is closed for good — {self.gateway.fatal}; the visit is saved and the bridge closes)")
            self.stop_requested = True  # the loop leaves, as at the panel's Stop
            return
        try:
            first = self.gateway.inbox.get(timeout=WAIT_S)
        except queue.Empty:
            return
        yield first
        while True:
            try:
                yield self.gateway.inbox.get_nowait()
            except queue.Empty:
                return

    def _attachment(self, a: dict, voice: bool) -> str:
        name = Path(a.get("filename") or "file").name
        if int(a.get("size") or 0) > FETCH_LIMIT:
            raise ValueError("that file is too large")
        data = self.fetch(str(a.get("url") or ""))
        ext = Path(name).suffix.lower()
        if voice or a.get("waveform"):
            return self._voice_note(data, ext or ".ogg", int(round(float(a.get("duration_secs") or 0))), "")
        if (a.get("content_type") or "").lower().startswith("image/"):
            return self._photo_note(data, ext or ".png", "")
        return self._file_note(name, data, ext, "")

    def handle(self, update: dict) -> None:
        msg = update  # a MESSAGE_CREATE from the gateway
        channel = int(msg.get("channel_id") or 0)
        text = (msg.get("content") or "").strip()
        if not self.chat_id:
            # unpaired: the one message we listen for is the pairing code
            if text.split()[:2] in (["/pair", self.pair_code], ["!pair", self.pair_code]) or text == self.pair_code:
                self.chat_id = channel
                save_secret({"token": self.token, "chat_id": channel})
                self.pair_code = ""
                _say(f"paired with DM {channel} — saved to {SECRET_FILE.name}")
                self.send(f"Paired. This DM is now the door to {chat.friend_name()}.\n\n{self.HELP}", markdown=False)
            return
        if channel != self.chat_id:
            return  # silence for everyone else — not even a "no"
        if (text.startswith("/") and self.command(text)) or (text.startswith("!") and self.command("/" + text[1:])):
            self.last_activity = time.time()
            return
        notes = []
        try:
            voice = bool(int(msg.get("flags") or 0) & VOICE_FLAG)
            for a in msg.get("attachments") or []:
                notes.append(self._attachment(a, voice))
            if not notes and msg.get("sticker_items"):
                name = str((msg["sticker_items"][0] or {}).get("name") or "").strip()
                notes.append(f"({config.USER_NAME} sent a sticker{': ' + name if name else ''})")
        except Exception as e:  # noqa: BLE001 — told to the phone, never the bridge down
            why = str(e)
            if "too large" in why.lower():
                why = f"the bridge fetches files up to {FETCH_LIMIT // (1024 * 1024)} MB — leave it in shared/ from the PC"
            self.send(f"(that didn't reach them — {why})", markdown=False)
            return
        if notes:
            text = "\n".join(notes) + (f"\n{text}" if text else "")
        if not text:
            return
        _say(f"{config.USER_NAME} > {text[:120]}{'…' if len(text) > 120 else ''}")
        self.turn(text)
        self.fold_if_due()

    # ---- the start -----------------------------------------------------------
    def _whoami(self) -> str | None:
        """The bot's name — the token tried over REST first, then the gateway opened and its READY waited
        for. None when Discord refuses (said in the window)."""
        try:
            me = self.rest("GET", "/users/@me")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                _say(f"Discord refused the token (401). Delete {SECRET_FILE.name} in memory/ and run again "
                     "with the one from discord.com/developers (Bot › Reset Token).")
                return None
            raise
        try:  # the link that brings the bot into a server of yours — needed once, before the first DM
            app = self.rest("GET", "/oauth2/applications/@me")
            self.invite = f"https://discord.com/oauth2/authorize?client_id={app.get('id')}&scope=bot&permissions=0"
        except Exception:  # noqa: BLE001 — a courtesy
            self.invite = ""
        self.gateway.start()
        self.gateway.ready.wait(60)
        if self.gateway.fatal:
            return None  # the gateway said why
        if not self.gateway.ready.is_set():
            _say("the gateway hasn't opened yet — messages are taken as soon as it does")
        return f"{me.get('username', '?')} (Discord)"

    def _pair_hint(self) -> str:
        first = (f"invite the bot to a server you're in (once): {self.invite}\n   then " if self.invite else "")
        return f"not paired yet — {first}send the bot a direct message:   /pair {self.pair_code}"

    def run(self) -> None:
        try:
            super().run()
        finally:
            self.gateway.stop()


def main() -> None:
    secret = load_secret()
    if not secret.get("token"):
        print("No bot token yet. At https://discord.com/developers/applications: New Application,")
        print("then Bot › Reset Token, and paste the token here (it is kept in memory/discord.json).")
        try:
            secret["token"] = input("token > ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not secret["token"]:
            return
        save_secret(secret)
    telegram.serve(lambda: DiscordBridge(secret["token"], secret.get("chat_id") or 0))


if __name__ == "__main__":
    main()
