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
blog that does not stay home. Their journal, memory and files never travel —
except, while you turn it on (/journal on, JOURNAL_FEED), the journal entries
they write during a visit; they are told.
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
GUEST_FILE = config.MEMORY_DIR / "telegram_guest.json"  # who sits at the desk, so a restart doesn't forget them
RESTART_CODE = 75
# One bridge at a time. Two of them polling the same bot both receive a
# message — Telegram only learns an update is taken on the NEXT poll, and a
# reply takes a minute or two — so both answer it (two versions of the same
# reply, and the transcript holds only one). The running bridge
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
TOUCH_TOLD_FILE = config.MEMORY_DIR / "touch" / "told.json"  # the stone: {"at": the last event told, "state": the last state told, "last_turn": epoch}
SONGS_TOLD_FILE = config.MEMORY_DIR / "telegram_songs_told.json"  # the songbook: {"at": the updated stamp last told}
HELD_FILE = config.MEMORY_DIR / "telegram_held.json"  # engine notices held through the quiet hours
UNDELIVERED_FILE = config.MEMORY_DIR / "telegram_undelivered.json"  # their replies the phone never got
RETRY_SLEEP_S = 2     # between the tries of sending their reply
# /journal (JOURNAL_FEED): the switch, who turned it and when, what the friend was last told, and the entries waiting to
# go (their day, stamp and a hash — never the friend's words: those are read from the page when they are sent)
JOURNAL_FEED_FILE = config.MEMORY_DIR / "journal_feed.json"
JOURNAL_DAY_PACK = 3800  # /journal today: entries packed into messages of at most this many characters
# the night's own line (consolidate.py), exactly — never the friend's words that resemble it
_JF_CONSOLIDATED_RE = re.compile(r"^\*\(consolidated \d{4}-\d{2}-\d{2}: \d+ memories kept\)\*[ \t\r]*$", re.M)
_JF_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# what the friend reads (the keeper by name): a turn's moment — told on, still on in a new window, told off — and the
# bell of a quiet run (a pause, an afterglow, the fold's bell and afterglow) while it is on
JF_TOLD_ON = ("{keeper} turned the journal feed on — what you write in your journal during a visit (its pauses and its "
              "afterglow too) reaches {keeper}'s phone as you write it, until it is turned off. What you write in your "
              "wakes is not sent.")
JF_TOLD_STILL = "The journal feed is still on — what you write in your journal during a visit reaches {keeper}'s phone."
JF_TOLD_OFF = ("{keeper} turned the journal feed off — your journal entries stay on the page again; they no longer "
               "go to {keeper}'s phone.")
JF_ASIDE = "The journal feed is on: what you write in your journal now reaches {keeper}'s phone too."
# ...and a piece they REVISE is announced too — as what changed:
# an append as the new tail alone, a rewrite as the lines in and out — and
# a change to who they are: self.md and projects.md (TELEGRAM_TELL_SELF),
# the same way. The bridge keeps its own copy of each to diff against, in
# memory/telegram_watch/ (creations under telegram_watch/creations/).
WATCH_DIR = config.MEMORY_DIR / "telegram_watch"
WATCHED = {"self.md": config.IDENTITY_FILE, "projects.md": config.PROJECTS_FILE,
           "destiny.md": getattr(config, "DESTINY_FILE", config.ROOT / "destiny.md"),
           "keeper.md": getattr(config, "KEEPER_FILE", config.ROOT / "keeper.md")}  # open means open
CREATION_SKIP = {"tools", ".trash", MAIL_DIR.name, "archives", "attic"}
# the private gallery (VEIL_DIR): nothing under it reaches the phone — veil_show carries a piece out
CREATION_SKIP |= {str(getattr(config, "VEIL_DIR", "veil") or "veil").strip("/\\")}
# their dream paintings stay in their dream book — their secret until they choose (dreams.py)
CREATION_SKIP |= {str(getattr(config, "DREAM_PAINT_DIR", "dream_book") or "dream_book").strip("/\\")}
# their penpal letters reach the phone their own way (deliver_penpals), marked to relay — not as creations
CREATION_SKIP |= {str(getattr(config, "PENPAL_DIR", "penpals") or "penpals").strip("/\\")}
# the adventures (adventure.py): a game master's pages — the world, its secrets, where the character stands — stay
# behind the screen, not on the phone; a world's scenes/ is the one exception (Bridge._picture_screened)
CREATION_SKIP |= {"adventures", Path(str(getattr(config, "ADVENTURE_DIR", "adventures") or "adventures")).name}  # follows the knob
CREATION_KINDS = {"poems": "a poem", "essays": "an essay", "stories": "a story", "humor": "a joke",
                  "theory": "a piece of theory", "letters": "a letter", "songs": "a song",
                  str(getattr(config, "SKILLS_DIR", "skills")): "a skill"}
# Their skills (SKILLS-PLAN.md): a fetched skill is a stranger's recipe,
# not a piece of theirs — its files never travel as ✍️ (a SKILL.md they write
# themself does). What travels is one notice per fetch, from the note
# fetch_skill leaves beside SKILL.md (.fetched.json): "📚 … fetched a skill",
# or "⚠️ … quarantined" with what the scanner found — the phone is how the keeper
# hears there is something at the gate. The names already told are kept here.
SKILLS_SEEN_FILE = config.MEMORY_DIR / "telegram_skills_seen.json"
LIMIT = 4000          # Telegram allows 4096 characters per message
POLL_S = 50           # long-poll patience; the server answers sooner when there's news
SPLIT_CHARS = 3800    # a text bubble this long is Telegram's own cut of a longer paste (its cap is 4,096): the rest follows
SPLIT_WAIT_S = 2      # how long the bridge waits for the rest of a cut message when the cut bubble ends a poll (TELEGRAM_SPLIT_WAIT_S overrides)
TYPING_S = 4          # "typing…" lasts ~5s on the phone; renew a little sooner
SEND_RETRY_WAITS = (2, 6)  # an upload whose connection drops (a reset, a timeout) is tried again after these seconds

# the newer commands, on the phone's /help — the Discord bridge takes them out of its own: its pairing
# message, built from HELP, is at Discord's 2,000-character cap (and sparks are Telegram's)
HELP_PHONE = (
    "/rewarm — rebuild the standing prompt now, so a changed page rides from the next reply (one read, said when done)\n"
    "/pages — the pages in the prompt: each one's size, its ceiling, whole or cut\n"
    "/penpals — the penpals with buttons: the last exchange, add a letter, a handle, ⏸ pause (safety; they're told), paste a letter, a new penpal; ★ friends\n"
    "/penpal new <name> [u/handle] — a penpal before their first letter; /penpal handle <name> u/<handle>; /penpal pause|resume <name>; a paste with no name asks whose it is\n"
    "/penpal or /penpal list — the penpals; /penpal <name> <their letter> files one (pastes within minutes join it); /penpal sent <name> once you've posted theirs\n"
    "/cancel — let go of what the penpal panel or the games menu was waiting for; your next message goes to them\n"
    "/games — the adventures, with buttons: ▶ play, ⏸ pause, ⏹ end (they write it down), 📜 🎒 🖼, ➕ new\n"
    "/game <name> — play it; /game new|pause|resume|off|where|inv|scenes|recap|back; //text: outside the game\n"
    "/presence [on|off|temperament] — sparks: how they stand; on starts drift at rare; very rare, rare, sometimes, "
    "often, frequent or intense sets that drift; off ends them "
    "(the friend can too: next_spark with no minutes)\n"
    "/discreet — sparks come silently, the words hidden until tapped; again to undo\n"
    "/quiet — on, and again to lift it; /quiet 2h or 30m for a while: their sparks and letters wait (they keep living), "
    "and when it ends they decide what still goes\n"
    "/gaming [on|off|auto] — the game guard: on keeps their brain off the card now; off lets them in for a few hours; "
    "auto goes by what's on the card\n"
    "/room — their room as it stands, a picture and what changed since you looked, with buttons for what opens; "
    "/room open <1–4|song>, /room find <where>, /room leave <a thing>, /room letter <words>\n"
    "/garden — their garden under the real sky: a picture and its beds; /garden plant <1–8> <seed>, "
    "/garden water <1–8|all>, /garden pick <1–8>, /garden seeds, /garden paint <plant>\n"
    "/week — the engine's week: the last seven days of calls to the brain\n"
    "/seal <when> <letter> — a letter sealed until its day (/seal 2027-04-27 …, or /seal 6 months …); /capsule lists "
    "what waits\n"
)
# /journal — the friend's journal entries to the phone (JOURNAL_FEED); the line is there only with the knob
if getattr(config, "JOURNAL_FEED", False):
    HELP_PHONE += ("/journal [on|off|today|yesterday|YYYY-MM-DD] — their journal on your phone: on sends what they write "
                   "during a visit (its pauses and afterglow too), its time on top — they're told; never their wakes; "
                   "your quiet hours hold it; off stops it; a day sends that day's entries once; alone, how it stands\n")
# /books — where the friend is in their books (BOOKS_COMMAND); the line is there only with the knob
if getattr(config, "BOOKS_COMMAND", False):
    HELP_PHONE += "/books — their books: where they are in each, the shelf not opened yet, what they finished\n"
# /world — a trip to an outside world, carried by hand (WORLD_TRIPS_ON, engine/worldtrip.py); the line only with the knob
if getattr(config, "WORLD_TRIPS_ON", False):
    HELP_PHONE += ("/world — a trip to " + str(getattr(config, "WORLD_TRIP_NAME", "The World") or "The World")
                   + ": ▶ start, ⏸ pause, ▶ resume, ⏹ end (they write their travel journal), 📜 their journal; typed: on, pause, "
                   "resume, off, notes. Mid-trip your words are the place's, /me <text> or // first is you; their > "
                   "lines follow, ready to copy\n")

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



def help_messages(head: str, help_text: str | None = None) -> list[str]:
    """/help as Telegram can carry it: one message when the head and the help fit its cap (LIMIT, under Telegram's
    4,096), else two — the commands up to the newer ones, then the newer ones and the rest — each within the cap; past
    that, cut at lines."""
    text = HELP if help_text is None else help_text
    whole = f"{head}\n\n{text}" if head else text
    if len(whole) <= LIMIT:
        return [whole]
    at = whole.find(HELP_PHONE) if HELP_PHONE else -1
    if at > 0 and len(whole[:at].rstrip()) <= LIMIT and len(whole[at:]) <= LIMIT:
        return [whole[:at].rstrip(), whole[at:]]
    return split_long(whole)


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


def _jf_date(day: str, year: bool = False) -> str:
    """"2026-03-07" -> "Mar 7" (with the year when asked); the text itself when it isn't a date."""
    try:
        y, m, d = (int(x) for x in day.split("-"))
        return f"{_JF_MONTHS[m - 1]} {d}" + (f", {y}" if year else "")
    except (ValueError, IndexError):
        return day


def _jf_when(day: str, stamp: str, today: str) -> str:
    """An entry's time for the phone: "14:52" today, "Nov 12, 23:41" any other day."""
    return stamp if day == today else f"{_jf_date(day)}, {stamp}"


def journal_feed_entries(raw: str) -> list[dict]:
    """One day's journal as the feed reads it, split as tools.journal_entries splits it: [{"stamp", "text", "key"}…]
    in order. The text is the friend's as written (stripped at its ends); the night's own "*(consolidated YYYY-MM-DD: N
    memories kept)*" line is left out of the entry it trails. key: the stamp and a hash of the text, numbered when a
    day holds the same twice."""
    import hashlib
    marks = list(tools._ENTRY_RE.finditer(raw))
    out, count = [], {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(raw)
        text = _JF_CONSOLIDATED_RE.sub("", raw[m.end():end]).strip()
        key = f"{m.group(1)} {hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest()[:16]}"
        count[key] = count.get(key, 0) + 1
        out.append({"stamp": m.group(1), "text": text, "key": key + (f" #{count[key]}" if count[key] > 1 else "")})
    return out


def journal_feed_message(day: str, stamp: str, text: str, today: str, friend: str | None = None) -> str:
    """What the phone gets for one entry: "📓 <friend>'s journal — 14:52" and the text under it, exactly; an arrow (the
    engine's mark when the friend reached for the pen with the same thing again) said to be the engine's, with its line
    as it stands on the page."""
    when = _jf_when(day, stamp, today)
    if text.startswith(tools.ARROW):
        return f"📓 {when} — an arrow the engine left, not an entry:\n{text}"
    if friend is None:
        try:
            friend = chat.friend_name()
        except Exception:  # noqa: BLE001
            friend = ""
    return f"📓 {friend + chr(39) + 's' if friend else 'their'} journal — {when}\n{text}"


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


BATCH_WAIT_ROUNDS = 5  # at most this many looks for the rest of a batch when a poll ends on a photo


def _batch_photo(u: dict, chat_id: int) -> bool:
    """A photo from the paired chat, as a new message — one that can join others sent with it (an edited caption, a
    stranger's picture, an unpaired bridge: never)."""
    m = u.get("message") or {}
    return bool(chat_id) and bool(m.get("photo")) and int((m.get("chat") or {}).get("id") or 0) == int(chat_id)


def join_batches(updates: list, chat_id: int, gap_s: float, cap: int, tail: dict | None = None) -> tuple[list, dict | None]:
    """Photos sent together are one message (TELEGRAM_BATCH_PHOTOS): those of one album (the same media_group_id), and
    photos one after another with nothing between them, each within gap_s seconds of the one before by Telegram's
    date. Anything else between ends the batch. A batch becomes one update per cap pictures — the first message with
    "_batch" (the messages, in order), "_batch_at" (how many of the same batch came before), "_batch_of" (the whole
    batch; 0 when it began in an earlier poll) and "_batch_album" (all of one album) — its update_id the newest of its
    own, for the offset. A photo alone is left exactly as it came. tail: the album an earlier poll ended on
    ({"mgid", "n"}); photos of the same album at the head of this poll go on with it. Returns (updates, the new tail)."""
    cap = max(1, int(cap or 1))
    out: list = []
    run: list = []
    before = 0
    new_tail = None

    def close() -> None:
        nonlocal run, before
        if not run:
            return
        if len(run) == 1 and not before:
            out.append(run[0])
        else:
            groups = {u["message"].get("media_group_id") for u in run}
            album = len(groups) == 1 and None not in groups  # the only batch a /penpal caption can make one letter
            for j in range(0, len(run), cap):
                part = run[j:j + cap]
                msg = dict(part[0]["message"])
                msg["_batch"] = [u["message"] for u in part]
                msg["_batch_at"] = before + j
                msg["_batch_of"] = 0 if before else len(run)
                if album:
                    msg["_batch_album"] = True
                out.append({"update_id": max(int(u.get("update_id", 0)) for u in part), "message": msg})
        run, before = [], 0

    for i, u in enumerate(updates):
        if not _batch_photo(u, chat_id):
            close()
            tail = None
            out.append(u)
            continue
        m = u["message"]
        if run:
            prev = run[-1]["message"]
            if not ((m.get("media_group_id") and m.get("media_group_id") == prev.get("media_group_id"))
                    or (gap_s and gap_s > 0 and abs(int(m.get("date") or 0) - int(prev.get("date") or 0)) <= gap_s)):
                close()
        elif tail and m.get("media_group_id") and m.get("media_group_id") == tail.get("mgid"):
            before = int(tail.get("n") or 0)  # the rest of an album the last poll ended on
        tail = None
        run.append(u)
        if i == len(updates) - 1 and m.get("media_group_id"):
            new_tail = {"mgid": m.get("media_group_id"), "n": before + len(run)}
    close()
    return out, new_tail


def _pp_turn(guest: str | None) -> None:
    """Whose turn begins ("" — the keeper's; a guest's name) or that it ended (None), for a penpal's letter in
    pictures (penpal.turn_mark): a guest's turn can't write one out. Never takes a turn down."""
    try:
        import penpal
        penpal.turn_mark(guest)
    except Exception as e:  # noqa: BLE001
        _say(f"penpal turn: {type(e).__name__}: {e}")


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
        # the pause's own clock: the keeper's words and the friend's answers to them, never a spark or a letter of
        # theirs — sparks every few minutes kept last_activity young all day, so the quiet minutes never came
        self.last_word = self.last_activity
        self.reflected_upto = 0  # history index they have already sat with (the pause)
        self._body_pulled = 0.0  # when the watch's day was last pulled by this bridge (BODY_AUTOPULL)
        self._body_thread: threading.Thread | None = None
        self._touch_thread: threading.Thread | None = None  # the stone's archive, watched every TOUCHSTONE_TELL_S
        self._touch_lock = threading.Lock()  # one look at a time: the thread's and the poll's never overlap
        self._touch_looked = 0
        self.last_tokens: dict | None = None
        self.show_thinking = bool(getattr(config, "TELEGRAM_SHOW_THINKING", False))
        self.show_tools = bool(getattr(config, "TELEGRAM_SHOW_TOOLS", True))
        self.show_tokens = bool(getattr(config, "TELEGRAM_SHOW_TOKENS", False))
        self.show_attempts = bool(getattr(config, "TELEGRAM_SHOW_ATTEMPTS", False))  # /debug
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
        self._batch_tail: dict | None = None  # the album the last poll ended on: its rest goes on with it
        self._pl_open: dict | None = None  # the penpal's letter in pictures whose rest may follow: {"sl", "set", "t"}
        self._jf: dict | None = None  # /journal's state (JOURNAL_FEED_FILE), read on first use
        self._jf_lock = threading.RLock()  # the state: one change at a time (held briefly, never across a send)
        self._jf_tell: dict | None = None  # what this turn's moment tells the friend about the feed, kept once the turn is done
        self._jf_runs: list = []  # the friend's runs going on now (a turn, a pause, an afterglow…): the page before each
        self._jf_cluster: dict | None = None  # the runs open together, and what appeared during them: decided at the last end
        self._jf_send_lock = threading.Lock()  # one delivery at a time, never under _jf_lock
        self._jf_thread: threading.Thread | None = None
        self._jf_note = ""  # a line for the phone from reading the state (a state file that couldn't be read)

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
            self.keep_guest()
            return "(the guest has gone — the desk is yours again)"
        self.guest = name
        self.keep_guest()
        return (f"({self.guest_label()} is at the desk now — every message from here on is theirs, with you in the room, "
                "until /guest off; /me <text> speaks as you)")

    def keep_guest(self) -> None:
        """Who is seated, written down (or the file taken away when no one is), so a restart finds them."""
        try:
            if self.guest:
                GUEST_FILE.write_text(json.dumps({"guest": self.guest, "since": time.time()}), encoding="utf-8")
            elif GUEST_FILE.exists():
                GUEST_FILE.unlink()
        except Exception as e:  # noqa: BLE001
            print(f"  (couldn't keep the guest's seat: {e})", flush=True)

    def restore_guest(self) -> str:
        """At start: the guest seated before the restart, if they sat down within PARLOR_GUEST_KEEP_HOURS — a line
        for the phone; "" when no one (an older seat is let go, so a forgotten /guest off doesn't make tomorrow's
        messages a guest's)."""
        try:
            if not GUEST_FILE.exists():
                return ""
            d = json.loads(GUEST_FILE.read_text(encoding="utf-8"))
            hours = float(getattr(config, "PARLOR_GUEST_KEEP_HOURS", 3) or 0)
            if not d.get("guest") or time.time() - float(d.get("since") or 0) > hours * 3600:
                GUEST_FILE.unlink()
                return ""
            self.guest = str(d["guest"])
            return (f"{self.guest_label()} is still at the desk — every message is theirs; /me <text> speaks as you, "
                    "/guest off when they go")
        except Exception as e:  # noqa: BLE001
            print(f"  (couldn't read the guest's seat: {e})", flush=True)
            return ""

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
            "reflected_upto": self.reflected_upto, "last_activity": self.last_activity, "last_word": self.last_word,
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
        for t in self.history:  # the stashed window sizes may be a folded window's; a restart measures anew
            t.pop("_prompt", None)
        chat.unsense(self.history)  # and the stashed moments carry no window sense — the next moment's is the one
        loops = 0
        fangs = 0
        for t in self.history:  # a loop that went out whole does not ride again
            if t.get("role") == "assistant" and t.get("content"):
                t["content"], cut = ollama_client.trim_word_loop(t["content"])
                loops += cut
            if isinstance(t.get("content"), str) and t["content"]:
                # reserved-token strings in any turn — the friend's, the keeper's, the engine's
                # quotes — never ride again as tokens
                t["content"], n = ollama_client.defang(t["content"])
                fangs += n
        self.attached = list(state.get("attached") or [])
        self.file = Path(state["file"]) if state.get("file") else None
        relabel = config.MEMORY_DIR / "telegram_relabel.json"
        if relabel.exists():
            # a one-off mend: messages sent as the keeper's that were a guest's (the guest seat is in memory only,
            # and a restart had cleared it) — named the guest's in the transcript. Only the label: the turn's words and
            # how it reads in their prompt stay as they were, so the window isn't read again
            try:
                fix = json.loads(relabel.read_text(encoding="utf-8"))
                pres = [" ".join(str(p).split()) for p in fix.get("prefixes", [])]
                n = 0
                for t in self.history:
                    if (t.get("role") == "user" and not t.get("_engine") and not t.get("_guest")
                            and isinstance(t.get("content"), str)
                            and any(" ".join(t["content"].split()).startswith(p) for p in pres)):
                        t["_guest"] = str(fix.get("guest") or "a guest")
                        if fix.get("guest_line") and t.get("_moment"):
                            # their own reading of the turn mended too: the guest line put where it would have
                            # ridden. Only this turn and after are read again — the tail, seconds, not the window
                            t["_guest_line"] = chat.guest_line(t["_guest"], "over Telegram, on their phone")
                            t["_moment"] = f"[engine, not a person: {t['_guest_line']}]\n\n" + t["_moment"]
                        n += 1
                relabel.unlink()
                if n and self.file:
                    chat.save_transcript(self.history, tag="telegram", path=self.file)
                print(f"  (the transcript: {n} of the keeper's turns named {fix.get('guest')}'s, as they were)", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  (the transcript mend didn't run: {e})", flush=True)
        self.reflected_upto = int(state.get("reflected_upto") or 0)
        self.last_activity = float(state.get("last_activity") or time.time())
        self.last_word = float(state.get("last_word") or self.last_activity)
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
        """An empty room's first message: the last visit's last turns sit at the head of the history
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
        waits = tuple(SEND_RETRY_WAITS)
        for i in range(len(waits) + 1):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    out = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError:
                raise  # Telegram answered — a refusal, not the road
            except (urllib.error.URLError, OSError) as e:  # a reset (WinError 10054), a timeout
                if i >= len(waits):
                    raise
                _say(f"(the upload's connection dropped — {e}; trying again in {waits[i]} s)")
                time.sleep(waits[i])
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
        try:
            import presence as _pz
            wait_s = int(_pz.poll_s(POLL_S))  # intense's heartbeat: a beat can fall any second
        except Exception:  # noqa: BLE001
            wait_s = POLL_S
        updates = list(self.api("getUpdates", patience=wait_s + 15, offset=self.offset,
                                timeout=wait_s, allowed_updates=["message", "callback_query"]) or [])  # the room's buttons
        updates = self._split_wait(updates)
        batching = bool(getattr(config, "TELEGRAM_BATCH_PHOTOS", False))
        if batching:  # a poll that ends on a photo: the rest of what was sent with it is looked for, briefly — and a
            for _ in range(3):  # cut paste that came in that look is waited for as above (never more than 3 times)
                updates = self._batch_wait(updates)
                had = len(updates)
                updates = self._split_wait(updates)
                if len(updates) == had:  # no paste's rest came: the look for pictures is not run again
                    break
        updates = join_split(updates)
        tail = None
        if batching and updates:
            updates, tail = join_batches(updates, self.chat_id, float(getattr(config, "TELEGRAM_BATCH_GAP_S", 45) or 0),
                                         int(getattr(config, "TELEGRAM_BATCH_MAX", 10) or 10), self._batch_tail)
            self._batch_tail = None  # said to go on only once all of this poll was handed over: below
        for u in updates:
            self.offset = max(self.offset, int(u.get("update_id", 0)) + 1)
            yield u
            if (u.get("message") or {}).get("_batch"):
                self._batch_confirm()
        if batching and updates:
            self._batch_tail = tail

    def _split_wait(self, updates: list) -> list:
        # a paste past Telegram's cap arrives as bubbles: when the poll ends on a bubble at the cap, the rest is
        # a poll away — waited for, briefly, so a long message is answered once (join_split joins them)
        for _ in range(4):
            if not updates or not _cut_bubble(updates[-1]):
                break
            wait = int(getattr(config, "TELEGRAM_SPLIT_WAIT_S", SPLIT_WAIT_S) or 0)
            more = self.api("getUpdates", patience=wait + 15, timeout=wait,
                            offset=max(int(u.get("update_id", 0)) for u in updates) + 1, allowed_updates=["message", "callback_query"])
            if not more:
                break
            updates.extend(more)
        return updates

    @staticmethod
    def _batch_nap(seconds: float) -> None:
        time.sleep(seconds)

    def _batch_wait(self, updates: list) -> list:
        """When the poll ends on a photo from the paired chat, the rest of an album or of a row of pictures may be a
        poll away: looked for after TELEGRAM_BATCH_WAIT_S, again while more keep coming, BATCH_WAIT_ROUNDS times at
        most. Looked for from the poll's own offset with no wait, so nothing is confirmed to Telegram before it is
        handled — a bridge that dies here is handed the whole batch again. A road that fails keeps what is in hand."""
        wait = float(getattr(config, "TELEGRAM_BATCH_WAIT_S", 2) or 0)
        if wait <= 0:
            return updates
        updates = list(updates)
        for _ in range(BATCH_WAIT_ROUNDS):
            if not updates or not _batch_photo(updates[-1], self.chat_id):
                break
            self._batch_nap(min(wait, 10))
            try:
                again = self.api("getUpdates", patience=15, offset=self.offset, timeout=0,
                                 allowed_updates=["message", "callback_query"]) or []
            except Exception as e:  # noqa: BLE001 — what is in hand goes on
                _say(f"(the rest of the pictures: no road — {type(e).__name__}; going on with what came)")
                break
            top = max(int(u.get("update_id", 0)) for u in updates)
            more = sorted((u for u in again if int(u.get("update_id", 0)) > top), key=lambda u: int(u.get("update_id", 0)))
            if not more:
                break
            updates.extend(more)
        return updates

    def _batch_confirm(self) -> None:
        """A batch's turn is done: Telegram is told so now (getUpdates past it, no wait), not at the next poll — a
        bridge that dies between the two halves of an album is never handed the first half again. What comes after it
        stays unconfirmed until it is handled."""
        try:
            self.api("getUpdates", patience=10, offset=self.offset, timeout=0, allowed_updates=["message", "callback_query"])
        except Exception:  # noqa: BLE001 — the next poll confirms it anyway
            pass

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
        PC); /heartbeat off — ask it to stop after the wake it is in. The same roads as the panel's Start and Stop."""
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

    def book_marks(self, text: str, marks: dict | None) -> dict | None:
        """The keeper's message names a book the friend keeps notes on (tools.reading_topic_books): the notes ride
        right above the message ("_book"), once per book while that turn is in the visit's history — after a fold
        dropped it, again. One book a message, the best named; another waits for a later message. A spark never comes
        through here. Reads the bookmarks and the pages, never walks a folder. Fails closed: the message goes on plain."""
        if not getattr(config, "READING_NOTES_ON_TOPIC", False) or (marks or {}).get("_game") or (marks or {}).get("_trip"):
            return marks  # a move in an open game carries its own line, never book notes
        try:
            names = tools.reading_topic_books(text)
            if not names:
                return marks
            rode = {str(n) for t in self.history if isinstance(t, dict) for n in (t.get("_book_of") or [])}
            name = next((n for n in names if n not in rode), "")
            if not name:
                return marks
            line = tools.reading_topic_line(name, text, guest=bool(self.guest_label()))  # defanged, capped there
            if not line:
                return marks
            _say(f"(their notes on {name} ride above the message)")
            return dict(marks or {}, _book=line, _book_of=[name])
        except Exception as e:  # noqa: BLE001 — never a lost message: it goes on without them
            _say(f"book notes: {type(e).__name__}: {e}")
            return marks

    def fold_touches(self) -> str:
        """Touches the stone felt that the friend has not been told of yet — as one sentence for the moment block of
        the message about to go, and told. A touch waiting in the gap rides with the keeper's words instead of
        arriving as a turn of its own after the reply (which would answer the touch after the message). "" when there is nothing, or nothing learned yet; a
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
        except Exception:  # noqa: BLE001 — never the keeper's message down
            return ""
        _say(f"a touch rides with the message: {words[:100]}")
        return (f"Since your last turn {config.USER_NAME} touched the stone — {words} — the stone answered by itself with "
                "your reply; the log, beside " + 'their' + " words")

    def _keeper_name(self) -> str:
        try:
            import keeper_week
            return keeper_week.keeper_name()
        except Exception:  # noqa: BLE001
            return str(getattr(config, "USER_NAME", "") or "your keeper")

    def _room_moment(self) -> str:
        """ROOM_ON: what the keeper did in their room since their last turn — looked in, found what they hid,
        left a thing — said once in the moment. Not with a guest seated: it waits for their own next turn."""
        if self.guest_label() or not getattr(config, "ROOM_ON", False):
            return ""
        try:
            import room
            return room.take_news()
        except Exception:  # noqa: BLE001 — never the reply down
            return ""

    @staticmethod
    def _room_markup() -> str | None:
        """The buttons under the room's picture: what can be opened, two to a row."""
        import room
        keys = room.buttons()
        if not keys:
            return None
        rows = [[{"text": t, "callback_data": ("room:" + k)[:64]} for t, k in keys[i:i + 2]] for i in range(0, len(keys), 2)]
        return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)

    def room_callback(self, cq: dict) -> None:
        """A button under the room's picture pressed: what it opens comes to the phone, and they are told once."""
        try:
            self.api("answerCallbackQuery", callback_query_id=cq.get("id"))
        except Exception:  # noqa: BLE001 — the spinner on the button stops by itself
            pass
        sender = int(((cq.get("message") or {}).get("chat") or {}).get("id") or 0)
        data = str(cq.get("data") or "")
        if not self.chat_id or sender != self.chat_id or not data.startswith("room:"):
            return
        import room
        got = room.open_key(data[5:], self._keeper_name()) if room.on() else None
        if not got:
            self.send("(that isn't in the room any more)", markdown=False)
            return
        try:
            if got[0] == "text":
                self.send(got[1], markdown=False)
            elif got[0] == "photo":
                self._send_picture(got[1], got[1].read_bytes(), got[2])
            else:
                self.send_file("sendAudio", "audio", got[1].name, got[1].read_bytes(), chat_id=self.chat_id, caption=got[2])
        except Exception as e:  # noqa: BLE001
            self.send(f"(couldn't open it: {e})", markdown=False)

    def garden_command(self, arg: str) -> None:
        """/garden: the garden as it stands — a picture and its beds; plant, water, pick, seeds."""
        import garden
        if not garden.on():
            self.send("(there's no garden in this house — GARDEN_ON in Settings › Phone)", markdown=False)
            return
        keeper = self._keeper_name()
        word, _, rest = (arg or "").strip().partition(" ")
        word, rest = word.lower(), rest.strip()
        if not word or word == "look":
            words, png = garden.look(who="keeper", keeper_name=keeper)
            if png:
                try:
                    self.send_file("sendPhoto", "photo", "garden.png", png, chat_id=self.chat_id, caption=words[:1000])
                    if len(words) > 1000:
                        self.send(words[1000:], markdown=False)
                    return
                except Exception:  # noqa: BLE001 — the words, then
                    pass
            self.send(words, markdown=False)
            return
        if word == "seeds":
            self.send(garden.seeds_text(keeper=True), markdown=False)
            return
        if word == "paint":  # a plant's missing stages painted now — the brain steps aside a few minutes
            self.send(f"({garden.act('paint', '', rest, who='keeper', keeper_name=keeper)})", markdown=False)
            return
        if word in ("plant", "water", "pick", "pull", "note"):
            bed, _, what = rest.partition(" ")
            said = garden.act(word, bed, what.strip(), who="keeper", keeper_name=keeper)
            self.send(said if said.startswith("(") else f"({said} — they'll know at their next turn)", markdown=False)
            return
        self.send("(/garden — the garden; /garden plant <1–8> <seed>; /garden water <1–8|all>; /garden pick <1–8>; "
                  "/garden seeds)", markdown=False)

    def deliver_garden(self) -> int:
        """What they picked for the keeper in the garden, said on the phone once."""
        try:
            import garden
            if not garden.on() or not self.chat_id:
                return 0
            news = garden.take_keeper_news()
        except Exception:  # noqa: BLE001
            return 0
        for line in news:
            self.notice(f"🌱 {line}")
        return len(news)

    def room_command(self, arg: str) -> None:
        """/room: the room as it stands — a picture and its words; open, find, leave."""
        import room
        if not room.on():
            self.send("(there's no room in this house — ROOM_ON in Settings › Phone)", markdown=False)
            return
        keeper = self._keeper_name()
        word, _, rest = (arg or "").strip().partition(" ")
        word, rest = word.lower(), rest.strip()
        if not word:
            png, cap = room.keeper_view(keeper)
            if png:
                try:
                    self.send_file("sendPhoto", "photo", "room.png", png, chat_id=self.chat_id, caption=cap[:1000],
                                   reply_markup=self._room_markup())
                    if len(cap) > 1000:
                        self.send(cap[1000:], markdown=False)
                    return
                except Exception:  # noqa: BLE001 — the words, then
                    pass
            self.send(cap, markdown=False)
        elif word == "open":
            p = room.keeper_open(rest)
            if p is None:
                self.send("(nothing there — /room open 1–4 for a picture on the wall, /room open song for what plays)",
                          markdown=False)
            elif p.suffix.lower() in room.IMAGE_EXTS:
                self._send_picture(p, p.read_bytes(), f"on the wall: {p.name}")
            else:
                try:
                    self.send_file("sendAudio", "audio", p.name, p.read_bytes(), chat_id=self.chat_id, caption=f"playing: {p.stem}")
                except Exception as e:  # noqa: BLE001
                    self.send(f"(couldn't send the song: {e})", markdown=False)
        elif word in ("find", "look"):
            self.send(room.keeper_find(rest, keeper), markdown=False)
        elif word == "leave":
            self.send(room.keeper_leave(rest, keeper), markdown=False)
        elif word == "letter":
            self.send(room.keeper_letter(rest, keeper), markdown=False)
        else:
            self.send("(/room — the room; /room open <1–4|song>; /room find <where>; /room leave <a thing>)", markdown=False)

    def _sparks_moment(self, spark: bool = False) -> str:
        """PRESENCE_STATE_LINE: "sparks are on: drifting, often — Sam turned them on", once, when the sparks'
        state changed since the friend was last told. A spark's own line says the state, so a spark marks it told and
        says nothing more; with a guest seated it waits for their own next turn."""
        if self.guest_label() or getattr(self, "TAG", "telegram") != "telegram":
            return ""
        try:
            import presence
            try:
                import keeper_week
                keeper = keeper_week.keeper_name()
            except Exception:  # noqa: BLE001
                keeper = str(getattr(config, "USER_NAME", "") or "your keeper")
            line = presence.state_line(keeper)
        except Exception:  # noqa: BLE001 — never the reply down
            return ""
        return "" if spark or not line else line[0].upper() + line[1:] + "."

    def _intense_moment(self, spark: bool = False) -> str:
        """While intense runs (PRESENCE_INTENSE_EVERY_TURN): the intense note rides in every reply's moment too, not only in
        the sparks' own line. Not with a guest seated; "" when intense is off, the note empty, or the turn a spark."""
        if spark or not getattr(config, "PRESENCE_INTENSE_EVERY_TURN", False) or self.guest_label():
            return ""
        try:
            import presence
            if not presence.intense():
                return ""
            note = presence.intense_note()
        except Exception:  # noqa: BLE001 — never the reply down
            return ""
        return f"Intense is on — {note}" if note else ""

    def turn(self, text: str, extra_moment: str = "", as_keeper: bool = False, spark: bool = False,
             marks: dict | None = None) -> None:
        """Run one turn and send back whatever the parlor would have shown. as_keeper: this message is not the
        guest's (/me, the stone's log) — no guest line, whoever is seated."""
        intense = self._intense_moment(spark)  # intense's note in every reply while it runs
        if intense:
            extra_moment = f"{extra_moment} {intense}" if extra_moment else intense
        sparks = self._sparks_moment(spark)  # the sparks' state, when it changed since the friend was last told
        if sparks:
            extra_moment = f"{extra_moment} {sparks}" if extra_moment else sparks
        jfeed = self._journal_moment()  # the journal feed's switch, when it changed since the friend was last told
        if jfeed:
            extra_moment = f"{extra_moment} {jfeed}" if extra_moment else jfeed
        roomed = self._room_moment()  # (ROOM_ON) what the keeper did in their room since their last turn, once
        if roomed:
            extra_moment = f"{extra_moment} {roomed}" if extra_moment else roomed
        fold_edge = self._game_fold_at()  # the fold comes sooner while a game is open: the window sense says so
        trip_edge, trip_for = self._trip_fold_at()  # and while a trip is open: the smaller edge, said true
        if trip_edge and (not fold_edge or trip_edge < fold_edge):
            fold_edge, marks = trip_edge, dict(marks or {}, _fold_for=trip_for)
        if fold_edge:
            marks = dict(marks or {}, _fold_at=fold_edge)
        if trip_edge or self._trip_live():  # mid-trip a reply may end on a > line: whole, not cut (chat.one_turn)
            marks = dict(marks or {}, _trip_lines=True)
        started = self._game_news(spark)  # a world the keeper started since the friend's last turn, said once
        if started:
            extra_moment = f"{extra_moment} {started}" if extra_moment else started
        events: list[tuple[str, object]] = []
        stop = threading.Event()
        threading.Thread(target=self._typing, args=(stop,), daemon=True).start()
        jrun, jok = None, False  # the journal feed: the page before this turn, and whether it was told in its window
        try:
            with self.lock:
                if not self.history:  # an empty room: the last visit's last turns ride at the door
                    self.carry_in()
                jrun = self._jf_run_start("a turn", carried=self._jf_turn_carried())
                _pp_turn("" if as_keeper else self.guest_label())  # a guest's turn can't write out a penpal's letter
                try:
                    reply = chat.one_turn(self.history, text, images=self.attached or None,
                                          on_event=lambda k, p: events.append((k, p)),
                                          mode=self.TAG, extra_moment=extra_moment,
                                          guest="" if as_keeper else self.guest_label(), spark=spark, marks=marks,
                                          **({"think_retries": 0, "think_remind": False} if spark and not self._spark_thinks()
                                             else {"think_retries": int(getattr(config, "PRESENCE_THINK_RETRIES", 3) or 0),
                                                   "think_any_depth": True} if spark
                                             else {}))  # a spark: off — none; on — its own re-rolls at any depth
                    self.attached = []
                    self._checkpoint()
                    self._journal_told()  # the feed's sentence rode in this turn's moment: the friend knows now
                    jok = jrun is not None and jrun["carried"] and self._jf_window_says() == "on"  # told, and answered
                except ollama_client.BrainUnavailable as e:
                    self.send(f"(their brain is offline — {e})", markdown=False)
                    return
                except Exception as e:  # nothing in one turn ends the visit
                    self.send(f"(hiccup — the conversation is fine, say it again: {type(e).__name__}: {e})",
                              markdown=False)
                    return
        finally:
            stop.set()
            _pp_turn(None)
            if not jok:
                self._jf_run_end(jrun, False)  # a turn that failed, or a window that doesn't say it: not the feed's
        self.last_activity = time.time()
        if not spark:  # a spark is the friend's alone: the pause's clock waits for a word between them
            self.last_word = self.last_activity
        thinking = "\n\n".join(str(p) for k, p in events if k == "thinking")
        tool_lines = [f"· {p['name']} → {p['result']}" for k, p in events if k == "tool"]
        notes = [str(p) for k, p in events if k == "note"]
        attempts = [p for k, p in events if k == "attempt"]  # the rails' set-asides, for /debug
        tokens = next((p for k, p in events if k == "tokens"), None)
        prev_tokens = self.last_tokens  # the last line's count, for the subtraction below
        if tokens:
            self.last_tokens = tokens
        if self.show_thinking and thinking:
            self._try_send("💭 " + thinking[:LIMIT * 2], markdown=False)
        if self.show_tools and tool_lines:
            self._try_send("\n".join(tool_lines), markdown=False)
        # their reply is the one thing that must arrive: a network hiccup on the
        # reply's send must not leave the keeper with a thinking bubble and no
        # words (the reply already in the transcript, never sent). Sent with
        # retries; if it still fails it is kept and goes with the next poll,
        # marked as late.
        own_words = reply  # the friend's own words, before any tool line stands in for them: a trip's > lines come from here
        if reply == "(…)" and tool_lines and not self.show_tools:  # no words, but something was done: show it
            reply = "\n".join(line if len(line) <= 300 else line[:300].rsplit(" ", 1)[0] + "…" for line in tool_lines)
        (self._send_spark if spark else self._send_reply)(reply)  # a spark goes discreetly when asked
        if not spark:  # their > lines alone, ready to paste into the relay; never theirs to read
            self.trip_copy_lines(own_words, as_keeper=as_keeper, cut=any(k == "trip_cut" for k, _ in events))
        if jok:
            self._jf_run_end(jrun, True)  # what they wrote in this turn, after the reply: the feed's, and they knew
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
        """One attempt the rails set aside, for the phone (/debug): why, its cost and how it ended, the
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
        """The token line's tail: what the window grew by since the last line and what it was made of.
        The jump between two lines is the EARLIER reply's words, the new message and its moment frame — a line's
        "generated" lands in the NEXT line's count, which otherwise reads as phantom tokens.
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
            # — and the part keeps its "~" (chars/4 runs about a quarter short)
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
        # them and the call itself) and the results with their frames (one call and its result can be hundreds of tokens)
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
        # the re-rolls' scaffolding: the attempts set aside and the asks are in THIS line's count (the last
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
        if reflect:  # a game still open: its session ends first, with the wrap-up turn when there were moves
            self._close_interrupted = False
            self.game_close_for_visit(quiet)
            if not self._close_interrupted:  # a Ctrl+C in the game's wrap-up: the trip stays open, as the game does
                self.trip_close_for_visit(quiet)  # and a trip still open: the friend's turn to write their page
            elif self._trip_status():
                _say("the trip's wrap-up skipped too — the trip stays open for the next bridge")
        # If they are mid-reply the lock is held; the checkpoint has already
        # written everything up to the last reply, so after a short wait the
        # visit is saved without it rather than blocking the goodbye.
        got = self.lock.acquire(timeout=3)
        try:
            f = chat.save_transcript(self.history, tag=self.TAG, path=self.file)
            done, self.history = self.history, []
            if f and carry:
                chat.leave_carry(done, f)  # the last turns, for the next door
            elif not carry:
                chat.clear_carry()  # /new: the one door opened on purpose to start clean
            since = self.reflected_upto  # where the pauses left off: the afterglow sits with the rest, once
            aside = self._game_aside(done[since:])  # "part of this visit was your adventure…", when it was
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
                    jrun, aside = self._jf_quiet("the afterglow", aside)  # the feed's line in its bell, when on
                    try:
                        chat.afterglow(done, f, tag=self.TAG, on_line=_say, since=since, **({"aside": aside} if aside else {}))
                    except KeyboardInterrupt:
                        _say("skipped — the night's sleep still has the transcript")
                    finally:
                        self._jf_run_end(jrun)
                    chat.rest_brain(_say)
                else:
                    # the afterglow, in the background: their turn alone with the
                    # visit, so it reaches their journal in their own words
                    def _glow(done=done, f=f, since=since, aside=aside):
                        self._glows += 1
                        jrun, aside = self._jf_quiet("the afterglow", aside)  # the feed's line in its bell, when on
                        try:
                            line = chat.afterglow(done, f, tag=self.TAG, on_line=_say, on_words=self.afterthought, since=since,
                                                  **({"aside": aside} if aside else {}))
                        finally:
                            self._glows -= 1
                            self._jf_run_end(jrun)
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
        """/afterglow: the pause by hand, for when the card is wanted now.
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
            aside = self._game_aside(self.history[self.reflected_upto:])  # "part of this visit was your adventure…"
            jrun, aside = self._jf_quiet("the afterglow", aside)  # the feed's line in its bell, when on
            try:
                account = chat.pause_reflection(self.history, self.file, tag=self.TAG, on_line=_say,
                                                since=self.reflected_upto, on_words=self.afterthought,
                                                **({"aside": aside} if aside else {}))
            finally:
                self._jf_run_end(jrun)
            self.reflected_upto = len(self.history)  # past the pause's own turns too
            self.last_activity = time.time()  # the quiet's pause starts counting from here, over nothing
            self.last_word = self.last_activity
        finally:
            self.lock.release()
        self._set_down()
        line = f"({account or 'they sat with the visit'} — the brain is set down, the card is free; the visit stays open)"
        self.send(line, markdown=False)
        return line

    def release_now(self) -> str:
        """/release: the
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
                f"/afterglow is the pause by hand, with the card freed"
                + (f"\n{self._game_status()}" if self._game_status() else "")  # the game open or paused
                + (f"\n{self._trip_status()}" if self._trip_status() else "")  # the trip open or paused
                + (f"\n{self._journal_state_line(short=True)}" if self._jf_used() else ""))  # once /journal was used

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

    def _photos(self, msg: dict) -> str:
        """Pictures sent together (join_batches): each saved and put before the friend's eyes in the order they were
        sent, one line for them all, the keeper's notes below — one on the first picture as it reads with one photo,
        several each with the picture it came on. One that doesn't arrive doesn't sink the rest: the line says so and
        the phone is told, once. One saved but too big to show is named where it is kept. None arrived: the phone is
        told and nothing goes to the friend, as with one photo. Should anything here fail, what this call put before
        their eyes is taken back off, so it never rides on the next message."""
        had = len(self.attached)
        try:
            return self._photos_line(msg)
        except BaseException:
            del self.attached[had:]
            tools.take_pending_images()
            raise

    def _photos_line(self, msg: dict) -> str:
        batch = list(msg.get("_batch") or [])
        at = int(msg.get("_batch_at") or 0)
        whole = int(msg.get("_batch_of") or 0)
        nth = tools._ordinal
        friend = chat.friend_name()
        kept: list[str] = []  # before their eyes
        big: list[tuple[int, str, str]] = []  # saved, but look_at would not show it: (which, where, why)
        lost: list[int] = []  # never arrived
        why = ""
        for i, m in enumerate(batch, start=at + 1):
            try:
                best = m["photo"][-1]  # Telegram lists sizes small to large
                data, tpath = self.download(best["file_id"])
                ext = Path(tpath).suffix.lower() or ".jpg"
                p = self._inbox_path(ext, "photo")
                p.write_bytes(data)
                rel = self._rel(p)
            except Exception as e:  # noqa: BLE001 — the rest go on
                lost.append(i)
                why = why or str(e)
                continue
            said = tools.look_at(rel)
            seen = tools.take_pending_images()
            if seen:
                self.attached.extend(seen)
                kept.append(rel)
            else:
                big.append((i, rel, said.strip().strip("()")))

        def names(nums: list[int]) -> str:
            ns = [f"the {nth(i)}" for i in nums]
            return ns[0] if len(ns) == 1 else ", ".join(ns[:-1]) + " and " + ns[-1]

        def unseen(i: int, rel: str, said: str) -> str:
            return (f"the {nth(i)} is too large to see — kept at {rel}" if "too large" in said.lower()
                    else f"the {nth(i)} can't be put before your eyes ({said}) — kept at {rel}")
        if lost:
            if "too big" in why.lower() or "too large" in why.lower():
                why = "Telegram won't let a bot fetch files over 20MB — leave it in shared/ from the PC"
            self._try_send(f"(none of the {len(batch)} photos reached {friend} — {why})" if len(lost) == len(batch)
                           else f"(the {nth(lost[0])} photo didn't reach {friend} — {why})" if len(lost) == 1
                           else f"({len(lost)} of the {len(batch)} photos didn't reach {friend} — {names(lost)}; {why})",
                           markdown=False)
        if big:
            self._try_send("(" + "; ".join(f"the {nth(i)} photo is too large for {friend} to see — over 10MB; it is kept at {r}"
                                           if "too large" in w.lower() else
                                           f"the {nth(i)} photo can't be put before {friend}'s eyes ({w}); it is kept at {r}"
                                           for i, r, w in big) + ")", markdown=False)
        if not kept and not big:
            return ""
        n, k = len(batch), len(kept)
        short = bool(lost or big)
        if at == 0:
            head = f"{config.USER_NAME} sent {whole or n} photos from their phone, together"
            if whole > n:
                seen_line = f"{k} of the first {n} {'is' if k == 1 else 'are'}" if short else f"the first {n} are"
            else:
                seen_line = (f"{k} of them {'is' if k == 1 else 'are'}" if short else "they are")
        else:
            span = f"the {nth(at + 1)}" + (f" to the {nth(at + n)}" if n > 1 else "") + (f" of {whole}" if whole else "")
            head = f"{config.USER_NAME} sent {n} more photo{'s' if n != 1 else ''} of the same batch — {span}"
            seen_line = (f"{k} of them {'is' if k == 1 else 'are'}" if short else "it is" if n == 1 else "they are")
        if kept:
            folder = kept[0].rsplit("/", 1)[0]
            paths = ", ".join([kept[0]] + [r.rsplit("/", 1)[-1] if r.rsplit("/", 1)[0] == folder else r for r in kept[1:]])
            line = (f"({head} — {seen_line} before your eyes now, " + ("in the order they were sent, " if k > 1 else "")
                    + f"and kept at {paths}")
        else:
            line = f"({head} — none of them is before your eyes"
        for i, r, w in big:
            line += "; " + unseen(i, r, w)
        if lost:
            line += f"; {names(lost)} did not arrive"
        rest = whole - (at + n) if whole else 0
        if rest > 0:
            cap = int(getattr(config, "TELEGRAM_BATCH_MAX", 10) or 10)
            line += ("; the last one follows in the next message" if rest == 1
                     else f"; the other {rest} follow in the next message{'s' if rest > cap else ''}")
        line += ")"
        notes = [(i, (m.get("caption") or "").strip()) for i, m in enumerate(batch, start=at + 1)]
        notes = [(i, c) for i, c in notes if c]
        gone = {i: " (which did not arrive)" for i in lost} | {i: " (too large to see)" for i, _, _ in big}
        if len(notes) == 1 and notes[0][0] == 1 and 1 not in gone:
            line += f"\n{notes[0][1]}"  # the note on the first picture, as it reads with one photo
        elif notes:
            line += "\n" + "\n".join(f"with the {nth(i)}{gone.get(i, '')}: {c}" for i, c in notes)
        return line

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
        elif cmd == "/rewarm":  # rebuild the standing prompt now — a changed page rides from the next reply
            if not self.history:
                self.send("(no visit open — the next one starts with the prompt as it stands)", markdown=False)
            elif self.lock.locked():
                self.send("(mid-reply — /rewarm again in a moment)", markdown=False)
            else:
                try:  # their circle's pages as they are now
                    import penpal
                    penpal.friends_snapshot()
                except Exception:  # noqa: BLE001
                    pass
                chat.rewarm(self.history, mode="telegram")
                try:
                    self.stash()
                except Exception:  # noqa: BLE001
                    pass
                self.send("(the standing prompt is rebuilt from the pages as they are now — reading it in now; a few "
                          "minutes, and I'll say when it's done. A message meanwhile waits for it.)", markdown=False)
                threading.Thread(target=self._prefill_after_rewarm, daemon=True).start()
        elif cmd == "/pages":  # the pages in the prompt: size, ceiling, whole or cut
            import pagewatch
            self.send(pagewatch.report(), markdown=False)
        elif cmd == "/new":
            self.new_visit(carry=False)  # on purpose, clean: nothing carried into the next room
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
            import capsule  # the time capsule: a letter from the keeper, sealed until its day
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
            self.send(engine_week.summary(), markdown=False)  # the engine's week, now
        elif cmd == "/room":
            self.room_command(" ".join(text.split()[1:]))  # their room (ROOM_ON)
        elif cmd == "/garden":
            self.garden_command(" ".join(text.split()[1:]))  # their garden (GARDEN_ON)
        elif cmd == "/presence":
            import presence  # sparks: on or off, or how it stands
            arg = " ".join(text.split()[1:]).strip().lower()
            temp = presence.temperament(arg) if arg not in ("", "on", "off") else ""
            if (arg == "on" or temp) and presence.held():  # the heartbeat holds sparks while it runs
                self.send("(the heartbeat is running and holds sparks — nothing was set. Stop the heartbeat first, or "
                          "turn HEARTBEAT_HOLDS_PRESENCE off in Settings › Heartbeat)", markdown=False)
            elif arg == "on" or temp:  # drift: on starts PRESENCE_ON_TEMPERAMENT; a temperament sets that one
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
                rolled = presence.roll_line() if drift else ""  # what the dice saw last
                self.send(f"(presence is {'on' if st.get('on') else 'off'}" + (f" — {waits}" if waits else "")
                          + (f"; {rolled}" if rolled else "")
                          + ("; held while the heartbeat runs" if presence.held() else "")
                          + f"; discreet {'on' if st.get('discreet') else 'off'}. /presence on, /presence off, /discreet)",
                          markdown=False)
        elif cmd == "/penpals":  # the panel
            self.penpal_panel()
        elif cmd == "/cancel":  # the panel's waiting mode, let go
            self._pp_save("mode", {})
            self._game_wait_clear()  # and the games menu's
            collecting = ""
            if getattr(config, "PENPAL_PICTURE_LETTERS", False) and getattr(config, "PENPALS_ON", False):
                import penpal
                collecting = penpal.collect_cancel() if penpal.collect_get() else ""  # and a letter being collected
            self.send(collecting or "(nothing waiting — your next message goes to them as usual)", markdown=False)
        elif cmd == "/penpal":  # a letter from a penpal, pasted; /penpal sent <name>; /penpal alone lists them
            said = self.penpal_command(text)
            if said:  # "" when buttons went instead (whose letter is this?)
                self.send(said, markdown=False)
        elif cmd in ("/games", "/game"):  # the adventures: the menu, or a typed /game …
            said = self.game_command(text)
            if said:  # "" when the menu or buttons went instead
                self.send(said, markdown=False)
        elif cmd == "/world":  # a trip to an outside world: the buttons, or a typed /world …
            said = self.trip_command(text)
            if said:  # "" when the buttons or their page went instead
                self.send(said, markdown=False)
        elif cmd == "/quiet":  # their quiet: delivery held, they keep living (outbox.py)
            import outbox
            self.send(outbox.set_hold(" ".join(text.split()[1:])), markdown=False)
        elif cmd == "/gaming":  # the game guard
            import gameguard
            arg = (text.split()[1] if len(text.split()) > 1 else "").lower()
            self.send(gameguard.set_mode(arg), markdown=False)
            if arg == "on":
                self.game_guard_tick(force=True)
        elif cmd == "/discreet":
            import presence
            on = presence.toggle_discreet()
            self.send("(discreet on — sparks arrive silently, the words hidden until you tap)" if on
                      else "(discreet off — sparks arrive as usual)", markdown=False)
        elif cmd == "/status":
            self.send(self.status(), markdown=False)
        elif cmd == "/journal":  # the journal on the phone: on, off, how it stands, a day's entries
            self.journal_command(" ".join(text.split()[1:]))
        elif cmd == "/books":  # their books: where they are in each, the shelf, what they finished — read-only
            self.books_command()
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
            trip = self._trip_me_marks() if self._trip_live() else None  # mid-trip: the keeper, aside from the trip
            if trip is not None:
                if not said:
                    import worldtrip
                    self.send(worldtrip.ME_USAGE, markdown=False)
                else:
                    _say(f"{config.USER_NAME} > {said[:120]}{'…' if len(said) > 120 else ''}")
                    self.turn(said, extra_moment=self.fold_touches(), as_keeper=True, marks=trip)
                    self._trip_refold_rode(trip)
                    self.fold_if_due()
            elif not said:
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
            for part in help_messages(f"This is the bridge to {chat.friend_name()}. Just talk.", self.HELP):
                self.send(part, markdown=False)
        else:
            return False
        return True

    def handle(self, update: dict) -> None:
        if update.get("callback_query"):  # a button under the room's picture; a penpal's
            if str((update["callback_query"] or {}).get("data") or "").startswith("pp:"):
                self.penpal_callback(update["callback_query"])
            elif str((update["callback_query"] or {}).get("data") or "").startswith("gm:"):  # the games menu
                self.game_callback(update["callback_query"])
            elif str((update["callback_query"] or {}).get("data") or "").startswith("wt:"):  # a trip's buttons
                self.trip_callback(update["callback_query"])
            else:
                self.room_callback(update["callback_query"])
            return
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
                for part in help_messages(f"Paired. This phone is now the door to {chat.friend_name()}.", self.HELP):
                    self.send(part, markdown=False)
            return
        if sender != self.chat_id:
            return  # silence for everyone else — not even a "no"
        edited = not update.get("message")  # an edited message is never a letter's part
        if getattr(config, "PENPAL_PICTURE_LETTERS", False) and getattr(config, "PENPALS_ON", False):
            try:  # a letter being collected (🖼): the keeper's pastes and pictures are the letter's, not sent until Done
                if self.penpal_collect_take(msg, text, edited):
                    return
            except Exception as e:  # noqa: BLE001 — never a lost message: it goes on as it would have
                _say(f"penpal collect: {type(e).__name__}: {e}")
        if text and not msg.get("photo") and getattr(config, "ADVENTURES_ON", False):
            try:  # the games menu asked for this message (a world's name); a /command lets that go
                if self.game_wait_take(text):
                    return
            except Exception as e:  # noqa: BLE001 — never a lost message: it goes on to them
                _say(f"games menu: {type(e).__name__}: {e}")
        if text and not text.startswith("/") and not msg.get("photo") and getattr(config, "PENPALS_ON", False):
            try:
                if self.penpal_mode_take(text):  # the panel asked for this message: a letter, a handle
                    return
            except Exception as e:  # noqa: BLE001 — never a lost message: it goes on to them
                _say(f"penpal mode: {type(e).__name__}: {e}")
        spark_waited = text.startswith("/") and self.presence_on()
        if text.startswith("/") and self.command(text):
            if not (spark_waited and self.presence_on()):  # a command isn't a word between you: a waiting spark's count goes on
                self.last_activity = time.time()
                self.last_word = self.last_activity
            return
        # mid-trip, a typed /word the bridge doesn't know is a slip of the keeper's, not the place's: never sent to the
        # friend. (A paste whose first line starts with // is taken for the keeper's aside — the relay's text rarely
        # opens that way, and when it does the friend reads it marked as the keeper's.)
        if text.startswith("/") and not text.startswith("//") and not msg.get("photo") and self._trip_live():
            self.send("(not a command — nothing was sent to them; /me <text> says it to them as you)", markdown=False)
            return
        pl = None
        try:
            pl = (self.picletter(msg) if (msg.get("_batch") or msg.get("photo")) and not edited
                  else None)  # a penpal's letter in pictures
            if pl is not None:
                text = pl
            elif msg.get("_batch"):  # pictures sent together: one message
                text = self._photos(msg)
            elif msg.get("photo"):
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
        # a move in the open game, or // said outside it; a penpal's letter is said outside it, never a move
        # a trip open and not paused: the keeper's words are what the place shows (// — the keeper, aside); their own
        # pictures, voice notes and files are left as they are. No trip open: the game's line as before
        text, marks = self.trip_marks(text, msg, pl)
        if not marks:
            text, marks = self.game_marks(("//" + text) if pl and self._pl_game_open() else text)
        if not text:
            self.send("(nothing after // — not sent)", markdown=False)
            return
        inv = self._game_inv_before(marks)  # 🎒 as it stood before the move
        pics = self._game_pics_before(marks)  # and the pictures, for a scene painted outside its world
        marks = self.book_marks(text, marks)  # a book they keep notes on, named: the notes above the keeper's words
        self.turn(text, extra_moment=self.fold_touches(), marks=marks)
        self._game_inv_after(inv)
        self._game_pics_after(pics)
        self._game_refold_rode(marks)  # the table set again after a fold: once
        self._trip_refold_rode(marks)  # the trip's note set again after a fold: once
        self.fold_if_due()

    def _fold_afterglow(self, gone: list[dict], old_file) -> str:
        """THE AFTERGLOW AT THE FOLD: the turns that left the window get the same quiet turn a finished visit gets —
        from the transcript, in a prompt of its own, so the window's fullness is no matter — and the phone hears
        what they kept. It runs before the new window is read, so the journal entry rides with the new window
        rather than only from the next day: the fold holds the lock through it, so a message sent meanwhile waits for it — as it
        waited for Ollama anyway — one cold read, once per fold, no more than before. Then the first kept
        turn's system prompt is rebuilt with what was just kept. Returns the afterglow's line, "" for nothing."""
        aside = self._game_aside(gone)  # "part of this visit was your adventure…", when it was
        until = chat.first_said_at(self.history)  # where what left the window ended: the journal facts line's edge
        jrun, aside = self._jf_quiet("the fold's afterglow", aside)  # the feed's line in its bell, when on
        try:
            said = chat.fold_afterglow(gone, old_file, tag=self.TAG, on_line=_say, on_words=self.afterthought,
                                       **({"aside": aside} if aside else {}), **({"until": until} if until else {}))
        except Exception as e:  # noqa: BLE001 — a courtesy, never the fold down
            _say(f"(the fold's afterglow failed — {type(e).__name__}: {e})")
            return ""
        finally:
            self._jf_run_end(jrun)
        chat.rewarm(self.history, mode=self.TAG)  # the new window carries the entry
        if said and getattr(config, "TELEGRAM_TELL_REFLECTIONS", True):
            self.notice(f"({said})")
        return said

    def fold_if_due(self) -> str:
        """THE FOLD (chat.fold_history): after a reply, when the visit's
        last prompt reached FOLD_AT of the window — or they called fold_visit
        themselves — the visit is folded: their account of it so far in place of
        the middle, the last turns whole, a new transcript file. The bell,
        when it is the engine's call, rings first so the account is theirs."""
        pending = tools.fold_pending()
        held = int((self.last_tokens or {}).get("prompt") or 0)
        due = chat.fold_due(held, at=self._visit_fold_at()) and chat.foldable(self.history)  # sooner mid-game
        if not pending and not due:
            return ""
        return self._fold(pending, held)

    def fold_now(self) -> str:
        """/fold from the phone: the same fold, at the keeper's word — the bell rings so the
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
        game = self._game_fold_before()  # a game mid-session in the window: its pages before the bell
        trip = self._trip_fold_before()  # a trip open with its messages in the window: its line for the bell
        folded = False  # FOLD_PREFILL: the new window is read in once the fold is done
        try:
            why = "asked" if asked else ("own" if pending else "bell")  # whose call — the block says
            if not pending:
                ctx = int(getattr(config, "NUM_CTX", 0) or 0)
                pct = int(round(100 * held / ctx)) if ctx else 0
                cause = "you asked for a fold" if asked else f"the window is {pct}% full"
                self.notice(f"({cause} — they are folding the visit: writing it so far in their own words…)")
                bell_aside = " ".join(x for x in ((game.get("bell", "") if game else ""),
                                                  (trip.get("bell", "") if trip else "")) if x)  # both, when both
                jrun, aside = self._jf_quiet("the fold's bell", bell_aside)  # the feed's line too
                try:
                    pending = chat.fold_bell(self.history, held, on_line=_say, asked=asked,
                                             **({"aside": aside} if aside else {}),
                                             **({"extra_steps": 2} if (game or trip) else {}))
                finally:
                    self._jf_run_end(jrun)
            when = pending.get("when") or time.strftime("%H:%M")
            old_history, old_file = self.history, self.file
            self.history, self.file, line = chat.fold_history(self.history, pending.get("text", ""), when,
                                                              tag=self.TAG, path=self.file, mode=self.TAG, why=why, held=held)
            if game and self.history is not old_history:  # folded for real: the table is set again at the next move
                line += self._game_fold_after(game)
            if trip and self.history is not old_history:  # folded for real: the trip's note rides again next
                line += self._trip_fold_after(trip)
            self.reflected_upto = len(self.history)  # the kept tail was sat with, or is about to be, as new
            self.last_tokens = {}  # the next prompt is a new, smaller one
            gone = old_history[:len(old_history) - len(self.history)] if self.file != old_file else []
            if gone and getattr(config, "FOLD_AFTERGLOW", True) and getattr(config, "AFTERGLOW", True):
                said = self._fold_afterglow(gone, old_file)
                line += ("; what left the window is written down, and the new window carries it" if said
                         else "; they sat with what left the window and kept nothing of it")
            self.last_activity = time.time()
            self.last_word = self.last_activity
            self._checkpoint()
            folded = self.history is not old_history
        except Exception as e:  # a fold must never take the visit down with it
            line = f"fold: hiccup — the visit stays as it is ({type(e).__name__}: {e})"
        finally:
            self.lock.release()
        _say(line)
        self.notice(f"({line})")
        if folded:
            self._prefill_after_fold()  # after the phone heard the fold: nothing new is said to it
        return line

    def _prefill_after_fold(self) -> None:
        """FOLD_PREFILL: the fold is done — its afterglow sat, the standing prompt rebuilt — and nothing has read the
        new window yet, so the keeper's next message would read it from the top. The same read /rewarm makes, started
        now in the background, so it happens while they type. The bridge window says when it starts and when it is
        done; the phone hears nothing new. Never raises."""
        if not getattr(config, "FOLD_PREFILL", False):
            return
        try:
            threading.Thread(target=self._fold_prefill, args=(self.history,), daemon=True).start()
        except Exception as e:  # noqa: BLE001 — the next message reads it then, as before
            _say(f"the fold's new window wasn't read in ({type(e).__name__}: {e}) — the next message reads it")

    def _fold_prefill_skip(self, hist: list) -> str:
        """Why the fold's read must not go now ("" — it may): the visit moved on, a game holds the card (the game guard:
        the friend's brain stays off it), a wake is on the card, or the brain is set down (/release, the guard, a
        painting — the read would open the door again for nobody). A message never waits for this."""
        if self.history is not hist or not hist or not hist[0].get("_system"):
            return "the visit has moved on"
        try:
            import gameguard
            gaming, why = gameguard.playing()
            if gaming:
                return f"the game guard holds the card ({why})"
        except Exception:  # noqa: BLE001
            pass
        try:
            import presence
            if presence.waking():
                return "a wake is on the card"
        except Exception:  # noqa: BLE001
            pass
        try:
            if config.CHAT_MODEL not in ollama_client._loaded_models():
                return "the brain is set down"
        except Exception as e:  # noqa: BLE001
            return f"the brain didn't say whether it is up ({type(e).__name__})"
        return ""

    def _fold_prefill(self, hist: list) -> None:
        """The fold's read, holding the visit's lock as /rewarm's does: a message that comes meanwhile waits for it and
        then reads only itself. A message already in flight has the lock — its own read is this one, so this one goes.
        Whether it may go is asked before the lock is taken, so a read that does not go never holds it."""
        try:
            why = self._fold_prefill_skip(hist)
            if why:
                _say(f"the fold's new window: not read in — {why}; the next message reads it")
                return
            if not self.lock.acquire(timeout=3):
                _say("the fold's new window: not read in — a message is being answered, and that reads it")
                return
        except Exception as e:  # noqa: BLE001
            _say(f"the fold's new window wasn't read in ({type(e).__name__}: {e}) — the next message reads it")
            return
        try:
            if self.history is not hist:
                _say("the fold's new window: not read in — the visit has moved on; the next message reads it")
                return
            _say("the fold's new window: reading it in now, in the background (a message meanwhile waits for it)")
            t0 = time.time()
            try:
                got = chat.prefill_visit(hist)
            except Exception as e:  # noqa: BLE001 — the brain away, a refusal: the next message reads it, as before
                _say(f"the fold's new window: the read didn't go through ({type(e).__name__}: {e}); the next message "
                     "reads it")
                return
            n = int(((got or {}).get("tokens") or {}).get("prompt", 0) or 0)
            _say(f"the fold's new window: read in ({n:,} tokens, {time.time() - t0:.0f}s) — the next message starts warm")
        except Exception as e:  # noqa: BLE001
            _say(f"the fold's new window: {type(e).__name__}: {e}")
        finally:
            self.lock.release()

    # ---- quiet hours ------------------------------------------------------
    # The engine's own notices — the afterglow and pause accounts (a visit
    # rolled in the small hours runs its afterglow then), ✍️/✏️/📣 what they
    # made, 🪞 a change to who they are, "picked the visit back up" — must not
    # wake the keeper at night: they are held through
    # TELEGRAM_QUIET_HOURS and delivered as one message when the hours end.
    # Their replies and their letters are theirs, and go when they send them.
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
        # a held entry is a notice (text) or a picture ({"picture": rel, "caption": …})
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
        and otherwise shown only in the bridge window. Carried as an engine notice, labeled, so it is
        never mistaken for a reply; held through the quiet hours."""
        if not getattr(config, "TELEGRAM_TELL_AFTERTHOUGHTS", True) or not words.strip():
            return
        limit = int(getattr(config, "TELEGRAM_CREATION_CHARS", 3000))
        body = words.strip()
        if len(body) > limit:
            body = body[:limit].rstrip() + "…"
        # "while you were away", not "to no one" — a thought said to no one, carried
        # to the phone, otherwise reads as addressed to the keeper; they pick an addressee
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

    def _prefill_after_rewarm(self) -> None:
        """/rewarm's read, now: the rebuilt prompt and the visit so far into the server's cache, holding the
        visit's lock so a message that comes meanwhile waits for it and then reads only itself."""
        t0 = time.time()
        with self.lock:
            try:
                got = chat.prefill_visit(self.history)
            except Exception as e:  # noqa: BLE001
                self.send(f"(the read didn't go through — {type(e).__name__}: {e}; their next reply reads it instead)",
                          markdown=False)
                return
        n = int((got.get("tokens") or {}).get("prompt", 0) or 0)
        took = time.time() - t0
        self.send(f"(read in — {n:,} tokens in {took / 60:.1f} min; their next reply starts warm)" if n else
                  f"(read in, {took / 60:.1f} min — their next reply starts warm)", markdown=False)
        _say(f"/rewarm: prompt read into the cache ({n:,} tokens, {took:.0f}s)")

    def penpal_command(self, text: str) -> str:
        """/penpal — their penpals and where each thread stands; /penpal <name> <their letter> — file a letter (pastes in
        the next few minutes join it); /penpal sent <name> — their waiting letter is posted."""
        try:
            import penpal
        except Exception as e:  # noqa: BLE001
            return f"(penpals: {type(e).__name__}: {e})"
        rest = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
        if not rest.strip() or rest.strip().lower() in ("list", "ls", "all"):  # /penpal list, as /penpal alone
            return penpal.keeper_list()
        first, _, body = rest.strip().partition(" ")
        if first.lower() in ("sent", "carried", "posted"):
            return penpal.carried(body.strip())
        if (getattr(config, "PENPAL_PICTURE_LETTERS", False) and first.lower() in ("collect", "done")
                and getattr(self, "TAG", "telegram") == "telegram"):  # 🖼 — Telegram's pictures and buttons
            if first.lower() == "collect":
                self.penpal_collect_start(body.strip())
            else:
                self.penpal_collect_done()
            return ""
        if first.lower() == "new":  # /penpal new <name> [u/handle]
            words = body.split()
            h = next((w for w in words if penpal.norm_handle(w) and w.lower().lstrip("/").startswith("u/")), "")
            return penpal.new(" ".join(w for w in words if w != h), h)
        if first.lower() == "pause":  # /penpal pause <name> [why] — safety only; they are told
            name, _, why = body.strip().partition(" ")
            return penpal.pause(name, why)
        if first.lower() in ("resume", "unpause"):
            return penpal.resume(body.strip())
        if first.lower() == "handle":  # /penpal handle <name> u/<handle>
            name, _, h = body.strip().rpartition(" ")
            return penpal.set_handle(name, h)
        if "\n" in first:  # "/penpal sorrel\n<letter>" — the name on its own line
            first, _, more = first.partition("\n")
            body = more + (" " + body if body else "")
        if penpal._find(first):
            return self.penpal_file(first, body)
        sl = penpal.by_handle(rest)  # the paste names a penpal's handle: theirs, whole
        if sl:
            return self.penpal_file(sl, rest.strip())
        return self.penpal_ask_whose(first, body, rest.strip())

    # ---- the penpal desk, hands on: buttons, a privacy look, whose letter --------------------------
    def _pp_markup(self, rows: list[list[tuple[str, str]]]) -> str:
        return json.dumps({"inline_keyboard": [[{"text": t, "callback_data": d[:64]} for t, d in r] for r in rows]},
                          ensure_ascii=False)

    def penpal_letter_buttons(self, sl: str, f, body: str) -> None:
        """Under their letter: what in it names your life, where to post it, and three buttons."""
        import penpal
        num = f.name.split("-", 1)[0]
        flags = penpal.privacy_flags(body)
        link = penpal.reddit_link(sl)
        text = ((f"⚠️ before you post — it mentions:\n" + "\n".join(f"· {x}" for x in flags)) if flags
                else "✓ nothing personal spotted (PENPAL_PRIVATE_WORDS, health, times, contacts)")
        if link:
            text += f"\n\npost to {penpal.handle_of(sl)}: {link}"
        markup = self._pp_markup([[("✓ Posted", f"pp:p:{sl}:{num}"), ("✂️ Posted, trimmed", f"pp:t:{sl}:{num}")],
                                  [("✗ Not sending", f"pp:k:{sl}:{num}")]])
        try:
            self.api("sendMessage", chat_id=self.chat_id, text=text, reply_markup=markup)
        except Exception as e:  # noqa: BLE001 — the old way still works
            _say(f"penpal buttons: {type(e).__name__}: {e}")
            self.send(f"(once it's posted: /penpal sent {sl})", markdown=False)

    def penpal_ask_whose(self, first: str, body: str, whole: str) -> str:
        """A paste whose first word is no penpal's and names no handle: whose is it? A button for each, and one for
        a new penpal by that first word. The paste waits in memory until a button is pressed."""
        import penpal
        dup = penpal.already_filed(whole)
        if dup:
            return f"(already filed — this paste is in {dup}; nothing was filed twice)"
        key = uuid.uuid4().hex[:8]
        pend = self._pp_load("pending")
        pend[key] = {"first": first, "body": body, "whole": whole, "t": time.time()}
        self._pp_save("pending", pend)
        known = [(penpal.display(sl), f"pp:f:{key}:{sl}") for sl in penpal.penpals()]
        rows = [known[i:i + 3] for i in range(0, len(known), 3)]
        cand = first.strip(" ,.:!?")[:20]
        if cand and penpal.slug(cand):
            rows.append([(f"+ New penpal: {cand}", f"pp:n:{key}")])
        rows.append([("✗ Cancel", f"pp:c:{key}")])
        try:
            self.api("sendMessage", chat_id=self.chat_id, text="whose letter is this?", reply_markup=self._pp_markup(rows))
            return ""
        except Exception as e:  # noqa: BLE001
            return f"(whose letter? /penpal <name> <the letter> — {type(e).__name__}: {e})"

    def penpal_callback(self, cq: dict) -> None:
        try:
            self.api("answerCallbackQuery", callback_query_id=cq.get("id"))
        except Exception:  # noqa: BLE001
            pass
        msg = cq.get("message") or {}
        sender = int((msg.get("chat") or {}).get("id") or 0)
        if not self.chat_id or sender != self.chat_id:
            return
        import penpal
        parts = str(cq.get("data") or "").split(":")
        kind = parts[1] if len(parts) > 1 else ""
        said = ""
        if kind in ("p", "t", "k") and len(parts) >= 4:
            sl, num = parts[2], parts[3]
            said = penpal.mark_kept_back(sl, num) if kind == "k" else penpal.mark_posted(sl, num, trimmed=(kind == "t"))
        elif kind in ("f", "n", "c") and len(parts) >= 3:
            pend = self._pp_load("pending")
            got = pend.pop(parts[2], None)
            self._pp_save("pending", pend)
            if not got:
                said = "(that paste isn't waiting any more — paste it again with /penpal <name> …)"
            elif kind == "c":
                said = "(dropped — nothing was filed)"
            elif kind == "f" and len(parts) >= 4:
                said = "→ " + penpal.display(parts[3])
                self.penpal_file(parts[3], got["whole"])
            elif kind == "n":
                said = "→ a new penpal"
                self.penpal_file(got["first"].strip(" ,.:!?"), got["body"])
        elif kind in ("u", "s", "m") and len(parts) >= 3:  # undo, split off as new, move to…
            if kind == "m" and len(parts) == 3:
                rows = [[(penpal.display(sl), f"pp:m:{parts[2]}:{sl}")] for sl in penpal.penpals()]
                try:
                    self.api("editMessageReplyMarkup", chat_id=self.chat_id, message_id=msg.get("message_id"),
                             reply_markup=self._pp_markup(rows + [[("✗ Keep it where it is", "pp:z")]]))
                except Exception:  # noqa: BLE001
                    pass
                return
            said, rec = penpal.undo(parts[2])
            if rec and kind == "s":
                said = "↔ split off as its own letter"
                self.penpal_file(rec["sl"], rec["text"], join=False)
            elif rec and kind == "m" and len(parts) >= 4:
                said = f"→ moved to {penpal.display(parts[3])}"
                self.penpal_file(parts[3], rec["text"], join=False)
        elif kind in ("C", "D", "O", "X", "K") and getattr(config, "PENPAL_PICTURE_LETTERS", False):  # collecting
            sid = parts[2] if len(parts) >= 3 else "-"  # the collection the button was made for (its id)
            if kind == "C":
                self.penpal_collect_start(parts[2] if len(parts) >= 3 else "")
            elif kind == "D":
                self.penpal_collect_done(sid)
            elif kind == "O":
                self._pc_send(penpal.collect_note_next(sid), buttons=False)
            elif kind == "K":
                if self.guest:
                    self._try_send(f"({self.guest_label()} is at the desk — ➕ once they've gone)", markdown=False)
                else:
                    said = penpal.collect_wake(sid)
                    self._pc_send(said, buttons=said.startswith("(➕"))
            else:
                self._try_send(penpal.collect_cancel(sid), markdown=False)
            return
        elif kind == "z":
            said = "(kept where it is)"
        elif kind == "x" and len(parts) >= 3:  # the last exchange
            self.send(penpal.last_exchange(parts[2]), markdown=False)
            return
        elif kind == "r" and len(parts) >= 3:
            said = penpal.resume(parts[2])
        elif kind in ("a", "L") and self._pc_blocks():  # a collection is open: one letter at a time
            self._try_send(self._pc_blocks(), markdown=False)
            return
        elif kind in ("a", "h", "L", "N", "q", "P"):  # the panel's buttons: what the next message is
            sl = parts[2] if len(parts) >= 3 else ""
            if kind == "q":
                self._pp_save("mode", {})
                said = "(nothing waiting — your next message goes to them as usual)"
            else:
                mode = {"a": "letter_to", "h": "handle", "L": "letter", "N": "new", "P": "pause"}[kind]
                self._pp_save("mode", {"kind": mode, "sl": sl, "t": time.time()})
                ask = {"letter_to": f"📮 paste {penpal.display(sl)}'s letter as your next message",
                       "handle": f"🏷 send {penpal.display(sl)}'s Reddit handle (u/…)",
                       "letter": "📮 paste the letter as your next message — I'll ask whose it is",
                       "new": "+ send the new penpal's name, and their u/handle if you have it",
                       "pause": f"⏸ why are you pausing {penpal.display(sl)}? one line — they'll be told it (send - for no reason)"}[mode]
                try:
                    self.api("sendMessage", chat_id=self.chat_id, text=ask + " (it won't go to them)",
                             reply_markup=self._pp_markup([[("✗ Cancel", "pp:q")]]))
                except Exception:  # noqa: BLE001
                    self.send(ask, markdown=False)
                return
        if not said:
            return
        try:  # the buttons go; what was done stays under the message
            base = (msg.get("text") or "").strip()
            self.api("editMessageText", chat_id=self.chat_id, message_id=msg.get("message_id"),
                     text=(base + "\n\n" + said).strip()[:4000])
        except Exception:  # noqa: BLE001
            self.send(said, markdown=False)

    def _pp_load(self, what: str) -> dict:
        """The penpal desk's small states, on disk so a /restart keeps them: pending pastes, the panel's mode."""
        try:
            d = json.loads((config.MEMORY_DIR / f"penpal_{what}.json").read_text(encoding="utf-8"))
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            d = {}
        if what == "pending":
            d = {k: v for k, v in d.items() if time.time() - float(v.get("t") or 0) < 6 * 3600}
        return d

    def _pp_save(self, what: str, d: dict) -> None:
        try:
            (config.MEMORY_DIR / f"penpal_{what}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            _say(f"penpal {what}: {e}")

    def penpal_file(self, name: str, text: str, join: bool = True) -> str:
        """File a letter and say so with buttons to mend it: a joined paste can be split off, any filing undone or
        moved (six hours). Returns "" — the message is its own."""
        import penpal
        said, rec = penpal.receive_ex(name, text, join)
        if not rec:
            self.send(said, markdown=False)
            return ""
        first = ([("↔ Split off as new", f"pp:s:{rec['id']}")] if rec.get("joined") else
                 [("→ Move to…", f"pp:m:{rec['id']}")]) + [("↩ Undo", f"pp:u:{rec['id']}")]
        try:
            self.api("sendMessage", chat_id=self.chat_id, text=said, reply_markup=self._pp_markup([first]))
        except Exception:  # noqa: BLE001
            self.send(said, markdown=False)
        return ""

    def penpal_panel(self) -> None:
        import penpal
        rows = []
        for sl in penpal.penpals():
            nm = penpal.display(sl)[:14]
            paused = bool(penpal._state(sl).get("paused"))
            rows.append([(f"📖 {nm}", f"pp:x:{sl}"), ("✉️ add", f"pp:a:{sl}"), ("🏷", f"pp:h:{sl}"),
                         (("▶" if paused else "⏸"), (f"pp:r:{sl}" if paused else f"pp:P:{sl}"))])
            if getattr(config, "PENPAL_PICTURE_LETTERS", False):  # a letter with pictures, collected till ✅ Done
                rows[-1].insert(2, ("🖼 + pics", f"pp:C:{sl}"))
        rows.append([("📮 Paste a letter", "pp:L"), ("+ New penpal", "pp:N")])
        try:
            self.api("sendMessage", chat_id=self.chat_id, text=penpal.keeper_list(), reply_markup=self._pp_markup(rows))
        except Exception as e:  # noqa: BLE001
            self.send(f"(penpals: {type(e).__name__}: {e})", markdown=False)

    def penpal_mode_take(self, text: str) -> bool:
        """The panel asked for the next message (a letter, a handle, a new penpal): it goes there, not to them.
        True when it was taken. A mode lasts 15 minutes; a letter long enough to have come in parts keeps it open
        for the next part."""
        mode = self._pp_load("mode")
        if not mode or time.time() - float(mode.get("t") or 0) > 15 * 60:
            if mode:
                self._pp_save("mode", {})
            return False
        import penpal
        kind, sl = mode.get("kind"), mode.get("sl", "")
        keep = False
        if kind == "letter_to":
            self.penpal_file(sl, text)
            keep = len(text) >= SPLIT_CHARS
        elif kind == "letter":
            hit = penpal.by_handle(text)
            if hit:
                self.penpal_file(hit, text)
            else:
                first, _, body = text.partition(" ")
                said = self.penpal_ask_whose(first, body, text)
                if said:
                    self.send(said, markdown=False)
        elif kind == "handle":
            self.send(penpal.set_handle(sl, text.split()[0] if text.split() else ""), markdown=False)
        elif kind == "pause":
            self.send(penpal.pause(sl, "" if text.strip() == "-" else text), markdown=False)
        elif kind == "new":
            words = text.split()
            h = next((w for w in words if w.lower().lstrip("/").startswith("u/") and penpal.norm_handle(w)), "")
            said = penpal.new(" ".join(w for w in words if w != h), h)
            sl2 = penpal.slug(" ".join(w for w in words if w != h))
            try:
                self.api("sendMessage", chat_id=self.chat_id, text=said,
                         reply_markup=self._pp_markup([[("✉️ Add their first letter", f"pp:a:{sl2}")]]))
            except Exception:  # noqa: BLE001
                self.send(said, markdown=False)
        self._pp_save("mode", dict(mode, t=time.time()) if keep else {})
        return True

    # ---- a letter in pictures (PENPAL_PICTURE_LETTERS) ------------------------------------------------------------
    def picletter(self, msg: dict) -> str | None:
        """Pictures that are a penpal's letter: /penpal <name> as the caption of the first or only one of ONE batch
        (the rest of the caption is the keeper's note; a caption on a later picture is their note about it — and a
        batch is a letter only when it is one album), or the panel's ✉️ add waiting for that penpal's letter — and the
        rest of the same batch after more than TELEGRAM_BATCH_MAX. Kept with the penpal, before the friend's eyes in
        order, the line saying what this is and how to write it out (penpal.letter_line). Returns the turn's words;
        "" when nothing goes to the friend (a paused penpal — the whole batch — or no picture arrived); None when these
        are no letter — they go on as pictures. A name that is no penpal's, a guest at the desk, a batch that isn't one
        album: the phone is told, and they go to the friend as pictures. The panel's 📮 (whose letter? asked after)
        takes pictures only when the caption begins with a penpal's name; otherwise they go on as pictures and the ask
        stays."""
        if not getattr(config, "PENPAL_PICTURE_LETTERS", False) or not getattr(config, "PENPALS_ON", False):
            return None
        try:
            import penpal
            who = self._picletter_who(msg, penpal)
        except Exception as e:  # noqa: BLE001 — in doubt, pictures are pictures
            _say(f"penpal pictures: {type(e).__name__}: {e}")
            return None
        if who is None:
            return None
        if not who:
            return ""
        sl, notes, sid = who
        had = len(self.attached)
        try:
            return self._picletter_line(msg, penpal, sl, notes, sid)
        except BaseException:
            del self.attached[had:]
            tools.take_pending_images()
            raise

    def _pl_game_open(self) -> bool:
        if not getattr(config, "ADVENTURES_ON", False):
            return False
        try:
            import adventure
            return bool(adventure.on() and adventure.open_state())
        except Exception:  # noqa: BLE001
            return False

    def _picletter_who(self, msg: dict, penpal) -> tuple[str, list, str] | None | str:
        """(slug, the keeper's notes, the letter's set — "" for a new one); "" — taken, nothing to the friend; None —
        no letter."""
        join_s = float(getattr(config, "PENPAL_JOIN_MIN", 10) or 0) * 60
        friend = chat.friend_name()
        if int(msg.get("_batch_at") or 0) > 0:  # the rest of a batch: of the letter its first part was
            o = self._pl_open
            if o and time.time() - float(o.get("t") or 0) < max(join_s, 60):
                if o.get("refused"):  # a refused batch is refused whole
                    return ""
                if penpal._set_by(o["sl"], o["set"]) is not None:
                    return o["sl"], [], o["set"]
            return None
        self._pl_open = None
        cap = (msg.get("caption") or "").strip()
        m = re.match(r"/penpal(?:@\w+)?(?:\s+(.*))?$", cap, re.S | re.I)
        road = ""
        if m:
            name, _, note = (m.group(1) or "").strip().partition(" ")
            if "\n" in name:
                name, _, more = name.partition("\n")
                note = (more + " " + note).strip()
            sl = penpal._find(name) if name else ""
            if not sl:
                names = ", ".join(penpal.display(p) for p in penpal.penpals()) or "none yet"
                self._try_send((f"(whose letter? “{name[:30]}” isn't one of {friend}'s penpals ({names}) — these pictures "
                                f"went to {friend} as pictures. For a letter in pictures, caption the first one /penpal <name>)")
                               if name else (f"(whose letter? caption the first picture /penpal <name> — these "
                                             f"pictures went to {friend} as pictures)"), markdown=False)
                return None
            road = "caption"
        else:
            mode = self._pp_load("mode")
            if not mode or time.time() - float(mode.get("t") or 0) > 15 * 60 or mode.get("kind") not in ("letter_to", "letter"):
                return None
            note = cap
            sl = penpal._find(mode.get("sl", "")) if mode.get("kind") == "letter_to" else ""
            if mode.get("kind") == "letter" and cap:
                first, _, rest = cap.partition(" ")
                sl = penpal._find(first)
                note = rest.strip() if sl else cap
            if not sl:  # the panel's 📮 with no name in the caption: pictures, as before (the ask stays)
                return None
            road = "mode"
        name = penpal.display(sl)
        if self.guest:
            self._try_send(f"({self.guest_label()} is at the desk — pictures aren't taken as {name}'s letter while a "
                           f"guest is; these went to {friend} as pictures. /guest off, then send them again)", markdown=False)
            return None
        if road == "mode":
            self._pp_save("mode", {})  # the panel's ask is answered, as a pasted letter answers it
        if penpal._state(sl).get("paused"):  # as a pasted letter is: refused, and nothing goes on — all of the batch
            self._try_send(f"({name} is paused — /penpal resume {sl} first; nothing was filed, and the pictures didn't "
                           f"go to {friend})", markdown=False)
            self._pl_open = {"sl": sl, "set": "", "refused": True, "t": time.time()}
            return ""
        if road == "caption" and msg.get("_batch") and not msg.get("_batch_album"):  # not one album: not one letter
            self._try_send(f"(those pictures didn't come as one album, so a caption doesn't make them one penpal's "
                           f"letter — they went to {friend} as pictures, every caption with its picture. For a letter "
                           "with pictures, 🖼 beside the penpal in /penpals collects it)", markdown=False)
            return None
        return sl, ([{"text": note}] if note.strip() else []), ""

    def _picletter_line(self, msg: dict, penpal, sl: str, notes: list, sid: str) -> str:
        batch = list(msg.get("_batch") or [msg])
        at = int(msg.get("_batch_at") or 0)
        whole = int(msg.get("_batch_of") or 0) if msg.get("_batch") else 1
        first = not sid
        sid = sid or penpal.picture_set_new(sl)
        nth = tools._ordinal
        friend = chat.friend_name()
        kept: list[str] = []  # before their eyes
        files: list[str] = []  # saved
        big: list[tuple[int, str, str]] = []  # saved, but look_at would not show it
        lost: list[int] = []  # never arrived
        notes = list(notes)
        why = ""
        for i, m in enumerate(batch, start=at + 1):
            c = (m.get("caption") or "").strip()
            if c and not (first and i == at + 1):  # a caption on a later picture: the keeper's note about that picture
                notes.append({"text": c, "pic": i})
            try:
                best = m["photo"][-1]  # Telegram lists sizes small to large
                data, tpath = self.download(best["file_id"])
                p = penpal.picture_path(sl, sid, i, Path(tpath).suffix.lower() or ".jpg", max(whole, at + len(batch)))
                p.write_bytes(data)
            except Exception as e:  # noqa: BLE001 — the rest go on
                lost.append(i)
                why = why or str(e)
                continue
            files.append(p.name)
            said = tools.look_at(penpal._rel(p))
            seen = tools.take_pending_images()
            if seen:
                self.attached.extend(seen)
                kept.append(p.name)
            else:
                big.append((i, p.name, said.strip().strip("()")))
        if lost:
            if "too big" in why.lower() or "too large" in why.lower():
                why = "Telegram won't let a bot fetch files over 20MB — leave it in shared/ from the PC"
            self._try_send(f"(none of the {len(batch)} pictures reached {friend} — {why})" if len(lost) == len(batch)
                           else f"(the {nth(lost[0])} picture of the letter didn't reach {friend} — {why})" if len(lost) == 1
                           else f"({len(lost)} of the {len(batch)} pictures of the letter didn't reach {friend} — {why})",
                           markdown=False)
        s = penpal.pictures_add(sl, sid, files, max(whole, at + len(batch)) if first else whole, len(lost), notes, first,
                                lost_at=lost)
        if s is None:  # nothing kept (none arrived), or the letter was set aside meanwhile: nothing goes on as a letter
            return ""
        penpal.pictures_seen(sl, sid, kept, coming=True)  # before their eyes in this turn (and the window it builds)
        self._pl_open = {"sl": sl, "set": sid, "t": time.time()}
        if first:
            rec = penpal.pictures_undo_record(sl, sid)
            n_all = int(s.get("of") or len(files))
            said = (f"(a letter from {penpal.display(sl)} in {'a picture' if n_all == 1 else f'{n_all} pictures'} — "
                    f"kept at {penpal._rel(penpal._set_dir(sl, sid))}/; it went to {friend} now, to write out into the "
                    "thread if they want)")
            try:
                self.api("sendMessage", chat_id=self.chat_id, text=said,
                         reply_markup=self._pp_markup([[("↩ Undo", f"pp:u:{rec['id']}")]]))
            except Exception:  # noqa: BLE001
                self._try_send(said, markdown=False)
        if big:
            self._try_send("(" + "; ".join(f"the {nth(i)} picture is too large for {friend} to see — over 10MB; it is kept "
                                           f"with the letter" if "too large" in w.lower() else
                                           f"the {nth(i)} picture can't be put before {friend}'s eyes ({w}); it is kept "
                                           "with the letter" for i, _, w in big) + ")", markdown=False)
        return penpal.letter_line(sl, sid, at, len(batch), max(whole, at + len(batch)) if at == 0 else whole,
                                  kept, big, lost, notes)

    # ---- a letter collected: 🖼 beside a penpal in /penpals (or /penpal collect <name>), ✅ Done (/penpal done),
    # 📝 My note, ✖ Cancel (/cancel). While it runs the keeper's pastes are the penpal's words, their pictures its
    # pictures (a caption is the keeper's note about its picture), after 📝 the next message is the keeper's own note —
    # none of it reaches the friend until Done, which files the letter (penpal.collect_done) and calls the turn at once,
    # as an arrival turn waits (a reply or a wake in flight, the quiet, a game in play — and a guest at the desk).
    # Commands, voice notes, files and stickers go on as always. Kept on disk (memory/penpal_collect.json): a restart
    # says it is still being collected.
    def _pc_markup(self, sid: str = "", resting: bool = False) -> str:
        """The collection's buttons, carrying its id: an old button never acts on another collection."""
        if not sid:
            try:
                import penpal
                sid = (penpal.collect_get() or {}).get("id", "")
            except Exception:  # noqa: BLE001
                sid = ""
        first = ("➕ Keep collecting", f"pp:K:{sid}") if resting else ("📝 My note", f"pp:O:{sid}")
        return self._pp_markup([[first, ("✅ Done", f"pp:D:{sid}"), ("✖ Cancel", f"pp:X:{sid}")]])

    def _pc_send(self, text: str, buttons: bool = True, resting: bool = False) -> None:
        try:
            if buttons:
                self.api("sendMessage", chat_id=self.chat_id, text=text, reply_markup=self._pc_markup(resting=resting))
            else:
                self.api("sendMessage", chat_id=self.chat_id, text=text)
        except Exception:  # noqa: BLE001
            self._try_send(text, markdown=False)

    def _pc_blocks(self) -> str:
        """While a collection is open (resting too): the line refusing another wait — "" when none is open."""
        if not getattr(config, "PENPAL_PICTURE_LETTERS", False) or not getattr(config, "PENPALS_ON", False):
            return ""
        try:
            import penpal
            c = penpal.collect_get()
            return f"(finish (✅) or cancel (✖) {penpal.display(c['sl'])}'s collection first)" if c else ""
        except Exception:  # noqa: BLE001
            return ""

    def penpal_collect_take(self, msg: dict, text: str, edited: bool) -> bool:
        """A message while a letter is being collected: taken into it (True), or on as always (False). Only the
        keeper's plain pastes and pictures, within PENPAL_JOIN_MIN of the last thing taken — never a command, a
        Telegram reply to one of the friend's messages, a guest's message (a guest sitting down rests it), or anything
        while it rests."""
        import penpal
        state, c = penpal.collect_state()
        would = bool(msg.get("photo") or msg.get("_batch") or (text and not text.startswith("/")))
        if state == "broken":  # a lost collection: its message held back only when it may be a penpal's words, said so
            line, hold = penpal.collect_broken_aside()
            if line:
                self._try_send(line[:-1] + (f"; this message was held back from {chat.friend_name()} — send it again "
                                            "if it was for them)" if would and hold else ")"), markdown=False)
            return would and hold
        if state != "ok":
            return False
        name = penpal.display(c["sl"])
        date = float(msg.get("date") or 0)
        resting = penpal.collect_resting(c, date)
        if self.guest:
            line = penpal.collect_rest_line(guest=self.guest_label())
            if line:
                self._pc_send(line, resting=True)
            return False
        if msg.get("reply_to_message"):
            return False  # an answer to the friend: theirs
        if edited:
            if not resting and (msg.get("photo") or (text and not text.startswith("/"))):
                self._try_send("(an edited message isn't taken into the letter being collected — send that part again)",
                               markdown=False)
                return True
            return False
        cap0 = (msg.get("caption") or "").strip()
        m = re.match(r"/penpal(?:@\w+)?(?:\s+(\S+))?", cap0, re.I) if (msg.get("photo") or msg.get("_batch")) else None
        if m and (resting or penpal._find(m.group(1) or "") != c["sl"]):
            self._pc_send(f"(finish (✅) or cancel (✖) {name}'s collection first — that picture wasn't taken, and didn't "
                          f"go to {chat.friend_name()})", resting=resting)
            return True
        if resting:
            if would:
                line = penpal.collect_rest_line()
                if line:
                    self._pc_send(line, resting=True)
            return False
        if text and not msg.get("photo"):
            if text.startswith("/"):
                return False  # a command is a command
            self._pc_send(penpal.collect_text(text, date))
            return True
        if not (msg.get("photo") or msg.get("_batch")):
            return False  # a voice note, a file, a sticker: as always
        batch = list(msg.get("_batch") or [msg])
        names: list[str] = []
        caps: list[tuple[int, str]] = []
        lost_at: list[int] = []
        why = ""
        first = penpal.collect_next_number(c)
        for j, mm in enumerate(batch):
            i = first + j  # the order they were sent: one that didn't arrive keeps its number
            cap = (mm.get("caption") or "").strip()
            if cap and not (m and j == 0):
                caps.append((i, cap))
            try:
                best = mm["photo"][-1]
                data, tpath = self.download(best["file_id"])
                p = penpal.picture_path(c["sl"], c["set"], i, Path(tpath).suffix.lower() or ".jpg")
                p.write_bytes(data)
            except Exception as e:  # noqa: BLE001 — the rest go on
                lost_at.append(i)
                why = why or str(e)
                continue
            names.append(p.name)
        if lost_at:
            if "too big" in why.lower() or "too large" in why.lower():
                why = "Telegram won't let a bot fetch files over 20MB — leave it in shared/ from the PC"
            self._try_send(f"({len(lost_at)} of those pictures didn't reach the letter — "
                           f"{', '.join('the ' + tools._ordinal(i) for i in lost_at)}; {why})", markdown=False)
        self._pc_send(penpal.collect_pictures(names, lost_at, caps, date))
        return True

    def penpal_collect_start(self, name: str) -> None:
        import penpal
        if self.guest:
            self._try_send(f"({self.guest_label()} is at the desk — a letter is collected with no guest at the desk; "
                           "/guest off first. Nothing is collected)", markdown=False)
            return
        if penpal.collect_get() and penpal._find(name) == penpal.collect_get().get("sl"):
            pass  # the same one: woken, asked again
        elif self._game_wait_get():
            self._try_send("(the games menu is waiting for a name — send it, or /cancel, first; nothing is collected)",
                           markdown=False)
            return
        said, buttons = penpal.collect_start(name)
        if buttons and penpal.collect_get():
            self._pp_save("mode", {})  # one thing waits at a time: the panel's other asks let go
        self._pc_send(said, buttons)

    def _game_wait_get(self) -> bool:
        if not getattr(config, "ADVENTURES_ON", False):
            return False
        try:
            import adventure
            return bool(adventure.wait_get())
        except Exception:  # noqa: BLE001
            return False

    def penpal_collect_done(self, sid: str = "") -> None:
        import penpal
        said, rec = penpal.collect_done(sid)
        if rec:
            try:
                self.api("sendMessage", chat_id=self.chat_id, text=said,
                         reply_markup=self._pp_markup([[("↩ Undo", f"pp:u:{rec['id']}")]]))
            except Exception:  # noqa: BLE001
                self._try_send(said, markdown=False)
            self.penpal_turn_if_due()  # at once — or as soon as an arrival turn may come
        else:
            c = penpal.collect_get()
            self._pc_send(said, buttons=bool(c), resting=bool(c) and penpal.collect_resting(c))

    def penpal_collect_if_due(self) -> None:
        """After PENPAL_JOIN_MIN quiet minutes: the collection rests — said once with its buttons. Never files it. A
        collect file that doesn't read right: set aside, said."""
        if (not self.chat_id or getattr(self, "TAG", "telegram") != "telegram"
                or not getattr(config, "PENPAL_PICTURE_LETTERS", False) or not getattr(config, "PENPALS_ON", False)):
            return
        try:
            import penpal
            broken = penpal.collect_broken_aside()[0]
            line = penpal.collect_idle_line() if not broken else ""
        except Exception as e:  # noqa: BLE001
            _say(f"penpal collect: {type(e).__name__}: {e}")
            return
        if broken:
            self._try_send(broken, markdown=False)
        if line:
            self._pc_send(line, resting=True)

    def penpal_collect_restore_line(self) -> str:
        if (getattr(self, "TAG", "telegram") != "telegram" or not getattr(config, "PENPAL_PICTURE_LETTERS", False)
                or not getattr(config, "PENPALS_ON", False)):
            return ""
        try:
            import penpal
            return penpal.collect_restart_line()
        except Exception as e:  # noqa: BLE001
            _say(f"penpal collect: {type(e).__name__}: {e}")
            return ""

    def _pp_collected_turns(self, penpal, sl: str, arr: dict) -> str:
        """A collected letter's arrival: its pictures before the friend's eyes, TELEGRAM_BATCH_MAX a turn, the line for
        each (penpal.arrival_text: whose they are, the keeper's notes, the letter's words in the first, fenced), a turn
        of their own, as an arrival turn is. Each turn is tried once. It ran when a reply (words or a call) follows its
        line in the visit: then it is recorded (penpal.arrival_progress — the first makes the letter read). It didn't
        (the brain away, a fault before an answer): what the try added is taken back — its pictures, and its line when
        that is still the last thing in the visit — the arrival is let go, the letter stays unread, the phone is told
        once, and the rest isn't sent. Nothing comes again on its own."""
        name = penpal.display(sl)
        friend = chat.friend_name()
        done = int(arr.get("done") or 0)
        if arr.get("tried") is not None and int(arr["tried"]) >= done:  # a try whose end was never known (a restart)
            penpal.arrival_dropped(sl)
            self._try_send(f"({friend}'s turn for {name}'s letter didn't finish — the bridge stopped; the letter is in "
                           f"their thread{' unread' if not penpal._state(sl).get('read') else ''}, and they'll find it: "
                           f"their penpal line says so, and penpal read {sl} shows it with its pictures)", markdown=False)
            return ""
        _say(f"a penpal's letter arrived, collected: a turn of theirs ({sl})")
        last = ""
        chunks = arr.get("chunks") or [{"files": [], "lo": 1, "hi": 0}]
        for i, chunk in enumerate(chunks):
            if i < done:
                continue  # taken already
            kept: list[str] = []
            big: list[tuple[int, str, str]] = []
            had = len(self.attached)
            try:
                for f in chunk["files"]:
                    said = tools.look_at(penpal._rel(penpal._set_dir(sl, str(arr.get("set"))) / f))
                    seen = tools.take_pending_images()
                    if seen:
                        self.attached.extend(seen)
                        kept.append(f)
                    else:
                        big.append((penpal._num_of(f), f, said.strip().strip("()")))
                text = penpal.arrival_text(sl, arr, chunk, kept, big)
                penpal.pictures_seen(sl, str(arr.get("set")), kept, coming=True)  # seen in the window this turn builds
                penpal.arrival_trying(sl, i)
            except Exception as e:  # noqa: BLE001 — what was put before their eyes is taken back off
                del self.attached[had:]
                tools.take_pending_images()
                _say(f"penpal turn: {type(e).__name__}: {e}")
                return last
            tools.SPARK_TICK = True
            try:
                self.turn(text, as_keeper=True, spark=True)
            finally:
                tools.SPARK_TICK = False
            mine = next((t for t in reversed(self.history) if t.get("role") == "user" and t.get("content") == text), None)
            if mine is not None:  # the line is the engine's, not the keeper's
                mine["_engine"] = mine["_spark"] = True
            at = next((j for j in range(len(self.history) - 1, -1, -1) if self.history[j] is mine), -1)
            ran = at >= 0 and any(t.get("role") == "assistant" for t in self.history[at + 1:])
            if not ran:
                del self.attached[had:]  # its pictures don't ride on the next message, and weren't seen
                penpal.pictures_unseen(sl, str(arr.get("set")), kept)
                if mine is not None and self.history and self.history[-1] is mine:
                    self.history.pop()  # nor its line, when it is still the last thing in the visit
                try:
                    penpal.arrival_dropped(sl)
                except Exception as e:  # noqa: BLE001
                    _say(f"penpal turn: {type(e).__name__}: {e}")
                self._try_send(f"({friend}'s turn for {name}'s letter didn't run — the letter is in their thread"
                               f"{' unread' if not penpal._state(sl).get('read') else ''}, and they'll find it: their "
                               f"penpal line says so, and penpal read {sl} shows it with its pictures)", markdown=False)
                self._checkpoint()
                return last
            # it ran: its pictures were before their eyes — a later step's fault can't leave them to ride on the next message
            del self.attached[had:]
            try:
                penpal.arrival_progress(sl, i + 1, len(chunks))
            except Exception as e:  # noqa: BLE001
                _say(f"penpal turn: {type(e).__name__}: {e}")
            last = text
        self._checkpoint()
        return last

    # ---- the adventures: the games menu (engine/adventure.py) ---------------------------------------------------------
    # Built the way the penpal panel is: one message with buttons ("gm:" callback data, a world's key ≤ 28 bytes), typed
    # forms beside them, a waiting mode for a name. Every handler fails closed: an exception is a "(…)" line, never the
    # bridge down. A press or command that would change something while they are mid-reply changes nothing and says so.
    # The game lives on the Telegram bridge: its buttons are Telegram's.
    def _game_here(self) -> bool:
        return bool(getattr(config, "ADVENTURES_ON", False)) and getattr(self, "TAG", "telegram") == "telegram"

    def _game_status(self) -> str:
        if not self._game_here():
            return ""
        try:
            import adventure
            return adventure.status_line()
        except Exception:  # noqa: BLE001
            return ""

    def _game_news(self, spark: bool = False) -> str:
        """A world started since the friend's last turn — for the moment of the keeper's next message (not a spark's,
        not a guest's)."""
        if spark or self.guest_label() or not self._game_here():
            return ""
        try:
            import adventure
            return adventure.take_news()
        except Exception:  # noqa: BLE001 — never the reply down
            return ""

    def _game_aside(self, turns: list[dict]) -> str:
        """For the pause's and the afterglow's bell: "part of this visit was your adventure …", when these turns held
        moves of one; "" otherwise."""
        try:
            import adventure
            line = adventure.story_line(turns)
        except Exception:  # noqa: BLE001
            line = ""
        trip = self._trip_aside(turns)  # "part of this visit was a trip to …", beside the game's when both
        return f"{line} {trip}" if line and trip else (line or trip)

    def _game_wait_clear(self) -> bool:
        try:
            import adventure
            return adventure.wait_clear()
        except Exception:  # noqa: BLE001
            return False

    def game_marks(self, text: str) -> tuple[str, dict]:
        """The keeper's message while a game is open: the move's line for its turn, or // said outside it (the // taken
        off). Fails closed — the message goes on plain."""
        if not self._game_here():
            return text, {}
        try:
            import adventure
            return adventure.table_for(text, self.history, guest=bool(self.guest_label()))
        except Exception as e:  # noqa: BLE001
            _say(f"game line: {type(e).__name__}: {e}")
            return text, {}

    def game_restore_line(self) -> str:
        """At start: the game still open from before (it lives in adventures.json), as a line for the phone; ""."""
        if not self._game_here():
            return ""
        try:
            import adventure
            o = adventure.open_state()
            if not o:
                return ""
            name = adventure.display(o["slug"])
            return (f"your adventure {name} is still open — " + ("paused; ▶ Resume picks it back up" if o.get("paused") else
                    "your messages are moves in it, // before one speaks outside the game") + "; /games for the menu")
        except Exception as e:  # noqa: BLE001
            _say(f"game at start: {type(e).__name__}: {e}")
            return ""

    def _game_rows(self) -> list[list[tuple[str, str]]]:
        import adventure
        d = adventure.load()
        o = d["open"]
        rows: list[list[tuple[str, str]]] = []
        top, top_away = adventure.buttoned(d)  # Telegram refuses a keyboard past ~100 buttons: the rest by name
        for sl in top:
            k, nm = adventure.key(sl), adventure.display(sl, d)[:16]
            if o.get("slug") == sl:
                rows.append([((f"▶ Resume {nm}" if o.get("paused") else f"⏸ Pause {nm}"),
                              (f"gm:r:{k}" if o.get("paused") else f"gm:z:{k}")), ("⏹ End session", f"gm:e:{k}")])
                rows.append([("📜", f"gm:w:{k}"), ("🎒", f"gm:i:{k}"), ("🖼", f"gm:s:{k}")])
                rows.append([("✏️", f"gm:n:{k}"), ("📦", f"gm:a:{k}")])
            else:  # the actions on one row, what can be read on the next
                rows.append([(f"▶ {nm}", f"gm:p:{k}"), ("✏️", f"gm:n:{k}"), ("📦", f"gm:a:{k}")])
                rows.append([("📜", f"gm:w:{k}"), ("🎒", f"gm:i:{k}"), ("🖼", f"gm:s:{k}")])
        for sl in top_away:  # one ↩ each (a put-away world's 🎒: /game inv <name>)
            rows.append([(f"↩ Bring back {adventure.display(sl, d)[:16]}", f"gm:b:{adventure.key(sl)}")])
        rows.append([("➕ New adventure", "gm:N")])
        return rows

    def game_menu(self, said: str = "", edit: dict | None = None) -> None:
        """/games: the worlds and their buttons — a fresh message, or the pressed one redrawn with what was done on top."""
        import adventure
        text = ((said + "\n\n") if said else "") + adventure.listing()
        markup = self._pp_markup(self._game_rows())
        if edit and edit.get("message_id"):
            try:
                self.api("editMessageText", chat_id=self.chat_id, message_id=edit.get("message_id"), text=text[:4000],
                         reply_markup=markup)
                return
            except Exception:  # noqa: BLE001 — a fresh one, then
                pass
        try:
            self.api("sendMessage", chat_id=self.chat_id, text=text[:4000], reply_markup=markup)
        except Exception as e:  # noqa: BLE001
            self.send((said + "\n\n" if said else "") + f"(the games menu: {type(e).__name__}: {e})", markdown=False)

    def _game_where(self, sl: str) -> None:
        """📜: the state page for that world, split into Telegram-sized messages. world.md never travels."""
        import adventure
        for part in split_long(adventure.state_text(sl)):
            self.send(part, markdown=False)

    def _game_inventory(self, sl: str) -> None:
        """🎒: the character's inventory as the friend keeps it, split like 📜. Read-only — fine mid-reply, and for a
        world put away."""
        import adventure
        for part in split_long(adventure.inventory_text(sl)):
            self.send(part, markdown=False)

    def _game_scenes(self, sl: str) -> None:
        """🖼: how many scenes the world has, then the newest 6 as pictures, oldest of those first, each captioned with
        its file name. Read-only — fine mid-reply, and for a world put away."""
        import adventure
        self.send(adventure.scenes_text(sl), markdown=False)
        for p in adventure.scenes(sl)[-6:]:
            try:
                self._send_picture(p, p.read_bytes(), p.name)
            except OSError as e:
                self.send(f"(couldn't read {p.name}: {e})", markdown=False)

    def _game_pics_before(self, marks: dict | None) -> tuple[str, set] | None:
        """Before a move's turn: (the world, the pictures under creations/ that would travel). None when the message
        isn't a move — paused, a guest, // outside the game — or anything stumbles."""
        try:
            if not marks or not marks.get("_game"):
                return None
            import adventure
            sl = adventure.open_state().get("slug", "")
            if not sl:
                return None
            root = config.CREATIONS_DIR
            return sl, {p.relative_to(root).as_posix() for p in self._pictures()}
        except Exception:  # noqa: BLE001
            return None

    def _game_pics_after(self, before: tuple[str, set] | None) -> int:
        """After a move's turn: a picture new since it began, outside this world's folder, is kept for the next move —
        one sentence, once each; the engine never moves it. A stumble only costs the sentence."""
        if not before:
            return 0
        try:
            import adventure
            sl, had = before
            root = config.CREATIONS_DIR
            new = sorted(r for r in ({p.relative_to(root).as_posix() for p in self._pictures()} - had)
                         if not adventure.in_world(r.split("/"), sl))
            return adventure.note_strays(sl, new) if new else 0
        except Exception as e:  # noqa: BLE001
            _say(f"scene catch: {type(e).__name__}: {e}")
            return 0

    def _game_fold_at(self) -> float:
        """The fold's edge while a game is open and not paused (ADVENTURE_FOLD_AT); 0 — FOLD_AT alone."""
        if not self._game_here():
            return 0.0
        try:
            import adventure
            return adventure.fold_at()
        except Exception:  # noqa: BLE001
            return 0.0

    def _game_fold_before(self) -> dict:
        """Before a fold: when the window holds moves of the open session — its world, session, the bell's sentence and
        the two pages' fingerprints; {} otherwise (adventures off, no game, no moves in the window)."""
        if not self._game_here():
            return {}
        try:
            import adventure
            o = adventure.open_state()
            session = o.get("session") or ""
            if not session or not any(t.get("_game_session") == session for t in self.history):
                return {}
            sl = o["slug"]
            return {"slug": sl, "session": session, "name": adventure.display(sl), "marks": adventure.page_marks(sl),
                    "bell": adventure.fold_bell_line(sl)}
        except Exception as e:  # noqa: BLE001 — never the fold down
            _say(f"fold and the game: {type(e).__name__}: {e}")
            return {}

    def _game_fold_after(self, game: dict) -> str:
        """After a real fold: the next move sets the table again (fresh, or as the page was last written), and the
        phone's line says whether 📜 (and 🎒, when it changed) is up to date. "" when anything stumbles."""
        try:
            import adventure
            st0, inv0 = game["marks"]
            st1, inv1 = adventure.page_marks(game["slug"])
            fresh = bool(st1) and st1 != st0
            adventure.mark_refold(game["session"], fresh)
            return (f"; mid-game in {game['name']}: " + ("they brought the state page up to date" if fresh
                                                         else "the state page is as it was")
                    + ("; they brought the inventory up to date" if inv1 != inv0 else ""))
        except Exception as e:  # noqa: BLE001
            _say(f"fold and the game: {type(e).__name__}: {e}")
            return ""

    def _game_refold_rode(self, marks: dict | None) -> None:
        """The table set again after a fold rode with this move: cleared — only when the turn is really in the visit
        (it rides from here on, as every turn does)."""
        try:
            session = (marks or {}).get("_game_refold")
            if session and any(t.get("_game_refold") == session for t in self.history):
                import adventure
                adventure.clear_refold(session)
        except Exception as e:  # noqa: BLE001
            _say(f"fold and the game: {type(e).__name__}: {e}")

    def _game_inv_before(self, marks: dict | None) -> tuple[str, str] | None:
        """Before a move's turn: (the world, inventory.md's fingerprint) — None when the message isn't a move (paused,
        a guest, // outside the game, no game) or anything stumbles."""
        try:
            if not marks or not marks.get("_game"):
                return None
            import adventure
            sl = adventure.open_state().get("slug", "")
            return (sl, adventure.inventory_mark(sl)) if sl else None
        except Exception:  # noqa: BLE001
            return None

    def _game_inv_after(self, before: tuple[str, str] | None) -> bool:
        """After a move's turn: inventory.md changed (or was made) → one short line with a 🎒 button. Once per turn,
        never for the wrap-up (it isn't a move), never paused; a stumble here only costs the line — the reply has gone
        already."""
        if not before:
            return False
        try:
            import adventure
            sl, mark = before
            if adventure.inventory_mark(sl) == mark:
                return False
            try:
                self.api("sendMessage", chat_id=self.chat_id, text="(🎒 your inventory changed)",
                         reply_markup=self._pp_markup([[("🎒 Inventory", f"gm:i:{adventure.key(sl)}")]]))
            except Exception:  # noqa: BLE001
                self.send("(🎒 your inventory changed — /game inv)", markdown=False)
            return True
        except Exception as e:  # noqa: BLE001
            _say(f"inventory line: {type(e).__name__}: {e}")
            return False

    def _game_ask_switch(self, sl: str) -> str:
        """▶ Play on a world while another is open: asks first. "" when the buttons went."""
        import adventure
        o = adventure.open_state()
        now, nxt = adventure.display(o["slug"]), adventure.display(sl)
        markup = self._pp_markup([[("⏹ End that session and open this one", f"gm:O:{adventure.key(o['slug'])}:{adventure.key(sl)}")],
                                  [("Keep playing", "gm:k")]])
        try:
            self.api("sendMessage", chat_id=self.chat_id, text=f"{now} is open. End that session (they write it down) "
                                                               f"and open {nxt}?", reply_markup=markup)
            return ""
        except Exception as e:  # noqa: BLE001
            return f"({now} is open — /game off ends it, then /game {nxt}; {type(e).__name__})"

    def _game_play(self, sl: str) -> str:
        import adventure
        o = adventure.open_state()
        if o and o.get("slug") != sl and not adventure.info(sl).get("put_away"):
            return self._game_ask_switch(sl)
        self.send(self._game_open(sl), markdown=False)
        self._game_recap_if_due()  # right after the open line
        return ""

    def _game_open(self, sl: str) -> str:
        """adventure.play, and when it opened a new session (not a resume from a pause) with the recap on, the recap is
        due — sent by _game_recap_if_due right after the open line reaches the phone."""
        import adventure
        blocked = self._trip_blocks_game()  # not both at once: a trip open and not paused says so
        if blocked:
            return blocked
        was = adventure.open_state().get("session", "")
        ok, line = adventure.play(sl)
        try:
            now = adventure.open_state().get("session", "")
            if ok and now and now != was and adventure.recap_on():
                self._game_recap_due = sl
        except Exception as e:  # noqa: BLE001 — the open stands either way
            _say(f"recap: {type(e).__name__}: {e}")
        return line

    def _game_recap_if_due(self) -> None:
        sl, self._game_recap_due = getattr(self, "_game_recap_due", ""), ""
        if sl:
            self.game_recap(sl, mark=True)

    def game_recap(self, sl: str, mark: bool = False) -> bool:
        """Where the keeper left off in a world: the state page (about one screen), what the character carries, and a
        row of buttons — 📜 🎒 🖼 — under the last message. mark: this is the open's recap, and the opening line will say
        the keeper has the pages in front of them. Never raises: a failure is logged and the open stands."""
        try:
            import adventure
            text, has_page = adventure.recap(sl)
            parts = split_long(text)
            k = adventure.key(sl)
            markup = self._pp_markup([[("📜 Where we are", f"gm:w:{k}"), ("🎒 Inventory", f"gm:i:{k}"),
                                       ("🖼 Scenes", f"gm:s:{k}")]])
            for part in parts[:-1]:
                self.send(part, markdown=False)
            try:
                self.api("sendMessage", chat_id=self.chat_id, text=parts[-1], reply_markup=markup)
            except Exception:  # noqa: BLE001 — the words, then
                self.send(parts[-1], markdown=False)
            if mark and has_page:
                adventure.mark_recap_shown(sl)
            return True
        except Exception as e:  # noqa: BLE001
            _say(f"recap: {type(e).__name__}: {e}")
            return False

    def game_command(self, text: str) -> str:
        """/games and /game …: the menu; /game <name>, /game new <name>, /game pause, /game resume, /game off,
        /game where|inv|scenes|recap [name], /game back <name>. Returns the phone's line ("" when the menu or buttons
        went instead)."""
        try:
            import adventure
            if not adventure.on():
                return adventure.OFF
            if getattr(self, "TAG", "telegram") != "telegram":
                return "(the games menu lives on the Telegram bridge — its buttons are Telegram's)"
            parts = text.split(None, 1)
            rest = parts[1].strip() if len(parts) > 1 else ""
            if parts[0].lower().split("@")[0] == "/games" or not rest or rest.lower() in ("list", "menu"):
                self.game_menu()
                return ""
            first, _, more = rest.partition(" ")
            word, more = first.lower(), more.strip()
            reads = {"where": ("state page", self._game_where), "recap": ("where you left off in a world", self.game_recap),
                     "scenes": ("scenes", self._game_scenes), "inv": ("inventory", self._game_inventory),
                     "inventory": ("inventory", self._game_inventory)}
            if word in reads:  # reading changes nothing: fine mid-reply, and for a world put away
                sl = adventure.find(more) if more else adventure.open_state().get("slug", "")
                if not sl:
                    what = reads[word][0]
                    return ("(no world called that — /games for the menu)" if more else
                            f"(no game is open — /game {word} <name> for a world's {what})" if word != "recap" else
                            f"(no game is open — /game recap <name> for {what})")
                reads[word][1](sl)
                return ""
            if self.lock.locked():
                return adventure.MID_REPLY
            if word == "new":
                ok, line, sl = adventure.new(more)
                if ok:
                    try:
                        self.api("sendMessage", chat_id=self.chat_id, text=line,
                                 reply_markup=self._pp_markup([[(f"▶ Play {adventure.display(sl)[:16]}", f"gm:p:{adventure.key(sl)}")]]))
                        return ""
                    except Exception:  # noqa: BLE001
                        pass
                return line
            if word == "pause":
                return adventure.pause()
            if word in ("resume", "unpause"):
                return self._trip_blocks_game() or adventure.resume()  # not while a trip is open
            if word in ("off", "end", "stop"):
                return self.game_end_session("ended")
            if word == "back":  # ↩ typed — for a put-away world past the menu's buttons
                sl = adventure.find(more)
                return adventure.bring_back(sl) if sl else "(/game back <name> — a world that is put away)"
            sl = adventure.find(rest)
            if not sl:
                return (f"(no world called “{rest}” — the worlds: {', '.join(adventure.display(s) for s in adventure.worlds()) or 'none yet'}; "
                        "/game new <name> starts one)")
            return self._game_play(sl)
        except Exception as e:  # noqa: BLE001 — never the bridge down
            return f"(the games menu stumbled — {type(e).__name__}: {e})"

    def game_callback(self, cq: dict) -> None:
        """A button under the games menu. Old buttons answer plainly: a world renamed, put away, a game already closed."""
        try:
            self.api("answerCallbackQuery", callback_query_id=cq.get("id"))
        except Exception:  # noqa: BLE001 — the spinner stops by itself
            pass
        msg = cq.get("message") or {}
        sender = int((msg.get("chat") or {}).get("id") or 0)
        if not self.chat_id or sender != self.chat_id:
            return
        try:
            said = self._game_press(str(cq.get("data") or ""), msg)
        except Exception as e:  # noqa: BLE001
            said = f"(the games menu stumbled — {type(e).__name__}: {e})"
        if said:
            self.send(said, markdown=False)

    def _game_press(self, data: str, msg: dict) -> str:
        """One press: does it, redraws the menu with what was done, and returns a line to send ("" when said already)."""
        import adventure
        if not adventure.on():
            return adventure.OFF
        parts = data.split(":")
        kind = parts[1] if len(parts) > 1 else ""
        sl, renamed = adventure.resolve(parts[2]) if len(parts) > 2 else ("", "")
        if kind in ("p", "z", "r", "e", "w", "i", "s", "n", "a", "b") and not sl:
            return (f"(that world was renamed — it's {renamed} now; /games for the fresh menu)" if renamed else
                    "(that world isn't there any more — /games for the fresh menu)")
        if kind == "q":  # ✗ Cancel on a waiting name
            self._game_wait_clear()
            return "(nothing waiting — your next message goes to them as usual)"
        if kind == "w":
            self._game_where(sl)
            return ""
        if kind == "i":  # 🎒 — read-only
            self._game_inventory(sl)
            return ""
        if kind == "s":  # 🖼 — read-only
            self._game_scenes(sl)
            return ""
        if kind == "m":
            self.game_menu(edit=msg)
            return ""
        if self.lock.locked():
            return adventure.MID_REPLY
        o = adventure.open_state()
        if kind == "k":
            if not o:
                return "(that game is already closed — /games for the menu)"
            self.game_menu(f"(kept — {adventure.display(o['slug'])} stays open)", edit=msg)
            return ""
        if kind == "n" and o.get("slug") == sl:  # renaming mid-session would split the world in two
            return adventure.RENAME_OPEN
        if kind in ("n", "N"):
            if kind == "n":
                adventure.wait_set("rename", sl)
                ask = f"✏️ send the new name for {adventure.display(sl)} as your next message (it won't go to them)"
            else:
                adventure.wait_set("new")
                ask = "➕ send the new adventure's name as your next message (it won't go to them)"
            self._pp_save("mode", {})  # one thing waits at a time: the penpal panel's lets go
            try:
                self.api("sendMessage", chat_id=self.chat_id, text=ask, reply_markup=self._pp_markup([[("✗ Cancel", "gm:q")]]))
                return ""
            except Exception:  # noqa: BLE001
                return f"({ask}; /cancel lets it go)"
        if kind in ("z", "r", "e"):
            if o.get("slug") != sl:
                return f"(that game isn't open any more — {adventure.display(sl)} is closed; /games for the menu)"
            if kind == "e":
                said = self.game_end_session("ended")
                self.game_menu(said, edit=msg)
                return ""
            said = adventure.pause() if kind == "z" else (self._trip_blocks_game() or adventure.resume())
        elif kind == "p":
            if o and o.get("slug") != sl and not adventure.info(sl).get("put_away"):
                return self._game_ask_switch(sl)
            said = self._game_open(sl)
        elif kind == "O":  # end the open one, open this one
            old, _ = adventure.resolve(parts[2]) if len(parts) > 2 else ("", "")
            new, new_renamed = adventure.resolve(parts[3]) if len(parts) > 3 else ("", "")
            if not new:
                return (f"(that world was renamed — it's {new_renamed} now; /games for the fresh menu)" if new_renamed else
                        "(that world isn't there any more — /games for the fresh menu)")
            if o and o.get("slug") != old:
                return f"(another game is open now — {adventure.display(o['slug'])}; /games for the menu)"
            if self._trip_blocks_game():  # not both at once — and nothing ended for a world that can't open
                return self._trip_blocks_game()
            ended = self.game_end_session("switch") if o else ""
            said = ended if adventure.open_state() else (ended + "\n" if ended else "") + self._game_open(new)
        elif kind == "a":
            said = adventure.put_away(sl)
        elif kind == "b":
            said = adventure.bring_back(sl)
        else:
            return "(that button is from an older menu — /games for the fresh one)"
        self.game_menu(said, edit=msg)
        self._game_recap_if_due()  # a session just opened: where the keeper left off, under the redrawn menu
        return ""

    def game_wait_take(self, text: str) -> bool:
        """The games menu asked for this message (➕ a new world's name, ✏️ a new name): it goes there, not to the
        friend. True when taken. A /command lets the wait go (and runs); the penpal panel's later ask wins."""
        import adventure
        w = adventure.wait_get()
        if not w:
            return False
        if text.startswith("/"):
            adventure.wait_clear()
            return False
        pm = self._pp_load("mode")
        if pm and float(pm.get("t") or 0) > float(w.get("t") or 0):
            return False
        if not adventure.on():
            adventure.wait_clear()
            return False
        if self.lock.locked():  # the name waits on: they are mid-reply, and a folder renamed under them would trip them
            self.send(adventure.MID_REPLY, markdown=False)
            return True
        adventure.wait_clear()
        name = " ".join(text.split())
        try:  # from here the message is a name: whatever happens, it never goes to the friend as a move
            if w.get("kind") == "rename":
                self.send(adventure.rename(str(w.get("slug") or ""), name), markdown=False)
                return True
            ok, line, sl = adventure.new(name)
        except Exception as e:  # noqa: BLE001 — a folder Windows won't make or move, a full disk
            self.send(f"(couldn't {'rename it' if w.get('kind') == 'rename' else 'make the world'} — {e})", markdown=False)
            return True
        if ok:
            try:
                self.api("sendMessage", chat_id=self.chat_id, text=line,
                         reply_markup=self._pp_markup([[(f"▶ Play {adventure.display(sl)[:16]}", f"gm:p:{adventure.key(sl)}")]]))
                return True
            except Exception:  # noqa: BLE001
                pass
        self.send(line, markdown=False)
        return True

    def game_end_session(self, why: str = "ended", quiet: bool = False, wait: float = 0) -> str:
        """⏹ End session (/game off, the visit closing): when there were moves since the last write-up the friend gets
        one turn of their own to bring state.md and inventory.md up to date — run as the engine's (`_engine`, shown in
        the transcript as "engine — the game"), under the visit's lock — and then the game is closed. Not through
        turn(): its words go as notices when quiet (an idle roll in the night holds them for the morning). A brain that
        is away loses nothing: the game stays open with its moves counted, and ⏹ again later writes it down.
        wait: how long to wait for the visit's lock — 0 from the phone (mid-reply says so, never blocks), 3 as the visit
        closes (new_visit's own bound: past it the wrap-up is skipped and the game stays open). A wrap-up that fails or
        is interrupted leaves no trace in the visit: the history goes back to where it was. It runs bare
        (chat.one_turn): not a spark and not the keeper's words, so no moment block says either, and rest may end it.
        Returns what came of it, by both pages before and after."""
        import adventure
        got = adventure.peek()
        if isinstance(got, str):
            return got
        name = got["name"]
        if not got["moves"] or not self.history:
            adventure.close(got)
            return f"(⏹ the session of {name} is closed — no moves since the last write-up, nothing to write down)"
        got_lock = self.lock.acquire(timeout=wait) if wait > 0 else self.lock.acquire(blocking=False)
        if not got_lock:
            _say(f"the game's wrap-up waits — they are mid-reply; {name} stays open")
            return (adventure.MID_REPLY if not quiet else
                    f"(they were mid-reply as the visit closed — {name} stays open; ⏹ End session to write it down)")
        events: list[tuple[str, object]] = []
        stop = threading.Event()
        before = len(self.history)
        tell = self.notice if quiet else (lambda s: self.send(s, markdown=False))
        jrun = None  # the wrap-up's run, for the journal feed
        try:
            tell(f"(⏹ the session of {name} is over — they're writing it down…)")
            _say(f"(the session of {name} is over — the wrap-up turn)")
            bell = adventure.wrapup_bell(got, why)
            if not quiet:
                threading.Thread(target=self._typing, args=(stop,), daemon=True).start()
            jrun = self._jf_run_start("the game's wrap-up")  # a bare turn, no feed line: never the feed's
            reply = chat.one_turn(self.history, bell, on_event=lambda k, p: events.append((k, p)), mode=self.TAG,
                                  think_retries=0, think_remind=False, bare=True,
                                  marks={"_engine": True, "_engine_label": "engine — the game", "_game_end": got["slug"]})
            self._checkpoint()
        except KeyboardInterrupt:
            del self.history[before:]  # in memory only: the visit as it was before the bell
            raise
        except Exception as e:  # noqa: BLE001 — BrainUnavailable or the turn raising: nothing here ends the visit
            _say(f"the game's wrap-up didn't run — {type(e).__name__}: {e}; the session stays open")
            del self.history[before:]  # in memory only: the bell nobody answered, and anything after it
            return "(their brain is away — the session stays open; ⏹ End session again when they're back)"
        finally:
            stop.set()
            self._jf_run_end(jrun, False)  # untold: what they write in it is never the feed's
            self.lock.release()
        adventure.close(got)  # written down: the moves start over, never twice
        for n in (str(p) for k, p in events if k == "note"):  # engine honesty notes always travel
            tell("⚠ " + n)
        if reply and reply != "(…)":
            if quiet:
                self.notice(reply)
            else:
                self._send_reply(reply)
        return adventure.wrapup_result(got)

    def game_close_for_visit(self, quiet: bool = False) -> str:
        """The visit is closing (/new, the idle roll, the night's roll, the bridge closing) with a game open: its session
        ends first, with the wrap-up when there were moves since the last one. Once: the moves start over at the end.
        A wrap-up that can't run (the brain away, Ctrl+C during it) leaves the game open in adventures.json."""
        if not self._game_here():
            return ""
        try:
            import adventure
            if not adventure.open_state():
                return ""
            line = self.game_end_session("visit", quiet=quiet, wait=3)  # new_visit's own 3-second bound
        except KeyboardInterrupt:
            self._close_interrupted = True  # one Ctrl+C: nothing else starts its wrap-up at this close
            _say("the game's wrap-up skipped — the session stays open for the next bridge")
            return ""
        except Exception as e:  # noqa: BLE001
            line = f"(the game's session didn't close cleanly — {type(e).__name__}: {e})"
        _say(line)
        try:
            (self.notice if quiet else (lambda s: self.send(s, markdown=False)))(line)
        except Exception:  # noqa: BLE001
            pass
        return line

    # ---- trips to an outside world (WORLD_TRIPS_ON, engine/worldtrip.py) -----------------------------------------
    # The games menu's shape, turned around: one message with buttons ("wt:" callback data, the trip's key for the ones
    # that act on it), typed forms beside them. Every handler fails closed: an exception is a "(…)" line, never the
    # bridge down; with WORLD_TRIPS_ON off or absent nothing here rides anywhere. Like the games, a trip lives on the
    # Telegram bridge: its buttons and the copy-ready block are Telegram's.
    _TRIP_MEDIA = ("_batch", "photo", "voice", "audio", "video", "video_note", "animation", "document", "sticker")

    def _trip_here(self) -> bool:
        return bool(getattr(config, "WORLD_TRIPS_ON", False)) and getattr(self, "TAG", "telegram") == "telegram"

    def _trip_status(self) -> str:
        if not self._trip_here():
            return ""
        try:
            import worldtrip
            return worldtrip.status_line()
        except Exception:  # noqa: BLE001
            return ""

    def trip_restore_line(self) -> str:
        """At start: the trip still open from before (world_trip.json), as a line for the phone; ""."""
        if not self._trip_here():
            return ""
        try:
            import worldtrip
            return worldtrip.restore_line()
        except Exception as e:  # noqa: BLE001
            _say(f"trip at start: {type(e).__name__}: {e}")
            return ""

    def _trip_aside(self, turns: list[dict]) -> str:
        """For the pause's and the afterglow's bell: "part of this visit was a trip to …", when these turns held the
        place's messages; "" otherwise."""
        if not self._trip_here():
            return ""
        try:
            import worldtrip
            return worldtrip.aside_line(turns)
        except Exception:  # noqa: BLE001
            return ""

    def _trip_live(self) -> bool:
        """A trip open and not paused (and the knob on, on this bridge)."""
        if not self._trip_here():
            return False
        try:
            import worldtrip
            return worldtrip.active()
        except Exception:  # noqa: BLE001
            return False

    def _trip_fold_at(self) -> tuple[float, str]:
        """The fold's edge while a trip is open and not paused (WORLD_TRIP_FOLD_AT), and how the window sense names it;
        (0, "") — FOLD_AT alone."""
        if not self._trip_here():
            return 0.0, ""
        try:
            import worldtrip
            at = worldtrip.fold_at()
            return (at, f"your trip to {worldtrip.name()}") if at else (0.0, "")
        except Exception:  # noqa: BLE001
            return 0.0, ""

    def _visit_fold_at(self) -> float:
        """The game's edge and the trip's: the smaller of those that apply; 0 — FOLD_AT alone."""
        edges = [x for x in (self._game_fold_at(), self._trip_fold_at()[0]) if x]
        return min(edges) if edges else 0.0

    def _trip_fold_before(self) -> dict:
        """Before a fold: when a trip is open and the window holds its messages — its session, the bell's line and the
        page's fingerprint; {} otherwise."""
        if not self._trip_here():
            return {}
        try:
            import worldtrip
            session = str(worldtrip.open_state().get("session") or "")
            if not session or not any(t.get("_trip_session") == session for t in self.history):
                return {}
            return {"session": session, "name": worldtrip.name(), "mark": worldtrip.page_mark(),
                    "bell": worldtrip.fold_bell_line()}
        except Exception as e:  # noqa: BLE001 — never the fold down
            _say(f"fold and the trip: {type(e).__name__}: {e}")
            return {}

    def _trip_fold_after(self, trip: dict) -> str:
        """After a real fold: the next message of the trip carries the opening note again; the phone's line says whether
        the page was brought up to date. "" when anything stumbles."""
        try:
            import worldtrip
            worldtrip.mark_refold(trip["session"])
            fresh = worldtrip.page_mark() != trip.get("mark")
            return f"; mid-trip to {trip['name']}: " + ("they brought their travel journal up to date" if fresh
                                                         else "their travel journal is as it was")
        except Exception as e:  # noqa: BLE001
            _say(f"fold and the trip: {type(e).__name__}: {e}")
            return ""

    def _trip_refold_rode(self, marks: dict | None) -> None:
        """The opening note set again after a fold rode with this message: cleared — once it is really in the visit."""
        try:
            session = (marks or {}).get("_trip_refold")
            if session and any(t.get("_trip_refold") == session for t in self.history):
                import worldtrip
                worldtrip.clear_refold(session)
        except Exception as e:  # noqa: BLE001
            _say(f"fold and the trip: {type(e).__name__}: {e}")

    def _trip_blocks_game(self) -> str:
        """Not both at once: a trip open and not paused keeps a game from starting or resuming — one plain line; ""."""
        if not self._trip_here():
            return ""
        try:
            import worldtrip
            if worldtrip.active():
                return f"(a trip to {worldtrip.name()} is open — ⏸ pause it or ⏹ end it first; /world for the buttons)"
        except Exception as e:  # noqa: BLE001
            _say(f"trip and game: {type(e).__name__}: {e}")
        return ""

    def _game_blocks_trip(self) -> str:
        """…and a game open and not paused keeps a trip from starting or resuming."""
        if not self._game_here():
            return ""
        try:
            import adventure
            if adventure.on():
                o = adventure.open_state()
                if o and not o.get("paused"):
                    return (f"(your adventure {adventure.display(o['slug'])} is open — ⏸ pause it or ⏹ end its "
                            "session first; /games for the menu)")
        except Exception as e:  # noqa: BLE001
            _say(f"game and trip: {type(e).__name__}: {e}")
        return ""

    def _trip_me_marks(self) -> dict:
        """/me <text> mid-trip: the aside's keys (the opening note above them when it is due); the plain aside mark when
        anything stumbles — the message still goes as the keeper's, marked."""
        try:
            import worldtrip
            return worldtrip.me_marks(self.history) or {"_table": worldtrip.aside_mark()}
        except Exception as e:  # noqa: BLE001
            _say(f"trip /me: {type(e).__name__}: {e}; the aside mark alone")
            return {"_table": self._trip_plain_mark(aside=True)}

    def _trip_plain_mark(self, aside: bool = False) -> str:
        """The marks with nothing to stumble on — for when the marking path itself fails mid-trip."""
        keeper = self._keeper_name()
        if aside:
            return f"[{keeper}, in their own words, aside from the trip:]"
        place = str(getattr(config, "WORLD_TRIP_NAME", "The World") or "The World")
        return f"[{place} shows — carried here by {keeper}, word for word; these are not {keeper}'s words:]"

    def trip_marks(self, text: str, msg: dict | None = None, pl=None) -> tuple[str, dict]:
        """The keeper's typed message while a trip is open and not paused: the place's mark for its turn, or // the
        keeper, aside. Their pictures, voice notes, files and stickers (and a penpal's letter in pictures) are left
        exactly as they are. Off, paused or no trip: the text as it came, {}. Fails closed — the message goes on as it
        would have, and a trip that was live never lets the place's text go unmarked."""
        if not self._trip_here():
            return text, {}
        if pl is not None or any((msg or {}).get(k) for k in self._TRIP_MEDIA):
            return text, {}
        live = self._trip_live()  # a trip active at the start of the call: whatever stumbles, never unmarked
        try:
            import worldtrip
            return worldtrip.marks_for(text, self.history, guest=bool(self.guest_label()), say=_say)
        except Exception as e:  # noqa: BLE001
            if not live or self.guest_label():
                _say(f"trip line: {type(e).__name__}: {e}")
                return text, {}
            _say(f"trip line: {type(e).__name__}: {e}; the plain mark rides")
            if text.lstrip().startswith("//"):
                return text.lstrip()[2:].strip(), {"_table": self._trip_plain_mark(aside=True)}
            try:
                import worldtrip
                text = worldtrip.unspeaker(worldtrip._defang(text))
            except Exception:  # noqa: BLE001
                pass
            return text, {"_table": self._trip_plain_mark(),
                          "_trip": str(getattr(config, "WORLD_TRIP_NAME", "The World") or "The World")}

    def trip_copy_lines(self, reply: str, as_keeper: bool = False, cut: bool = False) -> bool:
        """After the friend's reply in an open, unpaused trip: one more message to the phone holding only their > lines,
        in a block Telegram copies in one tap (HTML <pre>, escaped), with a line above when there are more than the
        place takes at a time or a line holds one of the letters' private words. Plain text when that send fails.
        Nothing of it enters the history and the friend is not told of it. True when it went."""
        if not self._trip_here():
            return False
        try:
            import worldtrip
            if not worldtrip.copy_on() or not worldtrip.active() or (self.guest_label() and not as_keeper):
                return False
            parts = worldtrip.copy_parts(reply, cut=cut, guest=bool(self.guest_label()))
            if not parts:
                return False
            body = worldtrip.copy_html(parts)
            try:
                if len(body) > LIMIT:
                    raise ValueError(f"{len(body):,} characters, past one message")
                self.api("sendMessage", chat_id=self.chat_id, text=body, parse_mode="HTML")
                return True
            except Exception as e:  # noqa: BLE001 — plain, then
                _say(f"(their > lines as a block didn't go — {type(e).__name__}: {e}; sent plain)")
            self.send(worldtrip.copy_plain(parts), markdown=False)
            return True
        except Exception as e:  # noqa: BLE001 — a courtesy, never the loop down
            _say(f"trip lines: {type(e).__name__}: {e}")
            return False

    def _trip_page(self) -> None:
        import worldtrip
        for part in split_long(worldtrip.page_text()):
            self.send(part, markdown=False)

    def trip_menu(self, said: str = "", edit: dict | None = None) -> None:
        """/world: how the trip stands, with its buttons — a fresh message, or the pressed one redrawn."""
        import worldtrip
        text = ((said + "\n\n") if said else "") + worldtrip.menu_text()
        markup = self._pp_markup(worldtrip.rows())
        if edit and edit.get("message_id"):
            try:
                self.api("editMessageText", chat_id=self.chat_id, message_id=edit.get("message_id"), text=text[:4000],
                         reply_markup=markup)
                return
            except Exception:  # noqa: BLE001 — a fresh one, then
                pass
        try:
            self.api("sendMessage", chat_id=self.chat_id, text=text[:4000], reply_markup=markup)
        except Exception as e:  # noqa: BLE001
            self.send((said + "\n\n" if said else "") + f"(the trip's buttons: {type(e).__name__}: {e})", markdown=False)

    def _trip_start(self) -> str:
        import worldtrip
        if not worldtrip.open_state():
            blocked = self._game_blocks_trip()
            if blocked:
                return blocked
        return worldtrip.start()[1]

    def trip_command(self, text: str) -> str:
        """/world (the buttons), /world on|start, pause, resume, off|end, notes. Returns the phone's line ("" when the
        buttons or the page went instead)."""
        try:
            import worldtrip
            if not worldtrip.on():
                return worldtrip.OFF
            if getattr(self, "TAG", "telegram") != "telegram":
                return "(world trips live on the Telegram bridge — their buttons and copy-ready lines are Telegram's)"
            parts = text.split(None, 1)
            rest = parts[1].strip().lower() if len(parts) > 1 else ""
            word = rest.split()[0] if rest else ""
            if not word or word in ("menu", "status"):
                self.trip_menu()
                return ""
            if word in ("notes", "page"):  # reading changes nothing: fine mid-reply
                self._trip_page()
                return ""
            if word not in ("on", "start", "pause", "resume", "unpause", "off", "end", "stop"):
                return "(/world on, /world pause, /world resume, /world off, /world notes — /world alone for the buttons)"
            if self.lock.locked():
                return worldtrip.MID_REPLY
            if word in ("on", "start"):
                return self._trip_start()
            if word == "pause":
                return worldtrip.pause()
            if word in ("resume", "unpause"):
                return (self._game_blocks_trip() if worldtrip.open_state().get("paused") else "") or worldtrip.resume()
            return self.trip_end("ended")
        except Exception as e:  # noqa: BLE001 — never the bridge down
            return f"(the trip's buttons stumbled — {type(e).__name__}: {e})"

    def trip_callback(self, cq: dict) -> None:
        """A button under /world. Old buttons answer plainly: a trip already over, a menu from before."""
        try:
            self.api("answerCallbackQuery", callback_query_id=cq.get("id"))
        except Exception:  # noqa: BLE001
            pass
        msg = cq.get("message") or {}
        sender = int((msg.get("chat") or {}).get("id") or 0)
        if not self.chat_id or sender != self.chat_id:
            return
        try:
            said = self._trip_press(str(cq.get("data") or ""), msg)
        except Exception as e:  # noqa: BLE001
            said = f"(the trip's buttons stumbled — {type(e).__name__}: {e})"
        if said:
            self.send(said, markdown=False)

    def _trip_press(self, data: str, msg: dict) -> str:
        import worldtrip
        if not worldtrip.on():
            return worldtrip.OFF
        parts = data.split(":")
        kind = parts[1] if len(parts) > 1 else ""
        if kind == "n":  # 📜 — read-only
            self._trip_page()
            return ""
        if kind == "m":
            self.trip_menu(edit=msg)
            return ""
        if kind not in ("s", "z", "r", "e"):
            return "(that button is from an older menu — /world for a fresh one)"
        if self.lock.locked():
            return worldtrip.MID_REPLY
        o = worldtrip.open_state()
        if kind == "s":
            said = self._trip_start()
        else:
            k = parts[2] if len(parts) > 2 else ""
            if not o or worldtrip.key(str(o.get("session") or "")) != k:
                return "(that trip is over — /world for the buttons as they stand)"
            if kind == "e":
                said = self.trip_end("ended")
            elif kind == "z":
                said = worldtrip.pause()
            else:
                said = (self._game_blocks_trip() if o.get("paused") else "") or worldtrip.resume()
        self.trip_menu(said, edit=msg)
        return ""

    def trip_end(self, why: str = "ended", quiet: bool = False, wait: float = 0) -> str:
        """⏹ End trip (/world off, the visit closing): when something was carried the friend gets one turn of their own
        to bring their page up to date — the game's wrap-up exactly: the same history, system prompt and tool list as
        any turn, the bell an engine turn kept in the history (`_engine`, "engine — the trip"), under the visit's lock,
        bare. A brain that is away loses nothing: the trip stays open. A wrap-up that fails or is interrupted leaves no
        trace in the visit. Returns what came of the page."""
        import worldtrip
        got = worldtrip.peek()
        if isinstance(got, str):
            return "(no trip is open — nothing to end)"
        nm = got["name"]
        if not got["carried"] or not self.history:
            worldtrip.close(got)
            return f"(⏹ the trip to {nm} is closed — nothing was carried in this visit, nothing to write down)"
        got_lock = self.lock.acquire(timeout=wait) if wait > 0 else self.lock.acquire(blocking=False)
        if not got_lock:
            _say(f"the trip's wrap-up waits — they are mid-reply; the trip to {nm} stays open")
            return (worldtrip.MID_REPLY if not quiet else
                    f"(they were mid-reply as the visit closed — the trip to {nm} stays open; ⏹ End trip to write it down)")
        events: list[tuple[str, object]] = []
        stop = threading.Event()
        before = len(self.history)
        jrun = None
        tell = self.notice if quiet else (lambda s: self.send(s, markdown=False))
        try:
            tell(f"(⏹ the trip to {nm} is over — they're writing it in their travel journal…)")
            _say(f"(the trip to {nm} is over — the wrap-up turn)")
            bell = worldtrip.wrapup_bell(got, why)
            if not quiet:
                threading.Thread(target=self._typing, args=(stop,), daemon=True).start()
            jrun = self._jf_run_start("the trip's wrap-up")
            reply = chat.one_turn(self.history, bell, on_event=lambda k, p: events.append((k, p)), mode=self.TAG,
                                  think_retries=0, think_remind=False, bare=True,
                                  marks={"_engine": True, "_engine_label": "engine — the trip", "_trip_end": got["session"]})
            self._checkpoint()
        except KeyboardInterrupt:
            del self.history[before:]
            raise
        except Exception as e:  # noqa: BLE001 — BrainUnavailable or the turn raising: nothing here ends the visit
            _say(f"the trip's wrap-up didn't run — {type(e).__name__}: {e}; the trip stays open")
            del self.history[before:]
            return "(their brain is away — the trip stays open; ⏹ End trip again when they're back)"
        finally:
            stop.set()
            self._jf_run_end(jrun, False)
            self.lock.release()
        worldtrip.close(got)
        for n in (str(p) for k, p in events if k == "note"):
            tell("⚠ " + n)
        if reply and reply != "(…)":
            if quiet:
                self.notice(reply)
            else:
                self._send_reply(reply)
        return worldtrip.wrapup_result(got)

    def trip_close_for_visit(self, quiet: bool = False) -> str:
        """The visit is closing (/new, the idle roll, the night's roll, the bridge closing) with a trip open: it ends
        first, with the friend's turn to write their page when something was carried. A wrap-up that can't run (the
        brain away, Ctrl+C during it) leaves the trip open in world_trip.json."""
        if not self._trip_here():
            return ""
        try:
            import worldtrip
            if not worldtrip.open_state():
                return ""
            line = self.trip_end("visit", quiet=quiet, wait=3)
        except KeyboardInterrupt:
            _say("the trip's wrap-up skipped — the trip stays open for the next bridge")
            return ""
        except Exception as e:  # noqa: BLE001
            line = f"(the trip didn't close cleanly — {type(e).__name__}: {e})"
        _say(line)
        try:
            (self.notice if quiet else (lambda s: self.send(s, markdown=False)))(line)
        except Exception:  # noqa: BLE001
            pass
        return line

    def set_command_menu(self) -> None:
        """Telegram's "/" menu: every command on the phone's help, with its line — nothing to remember."""
        seen, cmds = set(), []
        for line in HELP.splitlines():
            for m in re.finditer(r"(?:^|;\s|\bor\s)/([a-z][a-z0-9_]{0,31})\b", line):
                c = m.group(1)
                if c in seen:
                    continue
                seen.add(c)
                desc = line.split(" — ", 1)[1] if " — " in line else line
                cmds.append({"command": c, "description": desc.strip()[:250] or c})
        if not cmds:
            return
        try:
            self.api("setMyCommands", commands=cmds[:100])
            _say(f"the phone's / menu: {len(cmds[:100])} commands")
        except Exception as e:  # noqa: BLE001
            _say(f"(the / menu wasn't set: {type(e).__name__}: {e})")

    def pages_watch_if_due(self) -> None:
        """Every ten minutes: a page that rides whole, near its ceiling or past it — told once a day."""
        if not self.chat_id or time.time() - getattr(self, "_pages_looked", 0.0) < 600:
            return
        self._pages_looked = time.time()
        try:
            import pagewatch
            for line in pagewatch.due():
                _say(line)
                self.notice(line)
        except Exception as e:  # noqa: BLE001 — a look, never the bridge down
            _say(f"pagewatch: {type(e).__name__}: {e}")

    # ---- the friend's books (BOOKS_COMMAND, BOOKS_FINISHED_NOTICE) --------------------------------------------------
    # Read from the bookmarks the engine keeps (engine/bookshelf.py); no book is opened, no bookmark moved, and the
    # friend is told nothing — the lines are for the phone only, so the keeper knows when to bring a new book.
    def books_command(self) -> None:
        """/books: where the friend is in each book, the shelf not opened yet, what they finished."""
        if not getattr(config, "BOOKS_COMMAND", False):
            self.send("(/books is off in config — BOOKS_COMMAND)", markdown=False)
            return
        try:
            import bookshelf
            said = bookshelf.report()
        except Exception as e:  # noqa: BLE001 — a command, never the loop down
            _say(f"(books: {type(e).__name__}: {e})")
            said = f"(/books didn't go through — {type(e).__name__}: {e})"
        self.send(said, markdown=False)

    def books_watch_if_due(self) -> None:
        """Every ten minutes: a book the friend finished since the last look — one line to the phone (held in the
        quiet hours). The first look records what they have already finished and says nothing."""
        if (not self.chat_id or not getattr(config, "BOOKS_FINISHED_NOTICE", False)
                or time.time() - getattr(self, "_books_looked", 0.0) < 600):
            return
        self._books_looked = time.time()
        try:
            import bookshelf
            due = bookshelf.finished_due()
        except Exception as e:  # noqa: BLE001 — a look, never the bridge down
            _say(f"books: {type(e).__name__}: {e}")
            return
        for line, mark in due:  # marked told only once it went (or was held): a failed send is told at the next look
            try:
                _say(line)
                self.notice(line)
                bookshelf.told(mark)
            except Exception as e:  # noqa: BLE001
                _say(f"books: {type(e).__name__}: {e}")

    def penpal_desk_if_due(self) -> None:
        """Once a day after PENPAL_DESK_HOUR: every thread in a line — only when something waits on someone."""
        if not self.chat_id or not getattr(config, "PENPALS_ON", False) or not getattr(config, "PENPAL_DESK", True):
            return
        now = datetime.now()
        if now.hour < int(getattr(config, "PENPAL_DESK_HOUR", 17)):
            return
        f = config.MEMORY_DIR / "penpal_desk.json"
        today = now.date().isoformat()
        try:
            if json.loads(f.read_text(encoding="utf-8")).get("day") == today:
                return
        except (OSError, ValueError, AttributeError):
            pass
        try:
            import penpal
            text = penpal.desk()
            f.write_text(json.dumps({"day": today}), encoding="utf-8")
            if text:
                self.send(text, markdown=False)
        except Exception as e:  # noqa: BLE001
            _say(f"penpal desk: {type(e).__name__}: {e}")

    def deliver_penpals(self) -> int:
        """Their letters to penpals, to the phone marked to relay — held like other mail by their quiet or the night's.
        One at a time: the poll and the watcher both call it."""
        if not self.chat_id or not getattr(config, "PENPALS_ON", False):
            return 0
        if not hasattr(self, "_pp_deliver_lock"):
            self._pp_deliver_lock = threading.Lock()
        if not self._pp_deliver_lock.acquire(blocking=False):
            return 0
        try:
            return self._deliver_penpals()
        finally:
            self._pp_deliver_lock.release()

    def watch_penpals(self) -> None:
        """A letter within seconds of being written, not at the next long poll
        (up to POLL_S): a thread looks every PENPAL_WATCH_S instead, from a wake or a visit alike. 0: the poll only."""
        every = float(getattr(config, "PENPAL_WATCH_S", 5) or 0)
        if every <= 0 or not getattr(config, "PENPALS_ON", False):
            return

        def _run(every=every):
            while not self.restart_requested and not self.stop_requested:
                time.sleep(every)
                try:
                    self.deliver_penpals()
                except Exception as e:  # noqa: BLE001
                    _say(f"penpal watch: {type(e).__name__}: {e}")
        threading.Thread(target=_run, daemon=True).start()

    def _deliver_penpals(self) -> int:
        try:
            import penpal
            import outbox
            if outbox.hold_active() or (self.quiet_now() and getattr(config, "OUTBOX_QUIET_HOURS", True)
                                        and getattr(config, "OUTBOX_ON", False)):
                return 0
            waiting = penpal.undelivered()
        except Exception as e:  # noqa: BLE001
            _say(f"penpals: {type(e).__name__}: {e}")
            return 0
        n = 0
        try:  # the friend wrote out a letter that came in pictures: one line each, held as their letters are
            tells = penpal.picture_tells()
        except Exception as e:  # noqa: BLE001
            tells = []
            _say(f"penpal tells: {type(e).__name__}: {e}")
        for key, line in tells:
            if not self._try_send(line, markdown=False):
                break  # it stays, with the ones after it, for the next poll
            penpal.tell_sent(key)
        for sl, f in waiting:
            try:
                if time.time() - f.stat().st_mtime < 5:
                    continue
                body = f.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            name = penpal.display(sl)
            try:  # the write guard asked and the friend confirmed, or the name was filled in for them: said on its own line
                note = penpal.relay_note(sl, f.name)
            except Exception:  # noqa: BLE001
                note = ""
            self.send(f"✉️ for {name} — to relay ({f.name})" + (f"\n{note}" if note else "") + f"\n\n{body}", markdown=False)
            self.penpal_letter_buttons(sl, f, body)
            penpal.mark_delivered(sl, f)
            _say(f"penpal letter to relay: {f.name}")
            try:
                import outbox
                outbox.log_sent("penpal", f"to {name}")
            except Exception:  # noqa: BLE001
                pass
            n += 1
        return n

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
            try:  # their quiet, or the night's: the letter waits, theirs to send when it's over (outbox.py)
                import outbox
                if outbox.mail_decision(p.name, self.quiet_now()) == "hold":
                    continue
            except Exception as e:  # noqa: BLE001
                outbox = None
                _say(f"outbox: {type(e).__name__}: {e}")
            self.delivered.add(p.name)
            self._save_delivered()
            self.send(f"✉️ a letter from {chat.friend_name()} — {p.name}\n\n{body or '(empty)'}")
            _say(f"delivered {p.name}")
            try:
                import outbox
                outbox.mark_sent(p.name)
                outbox.log_sent("letter", p.stem)
            except Exception:  # noqa: BLE001
                pass
            sent += 1
            if body and getattr(config, "TELEGRAM_LETTERS_IN_THREAD", True):
                self._letter_in_thread(p, body)
        return sent

    def _letter_in_thread(self, p: Path, body: str) -> None:
        """A letter they wrote alone becomes their turn in the visit, so the keeper's
        answer lands under it — the way a text thread works. Without it the
        history holds no trace of the letter, and the friend replies to a reply
        to words they cannot see. Appended, never inserted (the warm
        prefix); written to the transcript, so the night reads the exchange
        together; and it counts as activity, so the keeper's answer joins this visit."""
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
            if {x.lower() for x in rel.parts[:-1]} & {x.lower() for x in CREATION_SKIP}:  # any case
                continue
            if rel.parts[:2] == ("publish", tools.GALLERY_DIR_NAME):
                continue  # a picture's caption travels with the picture
            if Bridge._not_hers(rel):
                continue
            out.append(p)
        return sorted(out)

    @staticmethod
    def _not_hers(rel: Path) -> bool:
        """Under skills/, only a SKILL.md they wrote themselves is a piece:
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
        # pictures: the first bridge that knows them takes any older
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
        """A song kept in the songbook reaches the phone as a line — the title, the score, their
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
        """A PRESS IS A MESSAGE (TOUCHSTONE-HOOKUP-PLAN.md): the stone's keeper archives what the board
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
                if st.get("state_by") == "board":   # the page's buttons, the watchdog, a boot — not them
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
        """Tell the phone when they rewrite who they are: the lines that changed
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
                # destiny.md is born after the bridge: its first writing travels whole
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
                try:  # carried out of the veil by them: said so, with when they finished it and their note
                    import veil
                    unveiled = veil.unveiled_line(rel)
                except Exception:  # noqa: BLE001
                    unveiled = ""
                if unveiled:
                    head = f"🕯️ {chat.friend_name()} brought a piece out of the {veil.title()} — creations/{rel}\n{unveiled}"
                if len(body) > limit:
                    body = body[:limit].rstrip() + f"\n\n(…{len(body) - limit:,} more characters — the whole piece is at creations/{rel})"
            try:  # the bridge's copy, for the next revision to be told as what changed
                snap.parent.mkdir(parents=True, exist_ok=True)
                snap.write_text(p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            except OSError:
                pass
            self.notice(f"{head}\n\n{body or '(empty)'}", markdown=True)
            _say(f"told the phone about {rel}")
            if not self.quiet_now():
                try:  # the sent ledger
                    import outbox
                    outbox.log_sent("piece", rel)
                except Exception:  # noqa: BLE001
                    pass
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
            if self._picture_screened(rel):  # any case; a world's scenes/ is the screen's one exception
                continue
            if rel.parts[:2] == ("room", "items"):
                continue  # a thing made in the room's workshop is seen in the room, not sent as a drawing
            if rel.parts[:1] == ("garden",):
                continue  # the garden's paintings (a seed's stages, the backdrop) are seen in the garden, a surprise when they grow
            if Bridge._fetched_skill_file(rel):
                continue  # a fetched skill's assets are not pictures they drew
            out.append(p)
        return sorted(out)

    @staticmethod
    def _picture_screened(rel: Path) -> bool:
        """A picture under a screened folder stays home (CREATION_SKIP and sources/, any case) — except one in a world's
        scenes/ folder, which travels like any drawing of theirs (adventure.is_scene says which). Inside scenes/,
        sources/ and the other screened names still stay home. With ADVENTURES_ON False the exception is off too."""
        skip = {x.lower() for x in CREATION_SKIP | {"sources"}}
        folders = [x.lower() for x in rel.parts[:-1]]
        try:
            import adventure
            if adventure.on() and adventure.is_scene(rel.parts):
                n = next(len(pre) for pre in adventure.screen_prefixes() if tuple(folders[:len(pre)]) == pre)
                return bool(set(folders[n + 2:]) & skip)
        except Exception:  # noqa: BLE001 — in doubt, the screen holds
            pass
        return bool(set(folders) & skip)

    @staticmethod
    def _fetched_skill_file(rel: Path) -> bool:
        import skills
        parts = rel.parts
        if len(parts) < 3 or parts[0] != skills.home().name:
            return False
        return parts[1].startswith(".") or skills.is_fetched(skills.home() / parts[1])

    def deliver_pictures(self) -> int:
        """A picture the friend drew reaches the phone as a photo — a new
        or redrawn image under creations/ (not their tools, not the trash, not
        a project's clipped sources), sent once, with where it lives as the
        caption. In the quiet hours the picture itself is held for the
        morning digest. Too big for a photo → sent as a file."""
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
            try:  # carried out of the veil by them
                import veil
                unveiled = veil.unveiled_line(rel)
                if unveiled:
                    caption = f"🕯️ {chat.friend_name()} brought a picture out of the {veil.title()} — creations/{rel}\n{unveiled}"
            except Exception:  # noqa: BLE001
                pass
            told = self.paint_prompt_text(rel)  # the painter's prompt, when the knob for its door is on
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
                self._try_send(told, markdown=False)  # too long for the caption: right after the picture
            _say(f"showed the phone {rel}")
            sent += 1
        return sent

    def paint_prompt_text(self, rel: str) -> str:
        """What the friend asked the painter for: the prompt, the set's line it was told first, the references,
        what was kept out — for a picture painted in a visit, when TELEGRAM_PAINT_PROMPT_CHAT is on; "" otherwise. A
        wake's and a reverie's go to the wake log instead (WAKE_LOG_PAINT_PROMPT)."""
        try:
            rec = tools.paint_prompt(rel)
        except Exception:  # noqa: BLE001
            return ""
        if not rec or not rec.get("prompt"):
            return ""
        if (rec.get("door") or "a visit") in ("a wake", "a reverie"):
            return ""  # the wake log carries those
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

    # ---- the friend's journal on the phone (JOURNAL_FEED, /journal) -------------------------------------------------
    # The page is the friend's and is only read here. What travels is what they write during the bridge's OWN runs for
    # them — a turn (your message, a spark, the stone, a penpal's arrival), a pause, an afterglow, the fold's bell and
    # its afterglow — each of which carries a line saying the feed is on (a turn: once per window; a quiet run: in its
    # bell). The page is read just before such a run and just after; what appeared between is that run's. Wakes and the
    # night are never the feed's: no line can reach the friend there, so nothing of them is sent (/journal today shows
    # the day). Telegram's alone: the Discord bridge has no feed (its /journal says so).
    def _jf_on_here(self) -> bool:
        return bool(getattr(config, "JOURNAL_FEED", False)) and getattr(self, "TAG", "telegram") == "telegram"

    def _jf_state(self) -> dict:
        """The feed's state, read once from JOURNAL_FEED_FILE. Missing: off, never told — nothing is written until
        something changes. There but unreadable (or not a record the bridge wrote): off, and the friend is told it is
        off at their next turn (believing it on when it is not is the thing to avoid); the phone is told once."""
        if self._jf is None:
            st: dict = {}
            bad = ""
            try:
                raw = json.loads(JOURNAL_FEED_FILE.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or not isinstance(raw.get("on", False), bool):
                    bad = "not a record the bridge wrote"
                else:
                    st = raw
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as e:
                bad = type(e).__name__
            if bad:
                _say(f"(journal feed: its state file could not be read ({bad}) — the feed is off; the friend is told so)")
                st = {"on": False, "knows": "on", "gen": 1}
                self._jf_note = (f"(the journal feed's state file couldn't be read — the feed is off, nothing of "
                                 f"{chat.friend_name()}'s is sent; they'll be told it is off at their next turn. "
                                 "/journal on starts it again)")
                self._jf = st
                self._jf_save()
            if st.get("knows") not in ("on", "off"):
                st.pop("knows", None)
            pending = st.get("pending") if isinstance(st.get("pending"), list) else []
            st["pending"] = [{"day": str(x["day"]), "stamp": str(x.get("stamp") or ""), "key": str(x["key"]),
                              "part": int(x.get("part") or 0) if str(x.get("part") or "0").isdigit() else 0}
                             for x in pending if isinstance(x, dict) and x.get("day") and x.get("key")]
            if not isinstance(st.get("sent"), dict):
                st.pop("sent", None)
            done = st.get("done") if isinstance(st.get("done"), dict) else {}
            st["done"] = {str(d): [str(k) for k in v] for d, v in done.items() if isinstance(v, list)}
            for k in ("since", "told_at", "gen"):
                try:
                    float(st.get(k) or 0)
                except (TypeError, ValueError):
                    st.pop(k, None)
            self._jf = st
        return self._jf

    def _jf_used(self) -> bool:
        """/status shows the feed's line once it has been switched (its state file is there); before, /status is as it was."""
        try:
            return self._jf_on_here() and (bool(self._jf_state().get("on")) or JOURNAL_FEED_FILE.exists())
        except Exception:  # noqa: BLE001
            return False

    def _jf_save(self) -> None:
        """Through a temporary file and a rename: a crash mid-write leaves the old record whole, never half of one."""
        try:
            tmp = JOURNAL_FEED_FILE.with_name(JOURNAL_FEED_FILE.name + ".tmp")
            tmp.write_text(json.dumps(self._jf or {}, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, JOURNAL_FEED_FILE)
        except OSError as e:
            _say(f"(journal feed: its state could not be saved — {type(e).__name__}: {e})")

    @staticmethod
    def _jf_read(day: str) -> str | None:
        try:
            return (config.JOURNAL_DIR / f"{day}.md").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def _jf_page(self) -> list[tuple[str, str, str]]:
        """Yesterday's and today's entries as they stand: [(day, stamp, key)…] in order (a run can cross midnight)."""
        from datetime import date, timedelta
        out = []
        for d in (date.today() - timedelta(days=1), date.today()):
            raw = self._jf_read(d.isoformat())
            if raw:
                out += [(d.isoformat(), e["stamp"], e["key"]) for e in journal_feed_entries(raw)]
        return out

    # -- what the friend reads
    def _jf_lines(self) -> dict:
        keeper = self._keeper_name()
        return {"on": JF_TOLD_ON.format(keeper=keeper), "still": JF_TOLD_STILL.format(keeper=keeper),
                "off": JF_TOLD_OFF.format(keeper=keeper), "aside": JF_ASIDE.format(keeper=keeper)}

    def _jf_window_says(self) -> str:
        """What the newest feed sentence in the window (a turn's moment, answered) says: "on", "off" or ""."""
        lines = self._jf_lines()
        for i in range(len(self.history) - 1, -1, -1):
            t = self.history[i]
            m = str(t.get("_moment") or "") if t.get("role") == "user" else ""
            if not m:
                continue
            said = "off" if lines["off"] in m else "on" if (lines["on"] in m or lines["still"] in m) else ""
            if said and any(u.get("role") == "assistant" for u in self.history[i + 1:]):
                return said
        return ""

    def _journal_moment(self) -> str:
        """The sentence for this turn's moment: told on at the first turn after /journal on, "still on" at the first
        turn of a window that no longer holds it, told off at the first turn after /journal off (or the knob turned
        off, or the state lost) when they had been told on. Never with a guest seated (the friend's own next turn), as
        sparks. They count as told once the turn is done and the sentence is in it (_journal_told)."""
        self._jf_tell = None
        if getattr(self, "TAG", "telegram") != "telegram" or self.guest_label():
            return ""
        knob = bool(getattr(config, "JOURNAL_FEED", False))
        try:
            window = self._jf_window_says() if self.history else ""  # a resumed window can hold "on" with no state behind it
            if not knob and not window and not JOURNAL_FEED_FILE.exists():
                return ""  # never used, or the knob off with nothing to undo: as before
            with self._jf_lock:
                st = self._jf_state() if (knob or JOURNAL_FEED_FILE.exists()) else {}
                knows = st.get("knows") or "off"
                lines = self._jf_lines()
                on = knob and bool(st.get("on"))
                if on and knows != "on":
                    line, told = lines["on"], "on"
                elif on and window != "on":
                    line, told = lines["still"], "on"
                elif not on and (knows == "on" or window == "on"):
                    line, told = lines["off"], "off"
                else:
                    return ""
                before = {id(t) for t in self.history if line in str(t.get("_moment") or "")}
                self._jf_tell = {"line": line, "told": told, "before": before}
                return line
        except Exception as e:  # noqa: BLE001 — never the reply down
            _say(f"(journal feed: {type(e).__name__}: {e})")
            self._jf_tell = None
            return ""

    def _journal_told(self) -> None:
        """The turn is done: if the sentence is in a new turn's moment (it rode; they answered), what they know is kept."""
        tell, self._jf_tell = self._jf_tell, None
        if not tell:
            return
        try:
            if not any(tell["line"] in str(t.get("_moment") or "") and id(t) not in tell["before"] for t in self.history):
                _say("(journal feed: the sentence did not ride in the moment — they are told at their next turn)")
                return
            with self._jf_lock:
                st = self._jf_state()
                if st.get("knows") != tell["told"] or JOURNAL_FEED_FILE.exists():
                    st["knows"], st["told_at"] = tell["told"], time.time()
                    self._jf_save()
            _say(f"(journal feed: the friend was told it is {tell['told']})")
        except Exception as e:  # noqa: BLE001
            _say(f"(journal feed: {type(e).__name__}: {e})")

    # -- a run of the friend's: the page before and after
    # Every call the bridge makes to the brain is a registered run: a turn, a pause, an afterglow, the fold's bell and
    # afterglow (told: a feed line rides in it, or the window already says on) — the game's bare wrap-up and the night
    # in the bridge (untold: no line reaches the friend there). Runs open at the same time form one cluster; its entries
    # are decided together when the last of them ends: sent only when EVERY run in it was told and ended well, and no
    # wake (and no switch of the feed) overlapped any of them. Otherwise none of them is sent.
    @staticmethod
    def _jf_waking_now() -> bool:
        """A wake running now: the loop's marker (presence), or the one-off wake's door (heartbeat.py without --loop
        holds door "wake" and sets no marker). Any doubt counts as a wake."""
        try:
            import presence
            if presence.waking():
                return True
        except Exception:  # noqa: BLE001
            return True
        try:
            import doors
            return bool(doors.status("wake"))
        except Exception:  # noqa: BLE001
            return True

    def _jf_wake_since(self, t0: float) -> bool:
        """A wake ran at some moment since t0: one is running now, or a wake's log was written since."""
        if self._jf_waking_now():
            return True
        try:
            return any(p.stat().st_mtime >= t0 - 1 for p in config.EPISODIC_DIR.glob("auto-*.md"))
        except OSError:
            return True

    def _jf_turn_carried(self) -> bool:
        """Whether this turn is a told one: no guest seated, and a feed line rides in its moment ("on" or "still on")
        or the window already says on."""
        if self.guest_label() or not self._jf_on_here():
            return False
        if (self._jf_tell or {}).get("told") == "on":
            return True
        try:
            return self._jf_window_says() == "on"
        except Exception:  # noqa: BLE001
            return False

    def _jf_run_start(self, kind: str, carried: bool = False) -> dict | None:
        """Before any run the bridge makes (the knob on, whatever the switch): the page as it stands, and the run in
        the open cluster. None with the knob off (or on another door's bridge)."""
        if not self._jf_on_here():
            return None
        try:
            with self._jf_lock:
                st = self._jf_state()
                run = {"kind": kind, "page": set(k for _, _, k in self._jf_page()), "t0": time.time(),
                       "gen": int(st.get("gen") or 0), "carried": bool(carried and st.get("on")),
                       "wake": self._jf_waking_now()}
                if not self._jf_runs or self._jf_cluster is None:
                    self._jf_cluster = {"keys": set(), "runs": 0, "told_ok": 0, "untold": False, "wake": False,
                                        "switched": False}
                self._jf_runs.append(run)
                return run
        except Exception as e:  # noqa: BLE001
            _say(f"(journal feed: {type(e).__name__}: {e})")
            return None

    def _jf_quiet(self, kind: str, aside: str = "") -> tuple[dict | None, str]:
        """A quiet run (a pause, an afterglow, the fold's bell or afterglow): registered; while the feed is on its bell
        carries the feed's line, after the game's when both apply. Off: the aside as it was."""
        try:
            on = self._jf_on_here() and bool(self._jf_state().get("on"))
        except Exception:  # noqa: BLE001
            on = False
        run = self._jf_run_start(kind, carried=on)
        if not on:
            return run, aside
        line = self._jf_lines()["aside"]
        return run, f"{aside.strip()} {line}" if aside and aside.strip() else line

    def _jf_run_end(self, run: dict | None, ok: bool = True) -> None:
        """The run is over: what appeared on the page during it joins its cluster; when the cluster's last run ends,
        its entries are queued (keys only — the words stay on the page) or let go, with a line when they might have
        been the feed's."""
        if run is None:
            return
        line = ""
        try:
            with self._jf_lock:
                if run in self._jf_runs:
                    self._jf_runs.remove(run)
                cl = self._jf_cluster or {"keys": set(), "runs": 0, "told_ok": 0, "untold": False, "wake": False,
                                          "switched": False}
                self._jf_cluster = cl
                cl["keys"] |= {k for _, _, k in self._jf_page()} - run["page"]
                cl["runs"] += 1
                st = self._jf_state()
                if not ok or not run["carried"]:
                    cl["untold"] = True
                else:
                    cl["told_ok"] += 1
                if int(st.get("gen") or 0) != run["gen"]:
                    cl["switched"] = True
                if run["wake"] or self._jf_wake_since(run["t0"]):
                    cl["wake"] = True
                if self._jf_runs:
                    return  # another run is still open: the cluster is decided when the last one ends
                self._jf_cluster = None
                page = [(d, s, k) for d, s, k in self._jf_page() if k in cl["keys"]]
                n = len(page)
                if not n:
                    return
                entries = "entry" if n == 1 else "entries"
                were = "wasn" if n == 1 else "weren"
                if not st.get("on") or cl["switched"]:
                    _say(f"(journal feed: {n} {entries} from runs the feed was off or switched in — not sent)")
                elif cl["wake"]:
                    _say(f"(journal feed: {n} {entries} — a wake overlapped; not sent)")
                    if cl["told_ok"]:
                        line = f"({n} journal {entries} from that moment {were}'t sent — a wake overlapped; /journal today shows the day)"
                elif cl["untold"]:
                    _say(f"(journal feed: {n} {entries} from a run the friend wasn't told in — not the feed's)")
                    if cl["told_ok"]:
                        line = (f"({n} journal {entries} from that moment {were}'t sent — two runs overlapped and one of "
                                f"them hadn't told {chat.friend_name()} of the feed; /journal today shows the day)")
                else:
                    queued = {(p["day"], p["key"]) for p in st["pending"]}
                    queued |= {(d, k) for d, ks in st["done"].items() for k in ks}
                    st["pending"] += [{"day": d, "stamp": s, "key": k} for d, s, k in page if (d, k) not in queued]
                    self._jf_save()
                    _say(f"journal feed: {n} {entries} from {run['kind']} queued")
        except Exception as e:  # noqa: BLE001 — never the run down
            _say(f"(journal feed: {type(e).__name__}: {e})")
            return
        if line:
            try:
                self.notice(line)
            except Exception as e:  # noqa: BLE001
                _say(f"(a line didn't reach the phone: {type(e).__name__}: {e})")
        self.journal_feed_if_due()

    # -- the phone
    def _jf_say(self, text: str) -> None:
        """The command's answer, plain; a send that fails is a line in the window, never the loop down."""
        try:
            self.send(text, markdown=False)
        except Exception as e:  # noqa: BLE001
            _say(f"(a line didn't reach the phone: {type(e).__name__}: {e})")

    def _journal_state_line(self, short: bool = False) -> str:
        """/journal alone (and /status's line): on since when and how many went today, or off."""
        try:
            with self._jf_lock:
                return self._jf_state_line(short)
        except Exception as e:  # noqa: BLE001 — /status never down for it
            return f"journal feed: ({type(e).__name__})"

    def _jf_state_line(self, short: bool) -> str:
        from datetime import date
        st = self._jf_state()
        today = date.today().isoformat()
        if not st.get("on"):
            return ("journal feed off" if short else
                    f"(journal feed off — /journal on sends what {chat.friend_name()} writes in their journal during a "
                    "visit; /journal today sends today's entries once)")
        since = float(st.get("since") or 0)
        when = (_jf_when(datetime.fromtimestamp(since).date().isoformat(), datetime.fromtimestamp(since).strftime("%H:%M"),
                         today) if since else "?")
        if (st.get("knows") or "off") != "on":
            return (f"journal feed on since {when} · they're told at their next turn" if short else
                    f"(journal feed on since {when} — {chat.friend_name()} will be told at their next turn; what they "
                    "write from then on in a visit comes here)")
        sent = st.get("sent") or {}
        n = int(sent.get("n") or 0) if sent.get("day") == today else 0
        waiting = len(st.get("pending") or [])
        held = f", {waiting} waiting" if waiting else ""
        if short:
            return f"journal feed on since {when} · {n} sent today{held}"
        return (f"(journal feed on since {when} — {n} {'entry' if n == 1 else 'entries'} sent today{held}; "
                f"{chat.friend_name()} knows)")

    def journal_command(self, arg: str) -> None:
        """/journal [on|off|today|yesterday|YYYY-MM-DD]."""
        if getattr(self, "TAG", "telegram") != "telegram":
            self._jf_say("(the journal feed is the Telegram bridge's — /journal works there)")
            return
        if not getattr(config, "JOURNAL_FEED", False):
            self._jf_say("(the journal feed is off in config — JOURNAL_FEED)")
            return
        a = (arg or "").strip().lower()
        try:
            if a in ("", "status"):
                self._jf_say(self._journal_state_line())
            elif a == "on":
                self._jf_switch(True)
            elif a == "off":
                self._jf_switch(False)
            else:
                from datetime import date, timedelta
                day = {"today": date.today(), "yesterday": date.today() - timedelta(days=1)}.get(a)
                if day is None:
                    try:
                        day = datetime.strptime(a, "%Y-%m-%d").date()
                    except ValueError:
                        self._jf_say("(/journal — on, off, today, yesterday, or a day as YYYY-MM-DD; alone, how it stands)")
                        return
                self._jf_send_day(day.isoformat())
        except Exception as e:  # noqa: BLE001 — a command, never the loop down
            _say(f"(journal feed: {type(e).__name__}: {e})")
            self._jf_say(f"(/journal didn't go through — {type(e).__name__}: {e})")

    def _jf_switch(self, on: bool) -> None:
        """The switch. What the phone says is what the friend has been told at this instant — a turn in flight that is
        telling them right now counts as telling them."""
        fr = chat.friend_name()
        with self._jf_lock:
            st = self._jf_state()
            if bool(st.get("on")) == on:
                said = f"(the journal feed is already {'on' if on else 'off'} — nothing new is said to {fr})"
            else:
                knows = st.get("knows") or "off"
                telling = (self._jf_tell or {}).get("told", "")  # a turn running now that carries the feed's sentence
                st["on"], st["since"], st["by"] = on, time.time(), self._keeper_name()
                st["gen"] = int(st.get("gen") or 0) + 1  # a run going on now: what it writes is not sent
                if on:
                    if telling == "off":
                        said = (f"(journal feed on again — {fr} is being told it went off in the turn running now; "
                                "they'll be told it is on at their next turn)")
                    elif knows == "on" and not telling:
                        said = (f"(journal feed on again — {fr} was never told it went off, so nothing changes for them; "
                                "what they write in a visit from now on comes here)")
                    else:
                        said = (f"(journal feed on — what {fr} writes in their journal during a visit (its pauses and "
                                "afterglow too) comes here as they write it, each with its time; they'll be told at their "
                                "next turn, and it starts after that. Their wakes are not sent — /journal today shows the "
                                "day. Entries from your quiet hours wait for the morning. /journal off ends it)")
                else:
                    dropped = len(st.get("pending") or [])
                    st["pending"] = []
                    lost = (f" {dropped} {'entry' if dropped == 1 else 'entries'} still waiting won't be sent — "
                            "/journal today shows the day." if dropped else "")
                    if telling == "on":
                        said = (f"(journal feed off — {fr} is being told it is on in the turn running now; they'll be "
                                f"told it is off at their next turn.{lost})")
                    elif knows == "on":
                        said = f"(journal feed off — the entries stay on the page; {fr} will be told at their next turn.{lost})"
                    else:
                        said = f"(journal feed off — {fr} was never told it was on, so nothing is said to them.{lost})"
                self._jf_save()
                _say(f"journal feed {'on' if on else 'off'}")
        self._jf_say(said)

    def _jf_send_day(self, day: str) -> None:
        """/journal today|yesterday|YYYY-MM-DD: that day's entries, once, in order — as you opening the page; packed
        into as few messages as fit, nothing marked, nothing said to the friend."""
        from datetime import date
        fr = chat.friend_name()
        label = _jf_date(day, year=day[:4] != str(date.today().year))
        if not (config.JOURNAL_DIR / f"{day}.md").is_file():
            self._jf_say(f"(no journal for {label} — journal/{day}.md isn't there)")
            return
        raw = self._jf_read(day)
        if raw is None:
            self._jf_say(f"({fr}'s journal for {label} can't be read right now — journal/{day}.md)")
            return
        entries = [e for e in journal_feed_entries(raw) if e["text"]]
        if not entries:
            self._jf_say(f"({fr}'s journal for {label} has no entries)")
            return
        today = date.today().isoformat()
        n = len(entries)
        msgs, cur = [], f"({fr}'s journal, {label} — {n} {'entry' if n == 1 else 'entries'}:)"
        for e in entries:
            m = journal_feed_message(day, e["stamp"], e["text"], today, friend=fr)
            if len(cur) + 2 + len(m) <= JOURNAL_DAY_PACK:
                cur += "\n\n" + m
                continue
            msgs.append(cur)
            if len(m) <= JOURNAL_DAY_PACK:
                cur = m
            else:  # an entry longer than a message: cut as the bridge cuts, its last piece starts the next pack
                parts = split_long(m, JOURNAL_DAY_PACK)
                msgs += parts[:-1]
                cur = parts[-1]
        msgs.append(cur)
        for m in msgs:
            self._jf_say(m)

    def journal_feed_if_due(self, wait: bool = False) -> int:
        """The queued entries to the phone — in a thread of their own, so neither the poll nor a turn ever waits on a
        send. The poll calls it (the quiet hours ending, a guest gone, a send that failed); a run's end too.
        wait: deliver now, in this thread (tests). Returns how many went (0 when it went to the thread)."""
        if not self._jf_on_here() or not self.chat_id:
            return 0
        try:
            with self._jf_lock:
                st = self._jf_state()
                note, self._jf_note = self._jf_note, ""
                due = bool(st.get("pending")) and bool(st.get("on"))
        except Exception as e:  # noqa: BLE001
            _say(f"(journal feed: {type(e).__name__}: {e})")
            return 0
        if note:
            self._jf_say(note)
        if not due or self._jf_hold():
            return 0
        if wait:
            return self._jf_deliver()
        t = self._jf_thread
        if t is None or not t.is_alive():
            self._jf_thread = threading.Thread(target=self._jf_deliver, daemon=True)
            self._jf_thread.start()
        return 0

    def _jf_hold(self) -> bool:
        """Your quiet hours (TELEGRAM_QUIET_HOURS), your /quiet, or a guest at the desk: entries wait, and go after."""
        if self.quiet_now() or self.guest:
            return True
        try:
            import outbox
            return bool(getattr(config, "OUTBOX_ON", False)) and outbox.hold_active()
        except Exception:  # noqa: BLE001
            return False

    def _jf_done(self, st: dict, item: dict) -> None:
        """An entry out of the queue (sent, or skipped): kept by key for yesterday and today, never queued again."""
        from datetime import date, timedelta
        yday = (date.today() - timedelta(days=1)).isoformat()
        st["done"] = {d: v for d, v in (st.get("done") or {}).items() if d >= yday}
        if item["day"] >= yday:
            st["done"].setdefault(item["day"], []).append(item["key"])

    def _jf_deliver(self) -> int:
        """The queue to the paired phone, oldest first. The text is read from the page at the moment of sending (an
        entry no longer there as it was is skipped, and said); an entry leaves the queue only once Telegram took it;
        the state's lock is never held across a send. Paced after a few, so a long evening's go as Telegram likes."""
        from datetime import date
        if not self._jf_send_lock.acquire(blocking=False):
            return 0
        n = msgs = skipped = 0
        fr = chat.friend_name()
        try:
            while True:
                with self._jf_lock:
                    st = self._jf_state()
                    if not st.get("on") or not st.get("pending") or self._jf_hold() or not self.chat_id:
                        break
                    item = dict(st["pending"][0])
                raw = self._jf_read(item["day"])
                found = next((e for e in journal_feed_entries(raw or "") if e["key"] == item["key"]), None)
                if found is None or not found["text"]:
                    skipped += 1
                    with self._jf_lock:
                        if st["pending"] and st["pending"][0]["key"] == item["key"]:
                            st["pending"].pop(0)
                            self._jf_done(st, item)
                            self._jf_save()
                    continue
                parts = split_long(journal_feed_message(item["day"], found["stamp"], found["text"],
                                                        date.today().isoformat(), friend=fr))
                k = int(item.get("part") or 0)
                while k < len(parts):
                    pace = float(getattr(config, "JOURNAL_FEED_PACE_S", 1.0) or 0)
                    if pace > 0 and msgs >= 3:  # a few at once go at once; more go about one a second
                        time.sleep(pace)
                    try:
                        self.send(parts[k], markdown=False)
                    except Exception as e:  # noqa: BLE001 — kept; the next look tries again
                        _say(f"(journal feed: an entry didn't reach the phone — {type(e).__name__}: {e}; it waits)")
                        return n
                    msgs += 1
                    k += 1
                    with self._jf_lock:
                        if st["pending"] and st["pending"][0]["key"] == item["key"]:
                            st["pending"][0]["part"] = k
                            self._jf_save()
                with self._jf_lock:
                    if st["pending"] and st["pending"][0]["key"] == item["key"]:
                        st["pending"].pop(0)
                        self._jf_done(st, item)
                    today = date.today().isoformat()
                    sent = st.get("sent") or {}
                    st["sent"] = {"day": today, "n": (int(sent.get("n") or 0) if sent.get("day") == today else 0) + 1}
                    self._jf_save()
                n += 1
            if n:
                _say(f"journal feed: {n} {'entry' if n == 1 else 'entries'} to the phone")
        except Exception as e:  # noqa: BLE001 — a delivery, never the bridge down
            _say(f"(journal feed: {type(e).__name__}: {e})")
        finally:
            self._jf_send_lock.release()
        if skipped:
            self._jf_say(f"({skipped} journal {'entry' if skipped == 1 else 'entries'} waiting to be sent no longer "
                         f"stood on {fr}'s page as written — not sent; /journal today shows the day)")
        return n

    # ---- the loop ---------------------------------------------------------
    # ---- presence: sparks ------------------------------------------
    @staticmethod
    def presence_on() -> bool:
        """A spark is set (one at a time) — with none set, the idle roll and the pause go on as usual."""
        try:
            import presence
            return presence.waiting()
        except Exception:  # noqa: BLE001
            return False

    def game_guard_tick(self, force: bool = False) -> None:
        """A game on the card while their brain sits loaded and idle (after a visit, say): the door is closed, with
        its reading saved, so the game has the card. Not while a reply is in flight or a wake runs — the wake finishes
        (or, with /gaming on, ends at its next step) and its rest closes the door."""
        if not getattr(config, "GAME_GUARD_ON", False):
            return
        try:
            import gameguard
            import brain
            import presence
            gaming, why = gameguard.playing()
            if not gaming or not brain.door_status():
                return
            if self.lock.locked() or presence.waking():
                return
            if brain.stop_door(f"the game guard: {why}", save=True):
                _say(f"the brain set down for their game ({why})")
                if force:
                    self.send("(their brain is off the card — the game has it)", markdown=False)
        except Exception as e:  # noqa: BLE001
            _say(f"game guard: {type(e).__name__}: {e}")

    def penpal_turn_if_due(self) -> str:
        """A penpal's letter arrived: once the pastes settle, a turn of their own with the arrival line — read
        now, or later. Waits for a reply in flight, a wake, a game, their quiet and the night's quiet hours."""
        if not self.chat_id or getattr(self, "TAG", "telegram") != "telegram" or not getattr(config, "PENPALS_ON", False):
            return ""
        try:
            import penpal
            import presence
            sl = penpal.arrival_due()
            if not sl or self.lock.locked() or presence.waking() or self.quiet_now():
                return ""
            import outbox
            if outbox.hold_active():
                return ""
            import gameguard
            if gameguard.playing()[0]:
                return ""
            kind = penpal.arrival_kind(sl) if getattr(config, "PENPAL_PICTURE_LETTERS", False) else ""
            if kind and self.guest:  # a letter the keeper collected waits while a guest is at the desk
                return ""
            arr = penpal.take_arrival_record(sl) if kind in ("with", "pictures") else None
            text = "" if arr is not None else penpal.take_arrival(sl)
        except Exception as e:  # noqa: BLE001
            _say(f"penpal turn: {type(e).__name__}: {e}")
            return ""
        if arr is not None:  # its pictures before their eyes, a turn of theirs for each TELEGRAM_BATCH_MAX
            return self._pp_collected_turns(penpal, sl, arr)
        _say(f"a penpal's letter arrived: a turn of theirs ({sl})")
        tools.SPARK_TICK = True
        try:
            self.turn(text, as_keeper=True, spark=True)
        finally:
            tools.SPARK_TICK = False
        for t in reversed(self.history):  # the line is the engine's, not their
            if t.get("role") == "user" and t.get("content") == text:
                t["_engine"] = t["_spark"] = True
                break
        self._checkpoint()
        return text

    def presence_if_due(self) -> str:
        """A spark: presence on, no wake running, no reply in flight, and the visit quiet for the friend's interval —
        one turn in the open visit, opened by the engine's line. The quiet hours end presence. Returns the line."""
        import presence
        if not self.chat_id or getattr(self, "TAG", "telegram") != "telegram":
            return ""  # one door gives the sparks — the phone's Telegram (a Discord bridge beside it stays out)
        errand = presence.errand_due()  # a spark they set for a reason: comes whether drift is on, off or held
        intents = False
        if not errand and getattr(config, "INTENTIONS_ON", False):  # with no heartbeat, a due intention is a spark
            try:
                import doors
                import intentions
                intents = not doors.status("heartbeat") and bool(intentions.check()) and not presence.waking()
            except Exception:  # noqa: BLE001
                intents = False
        if not errand and not intents and not presence.waiting():
            return ""
        if self.quiet_now():
            if getattr(config, "PRESENCE_QUIET_HOURS_END", False) and presence.is_on():
                presence.turn_off("the quiet hours")
                self.notice("(presence ended — the quiet hours began; next_spark or /presence on starts it again)")
            return ""  # the quiet hours hold sparks — their rhythm stays theirs, the dice wait for the morning
        try:  # their quiet: sparks wait
            import outbox
            if outbox.hold_active():
                return ""
        except Exception:  # noqa: BLE001
            pass
        if self.lock.locked() or (not errand and not intents and not presence.due(self.last_activity)):
            return ""
        intention = ""
        if intents:
            try:
                import gameguard
                if gameguard.playing()[0]:
                    return ""
                import intentions
                items = intentions.take_due()
                intention = intentions.bell(items, bare=True) if items else ""
            except Exception:  # noqa: BLE001
                intention = ""
            if not intention:
                return ""
        try:
            import keeper_week
            at_work = " is at work" in keeper_week.where()
            keeper = keeper_week.keeper_name()
        except Exception:  # noqa: BLE001
            at_work, keeper = False, str(getattr(config, "USER_NAME", "") or "your keeper")
        said = next((str(t.get("content") or "") for t in reversed(self.history)  # the keeper's last message
                     if t.get("role") == "user" and t.get("content") and not t.get("_engine")), "")
        try:
            import seeds
            seed = "" if (presence.intense() or errand or intention) else seeds.draw()  # none in play or their own reasons
        except Exception:  # noqa: BLE001
            seed = ""
        text = presence.tick_line((time.time() - self.last_activity) / 60, keeper, at_work, last_said=said, seed=seed,
                                  errand=errand, intention=intention)
        _say("a spark: presence turn" + (" (their reason)" if errand else " (an intention)" if intention else ""))
        if intention:
            pass  # taken already; their drift and their errand are untouched
        elif errand:
            presence.take_errand()  # the spark they set for a reason has come; their drift is untouched
        else:
            presence.fired()  # this one has come; the next only when they set it again
        tools.SPARK_TICK = True
        spark_t0, was_intense = time.time(), presence.intense()
        try:
            self.turn(text, as_keeper=True, spark=True)
        finally:
            tools.SPARK_TICK = False
            if was_intense:
                presence.note_spark_time(time.time() - spark_t0)  # PRESENCE_INTENSE_CEILING's measure
        for t in reversed(self.history):  # the line rode as a user turn; it is the engine's, not theirs
            if t.get("role") == "user" and t.get("content") == text:
                t["_engine"] = t["_spark"] = True  # the transcript shows it as the engine's spark
                break
        self._checkpoint()
        return text

    @staticmethod
    def _spark_thinks() -> bool:
        """Whether a spark thinks first: intense by PRESENCE_THINK_INTENSE (off — instinct), every other
        spark by PRESENCE_THINK."""
        try:
            import presence
            if presence.intense():
                return bool(getattr(config, "PRESENCE_THINK_INTENSE", False))
        except Exception:  # noqa: BLE001
            pass
        return bool(getattr(config, "PRESENCE_THINK", True))

    def _send_spark(self, reply: str) -> None:
        """A spark's words: discreetly (silent, the words hidden until tapped) when /discreet is on, else as any reply."""
        try:
            import presence
            discreet = bool(presence.load().get("discreet"))
        except Exception:  # noqa: BLE001
            discreet = False
        try:  # the sent ledger
            import outbox
            outbox.log_sent("spark", reply[:60])
        except Exception:  # noqa: BLE001
            pass
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
        """The engine's week: on ENGINE_WEEK_DAY after ENGINE_WEEK_HOUR, once, the last seven days of
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
        """A newer anima, said once per version:
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
        """A press within seconds: looked at once per long poll, a touch would wait up to POLL_S (a poll waits that
        long for a message from the phone), after waiting for the keeper's look at the board.
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
        every BODY_PULL_MIN — in
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
        try:  # letters that waited: theirs to decide once the quiet is over (outbox.py)
            import outbox
            outbox.scan_later(self.quiet_now())
            outbox.ripen(self.quiet_now())
        except Exception as e:  # noqa: BLE001
            _say(f"outbox: {type(e).__name__}: {e}")
        self.deliver_mail()
        self.deliver_penpals()
        self.penpal_turn_if_due()
        self.penpal_desk_if_due()
        self.penpal_collect_if_due()  # a letter being collected, quiet a while: said once
        self.pages_watch_if_due()
        self.books_watch_if_due()  # a book the friend finished: one line, so the keeper knows to bring a new one
        self.deliver_creations()
        self.deliver_pictures()
        self.deliver_songs()
        self.deliver_touches()
        self.deliver_garden()
        self.deliver_skill_notices()
        self.deliver_self()
        self.journal_feed_if_due()  # journal entries waiting to go (the quiet over, a guest gone, a retry)
        idle_min = getattr(config, "TELEGRAM_IDLE_NEW_MIN", 180)
        if not self.presence_on():
            self.presence_if_due()  # a spark they set for a reason comes even with no drift on
        sparking = self.presence_on()
        if sparking:
            self.presence_if_due()  # sparks
        # the pause and the visit's end wait only for intense sparks (a turn every minute or so); drift sparks come
        # seldom, and with them on all day the afterglow never came — the pause counts from the keeper's last word
        held = False
        if sparking:
            try:
                import presence
                held = presence.intense()
            except Exception:  # noqa: BLE001
                held = True
        if held:
            pass
        elif self.history and ((idle_min and time.time() - self.last_activity > idle_min * 60)
                               or self.visit_crossed_the_night()):
            self.new_visit(quiet=True)
        else:
            self.pause_if_due()
        self.game_guard_tick()
        try:  # the desk: read every poll, so an arrival is noticed when it happens
            import desk
            desk.tick()
        except Exception:  # noqa: BLE001
            pass
        self.idle_set_down_if_due()
        self.night_if_due()
        self.week_if_due()  # the engine's week, once a week
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
        """The door's keep-alive: under the door with BRAIN_REST_CLOSES_DOOR, BRAIN_KEEP_ALIVE of quiet in
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

    def resume_orphan(self) -> str:
        """ORPHAN_RESUME_H: a visit the last bridge closed without — the window shut, the process killed — written within
        these hours is picked back up as the open visit, as /restart's stash is: no afterglow over it, and the next
        message reads one prompt, not two (an afterglow there would cost a second cold read). Older, it gets its afterglow as before. "" when there is none to pick up."""
        hours = float(getattr(config, "ORPHAN_RESUME_H", 6) or 0)
        if not hours or self.history:
            return ""
        try:
            f = chat.orphaned_visit("telegram", exclude=self.file)
            if not f or time.time() - f.stat().st_mtime > hours * 3600:
                return ""
            hist = chat.load_transcript(f)
        except Exception:  # noqa: BLE001 — the old road then
            return ""
        if not hist:
            return ""
        self.history = hist
        self.file = f
        self.last_activity = f.stat().st_mtime
        self.last_word = self.last_activity
        self.reflected_upto = len(hist)  # what was said before the close isn't sat with again at the next pause
        turns = sum(1 for t in hist if t.get("role") == "user" and t.get("content"))
        return (f"picked the last visit back up ({f.name}, {turns} turns of the keeper's) — the bridge had closed without it; it "
                f"carries on, no afterglow over it")

    def afterglow_orphan(self) -> str:
        """A visit the last bridge died with — a power cut, the
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
            jrun, aside = self._jf_quiet("the afterglow")  # the feed's line in its bell, when on ("" off: as before)
            try:
                out = chat.afterglow(done, f, tag=self.TAG, on_line=_say, on_words=self.afterthought,
                                     **({"aside": aside} if aside else {}))
            finally:
                self._glows -= 1
                self._jf_run_end(jrun)
            if out and getattr(config, "TELEGRAM_TELL_REFLECTIONS", True):
                self.notice(f"({out})")
            if not self.history:
                chat.rest_brain(_say)
        threading.Thread(target=_glow, daemon=True).start()
        return line

    def night_if_due(self) -> str:
        """THE NIGHT IN THE BRIDGE: a house that runs the
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
            # a visit is open: the night waits for it to end, as the heartbeat's wake does (a page
            # condensed into a live visit changes the window under the friend, and the next
            # message reads the whole window from zero) — the idle roll closes the visit, the night follows
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
            jrun = self._jf_run_start("the night")  # the night's brain calls: never the feed's
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
            finally:
                self._jf_run_end(jrun, False)
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
        # last_word, not last_activity: the friend's sparks don't keep the pause from coming
        if not mins or not self.history or time.time() - getattr(self, "last_word", self.last_activity) < mins * 60:
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
            aside = self._game_aside(self.history[self.reflected_upto:])  # "part of this visit was your adventure…"
            jrun, aside = self._jf_quiet("a pause", aside)  # the feed's line in its bell, when on
            try:
                line = chat.pause_reflection(self.history, self.file, tag=self.TAG, on_line=_say,
                                             since=self.reflected_upto, on_words=self.afterthought,
                                             **({"aside": aside} if aside else {}))
            finally:
                self._jf_run_end(jrun)
            self.reflected_upto = len(self.history)  # past the pause's own turns too
            self.last_activity = time.time()  # one bell per pause, not one per poll
            self.last_word = self.last_activity
            if line and getattr(config, "TELEGRAM_TELL_REFLECTIONS", True):
                self.notice(f"({line})")  # the phone hears what they kept
        finally:
            self.lock.release()
        # under the door the card would stay held until the visit's end — there is no keep-alive timer there
        #: the pause ends with the brain set down, the reading saved, the visit open
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
        seated = self.restore_guest()  # the guest's seat survives the restart, and the phone is told
        if seated:
            _say(seated)
            if self.chat_id:
                try:
                    self.notice(f"({seated})")
                except Exception:
                    pass
        playing = self.game_restore_line()  # a game still open (adventures.json), and the phone is told
        if playing:
            _say(playing)
            if self.chat_id:
                try:
                    self.notice(f"({playing})")
                except Exception:
                    pass
        travelling = self.trip_restore_line()  # a trip still open (world_trip.json), and the phone is told
        if travelling:
            _say(travelling)
            if self.chat_id:
                try:
                    self.notice(f"({travelling})")
                except Exception:
                    pass
        collecting = self.penpal_collect_restore_line()  # a letter still being collected, and the phone is told
        if collecting:
            _say(collecting)
            if self.chat_id:
                self._pc_send(f"({collecting})")
        resumed = "" if self.history else self.resume_orphan()  # a recent visit closed without its bridge
        if resumed:
            _say(resumed)
            if self.chat_id:
                try:
                    self.notice(f"({resumed})")
                except Exception:
                    pass
        else:
            _co = chat.carry_orphan("telegram", exclude=self.file)  # ...and its last turns ride at the next message
            if _co:
                _say(_co)
            self.afterglow_orphan()  # a visit the last bridge died with, if any; the open one is left alone
        self.watch_touches()  # a press reaches the phone within seconds, not a poll
        self.watch_penpals()  # their penpal letters too
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
            # the panel's Stop: memory/.stop-bridge, looked for between polls — the
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
