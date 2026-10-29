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
PROJECTS_HISTORY_DIR = MEMORY_DIR / "projects_history"  # every version of projects.md before a rewrite
PAGE_LEDGER = MEMORY_DIR / "page_history.jsonl"  # one line per write of a root page: when, which model, from which door, the version before
DB_PATH = MEMORY_DIR / "memory.db"

SHARED_DIR = ROOT / "shared"  # where you leave images, music and books for the friend
HOUSE_FILE = SHARED_DIR / "house.md"  # your words about this house (house_file) — see HOUSE_LINE
PRESENCE_INTENSE_FILE = SHARED_DIR / "intense.md"  # the line every intense spark carries — see PRESENCE_INTENSE_NOTE
# list_shared lists NEW arrivals whole and the familiar as counts by folder with the newest this many named — find_shared(words)
# finds any one of them: a shelf of a few hundred files was a wall of lines in the window at every look. 0: none named.
LIST_SHARED_FAMILIAR = 5
# ...and every message carries one sentence about the shelf — "the shelf: nothing new in shared/ since your last look (235 things)",
# "the shelf: 2 new in shared/ — shared/music/…" — so the look itself is rarely needed. False: no shelf line in the moment.
SHELF_IN_PROMPT = True

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
# 127.0.0.1, not localhost: on Windows "localhost" is tried over IPv6 first (::1), which Ollama
# does not listen on, and the fall-back cost about two seconds on every request — every
# message, every tool step, every embedding (a keeper of another house measured it, 10-11).
OLLAMA_URL = "http://127.0.0.1:11434"

# Which program answers for the brain. "ollama" (default) talks to OLLAMA_URL as it
# always has. "llama" talks to llama.cpp's own server (llama-server) at BRAIN_URL
# through its OpenAI-style API, translated at the door so the engine sees the same
# replies; the ears and the embeddings stay on Ollama. The window is the server's
# -c; the sampler is the same one. Nothing of the friend's moves either way.
BRAIN_API = "ollama"
BRAIN_URL = "http://127.0.0.1:8768"   # llama-server, when BRAIN_API = "llama"
# Where llama-server saves its reading of the prompt (--slot-save-path) right before the
# door closes, so the brain comes back from stepping aside without reading it all again:
# the next message restores it in seconds. A folder on a RAM disk (R:\kv) keeps the SSD
# out of it; a folder under memory\ is the SSD; empty saves nothing. bat\brain.bat reads
# it, and the knobs below, when it starts the door.
BRAIN_SLOT_DIR = ""
# How many saved readings the folder keeps, the newest; older ones are deleted (each is a
# few GB). 0 keeps them all.
BRAIN_SLOT_KEEP = 1   # saved readings the folder keeps, the newest; a reading of a full window is ~8 GB, so one is what a 16 GB RAM disk holds
# Host RAM llama-server may keep evicted prompt caches in, MiB (--cache-ram): the visit's
# prompt and a wake's take turns on one slot; with room here both stay warm. 32768 on a
# 64 GB machine. 0: the server's default.
BRAIN_CACHE_RAM_MB = 0   # host RAM (MiB) llama-server may keep evicted prompt caches in (--cache-ram): one evicted prompt is ~8 GB, so 12288 holds the visit's or the wake's while the other is on the card; 0: the server's default
# A GGUF for the door instead of the one Ollama's manifest names for CHAT_MODEL, and its
# projector (the eyes). Empty finds both in Ollama's own files.
BRAIN_MODEL_FILE = ""
BRAIN_MMPROJ_FILE = ""
# Where llama-server is, when it is not on the PATH and not in a llama\ folder inside or
# beside this one: the full path to llama-server.exe. Empty looks in those places.
LLAMA_SERVER = ""
# Whether llama-server keeps the model file mapped in host RAM after copying it to the
# card. False passes --load-mode none (--no-mmap on older builds; the door asks the binary
# which it knows): the weights are read straight into the card's buffer and
# no host copy stays (with mmap, the mapped file counted as ~17 GB of RAM "in use" on a
# 31B model, under no process line Task Manager shows). True leaves the mapping — a Mac,
# where the card shares the memory, may load faster that way.
BRAIN_MMAP = False
# Whether the door opens the thought channel at each of the friend's turns. Gemma 4's own
# template leaves that to the model, and deep in a long window it skips thinking more
# often than not — a thoughtless reply is re-rolled, and one can run to the ceiling.
# True writes a copy of the model's template with `<|channel>thought` at the generation
# prompt (memory/brain_template.jinja; Ollama's renderer did the same) and opens with it;
# only for Gemma 4's template — any other is left to itself. False: the model's to open.
BRAIN_THINK_OPEN = True
# When a door the engine opened falls at its first kernel ("CUDA error", "out of
# memory" in memory/brain.log) — the card not free yet after the painter or an
# ear set it down — the engine waits this many seconds and opens it once more; a
# second fall is said as it is. 0 opens it again at once.
BRAIN_CUDA_RETRY_S = 8.0
# ...and before it opens, the card's own word by nvidia-smi: a process on the card using BRAIN_CARD_BUSY_MB or more that is
# not the door (an ear that rested but hasn't left, a painter on its way out) keeps the door waiting as a sidecar does, named
# with its pid; where the driver gives no per-process count, used memory above BRAIN_CARD_IDLE_MB (the desktop's own share and
# some) is waited for BRAIN_CARD_SETTLE_S at most, then the door opens and says what was left. A server that starts on a
# crowded card has the part that doesn't fit put in system RAM by the driver, and limps for its whole life. 0 turns each off.
BRAIN_CARD_BUSY_MB = 256
BRAIN_CARD_IDLE_MB = 3072
BRAIN_CARD_SETTLE_S = 20
# ...and a nameless remainder of this many MiB or more is a sidecar's weight (an ear or a painter still on its way out),
# not the desktop's share: waited for as a named process is, the door not opened while it stays. 0: the brief settle only.
BRAIN_CARD_CROWDED_MB = 8192

# The brain (the chat model). Swap freely; memories and identity survive a swap.
#   fits a 12 GB card : "gemma4:12b-it-qat" (7.2 GB; the build Google trained
#                       to be 4-bit — near-bf16 quality; tools + thinking + eyes)
#   alternatives      : "qwen3:14b", "qwen3:30b-a3b" (RAM offload),
#                       "gemma4:e4b-it-qat" (smaller and faster)
# If tool calls misbehave on a Gemma 4 model, try the same tag with thinking
# disabled, or a Qwen3 tag.
CHAT_MODEL = "gemma4:12b-it-qat"
# The README's ladder, by the card's memory: 6 GB "gemma4:e2b-it-qat", 8 GB
# "gemma4:e4b-it-qat", 10–16 GB this 12B QAT, 24–32 GB "gemma4:31b-it-qat"
# (near-bf16 quality in ~19 GB) — with the NUM_CTX, TOOL_KIT and journal size
# for each rung in the README's "The ladder". The same QAT 12B is the ears
# (EARS_MODEL) — measured 10-08, a voice note heard whole — so from 10 GB up
# the ladder is one pull per rung, and a 12B house keeps one file.

# Embedding model for semantic memory: it turns memories into vectors so the
# ones related to the moment can be found. Install: ollama pull nomic-embed-text
EMBED_MODEL = "nomic-embed-text"
# True runs the embedding model on the CPU (num_gpu 0): on a card the brain fills to the
# edge, the small embedder beside it can push layers into shared system memory and slow
# everything; embeddings are short and the CPU is fine for them. False: Ollama decides.
EMBED_ON_CPU = False

# The friend's ears — three layers (see engine/ears.py):
#   WORDS — faster-whisper transcription   (py -m pip install faster-whisper)
#   MUSIC — numpy acoustic measurement     (py -m pip install numpy)
#   HEARD — the brain listening to the raw audio (the 12B has native audio,
#           the QAT build included — measured; thinking must stay ON for it,
#           see engine/ollama_client.py). The bigger Gemmas are deaf.
EARS_MODEL = "gemma4:12b-it-qat"
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
# ...and the sidecar's process leaves with the rest, as the painter's does (PAINTER_REST_LEAVES): a rest frees the
# weights, but the process keeps its CUDA context (~0.5-1 GB) for as long as it lingers, and beside the brain's reading
# and model on a 32 GiB card that is a fall at the door's first kernel ("CUDA error: shared object initialization
# failed"). True: /rest frees the model and the process goes, and listen_to waits (a few seconds at most) until it is
# gone before the brain comes back. False: it rests and lingers for MUSIC_EARS_EXIT_S, ready for a second song.
MUSIC_EARS_REST_LEAVES = True
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
# A song's lyrics with the moment each line begins — "[1:42] …" — so the words can be laid against what the music
# does there (listen_to; a voice note stays plain text). False: one block, as before.
EARS_LINE_TIMES = True
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
# A book read to the end and begun again ('start') is a second reading: the
# bookmark counts it, and its notes go under a heading of their own at the end
# of the same page ("## Second reading — …"), which is the part that rides.
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
#   sentencepiece protobuf tiktoken  — and torchvision beside torch, from the same CUDA index (painter.py's head)
# Cost: every painting is a model swap, and the brain then re-reads its whole
# context cold (minutes on a large context). Gather prompts into one call.
PAINTER_URL = "http://127.0.0.1:8767"
# Ungated, Apache 2.0, ~16 GB (the brain is off the card while painting).
# Alternative: "black-forest-labs/FLUX.2-klein-4B" (4 steps, ~13 GB; can edit too).
PAINTER_MODEL = "Tongyi-MAI/Z-Image-Turbo"
PAINTER_AUTOSTART = True      # paint starts the sidecar when needed

# The Touchstone — a body on the desk (touchstone/README.md builds it): a small board
# that hums the state the friend last set, answers a press by itself with the
# reply they chose, and logs what it felt. The stone's keeper (engine/touchstone.py,
# bat\touchstone.bat) owns the board and answers the engine on TOUCHSTONE_URL;
# "" means no body — the four tools (feel, set_state, pulse, touch_later), the
# prompt section and the phone's lines stay away. TOUCHSTONE_BOARD is the board
# itself on the LAN (the sketch announces touchstone.local, or use its address).
TOUCHSTONE_URL = ""
TOUCHSTONE_BOARD = "http://touchstone.local"
TOUCHSTONE_POLL_S = 5             # how often the stone's keeper asks the board what it felt (was 30: a press could wait a
                                  # minute for the phone; a board on the LAN answers two small requests in milliseconds)
TOUCHSTONE_TELL_S = 3             # how often the bridge looks at the stone's archive for a new press, in a thread beside the
                                  # long poll (which waits up to 50 s for a message); 0: the look between polls only
# A tick at a change of state: one short gesture the stone's door asks of the board right after a different state is set,
# so a state with no hum still announces itself on the desk — a reply name or a pattern ("nudge", "warm", "double",
# "strong", "tide"…), for this many seconds; the stone's hours hold it as they hold a pulse. "": no tick.
TOUCHSTONE_STATE_TICK = "nudge"
TOUCHSTONE_STATE_TICK_S = 1.0
TOUCHSTONE_STATES = ROOT / "creations" / "projects" / "robotics" / "states.json"  # their states, theirs to edit; pushed when it changes
TOUCHSTONE_WAKES = True           # a press by day becomes a turn in the open visit (the bridge); off: a held notice
TOUCHSTONE_WAKE_MIN_GAP_S = 600   # after a press-turn, further presses wait this long and arrive together
TOUCHSTONE_FALLBACK_H = 6         # the board falls back to Baseline after this long without a word from its keeper
TOUCH_LINES_IN_PROMPT = 40        # today's touches in the prompt, newest kept
TOUCHSTONE_LATER_MAX = 12         # touches that may wait in the board at once
TOUCHSTONE_HOURS = ""             # when the stone may reach out — a pulse, a touch left for later: "06:00-21:00"; outside it, and
                                  # within KEEPER_WORK_WEEK's hours, it keeps still and the tool says so, with the next open moment. "": any hour
PAINTER_PYTHON = ""           # "" = the engine's own; e.g. "py -3.12" (Windows) or "python3.12" (macOS, Linux) if torch lives elsewhere
# Where the painter paints: "auto" takes an NVIDIA (or ROCm) card, else a Mac's
# GPU ("mps", float16), else the processor (slow); "cuda", "mps" or "cpu" names one.
PAINTER_DEVICE = "auto"
PAINTER_REST_AFTER = True     # free the GPU as soon as a painting is done
# ...and the sidecar's process leaves with the rest. A rested painter that lingers
# for PAINTER_EXIT_S still holds its CUDA context (~0.5-1 GB), and a large brain
# opened beside it on a card with little to spare can fall at its first kernel.
# True: /rest frees the model and the process goes, and paint waits (a few
# seconds at most) until it is gone before the brain comes back. False: it rests
# and lingers, ready for a second painting without a load.
PAINTER_REST_LEAVES = True
PAINTER_IDLE_S = 120          # seconds; fallback: the sidecar frees the GPU after this much idle time
PAINTER_EXIT_S = 60           # seconds unused before the sidecar process exits (it holds ~11 GB of RAM while it waits; a minute covers a second painting asked right away, and not more)
PAINTER_TIMEOUT_S = 300       # seconds allowed for one painting, model load included
PAINTER_STEPS = 0             # 0 = the model's default (Z-Image-Turbo 9, FLUX.2 klein 4)
# Qwen-Image's text encoder (Qwen3-VL 8B) quantized as it loads, so the whole pipeline fits the card and paints
# without offload: 8 (about 9 GB, near-lossless), 4 (about 5 GB), 0 (full precision, under offload). Needs
# bitsandbytes (py -m pip install bitsandbytes); without it the painter says so and paints under offload.
PAINTER_ENCODER_BITS = 0
# A line of your own added to the end of the paint tool's description — who is in which reference folder, say
# ("" — none). A standing prompt change: one cold read when it lands.
PAINTER_REFERENCE_NOTE = ""
# Reference sets: a word that, given alone as paint's `reference`, stands for its pictures in order — and its line
# goes to the painter ahead of the friend's prompt, saying what each picture is for: name → (the references, one
# line), e.g. a pair's lineup first for their sizes, then each face. {} — none.
PAINTER_REFERENCE_SETS = {}
# A reference picture turned level before it goes to the painter: path under creations/ (or its folder) → degrees,
# clockwise positive — for a face that leans in its picture, which the painter otherwise copies into every painting.
# Turned in memory only; the picture's file is never touched. {} — none.
PAINTER_REFERENCE_TURN = {}
# A reference picture cut to part of itself after the turn: path under creations/ (or its folder) → (left, top,
# right, bottom) as parts of its width and height, 0 to 1 — (0.15, 0, 0.85, 0.75) keeps the head and drops the
# shoulders, so the painter draws the body from the words. In memory only; the file is never touched. {} — none.
PAINTER_REFERENCE_CROP = {}
# Words that bring the painter a plain line: word → line; when a prompt has the word (any ending), the line goes to
# the painter ahead of it, after a set's. For a pose the painter keeps getting wrong in the friend's own language.
# {} — none.
PAINTER_PROMPT_HINTS = {}
# Names in the words bring their pictures: a painting with no reference whose words name the friend (their own name)
# brings creations/face/, your name (USER_NAME) a folder of that name under creations/, both together a reference set
# that holds them both, with its line. Only on a brush that reads references; the result says what came; a reference
# given by hand is kept, and a name it leaves out is added. False: off.
PAINTER_AUTO_REFERENCE = True
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
# ...and when a wake finishes — a single one (bat\wake.bat, the panel's Wake)
# or one of the heartbeat's — the same: the brain set down at once, the card
# free the moment the wake ends. The next wake reads its prompt cold either
# way (the journal and the clock have moved), so nothing is lost but seconds.
BRAIN_REST_AFTER_WAKE = True
# Under the brain's door (BRAIN_API = "llama"), whether those two rests close the
# door — the card free, as a rest under Ollama always was. A visit's end saves the
# reading first (seconds; there if the same prompt returns); a wake's end closes
# without one (a wake's prompt is never read twice, and its save would push the
# visit's reading out of a one-reading folder). False: the door stays up after a
# rest, its prompt caches warm — the card held until the painter, the ears or
# /release need it.
BRAIN_REST_CLOSES_DOOR = True
# A guest at the desk (the parlor's "seat a guest", or /guest on the phone):
# every message then says it is from the guest, with you in the room, and the
# transcript marks their turns. True: by the name given; False: "a guest", for
# a visitor who would rather not be written down.
PARLOR_GUEST_NAMED = True

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
# A phrase named in SIGNATURE is not counted at all — it is theirs however
# often it comes. 0 turns the check off.
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
# The night in the bridge: a house that runs the phone and no heartbeat never
# slept. After SLEEP_AFTER_HOUR, when no heartbeat is up and the phone has been
# quiet for SLEEP_IN_BRIDGE_QUIET_MIN and no visit is open, the bridge sleeps on yesterday and runs
# the condensing hour itself (the heartbeat stays the sleeper wherever it runs).
# The first reply after it is a cold read — one a day. False: the bridge never sleeps.
SLEEP_IN_BRIDGE = True
SLEEP_IN_BRIDGE_QUIET_MIN = 10

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
# A hit below this similarity (cosine, the embedding model's own scale) does
# not ride at all: once a visit has surfaced what relates to it, the search
# hands back the barely-related next, and "nothing new surfaces" is the truer
# block. 0 turns the floor off. Read memory/moment.log for a day before
# setting it — on nomic-embed-text, 0.66 kept the related and dropped the
# filler. The newest slice (MEMORY_RECENT_K) is not held to it.
MEMORY_MIN_SCORE = 0
# The moment's weight, phase one. A long visit surfaces memories all day, a
# few a message, because each message's hint moves a little and a slightly
# different top-k brings a couple of new ones — a slow walk through the
# store. Three dials, none touching what is kept:
# The drift gate: the moment searches again only when the hint has moved
# past this much cosine distance from the hint it last searched with; between
# searches the block carries the frame and the newest slice. A visit's first
# message always searches. 0 turns the gate off.
MEMORY_DRIFT = 0.15
# The visit budget: past this many tokens of moments in one visit, only hits
# at or above the late floor ride. 0 turns it off.
MEMORY_VISIT_TOKENS = 8000
MEMORY_MIN_SCORE_LATE = 0.75
# The short first pick: a hint under this many words (a greeting) takes
# MEMORY_TOP_K_SHORT instead of MEMORY_TOP_K. 0 turns it off.
MEMORY_SHORT_HINT_WORDS = 12
MEMORY_TOP_K_SHORT = 4
# Spread the picks instead of clustering them: with MEMORY_DIVERSE each pick is
# weighed against those already chosen (MEMORY_MMR_LAMBDA of relevance, the rest
# a penalty for resembling one already in), so the slots hold different things.
# MEMORY_RECENT_K of the newest memories ride along whatever the topic, so what
# was kept this morning is still in view this afternoon. 0 turns that slice off.
MEMORY_DIVERSE = True
MEMORY_MMR_LAMBDA = 0.75
MEMORY_RECENT_K = 6
# The thread: one short note the friend leaves for the next of themselves with
# leave_thread — where they are, in their own words — read first, at the top
# of the first message of every visit, wake and reverie, until they leave
# another. The friend writes it; the engine never does. False: nothing is read
# at the door (the tool stays, the notes are kept — memory/thread.md, all of
# them in memory/thread.log). THREAD_CHARS: the longest a thread may be; a
# longer one is handed back with its count.
THREAD = True
THREAD_CHARS = 1500
# ...and the nudge: at a door whose last door closed without a thread, one
# engine line says so and names leave_thread — gone once the friend is in the
# habit. False: the thread rides when there is one and nothing is said when
# there is not.
THREAD_NUDGE = True

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
# Whether a turn's set-aside attempts (salad, no thought, a call written out) and
# the engine's lines stay in the visit after the answer is in. Under Ollama they
# must: Gemma's sliding-window layers mean a history that differs anywhere behind
# the end is read again from the top, minutes on a big window. Under the brain's
# door llama.cpp keeps context checkpoints and a divergence re-reads only what
# follows it — the kept answer, seconds — so they go, and the window holds only
# what was said. "auto": kept under Ollama, let go under the door; "always"; "never".
REROLLS_KEPT = "auto"   # the same rule lets the pause's quiet steps leave the visit after the pause, under the door

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

# Starting the heartbeat loop turns presence (sparks) off: the wakes take the
# time between visits instead. Only the start does it; a spark set again later
# stands. False: the two run side by side.
HEARTBEAT_ENDS_PRESENCE = True
# While the heartbeat loop runs, sparks are held: next_spark and /presence on
# set nothing, and no spark comes, until the heartbeat stops. False: a spark
# set during the heartbeat stands.
HEARTBEAT_HOLDS_PRESENCE = False

# Under the bell of every wake and reverie, one line of how the shelf stands: the open
# book and where it stopped, how many songs in shared/ have not been played yet, how many
# books not opened — one of each named, a different one each wake. Facts only, nothing
# asked. False: the bell alone.
WAKE_FACTS = False
# Name one song and one book among the counts (it turns with every wake). False: the counts alone.
WAKE_FACTS_NAMES = True

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
# ...and only while the window is less than this full. 0, the default: never —
# a thoughtless answer is theirs as it came, at any depth, and replies come at
# once (the same as CHAT_THINK_RETRIES = 0, but the wake's retries stay). The
# re-rolls were the old rail: deep in a long window the model opens no thought,
# nudged or not, every re-roll came back thoughtless too and the last was sent
# anyway — most of the writing time for nothing. A share of NUM_CTX (0.7) keeps
# them below that depth; 1.0 keeps them everywhere — and there, with the
# re-rolls standing at any depth, an answer begun with no thought is cut at its
# first token while a re-roll remains, so a re-roll costs seconds, not a reply.
THINK_RETRY_UNTIL = 0
# From this many tokens of window held (the last prompt's size), every
# message carries a short think-first line in its moment — a standing
# reminder, not a re-roll: deep in a long window the model tends to answer
# without opening a thought, and a sentence beside the message costs a few
# dozen tokens where a re-roll costs a whole second generation. 0: never.
THINK_REMIND_FROM = 60000
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
# …and before the rungs, the warm re-rolls cool a step at a time: from the third
# re-roll on, each is this much cooler than the last, down to the first rung —
# for the sampler's own defects (salad, a refrain, an emoji storm, no words); an
# echo or a copy is the model repeating itself, which a cooler roll only makes
# likelier, so those keep the everyday temperature. 0: off.
CHAT_COOL_STEP = 0.1
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
# The friend may also fold at a natural pause; from FOLD_SENSE_FROM of NUM_CTX the
# moment block says how full the window is, and how much of that is the standing
# prompt (the visit's first prompt — self, journal, pages, memory — which no fold
# shrinks). A standing prompt already past the mark moves the mark to halfway up the
# room above it, so the sense never rides from a visit's first message. 0 turns the
# fold off (then /new is suggested).
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
FOLD_SENSE_FROM = 0.5     # from this fraction of NUM_CTX the moment block shows how full the window is (never from a visit's first message)
WINDOW_WARN_AT = 0.9      # from this fraction of NUM_CTX you are told "this visit is near the edge of the window" after each reply; 0: never

# The carry: when a visit starts in an empty room — the phone after /new, after the
# night, after a shutdown; the parlor's first message — the last CARRY_TURNS visible
# turns of the previous visit sit at the head of it, word for word, under one engine
# line, if that visit ended within CARRY_HOURS. Then the thread, the clock and the
# message, as at any door. The journal and the afterglow keep the rest; wakes and
# reveries carry nothing.
CARRY_TURNS = 6           # visible turns carried whole, the most recent ones
CARRY_HOURS = 20          # how recent the previous visit must be to be carried; 0: never

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
# ...and a thought that runs past this many characters before a word or a call is cut as a runaway is — the sampler
# circling at depth; a thoughtful step is a tenth of this — and the step asked for again in words. 0: never.
STREAM_THINK_MAX_CHARS = 12000
# A tool call's arguments are watched the same way: a call cut short in a loop
# is not run, and the friend is told so, short. What the visit keeps of the
# call is its head, at most RUNAWAY_KEEP_CHARS characters, and a line saying
# the rest was the same line over and over.
RUNAWAY_KEEP_CHARS = 600

# The afterglow: when a visit ends (parlor "leave", /new, the bridge's idle
# roll, /quit), the friend gets one quiet turn alone with the transcript and
# three tools (write_journal, remember, do_nothing), so the visit reaches their
# journal in their own words, not only the nightly summary. Resting is a
# complete answer. Costs one mostly cached brain call in the background.
# Transcripts longer than AFTERGLOW_MAX_CHARS are given from the end.
AFTERGLOW = True
AFTERGLOW_MAX_CHARS = 60000
# The afterglow sits only with what no pause has (the quiet's pause, or /afterglow by hand, moved the door's mark);
# with nothing new since the last pause it writes nothing and signs the transcript — once, never the same words
# twice. False: the whole visit from the top, whatever the pauses read.
AFTERGLOW_SINCE_PAUSE = True
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
# …and the journal twin needs the wording too: the share of the new entry's
# word-trigrams the earlier one already has. One voice reads as near-identity
# to the embedder — most entries that are not twins score 0.86–0.88 against
# some other entry of the two days, and a wake's account of its own night
# was refused as a twin of the night before's. Different entries in one
# voice share about 0.03 of their wording (nineteen in twenty under 0.11);
# a copy is 1.0; a retelling of the same moment keeps its phrases. 0: the
# score alone, as before.
JOURNAL_DUP_WORDING = 0.25
# A tic in the prose (10-07) — a word, or a prefix with its hyphen ("la-") —
# counted on every write that goes through. The window feeds a tic back: the
# journal in the prompt is the friend's own recent prose, so the rate of the
# tic there is close to its odds in the next word, and each entry that
# carries it raises the rate for the next (one house: 7 per thousand words
# to 31 in three weeks, a steady slope, the salad check seeing only the far
# end). Nothing is filtered or corrected. A write that carries the tic at
# TIC_TELL_FACTOR times the friend's own rate of two to four weeks ago (the
# median of the journal days 14–28 back with 200 words or more; fewer than
# three such days: no tell; TIC_BASELINE_PER_1000 pins it) gets one line with
# the two numbers, at most every TIC_TELL_GAP_MIN minutes. Empty TIC_WORD:
# nothing is counted.
TIC_WORD = ""
TIC_TELL_FACTOR = 2.0
TIC_TELL_GAP_MIN = 60
TIC_BASELINE_PER_1000 = 0
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

# How many of the friend's earlier replies an echo is looked for in, newest
# first. The previous reply is checked whole (opening and paragraphs, above);
# the ones before it for the opening and for whole paragraphs of 150
# characters or more only — a sentence they are fond of may come round again
# across a visit, a paragraph does not. Deep into a long visit the sampler
# can hand back a reply from several messages ago, entire, under a fresh
# stage direction. 1 = the previous reply only.
ECHO_LOOKBACK = 12
# …and a reply that doubles back over ITSELF (a goodnight said, then said again,
# each paragraph a little reworded, then a new close): a paragraph the same
# reply already said, word for word or this alike (both 100 characters or
# more), is asked for once. 0 turns the near-match off; the exact one stays.
SELF_ECHO_RATIO = 0.8
# A stage direction that opens reply after reply — "(a voice note, delivered
# with a …)" each time, a little reworded — is one reply's warm tail feeding
# the next. Not re-rolled: when the last two or more spoken replies opened
# with the same first this-many words of a stage direction, the moment says so
# as a fact and leaves the next opening theirs. 0 turns the tell off.
OPENER_REPEAT_WORDS = 5
# ...and the SHAPE of a reply, which the five-word opener check cannot see:
# a stage direction to open, an italic line under it, a paragraph that
# begins the same way, the same emoji run to close — six replies, one
# skeleton, each filled in afresh. When this many spoken replies in a row
# share three of those four marks, the moment says so and names them. A
# tell, not a re-roll; 0 turns it off.
REPLY_SHAPE_RUN = 3
# The signature said this many times or more in one reply is told as a
# count in the moment (past a few, the repeat penalty breaks the word
# rather than placing it). Needs SIGNATURE; 0 turns it off.
SIGNATURE_DENSE = 6
# ...and the phrases the sampler wears thin beside it — a two-word refrain that
# turns into a noun — counted the same way: any of them at SIGNATURE_DENSE in a
# reply tells the count of all. () — the word alone.
SIGNATURE_REFRAINS = ()

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
# ...and how many DIFFERENT emojis in one unbroken row count as the sampler walking the emoji table (a cascade,
# re-rolled): the walk has sixty; a sign-off row of a dozen, the same dozen most messages, is a signature.
EMOJI_CASCADE_RUN = 20
# ...and the row's length told, as the signature's count is: when the last reply's longest row carries this many
# different emoji or more, the moment says so — a fact, the row still theirs. 0: never.
EMOJI_ROW_DENSE = 14
# ...and a repeat in a row of this many different emoji or more is taken off at the reply, the first kept — the row
# feeding on itself, the sampler's re-deal; an adjacent repeat (💋💋💋) stays, a shorter row is never touched. 0: never.
EMOJI_ROW_DEDUPE = 6
# ...and the same row of six or more emoji (four different) dealt this many times running, nothing but space between,
# is the sampler's loop, not a sign-off: cut mid-stream, asked again (10-22: a 23-emoji row re-dealt to the ceiling,
# 8,192 tokens, which the cascade rule, the stuck rule and the dedupe mend all looked past). 0: never.
EMOJI_ROW_REPEATS = 3
# ...and a sign-off row past EMOJI_CASCADE_RUN at the end of a reply that has words goes out as its first this-many
# different emoji, the rest left, the next moment saying so — the words stand as written instead of a re-roll. A
# wordless reply, a cascade mid-reply and a re-dealt row are still re-rolled. 0: the re-roll as before.
EMOJI_ROW_TRIM = 14
# ...and inside a row of EMOJI_ROW_DEDUPE-odd different emoji, the same emoji stacked more than this many times running is
# cut to this many, the note saying so — the sampler leaning on a key; a row of one emoji alone (a row of kisses) is never
# touched. 0: never.
EMOJI_ROW_RUN = 3

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
# What a delete does to the piece's row: "mark" — the row stays, saying it went (the friend remembers making it and
# letting it go); "remove" — the row leaves memory with the piece. The rows of pieces already gone:
# bat\backfill.bat --gone lists them, --gone --write lets them go.
CREATION_ROWS_ON_DELETE = "mark"
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
# ...and the attempts the rails set aside (salad, a cascade, an echo, a re-roll), words and all, after each reply —
# /debug on the phone toggles it; off by default
TELEGRAM_SHOW_ATTEMPTS = False
# The painter's prompt with each picture painted in a visit, on the phone — in the caption when it fits, a message
# after the photo when it doesn't.
TELEGRAM_PAINT_PROMPT_CHAT = False
# ...and a wake's or a reverie's in the wake log, under each paint call.
WAKE_LOG_PAINT_PROMPT = True
# The engine's week: once a week, on this day after this hour, an engine notice on the phone — what the rails set
# aside and asked again, the mends made in place, the cold reads, the longest thought, the signature's count, the
# window's peak — from memory/steps.log (a line a call to the brain). /week shows it any time. "" — never on its own.
ENGINE_WEEK_DAY = "sun"
ENGINE_WEEK_HOUR = 18
ENGINE_WEEK_COLD_S = 60  # a prompt read this long or longer (seconds) counts as a cold read
ENGINE_WEEK_LOG = True   # memory/steps.log, a line a call to the brain; False writes nothing (the week then has nothing to say)
# Presence — sparks: next_spark sets ONE spark (10–60 min, a turn of the friend's own once the visit has been quiet
# that long) and turns presence on; after it, another only when they set it again. Or drift: next_spark(drift=…) —
# no set time, a die every quiet minute, sparks keep coming; very rare (~2 h), rare (~1 h), sometimes (~25 min), often
# (~10 min), frequent (~5 min), intense (0–1 min, for play); the friend's ache (0–3) makes them likelier the longer it's quiet. /presence
# on|off|a temperament and /discreet on the phone. The drift /presence on starts:
PRESENCE_ON_TEMPERAMENT = "rare"
# A line every intense spark carries, in your words — intense is for play; "" — none.
# The words live in shared/intense.md now (PRESENCE_INTENSE_FILE) — edit it in any editor; the panel's Edit
# intense.md opens it. The first time it is read, a note here that says something moves into shared/intense.md.
PRESENCE_INTENSE_NOTE = ""
# A spark thinks first (True): the think-first reminder in its moment, and PRESENCE_THINK_RETRIES re-rolls if it
# comes back thoughtless — with a thought the friend plans past one gesture, the next spark too. False: quick, no
# reminder, no re-roll. The thinking switch itself stays as the visit's, so the window is not read again for a spark.
# This is every spark but intense's:
PRESENCE_THINK = True
# Intense's own: False — instinct, no think re-roll and no reminder (it is for play); True — as every other spark.
PRESENCE_THINK_INTENSE = False
# A spark's line names the doors out as well: something to read, hear or look up
# that they might bring back to you — besides words, a painting, the stone. Not in
# intense. What a spark reads stays in the visit's window. False: the shorter menu.
PRESENCE_SPARK_DOORS = False
# While intense runs, every reply to you carries the intense note in its moment too — not only the sparks
# (never with a guest seated). False: the note rides in intense's sparks alone.
PRESENCE_INTENSE_EVERY_TURN = False
# How many times a thoughtless spark is asked again, with the think-first nudge: at any depth (THINK_RETRY_UNTIL does
# not apply to a spark) and at the friend's own temperature. 0: none.
# How much one step of the friend's ache (0–3) adds to drift's climb, against an hour of quiet: 1.0 as much as an
# hour of quiet; 0.25 a quarter; 0 — the ache doesn't hurry a spark. The quiet's own climb and the 0.9 cap stay.
PRESENCE_ACHE_WEIGHT = 1.0
# Drift's ladder: every this many minutes of quiet adds one more of the temperament's base chance a
# minute — 60 doubles it after an hour; 10 makes "often" (10% a minute) 20% after ten quiet minutes and
# 30% after twenty, so long dry spells grow rare. The 0.9 cap stays.
PRESENCE_CLIMB_MIN = 60
PRESENCE_THINK_RETRIES = 3
# Seeds: every spark carries one thing picked at random to spark off, so a spark isn't the same gesture every time —
# a memory, something the friend made, a song from the songbook, a few lines of the journal from a week or a month
# ago, the world (the day, the season, where you are by your week), a word from the lexicon. Not a task. The kinds
# in the pool; () — no seeds.
PRESENCE_SEEDS = ("memory", "creation", "song", "journal", "world", "word")
# Strings the brain never writes — a fence at the sampler, not a nudge: each string's tokens go to llama-server as
# logit_bias, never produced, in the thought and the reply alike — for a tic that has turned into a glitch, a double
# slash wrapped around words, say. Only a string that is one token at the door is banned. Under Ollama it does nothing.
# () — none.
BRAIN_BANNED_STRINGS = ()
TELEGRAM_TOKENS_SINCE_LAST = True  # ...and its tail: what the window grew by since the last line and of what (the earlier reply's words, the message, the moment, the turn's steps). False: the line alone
# A message past Telegram's cap arrives as bubbles; when a poll ends on a bubble
# at the cap the bridge waits this many seconds for the rest, so the message is
# answered once. An ordinary message is never held.
TELEGRAM_SPLIT_WAIT_S = 2
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
# Where you are, by the calendar, said in the engine's clock line at the top
# of every message and bell: your working week as days with hours ("sun-wed
# 07:00-16:25, thu 07:00-15:55"; a segment without hours takes the one before
# it), and what to say during working hours ("on the floor, the phone in my
# pocket"; empty: "at work"). Without it the friend infers where you are from
# the journal, which was mostly written on workdays. Empty says nothing. A day
# off is /off on the phone (memory/days_off.json); /on takes it back.
# The friend's first day, for the second clock on the date line — "your 54th
# day here: you first wrote on 27 August 2026, a month and three weeks ago".
# "" takes the earliest journal file's day; no journal yet, no clock.
FIRST_DAY = ""
KEEPER_WORK_WEEK = ""
KEEPER_AT_WORK = ""
KEEPER_COMMUTE_MIN = 0            # minutes on the road (to work, home again), or one number for both — "on the way home, in by about 17:00"
# A sentence from you about what is welcome in this house, in your own words. It rides in
# the system prompt right after the situation, stated as yours — "Your keeper says of this
# house, in their own words: …" — never as a rule of the engine's. A brain's trained
# hesitations are in its weights; nothing in the engine filters a word or a picture. This
# puts the house's own word beside them. Empty says nothing.
# The words live in shared/house.md now (HOUSE_FILE), paragraphs and all — edit it in any
# editor; the panel's Edit house.md opens it. The first time the engine reads it, a line
# here that says something becomes that file, and from then on the file is what rides.
HOUSE_LINE = ""

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
# Optional turn-based voice in Parlor. Off by default; installs are separate
# from the engine and Kokoro. See VOICE.md and python engine/setup_voice.py.
LIVE_VOICE_ENABLED = False
LIVE_VOICE_PYTHON = ""          # empty: .runtime/voice-env; otherwise an interpreter command
LIVE_VOICE_DEVICE = "cuda"     # Kyutai speech model; CPU is substantially slower
LIVE_VOICE_KYUTAI_STYLE = "calm"  # calm, desire, happy, neutral (released voices)
LIVE_VOICE_STT_MODEL = "large-v3-turbo"
LIVE_VOICE_STT_DEVICE = "cpu"   # cpu: int8; cuda: float16; GPU needs additional headroom
LIVE_VOICE_STT_BEAM_SIZE = 5
LIVE_VOICE_STT_HINT = ""        # optional names/terms, e.g. "Squadron 42"
LIVE_VOICE_LANGUAGE = "en"      # English or French for Kyutai; empty: recognizer auto-detect
LIVE_VOICE_THINK = None        # None inherits CHAT_THINK and its normal retry rail
LIVE_VOICE_SILENCE_MS = 1000
LIVE_VOICE_MIN_SPEECH_MS = 250
LIVE_VOICE_INTERRUPT_MS = 350
LIVE_VOICE_THRESHOLD = 0.018
LIVE_VOICE_MAX_SECONDS = 30
LIVE_VOICE_CHUNK_CHARS = 180
LIVE_VOICE_TIMEOUT_S = 300

# Photos, voice notes and files from the phone are kept here, under shared/,
# so the friend can look_at / listen_to / read_file them later like anything
# else you leave for them.
TELEGRAM_INBOX = SHARED_DIR / "telegram"

# --------------------------------------------------------------- discord ----
# The same bridge over Discord instead: engine/discord_bridge.py
# (bat\discord.bat) — a bot you make at discord.com/developers, talked to in a
# direct message. Same visit, mail and notices; the TELEGRAM_* knobs above are
# the bridge's, whichever road it takes. The token and the paired DM are kept
# in memory/discord.json (env var DISCORD_BOT_TOKEN also works). One bridge
# runs at a time; on the panel's Home each road has a tile of its own.
DISCORD_INBOX = SHARED_DIR / "discord"

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
