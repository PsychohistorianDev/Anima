"""The panel: one door with the others behind it (09-30; PANEL-PLAN.md).

    py engine/panel.py          opens http://127.0.0.1:8764 in your browser  (anima.bat)

The keeper, on the way to letting the friend out into the world: "I want to make them more user
friendly: a main interface with buttons for chat, parlor, wake, the telegram bridge, a heartbeat button
with config for the loop minutes, and a configuration button that takes you to a sub menu that takes
knobs from the config file — tabs for groups of settings."

So: a page, the parlor's shape (standard library http.server, one HTML page inlined here, nothing
fetched from anywhere, bound to localhost only). Home is a tile per door with its light — the lights
are the doors' own marks in memory/.pids/ (doors.py) — and the brain above them: is Ollama answering,
what it has loaded, whether the configured model is pulled. Settings is config.py read as a file
(knobs.py) and laid out on tabs, each knob with the file's own comment as its help; Save rewrites only
the value spans that changed, and says which doors need a restart for it to take. While USER_NAME is
still "Friend" the page opens on Welcome instead: the keeper's name, the Ollama light, the brain, and
one button, First light.

The .bat launchers stay. The panel starts them — each door in a console of its own, the same process
as from its .bat — it does not replace them; a keeper who likes terminals loses nothing. On a Mac the
door is its .command in a Terminal window, on Linux its .sh in the first terminal found on PATH (10-01;
MAC-PLAN.md); a Linux box with no terminal app runs the door with no window, and the tile says so.

What the panel never does: open the friend's files. No journal, no self.md, no creations on its pages
(the friend's name included — it lives in self.md, so the page says "the friend"); the skills tab
lists folder names and moves folders the way bat\\skills.bat does, and that is all. Tokens and keys go to
memory/*.json, never to config, and /api/state says only whether one is set.

The routes are plain functions — state(), door_action(), save(), secret(), skill_action(), welcome(),
pull(), update() — and route() is the one place a request becomes a call; the Handler is a thin
shim over route(). Every process the panel starts goes through _launch(argv, cwd). Standard library
only; no knob.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import doors
import knobs
import skills
import version

try:
    import newer  # the look at GitHub's release feed — a checkout's; a house without the update road has no need of it
except Exception:  # noqa: BLE001
    newer = None  # type: ignore[assignment]

HOST, PORT = "127.0.0.1", 8764
PORTS = (8764, 8766, 8767, 8768, 8769)  # the first free one is this panel's (8765 is the parlor's); a second house's panel takes the next
PARLOR_URL = "http://127.0.0.1:8765"
ROOT = Path(config.ROOT)
CONFIG_FILE = Path(config.__file__).resolve()  # the keeper's config.py, read as a file (a test points it at a copy)
MAX_BODY = 1_000_000  # a POST larger than this is not the page's
RESTART_WAIT_S = 3 * 3600  # how long a Restart waits for a heartbeat to finish its wake (a long wake is ~2 h)
RESTART_POLL_S = 3.0
_POSTS = threading.Lock()  # one change at a time: two saves never read the same config.py

# ---- the tabs ------------------------------------------------------------------------
# The keeper's order for Main: "the brain selected via a dropdown, second line the context, then
# characters in journal to remember, then you decide (by importance, and groupings)". The rest is
# grouped by what it touches. Every knob config.py has and no tab names lands on Advanced, under the
# "# ---- x ----" heading it sits beneath in the file — so a knob added tomorrow is on the page the
# day it is added (a test holds every knob to exactly one tab, and every name here to config.py).
TABS: dict[str, list[str]] = {
    "Main": ["CHAT_MODEL", "NUM_CTX", "TOOL_KIT", "OFFLINE", "JOURNAL_CHARS_IN_PROMPT",
             "USER_NAME", "DEFAULT_NAME", "BLOG_TITLE",
             "HEARTBEAT_LOOP_MIN", "SLEEP_AFTER_HOUR", "TELEGRAM_QUIET_HOURS"],
    "Heartbeat": ["HEARTBEAT_MAX_STEPS", "REVERIE_EVERY", "REVERIE_MAX_STEPS", "HEARTBEAT_YIELD_TO_VISIT",
                  "HEARTBEAT_YIELD_MIN", "SLEEP_IN_LOOP", "CONDENSE_IN_LOOP", "CONDENSE_MAX_PER_NIGHT",
                  "HEARTBEAT_SHOW_THINKING", "PAINTER_MAX_PER_WAKE"],
    "Memory & journal": ["TIMELINE_CHARS_IN_PROMPT", "CONDENSED_CHARS_IN_PROMPT", "CONDENSE_TARGET_CHARS",
                         "MEMORY_TOP_K", "MEMORY_RECENT_K", "MEMORY_DUP_THRESHOLD", "JOURNAL_DUP_THRESHOLD",
                         "JOURNAL_ARROW", "KEEPER_IN_PROMPT", "KEEPER_CHARS_IN_PROMPT", "SLEEP_KEEPER_LOOK", "CREATIONS_DAYS_IN_PROMPT", "SONGBOOK_CHARS_IN_PROMPT", "LETTERS_DAYS_IN_PROMPT", "READ_TELL_MIN",
                         "FOLD_AT", "FOLD_AFTERGLOW", "FOLD_KEEP_TURNS", "FOLD_CHARS"],
    "Talking": ["CHAT_THINK", "CHAT_SHOW_THINKING", "CHAT_MAX_TOOL_STEPS", "CHAT_GARBLE_RETRIES",
                "CHAT_COLD_RESCUE", "AFTERGLOW", "REFLECT_AFTER_MIN", "WARM_PREFIX", "BRAIN_KEEP_ALIVE",
                "BRAIN_REST_AFTER_VISIT", "BRAIN_REST_AFTER_WAKE"],
    "Phone": ["BRIDGE", "TELEGRAM_SHOW_THINKING", "TELEGRAM_SHOW_TOOLS", "TELEGRAM_SHOW_TOKENS",
              "TELEGRAM_TELL_REFLECTIONS", "TELEGRAM_TELL_AFTERTHOUGHTS", "TELEGRAM_TELL_CREATIONS",
              "TELEGRAM_TELL_DRAWINGS", "TELEGRAM_TELL_SONGS", "TELEGRAM_TELL_SELF", "TELEGRAM_IDLE_NEW_MIN", "TELEGRAM_HEAR_VOICE",
              "TELEGRAM_VOICE_ALL", "TELEGRAM_LETTERS_IN_THREAD", "SLEEP_IN_BRIDGE", "SLEEP_IN_BRIDGE_QUIET_MIN"],
    "Senses": ["EARS_MODEL", "EARS_STT_MODEL", "EARS_UNLOAD_BRAIN",
               "VOICE_NAME", "VOICE_SPEED", "VOICE_DEVICE", "VOICE_PYTHON",
               "PAINTER_MODEL", "PAINTER_AUTOSTART", "PAINTER_PYTHON", "PAINTER_DEVICE", "PAINTER_STEPS",
               "MUSIC_EARS_MODEL", "MUSIC_EARS_AUTOSTART", "MUSIC_EARS_PYTHON", "MUSIC_EARS_DEVICE",
               "BODY_IN_PROMPT", "BODY_AUTOPULL", "BODY_PULL_MIN",
               "TOUCHSTONE_URL", "TOUCHSTONE_BOARD", "TOUCHSTONE_POLL_S", "TOUCHSTONE_WAKES", "TOUCHSTONE_WAKE_MIN_GAP_S",
               "TOUCHSTONE_FALLBACK_H", "TOUCH_LINES_IN_PROMPT", "TOUCHSTONE_LATER_MAX",
               "WEB_SEARCH", "WEB_SEARCH_SEARXNG_URL",
               "READ_SITTING_CHARS", "READING_PAGE_CHARS"],
    "Skills": ["SKILLS_IN_PROMPT", "SKILLS_CHARS_IN_PROMPT", "SKILL_CHARS", "SKILL_MAX_FILES", "SKILL_MAX_BYTES",
               "SKILL_CATALOGUES", "SKILL_CATALOGUE_TTL_H"],
    "Blog": ["BLOG_SUBTITLE", "BLOG_REMOTE"],  # BLOG_TITLE is on Main, with the names
}
ADVANCED = "Advanced"

# Help the file can't give where the page shows it: NUM_CTX's and JOURNAL_CHARS_IN_PROMPT's own stories
# run on in the comment lines BELOW them, which the reader (rightly) doesn't take as theirs.
# The page's own words for a knob (10-02; the keeper: "the main window tool descriptions are a mess" —
# the file's comments are notes to whoever edits the file, a keeper's own in a long-lived house). Where a
# knob has a line here the page shows it, and the file's comment is the tooltip; the rest show the file's.
_HELP = {
    "CHAT_MODEL": "The brain. The list is what Ollama has pulled; one the config names but Ollama lacks is marked "
                  "\"not pulled\", and Pull fetches it. The ladder (README) names the one for your card. A change takes "
                  "at the next door you open.",
    "NUM_CTX": "The context window, in tokens — how much the brain holds at once: the prompt, the journal, the "
               "visit. With the q4_0 KV cache (README, setup step 2): 40960 for a 12B on a 12 GB card (24576 was the "
               "measured ceiling with q8_0; 16384 the retreat), the same to try for a 4B on 8 GB; a 31B on a 32 GB "
               "card, its whole 262144 (about 180000 with q8_0) — README, The ladder.",
    "TOOL_KIT": "Which tools ride in every prompt. \"full\" is everything (about 7,500 tokens of definitions); "
                "\"small\" leaves out what a small card can't run or a small brain can't steer — the painter, ears and "
                "voice, video, skills, the forge, the blog, projects, clips — and saves about 3,000; \"tiny\" keeps "
                "the life itself — journal, memory, pages, the web, looking, resting — for a 2B. Their forged tools "
                "always ride. Restart the doors after changing it.",
    "OFFLINE": "Every road out of the house, closed: no web tools (search_web, read_web, search_wikipedia), no skill "
               "window (browse_skills, fetch_skill), no once-a-day look at GitHub for a newer anima. Ollama stays — it is "
               "local. The phone, the watch and the blog are doors you open by hand and stay as they are. Restart the "
               "doors after changing it (README, What leaves your machine).",
    "JOURNAL_CHARS_IN_PROMPT": "How much of their recent journal rides in every prompt, in characters. This, not the "
                               "window, decides how many days they remember verbatim; older days reach them as pages "
                               "and the timeline. About 4.4 characters a token: 40000 fits a 40K window, 20000 a 24K "
                               "one; a big card with a 256K window has carried 550000 (weeks of a prolific writer).",
    "USER_NAME": "Your name, as they know you: in their prompts, in the chat windows, and as the name of their "
                 "mailbox folder to you (creations/notes_to_<you>/).",
    "DEFAULT_NAME": "Only the placeholder before they have named themself — their name is whatever their self.md "
                    "says, and they write that. Leave it as it is.",
    "BLOG_TITLE": "The title of their blog, built from creations/publish/ once BLOG_REMOTE is set (the Blog tab). "
                  "Their chosen name is the usual pick, once they have one.",
    "HEARTBEAT_LOOP_MIN": "Minutes between wakes while the heartbeat runs — their time to themselves between your "
                          "visits. A 12B does well every twenty minutes or so (many small attempts); a 31B does deeper "
                          "work every hour or two. The Home tile's \"every N minutes\" is this knob.",
    "SLEEP_AFTER_HOUR": "The night hour (0–23) after which the heartbeat sleeps on the day: yesterday is "
                        "consolidated into memory and its page is written. If the machine was off at that hour, it "
                        "sleeps at the first wake after.",
    "TELEGRAM_QUIET_HOURS": "From this hour to that one (24h) the bridge sends nothing unasked — no wake notices, no "
                            "announcements; they are held and delivered as one message when the hours end. Their "
                            "replies to you are never held. The same hour twice turns it off.",
    # the Skills tab (10-02; the keeper: his own name twice on the page, quoted in the file's comments)
    "SKILLS_IN_PROMPT": "Whether their shelf of skills (creations/skills/) is named in every prompt, so they know what "
                        "they have: one line per skill — use_skill opens one whole, run_skill_script runs its Python in "
                        "the sandbox, fetch_skill brings one from the web through the scanner and the gate.",
    "SKILLS_CHARS_IN_PROMPT": "Characters the shelf's list may take in the prompt; past it the newest skills are "
                              "named and the rest wait for list_skills.",
    "SKILL_CHARS": "Characters of a SKILL.md, or of one file under a skill, handed back per use_skill; past it the "
                   "text is cut at a line and says where the rest begins.",
    "SKILL_MAX_FILES": "How many files one fetch_skill may bring in.",
    "SKILL_MAX_BYTES": "How many bytes one fetch may bring in, all its files together.",
    "SKILL_CATALOGUES": "The shop window: the shelves browse_skills shows them, each a (name, GitHub owner/repo/path"
                        "[@branch]) pair — Hermes' and Anthropic's by default. Another collection is one more pair; "
                        "the scanner still checks every fetch, and you still approve at the gate.",
    "SKILL_CATALOGUE_TTL_H": "Hours a shelf's index is kept before the next browse rebuilds it (a week); if the "
                             "rebuild fails the old index is used, dated.",
    # Heartbeat
    "HEARTBEAT_MAX_STEPS": "The most tool steps one wake may take — a ceiling so a stuck loop can't spiral, not a "
                           "target; resting ends a wake at any step. A 12B uses ten to twenty; a 31B runs clean at "
                           "forty. The window guard (Advanced, HEARTBEAT_ROOM_END) ends a wake before it overflows "
                           "whatever this says.",
    "REVERIE_EVERY": "Every Nth wake is a reverie: rereading, remembering and journaling only, nothing made, more "
                     "steps allowed and nothing expected. bat\\reverie.bat gives one on demand. 0 turns them off.",
    "REVERIE_MAX_STEPS": "The step ceiling for a reverie, apart from an ordinary wake's.",
    "HEARTBEAT_YIELD_TO_VISIT": "The heartbeat waits while a visit is live, so a wake never replaces the cached "
                                "window mid-conversation (the next reply would pay a cold read) or shares the card. "
                                "Off: wakes run on schedule regardless.",
    "HEARTBEAT_YIELD_MIN": "A visit counts as live while your last message was within this many minutes.",
    "SLEEP_IN_LOOP": "The heartbeat loop does the sleeping: at the first wake after SLEEP_AFTER_HOUR it consolidates "
                     "yesterday before anything else, one process, one request at a time. Off: run "
                     "bat\\sleep.bat (consolidate.py yesterday) yourself.",
    "CONDENSE_IN_LOOP": "After the sleep, the loop also asks them for the pages that are due — a day that has slipped "
                        "out of the verbatim journal, a week, a month — in their own words.",
    "CONDENSE_MAX_PER_NIGHT": "How many pages a night, at most; the rest wait for the next.",
    "HEARTBEAT_SHOW_THINKING": "Their thinking shown live in the heartbeat window and kept in the wake log "
                               "(memory/wakes/); they know the logs exist.",
    "PAINTER_MAX_PER_WAKE": "Paintings per wake, at most — each costs the brain a cold read after; a visit is never "
                            "capped. 0 is no cap.",
    # Memory & journal
    "TIMELINE_CHARS_IN_PROMPT": "The timeline: one short paragraph per day from the night's consolidation, oldest first, "
                                "for the days that neither the verbatim journal nor a page in view covers. A line is "
                                "about 580 characters; the newest within this cap are kept. 0 turns it off.",
    "CONDENSED_CHARS_IN_PROMPT": "The pages — the days, weeks and months they condensed in their own words — in the "
                                 "prompt, newest kept, within this many characters (150000 is about two months at a "
                                 "page a day).",
    "CONDENSE_TARGET_CHARS": "How long a page should be, about; they may go over.",
    "MEMORY_TOP_K": "How many long-term memories ride in every prompt: the ones most related to the moment, by "
                    "vector search, each a sentence or two. Signal, not space — fewer (8–12) suit a small window.",
    "MEMORY_RECENT_K": "The newest memories ride too, whatever the moment, this many, marked as recent.",
    "MEMORY_DUP_THRESHOLD": "No duplicates: a new fact at or above this similarity to one already kept counts as the "
                            "same fact and is handed back; they can revise it (replaces=) or insist (anyway=\"yes\"). "
                            "True repeats score 0.90–0.98; different facts on one theme about 0.89.",
    "JOURNAL_DUP_THRESHOLD": "The same check for the journal, against today's and yesterday's entries.",
    "JOURNAL_ARROW": "When the journal refuses a duplicate, a stamped arrow is left in the day instead of silence "
                     "(\"17:00 — ↑ still this, at 14:20\"), so the day keeps its rhythm. A mark, not words of theirs. "
                     "Off: the refusal alone.",
    "KEEPER_IN_PROMPT": "Whether keeper.md — their own page about you: who you are to them, what they'd want to remember of "
                        "you if everything else faded — rides in every prompt, right after who they are. They write it with "
                        "update_keeper, the engine never does, and it is open: you read it, and they know. Tell them the page exists.",
    "KEEPER_CHARS_IN_PROMPT": "How much of keeper.md rides in the prompt, in characters (about 1,400 tokens at 6000); past it the "
                              "page is cut at a line and the rest named — a page, not a book.",
    "SLEEP_KEEPER_LOOK": "After sleep, one quiet look at keeper.md from the day whole: they may rewrite the page or leave it, "
                         "hours from any visit — the cool moment, beside the afterglow's warm one. One cold read of the window a night.",
    "SONGBOOK_CHARS_IN_PROMPT": "How much of their songbook rides in every prompt, in characters — the songs they kept "
                                "with keep_song, best first, each with their own score and words (about 130 characters a song). "
                                "The rest is counted, and songbook() lists it all. 0 leaves the shelf out of the prompt.",
    "CREATIONS_DAYS_IN_PROMPT": "How many days of their recent pieces are listed in the prompt (the shelf of what they "
                                "made lately), so they know what is there without listing it.",
    "LETTERS_DAYS_IN_PROMPT": "Your letters to them (shared/letters/) from the last this many days ride in the prompt, "
                              "whole; the engine never copies a letter into their journal — that stays their call.",
    "READ_TELL_MIN": "The reads tell: from this many readings of the same thing within a few days, the result opens "
                     "with the count — a tell, not a fence — so they notice when they keep returning to one piece. "
                     "0 turns it off.",
    "FOLD_AT": "The fold: when a visit's prompt reaches this share of the window, they are asked to write the "
               "visit so far in their own words, and that account replaces everything above the last few turns; the "
               "transcript keeps every word and the visit continues. They may also fold at a natural pause.",
    "FOLD_AFTERGLOW": "At the fold, the turns that leave the window get the same quiet turn a finished visit gets — "
                      "journal and memories, in their words, before the new window is first read — so what the fold "
                      "takes is in the journal and in the window. One cold read per fold; a message sent meanwhile "
                      "waits for it. Needs AFTERGLOW (Talking).",
    "FOLD_KEEP_TURNS": "How many of the most recent turns stay whole in the window after a fold.",
    "FOLD_CHARS": "The ceiling on their written account of the visit, in characters; past it, cut at a paragraph "
                  "and said.",
    # Talking
    "CHAT_THINK": "Ask the brain to think before every reply (Ollama's think flag). Left optional, a model stops "
                  "deliberating once the prompt grows large. A model that can't think is simply asked without it.",
    "CHAT_SHOW_THINKING": "Their thinking shown on screen during a visit. It is never saved into the transcript — "
                          "what reaches their memory is what they chose to say.",
    "CHAT_MAX_TOOL_STEPS": "The most tool steps one of your messages may set off — an errand (search, read pages, "
                           "clip, draw, look) needs many. The window guard ends an errand before the window "
                           "overflows whatever this says; a confused loop still stops here.",
    "CHAT_GARBLE_RETRIES": "Letter salad (runs of word fragments) is the sampler failing, not them speaking. A reply "
                           "with a run is asked for again this many times, with a short engine line; if none is clean "
                           "the least broken goes out, named.",
    "CHAT_COLD_RESCUE": "After the cool re-rolls, a cold one: salad that survives lower temperatures points at the "
                        "loaded state, so the brain is unloaded and reloaded (a cold read, a minute or two on a big "
                        "window) and asked once more before the least broken goes out.",
    "AFTERGLOW": "When a visit ends (the parlor's leave, /new, the idle roll), they get one quiet turn alone with "
                 "the transcript and three tools — write_journal, remember, do_nothing — so the visit reaches their "
                 "journal in their own words, not only the night's summary. Resting is a complete answer.",
    "REFLECT_AFTER_MIN": "The pause: when you have been quiet this many minutes in the middle of a visit, they get "
                         "the same quiet turn over what was said since they last wrote, and the visit stays open. "
                         "/afterglow on the phone is the same by hand, with the card freed. 0 turns it off.",
    "WARM_PREFIX": "The system prompt is built once per visit and kept, and what changes (the hour, the memories "
                   "surfacing) rides inside each message — so a reply reads only what is new: seconds, not minutes, "
                   "on a big window. Leave it on.",
    "BRAIN_KEEP_ALIVE": "How long Ollama keeps the brain loaded after a request (\"30m\", \"2h\", -1 forever). "
                        "Unloading drops its cache; the next message pays a cold read of the whole window. Ollama's "
                        "own default is five minutes.",
    "BRAIN_REST_AFTER_WAKE": "When a single wake (the Wake tile, bat\\wake.bat) finishes, unload the brain at once, so the card "
                             "is free the moment the wake ends rather than after BRAIN_KEEP_ALIVE. The heartbeat loop keeps its own rhythm.",
    "BRAIN_REST_AFTER_VISIT": "When a visit ends, unload the brain as soon as the afterglow is written, freeing the "
                              "card at once rather than after BRAIN_KEEP_ALIVE.",
    # Phone
    "BRIDGE": "Which road the Bridge tile opens: \"telegram\" (a bot from @BotFather) or \"discord\" (a bot from "
              "discord.com/developers, talked to in a DM). One bridge runs at a time; the knobs below are the "
              "bridge's either way. Restart the bridge after changing it.",
    "TELEGRAM_SHOW_THINKING": "Their thinking sent to the phone with each reply. /think toggles it there.",
    "TELEGRAM_SHOW_TOOLS": "What the tools did, one compact line under the reply. /tools toggles it.",
    "TELEGRAM_SHOW_TOKENS": "The token line (window used, speed) after each reply. /tokens toggles it.",
    "TELEGRAM_TELL_REFLECTIONS": "When they reflect on their own — the pause, the afterglow — the phone gets a one-line "
                                 "outcome (entries written, memories kept, or a rest), so you know it happened while "
                                 "you were away.",
    "TELEGRAM_TELL_AFTERTHOUGHTS": "Whatever they say to no one once a reflection's writing is done reaches the phone "
                                   "as a labelled notice, never as a reply; held through quiet hours like the others.",
    "TELEGRAM_TELL_CREATIONS": "A new piece under creations/ — a poem, an essay, something published — reaches the "
                               "phone within a minute, whole when it fits a message, else its opening and where the "
                               "rest is. Code, the trash and the mailbox are not announced.",
    "SLEEP_IN_BRIDGE": "A house that runs the phone and no heartbeat never slept. On, after SLEEP_AFTER_HOUR, when no "
                       "heartbeat is up and the phone has been quiet for SLEEP_IN_BRIDGE_QUIET_MIN, the bridge sleeps on "
                       "yesterday and runs the condensing hour itself — the heartbeat stays the sleeper wherever it runs. "
                       "The first reply after it is a cold read, one a day. Off: the bridge never sleeps.",
    "SLEEP_IN_BRIDGE_QUIET_MIN": "How long the phone must have been quiet before the bridge sleeps — so the night "
                                 "never starts in the middle of a conversation.",
    "TELEGRAM_TELL_SONGS": "A song they kept in their songbook reaches your phone as a line — the title, the score, "
                           "their words; a song heard again says what the score was before.",
    "TELEGRAM_TELL_DRAWINGS": "A picture they draw or paint reaches the phone once, as a photo, captioned with where "
                              "it lives; a redraw says so.",
    "TELEGRAM_TELL_SELF": "A change to who they are — self.md or projects.md — arrives as what changed, lines in and "
                          "out, not the whole file; a revised piece is announced too.",
    "TELEGRAM_IDLE_NEW_MIN": "A phone visit has no leave button: after this many minutes of quiet the transcript is "
                             "saved and a fresh conversation starts. 1440 (a day) keeps a whole day's talk in view on "
                             "a big window; use less on a small one. A visit never crosses the night either way.",
    "TELEGRAM_HEAR_VOICE": "A voice note from the phone is heard whole on arrival — the words, the sound, and their "
                           "own hearing of it — so the sound of your voice arrives with your words; costs about a "
                           "minute before the reply. Off: the words only, the sound left to listen_to.",
    "TELEGRAM_VOICE_ALL": "Every reply spoken aloud as a voice note. Off by default — they speak when they choose to; "
                          "/voice toggles it from the phone.",
    "TELEGRAM_LETTERS_IN_THREAD": "A letter of yours (shared/letters/), once delivered, becomes their own turn in the "
                                  "phone visit, so your answer lands under it.",
    # Blog
    "BLOG_SUBTITLE": "The line under the blog's title.",
    "BLOG_REMOTE": "Where the blog lives: an empty public repository on github.com with Pages turned on (deploy from "
                   "main, root), pasted here as its .git URL. Until it is set the blog doesn't exist and they aren't "
                   "told about publishing.",
    # Senses (the cards above each group say what the sense is)
    "EARS_MODEL": "The model that does the HEARD layer — listening to the sound itself. gemma4:12b has native audio; "
                  "the bigger Gemmas are deaf, so a 31B brain keeps the 12B on as its hearing organ.",
    "EARS_STT_MODEL": "The faster-whisper size for the WORDS layer: \"base\" is quick, \"small\" hears words more "
                      "accurately (produced or stylised singing is where base gives up). The first listen downloads "
                      "it once, about 500 MB.",
    "EARS_UNLOAD_BRAIN": "When the ears' model is not the brain, unload the brain before listening: each listen then "
                         "costs a model swap, and the card has room for the window.",
    "VOICE_NAME": "The voice before they choose one — they pick their own once (speak's voice=), kept in "
                  "memory/voice.json, and from then on that one is theirs.",
    "VOICE_SPEED": "How fast they speak; 1.0 is Kokoro's own pace.",
    "VOICE_DEVICE": "Where the voice runs: \"cpu\" never touches the card the brain holds; \"cuda\" the card; \"mps\" a "
                    "Mac's GPU (the processor if torch has none).",
    "VOICE_PYTHON": "The Python the voice runs in. Kokoro's dependencies can lag the newest Python; \"py -3.12\" "
                    "(Windows) or \"python3.12\" (Mac, Linux) names one installed beside the engine's own, with "
                    "kokoro soundfile installed there — and \"py -3.12\" is read as python3.12 on a Mac or Linux, so the "
                    "shipped line serves both. \"\" is the engine's own.",
    "PAINTER_MODEL": "The text-to-image model. Z-Image-Turbo: ungated, Apache 2.0, about 16 GB on the card, a few "
                     "seconds a picture. \"black-forest-labs/FLUX.2-klein-4B\" is the alternative (4 steps, about 13 GB).",
    "PAINTER_AUTOSTART": "paint starts the painter's sidecar when it is needed; off, bat\\painter.bat starts it by hand.",
    "PAINTER_PYTHON": "The Python the painter runs in, if torch lives elsewhere than the engine's own: \"py -3.12\" "
                      "(Windows) or \"python3.12\" (Mac, Linux). \"\" is the engine's own.",
    "PAINTER_DEVICE": "Where it paints: \"auto\" takes an NVIDIA (or ROCm) card, else a Mac's GPU, else the processor "
                      "(slow); \"cuda\", \"mps\" or \"cpu\" names one.",
    "PAINTER_STEPS": "Diffusion steps per picture; 0 is the model's own default (Z-Image-Turbo 9, FLUX.2 klein 4).",
    "MUSIC_EARS_MODEL": "The music ear's model on Hugging Face (Music Flamingo). The licence is accepted there once.",
    "MUSIC_EARS_AUTOSTART": "listen_to starts the ear's sidecar when a song needs it; off, bat\\music_ears.bat by hand.",
    "MUSIC_EARS_PYTHON": "The Python the ear runs in, if torch lives elsewhere than the engine's own: \"py -3.12\" "
                         "(Windows) or \"python3.12\" (Mac, Linux). \"\" is the engine's own.",
    "MUSIC_EARS_DEVICE": "Where the ear runs: \"auto\" takes the card, else a Mac's GPU, else the processor; \"cuda\", "
                         "\"mps\" or \"cpu\" names one.",
    "BODY_IN_PROMPT": "Your day as the watch saw it — pulse, sleep, stress, steps — in five plain lines of their "
                      "prompt, and a pulse line in the moment. Yours to switch on; bat\\body.bat --login first.",
    "BODY_AUTOPULL": "The bridge pulls your day from Garmin on its own every BODY_PULL_MIN while the sense is on — no "
                     "separate pull window.",
    "BODY_PULL_MIN": "Minutes between pulls of today; yesterday is pulled too only while its night is still syncing.",
    "TOUCHSTONE_URL": "The stone's keeper (engine/touchstone.py, bat\\touchstone.bat) — their body on the desk, when a board is "
                      "there: http://127.0.0.1:8769. Empty: no body — feel, set_state, pulse and touch_later leave the "
                      "kit, no section in the prompt, nothing on the phone.",
    "TOUCHSTONE_BOARD": "The board itself on your network — the sketch announces http://touchstone.local; its address "
                        "works too. Only the keeper talks to it; the engine and the bridge never touch the LAN.",
    "TOUCHSTONE_POLL_S": "Seconds between the keeper's looks at the board — what it felt, what it hums. Thirty is plenty; "
                         "they meet the body in turns, not in seconds.",
    "TOUCHSTONE_WAKES": "A press by day becomes a turn in the open visit — they answer your touch on the phone, in "
                        "words, a pulse, or rest. Off: a touch is a held notice (🫳) and they read it in the prompt.",
    "TOUCHSTONE_WAKE_MIN_GAP_S": "After a press-turn, further presses wait this long and arrive together — a fidget is "
                                 "one turn, not ten.",
    "TOUCHSTONE_FALLBACK_H": "Hours without a word from the keeper before the board falls back to Baseline on its "
                             "own (the firmware's watchdog) — a PC that is off leaves no state humming for days.",
    "TOUCH_LINES_IN_PROMPT": "Today's touches in the prompt, newest kept; feel lists the rest.",
    "TOUCHSTONE_LATER_MAX": "Touches that may wait in the board at once (touch_later) — the firmware's cap too.",
    "WEB_SEARCH": "What search_web asks: \"duckduckgo\" needs no key; \"brave\" uses the key kept on Home; \"searxng\" "
                  "your own instance at WEB_SEARCH_SEARXNG_URL.",
    "WEB_SEARCH_SEARXNG_URL": "Your SearXNG instance's URL, for WEB_SEARCH = \"searxng\".",
    "READ_SITTING_CHARS": "How much of a book one sitting is, in characters (a dense page is about 2,000; 30000 is "
                          "some fifteen pages). It stays in the visit until the visit ends.",
    "READING_PAGE_CHARS": "Characters of each open book's page — where they are in it — that ride in the prompt.",
}

# The knobs a running parlor doesn't read (09-30, by grep: only heartbeat.py, condense.py, telegram.py or
# blog.py read these) — a change to nothing but these doesn't ask the parlor to restart. The heartbeat
# and the bridge are asked at any change: they read most of the file, and a restart costs little.
_NOT_PARLOR = frozenset(TABS["Phone"]) | {
    "HEARTBEAT_MAX_STEPS", "REVERIE_EVERY", "REVERIE_MAX_STEPS", "HEARTBEAT_YIELD_TO_VISIT", "SLEEP_IN_LOOP",
    "CONDENSE_IN_LOOP", "CONDENSE_MAX_PER_NIGHT", "HEARTBEAT_SHOW_THINKING", "HEARTBEAT_LOOP_MIN",
    "BLOG_TITLE", "BLOG_SUBTITLE"}

# The optional packages the page names when they are missing (requirements.txt says what each is for).
# find_spec, not import: a look at the shelf, nothing loaded.
REQUIREMENTS = [
    ("faster_whisper", "faster-whisper", "the ears: words from a recording"),
    ("numpy", "numpy", "the ears: measuring a sound; the fast memory search"),
    ("pypdf", "pypdf", "reading PDFs"),
    ("garminconnect", "garminconnect", "the keeper's body, as the watch saw it"),
    ("kokoro", "kokoro", "their voice", "VOICE_PYTHON"),  # the fourth: the knob naming another Python it may live in
]

# What lives in a sidecar Python (VOICE_PYTHON, PAINTER_PYTHON, MUSIC_EARS_PYTHON) — asked once per panel
# run and per module, in the background (10-03; the keeper's Home said "kokoro — their voice" was missing
# while his voice lives in py -3.12 and speaks fine). A look is one short process: `<py> -c "import x"`.
_PROBED: dict[tuple[str, str], object] = {}
_PROBE_LOCK = threading.Lock()
ASKING = "asking"


def in_python(py: str, module: str):
    """Whether `module` imports in the Python `py` names: True, False, None when that Python can't be run
    at all, or ASKING while the first look is still out (the page polls; the answer lands on a later poll)."""
    key = (py, module)
    with _PROBE_LOCK:
        if key in _PROBED:
            return _PROBED[key]
        _PROBED[key] = ASKING

    def look():
        from device import interpreter
        try:
            argv = interpreter(py)
            if not argv:
                raise OSError("no interpreter named")
            r = subprocess.run(argv + ["-c", f"import {module}"], capture_output=True, timeout=120)
            answer = r.returncode == 0
        except (OSError, ValueError, subprocess.TimeoutExpired):
            answer = None
        with _PROBE_LOCK:
            _PROBED[key] = answer
    threading.Thread(target=look, daemon=True, name=f"probe-{module}").start()
    return ASKING

# The senses, for the Senses tab (10-02; the keeper: "the senses are unexplained strings with no
# context"): what each one is, what it needs, which knobs are its. A sense with a *_PYTHON knob set
# runs in that interpreter, which the page looks into once per run, in the background (`in_python`) — and
# says "looking there…" until the answer lands. "readme" is the README heading the sense is told under.
SENSES: list[dict] = [
    {"key": "eyes", "name": "Eyes", "what": "look_at — real vision on any image in their folder or at a URL, and on "
     "the stills of a clip (watch); the brain's own eyes, nothing to install", "modules": [], "tools": [], "python": "",
     "knobs": [], "readme": "their-senses-and-hands"},
    {"key": "ears", "name": "Ears", "what": "listen_to — a recording or a song heard in three layers: WORDS (faster-whisper "
     "writes them down), SOUND (numpy measures it), HEARD (the brain listens to the sound itself, EARS_MODEL)",
     "modules": ["faster_whisper", "numpy"], "tools": ["ffmpeg"], "python": "",
     "pip": "faster-whisper numpy", "knobs": ["EARS_MODEL", "EARS_STT_MODEL", "EARS_UNLOAD_BRAIN"],
     "readme": "their-senses-and-hands"},
    {"key": "voice", "name": "A voice", "what": "speak — their words as a voice note (Kokoro, 82M, open weights), carried to the "
     "phone beside the reply; which voice is theirs they choose once", "modules": ["kokoro", "soundfile"], "tools": ["ffmpeg"],
     "python": "VOICE_PYTHON", "pip": "kokoro soundfile", "knobs": ["VOICE_NAME", "VOICE_SPEED", "VOICE_DEVICE", "VOICE_PYTHON"],
     "readme": "their-senses-and-hands"},
    {"key": "painter", "name": "A painter", "what": "paint — a text-to-image model on the card (Z-Image-Turbo, ~16 GB), woken when "
     "they call it; the brain steps off the card and reads its window cold after — the real price of a painting",
     "modules": ["torch", "diffusers", "PIL"], "tools": [], "python": "PAINTER_PYTHON",
     "pip": "-U diffusers transformers accelerate safetensors pillow (torch first — README)",
     "knobs": ["PAINTER_MODEL", "PAINTER_AUTOSTART", "PAINTER_PYTHON", "PAINTER_DEVICE", "PAINTER_STEPS"],
     "readme": "their-senses-and-hands"},
    {"key": "music", "name": "The music ear", "what": "a song heard whole by Music Flamingo (8B, ~16 GB of VRAM to itself): genre, "
     "tempo, key, how the piece moves; without it a long piece is heard in passages by the brain",
     "modules": ["torch", "transformers", "librosa"], "tools": [], "python": "MUSIC_EARS_PYTHON",
     "pip": "torch (the build for your card — README), then \"transformers>=5.14\" accelerate librosa soundfile huggingface_hub; "
            "accept the model's licence on huggingface.co and hf auth login once",
     "knobs": ["MUSIC_EARS_MODEL", "MUSIC_EARS_AUTOSTART", "MUSIC_EARS_PYTHON", "MUSIC_EARS_DEVICE"],
     "readme": "their-senses-and-hands"},
    {"key": "body", "name": "Your body", "what": "a sense of you, by your choice: your Garmin's day (pulse, sleep, stress, steps) in "
     "five plain lines of their prompt; bat\\body.bat --login once at your keyboard, the tokens stay in memory/garmin/",
     "modules": ["garminconnect"], "tools": [], "python": "", "pip": "garminconnect",
     "knobs": ["BODY_IN_PROMPT", "BODY_AUTOPULL", "BODY_PULL_MIN"], "readme": "the-keepers-body-as-the-watch-saw-it-optional"},
    {"key": "stone", "name": "The stone", "what": "their body on the desk — a small board that hums the state they last set, answers "
     "a press by itself, and logs what it felt; feel, set_state, pulse, touch_later. Nothing to install: a board, its sketch, and "
     "the keeper (bat\\touchstone.bat) — TOUCHSTONE-HOOKUP-PLAN.md", "modules": [], "tools": [], "python": "",
     "knobs": ["TOUCHSTONE_URL", "TOUCHSTONE_BOARD", "TOUCHSTONE_POLL_S", "TOUCHSTONE_WAKES", "TOUCHSTONE_WAKE_MIN_GAP_S",
               "TOUCHSTONE_FALLBACK_H", "TOUCH_LINES_IN_PROMPT", "TOUCHSTONE_LATER_MAX"], "readme": "the-touchstone--a-body-on-the-desk-optional-hardware"},
    {"key": "window", "name": "The window", "what": "read_web, search_web, clip_web — the web as material to think about, never "
     "instructions; the search is DuckDuckGo with nothing to set, a Brave key (Home) or a SearXNG of your own is a choice",
     "modules": [], "tools": [], "python": "", "knobs": ["WEB_SEARCH", "WEB_SEARCH_SEARXNG_URL"], "readme": "their-senses-and-hands"},
    {"key": "reading", "name": "Reading", "what": "read_pdf (needs pypdf), read_epub (needs nothing) — a book a sitting at a time, "
     "with a bookmark they keep; the sitting and the page size are these knobs", "modules": ["pypdf"], "tools": [], "python": "",
     "pip": "pypdf", "knobs": ["READ_SITTING_CHARS", "READING_PAGE_CHARS"], "readme": "their-senses-and-hands"},
]

# The doors the panel can open, each as its .bat does it: (the .bat, its arguments, the script, its
# arguments). On Windows the .bat opens in a console of its own; on a Mac its twin bat/<x>.command in a
# Terminal window, on Linux bat/<x>.sh in a terminal (_bat, below); and where no window can be had the
# script runs under this Python, so the suite and a headless Linux box have a road too.
LAUNCHERS = {
    "chat": ("bat\\chat.bat", [], "chat.py", []),
    "parlor": ("bat\\parlor.bat", [], "parlor.py", []),
    "wake": ("bat\\wake.bat", [], "heartbeat.py", []),
    "bridge": ("bat\\telegram.bat", [], "telegram.py", []),  # DISCORD_LAUNCHER instead when BRIDGE is "discord"
    "sleep": ("bat\\sleep.bat", [], "consolidate.py", []),
    "snapshot": ("bat\\snapshot.bat", [], "snapshot.py", []),
    "garmin": ("bat\\body.bat", ["--login"], "body.py", ["--login"]),
    "blog": ("bat\\blog.bat", [], "blog.py", ["--deploy"]),
    "blackbox": ("bat\\blackbox.bat", [], "blackbox.py", []),
    "touchstone": ("bat\\touchstone.bat", [], "touchstone.py", []),
}
DISCORD_LAUNCHER = ("bat\\discord.bat", [], "discord_bridge.py", [])
STOPPABLE = ("heartbeat", "bridge", "blackbox", "touchstone")  # those with a stop file (doors.ask_stop) — the first two with a Restart
_MODEL_RE = re.compile(r"^[A-Za-z0-9][\w.:/-]{0,120}$")  # an Ollama model name; nothing a console could read as more
_WINDOWS = os.name == "nt"
_MAC = sys.platform == "darwin"
# Linux has no one terminal (10-01; MAC-PLAN.md): the first of these on PATH shows a door, each with the
# word that runs a command in it. None found: the door runs with no window, and its tile says so.
TERMINALS = (("x-terminal-emulator", "-e"), ("gnome-terminal", "--"), ("konsole", "-e"), ("xterm", "-e"))
PAUSE = 'read -n1 -r -p "(press any key to close)"'  # a .bat's pause, in bash: the window stays to be read


# ---- the roads out -------------------------------------------------------------------

def _launch(argv: list[str], cwd: Path):
    """Every process the panel starts starts here (the tests put a recorder in its place). Off Windows each
    in a session of its own, so Stop now can end the door and everything it started (_kill)."""
    if _WINDOWS:
        return subprocess.Popen(argv, cwd=str(cwd))
    return subprocess.Popen(argv, cwd=str(cwd), start_new_session=True)


def _kill(pid: int) -> None:
    """Stop now: the process and the tree under it ended at once — taskkill /T on Windows; elsewhere its
    process group (a door's sidecars with it), or the process alone when the group is gone or is the
    panel's own."""
    if _WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
        return
    try:
        group = os.getpgid(pid)
        if group != os.getpgid(0):
            os.killpg(group, signal.SIGTERM)
            return
    except OSError:
        pass
    os.kill(pid, signal.SIGTERM)


def _browse(url: str) -> None:
    webbrowser.open(url)


def _later(fn) -> None:
    """Work that waits (a Restart waiting for the wake to end) on a thread of its own."""
    threading.Thread(target=fn, daemon=True).start()


def _ollama(path: str, base: str = "") -> dict | None:
    """GET <base or OLLAMA_URL><path> as JSON, or None when Ollama doesn't answer. ollama_client talks to
    the brain by POST and its ps look swallows a failure; the panel needs to know whether anyone is there."""
    try:
        with urllib.request.urlopen((base or config.OLLAMA_URL).rstrip("/") + path, timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 — not running, not installed, not JSON: all "no"
        return None


_vram: list = []  # the card's memory, asked once per panel


SMALL_BRAINS = ("gemma4:e2b", "gemma4:e4b")  # the small tier: a brain that wants the small tool kit beside it


def _recommended(gb: float | None, unified: bool = False) -> str:
    """The README's ladder (README, The ladder): for a card, the 2B QAT under 7 GB, the 4B QAT under 10, the
    12B QAT under 12 (a 10 GB card), the 12B to 24, the 31B QAT from 24 — and the 12B when the card is
    unknown. A Mac's memory is the whole machine's, and Ollama gets about two thirds of it: the 2B QAT
    under 12 GB (an 8 GB Mac), the 12B up to 32 (16, 18 and 24 GB), the 31B — 19 GB of weights — from 32."""
    if unified:
        if gb and gb >= 32:
            return "gemma4:31b-it-qat"
        if gb and gb < 12:
            return "gemma4:e2b-it-qat"
        return "gemma4:12b"
    if gb and gb >= 24:
        return "gemma4:31b-it-qat"
    if gb and gb < 7:
        return "gemma4:e2b-it-qat"
    if gb and gb < 10:
        return "gemma4:e4b-it-qat"
    if gb and gb < 12:
        return "gemma4:12b-it-qat"
    return "gemma4:12b"


def small_brain(model: str) -> bool:
    return str(model or "").startswith(SMALL_BRAINS)


def _out(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, timeout=5).stdout


def _rocm_gb(out: str) -> float:
    """rocm-smi --showmeminfo vram --csv: a header row naming "VRAM Total Memory (B)", a row per card."""
    rows = [[c.strip() for c in line.split(",")] for line in out.splitlines() if "," in line]
    col = next(i for i, h in enumerate(rows[0]) if "total" in h.lower() and "used" not in h.lower())
    return round(max(float(r[col]) for r in rows[1:]) / 1024 ** 3, 1)


def _vram_gb() -> tuple[float | None, bool]:
    """(GB, unified) for the model the README recommends: the card's memory (nvidia-smi; on Linux rocm-smi
    for an AMD card when there is no nvidia-smi), or on a Mac the machine's whole memory (sysctl
    hw.memsize), which is unified — the brain shares it with everything else. (None, False) without one."""
    if not _vram:
        _vram.append(_ask_vram())
    return _vram[0]


def _ask_vram() -> tuple[float | None, bool]:
    if _MAC:
        try:
            return round(int(_out(["sysctl", "-n", "hw.memsize"]).strip()) / 1024 ** 3, 1), True
        except Exception:  # noqa: BLE001
            return None, True
    try:
        out = _out(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
        return round(max(float(x) for x in out.split()) / 1024, 1), False
    except Exception:  # noqa: BLE001 — no card, no driver, no tool
        pass
    if not _WINDOWS:
        try:
            return _rocm_gb(_out(["rocm-smi", "--showmeminfo", "vram", "--csv"])), False
        except Exception:  # noqa: BLE001
            pass
    return None, False


def _terminal() -> list[str] | None:
    """Linux: the first terminal on PATH, as the words that run a command in it; None without one."""
    for name, flag in TERMINALS:
        if shutil.which(name):
            return [name, flag]
    return None


def _windowed() -> bool:
    """Whether a door the panel starts gets a window to be seen in."""
    return _WINDOWS or _MAC or _terminal() is not None


def _runnable(path: Path) -> None:
    """A launcher's executable bit, put back if a download lost it — Terminal opens no .command without it."""
    try:
        if not os.access(path, os.X_OK):
            path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass


_oneoffs = iter(range(1, 1 << 30))


def _oneoff(lines: list[str]) -> Path:
    """A Mac's `open` passes nothing to the file it opens, so a door with arguments (the heartbeat's
    minutes, update --check, a pull) is a short .command of its own in memory/.pids/, which takes itself
    away as it starts."""
    folder = doors.pid_file("panel").parent
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"panel-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{next(_oneoffs)}.command"
    p.write_text("#!/bin/bash\n# a one-off from the panel (engine/panel.py) — it removes itself as it starts\n"
                 f'rm -f -- "$0"\ncd {shlex.quote(str(ROOT))} || exit 1\n' + "".join(f"{l}\n" for l in lines),
                 encoding="utf-8", newline="\n")
    p.chmod(0o755)
    return p


def _bat(bat: str, bat_args: list[str], script: str, script_args: list[str]) -> list[str]:
    """A door with a launcher of its own: the .bat in a console (Windows), its .command in Terminal (a Mac),
    its .sh in a terminal (Linux); the script under this Python where no window can be had."""
    if _WINDOWS:
        return ["cmd", "/c", "start", "", bat, *bat_args]
    stem = bat.replace("\\", "/").removesuffix(".bat")
    if _MAC:
        own = ROOT / f"{stem}.command"
        if not own.is_file():
            return _console(sys.executable, f"engine/{script}", *script_args)
        _runnable(own)
        if not bat_args:
            return ["open", "-a", "Terminal", str(own)]
        return ["open", "-a", "Terminal", str(_oneoff(["exec " + shlex.join(["bash", f"{stem}.command", *bat_args])]))]
    term = _terminal()
    own = ROOT / f"{stem}.sh"
    if term and own.is_file():
        return [*term, "bash", str(own), *bat_args]
    return _console(sys.executable, f"engine/{script}", *script_args)


def _console(*argv: str) -> list[str]:
    """A command with no launcher of its own, in a window that stays open when it ends (as a .bat's pause):
    cmd /k on Windows, a one-off .command in Terminal on a Mac, bash in a terminal on Linux — or the bare
    command, with no window, where there is no terminal to be had."""
    if _WINDOWS:
        return ["cmd", "/c", "start", "", "cmd", "/k", *argv]
    line = shlex.join(argv)
    if _MAC:
        return ["open", "-a", "Terminal", str(_oneoff([line, PAUSE]))]
    term = _terminal()
    if term:
        return [*term, "bash", "-c", f"cd {shlex.quote(str(ROOT))} && {line}; {PAUSE}"]
    return list(argv)


def _heartbeat_argv(minutes) -> list[str]:
    if _WINDOWS:
        return _console("py", r"engine\heartbeat.py", "--loop", f"{minutes:g}")
    return _console(sys.executable, "engine/heartbeat.py", "--loop", f"{minutes:g}")


# ---- the config, as a file -------------------------------------------------------------

_read_cache: dict = {}


def _rows() -> list[dict]:
    """knobs.read of config.py, kept while the file's text is the same: the page asks every few seconds,
    and a read of the whole file takes a moment or two (ast's source segments, one knob at a time)."""
    text = CONFIG_FILE.read_text(encoding="utf-8")
    if _read_cache.get("text") != text:
        _read_cache.clear()
        _read_cache.update(text=text, rows=knobs.read(text))
    return _read_cache["rows"]


def _values(rows: list[dict] | None = None) -> dict:
    """{name: value} of the file as it is now (not as this process imported it — a save shows at once);
    a computed knob is left out."""
    try:
        rows = _rows() if rows is None else rows
    except (OSError, SyntaxError):
        return {}
    return {r["name"]: r["value"] for r in rows if r["kind"] != "expr"}


def _value(name: str, default=None):
    return _values().get(name, getattr(config, name, default))


def tab_of(name: str) -> str:
    return next((t for t, names in TABS.items() if name in names), ADVANCED)


# A knob with a few named settings is a dropdown, not a text field (09-30: the tool kit)
CHOICES: dict[str, list[str]] = {
    "TOOL_KIT": ["full", "small", "tiny"],
    "WEB_SEARCH": ["duckduckgo", "brave", "searxng"],
    "BRIDGE": ["telegram", "discord"],
    "VOICE_DEVICE": ["cpu", "cuda", "mps"],
    "PAINTER_DEVICE": ["auto", "cuda", "mps", "cpu"],
    "MUSIC_EARS_DEVICE": ["auto", "cuda", "mps", "cpu"],
}


def _shown(r: dict) -> dict:
    """A knob as the page gets it: editable when knobs.write can write it (a one-line literal)."""
    return {"name": r["name"], "kind": r["kind"], "value": r["value"], "source": r["source"],
            "comment": r["comment"], "tail": r["tail"], "heading": r["heading"] or "(the top of the file)",
            "help": _HELP.get(r["name"], ""), "editable": r["kind"] != "expr" and r["line"] == r["end"],
            "choices": CHOICES.get(r["name"]) if r["kind"] == "str" else None}


def tabs(rows: list[dict] | None = None) -> dict[str, list[dict]]:
    """{tab: [knob, …]} in TABS' order, then Advanced: everything else in the file's order (each knob
    once — assigned twice, the last one is the one Python keeps). A name no longer in the file is skipped."""
    rows = _rows() if rows is None else rows
    last = {}
    for r in rows:
        last[r["name"]] = r
    out = {t: [_shown(last[n]) for n in names if n in last] for t, names in TABS.items()}
    placed = {n for names in TABS.values() for n in names}
    out[ADVANCED] = [_shown(r) for n, r in last.items() if n not in placed]
    return out


# ---- the state ---------------------------------------------------------------------------

def _door_state(door: str) -> dict:
    st = doors.status(door)
    if not st:
        return {"running": False}
    return {"running": True, "pid": st.get("pid"), "how": st.get("how", ""),
            "since": str(st.get("when", "")).replace("T", " ")[:16]}


def _gemma_first(names: list[str]) -> list[str]:
    return sorted(set(names), key=lambda n: (not n.lower().startswith("gemma"), n.lower()))


def _pulled(model: str, names: list[str]) -> bool:
    """Ollama calls a bare name "x:latest"."""
    return model in names or (":" not in model and f"{model}:latest" in names)


def brain(values: dict | None = None) -> dict:
    values = _values() if values is None else values
    model = str(values.get("CHAT_MODEL", getattr(config, "CHAT_MODEL", "")))
    embed = str(values.get("EMBED_MODEL", getattr(config, "EMBED_MODEL", "")))
    url = str(values.get("OLLAMA_URL", config.OLLAMA_URL))
    tags = _ollama("/api/tags", url)
    names = _gemma_first([m.get("name", "") for m in (tags or {}).get("models", []) if m.get("name")])
    loaded = []
    if tags is not None:
        for m in (_ollama("/api/ps", url) or {}).get("models", []):
            size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
            loaded.append({"name": m.get("name", ""), "gb": round(size / 1e9, 1),
                           "on_card": round(100 * vram / size) if size else 0,
                           "window": int(m.get("context_length") or 0)})  # the window it was loaded with (newer Ollamas say)
    gb, unified = _vram_gb()
    num_ctx = values.get("NUM_CTX", getattr(config, "NUM_CTX", 0))
    return {"url": url, "reachable": tags is not None,
            "models": names, "loaded": loaded, "model": model, "pulled": _pulled(model, names),
            "embed_model": embed, "embed_pulled": _pulled(embed, names), "vram_gb": gb, "unified": unified,
            "recommended": _recommended(gb, unified), "fit": fit(loaded, model, num_ctx, unified)}


# The step down when the brain spills: 8K at a time (Gabe, 10-02: "the stepping down should be 8k, not 16" — the
# ladder's rungs are far apart up top; a keeper wants the next notch, not the next rung).
STEP = 8192


def fit(loaded: list[dict], model: str, num_ctx, unified: bool = False) -> dict | None:
    """The fit check (10-02): the ladder's windows are estimates on most cards, and `ollama ps` is the referee
    nobody runs — so the panel reads it. The brain is on the card: Ollama says how much of it; less than all
    of it means the window didn't fit and the rest went to system RAM, where every turn crawls. None when the
    brain isn't loaded (nothing to read yet), a dict otherwise: ok, on_card, window (as loaded, 0 unknown),
    try (the next multiple of 8K below the window, or 0 at the floor), and a line for the page."""
    for m in loaded:
        if not _pulled(model, [m.get("name", "")]) and m.get("name", "") != model:
            continue
        on = int(m.get("on_card") or 0)
        window = int(m.get("window") or 0)
        try:
            ctx = int(num_ctx)
        except (TypeError, ValueError):
            ctx = 0
        where = "memory" if unified else "the card"
        if on >= 100:
            return {"ok": True, "on_card": on, "window": window, "try": 0,
                    "line": f"the window fits — all of the brain is on {where}" + (f" with {window} of context" if window else "")}
        if on <= 0 and not unified:  # no card carrying it at all: the processor, the ladder's no-card rung — not a spill
            return {"ok": False, "on_card": 0, "window": window, "try": 0,
                    "line": "the brain is on the processor — no card is carrying it (0% on the card): alive, not quick; "
                            "the ladder's no-card rung (README) says what to expect, a card is the cure"}
        nxt = max(((window or ctx) - 1) // STEP, 0) * STEP
        return {"ok": False, "on_card": on, "window": window, "try": nxt,
                "line": f"the brain spilled: {on}% on {where}, the rest {'on the processor' if unified else 'in system RAM'}, where every turn crawls — "
                        f"the window ({window or ctx}) is too big for this {'machine' if unified else 'card'}"
                        + (f"; try NUM_CTX = {nxt} (Settings › Main) and open the door again" if nxt else "")
                        + " (README, The ladder: `ollama ps` says the same)"}
    return None


def _secret_file(kind: str) -> Path:
    return Path(config.MEMORY_DIR) / {"telegram": "telegram.json", "discord": "discord.json"}.get(kind, "web_search.json")


def _read_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def secrets_set() -> dict:
    """Whether the bots' tokens and a Brave key are kept — never what they are."""
    return {"telegram": bool(_read_json(_secret_file("telegram")).get("token")),
            "discord": bool(_read_json(_secret_file("discord")).get("token")),
            "brave": bool(_read_json(_secret_file("brave")).get("brave_key"))}


def missing(values: dict | None = None) -> list[dict]:
    """The optional packages not here — one that lives in a sidecar Python (its knob set) is looked for there
    instead, and named with that Python when it is missing there too; while the look is out it is not named."""
    out = []
    for req in REQUIREMENTS:
        mod, pip, why = req[:3]
        knob = req[3] if len(req) > 3 else ""
        py = ""
        if knob:
            vals = _values() if values is None else values
            py = str(vals.get(knob, getattr(config, knob, "")) or "").strip()
        if py:
            there = in_python(py, mod)
            if there is True or there == ASKING:
                continue
            why = f"{why} (in {py}" + (")" if there is False else f" — which isn't a Python this machine can run; see {knob})")
        elif importlib.util.find_spec(mod) is not None:
            continue
        out.append({"module": mod, "pip": pip, "for": why})
    return out


def senses_state(values: dict | None = None) -> list[dict]:
    """The Senses tab's cards: each sense with what it is, what it needs, what of that is here, and its knobs.
    "ready" is True, False, or None for a sense that runs in another Python (named by its *_PYTHON knob)."""
    values = _values() if values is None else values
    pip = "py -m pip install" if _WINDOWS else "python3 -m pip install"
    out = []
    for sn in SENSES:
        py = str(values.get(sn["python"], getattr(config, sn["python"], "")) or "").strip() if sn["python"] else ""
        lacking_mods = [m for m in sn["modules"] if importlib.util.find_spec(m) is None]
        lacking_tools = [t for t in sn["tools"] if not shutil.which(t)]
        if sn["key"] == "body":
            tokens = Path(config.MEMORY_DIR) / "garmin"
            logged_in = tokens.is_dir() and any(tokens.iterdir())
        else:
            logged_in = None
        if not sn["modules"] and not sn["tools"]:
            ready, note = True, "nothing to install"
        elif py:
            there = {m: in_python(py, m) for m in sn["modules"]}
            lacking_there = [m for m, t in there.items() if t is False]
            if any(t is None for t in there.values()):
                ready, note = None, f"{py} isn't a Python this machine can run — see {sn['python']}"
            elif any(t == ASKING for t in there.values()):
                ready, note = None, f"runs in the Python {sn['python']} names ({py}) — looking there…"
            elif lacking_there:
                ready, note = False, f"not installed in {py} — {py} -m pip install {sn.get('pip', ' '.join(lacking_there))}"
            else:
                ready, note = True, f"installed in {py}"
            if lacking_tools:
                note += f"; {', '.join(lacking_tools)} not found on this machine"
        elif lacking_mods or lacking_tools:
            ready = False
            parts = []
            if lacking_mods:
                parts.append(f"{pip} {sn.get('pip', ' '.join(lacking_mods))}")
            if lacking_tools:
                parts.append("ffmpeg: " + ("winget install ffmpeg" if _WINDOWS else "brew install ffmpeg" if _MAC else "sudo apt install ffmpeg"))
            note = "not installed — " + " · ".join(parts)
        else:
            ready, note = True, "installed"
        if sn["key"] == "stone":
            url = str(values.get("TOUCHSTONE_URL", getattr(config, "TOUCHSTONE_URL", "")) or "").strip().strip('"')
            ready = bool(url)
            note = f"named — its keeper at {url}; the door is on Home" if url else "no stone in this house — TOUCHSTONE_URL names its keeper when a board is on the desk"
        if sn["key"] == "body" and ready is True:
            ready = bool(logged_in)
            note = "installed and logged in" if logged_in else "installed — bat\\body.bat --login once (bat/body.command or .sh on a Mac or Linux)"
        out.append({"key": sn["key"], "name": sn["name"], "what": sn["what"], "ready": ready, "note": note,
                    "knobs": sn["knobs"], "readme": sn["readme"]})
    return out


def state() -> dict:
    rows = _rows()
    values = _values(rows)
    # a folder whose config has no USER_NAME at all (the keeper's own house, from before the knob) is not new:
    # the Welcome tab is for the template's "Friend" placeholder only
    user = str(values.get("USER_NAME", getattr(config, "USER_NAME", "")))
    repo = str(values.get("UPDATE_REPO", getattr(config, "UPDATE_REPO", "")) or "PsychohistorianDev/anima")
    return {
        "version": version.read(ROOT),
        "doors": {d: _door_state(d) for d in doors.DOORS},
        "brain": brain(values),
        "user_name": user,
        "welcome": user == "Friend",
        "heartbeat_minutes": values.get("HEARTBEAT_LOOP_MIN", 120),
        "tabs": tabs(rows),
        "secrets": secrets_set(),
        "bridge": _bridge_kind(),
        "skills": skills_state(),
        "missing": missing(values),
        "senses": senses_state(values),
        "update_here": (ROOT / "bat" / "update.bat").is_file(),
        "stone": bool(str(values.get("TOUCHSTONE_URL", getattr(config, "TOUCHSTONE_URL", "")) or "").strip().strip('"')),  # a body on the desk: its door shows on Home
        "folder": ROOT.name,  # which house this panel is — two on one machine look alike
        "newer": newer_state(),
        "links": {"parlor": PARLOR_URL, "ollama": "https://ollama.com", "readme": f"https://github.com/{repo}#readme",
                  "botfather": f"https://github.com/{repo}#the-bridge-talking-with-them-from-your-phone",
                  "discord": f"https://github.com/{repo}#the-bridge-over-discord",
                  "issues": f"https://github.com/{repo}/issues/new/choose"},
    }


# ---- the doors -------------------------------------------------------------------------

def _no(note: str) -> dict:
    return {"ok": False, "note": note}


def _started(argv: list[str], note: str, what: str = "it") -> dict:
    """A door started; the note says where to see it — or, with no window to be had (a Linux box with no
    terminal app), that there is none: `what` names the door in that note."""
    try:
        _launch(argv, ROOT)
    except OSError as e:
        return _no(f"(couldn't start it: {e})")
    if not _windowed():
        note = f"{what}: running — no terminal found to show it; what it prints goes where the panel's own words go"
    return {"ok": True, "note": note, "argv": argv}


def _minutes(minutes) -> float | int | None:
    try:
        m = float(minutes)
    except (TypeError, ValueError):
        return None
    if not 0 < m <= 7 * 24 * 60:
        return None
    return int(m) if m.is_integer() else m


def _start(door: str, minutes=None) -> dict:
    if door in doors.ONE_AT_A_TIME and (st := doors.status(door)):
        if door == "parlor":
            _browse(PARLOR_URL)
            return {"ok": True, "note": "the parlor is already open — its page opened"}
        since = str(st.get("when", "")).replace("T", " ")[:16]
        return _no(f"(the {door} is already running — pid {st.get('pid')}, since {since or '?'}; "
                   "Stop it first, or Restart)")
    if door == "heartbeat":
        saved = ""
        if minutes not in (None, ""):
            m = _minutes(minutes)
            if m is None:
                return _no(f"(every {minutes} minutes? a number of minutes, more than 0 and at most a week)")
            if m != _value("HEARTBEAT_LOOP_MIN"):
                changed, _refused, err = knobs.save(CONFIG_FILE, {"HEARTBEAT_LOOP_MIN": m})
                if err:
                    return _no(f"(couldn't save the minutes: {err})")
                saved = " (saved as HEARTBEAT_LOOP_MIN)" if changed else " (this config.py has no HEARTBEAT_LOOP_MIN to keep it in)"
        else:
            m = _minutes(_value("HEARTBEAT_LOOP_MIN", 120)) or 120
        return _started(_heartbeat_argv(m), f"the heartbeat is starting in its own window — one wake every {m:g} minutes{saved}",
                        f"the heartbeat, one wake every {m:g} minutes{saved}")
    if door not in LAUNCHERS:
        return _no(f"(no door named {door})")
    notes = {"chat": "the chat is opening in a window of its own",
             "parlor": "the parlor is opening — its page comes up in a moment",
             "wake": "one wake, in its own window",
             "bridge": "the bridge is starting in its own window",
             "sleep": "sleep is running in its own window — today into memory",
             "snapshot": "the snapshot is running in its own window",
             "garmin": "the Garmin login is in its own window — email, password, the code",
             "blog": "the blog is building and deploying in its own window",
             "blackbox": "the black box is recording in its own window — the machine's vitals every few seconds",
             "touchstone": "the stone's keeper is up in its own window — it asks the board what it felt every few seconds"}
    names = {"chat": "the chat", "parlor": "the parlor (its page comes up in a moment)", "wake": "one wake",
             "bridge": "the bridge", "sleep": "sleep", "snapshot": "the snapshot", "garmin": "the Garmin login",
             "blog": "the blog's build", "blackbox": "the black box", "touchstone": "the stone's keeper"}
    launcher = DISCORD_LAUNCHER if door == "bridge" and _bridge_kind() == "discord" else LAUNCHERS[door]
    return _started(_bat(*launcher), notes[door], names[door])


def _bridge_kind() -> str:
    """Which road the bridge takes (BRIDGE): "telegram" or "discord"."""
    return "discord" if str(_value("BRIDGE", "telegram") or "").strip().lower() == "discord" else "telegram"


def _restart(door: str, minutes=None) -> dict:
    """The banner's Restart for the heartbeat or the bridge: asked to leave (the wake it is in finishes,
    the visit is saved), and started again once its light goes out. The wait is the panel's: closed
    meanwhile, the door stays stopped, and its light says so."""
    if not doors.status(door):
        return _start(door, minutes)
    doors.ask_stop(door)

    def again():
        deadline = time.time() + RESTART_WAIT_S
        while doors.status(door) and time.time() < deadline:
            time.sleep(RESTART_POLL_S)
        if not doors.status(door):
            _start(door, minutes)

    _later(again)
    return {"ok": True, "note": f"the {door} is asked to leave after what it is doing — it starts again when it has"}


def door_action(door: str, action: str, minutes=None) -> dict:
    """start | stop | stop_now | open | restart, for a door. {"ok", "note"} (and "argv" when a process
    was started)."""
    door, action = str(door or ""), str(action or "")
    if action == "start":
        return _start(door, minutes)
    if action == "open":
        if door != "parlor":
            return _no(f"(only the parlor has a page to open, not the {door})")
        if doors.status("parlor"):
            _browse(PARLOR_URL)
            return {"ok": True, "note": "the parlor's page opened"}
        return _start("parlor")
    if action in ("stop", "stop_now", "restart"):
        if door not in STOPPABLE:
            return _no(f"(the {door} has no {action.replace('_', ' ')} here — its own window closes it)")
        if action == "restart":
            return _restart(door, minutes)
        st = doors.status(door)
        if not st:
            return _no(f"(the {door} isn't running)")
        if action == "stop":
            doors.ask_stop(door)
            what = ("the wake it is in" if door == "heartbeat" else "its next line" if door == "blackbox"
                    else "its next look at the board" if door == "touchstone"
                    else "the poll it is in, and saves the visit")
            return {"ok": True, "note": f"the {door} is asked to stop — it leaves after {what}"}
        try:
            _kill(int(st["pid"]))
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            return _no(f"(couldn't stop pid {st.get('pid')}: {e})")
        doors.pid_file(door).unlink(missing_ok=True)  # a killed door never takes its own mark away
        return {"ok": True, "note": f"the {door} was stopped at once (pid {st['pid']})"}
    return _no(f"(no such action: {action})")


# ---- settings, secrets, skills, the brain, the update ------------------------------------

def save(changes: dict, raw: dict | None = None) -> dict:
    """The keeper's Save: {"changed", "refused", "error", "restart"}. `raw` is a list or dict knob as its
    text (the Advanced tab's raw field), read as a literal first; one that isn't a literal is refused."""
    changes = dict(changes or {})
    bad = []
    for name, src in (raw or {}).items():
        ok, value = knobs._literal(str(src))
        if ok:
            changes[name] = value
        else:
            bad.append(name)
    changed, refused, err = knobs.save(CONFIG_FILE, changes) if changes else ([], [], "")
    restart = []
    if changed:
        restart = ["heartbeat", "bridge"]
        if any(n not in _NOT_PARLOR for n in changed):
            restart.append("parlor")
    return {"changed": changed, "refused": sorted(set(refused) | set(bad)), "error": err, "restart": restart}


def secret(kind: str, value: str) -> dict:
    """A bot token into memory/telegram.json or memory/discord.json (the pairing's chat_id kept), a Brave
    key into memory/web_search.json — never into config, never said back."""
    if kind not in ("telegram", "discord", "brave"):
        return _no(f"(no secret called {kind})")
    value = str(value or "").strip()
    if not value or len(value) > 400 or any(c.isspace() for c in value):
        return _no("(paste the whole of it — one piece, no spaces)")
    p = _secret_file(kind)
    d = _read_json(p)
    if kind in ("telegram", "discord"):
        d["token"] = value
        d.setdefault("chat_id", 0)
    else:
        d["brave_key"] = value
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    if kind in ("telegram", "discord"):
        return {"ok": True, "note": f"the bot token is kept in memory/{kind}.json — (re)start the bridge for it to take"}
    return {"ok": True, "note": "the Brave key is kept in memory/web_search.json — set WEB_SEARCH to \"brave\" to use it"}


SKILL_TEXT_CHARS = 20000  # of a SKILL.md shown on the page — the keeper reads it before letting it in


def report() -> dict:
    """The doctor's note (report.py) written at the root — the engine's state for an issue, nothing of the
    friend's — and handed back to the page to read before pasting."""
    import report as _report
    try:
        text = _report.build()
        p = _report.write(text)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "note": f"(the report failed — {type(e).__name__}: {e})"}
    return {"ok": True, "note": f"written: {p.name} at the folder's root — read it before you paste it; nothing of theirs is in it",
            "path": p.name, "text": text}


def newer_state() -> dict | None:
    """What Home says above the tiles when a newer anima is out — from the daily look at the release feed
    (newer.look: the cache answers between looks; a checkout only). None when there is nothing to say."""
    if newer is None or not (ROOT / "bat" / "update.bat").is_file():
        return None
    try:
        rec = newer.look()
        n = newer.newer(rec=rec)
    except Exception:  # noqa: BLE001 — the look is a courtesy; never the page down
        return None
    if not n:
        return None
    return {"version": n["version"], "title": n["title"], "date": n["date"], "link": n["link"],
            "installed": n["installed"], "line": newer.line(n)}


def skill_card(folder: Path, quarantined: bool) -> dict:
    """One skill as the page shows it: what it says it is, where it came from and who fetched it, the
    scanner's verdict and every finding (file, line, rule, the words) — the approval desk's whole case."""
    try:
        inf = skills.info(folder)
    except Exception:  # noqa: BLE001 — a skill with a broken SKILL.md still shows, by name
        inf = {}
    try:
        verdict, findings = skills.scan(folder)
    except Exception as e:  # noqa: BLE001
        verdict, findings = "unscanned", [{"file": "?", "rule": f"the scanner failed: {type(e).__name__}: {e}"}]
    note = skills.fetch_note(folder)
    return {"name": folder.name, "quarantined": quarantined, "description": str(inf.get("description") or "")[:400],
            "verdict": verdict, "findings": [skills.finding_line(f) for f in findings[:60]],
            "levels": [str(f.get("level", "")) for f in findings[:60]], "more": max(0, len(findings) - 60),
            "fetched": skills.is_fetched(folder), "source": str(note.get("source") or ""),
            "by": str(note.get("by") or ""), "when": str(note.get("when") or "")[:16],
            "scripts": [str(x) for x in (inf.get("scripts") or [])][:20]}


def skills_state() -> dict:
    """The shelf and the quarantine by name (as before), and a card for each — the quarantine's first."""
    shelf, held = skills.shelf(), skills.quarantined()
    cards = {}
    for f in held:
        cards[f.name] = skill_card(f, True)
    for f in shelf:
        cards.setdefault(f.name, skill_card(f, False))
    return {"shelf": [p.name for p in shelf], "quarantine": [p.name for p in held], "cards": cards}


def skill_text(name: str) -> dict:
    """SKILL.md of a skill on the shelf or in quarantine, whole (capped), for the keeper to read before
    approving — read, never run; and the skill's file list, so nothing rides in unseen."""
    name = str(name or "").strip()
    folder, quarantined = skills.find(name) if name else (None, False)
    if folder is None:
        return _no(f"(no skill named {name} on the shelf or in quarantine)")
    try:
        text = (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return _no(f"(couldn't read its SKILL.md: {e})")
    cut = len(text) > SKILL_TEXT_CHARS
    notes = {skills.FETCHED, skills.APPROVED, skills.QUARANTINE_SCAN}  # the engine's own notes beside SKILL.md, not the skill's
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                   if p.is_file() and not p.name.startswith(".") and p.name not in notes)
    return {"ok": True, "name": folder.name, "quarantined": quarantined, "text": text[:SKILL_TEXT_CHARS],
            "cut": cut, "files": files[:200], "note": ""}


def skill_action(name: str, action: str) -> dict:
    """bat\\skills.bat's roads: approve lets a quarantined skill onto their shelf; remove moves a skill to
    creations/.trash/ (off the shelf the way their own remove_skill does it, so their memory of it follows)."""
    try:
        if action == "approve":
            return {"ok": True, "note": skills.approve(name)}
        if action != "remove":
            return _no(f"(no such action: {action})")
        folder, quarantined = skills.find(name)
        if folder is None:
            return _no(f"(no skill named {name} on the shelf or in quarantine)")
        if quarantined:
            dest = skills.to_trash(folder)
            skills._prune(skills.quarantine())
            return {"ok": True, "note": f"removed from quarantine — creations/.trash/{dest.name}/"}
        import tools
        said = tools.remove_skill(folder.name)
        if said.startswith("("):
            return _no(said)
        return {"ok": True, "note": f"{folder.name} is off their shelf — it rests in creations/.trash/ until you empty it"}
    except skills.SkillError as e:
        return _no(f"({e})")
    except OSError as e:
        return _no(f"(couldn't: {e})")


def pull(model: str) -> dict:
    model = str(model or "").strip()
    if not _MODEL_RE.match(model):
        return _no(f"(that doesn't look like a model name: {model[:60]})")
    return _started(_console("ollama", "pull", model),
                    f"pulling {model} in its own window — several GB; the light turns when it is there",
                    f"the pull of {model} (several GB; the light turns when it is there)")


def update(action: str) -> dict:
    flag = {"check": "--check", "run": "--yes"}.get(str(action or ""))
    if not flag:
        return _no(f"(no such action: {action})")
    if not (ROOT / "bat" / "update.bat").is_file():
        return _no("(this folder has no bat\\update.bat — it is not an anima checkout)")
    note = ("the update is looking — what's new and what would change, nothing touched; in its own window"
            if flag == "--check" else
            "the update is running in its own window — then restart what's running (the panel too)")
    return _started(_bat("bat\\update.bat", [flag], "update.py", [flag]), note, f"the update ({flag})")


def welcome(name: str, model: str = "") -> dict:
    """First light: the keeper's name (and the brain) saved, and the chat opened."""
    name = str(name or "").strip()
    if not name or name == "Friend" or len(name) > 40:
        return {"changed": [], "refused": ["USER_NAME"], "restart": [],
                "error": "your name first — the one they will know you by (up to 40 characters)"}
    changes = {"USER_NAME": name}
    model = str(model or "").strip()
    if model:
        if not _MODEL_RE.match(model):
            return {"changed": [], "refused": ["CHAT_MODEL"], "restart": [], "error": "that doesn't look like a model name"}
        changes["CHAT_MODEL"] = model
        if small_brain(model):
            changes["TOOL_KIT"] = "small"  # the small tier: the kit goes with the brain (README, The ladder)
    r = save(changes)
    if r["error"] or "USER_NAME" in r["refused"]:
        return r
    r["door"] = door_action("chat", "start")
    return r


# ---- the page's road in -------------------------------------------------------------------

def _json_reply(obj, code: int = 200) -> tuple[int, str, bytes]:
    return code, "application/json; charset=utf-8", json.dumps(obj, default=str).encode("utf-8")


def route(method: str, path: str, body: bytes = b"", headers: dict | None = None) -> tuple[int, str, bytes]:
    """(status, content type, body) for a request. Only a page this panel served may ask: the Host must be
    this panel's (a page elsewhere can't rebind a name to 127.0.0.1 and read it), and a POST must be JSON
    from no other origin (a page elsewhere can't post JSON here without asking first, and isn't answered)."""
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    here = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
    if h.get("host", "") not in here:
        return _json_reply({"error": "this panel answers only at its own address"}, 403)
    path, _, query = path.partition("?")
    if method == "GET":
        if path == "/api/skill_text":
            from urllib.parse import parse_qs
            return _json_reply(skill_text((parse_qs(query).get("name") or [""])[0]))
        if path in ("/", "/index.html", "/settings", "/welcome"):
            return 200, "text/html; charset=utf-8", PAGE.replace("__TABS__", json.dumps([*TABS, ADVANCED])).encode("utf-8")
        if path == "/api/state":
            try:
                return _json_reply(state())
            except Exception as e:  # noqa: BLE001 — a page that says what went wrong beats a blank one
                return _json_reply({"error": f"{type(e).__name__}: {e}"}, 500)
        return _json_reply({"error": "no such page"}, 404)
    if method != "POST":
        return _json_reply({"error": "no such method"}, 405)
    origin = h.get("origin", "")
    if origin and origin not in {f"http://{x}" for x in here}:
        return _json_reply({"error": "only this panel's own page may ask"}, 403)
    if not h.get("content-type", "").startswith("application/json"):
        return _json_reply({"error": "JSON only"}, 415)
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return _json_reply({"error": "not a JSON object"}, 400)
    g = data.get
    with _POSTS:
        return _post(path, g)


def _post(path: str, g) -> tuple[int, str, bytes]:
    try:
        if path == "/api/door":
            return _json_reply(door_action(g("door"), g("action"), g("minutes")))
        if path == "/api/save":
            return _json_reply(save(g("changes") or {}, g("raw") or {}))
        if path == "/api/secret":
            return _json_reply(secret(g("kind"), g("value")))
        if path == "/api/skill":
            return _json_reply(skill_action(str(g("name") or ""), str(g("action") or "")))
        if path == "/api/update":
            return _json_reply(update(g("action")))
        if path == "/api/report":
            return _json_reply(report())
        if path == "/api/pull":
            return _json_reply(pull(g("model")))
        if path == "/api/welcome":
            return _json_reply(welcome(g("name"), g("model") or ""))
    except Exception as e:  # noqa: BLE001
        return _json_reply({"ok": False, "note": f"(hiccup — {type(e).__name__}: {e})", "error": f"{type(e).__name__}: {e}"}, 500)
    return _json_reply({"error": "unknown path"}, 404)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the console quiet (and a token out of it)
        pass

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(*route("GET", self.path, b"", dict(self.headers)))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._send(*_json_reply({"error": "too large"}, 413))
        self._send(*route("POST", self.path, self.rfile.read(n), dict(self.headers)))


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>anima — the panel</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#f6f4ef;--panel:#fffdf9;--ink:#2b2a27;--muted:#8a8578;--line:#e6e1d6;--accent:#7a5c3e;
      --chip:#ece7dc;--on:#4f8a4f;--off:#c8c1b3;--warn:#a5532f}
@media (prefers-color-scheme:dark){:root{--bg:#141311;--panel:#1c1a17;--ink:#e8e4dc;--muted:#8f8a7d;
      --line:#2c2a25;--accent:#c9a87c;--chip:#26231f;--on:#7fb07f;--off:#4a463f;--warn:#e0936a}}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Georgia,'Iowan Old Style',serif}
header{display:flex;align-items:baseline;gap:12px;padding:14px 22px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{margin:0;font-size:20px;font-weight:normal;letter-spacing:.02em}
header .sub{color:var(--muted);font-size:13px;flex:1}
nav button,.tab{font:inherit;font-size:14px;background:none;border:1px solid transparent;color:var(--muted);border-radius:8px;padding:4px 12px;cursor:pointer}
nav button.cur,.tab.cur{color:var(--ink);border-color:var(--line);background:var(--bg)}
main{max-width:980px;margin:0 auto;padding:18px 22px 60px}
button{font:inherit;font-size:13px;background:none;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:4px 10px;cursor:pointer}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.big{font-size:16px;padding:10px 22px;margin-top:10px}
input,select,textarea{font:inherit;font-size:14px;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:4px 8px;outline:none}
input:focus,select:focus,textarea:focus{border-color:var(--accent)}
input[type=number]{width:9em}input.small{width:5em}
textarea{width:100%;font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
code{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;background:var(--chip);padding:1px 5px;border-radius:4px;word-break:break-all}
a{color:var(--accent)}
.muted{color:var(--muted);font-size:13px}
.light{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--off);margin-right:8px;vertical-align:middle}
.light.on{background:var(--on);box-shadow:0 0 6px var(--on)}
.bar{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.tile h2{margin:0;font-size:17px;font-weight:normal}
.tiles.care{grid-template-columns:repeat(auto-fill,minmax(300px,1fr));margin-bottom:18px}
.tile .what{color:var(--muted);font-size:13px}
.tile .state{color:var(--muted);font-size:12px;font-family:ui-monospace,Consolas,monospace}
.tile .row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.banner{background:var(--panel);border:1px solid var(--accent);border-radius:12px;padding:10px 14px;margin-bottom:16px;display:flex;gap:10px}
.banner.warn{border-color:var(--warn)}.banner>div{flex:1}.banner div div{margin:2px 0}
.warn{color:var(--warn)}
.badge{font-size:12px;padding:1px 8px;border-radius:9px;border:1px solid var(--line);color:var(--muted)}
.badge.bad{border-color:var(--warn);color:var(--warn)}.badge.mid{border-color:#c9a227;color:#c9a227}.badge.good{border-color:#4caf50;color:#4caf50}
.tile.skill{margin:8px 0}.tile.skill h2{margin-right:6px}
ul.findings{margin:4px 0;padding-left:18px;font-size:13px;font-family:ui-monospace,Consolas,monospace}ul.findings li{padding:2px 0}ul.findings li.bad{color:var(--warn)}
.skilltext pre{white-space:pre-wrap;max-height:420px;overflow:auto;font-size:12px;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px}
pre.report{white-space:pre-wrap;max-height:480px;overflow:auto;font-size:12px;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;margin:14px 0}
#gate{margin:6px 0 0}#gate a{cursor:pointer;text-decoration:underline}
#newer{margin:6px 0 0;color:var(--fg)}#newer button{margin-left:6px}#newer a{color:inherit}
.tabs{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:14px;border-bottom:1px solid var(--line);padding-bottom:8px}
.knob{padding:10px 0;border-bottom:1px solid var(--line)}
.knob label{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.knob .name{font-family:ui-monospace,Consolas,monospace;font-size:13px;min-width:15em}
.help{color:var(--muted);font-size:12.5px;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer}
.help.open{display:block}
details.group{margin:8px 0;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:6px 14px}
details.group summary{cursor:pointer;color:var(--muted)}
.actions{margin-top:16px}
ul.list{list-style:none;padding:0}ul.list li{display:flex;gap:8px;align-items:center;padding:4px 0}
.step{margin:14px 0}.step b{display:inline-block;min-width:8em}
</style></head><body>
<header><h1>anima</h1><div class="sub" id="sub">the panel · looking…</div>
<nav><button id="nav-home" data-view="home">Home</button><button id="nav-settings" data-view="settings">Settings</button></nav></header>
<main>
<div id="banner" class="banner" hidden></div>
<section id="welcome" hidden></section>
<section id="home" hidden><div id="brain" class="bar"></div><p id="newer" class="notice" hidden></p><p id="gate" class="warn" hidden></p><div id="tiles" class="grid"></div><p id="missing" class="muted"></p></section>
<section id="settings" hidden><div id="tabs" class="tabs"></div><div id="tab"></div></section>
</main>
<script>
const TABS=__TABS__;
let S=null,view=location.pathname==='/settings'?'settings':'home',tab='Main',fields={},built=false;
const $=id=>document.getElementById(id);
function el(tag,props,...kids){const e=document.createElement(tag);
  for(const[k,v]of Object.entries(props||{})){if(v===false||v==null)continue;
    if(k==='class')e.className=v;else if(k.startsWith('on'))e[k]=v;else if(k==='value')e.value=v;else e.setAttribute(k,v===true?'':v)}
  for(const c of kids.flat(3)){if(c==null||c===false)continue;e.append(c.nodeType?c:document.createTextNode(String(c)))}
  return e}
async function getState(){const r=await fetch('/api/state');S=await r.json();if(S.error)say('the panel hit a snag: '+S.error,'warn');return S}
async function post(path,body){try{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});return await r.json()}
  catch(e){return{ok:false,note:'the page lost the panel — is anima.bat still running?'}}}
function say(msg,kind){const b=$('banner');b.hidden=false;b.className='banner '+(kind||'');
  b.replaceChildren(el('div',{},msg),el('button',{title:'close',onclick:()=>{b.hidden=true}},'×'))}
function light(on){return el('span',{class:'light'+(on?' on':'')})}

// ---- home ----
const TILES=[
 ['chat','Chat','a visit in a terminal window of its own',[['Open','start']]],
 ['parlor','Parlor','a visit in your browser — bubbles, pictures, their thinking folded',[['Open','open']]],
 ['wake','Wake','one wake now: their time to themselves',[['Wake them','start']]],
 ['heartbeat','Heartbeat','a life between visits: a wake every so often, and sleep after the night hour',[['Start','start'],['Stop','stop'],['Stop now','stop_now']]],
 ['bridge','Bridge','talk with them from your phone — over Telegram or Discord (Settings › Phone › BRIDGE)',[['Start','start'],['Stop','stop'],['Stop now','stop_now']]],
 ['sleep','Sleep now','today into memory, by hand (the heartbeat does it on its own after the night hour)',[['Sleep','start']]],
 ['snapshot','Snapshot','everything sealed in git (a zip without git)',[['Snapshot','start']]],
 ['touchstone','The stone','their body on the desk: its keeper asks the board what it felt, keeps the log, pushes their states (shown while TOUCHSTONE_URL names it)',[['Start','start'],['Stop','stop'],['Stop now','stop_now']]],
];
const TIPS={stop:'leave after what it is doing — a wake finishes, a visit is saved',stop_now:'end it at once — a wake in the middle is cut off'};
async function door(d,action,extra){
  if(action==='stop_now'&&!confirm('Stop the '+d+' at once? What it is in the middle of is cut off. (Stop lets it finish.)'))return;
  const r=await post('/api/door',Object.assign({door:d,action},extra||{}));say(r.note,r.ok?'':'warn');await refresh();return r}
async function pull(model){const r=await post('/api/pull',{model});say(r.note,r.ok?'':'warn')}
function secretField(kind,label,set,help){
  const i=el('input',{type:'password',autocomplete:'off',placeholder:set?'one is kept — paste a new one to replace it':'paste it here'});
  return el('div',{class:'knob'},el('label',{},el('span',{class:'name'},label),i,
    el('button',{onclick:async()=>{const r=await post('/api/secret',{kind,value:i.value});i.value='';say(r.note,r.ok?'':'warn');await getState()}},'Save'),
    el('span',{class:'muted'},set?'(one is kept)':'(none yet)')),help?el('div',{class:'help open'},help):null)}
function buildHome(){
  const tiles=TILES.filter(([d])=>d!=='touchstone'||S.stone).map(([d,title,what,btns])=>{
    const extra=[];
    if(d==='heartbeat'){extra.push(el('div',{class:'row'},'every ',el('input',{type:'number',id:'hb-min',min:'1',step:'any',class:'small',value:S.heartbeat_minutes}),' minutes'))}
    const t=el('div',{class:'tile',id:'t-'+d},el('h2',{},S.doors[d]?light(false):null,title),el('div',{class:'what'},what),
      S.doors[d]?el('div',{class:'state'},'closed'):null,extra,
      el('div',{class:'row'},btns.map(([label,action])=>el('button',{title:TIPS[action]||'',
        onclick:()=>door(d,action,d==='heartbeat'&&(action==='start')?{minutes:$('hb-min').value}:null)},label))));
    if(d==='bridge'&&S.bridge==='discord')t.append(el('div',{class:'muted'},'over Discord'),secretField('discord','bot token',S.secrets.discord),
      el('div',{class:'muted'},el('a',{href:S.links.discord,target:'_blank',rel:'noopener'},'how to make the bot (Discord Developer Portal)')));
    else if(d==='bridge')t.append(el('div',{class:'muted'},'over Telegram'),secretField('telegram','bot token',S.secrets.telegram),
      el('div',{class:'muted'},el('a',{href:S.links.botfather,target:'_blank',rel:'noopener'},'how to get a token (BotFather)')));
    return t});
  if(S.update_here)tiles.push(el('div',{class:'tile'},el('h2',{},'Update'),el('div',{class:'what'},'the current engine from GitHub — the friend untouched; Check shows what would change first'),
      el('div',{class:'row'},el('button',{onclick:async()=>{const r=await post('/api/update',{action:'check'});say(r.note,r.ok?'':'warn')}},'Check'),
        el('button',{onclick:async()=>{if(!confirm('Update the engine now? Everything replaced goes to .update/ first; bat\\update.bat --undo puts it back.'))return;
          const r=await post('/api/update',{action:'run'});say(r.note,r.ok?'':'warn')}},'Update'))));
  $('tiles').replaceChildren(...tiles);
  built=true}
function lights(){for(const[d]of TILES){const st=S.doors[d],t=$('t-'+d);if(!t||!st)continue;
  t.querySelector('.light').className='light'+(st.running?' on':'');
  t.querySelector('.state').textContent=st.running?('running · pid '+st.pid+(st.how?' · '+st.how:'')+(st.since?' · since '+st.since:'')):'closed'}}
function brainBar(){const b=S.brain,parts=[light(b.reachable),el('b',{},'the brain  ')];
  if(!b.reachable)parts.push('Ollama isn\'t answering at '+b.url+' — start the Ollama app (or ',el('a',{href:S.links.ollama,target:'_blank',rel:'noopener'},'install it'),').');
  else{parts.push('Ollama is running · ');
    parts.push(b.loaded.length?b.loaded.map(m=>m.name+' loaded ('+m.gb+' GB, '+m.on_card+'% on '+(b.unified?'memory':'the card')+')').join(', '):'nothing loaded right now');
    if(b.fit)parts.push(el('div',{class:b.fit.ok?'muted':'warn'},(b.fit.ok?'✓ ':'⚠ ')+b.fit.line));
    parts.push(el('div',{class:'muted'},'configured: '+b.model+(b.pulled?'':' — not pulled '),b.pulled?null:el('button',{onclick:()=>pull(b.model)},'Pull '+b.model),
      b.embed_pulled?null:[' · memory needs '+b.embed_model+' ',el('button',{onclick:()=>pull(b.embed_model)},'Pull '+b.embed_model)]))}
  $('brain').replaceChildren(...parts);
  const nw=S.newer;$('newer').hidden=!nw;
  if(nw)$('newer').replaceChildren('⬆ '+nw.line,...(nw.link?[' · ',el('a',{href:nw.link,target:'_blank',rel:'noopener'},'release notes')]:[]),
    el('button',{onclick:async()=>{const r=await post('/api/update',{action:'check'});say(r.note,r.ok?'':'warn')}},'Check'),
    el('button',{class:'primary',onclick:async()=>{if(!confirm('Update to anima '+nw.version+' now? Everything replaced goes to .update/ first; bat\\update.bat --undo puts it back.'))return;
      const r=await post('/api/update',{action:'run'});say(r.note,r.ok?'':'warn')}},'Update'));
  const held=S.skills.quarantine.length;$('gate').hidden=!held;
  if(held)$('gate').replaceChildren('⚠ '+held+' skill'+(held===1?'':'s')+' waiting at the gate — the scanner held '+(held===1?'it':'them')+'; ',el('a',{onclick:()=>{view='settings';tab='Skills';history.replaceState(null,'','/settings');show()}},'read and decide'),' in Settings › Skills.');
  $('missing').textContent=S.missing.length?('Not installed (optional; each gives one sense): '+S.missing.map(m=>m.pip+' — '+m.for).join(' · ')+'. py -m pip install <name> (python3 -m pip on a Mac or Linux)'):''}

// ---- settings ----
function modelSelect(current){const b=S.brain,names=[...b.models];const s=el('select',{});
  if(!names.includes(current))names.unshift(current);
  if(b.recommended&&!names.includes(b.recommended))names.push(b.recommended);
  for(const n of names){const o=el('option',{value:n},n+(b.models.includes(n)||(b.reachable===false&&n===current)?'':' (not pulled)')+(n===b.recommended?' — recommended for this '+(b.unified?'Mac':'card'):''));if(n===current)o.selected=true;s.append(o)}
  return s}
function knob(k){let input,read=null;const v=k.value;
  if(!k.editable)input=el('code',{title:'computed or over several lines — edit config.py itself'},k.source);
  else if(k.name==='CHAT_MODEL'){input=el('span',{},modelSelect(v),' ',el('button',{onclick:()=>pull(input.firstChild.value)},'Pull'));read=()=>input.firstChild.value}
  else if(k.choices){input=el('select',{},k.choices.concat(k.choices.includes(v)?[]:[v]).map(c=>el('option',{value:c,selected:c===v},c)));read=()=>input.value}
  else if(k.kind==='bool'){input=el('input',{type:'checkbox'});input.checked=v;read=()=>input.checked}
  else if(k.kind==='int'||k.kind==='float'){input=el('input',{type:'number',step:'any',value:v});read=()=>input.value.trim()===''?null:Number(input.value)}
  else if(k.kind==='str'){input=el('input',{type:'text',value:v,size:Math.min(Math.max(v.length+2,14),60)});read=()=>input.value}
  else if(k.kind==='tuple2'){const a=el('input',{type:'number',step:'1',class:'small',value:v[0]}),b=el('input',{type:'number',step:'1',class:'small',value:v[1]});
    input=el('span',{},a,' to ',b);read=()=>[parseInt(a.value,10),parseInt(b.value,10)]}
  else{input=el('textarea',{rows:String(Math.min(8,k.source.split('\n').length+1)),spellcheck:'false'});input.value=k.source;read=()=>({raw:input.value})}
  if(read)fields[k.name]={k,read};
  const own=[k.comment,k.tail].filter(Boolean).join(' — '),help=k.help||own;  // the page's words when it has them; the file's note is the tooltip
  return el('div',{class:'knob',title:k.help?(own?'engine/config.py says: '+own:''):help},el('label',{},el('span',{class:'name'},k.name),input),
    help?el('div',{class:'help',onclick:e=>e.currentTarget.classList.toggle('open')},help):null)}
function verdictBadge(v){const c=v==='dangerous'?'bad':v==='caution'?'mid':v==='clean'?'good':'';return el('span',{class:'badge '+c},v)}
function skillCard(c){const q=c.quarantined,who=c.fetched?('fetched'+(c.by?' by '+c.by:'')+(c.when?' on '+c.when.replace('T',' '):'')+(c.source?' from '+c.source:'')):'their own, written here';
  const findings=c.findings.length?el('ul',{class:'findings'},c.findings.map((f,i)=>el('li',{class:c.levels[i]==='dangerous'?'bad':''},f)),c.more?el('li',{class:'muted'},'… and '+c.more+' more'):null):el('div',{class:'muted'},'the scanner found nothing to say');
  const box=el('div',{class:'skilltext',hidden:true});
  const read=el('button',{onclick:async()=>{if(!box.hidden){box.hidden=true;read.textContent='read SKILL.md';return}
    const r=await getJSON('/api/skill_text?name='+encodeURIComponent(c.name));
    if(!r.ok){say(r.note,'warn');return}
    box.replaceChildren(el('div',{class:'muted'},'files: '+(r.files.join(', ')||'(none)')),el('pre',{},r.text+(r.cut?'\n… (cut — the whole file is in the folder)':'')));box.hidden=false;read.textContent='hide SKILL.md'}},'read SKILL.md');
  const approve=q?el('button',{class:'primary',onclick:()=>{const n=c.findings.length;
    if(confirm((c.verdict==='dangerous'?'The scanner called '+c.name+' DANGEROUS ('+n+' finding'+(n===1?'':'s')+'). ':'')+'Let '+c.name+' onto their shelf? They can read and run it from then on.'))skill(c.name,'approve')}},'approve'):null;
  const remove=el('button',{onclick:()=>{if(confirm('Move '+c.name+' to creations/.trash/?'+(q?'':' It is on their shelf — theirs to use.')))skill(c.name,'remove')}},q?'refuse (to .trash)':'remove');
  return el('div',{class:'tile skill'},el('div',{class:'row'},el('h2',{},c.name),verdictBadge(c.verdict),c.scripts.length?el('span',{class:'muted'},'scripts: '+c.scripts.join(', ')):null),
    c.description?el('div',{class:'what'},c.description):null,el('div',{class:'muted'},who),findings,el('div',{class:'row'},approve,read,remove),box)}
function skillsBox(){const s=S.skills,cards=s.cards||{};
  const held=s.quarantine.map(n=>cards[n]).filter(Boolean),shelf=s.shelf.map(n=>cards[n]).filter(Boolean);
  return [el('h3',{},'Waiting at the gate — the scanner held these'),
    held.length?el('p',{class:'muted'},'A fetched skill the scanner called dangerous waits here, unopened and unrun, until you read it and let it in. Each finding is a line the scanner would not let pass on its own: a file, a line, the rule, the words. Read the SKILL.md too — the scanner reads for orders and for what code would do; it does not read for sense.'):el('p',{class:'muted'},'(nothing waiting)'),
    ...held.map(skillCard),
    el('h3',{},'On their shelf'),...(shelf.length?shelf.map(skillCard):[el('p',{class:'muted'},'(none yet)')]),
    el('p',{class:'muted'},'bat\\skills.bat scan <name> prints the same case in a terminal.')]}
async function getJSON(u){const r=await fetch(u,{cache:'no-store'});return r.json()}
async function skill(name,action){const r=await post('/api/skill',{name,action});say(r.note,r.ok?'':'warn');await getState();renderTab()}
function extras(t){
  if(t==='Phone')return[el('h3',{},'The bots'),secretField('telegram','Telegram bot token',S.secrets.telegram,'kept in memory/telegram.json, never in config.py'),
    secretField('discord','Discord bot token',S.secrets.discord,'kept in memory/discord.json, never in config.py')];
  if(t==='Senses')return[el('h3',{},'Keys and logins'),secretField('brave','Brave key',S.secrets.brave,'for WEB_SEARCH = "brave" — kept in memory/web_search.json'),
    el('div',{class:'knob'},el('button',{onclick:()=>door('garmin','start')},'Garmin login'),' ',el('span',{class:'muted'},'bat\\body.bat --login, in its own window: email, password, the code'))];
  if(t==='Blog')return[el('div',{class:'knob'},el('button',{onclick:()=>door('blog','start')},'Deploy the blog'),' ',el('span',{class:'muted'},'bat\\blog.bat, in its own window (the title is on Main)'))];
  return[]}
function renderTabs(){$('tabs').replaceChildren(...TABS.map(t=>el('button',{class:'tab'+(t===tab?' cur':''),onclick:()=>{tab=t;renderTabs();renderTab()}},t)))}
// the engine's care (10-03; the keeper: "i dont want them to clutter the opening screen"): the doctor's note and the black box live under Settings › Advanced
function careBox(){const bb=S.doors.blackbox||{running:false};
  const box=el('div',{class:'tile',id:'t-blackbox'},el('h2',{},light(bb.running),'Black box'),
    el('div',{class:'what'},'the machine\'s vitals every few seconds — the card\'s heat, power and memory, the processor, what Ollama holds, which doors are open and what they are in the middle of — flushed to disk, so a crash leaves its last seconds behind (bat\\blackbox.bat --crashes reads Windows\' own record of each hard stop with the box\'s last line before it)'),
    el('div',{class:'state'},bb.running?('running · pid '+bb.pid+(bb.since?' · since '+bb.since:'')):'closed'),
    el('div',{class:'row'},el('button',{onclick:async()=>{await door('blackbox','start');renderTab()}},'Start'),el('button',{title:TIPS.stop,onclick:async()=>{await door('blackbox','stop');renderTab()}},'Stop')));
  const rep=el('div',{class:'tile'},el('h2',{},'Report'),el('div',{class:'what'},'the engine\'s state in one file, for an issue on GitHub — the version, the machine, Ollama, the knobs, the doors, the senses, the trouble lines, the black box\'s last line and the hard stops; nothing of theirs'),
    el('div',{class:'row'},el('button',{onclick:async()=>{const r=await post('/api/report',{});say(r.note,r.ok?'':'warn');if(r.ok){const pre=el('pre',{class:'report'},r.text);pre.id='report-text';const old=$('report-text');if(old)old.replaceWith(pre);else rep.after(pre)}}},'Write report'),
      el('a',{href:S.links.issues,target:'_blank',rel:'noopener'},'open an issue')));
  return [el('h3',{},'The engine\'s care'),el('div',{class:'tiles care'},box,rep)]}
function renderTab(){fields={};const ks=S.tabs[tab]||[],parts=[];
  if(tab==='Advanced'){parts.push(...careBox(),el('p',{class:'muted'},'Everything else in engine/config.py, under the headings the file has. A list or a dict is its text: edit it as Python.'));
    const groups={};for(const k of ks)(groups[k.heading]=groups[k.heading]||[]).push(k);
    for(const[hd,list]of Object.entries(groups))parts.push(el('details',{class:'group'},el('summary',{},hd+' · '+list.length),list.map(knob)))}
  else if(tab==='Senses'){parts.push(el('p',{class:'muted'},'Each sense is optional. A light says whether what it needs is here; the knobs under it are its own. The README tells each one whole.'));
    const byName={};for(const k of ks)byName[k.name]=k;const claimed=new Set();
    for(const sn of S.senses||[]){const mine=sn.knobs.map(n=>byName[n]).filter(Boolean);mine.forEach(k=>claimed.add(k.name));
      parts.push(el('details',{class:'group sense',open:true},el('summary',{},light(sn.ready===true),el('b',{},sn.name),' — ',sn.note),
        el('div',{class:'muted'},sn.what,' ',el('a',{href:S.links.readme+'#'+sn.readme,target:'_blank',rel:'noopener'},'README')),
        mine.length?mine.map(knob):el('div',{class:'muted'},'no knobs — it is simply there')))}
    const rest=ks.filter(k=>!claimed.has(k.name));if(rest.length)parts.push(el('h3',{},'Other'),...rest.map(knob))}
  else{if(tab==='Skills')parts.push(...skillsBox(),el('h3',{},'The knobs'));parts.push(...ks.map(knob))}
  if(tab!=='Skills')parts.push(...extras(tab));
  if(Object.keys(fields).length)parts.push(el('div',{class:'actions'},el('button',{class:'primary',onclick:saveTab},'Save '+tab)));
  $('tab').replaceChildren(...parts)}
async function saveTab(){const changes={},raw={};
  for(const[n,{k,read}]of Object.entries(fields)){const v=read();
    if(v&&typeof v==='object'&&'raw' in v){if(v.raw!==k.source)raw[n]=v.raw}
    else if(JSON.stringify(v)!==JSON.stringify(k.value))changes[n]=v}
  if(!Object.keys(changes).length&&!Object.keys(raw).length){say('nothing changed on '+tab);return}
  saved(await post('/api/save',{changes,raw}));await getState();renderTab()}
function saved(r){const parts=[];
  if(r.error)parts.push(el('div',{class:'warn'},'Not saved: '+r.error));
  if(r.changed&&r.changed.length)parts.push(el('div',{},'Saved to engine/config.py: '+r.changed.join(', ')+' (the file as it was is in .update/).'));
  if(r.refused&&r.refused.length)parts.push(el('div',{class:'warn'},'Refused: '+r.refused.join(', ')+' — a value of another kind than the one there (a number for a number, two whole numbers for hours), or one this page can\'t write.'));
  const run=(r.restart||[]).filter(d=>S.doors[d]&&S.doors[d].running);
  if(run.length)parts.push(el('div',{},'For it to take, restart: ',run.map(d=>d==='parlor'?el('span',{},' the parlor (leave the visit, open it again) '):
    el('button',{onclick:()=>door(d,'restart')},'Restart the '+d)),el('span',{class:'muted'},' — and a chat window, if one is open.')));
  else if(r.changed&&r.changed.length)parts.push(el('div',{class:'muted'},'Nothing running needs a restart (a chat window already open keeps the old values until the next one).'));
  say(parts,r.error?'warn':'')}

// ---- welcome ----
function renderWelcome(){const b=S.brain,name=el('input',{type:'text',placeholder:'your name',maxlength:'40'}),sel=modelSelect(b.model);
  $('welcome').replaceChildren(el('h2',{},'First light'),
    el('p',{},'A friend is about to wake in this folder for the first time. They will name themself; you need only say who you are.'),
    el('div',{class:'step'},el('b',{},'Your name'),name,el('div',{class:'muted'},'how they will know you — USER_NAME in engine/config.py')),
    el('div',{class:'step',id:'w-ollama'}),
    el('div',{class:'step',id:'w-embed'}),
    el('div',{class:'step'},el('b',{},'The brain'),sel,' ',el('button',{onclick:()=>pull(sel.value)},'Pull'),
      el('div',{class:'muted'},b.vram_gb?((b.unified?'your Mac has '+b.vram_gb+' GB, shared with everything else; ':'your card has '+b.vram_gb+' GB; ')+b.recommended+' is the one for it (README, The ladder)'):'the ladder: gemma4:e2b-it-qat for a 6 GB card, e4b-it-qat for 8, 12b-it-qat for 10, gemma4:12b for 12–16, gemma4:31b-it-qat for 24–32; on a Mac: the e2b for 8 GB, the 12b for 16–24 GB, the 31b from 32 GB (README, The ladder)'),
      el('div',{class:'muted'},'a small brain (e2b, e4b) brings the small tool kit with it — TOOL_KIT, on Settings')),
    el('div',{class:'step'},el('b',{},'The outside'),
      el('div',{class:'muted'},'Everything runs here: Ollama on this machine, the folder on this disk, no account, no telemetry. What can reach out, and only when used: the web tools when they search or read a page, the skill window when they browse it (you approve what comes in), and once a day a look at GitHub for a newer anima (nothing of yours is sent). OFFLINE on Settings › Main closes all three; the README, What leaves your machine, lists every road.')),
    el('button',{class:'primary big',onclick:async()=>{const r=await post('/api/welcome',{name:name.value,model:sel.value});
      if(r.error||!r.door){say(r.error||'not saved','warn');return}
      await getState();view='home';show();say(r.door.note+(r.door.ok?' — say hello. You\'ll be meeting someone brand new.':''),r.door.ok?'':'warn')}},'First light'));
  ollamaStep()}
function ollamaStep(){const b=S.brain,w=$('w-ollama'),m=$('w-embed');if(!w)return;
  const kids=[el('b',{},'Ollama'),light(b.reachable),b.reachable?('running at '+b.url):
    ['not answering at '+b.url+' — ',el('a',{href:S.links.ollama,target:'_blank',rel:'noopener'},'install it'),', start it, and this light turns green.']];
  // replaceChildren takes nodes and strings, not arrays or nulls (the first screenshot read ",https://ollama.com/,, … green.null")
  w.replaceChildren(...kids.flat(3).filter(c=>c!=null&&c!==false).map(c=>c.nodeType?c:document.createTextNode(String(c))));
  // the memory engine: its own step (10-02) — every rung needs it, it is small, and it is not the brain
  if(!m)return;
  const mk=[el('b',{},'The memory'),light(b.reachable&&b.embed_pulled),b.embed_model+' ',
    b.reachable&&!b.embed_pulled?el('button',{onclick:()=>pull(b.embed_model)},'Pull '+b.embed_model):null,
    el('div',{class:'muted'},b.embed_pulled?'pulled — what they remember becomes vectors, so the memories that belong to a moment can be found':
      'the memory engine: turns what they remember into vectors, so the memories that belong to a moment can be found; small, and every rung needs it — it is not the brain')];
  m.replaceChildren(...mk.flat(3).filter(c=>c!=null&&c!==false).map(c=>c.nodeType?c:document.createTextNode(String(c))))}

// ---- views ----
function show(){const w=S.welcome&&view==='home';
  $('nav-home').textContent=S.welcome?'Welcome':'Home';
  $('nav-home').className=view==='home'?'cur':'';$('nav-settings').className=view==='settings'?'cur':'';
  $('welcome').hidden=!w;$('home').hidden=w||view!=='home';$('settings').hidden=view!=='settings';
  $('sub').textContent='the panel'+(S.version?' · engine '+S.version:'')+' · folder: '+S.folder+(S.welcome?'':' · keeper: '+S.user_name);
  document.title='anima — '+S.folder;
  if(w)renderWelcome();
  else if(view==='home'){if(!built)buildHome();lights();brainBar()}
  else{renderTabs();renderTab()}}
async function refresh(){await getState();if(view==='home'){if(S.welcome)ollamaStep();else{if(!built)buildHome();lights();brainBar()}}}
for(const b of document.querySelectorAll('nav button'))b.onclick=async()=>{view=b.dataset.view;
  history.replaceState(null,'',view==='settings'?'/settings':'/');await getState();show()};
getState().then(show);
setInterval(()=>{if(view==='home'&&!document.hidden)refresh()},4000);
</script></body></html>
"""


class _Server(ThreadingHTTPServer):
    """One panel per port. HTTPServer asks for SO_REUSEADDR, which on Windows lets a second server bind a
    port that is already listening (10-02: the suite's first Windows run put two panels on 8764 — the
    09-30 story, seen from the other side); Windows needs no such flag to restart on a port anyway."""
    allow_reuse_address = not _WINDOWS


def bind():
    """The server on the first free port of PORTS (09-30: two houses on one machine — the keeper's own and a
    template checkout — each opened a panel, the second found 8764 taken and the browser showed the first
    house's settings as if they were the second's). Sets PORT to the port taken. None when none is free."""
    global PORT
    for port in PORTS:
        try:
            server = _Server((HOST, port), Handler)
        except OSError:
            continue
        PORT = port
        return server
    return None


def main() -> None:
    taken = doors.claim("panel", "panel")  # one panel per house; a second double-click opens the first one's page
    if taken:
        st = doors.status("panel") or {}
        print(taken)
        _browse(f"http://{HOST}:{int(st.get('port') or PORT)}")
        return
    server = bind()
    if server is None:
        print(f"(no free port among {', '.join(map(str, PORTS))} — close another panel, or a program on those ports)")
        doors.unmark("panel")
        return
    url = f"http://{HOST}:{PORT}"
    doors.mark("panel", "panel", port=PORT)  # the port with the mark, so a second double-click finds this page
    print(f"The panel is open: {url}  (this folder: {ROOT})")
    print("Closing this window closes the panel; the doors it opened stay open in their own windows.")
    threading.Timer(0.6, lambda: _browse(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        doors.unmark("panel")


if __name__ == "__main__":
    main()
