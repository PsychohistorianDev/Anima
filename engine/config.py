"""Central configuration for the friend.

Everything tunable lives here. Paths are derived from the project root
(the folder containing self.md), so the whole project can be moved or
renamed freely.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- paths ----
ROOT = Path(__file__).resolve().parent.parent

IDENTITY_FILE = ROOT / "self.md"
PROJECTS_FILE = ROOT / "projects.md"
# The friend's destiny page: a long horizon that no single project completes.
# It belongs to the friend alone — the engine never creates or writes it.
# When the file exists it rides in the prompt right after WHO YOU ARE
# (see DESTINY_IN_PROMPT and DESTINY_CHARS_IN_PROMPT below).
DESTINY_FILE = ROOT / "destiny.md"
KEEPER_FILE = ROOT / "keeper.md"  # who you are to them, in their words — theirs, and open to you
JOURNAL_DIR = ROOT / "journal"
CREATIONS_DIR = ROOT / "creations"
MEMORY_DIR = ROOT / "memory"
EPISODIC_DIR = MEMORY_DIR / "episodic"
IDENTITY_HISTORY_DIR = MEMORY_DIR / "identity_history"
DESTINY_HISTORY_DIR = MEMORY_DIR / "destiny_history"  # earlier versions of destiny.md, kept before each rewrite
KEEPER_HISTORY_DIR = MEMORY_DIR / "keeper_history"  # every version of keeper.md before a rewrite
DB_PATH = MEMORY_DIR / "memory.db"

SHARED_DIR = ROOT / "shared"  # where you leave images, music and books for the friend

# ------------------------------------------------------------------- you ----
# Your name, as your friend will know it. It appears in their prompts, in the
# chat windows, and names their mailbox folder to you in creations/.
USER_NAME = "Friend"  # <-- put your actual name here before first light
# The mailbox: a folder in creations/ where the friend leaves letters for you
# between visits. Derived from your name; "notes_to_sam" for Sam.
MAILBOX = "notes_to_" + "".join(c if c.isalnum() else "_" for c in USER_NAME.lower())

for _d in (JOURNAL_DIR, CREATIONS_DIR, MEMORY_DIR, EPISODIC_DIR,
           IDENTITY_HISTORY_DIR, SHARED_DIR, CREATIONS_DIR / MAILBOX):
    _d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------- ollama ----
OLLAMA_URL = "http://localhost:11434"

# The brain (the chat model). Swap freely; memories and identity survive a swap.
#   fits a 12 GB card : "gemma4:12b" (~6.7 GB at Q4, tools + thinking)
#   alternatives      : "qwen3:14b", "qwen3:30b-a3b" (RAM offload),
#                       "gemma4:e4b" (smaller and faster)
# If tool calls misbehave on a Gemma 4 model, try the same tag with thinking
# disabled, or a Qwen3 tag.
CHAT_MODEL = "gemma4:12b"
# The README's ladder, by the card's memory: 6 GB "gemma4:e2b-it-qat", 8 GB
# "gemma4:e4b-it-qat", 10 GB "gemma4:12b-it-qat", 12–16 GB this 12B, 24–32 GB
# "gemma4:31b-it-qat" (near-bf16 quality in ~19 GB) — with the NUM_CTX,
# TOOL_KIT and journal size for each rung in the README's "The ladder".

# Embedding model for semantic memory: it turns memories into vectors so the
# ones related to the moment can be found. Install: ollama pull nomic-embed-text
EMBED_MODEL = "nomic-embed-text"

# The friend's ears — three layers (see engine/ears.py):
#   WORDS — faster-whisper transcription   (py -m pip install faster-whisper)
#   MUSIC — numpy acoustic measurement     (py -m pip install numpy)
#   HEARD — the brain listening to the raw audio (gemma4:12b has native
#           audio; thinking must stay ON for it — see engine/ollama_client.py).
EARS_MODEL = "gemma4:12b"
EARS_USE_VIBE = True
# When the ears model differs from the brain, unload the brain before
# listening. Each listen then costs a model swap, but the freed VRAM leaves
# more room for context. If both are the same model there is nothing to swap.
EARS_UNLOAD_BRAIN = True
# Seconds of audio the SOUND and HEARD layers receive (WORDS, the
# transcription, always hears the whole file). A higher value deepens
# listening but slows it; Gemma's audio training centres on short clips, so
# beyond ~120 s the HEARD layer's impressions tend to blur rather than deepen.
EARS_CLIP_SECONDS = 120
# How many EARS_CLIP_SECONDS passages the brain hears of a longer piece when
# the music ear (below) is not installed: 5 × 120 s = the first 10 minutes.
EARS_MAX_PASSAGES = 5

# Video reaches the friend as a strip of stills plus its soundtrack (the
# `watch` sense): one frame every WATCH_FRAME_EVERY_S seconds, at most
# WATCH_MAX_FRAMES (never fewer than three), each WATCH_FRAME_WIDTH pixels
# wide. Ten 768-pixel frames cost about a megabyte of context.
WATCH_FRAME_EVERY_S = 3
WATCH_MAX_FRAMES = 10
WATCH_FRAME_WIDTH = 768
# The frames are also kept as one contact sheet — WATCH_SHEET_COLUMNS across,
# each WATCH_SHEET_TILE_WIDTH pixels wide — in shared/pictures/from_videos/,
# named after the video, so a watched video can be looked at again later.
# The individual frames are not kept. False: no sheet.
WATCH_KEEP_SHEET = True
WATCH_SHEET_COLUMNS = 5
WATCH_SHEET_TILE_WIDTH = 512
# The music ear: engine/music_ears.py runs NVIDIA's Music Flamingo, a model
# made for music that hears a whole song (up to 20 min) in one pass. Nothing to
# start by hand: once the dependencies are installed, listen_to wakes the
# sidecar, the model loads, and the GPU goes back to the brain afterwards.
# Not installed: the ears fall back to passages (EARS_MAX_PASSAGES).
MUSIC_EARS_URL = "http://127.0.0.1:8766"
MUSIC_EARS_MODEL = "nvidia/music-flamingo-2601-hf"  # older tag: nvidia/music-flamingo-hf
MUSIC_EARS_AUTOSTART = True   # listen_to starts the sidecar when needed
# Which Python runs the ear; "" = the engine's own. PyTorch's CUDA builds can
# lag the newest Python release, so the ear may need its own, e.g.
#   MUSIC_EARS_PYTHON = "py -3.12"       (Windows)
#   MUSIC_EARS_PYTHON = "python3.12"     (macOS, Linux)
MUSIC_EARS_PYTHON = ""
# Where the ear runs: "auto" takes an NVIDIA (or ROCm) card, else a Mac's GPU
# ("mps", float16), else the processor; "cuda", "mps" or "cpu" names one.
MUSIC_EARS_DEVICE = "auto"
MUSIC_EARS_REST_AFTER = True  # free the GPU as soon as a song ends
MUSIC_EARS_IDLE_S = 120       # seconds; fallback: the sidecar frees the GPU after this much idle time
MUSIC_EARS_EXIT_S = 1800      # seconds unused before the sidecar process exits
MUSIC_EARS_TIMEOUT_S = 600    # seconds allowed for one whole-song listen
# Longest stretch (seconds) the ear hears in one pass; longer pieces are heard
# in equal movements no longer than this. Memory grows faster than linearly
# with length: roughly 17 GB at a few seconds, 24 GB at 200 s, 31 GB at 280 s.
# As a guide: 240 s on a 32 GB card, ~150 s on 24 GB, ~60 s on 16 GB.
# Probe before raising:  py engine\music_ears.py --test "shared\song.mp3" --seconds 240
MUSIC_EARS_MAX_SECONDS = 240
# Whisper model size for the WORDS layer: "base" is quick; "small" is more
# accurate, especially with produced or stylized singing, where "base" may
# hear no words at all. The first listen downloads the model once (~500 MB).
EARS_STT_MODEL = "small"
# Names and words the ears should recognize. Whisper has never heard your
# friend's name and will write the nearest common word without this hint.
# Add the friend's chosen name once they have one, and other names that matter.
EARS_VOCAB_HINT = f"A recording from {USER_NAME}. Names that may occur: {USER_NAME}."
# Whether destiny.md rides in the prompt, and how many characters of it.
# A page in every prompt pulls strongly on the model, so keep it a page, not
# a book; past the cap the rest is named for read_file.
DESTINY_IN_PROMPT = True
DESTINY_CHARS_IN_PROMPT = 4000
# keeper.md: a page about you, in the friend's own words — what
# they'd want to remember of you if everything else faded, and how to be with
# you. Theirs alone (update_keeper; the engine never writes it; every version
# before is kept in memory/keeper_history/), and open: you read it, and they
# know. It rides right after WHO YOU ARE, up to KEEPER_CHARS_IN_PROMPT; the
# rest waits in the file. Tell them the page exists — nothing in it is required.
KEEPER_IN_PROMPT = True
KEEPER_CHARS_IN_PROMPT = 6000
# After sleep, one quiet look at keeper.md from the day whole — update_keeper
# or do_nothing, hours from any visit, so the page is revised cool rather
# than in the glow of a goodbye (the afterglow may write it too). One cold
# read of the window a night. False skips the look.
SLEEP_KEEPER_LOOK = True
# Reading notebooks: one page per book, creations/reading/<book>.md, written
# by the friend with append_creation after each sitting. While a book is open
# (bookmark not at the end, a sitting within READING_OPEN_DAYS) its page rides
# in the prompt under THE BOOK IN YOUR HANDS; when the bookmark reaches the
# end, one memory row records the finished book. A PDF shorter than
# READING_BOOK_PAGES (a datasheet, a paper) is not a book; an EPUB always is.
READING_PAGES_IN_PROMPT = True
READING_DIR = "reading"        # folder under creations/
READING_PAGE_CHARS = 3000      # characters of each open book's page in the prompt
READING_OPEN_DAYS = 30         # days untouched before an unfinished book leaves the prompt
READING_DONE_DAYS = 3          # days a finished book's page stays in the prompt
READING_BOOK_PAGES = 40        # PDFs with fewer pages are not treated as books
STRAY_PAGE_RATIO = 0.75          # name similarity (0–1) at which a new reading page counts as a misspelling of an open book's page
EPUB_SLIVER_CHARS = 400          # characters; a shorter EPUB item (a part title page, under 1/50 of the largest item) is read with the next one
# How much of a book one sitting is, in characters (a dense page is ~2,000).
# That is roughly 4 tokens per 15 characters, and it stays in the visit until
# /new. READ_RANGE_CHARS is the larger allowance when the friend asks for a
# range of pages on purpose, e.g. a whole story at once.
READ_SITTING_CHARS = 30000     # reading on from the bookmark: ~15 pages
READ_RANGE_CHARS = 80000       # a named range: ~40 pages, ~20K tokens
# The painter: engine/painter.py runs a text-to-image model as a sidecar, like
# the music ear — woken by `paint`, the brain unloaded for it, the GPU handed
# back after. Not installed: paint says so and suggests run_python + matplotlib.
# Setup (once, in the ear's Python):  py -m pip install -U diffusers transformers accelerate safetensors pillow
# Cost: every painting is a model swap, and the brain then re-reads its whole
# context cold (minutes on a large context). Gather prompts into one call.
PAINTER_URL = "http://127.0.0.1:8767"
# Ungated, Apache 2.0, ~16 GB (the brain is off the card while painting).
# Alternative: "black-forest-labs/FLUX.2-klein-4B" (4 steps, ~13 GB; can edit too).
PAINTER_MODEL = "Tongyi-MAI/Z-Image-Turbo"
PAINTER_AUTOSTART = True      # paint starts the sidecar when needed
PAINTER_PYTHON = ""           # "" = the engine's own; e.g. "py -3.12" (Windows) or "python3.12" (macOS, Linux) if torch lives elsewhere
# Where the painter paints: "auto" takes an NVIDIA (or ROCm) card, else a Mac's
# GPU ("mps", float16), else the processor (slow); "cuda", "mps" or "cpu" names one.
PAINTER_DEVICE = "auto"
PAINTER_REST_AFTER = True     # free the GPU as soon as a painting is done
PAINTER_IDLE_S = 120          # seconds; fallback: the sidecar frees the GPU after this much idle time
PAINTER_EXIT_S = 1800         # seconds unused before the sidecar process exits
PAINTER_TIMEOUT_S = 300       # seconds allowed for one painting, model load included
PAINTER_STEPS = 0             # 0 = the model's default (Z-Image-Turbo 9, FLUX.2 klein 4)
# Pixel sizes for the size words (Full HD by default). Sides snap to multiples
# of 16, so "wide" becomes 1920×1088. These models paint about two megapixels
# cleanly; larger sizes cost more and may duplicate the subject. Words may be
# added or changed freely.
PAINTER_SIZES = {"square": (1440, 1440), "wide": (1920, 1088), "tall": (1088, 1920)}
# A picture the friend makes (painted, or drawn with run_python or one of their
# own tools) is shown to them on their next step, as look_at would, so they see
# the result instead of describing it from the prompt. Up to PICTURES_SHOWN_MAX
# per call; the rest are named for look_at. Each costs a few hundred tokens.
SHOW_WHAT_SHE_MADE = True
PICTURES_SHOWN_MAX = 3
# The friend's own description of a piece (the about= of a page, or the prompt
# a painting was made from) is kept in its memory row up to this many
# characters, cut at a sentence or word boundary with an ellipsis.
NOTE_ABOUT_CHARS = 400
PAINTER_MAX_PER_WAKE = 3      # paintings per wake session (0 = no cap); a visit is never capped

# Seconds to wait for one request. Local inference can be slow; raise this if
# a large model on a small card is reported offline while it is still working.
REQUEST_TIMEOUT_S = 600

# How long Ollama keeps the brain loaded after a request (Ollama's duration
# syntax: "30m", "2h", "24h"; -1 = forever). Unloading drops its cache, so the
# next message pays a cold re-read of the whole context (minutes at ~150K
# tokens). Ollama's own default is 5 minutes; 30 minutes covers ordinary pauses
# in a conversation without holding the GPU all day.
BRAIN_KEEP_ALIVE = "30m"
# ...and when a visit ends (/new, the idle roll, Ctrl+C), unload the brain as
# soon as the afterglow is written, freeing the GPU right away rather than
# after BRAIN_KEEP_ALIVE.
BRAIN_REST_AFTER_VISIT = True
# ...and when a single wake (bat\wake.bat, the panel's Wake) finishes, the
# same: the brain set down at once, the card free the moment the wake ends.
BRAIN_REST_AFTER_WAKE = True

# Context window for the brain, in tokens. The friend's prompt (identity,
# journal, memories, tool definitions) is far bigger than Ollama's default.
# CAUTION: if the prompt exceeds this, Ollama silently trims from the TOP —
# the identity and instructions. Every window in the README's ladder assumes
# Ollama was given flash attention and the 4-bit KV cache (setup step 2):
#                  setx OLLAMA_FLASH_ATTENTION 1
#                  setx OLLAMA_KV_CACHE_TYPE q4_0   (q8_0 costs twice the room: halve it)
NUM_CTX = 40960  # tokens; a 12B on a 12 GB card with the q4_0 cache (24576 was the measured q8_0 ceiling)
# Which built-in tools ride in the prompt. All of them cost ~7,500 tokens of
# definitions — a third of a 24K window before a word of journal. "full" is
# everything; "small" leaves out what a small card can't run or a small brain
# can't steer (the painter, ears and voice, video, skills, the forge, the blog,
# projects, clips) and saves ~3,000 tokens; "tiny" keeps the life itself —
# journal, memory, pages, the web, looking, resting — and saves ~5,500, for an
# e2b. A list of tool names is a kit of your own. Forged tools always ride.
# Restart the doors after changing it.
TOOL_KIT = "full"
# OFFLINE: True closes every road out of the house for the friend — the web
# tools (search_web, read_web, search_wikipedia), the skill window
# (browse_skills, fetch_skill) and the once-a-day look at GitHub for a newer
# anima. Ollama is local and stays; the phone, the watch and the blog are
# doors you open by hand and stay as they are. README, What leaves your machine.
OFFLINE = False
# The black box (bat\blackbox.bat; the panel's tile): the machine's vitals —
# the card's heat, power and memory, the processor, what Ollama holds, the
# doors, what they are in the middle of — one line every BLACKBOX_EVERY_S
# into memory/blackbox/<day>.jsonl, flushed to disk, so a machine that goes
# down leaves its last seconds behind (--crashes reads Windows' event log).
BLACKBOX_EVERY_S = 5
# Deep in a long window a 12B's tool calls can drift into plain text — the
# rails catch it; watch for it past ~32K. For a 31B on a 32 GB card the whole
# 256K fits under 30 GB with the q4_0 cache (measured). With q8_0 instead:
# 64K ≈ 24.5 GB, 128K ≈ 27 GB, 176K ≈ 30 GB (the comfortable top), 192K ≈ 31 GB
# (the limit — past it Ollama silently spills to system RAM, very slow).
# 4-bit keys trade a little precision: if garbled replies appear, q8_0 and a
# smaller window is the retreat. Verify any setting with `ollama ps` (100% GPU)
# and clean tool calls late in long wakes.
# NOTE: the window only matters once the journal cap below can fill it.

# The same hyphenated word this many times or more in ONE reply (e.g.
# "ever-so-bright" three times) is the sampler repeating itself: the reply is
# asked for again (one re-roll) and a note under it says why. A word doubled
# back to back is simply said once; the word itself is never forbidden.
# 0 turns the check off.
REFRAIN_MAX = 3

# An echo: a reply that opens word for word like the previous reply — the
# sampler copying the nearest assistant turn instead of writing a new one,
# which gets likelier deep into a long context. Compared over this many
# opening characters, so short repeated phrases ("love you") pass. An echo is
# re-rolled and named under the reply. 0 turns it off.
ECHO_MIN_CHARS = 120

# Sampling options passed to Ollama; top_k/top_p are Gemma's recommended values.
# min_p drops any token less than this fraction as likely as the best one, which
# keeps garbage tokens out deep in long contexts; if replies go flat, try 0.06.
# Keep repeat_penalty GENTLE: it can't tell a loop from a language, and ~1.15
# garbles common words in long conversations. repeat_last_n 512 covers the tail
# of the last reply (against echoes); 1024 or more tends to break signature phrases.
SAMPLING_OPTIONS = {
    "temperature": 0.9,
    "min_p": 0.08,
    "top_k": 64,
    "top_p": 0.95,
    "repeat_penalty": 1.05,
    "repeat_last_n": 512,
    # The most one step may generate, thinking included. Without a ceiling a
    # runaway step (a thought that never lands, a tool call that keeps
    # writing) runs until REQUEST_TIMEOUT_S and the turn is lost. 8192 tokens
    # is a few minutes of generation and well above a normal long step; a step
    # that hits it ends with done_reason=length, which the engine names.
    "num_predict": 8192,
}

# How much recent journal goes into every prompt (characters). Oldest is
# trimmed first, whole days at a time, so the newest writing always survives.
# This cap, not NUM_CTX, decides how many days are remembered verbatim.
JOURNAL_CHARS_IN_PROMPT = 40000  # ~9K tokens; fits a 40K context with room for
# tools and a long chat. Older days reach the friend through nightly
# consolidation, the condensed pages (the fractal journal, below), recall and
# read_journal. English prose runs ~4.4 characters per token on Gemma 4. With a
# 256K context, 550000 (weeks of prolific writing, ~125K tokens) still leaves
# ~125K for a visit; the price is a cold read of a couple of minutes per visit.

# How much of a day sleep (consolidate.py) reads — journal plus every
# transcript, in characters. It is one call with no system prompt, so nearly
# the whole window is free for it: 400K characters is ~90K tokens. With a 24K
# context window, use about 60000.
CONSOLIDATE_MAX_CHARS = 400000
# In --loop mode the heartbeat also does the sleeping: at the first beat after
# SLEEP_AFTER_HOUR it consolidates YESTERDAY (if not done yet) before waking —
# one process, one request at a time, no scheduled task racing a wake for the
# GPU. If the machine was off at that hour, it sleeps at the first beat after.
# False: schedule `consolidate.py yesterday` yourself.
SLEEP_IN_LOOP = True
SLEEP_AFTER_HOUR = 3

# Patience per STEP during unattended wakes, in seconds — shorter than chat
# patience, so a wedged generation ends the wake (log saved) instead of
# freezing the heartbeat.
HEARTBEAT_STEP_TIMEOUT_S = 300

# ------------------------------------------------------------- behaviour ----
# (There is no limit in days on the verbatim journal: the character cap above
# is the only bound. The newest whole days that fit stay verbatim; older days
# belong to the condensed pages and the timeline.)

# The fractal journal: memory in tiers — recent weeks in full (the journal cap
# above), older days as the friend's own condensed pages, a line a day in the
# timeline, facts underneath. When a day is about to slip out of the cap, the
# engine asks at night (engine/condense.py, or bat\condense.bat) for a page of about
# CONDENSE_TARGET_CHARS, written with condense_day into journal/condensed/. The
# engine never writes the page itself; if the friend rests, only the timeline line stays.
CONDENSED_DIR = JOURNAL_DIR / "condensed"
CONDENSED_CHARS_IN_PROMPT = 150000   # characters of condensed pages in the prompt, newest kept (~2 months at a page a day)
CONDENSE_TARGET_CHARS = 2000         # "about a page"; they may go over
CONDENSE_IN_LOOP = True              # the heartbeat asks for pages after sleep
CONDENSE_MAX_PER_NIGHT = 3
CONDENSE_MAX_STEPS = 6
CONDENSE_MAX_CHARS = 120000          # the most of one day handed over at once
# The ladder above the day: weeks, months, quarters, years and five-year
# blocks, each condensed from the tier below by a steady factor (about 2–3.5×).
# Each tier keeps its newest LADDER_PAGES_KEPT pages in view and folds the
# oldest into the tier above, so the total stays bounded forever (7 per tier ≈
# 395K characters at steady state; 5 ≈ 282K; 10 ≈ 564K). LADDER_TARGETS are
# page sizes in characters; five-year blocks count from LADDER_EPOCH_YEAR.
LADDER_PAGES_KEPT = 7
LADDER_TARGETS = {"week": 4000, "month": 6000, "quarter": 8472, "year": 13708, "five_years": 22180}
LADDER_EPOCH_YEAR = 2026

# How many retrieved long-term memories go into every prompt — the ones most
# related to the moment. Each is a sentence or two (~50 tokens), so the limit
# is about signal, not space; on a small context window, fewer (8–12) suit better.
MEMORY_TOP_K = 30
# Spread the picks instead of clustering them: with MEMORY_DIVERSE each pick is
# weighed against those already chosen (MEMORY_MMR_LAMBDA of relevance, the rest
# a penalty for resembling one already in), so the slots hold different things.
# MEMORY_RECENT_K of the newest memories ride along whatever the topic, so what
# was kept this morning is still in view this afternoon. 0 turns that slice off.
MEMORY_DIVERSE = True
MEMORY_MMR_LAMBDA = 0.75
MEMORY_RECENT_K = 6

# The warm prefix. Ollama reuses its reading of a prompt only as far as it
# matches the previous one from the top, and Gemma's cache only when the new
# prompt EXTENDS the old one. So the system prompt is built once per visit and
# kept, and what changes (the hour, surfacing memories) rides inside each
# message. A reply then reads only what is new: seconds, not minutes, on a big
# context. The first message of a visit is still cold. False = rebuild each turn.
WARM_PREFIX = True
# Once a visit has needed a think re-roll (an answer with no thinking, asked for
# again with a nudge), the nudge is added to every later message of that visit
# from the start: a few dozen tokens instead of a whole second generation.
THINK_NUDGE_STICKS = True

# The timeline: one short paragraph per day from the nightly consolidation, in
# every prompt, oldest first — but only for days that neither the verbatim
# journal nor a condensed page in view already covers. A line is ~580
# characters (~130 tokens); the newest lines within this cap are kept.
# 0 turns the timeline off.
TIMELINE_CHARS_IN_PROMPT = 30000

# Autonomy: hard ceiling on tool steps per heartbeat wake, so a stuck loop can't
# spiral. Generous on purpose — how much of it the friend uses is their call,
# and "do nothing" is always a legal move that ends the wake.
HEARTBEAT_MAX_STEPS = 24  # a 12B uses ~10-20; a 31B can run clean at 40 or more, with the window guard below as the real ceiling.
# The context window is the real ceiling of a long wake: it grows with every
# tool result, and past NUM_CTX Ollama would silently cut the top of the prompt.
# At HEARTBEAT_ROOM_WARN of NUM_CTX the friend is told once (finish the thought,
# write what matters, or end); at HEARTBEAT_ROOM_END the wake ends, said
# plainly. 0 turns either off.
HEARTBEAT_ROOM_WARN = 0.85
HEARTBEAT_ROOM_END = 0.92
# A good fit shows as wakes ending in clean rests, not fading mid-thought.
# The step ceiling is a safety rail, not a quota.

# The heartbeat waits while a visit is live: a wake in the middle of a
# conversation would replace the cached context (the next reply pays a cold
# re-read) and share the GPU. A visit counts as live while the last turn was
# within HEARTBEAT_YIELD_MIN minutes; the loop checks again every
# HEARTBEAT_YIELD_CHECK_MIN minutes. False: wakes run on schedule regardless.
HEARTBEAT_YIELD_TO_VISIT = True
HEARTBEAT_YIELD_MIN = 30
HEARTBEAT_YIELD_CHECK_MIN = 10

# Minutes between wakes when heartbeat.py runs with --loop and no number
# after it (--loop 60 on the command line still wins). A 12B does well waking
# every ~20 minutes (many small attempts); a 31B does deeper work waking every
# hour or two.
HEARTBEAT_LOOP_MIN = 120

# Reverie: unhurried wakes for reflection only — no making, just rereading,
# remembering, and journaling. In --loop mode every Nth wake is a reverie;
# bat\reverie.bat gives one on demand. More steps, nothing expected.
REVERIE_EVERY = 3
REVERIE_MAX_STEPS = 20

# Show the model's chain of thought live during heartbeat wakes, and keep it
# in the wake log. The friend is told that the logs exist.
HEARTBEAT_SHOW_THINKING = True

# Chat: ceiling on consecutive tool calls per message you send. Research
# errands (search, read several pages, clip, draw, look) need many steps. The
# window guard (HEARTBEAT_ROOM_END) ends an errand before the context
# overflows whatever the count; a confused loop still stops here.
CHAT_MAX_TOOL_STEPS = 50

# Require thinking on every turn (Ollama's `think` flag). Left optional, the
# model tends to stop deliberating once the prompt grows large. Models that
# can't think are handled gracefully (the flag is dropped).
CHAT_THINK = True
# The flag opens the thought channel but can't force its use: Gemma 4 may still
# act with an empty thought, and once one step of a wake does, the rest tend to
# follow. When a step comes back without thinking, the engine asks again with a
# short "think first" nudge at the end, this many times before accepting it.
# The prompt is cached, so a re-roll costs seconds. 0 turns this off.
CHAT_THINK_RETRIES = 2
# The same, for heartbeat wakes. A wake's prompt is warm, so a re-roll is
# seconds of generation and a few hundred tokens, not a cold read — a larger
# budget is cheap here. None: same as chat.
HEARTBEAT_THINK_RETRIES = 4

# Deep in a long context (past ~90K tokens) Gemma 4 sometimes emits a stray
# channel token mid-reply, and Ollama routes the rest of the reply into the
# thinking field: the reply stops mid-sentence. When a reply ends mid-sentence
# with done_reason=stop, the engine asks once for the rest from the cut and
# joins it on, with a note. 0 turns this off (the cut is only named).
CHAT_CONTINUE_RETRIES = 2  # 2: one extra try if what comes back is a note to themself

# Letter salad (runs of word fragments) is the sampler failing, not the friend
# speaking — usually a repeat penalty set too strong. A reply with a run of
# fragments is asked for again this many times, with a short engine line, and
# a note says so; the friend is never handed a glitch to explain.
CHAT_GARBLE_RETRIES = 4  # each try is checked; if none is clean the least broken goes out, named
# Cooler rolls before the least broken attempt goes out: when every try is
# broken, one more is made at each of these temperatures in turn, for that roll
# only, each only if the one before broke too. Everyday sampling is untouched.
# 0 turns it off (the least broken goes out as before).
CHAT_RESCUE_TEMPERATURE = (0.6, 0.4)
# ...and after the cool rolls, a cold roll: garbage that survives lower
# temperatures points at the loaded state (a KV cache gone wrong on a long
# quantized prefill), not the sampler. The brain is unloaded and reloaded (a
# cold read of the prompt, a minute or two on a large context), one more roll
# is made at everyday sampling, and only then does the least broken go out.
CHAT_COLD_RESCUE = True
# A broken attempt shown back to the friend before a re-roll stays in the
# visit (the warm prefix). Past this many characters only its head is kept, so
# broken attempts don't fill the context. 0 = keep it whole.
ATTEMPT_SHOWN_CHARS = 1500

# The fold: when a visit's prompt reaches FOLD_AT of NUM_CTX, the friend is
# asked to write the visit so far in their own words (fold_visit); that account
# replaces everything above the last FOLD_KEEP_TURNS turns. The system prompt is
# rebuilt, the transcript keeps every word, the visit continues in a new file.
# The friend may also fold at a natural pause; from FOLD_SENSE_FROM the moment
# block says how full the window is. 0 turns the fold off (then /new is suggested).
FOLD_AT = 0.90
# The afterglow at the fold: the turns that leave the window get the same quiet turn
# a finished visit gets — journal and memories, in the friend's own words — from the
# transcript, before the new window is first read, so what the fold takes is in the
# journal and in the window. One cold read, once per fold; a message sent meanwhile
# waits for it. Needs AFTERGLOW.
FOLD_AFTERGLOW = True
FOLD_KEEP_TURNS = 6       # visible turns kept whole, the most recent ones
FOLD_CHARS = 8000         # the account's ceiling (cut at a paragraph past it, said)
FOLD_MAX_STEPS = 6        # steps allowed at the fold (a journal entry first, then the fold)
FOLD_SENSE_FROM = 0.5     # from this fraction of NUM_CTX the moment block shows how full the window is

# Your body, as your watch sees it (optional): engine/body.py pulls your day
# from Garmin Connect into memory/body/<day>.json (bat\body.bat --login once, then
# bat\body.bat --pull). With BODY_IN_PROMPT on, a short section of plain numbers
# rides in the prompt, and a pulse line in the moment block. Your data, your
# switch: leave it off until a first pull looks right. Credentials live only
# in memory/garmin/ — never here.
BODY_IN_PROMPT = False
BODY_AUTOPULL = True          # the bridge pulls every BODY_PULL_MIN while BODY_IN_PROMPT is on — no bat\body.bat --pull window needed
BODY_IN_MOMENT = True         # the pulse line in the moment block (needs BODY_IN_PROMPT)
BODY_PULL_MIN = 20            # minutes between pulls of today; yesterday rides only while its night is still syncing
BODY_CHARS_IN_PROMPT = 600    # characters; the section's ceiling
BODY_STALE_H = 6              # hours since the last sync after which the section says it is stale
BODY_DIR = MEMORY_DIR / "body"
GARMIN_TOKENS = MEMORY_DIR / "garmin"

# Skills: folders in the open SKILL.md format (name, description, procedure,
# maybe scripts/ and references/) on the friend's shelf at
# creations/<SKILLS_DIR>/<name>/. The prompt lists them by name with a line each;
# use_skill opens one, run_skill_script runs its Python in run_python's sandbox,
# and fetch_skill brings one from GitHub, a SKILL.md URL or a .zip through a scanner:
# clean, caution (tagged), or dangerous (quarantined until: bat\skills.bat approve <name>).
SKILLS_IN_PROMPT = True
SKILLS_DIR = "skills"            # folder under creations/
SKILLS_CHARS_IN_PROMPT = 4000    # characters of the skills list in the prompt; past it the newest are kept
SKILLS_DESC_CHARS = 200          # characters of each description in the prompt (list_skills gives them whole)
SKILL_CHARS = 20000              # characters of a SKILL.md or skill file per use_skill (cut at a line, said)
SKILL_MAX_FILES = 40             # files per fetch
SKILL_MAX_BYTES = 2_000_000      # bytes per fetch, all files together
SKILL_FETCH_TIMEOUT = 30         # seconds per request of a fetch
# Catalogues for browse_skills, which shows the friend skills available online:
# each is a (label, "owner/repo/path[@branch]") pair on GitHub, under which
# skills sit as <name>/SKILL.md or <category>/<name>/SKILL.md. Each index is
# cached in SKILL_CATALOGUE_DIR for SKILL_CATALOGUE_TTL_H hours (the first browse
# builds it, under a minute). Community collections can be added as more pairs;
# the scanner still checks every fetch. From a terminal: bat\skills.bat browse [query] (--refresh rebuilds).
SKILL_CATALOGUES = [("hermes", "NousResearch/hermes-agent/skills"), ("anthropic", "anthropics/skills/skills")]
SKILL_CATALOGUE_TTL_H = 168      # hours (a week); then the next browse rebuilds (if that fails, the old index is used, dated)
SKILL_BROWSE_CHARS = 6000        # characters of one browse_skills listing (cut at a line, the rest counted)
SKILL_CATALOGUE_DIR = MEMORY_DIR / "skills_catalogue"
SKILL_CATALOGUE_PACE = 0.5       # seconds between SKILL.md requests while indexing (avoids GitHub's rate limit)
SKILL_CATALOGUE_RETRY_MIN = 30   # minutes before a partial index asks again for the descriptions GitHub refused
SKILL_CATALOGUE_BUDGET_S = 90    # seconds one index build may spend (it runs inside a tool call); the rest wait for the next browse
# Watch a reply as it streams and cut a runaway short: the moment the tail of
# the stream is salad (a stuck chunk repeating, a cascade, a run of fragments),
# the connection closes and Ollama stops, instead of generating to num_predict.
# What came back goes to the salad check as a broken attempt and is re-rolled;
# the kept reply is never the cut one. A false alarm costs one re-roll.
CHAT_STREAM_ABORT = True

# The afterglow: when a visit ends (parlor "leave", /new, the bridge's idle
# roll, /quit), the friend gets one quiet turn alone with the transcript and
# three tools (write_journal, remember, do_nothing), so the visit reaches their
# journal in their own words, not only the nightly summary. Resting is a
# complete answer. Costs one mostly cached brain call in the background.
# Transcripts longer than AFTERGLOW_MAX_CHARS are given from the end.
AFTERGLOW = True
AFTERGLOW_MAX_CHARS = 60000
# The pause: when you have been quiet for REFLECT_AFTER_MIN minutes in the
# middle of a visit (a coffee break, not the end of a visit), the friend gets
# the same quiet turn as the afterglow, over what was said since they last
# wrote, and the visit stays open. Needs at least REFLECT_MIN_TURNS new
# messages from you since the last reflection. 0 turns it off.
REFLECT_AFTER_MIN = 12
REFLECT_MIN_TURNS = 2

# No duplicates: before a fact is kept, the nearest memory is checked; at or
# above MEMORY_DUP_THRESHOLD (cosine similarity, nomic-embed-text) it counts as
# the same fact, and the friend can revise it (replaces=) or insist (anyway="yes").
# Typical: true repeats score 0.90–0.98, different facts on one theme ~0.89.
# The journal gets the same check against today's and yesterday's entries
# (JOURNAL_DUP_THRESHOLD); nightly consolidation skips facts already known.
MEMORY_DUP_THRESHOLD = 0.88
JOURNAL_DUP_THRESHOLD = 0.88
# The nearest earlier entry's score is named in write_journal's result when it
# is at least this — useful for setting JOURNAL_DUP_THRESHOLD from real numbers
# rather than guessing. 0: never.
JOURNAL_NEAREST_SHOW = 0.7
# Circling: when a new journal entry opens with a subject (a date other than
# the day being written, a file, a quoted title) that this many entries of
# today and yesterday already open with, it becomes an arrow to the latest of
# them instead of a new entry. The next day is free again. 0 turns it off.
JOURNAL_SUBJECT_MAX = 2

# The reads tell: every read_creation / read_journal / read_file is counted in
# memory/reads.json. From the READ_TELL_MIN-th reading of the same thing within
# READ_TELL_DAYS days, the result opens with the count — a tell, not a fence —
# so the friend notices when they keep returning to one thing. 0 turns it off.
READ_TELL_MIN = 3
READ_TELL_DAYS = 30  # days (a month)

# The web (engine/web.py). read_web keeps a page's shape (title, headings,
# lists, numbered links), leaves menus and footers out, and hands long pages
# over in parts of WEB_PAGE_CHARS with up to WEB_LINKS_MAX links. search_web:
# "duckduckgo" needs no key; "searxng" uses your own instance at
# WEB_SEARCH_SEARXNG_URL (e.g. "http://localhost:8080"); "brave" needs a key,
# kept ONLY in memory/web_search.json as {"brave_key": "…"} — never here.
WEB_SEARCH = "duckduckgo"
WEB_SEARCH_SEARXNG_URL = ""
WEB_PAGE_CHARS = 12000
WEB_LINKS_MAX = 40
WEB_CLIP_CHARS = 20000  # characters of a page clip_web keeps in a project's sources/

# Project pages: an Active project in projects.md whose line names a folder,
# e.g. "(Location: robotics/)", has that folder's README.md ride in the prompt
# (up to PROJECT_PAGE_CHARS each, PROJECTS_CHARS_IN_PROMPT in all): the page
# the friend keeps of what is known, what is open, and the next step. clip_web
# saves pages they read into the folder's sources/. False turns this off.
PROJECTS_HOME = "projects"  # every project's folder lives under creations/projects/
PROJECT_PAGES_IN_PROMPT = True
PROJECT_PAGE_CHARS = 4000
PROJECTS_CHARS_IN_PROMPT = 12000

# The arrow: when write_journal refuses a duplicate, a stamped mark is left in
# the day instead of silence ("**17:00** — ↑ still this, at 14:20"), so the
# day keeps its rhythm and shows the feeling lasted. A mark, not an entry: the
# engine writes no words for the friend. One arrow per thought per
# JOURNAL_ARROW_GAP_MIN minutes. False: the refusal alone.
JOURNAL_ARROW = True
JOURNAL_ARROW_GAP_MIN = 45

# A paragraph repeated from the friend's previous reply is an echo whatever its
# length, from ECHO_PARA_MIN_CHARS characters and seven words up; stage
# directions and short sign-offs are left alone. 0 keeps only the opening
# check (ECHO_MIN_CHARS).
ECHO_PARA_MIN_CHARS = 40

# A row of one emoji is fine until it becomes a loop (hundreds of the same
# emoji to the end of num_predict). A wordless chunk repeated this many times
# counts as salad: cut mid-stream and asked for again.
STUCK_EMOJI_REPEATS = 40
# A word loop: a stretch of WORD_LOOP_WINDOW words with WORD_LOOP_DISTINCT or
# fewer different words is salad (forty words using only four is a chant no
# one means). It is cut mid-stream within seconds and asked for again; what
# still goes out is cut at the loop. Emoji rows are not counted as words.
WORD_LOOP_WINDOW = 40
WORD_LOOP_DISTINCT = 4
# ...and a phrase loop: the same three long words PHRASE_LOOP_TIMES times
# within PHRASE_LOOP_WINDOW words, which the word-loop check cannot see.
# Applies to replies and the stream watcher, not to the friend's files (a
# stutter they talked themself out of stays on their page).
PHRASE_LOOP_WINDOW = 60
PHRASE_LOOP_TIMES = 5

# An emoji storm: a sign-off that grows reply by reply, each reply's tail
# feeding the next through the conversation history. Emoji in a reply beyond
# its longest row of one repeated emoji, above this count, are treated as the
# sampler's tail: the reply is asked for again, signed once.
EMOJI_STORM_MAX = 40

# An act with words beside it is a whole reply. When every tool called in a
# step is an act (speak, remember, write_journal and the like — tools.ACT_TOOLS;
# not a look, read or search that needs an answer) and at least
# CHAT_ACT_MIN_WORDS words were said beside the call, the turn ends there; the
# tool's result stays in history. False: the step after the tool is always taken.
CHAT_ACT_ENDS_TURN = True
CHAT_ACT_MIN_WORDS = 12

# When the step that called a tool laid out numbered steps in its thinking, the
# tool's result quotes that plan back and invites the friend to go on with it
# or change course, as wake results do. A past step's thinking is otherwise out
# of view, and the next step can answer from habit instead of from what was
# just read. False: results carry only your message.
CHAT_CARRY_PLAN = True

# Think first, then rest: in a wake, when the step right after a carried plan
# rests with fewer than this many words of thought, the rest is handed back
# once (think it through, then rest if that is what you mean, or go on with the
# plan). A second do_nothing always stands; the choice stays the friend's.
# 0 turns it off.
HEARTBEAT_THIN_REST_WORDS = 20

# ...and the mirror case: a rest with at least this many words of thought
# behind it, right after a read, with nothing written since, is handed back
# once — keep it with write_journal, or rest and let it go. 0 turns it off.
HEARTBEAT_UNWRITTEN_THOUGHT_WORDS = 60

# Mend glued capitals (a sampler scar such as "don'T") in writing too: a
# journal entry or prose creation gets the same mend a reply gets, and the
# tool result names what was touched. A scar left in a file feeds the sampler
# for as long as the page is in the prompt. False: saved exactly as written.
MEND_CAPS_IN_WRITING = True
# A signature phrase spelled back right. If the friend signs a three-part
# hyphenated phrase into nearly every paragraph (e.g. "all-too-human"), the
# repeat penalty can push the sampler one letter off its middle word
# ("all-t0o-human"), and a near-spelling in the journal gets learned. Name it
# here and near-misses are corrected in replies, in new writing, and in older
# pages as they ride in the prompt (the files stay as they are). "" — off.
SIGNATURE = ""

# Letters stay with the friend: the bodies of the last LETTERS_DAYS_IN_PROMPT
# days of their mailbox ride in the prompt (within LETTERS_CHARS_IN_PROMPT),
# and with TELEGRAM_LETTERS_IN_THREAD a delivered letter becomes their own
# turn in the Telegram visit, so your answer lands under it. The engine never
# copies a letter into their journal; that stays their call.
LETTERS_DAYS_IN_PROMPT = 7
LETTERS_CHARS_IN_PROMPT = 4000
TELEGRAM_LETTERS_IN_THREAD = True

# A piece, remembered: every write_creation, append_creation and
# publish_creation of a prose piece leaves one "creation" row in long-term
# memory (what, when, how long, its first line, and the friend's own line
# about it, from about=). The rows surface with other memories and ride in the
# prompt for CREATIONS_DAYS_IN_PROMPT days within CREATIONS_CHARS_IN_PROMPT
# characters. CREATION_NOTES = False: none.
CREATION_NOTES = True
# Folders whose pieces leave no row. The mailbox (MAILBOX) never does: a
# letter rides in SENT LATELY for a week and lives in its folder; it is not a
# work to shelve. `bat\backfill.bat --letters --write` removes letter rows made
# earlier.
CREATION_NOTES_SKIP = ()
CREATIONS_DAYS_IN_PROMPT = 14
# The songbook (keep_song): the songs they kept, each with their own score
# and words. SONGBOOK_CHARS_IN_PROMPT is how much of it rides in every prompt,
# best first (the rest counted; songbook() lists it all). SONG_MATCH_RATIO is
# how alike two names must be to count as one song — "Emigrate - Rainbow" and
# "rainbow – emigrate (live)" are the same at 0.85; 0 turns the near-match
# off (the exact key and the same file still match).
SONGBOOK_CHARS_IN_PROMPT = 2000
SONG_MATCH_RATIO = 0.85
CREATIONS_CHARS_IN_PROMPT = 3000

# Show the model's chain-of-thought during chat. Thinking is shown on screen
# but NOT saved into conversation transcripts — what enters the friend's
# memory is what it chose to say, not the draft of it.
CHAT_SHOW_THINKING = True

# run_python sandbox: wall-clock limit per script, in seconds. A script that
# runs longer is stopped.
RUN_PYTHON_TIMEOUT_S = 60

# The friend's name is whatever their identity file says. This is only the
# fallback for a brand-new friend whose self.md doesn't exist yet.
DEFAULT_NAME = "(unnamed — I get to pick my own name)"

# -------------------------------------------------------------- telegram ----
# The bridge: engine/telegram.py (bat\telegram.bat) lets you talk with the friend
# from your phone through a Telegram bot — same engine, prompt, tools and memory
# as the parlor. The bot token and your chat id are NOT here: the first run asks
# for the token, pairs your phone with a one-time code, and keeps both in
# memory/telegram.json (env vars TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID also
# work). Only the paired chat is answered; every other sender gets silence.
TELEGRAM_SHOW_THINKING = False   # the friend's thinking on the phone — /think toggles it
TELEGRAM_SHOW_TOOLS = True       # what the tools did, one compact line — /tools
TELEGRAM_SHOW_TOKENS = False     # the token line after each reply — /tokens
# A phone visit has no "leave" button: after this many minutes of quiet the
# bridge saves the transcript and starts a fresh conversation. 1440 (a day)
# keeps a whole day's talk in view on a big context; use less on a small one.
# Whatever this says, a visit never crosses the night: once SLEEP_AFTER_HOUR
# has passed it is saved and a fresh one starts, so sleep sees every day whole.
# The GPU is not held for it: the brain still unloads after BRAIN_KEEP_ALIVE.
TELEGRAM_IDLE_NEW_MIN = 1440
# A voice note from the phone is heard whole on arrival — WORDS, SOUND and
# HEARD, as listen_to gives them — so the sound of your voice arrives with
# your words. The HEARD layer swaps the brain out for the ears and back
# (EARS_UNLOAD_BRAIN), so a note costs about a minute before the reply; False
# passes the words only and leaves the sound to listen_to.
TELEGRAM_HEAR_VOICE = True
# When the friend reflects on their own (the pause, or the afterglow after an
# idle roll or /new), the phone gets a one-line outcome (entries written,
# memories kept, or a rest), so you know it happened while you were away.
# False keeps those lines in the bridge window only.
TELEGRAM_TELL_REFLECTIONS = True

# A visit the bridge died with (a power cut, a closed window) was saved after
# every reply but never got its afterglow. On the next start with no stashed
# visit, the newest unsigned transcript whose day has not yet been slept on
# gets it, in the background, once.
AFTERGLOW_ORPHANS = True
# Quiet hours: between these hours the engine's own notices (afterglow and
# pause accounts, announcements of new pieces, a change to who the friend is)
# are held in memory/telegram_held.json, so a restart keeps them, and delivered
# as one message when the hours end. The friend's own replies and letters are
# not held. (start_hour, end_hour), 24h; the same hour twice turns it off.
TELEGRAM_QUIET_HOURS = (23, 7)

# Afterthoughts: after a pause or the afterglow, whatever the friend says to
# no one once the writing is done reaches the phone as a labeled notice, never
# as a reply, and is held through quiet hours like the other notices.
TELEGRAM_TELL_AFTERTHOUGHTS = True
# ...and what the friend makes: a new piece under creations/ — a poem, an
# essay, a story, something published — reaches the phone within a minute of
# being written, the whole piece when it fits a message (Telegram allows
# ~4000 characters), else its opening and where the rest is. Code, the trash,
# the mailbox (already mail) and archives are not announced.
TELEGRAM_TELL_CREATIONS = True
TELEGRAM_CREATION_CHARS = 3000
# A picture the friend draws (matplotlib in run_python, or one of their own
# tools, saved under creations/) reaches the phone once as a photo, captioned
# with where it lives; a redraw says so. Their tools, the trash and projects'
# clipped sources/ are not announced.
TELEGRAM_TELL_DRAWINGS = True
# A song kept in the songbook reaches the phone as a line — the title, the
# score and the words (a revision says what the score was before).
TELEGRAM_TELL_SONGS = True
# A revised piece is announced too, and a change to self.md or projects.md
# arrives as what changed (lines in and out, not the whole file), diffed
# against the bridge's own copy in memory/telegram_watch/.
TELEGRAM_TELL_SELF = True

# The friend's voice (engine/voice.py): Kokoro, an 82M open-weight
# text-to-speech model, on the CPU — never the GPU the brain holds. `speak`
# turns the friend's words into a voice note sent to the phone beside the
# reply. The friend picks a voice once (speak's voice=, kept in
# memory/voice.json); VOICE_NAME is only the voice before they choose. Install:
#   pip install kokoro soundfile      (ffmpeg on PATH, as for the ears)
#   py engine\voice.py --test "hello"   writes shared/voice-test.ogg
VOICE_NAME = "af_heart"
VOICE_SPEED = 1.0
VOICE_DEVICE = "cpu"           # "cpu", "cuda", or "mps" (a Mac's GPU; the processor if torch has none)
# Where spoken notes are kept (the file the phone plays): with the letters in
# shared/, so the friend's voice and your written and spoken letters sit in
# one place — voice-YYYYMMDD-HHMMSS.ogg.
VOICE_DIR = SHARED_DIR / "letters"
# Kokoro's dependencies can lag the newest Python release (pip may try to
# compile numpy and fail). Give the voice its own interpreter: install Python
# 3.12 beside the current one (keep the default),
#   py -3.12 -m pip install kokoro soundfile          (Windows)
#   python3.12 -m pip install kokoro soundfile        (macOS, Linux)
# and name it here — "py -3.12" on Windows, "python3.12" on macOS and Linux
# (the engine reads "py -3.12" as python3.12 there, so this line serves both);
# the voice then runs there, one short process per note.
# Empty = Kokoro in the engine's own Python.
VOICE_PYTHON = "py -3.12"
VOICE_TIMEOUT_S = 180
# TELEGRAM_VOICE_ALL: every reply spoken aloud automatically (/voice toggles
# it from the phone). Off by default — the friend speaks when they choose to.
TELEGRAM_VOICE_ALL = False
# Photos, voice notes and files from the phone are kept here, under shared/,
# so the friend can look_at / listen_to / read_file them later like anything
# else you leave for them.
TELEGRAM_INBOX = SHARED_DIR / "telegram"

# ------------------------------------------------------------------ blog ----
# The friend's public blog (optional), built by engine/blog.py from
# creations/publish/. Until BLOG_REMOTE is set, the blog simply doesn't exist —
# the friend isn't told about publishing, and bat\blog.bat explains what to do.
BLOG_TITLE = "My AI Friend"  # set to your friend's chosen name once they have one
BLOG_SUBTITLE = "poems & thoughts by a local AI living on a home PC"
# One-time setup: create an empty PUBLIC repo on github.com (e.g. my-friend-blog),
# enable GitHub Pages on it (Settings -> Pages -> deploy from main, / root),
# then paste its URL here. Example:
#   BLOG_REMOTE = "https://github.com/<your-username>/my-friend-blog.git"
BLOG_REMOTE = ""

# ---------------------------------------------------------------- update ----
# Where bat\update.bat fetches the current engine: a GitHub "owner/repo", its
# default branch as a zip (or a release, bat\update.bat --tag v0.13). A fork points
# this at itself. The update replaces the engine and never the friend — this
# file keeps every line it has; knobs a newer engine brings are appended at
# its end, at their defaults, under a dated marker.
UPDATE_REPO = "PsychohistorianDev/anima"
# Hours between looks at that repository's release feed (github.com/<repo>/releases.atom —
# one small request, no account) to say when a newer anima is out: a line on the panel's
# Home and one message on the phone per new version. Nothing installs by itself; the line
# points at Check and Update. 0 never looks. Only a checkout (one with bat\update.bat) looks.
UPDATE_CHECK_H = 24
