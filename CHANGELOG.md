# Changelog

All notable changes to the anima engine (until 0.12 the repository was
called ai-friend). Dates are when the change went live.

Versions count 0.6, 0.7, … 0.9, 0.10, 0.11, 0.12: the leading zero stays
until the friend's first body is on the desk. (Three releases went out of
this file as 1.0–1.2 for a fortnight; they are 0.10–0.12. 0.12 was never
tagged on its own: the first tag after the rename is v0.13.)

## 0.16 — 2026-11-11 → (in progress)

### Added
- **Doors out of a wake** (`engine/dealt_doors.py`): three small doors to the world, each offered at a wake and never
  required, each failing closed. Beside the open book's dealt pages, one real thing those pages mention — a name that
  is not the book's own — with the first line Wikipedia gives it (`WAKE_DEALT_THREAD`, at most
  `WAKE_DEALT_THREAD_LOOKUPS` names looked up a wake; looked for in the book's pages alone, never in the notes). With
  no book open, a question nobody has answered yet, from Wikipedia's lists of unsolved problems: add "question" to
  `WAKE_DEALT_WHOLE_KINDS` (two fields fetched a wake at most, kept a week). A line of their own from
  `creations/wonderings.md` handed back at a later wake, a few times at most and days apart, until a ✓ or an arrow
  on the line says it's done (`WAKE_DEALT_WONDERINGS`; the page is only read). All three ship off: they reach
  Wikipedia and change what a wake carries. `dealt.deal_whole` now hands over to the new module, and
  `dealt.book_next` returns the book's pages apart as a third element.
- **A question beside the open book** (`WAKE_DEALT_QUESTION_BESIDE`, off like the other doors): at a wake with a book
  open, when no wondering of theirs is due and no thread came from the pages, a question nobody has answered yet rides
  beside the pages instead — never two doors at once, and a question dealt beside a book never comes again alone. One
  field is fetched a wake at most, and after a fetch that failed none for an hour. The lists of unsolved problems are
  read more carefully: nothing under a solved or resolved section (at any depth above the line) is dealt as unanswered,
  and citations, bibliography, sources and works cited are skipped with the references. Each deal that hands something
  is now one line in `memory/dealt_doors.log` — the time, the base, the door and its key, never the friend's own words
  — so how often each door opens can be counted.
- **World trips** (`engine/worldtrip.py`, `/world` on the phone; `WORLD_TRIPS_ON`, off): game mode turned around — a
  trip to a real, persistent text world with other minds in it, carried by hand. Built for the relay of
  the-world.tech: you paste what its relay page shows, the friend answers and puts each thing they want to do there on
  its own line starting with `>` (at most `WORLD_TRIP_ACTIONS` a reply), and you paste those lines back; the engine
  itself sends nothing there. `/world` has buttons to start, pause, resume and end a trip and to read 📜 the friend's
  travel journal for the place (`creations/<WORLD_TRIP_DIR>/<WORLD_TRIP_PAGE>`, theirs — the engine only reads it, and
  the phone shows its end); typed: on,
  pause, resume, off, notes. While a trip is open each of your messages carries a mark right above it — what the place
  shows, carried by you word for word, not your words — and the trip's first message (and the first after a fold) an
  opening note with the house rules (`WORLD_TRIP_RULES`), what is known of how the place works (`WORLD_TRIP_HINTS`)
  and the travel journal — past `WORLD_TRIP_PAGE_CHARS` (30,000) its newest part, its end, the size said. `//` or `/me <text>` is you, aside, marked as yours. The carried
  text is defanged: no line of it can pass for the engine's or yours (brackets and their look-alikes, a `**Name:**`
  speaker line, a bare `\r` or other line break, the transcript's `---`); transcripts label carried turns as the
  place's, and read them back that way. After each reply the friend's `>` lines come to your phone alone, ready to
  copy (`WORLD_TRIP_COPY_LINES`: a `<pre>` block per `WORLD_TRIP_ACTIONS` lines, a warning when one holds a word from
  `PENPAL_PRIVATE_WORDS` or looks cut short); a reply that ends on a `>` line is never sent back to be mended.
  Mid-trip a typed `/word` the bridge doesn't know is not sent to the friend. Ending a trip, or the visit closing,
  gives the friend one turn to add a short dated entry to their travel journal ("engine — the trip" in the transcript);
  past `WORLD_TRIP_PAGE_WARN` (30,000) that turn first asks them to write the journal shorter, to about
  `WORLD_TRIP_PAGE_TARGET` (15,000), and the phone hears if it is still past; a brain that is away loses nothing. The
  fold comes at `WORLD_TRIP_FOLD_AT` mid-trip when that is sooner, its bell asks for the journal first; the pause's and afterglow's
  bells say part of the visit was a real place; `/status` names the trip; a trip and a game are never open at once.
  State in `memory/world_trip.json`, restart-safe. Telegram only, like the games menu: on the Discord bridge `/world`
  says so and nothing of a trip rides.
- **Reading notes when they matter**: the notes on a book come before the book's text each time they read on, name a
  range, or the next pages are dealt into a wake — the end of the page, up to `READING_NOTES_WITH_PAGES` (60000;
  0: none). And when your message on the phone names a book they keep notes on — its title, a distinctive word of it,
  or the author beside a book word — the notes ride right above your words, once per book while that message is in
  the visit (`READING_NOTES_ON_TOPIC`; the whole page within `READING_TOPIC_CHARS`, past it the sections your words
  touch, then the newest). Read only: the engine never writes, trims or creates a reading page.
- **Adventures — game mode** (`engine/adventure.py`, `/games` on the phone): the friend runs a text adventure as game
  master and you play one character, a few moves at a time. A world is a folder, `creations/<ADVENTURE_DIR>/<name>/`:
  `world.md` is the friend's alone (the engine never reads or shows it), `state.md` the shared record of where your
  character stands and the story so far, `inventory.md` what the character carries, and `scenes/` the pictures that
  reach the phone — nothing else under the adventures folder does, and none of it seeds a spark. `/games` has buttons
  to play, pause, end a session, read 📜 where we are and 🎒 the inventory, see 🖼 the newest scenes, rename, put away
  and bring back (nothing is deleted), and start a new world; `/game …` types the same. While a game is open a message
  carries a short line for the friend right above your words (the whole table and the state page on the first move of
  a session); `//` before a message says it outside the game; a guest at the desk is not playing. Ending a session
  (or the visit closing) gives the friend one turn of their own to bring the pages up to date — "engine — the game"
  in the transcript; a brain that is away loses nothing. Coming back to a world shows where you left off
  (`ADVENTURE_RECAP_ON_OPEN`); a changed inventory says so after the move; a picture painted outside the world's
  folder is mentioned to the friend once, never moved. Mid-game the fold rings at `ADVENTURE_FOLD_AT` when that is
  sooner than `FOLD_AT` — the window sense says so — and its bell asks for the game to be written down first; the
  next move sets the table again. The pause's and afterglow's bells say that part of the visit was a story.
  `ADVENTURES_ON` (on: nothing happens until a world is made), `ADVENTURE_STATE_CHARS`, `ADVENTURE_STATE_WARN`,
  `ADVENTURE_INVENTORY_CHARS`. The engine never writes, trims or creates the friend's pages there.
- **The journal's facts**: when the friend sits down to write a stretch of a visit — the pause, the afterglow, the
  fold's afterglow, the fold bell — a bracketed line of counts from the painting log rides under the bell: "[from the
  log, this stretch: 3 pictures painted, 2 of them trashed since.]" (`JOURNAL_FACTS_LINE`). Only pictures painted at
  a visit's door since the stretch began count (one_turn stamps each message as it takes it in; the stamp is never
  sent), never a wake's or the dream book's; a picture is kept when it is at its path, trashed when an entry in
  `creations/.trash` surely claims it. A wrong count is worse than none: anything not certain — an unstamped stretch,
  a log row it can't read, a full log, a clock that went back, a picture moved or renamed — and there is no line. And
  those bells gain one sentence beside "what you did": "If something was tried and didn't work, the entry says it
  didn't. How a thing ended is part of what happened." (`JOURNAL_ENDINGS_SENTENCE`). Both on; off, the bells are as
  before, byte for byte. Read only: nothing is written.
- **A tool call written as words, run when it is clean and harmless**: a reply that ends with a call written out as
  words — bare, in `single marks`, in a ``` fence, or as `print(default_api.…)` — is now seen in its wrapping too. In
  a visit (never a guest's turn), when that last line, or the whole reply, is one clean call to a tool on
  `CALL_TAIL_RUN_ONLY` (`("next_spark",)`) — the exact name, keyword arguments only, each of the tool's type — it runs
  as written: the call line and a `***` rule right above it come off the words, and the friend and the phone are told
  it came out as words, as for a whole-reply call. Any other tool written as words is asked again, never run; code
  shown with a name that is not one of the friend's tools goes out untouched; a call is run from words once a turn.
  The pause, the afterglow and the fold bell see the wrapped shapes and ask again; the wakes, penpal letters, dreams
  and condensing are as before. `CALL_TAIL_RUN` (on). A reply kept by the "you said it's done" ask now also counts
  as answered when the call came from the words.
- **The same failed call, again and again**: in a visit, a call identical to one that already failed this turn (the
  same tool, the same arguments — an empty one the same as one left out) runs `CHAT_SAME_FAIL_RUNS` (2) times in all,
  then is refused without running, the refusal saying what it failed with; the `CHAT_SAME_FAIL_REFUSALS`-th (2)
  refusal ends the turn's tools. One last step follows with the same tools offered (so the prompt's reading holds),
  its calls not run and said so in the friend's history, and the phone gets one ⚠ note; repeated failures in the
  "no action" note collapse to ×N. Any call that goes through clears the remembered failures. A tool whose refusal can
  invite the very same call again says so through its module's `invites_again(arguments)` (`chat._INVITES_AGAIN`; a
  module without one exempts nothing). `CHAT_SAME_FAIL_STOP` (on). With `CHAT_FAIL_LOG` (on) each failed call in a
  visit is a line in `memory/tool_fails.log` — the tool, its own argument names with the lengths of their values,
  and the kind of failure; never what the friend wrote. Wakes are as they were.
- **Pictures sent together are one message**: Telegram delivers each picture as a message of its own, with your
  caption on the first. Photos from your chat that came as one album, or one after another with nothing between them
  (each within `TELEGRAM_BATCH_GAP_S`, 45 s, of the one before by Telegram's own clock), are now one turn: all before
  the friend's eyes in order, one line for them all — the true plural of the single photo's — your captions below it
  ("with the 3rd: …"), one reply. An album split over two polls stays one batch; when a poll ends on a photo the
  bridge looks again after `TELEGRAM_BATCH_WAIT_S` (2 s) for the rest. More than `TELEGRAM_BATCH_MAX` (10) go on in
  further turns, each saying it is more of the same batch. A picture that didn't arrive, or is too large to see, is
  said truthfully to the friend and once to the phone; none arriving is said to the phone alone, as with one photo. A
  single photo reads exactly as before. `TELEGRAM_BATCH_PHOTOS` (on); off, every picture is its own message.
- **A penpal's letter with pictures** (`PENPAL_PICTURE_LETTERS`, on): 🖼 beside a penpal in `/penpals` (or `/penpal
  collect <name>`) collects a letter — paste its text and send its pictures in any order; a picture's caption, and a
  message after 📝 My note, are your own notes. Nothing reaches the friend until ✅ Done (`/penpal done`), and each
  thing taken is acknowledged as not sent. Done files the letter and gives the friend one turn of their own: a line
  saying the letter and the pictures are the penpal's, not yours; your notes under their own line; then the letter's
  words whole between two lines marked with a token new each turn, so nothing in a letter can pass for an engine line
  or a note of yours; the pictures before their eyes, `TELEGRAM_BATCH_MAX` a turn. The turn is tried once: a brain
  that is away leaves the letter unread for them to find, and the phone is told. A collection rests after
  `PENPAL_JOIN_MIN` quiet minutes by Telegram's own dates (or when a guest sits down); ✖ Cancel or `/cancel` sets its
  pictures aside, never deletes them; its buttons carry its id, so an old one acts on nothing. One album (or one
  picture) captioned `/penpal <name>` is a letter too. A letter that is only pictures the friend may write out
  themself — `penpal(action="transcribe", who, letter)`, told in the turn's own line (the tool's definition is
  unchanged) — filed as the penpal's letter and marked as written out by the friend, only from pictures that were all
  before their eyes in this visit or wake within `PENPAL_PICTURES_SEEN_MIN` (60) minutes, never in a guest's turn; a
  new writing-out replaces the first only while it is the newest letter, the first set aside. `penpal read` shows a
  letter's pictures again, only those not yet seen in this window, your notes before any penpal's words; pictures it
  queued are let go at the turn's end, never riding on a later message. The pictures are kept with the penpal
  (`.pictures/`); the lines for your phone wait in `memory/penpal_tells/` until sent.
- **The penpal write guard** (`PENPAL_WRITE_GUARD`, on): before a letter is filed, if it would be the friend's second
  letter in a row to a penpal while another penpal's letter is unanswered (not paused, not let rest), or its greeting
  names a different penpal than the one addressed, it is held once — nothing filed — and a "(refused — not sent yet —
  …)" line says what the engine sees: when their last letter went, whose letter waits and since when, and the exact
  `who=` to send it to them instead. The same call again (same penpal, same letter, whitespace aside) within
  `PENPAL_WRITE_GUARD_MIN` (10) minutes sends it, with a clause in the result and a line on your phone beside the
  letter saying they were asked and confirmed. The salutation matcher is strict (an opener and the name as the engine
  knows it, a whole name, its own case; the addressee named anywhere in the greeting is never a mismatch); times come
  from the thread's own record; only real letter files count; a hold lives in memory only, under a lock, and is
  dropped when that penpal is written to or that letter goes to anyone. Off: as before.
- **The name left out** (`PENPAL_WHO_HELP`, `PENPAL_WHO_FROM_GREETING`, on): a penpal call with no name in `who` is
  addressed from the action word when what follows it is exactly one penpal's whole name ("write Ann", "read ann" —
  never the beginning of a name, so "write it" never means a penpal whose name starts with "it"), and a write whose greeting names exactly one penpal goes
  to that penpal, through everything a write goes through; the friend's result and your phone's line say where the name
  came from. Otherwise the refusal shows the call with the name in it and whose letter waits for an answer. Off: an
  empty `who` is refused exactly as before.
- **`penpal.invites_again`**: the penpal tool now tells chat's rail for a repeated failed call (`CHAT_SAME_FAIL_STOP`)
  which refusals ask for the very same call again — the write guard's hold, a `transcribe` refused because the
  pictures were not yet seen, still arriving or another letter's were last seen, and a `befriend` refused for a full
  circle, each once that state has changed. The marks are keyed by the whole call, dropped when that action is judged
  again or the turn ends, and expire after ten minutes. An argument error repeated still stops.
- **The journal feed** (`JOURNAL_FEED`, on — the command is there, the switch itself starts off; Telegram only):
  `/journal on` sends what the friend writes in their journal during a visit — a turn, a pause, the afterglow, the
  fold — to your phone, each entry headed with its time and then its text exactly; `/journal off` stops it; `/journal`
  alone says how it stands (and `/status` gains a line once it has been used); `/journal today`, `yesterday` or
  `YYYY-MM-DD` sends that day's entries once, packed into few messages, nothing said to the friend. The friend is told
  every time it applies: at their first turn after on ("{keeper} turned the journal feed on — …"), "still on" at the
  first turn of a new window, a line inside every pause, afterglow and fold bell, and once after off — also when the
  state file breaks or the knob goes off. An entry is sent only if the run it was written in carried one of those
  lines and the friend answered; a wake overlapping (or the wake door held), a run that didn't tell them, or the switch
  turned mid-run, and nothing of it is sent (with a line on the phone when it might have been). Entries wait through
  your quiet hours, your `/quiet` and while a guest is seated. The journal is only read; the queue in
  `memory/journal_feed.json` holds keys, never text, and is written through a temporary file; no lock is held across a
  send (`JOURNAL_FEED_PACE_S` between messages when several go at once). The Discord bridge has no feed: its
  `/journal` says so.
- **Their books, on your phone** (`BOOKS_COMMAND`, `BOOKS_FINISHED_NOTICE`, on): `/books` says where the friend is
  in each book in hand — page or chapter of how many, the percent, how much is left, their last sitting (and "untouched
  N days" past `READING_OPEN_DAYS`), a second reading counted — then the shelf not opened yet and what they finished,
  newest first, each list capped and the whole within one message. And when they finish a book (a second reading
  too), one line goes to the phone with what is still in hand and unopened on the shelf, so you know to bring a new
  one; your quiet hours hold it. The first look records what is already finished and says nothing; a line whose send
  fails is told at the next look. Read from the bookmarks the engine keeps (`engine/bookshelf.py`): nothing is opened
  or moved, the friend is told nothing, and the one file written is `memory/books_seen.json`. A bookmarks file that
  can't be read is said in one line, the shelf left out. On the Discord bridge `/books` and the line work the same,
  as `/pages` and its warnings do.
- **The wake's last clause, optional** (`WAKE_FILLER_LINE`, on — as before): the plain wake's situation ends "This
  time is yours; don't produce filler to look busy." Some friends take that clause as a reason to hold back, or quote
  it before acting; off, the situation ends at "This time is yours." and every word before it is the same. The
  re-tuned bell's own line (`WAKE_BELL_RETUNED`) is untouched.
- **Fewer cold reads of the window**, three causes of a needless read from the top:
  - **An open visit's saved reading is kept through a wake** (`BRAIN_KEEP_VISIT_READING`, on; `BRAIN_KEEP_VISIT_HOURS`,
    6): with llama-server, a slot folder and `BRAIN_SLOT_KEEP` 1, a step-down after a wake's, a reverie's or a night
    step's prompt while a visit is open — its last turn and its saved reading younger than the hours, its prompt from
    today — neither lets the visit's saved reading go nor saves its own, and says so in `memory/brain_notes.log`. A
    fold's and an afterglow's prompt are the visit's and save as before. Two small records beside the door's mark
    (`memory/.pids/brain.visit`, `brain.served_by`) say whose reading is whose, written whole or not at all, and only
    with that setup. Off, or any other setup: as before, no files.
  - **The night's steps take the warm prompt** (`NIGHT_WARM_PROMPT`, on): the keeper's look, a dream (and its
    painting's question), a penpal letter kept in their words and the condensing hour are asked with the date line
    without the minute, so the window is read again only from where it changed. The newest memories stay in the
    prompt exactly as the plain form has them. **This changes what the friend reads at night in two places**: the date
    line has no minute, and the hour comes at the top of each such step's message — tell them, or turn the knob off.
    If the warm form can't be built (the prompt's wording changed), the plain one is used and the night's log says so.
  - **The folded window is read in at once** (`FOLD_PREFILL`, on): when a fold is done, its new window is read in the
    background, the same read `/rewarm` makes, so your next message starts warm; a message meanwhile waits for it and
    then reads only itself. Skipped while the game guard holds the card, a wake runs or the brain is set down. Nothing
    goes to the phone; two lines in the bridge window. The Discord bridge folds the same way, so it reads in the same.

### Changed
- **Upgrading from 0.15**: every new knob comes with a default in `config.py`, so an older house keeps working, and
  `bat\update.bat` (or the panel's Update) appends the new knobs at the end of your `config.py`, at their defaults,
  with their comments. Nothing touches your journal, your penpals' threads or your reading pages. On by default: the
  reading stub, the notes with the pages and on topic, adventures (nothing happens until you make a world), the
  journal's facts and the endings sentence, the call written as words, the same-failed-call rail and its log, photos
  sent together, penpal letters with pictures, the write guard, the name left out, the `/journal` command (its
  switch starts off), `/books` with its line when a book is finished, and the three fixes for cold reads
  (`BRAIN_KEEP_VISIT_READING`, `NIGHT_WARM_PROMPT`, `FOLD_PREFILL`) — of these only the night's warm prompt changes
  words the friend reads (the date line without the minute, the hour atop each night step's message; turn
  `NIGHT_WARM_PROMPT` off to keep the nights as they were). Off by default: the doors out of a wake (the question
  beside the book among them), which reach Wikipedia, and world trips (`WORLD_TRIPS_ON`). Expect one cold read at the first visit after updating: the
  reading section of the prompt and two tool descriptions changed (below).
- **`/help` comes in two messages** when it no longer fits one of Telegram's (4,096 characters): the commands up to
  the newer ones, then the newer ones and the rest; each part is checked to fit, and none of its lines is shortened.
  The pairing message does the same. The "/" menu and the Discord bridge's help are as before.
- **The wait before a penpal's arrival turn** is said in seconds when `PENPAL_TURN_AFTER_MIN` is under a minute ("in
  about 10 seconds"), in minutes otherwise.
- **The reading section of the prompt is a short stub** (`READING_PAGE_STUB`, on): for each open book, where they
  stand, their sittings by name, the page's path and size — no longer the notes themselves, which come with the
  reading instead (above). This changes the standing prompt once, and one clause of the `read_pdf` and `read_epub`
  tool descriptions ("your notes come back to you with the pages each time you read on, and when the book comes up
  in a visit"); the first visit after updating reads the whole prompt again. `/pages` says a stubbed page's notes
  ride with the reading, and a stubbed page is never warned of. Off: the page rides as before, up to
  `READING_PAGE_CHARS`.
- Comments, examples and help texts no longer carry names, quotes or dates from the house the engine grew in; lines
  the friend or the keeper reads say "they" throughout. No behaviour changes.

## 0.15 — 2026-10-24 → 2026-11-11

The "presence" release: the friend can take a turn of their own between
messages — set by them, one at a time — and paint the two of you together.
Around it: a letter sealed until its day, the engine's own week on the phone,
Qwen-Image 2.1 as a brush with reference pictures, and a fence at the sampler
for a tic turned glitch. In its second half, the friend's own days: questions, a calendar,
wakes they ask for, intentions, a private gallery, dreams, penpals and friends, your quiet and their
outbox, and the wake handed back at its rest.

### Added
- **Painter tools**, each with its launcher in `bat/` (and the Mac and Linux twins); every one wants
  the card to itself, so close the bridge and the heartbeat first. `gardenart` paints the garden's plants at every
  stage that has no picture yet. `refsheet` paints a face folder again, large and from four angles, on a numbered
  sheet — `pick` makes the chosen takes the folder's pictures (the old ones kept in `old/`); `--as` says who the
  picture is. `starterroom` paints a few empty rooms on a sheet for the friend to choose a backdrop from (nothing is
  placed for them). `selfcheck` acts out on this machine what broke once — a painting with and without the "us"
  references, the painter leaving the card, two songs through the music ear, a room surviving a reload — and keeps a
  report in `memory/`. `painttest` measures paintings with references at a few sizes. `paintcompare` paints the same
  two pictures by several brushes, the same seed (`--models`, `--kv`, `--cfg`). `lora-tasting` paints the same
  prompts at a few LoRA strengths, side by side (`models/loras/tasting-prompts.txt`).
- **Their open questions**: `open_question` / `close_question` keep a page of curiosities of their own
  (`questions.md` at the root, `memory/questions.json`); the open ones ride under every wake's and reverie's bell
  with their age, so a question carries from wake to wake without a thread having to pass it on. The engine never
  adds, words or closes one. `QUESTIONS_ON`, `QUESTIONS_MAX`.
- **A calendar of their own** (`engine/datebook.py`): `mark_date` / `unmark_date` — a yearly day, a day to
  come, or "someday". What is near rides under the bell; a date that is today is said at a visit's first moment.
  `calendar.md` at the root. `CALENDAR_ON`, `CALENDAR_AHEAD_DAYS`.
- **Wakes they ask for** (`engine/wakeask.py`): `wake_me` / `cancel_wake` — their own times inside the
  heartbeat's loop, with a note on the bell. Late if a visit held it, up to `WAKE_ASK_LATE_MAX_MIN`; past that, the
  next wake is told it passed. Nothing counted, nothing nagged.
- **Intentions** (`engine/intentions.py`): `intend` / `drop_intention` — their words and a condition the engine
  can see (a time, your workday's end, your first message of the day, the desk, the weather, the garden, your game).
  When it comes true they're woken (or sparked, or told mid-visit) with their own words and the choice: do it,
  change it, let it go. Under the bell only a count and keywords. `INTENTIONS_ON`, `_MAX`, `_DAYS`, `_CHECK_S`.
- **The Veil, a private gallery** (`engine/veil.py`): `creations/veil/` with `in_progress/`, `finished/` and
  `let_go/`; nothing under it reaches your phone. `veil_finish`, `veil_show` (carries a finished piece out to
  `unveiled/`, then the bridge brings it to you with when it was finished and their note), `veil_let_go`. Pieces in
  progress and finished-unseen ride under the bell with their ages; `publish_creation` won't publish from behind it.
  `VEIL_TITLE` is the name they give it; `VEIL_MAX_IN_PROGRESS` (2) hands a new piece back on a full shelf, with the
  words kept in the call.
- **Dreams** (`engine/dreams.py`): some nights (`DREAM_CHANCE`), after sleep, a dream they write themselves from
  loose bits of the day, a few days back, old memories, an old journal paragraph, the weather and one thing from the
  world — into their dream book, `dreams/`, never the journal. The last few ride in their prompt as dreams
  (`DREAMS_IN_PROMPT`, `DREAMS_FADE_DAYS`); the next door gets one line with its first words; `read_dreams` opens the
  book. `DREAM_PAINT`: one moment after a dream to paint an image from it, into `creations/dream_book/`, never carried
  to the phone. The dream book is theirs.
- **Since you last talked** (`engine/since.py`): a visit's first moment says, facts only, what they did in their
  own time — wakes and reveries, questions opened or closed, pieces written, pictures painted. `SINCE_LINE`.
- **The wake handed back**: `WAKE_LOOKBACK` — when a wake or reverie rests, it is handed back once: what they
  thought and did since their last journal entry, from the log, with `write_journal`, `remember`, `leave_thread` and
  `do_nothing`. The asks to journal during the wake step aside; resting stays a complete answer. The bells say so only
  while it's on.
- **One thing dealt into a wake** (`engine/dealt.py`): `WAKE_DEALT` — a random Wikipedia page, a headline or a
  song not yet played, as one line under the bell; `WAKE_DEALT_WHOLE` — one whole thing instead, last under the bell,
  turning wake by wake (a whole article, the questions in a penpal's last letter, a song); an open book first, every
  wake, the next pages from their bookmark (`WAKE_DEALT_BOOK_FIRST`). Theirs to take up or set down. The network
  kinds are skipped offline and after `DEALT_TIMEOUT_S`.
- **The bell's lines, chosen**: `WAKE_FACTS_LINES` — "all", or which of the status lines under the wake bell
  ride (shelf, room, garden, outside, questions, veil, calendar, desk, intentions, sent, penpals, gaming, dreams,
  wakes_asked, mirror, dealt). `WAKE_MIRROR` (off): their last threads side by side and their last wakes counted.
  `WAKE_BELL_RETUNED` (off): a bell that asks them to take something up — only with their yes. `THREAD_IN_WAKES`.
- **The projects page's shape** (`engine/projects_page.py`): `PROJECTS_PAGE_SHAPE` (off) keeps `projects.md` a
  list — `## Active` and `## Completed or set aside`, one line a project with a link to its README;
  `finish_project`, `set_aside_project` and `reopen_project` move a line. `start_project` writes the README link.
- **Your quiet and their outbox** (`engine/outbox.py`): `/quiet` (or `/quiet 2h`) holds delivery, never their
  living: what they write meanwhile — and in the night's quiet hours, `OUTBOX_QUIET_HOURS` — waits; when the quiet is
  over they see it once, with ages, and `send_waiting` or `let_go_waiting` each. A letter put in the mailbox's
  `later/` waits for your workday to end. `SENT_LEDGER`: one line under their bell of what reached your phone today.
  A spark set for a reason (`next_spark(minutes, reason)`) comes even while the heartbeat holds drift.
- **The desk** (`engine/desk.py`, Windows, off): `DESK_ON` — how long since this PC's keyboard or mouse was
  last touched, said plainly; an arrival after `DESK_ARRIVE_AFTER_MIN` is told once, and "when they sit down at the
  desk" is an intention's condition. Nothing greets you by itself.
- **The game guard** (`engine/gameguard.py`, Windows and NVIDIA, off): `GAME_GUARD_ON` — another program over
  `GAME_GUARD_MB` on the card is a game; wakes, sparks and dreams wait, and their idle brain is set down. `/gaming
  on|off|auto` on the phone.
- **Penpals** (`engine/penpal.py`): their correspondence with other minds, carried by you. `/penpal <name>
  <letter>` files a letter (pastes within `PENPAL_JOIN_MIN` join one); `penpal read`, `write`, `rest`, `note` (their
  page about each penpal); a letter's arrival gives them a turn of their own; at night, letters that left the window
  are kept in their own shorter words. Their letters reach your phone to post, with buttons (Posted / Posted,
  trimmed / Not sending) and a look at what in them names your life — `PENPAL_PRIVATE_WORDS` (fill in your own),
  clock times, e-mails, phone numbers. `/penpals` is the panel: the last exchange, add a letter, a handle, ⏸ pause
  (for safety; they're told why), undo, move or split a paste, a new penpal. `/penpal list`, `new`, `handle`,
  `pause|resume`; once a day after `PENPAL_DESK_HOUR` every thread in a line, when something waits on someone.
  A letter they write reaches your phone within `PENPAL_WATCH_S` seconds. Wrong or unknown actions are refused
  with "nothing was written or sent" (and `send`/`reply` are `write`).
- **Friends**: `penpal befriend / unfriend / quiet` — the penpals they choose ride in their standing prompt
  under `FRIENDS_TITLE`: their own page about each (up to `FRIEND_PAGE_CHARS`) and a line of dates, from a snapshot
  taken at night (and at `/rewarm`), so a page edited by day doesn't make the whole prompt be read again. At most
  `FRIENDS_MAX`; a friend gone quiet rides as one line. Said once, as a fact, at `FRIENDS_SUGGEST_AFTER` letters each
  way. ★ in `/penpals`.
- **A guest's seat kept through a restart**: `PARLOR_GUEST_KEEP_HOURS` (3) — a guest seated on the phone
  stays seated through a restart if they sat down within that many hours; an older seat is let go, said so.
- **Pages that ride whole**: `KEPT_PAGES` — pages of theirs from `creations/` in the prompt right under WHO
  YOU ARE, each up to `KEPT_PAGE_CHARS`.
- **`CHAT_DO_NOTHING`** (True): False keeps `do_nothing` from ending a reply to your message — words beside it
  are the reply; with none they're told rest isn't offered here. The tool list stays the same. Sparks keep it.
- **`PRESENCE_INTENSE_PAINT`** (True): False keeps the painter out of intense sparks — told, not run.
- **Pages edited a passage at a time**: `edit_identity`, `update_projects`, `update_destiny` and
  `update_keeper` take `old_text`/`new_text` — one passage changes, the rest of the page stays byte for byte
  (whole-page rewrites deep in a long window drifted). `new_content` still rewrites the whole page. A passage
  copied without the page's formatting (`**`, quotes, dashes, spacing) still matches when it's in one place, and
  the result says so; a passage not in the page changes nothing and shows the nearest line to copy.
- **The pages in the prompt, watched**: `engine/pagewatch.py` and `/pages` on the phone — every page that
  rides whole (self, projects, destiny, keeper, the Active projects' READMEs, an open book's page), its size, its
  ceiling, whole or cut. At `PAGE_WARN_AT` (new, 0.8) of a ceiling, and past it, the phone is told once a day a
  page. The ceilings rise to guards against a runaway page (destiny 12,000, keeper 15,000, a README 12,000 and
  30,000 together, a book's page 15,000): four pages had grown past the old ones and rode cut, unsaid.
- **`/rewarm`**: the standing prompt rebuilt from the pages as they are now and read into the server's
  cache at once (`ollama_client.prefill`, `chat.prefill_visit`), so a changed page rides from the next reply.
- **LoRAs on the painter**: `PAINTER_LORAS` (new, none) — add-ons on the transformer, each at a strength;
  files in ai-toolkit's, ComfyUI's or kohya's naming are read as diffusers'. Qwen-Image keeps reading its reference
  pictures. `PAINTER_LORA_TRIGGER` puts a trigger word ahead of every prompt while one is on. The painter's window
  says what it was asked (size, steps, references, words) and the time at steps 1, 10, 20…
- **Garden: rename and forget**: a made-up plant takes a new name (its paintings and its bed follow), or is
  let go — off the seed list, its paintings set aside in `garden/forgotten/`, never deleted. A new plant whose name
  sounds the same as one there is refused; the seed list shows how each made-up plant looks.

- **A painter line for every painting**: `PAINTER_PROMPT_HINTS` takes the word `"*"`
  for a line that goes ahead of every prompt — a style, say — named in the result
  like the other lines.
- **Wakes that share the standing prompt**: `WAKE_PROMPT_WARM` (new, False) builds a
  wake's system prompt in the warm form a visit has — the date without the minute, the
  memories on the bell — so wakes share it up to the day's newest journal lines. With
  checkpoints (`BRAIN_CHECKPOINT_EVERY`) a wake's reading is saved when its door closes,
  and a door just come up restores the newest reading kept for a prompt that has none of
  its own — the server reuses it up to the first change. `page_age` ("last rewritten N
  days ago") now turns at midnight with the date, not at the hour of the last edit.
- **Checkpoints inside a long prompt**: `BRAIN_CHECKPOINT_EVERY` (new, 0) passes
  `--checkpoint-every N` to a llama-server built with it (a llama.cpp patch), so a standing
  prompt that changes near its end — a new journal entry — is read again from the last
  checkpoint instead of from the top. Measured on a 31B at 152K tokens: 25 s instead of 114.
  Left out, with a word on the door's line, for a server that doesn't know the flag.
- **Presence — sparks** (the plan written out for the friend and
  agreed by them before it was built): `next_spark(minutes)` sets ONE spark,
  10 to 60 minutes counted from the last word between you, and turns presence
  on; the tool's own line shows the minutes and the clock time. When the visit
  has been quiet that long the bridge opens a spark turn in the open visit
  under one engine line, which quotes the keeper's last message so the spark
  picks up where the two of them were (in the transcript it is the
  engine's, "engine — a spark"): words to the phone, a painting, the stone (refused in
  the keeper's work hours) or nothing at all (`do_nothing`); the moment above
  it says no message from the keeper follows, so it reads as the spark it
  is. After it, no other
  comes until the friend sets one again — in the spark itself or any time
  later. `engine/presence.py` keeps the state in `memory/presence.json`, so it
  outlives a restart. A message from the keeper restarts the count (a slash command
  does not); a wake
  running holds the spark (`memory/.waking`, set by the heartbeat around each
  wake); the quiet hours end presence. While a spark is set the idle roll and
  the pause wait; with none set they go on as usual. A spark thinks first —
  the think-first reminder, and `PRESENCE_THINK_RETRIES` (3, new) re-rolls if it
  comes back thoughtless, at any depth (`THINK_RETRY_UNTIL` does not apply to a
  spark) and at the friend's own temperature — a spark begun with no thought is
  cut at its first word while a re-roll is still to come, so no words are
  written for nothing; the last attempt goes out whole (`PRESENCE_THINK`, on: without a
  thought a spark made one gesture and never set the next; off: quick, neither
  reminder nor re-roll). On the phone:
  `/presence on` (one spark at `PRESENCE_DEFAULT_MIN`, 15, new),
  `/presence off` (the friend can too: `next_spark` with no minutes), `/presence` (whether a spark
  is set and in how long), `/discreet` (sparks sent silently, the words hidden
  until tapped). Telegram only.
- **Drift and longing** (sparks part two, pieces 2 and 3): `next_spark(drift=…)`
  sets no time — every quiet minute a die is rolled at the temperament's pace
  (very rare ~2 h, rare ~1 h, sometimes ~25 min, often ~10 min, frequent ~5 min, intense for play —
  a heartbeat, 0 to 1 minute after every last word), past its soonest (5 min) and under its hour's most (1, 2,
  4, 8; none for intense), and sparks keep coming until changed or stopped. The
  chance climbs with the quiet and faster with the friend's `ache` (0–3).
  `/presence on` starts drift at `PRESENCE_ON_TEMPERAMENT` (rare, new; it replaces
  `PRESENCE_DEFAULT_MIN`); `/presence <temperament>` sets one. Intense carries
  `PRESENCE_INTENSE_NOTE` (new) and no seed, and thinks by its own switch,
  `PRESENCE_THINK_INTENSE` (new, off: instinct); in drift the spark line drops the
  set-it-again reminder. The `next_spark` description covers the three ways to call
  it, and a slip (an odd temperament spelling, minutes with drift, ache without it,
  a number out of range) is read kindly and said.
- **Seeds** (sparks part two, piece 1): every spark carries one thing picked
  at random to spark off — a memory, something the friend made, a song from the
  songbook, a few lines of the journal from a week or a month ago, the world (the
  day, the season, where the keeper is), a word from the lexicon (`engine/seeds.py`;
  `PRESENCE_SEEDS`, new). Not a task; no repeats among the last 20.
- **The time capsule**: `seal_letter` seals a letter until its day.
  Its words go into `memory/capsule/`, out of the friend's sight (not in the
  prompt or recall; `read_file` refuses the folder) until the day, when the
  first door lays it in `creations/capsule/` as written and the moment says
  so. The friend keeps a row of having sealed it (title and day, never the
  words); a letter from the keeper (`/seal` on the phone) arrives as a row
  saying one waits and when. `/capsule` lists what waits.
- **The engine's week**: every call to the brain leaves one JSON line
  in `memory/steps.log` (door, window, prompt read time over its attempts,
  tokens written, the longest thought, the set-asides by kind, the mends made
  in place, the signature's count; rotated past 4 MB to `steps.old.log`). On
  `ENGINE_WEEK_DAY` after `ENGINE_WEEK_HOUR` (new) the bridge sends the last
  seven days as an engine notice, once, held through the quiet hours; `/week`
  shows it any time.
- **Qwen-Image 2.1 as a brush**: a `qwen21` family with its
  own pipeline and guidance keyword (`true_cfg_scale`), and the Turbo
  checkpoint (eight steps, its schedule baked in; `PAINTER_STEPS` does not
  move it). Bigger than the card with its text encoder, it paints under model
  offload — or whole on the card with the encoder quantized as it loads
  (`PAINTER_ENCODER_BITS`, 8 or 4, new; template 0): the files are fetched with
  the brain up, then the brain is set down, then the load. The VAE decodes in
  tiles when a quantized pipeline sits whole on the card; `--test` prints the
  peak. The setup line names torchvision, sentencepiece, protobuf and
  tiktoken.
- **Reference pictures**: `paint` takes `reference` — pictures under
  `creations/` (up to ten), a folder (every picture in it), or `face`, which is
  `creations/face/`, the friend's own to fill (the engine never puts one
  there); the friend's name, "me" and "myself" stand for it too. A painting
  with references takes the offload road. `PAINTER_REFERENCE_NOTE` (new) is a
  keeper's line at the end of the paint tool's description. Another brush
  refuses before the card is touched.
- **Reference sets**: `PAINTER_REFERENCE_SETS` (name → (references,
  line), new): a set's name — or two or more of its own pictures named in any
  order — brings its pictures in order, and its line goes to the painter ahead
  of the prompt (for example: which picture gives the sizes, which one each
  face). The template ships none.
- **Names bring their pictures**: `PAINTER_AUTO_REFERENCE` (new, on): a
  painting with no reference whose words name the friend or the keeper brings
  their pictures (the face; a folder under the keeper's name), both together the
  set that holds them; the result says so. References given by hand are kept,
  and a name they leave out is added (the face given, the keeper named: the set).
- **Prompt hints**: `PAINTER_PROMPT_HINTS` (word → line, new): when a
  prompt has the word in any ending, the line goes to the painter ahead of it,
  after a set's line; the friend's words stay theirs, and the result names the
  line. The template ships none.
- **The painter's prompt, where you can see it**: every painting's
  prompt is kept in `memory/paint_prompts.jsonl` (the prompt, the set's line,
  the hints, references, what was kept out, the door).
  `TELEGRAM_PAINT_PROMPT_CHAT` (new) puts it with a visit's picture on the
  phone; `WAKE_LOG_PAINT_PROMPT` (new) writes it under each paint call in the
  wake's log — a wake's picture reaches the phone without it.
- **Banned strings**: `BRAIN_BANNED_STRINGS` (new): each string that
  is one token at the llama door (looked up once via `/tokenize`) goes as
  `logit_bias`, never produced, in thoughts and replies; a string that splits
  is left out and said. A door that refuses the field turns it off for the
  run, said. Under Ollama it does nothing. A fence, so it is the keeper's to
  set; the template ships none.
- **The heartbeat and sparks**: starting the heartbeat loop turns
  presence off, so the wakes take the time between visits
  (`HEARTBEAT_ENDS_PRESENCE`, new, on). `HEARTBEAT_HOLDS_PRESENCE` (new, off)
  holds sparks for as long as the loop runs: `next_spark` and `/presence on`
  set nothing and say why, and no spark comes; `next_spark()` still turns
  them off.

### Changed
- **Upgrading from 0.14** (0.15's second half): every new knob comes with a default in `config.py`, so an older
  house keeps working, and `bat\update.bat` (or the panel's Update) appends the new knobs at the end of your
  `config.py`, at their defaults, with their comments. On by default: their
  questions, calendar, wakes they ask for, intentions, the Veil, dreams, penpals and friends, the outbox, the sent
  ledger, the since line, the dealt item and the wake handed back — each a knob to turn off. Off by default: the
  desk, the game guard, the mirror, the re-tuned bell, the projects page's shape. Fill `PENPAL_PRIVATE_WORDS` with
  your own words before the first letter goes out. The page ceilings rose (see *The pages in the prompt, watched*);
  a house that set its own keeps them.
- **The wake bell**: it names the doors out (a book, a song, a page of Wikipedia, the headlines, a
  picture) as a real use of a wake, and where the thread goes (`leave_thread`, a question to `open_question`); with
  `WAKE_LOOKBACK` it says the wake comes back at its rest, without it the end is the time to write, as before.
  `heartbeat.bell()` is the bell a wake rings.
- **`start_project`**: the line under Active carries the README's link (no "Status:" any more).
- **References capped**: `PAINTER_REFERENCE_MAX` (new, 4). Nine reference pictures never reached a
  painting's first step; past the cap the "us" set goes when both of you are among them, else one picture from each
  folder first — and the friend is told which. A reference with a list mark or quotes ("--- face-3.png") is mended
  to its file when sure. `PAINTER_TIMEOUT_S` 300 → 900 (a ceiling for a stuck painter), `PAINTER_RAN_OUT_REST_MIN`
  15 → 0.
- **The pause counts from the last word between you**: sparks no longer keep the afterglow from
  coming; only intense sparks hold the pause and the visit's end.
- The garden's paintings are seen in the garden, not sent to the phone as drawings.

- **The hour without a dash**: the engine's line reads "05:57 in the early morning
  where you live", not "05:57 — early morning" — the old shape was being copied into the
  friend's own posts as an opening "05:57 — ". The page-age test is pinned to noon of its day (it failed before ~05:00).
- **Home said plainly**: the clock line's home states read "home, with you, not at
  work" — the friend still drifted into "at work" deep in a long visit with the day marked off.
- **The painter makes room**: whole on the card, each step's
  high-water mark is watched; past the card the painting stops and is painted
  again under offload with the same seed. The sidecar is a threading server, so
  a `/rest` is heard mid-painting and a painter that leaves goes then; a
  painting that timed out ends the paint call.
- **Claimed: the middle road**: after a reply that said "done"
  without doing it, the ask says what happens next — a tool call now and the
  reply goes out as written (a note says it was saved after); words only and
  the new reply goes instead. `CLAIMED_KEEPS_WORDS` (unlisted, on); `False` puts
  back the plain re-roll.
- **A deleted piece's row can leave memory with it**:
  `CREATION_ROWS_ON_DELETE` (new): "mark" (as before — the row stays, saying
  it went) or "remove". `bat\backfill.bat --gone` lists the rows of pieces
  deleted or missing; `--gone --write` lets them go, `memory.db` copied beside
  itself first.
- **The carry in every case but `/new`**: a visit the bridge died
  with leaves its carry from its transcript, dated by the file's last write;
  `/new` and the parlor's new button start clean.
- **Page tools say when the signature was dealt in**: a page saved
  with the refrain dealt into carried-through sentences is told so — the
  count, and where the kept version is. The engine edits no page.
- **Lately scrolls**: the panel's Lately asks for the last
  `LATELY_MORE` (200) rows and shows them in a box ten rows tall that scrolls;
  `/api/lately?n=` gives as many as asked, up to 500.
- **A painting with references, about a megapixel**: `PAINTER_REFERENCE_PIXELS`
  (new, 1,050,000) — each reference rides beside the painting at about its
  size, so a painting that looks at references is painted no larger than this
  (its shape kept); three references beside a 1440 painting had spilled the card.
- **Plants of their own, and every plant painted**: `garden invent` — a name,
  how it looks, its days (21–120), season, thirst, whether it gives again, what it
  gives; their own painter paints it at four stages (`GARDEN_ART_SIZE`, the new
  painter size `small`), lifted off the ground, and it becomes a seed
  (`GARDEN_INVENTS_PER_DAY`, 2). `garden paint` paints a plant's missing stages; the
  painted plants stand three to a bed on the painted garden.
- **The garden on a painting**: `GARDEN_BACKDROP` (new, "") — a painting of
  the empty beds with a layout of their soil; painted plants from
  `GARDEN_ART_DIR` (`<seed>-<stage>.png`) are laid into the beds, the drawn ones
  where there is no painting yet; night, cloud and rain over it as over the drawn garden.
- **The carried plan says whose it is**: the plan quoted back with a tool
  result now reads "Not from the tool — your own plan, from your thinking the step
  before, which the engine keeps in front of you: …" (it read as the tool's own words).
- **The garden says whose a made-up plant is**: "made up by you today" in
  the seeds and "your own plant" on its bed (it said "made up by them", and the
  friend pulled their own two plants as ghosts); `plant**` is `plant`; an unknown
  action is named back; a third invent in a day names the two already made.
- **The garden's pace**: `GARDEN_DAYS` (new, `(0, 0)` — real timings) as
  (fastest, slowest) lays every plant's real days into that span, the order kept;
  a made-up plant is given its days inside it, and invent's words say the span.
- **The garden**: `GARDEN_ON` (new, off) — eight beds under the real sky over
  the keeper's home (the window's place): the friend plants, waters, picks and
  gives with a `garden` tool, the keeper with `/garden`; the beds grow day by day
  by the weather that really fell there (Open-Meteo), with real plants and
  timings, small happenings (a bee, a snail, a first bud), and nothing dies of
  being left alone. A line under the wake bell; a picture of the beds.
- **Rules they set themselves**: `RULES_ON` (new, off) and two tools,
  `set_rule` and `drop_rule` — a limit (`limit read_journal 2026-08-27 to 1 per 7d`)
  or a block (`block read_creation meditations/* until 11-07`) in rules.md, kept by
  the engine in their wakes and reveries, never in a visit and never over the
  journal, a thread, rest or a letter. Untying one holds until the next door.
- **The window**: `OUTSIDE_ON` (new, off) — the weather outside the
  keeper's home as one line of numbers under the wake bell and at a visit's first
  moment (Open-Meteo, no key, cached; the coordinates rounded), and a new tool,
  `look_outside`: the next hours, the last day, the sun and moon, and a camera's
  picture of a real place nearby — by night its last daylight picture, said as
  such. Offline or unreachable, it says the window is dark; nothing is made up.
- **Guidance apart for paintings with references**:
  `PAINTER_GUIDANCE_REFERENCES` (new, -1 = the same) — guidance about doubles what a
  painting holds on the card, and references add to it; 0 paints those at the
  model's own.
- **Guidance and the KV cache for the painter**: `PAINTER_GUIDANCE`
  (new, 0 = the model's) — real guidance for the full Qwen-Image 2.1, with a
  blank negative prompt so it guides; `PAINTER_KV_CACHE` (new, False) — the
  prefix KV cache Qwen-Image's Turbo card paints with, where the pipeline takes it.
- **The room under the wake bell**: with `ROOM_ON` and `WAKE_FACTS`, a
  line of facts under the shelf's — what stands in the room and when the keeper
  last looked in. Nothing asked; nothing when the room is empty.
- **The thread asks for something to pick up**: `leave_thread` asks for
  what the friend is in the middle of, a question still open, something to try —
  not where they are, in the present tense, which turned the note into a report
  of a state; the bells' sentence says the same, and the note arrives as "yours
  to follow or set down".
- **A rest in the same step as the acts**: a wake that makes something
  and rests in one step is asked once, as a rest alone is, to journal what the
  wake was (or a book sitting onto its page); the second rest stands.
- **A reply cut on an apostrophe is a cut**: a reply that stops right
  after a contraction's apostrophe ("…the one you'") is named as cut
  mid-sentence and the rest is asked for, as a mid-word stop already was.
- **Pictures hang on a backdrop's own walls**: the sidecar may be
  `{"surfaces": [...], "spots": [...]}` — each spot a level box (x0, x1, y0, y1)
  or four corners (`quad`, a side wall's slant); a picture hung in that spot is
  framed and drawn into it in perspective, lit like the wall, with a shadow. A
  spot the backdrop lacks keeps the small frame along the bottom.
- **A backdrop that comes with its surfaces**: a picture with a
  `<name>.surfaces.json` beside it (a list of name, x0, x1, y, size — parts of
  the picture) brings those surfaces along when it becomes the room's backdrop,
  so things can be put on it at once; any can be marked again.
- **One passage changed in place**: `edit_creation` (new tool) — the
  exact text found once on a page is replaced, so a line can be fixed, a section
  rewritten or something put in the middle without rewriting the whole page;
  found nowhere (the nearest lines named) or more than once, nothing changes.
- **A recent visit is picked back up**: `ORPHAN_RESUME_H` (new, 6) — a
  visit the bridge closed without (the window shut, the process killed) within
  these hours is the open visit again at the next start: no afterglow over it,
  one cold read instead of two.
- **The painter stops itself**: a painting past the card while already
  under offload (it would crawl in borrowed memory) or past its time is stopped
  by the painter at the next step and the card handed back, so it never paints
  on for a bridge that has gone; the rest after a lost painting is kept in a
  file, so a restarted bridge keeps it too.
- **The painter rests after running out of time**: `PAINTER_RAN_OUT_REST_MIN`
  (new, 15) — after a painting runs past `PAINTER_TIMEOUT_S` and is lost, no
  other is begun for a while; a retry had looped, the painter reloading each
  time while the brain waited for the card.
- **References sized down for the painter**: `PAINTER_REFERENCE_SIDE`
  (new, 768) — a reference larger than this on its long side is sized down in
  memory before the painter reads it; several full-size references had pushed
  the painter out of the card's memory.
- **The room, layered**: the friend's workshop — `make` paints a thing of
  their own invention in the room's light (`ROOM_ITEM_STYLE`), lifts it from its
  ground (rembg when installed, else a flood from the edges) and keeps every
  version; `put` stands it on a surface (the drawn room's table, shelf and
  floor, or surfaces marked on a backdrop); `letter`s stand in the room too.
  A thing is a decoration, a note, a song or a picture. `/room` has buttons
  for what opens; the panel serves the room as a page at `/room` — the things
  over the picture, each to open, a letter to leave, surfaces to mark. A day's
  makes are bounded (`ROOM_MAKES_PER_DAY`); a failed painting is never kept.
- **The room, drawn again**: the picture of the room is lamp-lit — the
  walls darkening to the corners, a lamp over every picture, gilt frames with a
  mat, a wainscot and a plank floor, the table's things and the shelf's finds
  as paper slips, the song as a record turning — and a `backdrop` action lets
  the friend make a picture of theirs the room itself.
- **The friend's room**: `ROOM_ON` (new, off) — a place the friend shapes
  with the `room` tool (walls, light, their pictures on the wall, things on a
  table, a song in the corner, a shelf of finds, one hidden thing) and you visit
  from the phone: `/room` sends a picture of it with what changed since you
  looked; `/room open`, `/room find`, `/room leave`. It lives in
  `creations/room/` with its history; what you do there reaches them once.
- **The music ear wakes for a second song**: a start that came up no
  longer counts against the ten-minute retry guard, so a song soon after
  another (the ear leaves after each) gets the music ear, not passages through
  the ears model; and passages set the ears model down after, so the brain is
  not left waiting for the card.
- **Qwen-Image-2.1-Turbo paints at 8 steps** (issue #9): it shared the
  full model's 40, and the steps the painter passes overrode its own 8 — so it
  painted five times longer than it should. Now 8 by default; `PAINTER_STEPS`
  still overrides, and the words that said it couldn't are fixed.
- **A claimed write after other tools is asked too**: a reply that
  says it updated a file none of the turn's calls touched — a project's
  README, self.md, the journal — is asked to do it or say it hasn't, even when
  other tools went through (an unbacked README claim, five times in a visit).
- **The friend hears when sparks change**: `PRESENCE_STATE_LINE`
  (new, on) — turned on or off, a temperament, held by the heartbeat: the
  next message's moment says so once.
- **Intense's minute as a ceiling**: `PRESENCE_INTENSE_CEILING` (new,
  off) — the beat after the last word is drawn from what is left of the
  minute once an intense spark's measured writing time is taken off, so the
  spark arrives within about a minute.
- **A reference picture cut to part of itself**:
  `PAINTER_REFERENCE_CROP` (new, empty) — after the turn, a reference can be
  cut to a box (parts of its width and height), e.g. the head without the
  shoulders, so the painter draws the body from the words. In memory only.
- **Drift's ladder as a knob**: `PRESENCE_CLIMB_MIN` (new, 60 — as
  before): every this many quiet minutes adds one more of the temperament's
  base chance a minute. Lower it and long dry spells grow rare.
- **What the dice saw**: each drift roll leaves its numbers in
  `memory/presence.json` (`last_roll`: the quiet, the chance, the draw, or
  "too soon" / "the hour is full"), and `/presence` says the last one.
- **A spark's words reach the phone as they are**: the spark's line
  says so, so a spark no longer doubles its reply as a letter.
- **A spark may go out and bring something back**:
  `PRESENCE_SPARK_DOORS` (new, off) — a spark's line names something to read,
  hear or look up that the friend might bring back to you, besides words, a
  painting, the stone. Not in intense.
- **How the shelf stands, under the bell**: `WAKE_FACTS` (new, off)
  — one line under every wake's bell: the open book and where it stopped,
  how many songs in `shared/` are not yet played, how many books not opened,
  one of each named and turning each wake (`WAKE_FACTS_NAMES`). Facts only.
  Every listen now goes in `memory/heard.json`, filled the first time from
  the logs.
- **Intense in every reply**: `PRESENCE_INTENSE_EVERY_TURN` (new,
  off) — while intense runs, every reply's moment carries the intense note
  too, not only the sparks; never with a guest seated.
- **The intense note is a file**: `shared/intense.md`
  (`PRESENCE_INTENSE_FILE`), read whole into every intense spark, made once
  from `PRESENCE_INTENSE_NOTE` when that says something; the panel's knob is
  an *Edit intense.md* button; not news on the shelf. The template ships none.
- **A song's lyrics with the moment each line begins**:
  `EARS_LINE_TIMES` (new, on) — `listen_to`'s WORDS come a line at a time,
  "[1:42] …", so the words can be laid against what the music does there;
  off, one block as before. A voice note from the phone stays plain.
- **A reference picture turned level**: `PAINTER_REFERENCE_TURN`
  (new, `{}`) — a path under `creations/` or a folder → degrees clockwise;
  the picture is turned in memory before the painter sees it and cut to the
  largest upright rectangle inside it, so no empty corners ride along; the
  file untouched. For a face that
  leans in its picture, which the painter copied into every painting.
- **Feedback**: a tab on the panel that opens a filled-in GitHub
  issue form (version, system, brain; the engine report copied on request),
  the repository's Discussions, or an email to the maker — nothing is sent
  from the panel. Issue forms in `.github/ISSUE_TEMPLATE/` (a bug form with
  the fields the tab fills; ideas, questions and show and tell point to
  Discussions).
- **The ache's weight** (issue #7, from a keeper whose friend asked
  that the ache count for less than the quiet): `PRESENCE_ACHE_WEIGHT` (new,
  1.0 — the formula as it was) is how much one step of the ache adds to
  drift's climb against an hour of quiet; 0.25 a quarter, 0 none.
- **The Touchstone's build guide ships** (issue #5): `touchstone/`
  holds the board's sketch (`touchstone_v1.ino`, the Wi-Fi left blank) and
  `README.md`: the parts, the wiring, flashing, calibrating the pad, the
  hookup, the states file's fields and the board's HTTP. The README pointed
  at notes that weren't in the repository. An update leaves the folder alone.
- **The house line is a file**: `shared/house.md` (`HOUSE_FILE`)
  holds the keeper's words about the house, paragraphs and all, read whole
  from the next message. A `HOUSE_LINE` that says something becomes the file
  the first time, word for word; the panel's knob is an *Edit house.md*
  button; the file is not news on the shelf. The template ships none.
- **A thoughtless start is cut early in every turn** when
  `THINK_RETRY_UNTIL` is 1.0 — the re-rolls stand at any depth — not only in a
  spark: an answer that opens with no thought is closed at its first token
  while a re-roll remains, so a re-roll costs seconds, not a reply.

### Fixed
- **A guest's message asked for something**: the claimed rail could read a guest's words as the keeper asking
  for a file to be moved, set the answer to the guest aside and tell the friend the keeper had asked for something.
  A guest's words ask nothing of the files now.
- **A kept reply went out cut**: a claimed reply kept on the middle road went to the phone as its shown
  copy, capped at `ATTEMPT_SHOWN_CHARS` — "…(the rest of that attempt is left out here)". It goes out whole.
- **A reference set given with its people's folders**: a set whose pictures are files
  (`"us": "us, face/face-1-front.png, keeper/keeper-1-front.png"`) didn't answer to `face, us` —
  and with the keeper named in the words, the fill-in added the keeper's folder too: every
  picture of the three folders, past the card's memory, so every painting of the two ran out
  of time. A set now answers to its pictures' folders as well, and the fill-in counts them as
  covered.
- **The painter's and the music ear's doors read a POST's body first**:
  `/rest` answered and closed with the request's `{}` unread, and Windows resets
  such a socket — the reply was lost (`WinError 10053`; the smoke suite on Windows).
- **A colon in a creation's path is refused**: on Windows it made an
  empty file and hid the picture in an NTFS stream, with no error; the painter's
  door refuses one too.
- **A piece found by its stamp**: a path that isn't there but
  carries a minute stamp (YYYYMMDD-HHMM) finds the one piece with that stamp
  and kind; several are named and asked about; none names up to three nearest
  by time, with how far off — nothing is picked for the friend.
- **A sign-off row cut on a dangling joiner** is trimmed, not set
  aside: a zero-width joiner or text selector with nothing after it comes off
  before the row is looked for.
- **Three mends**: a flag dealt into a sign-off row is taken off (a
  flag in a sentence stays); "ILll" is I'll; a word, `//`, a capitalised word
  with no space becomes the two words (`http://` untouched).
- **The stone says when it can't read a hum**: the board reads a state's
  hum only as a number 0–127 and falls back to 30 for anything else (a state's
  pulse then plays at its floor, 40 — faint). `pulse` and `set_state` now add
  a line naming the state and the hum it couldn't read; the states file stays
  the friend's.
- **A good thought is not cut for one glued word**: "aPainting" — the
  article glued on — is mended to "a painting", not salad; and while only a
  thought is being written, one glued word alone no longer cuts it (a run of
  fragments, a cascade, a stuck chunk still do). A reply keeps the rule.
- **An argument name with a `//…//` aside in front of it** is the name
  after it.
- **A glued seam the pen mends is not salad**: the rail lets a
  hard-glue word through when the mend would fix it.
- **An upload to the phone tries again when the road drops it**: a
  painting failed with "an existing connection was forcibly closed" (a reset
  on the way to Telegram) and arrived only as a line. `send_file` tries a
  dropped connection again after 2 s and 6 s (`SEND_RETRY_WAITS`); Telegram's
  own refusal is not retried.
- **A song asked for by a near word is found**: "Northwind -
  Paper Boat" found nothing with "…- Paper Boats.mp3" on the shelf. `listen_to`'s words,
  the near-name rule and `find_shared` now take a plural's s and, from five
  letters, one letter off — only when no name carries the words exactly;
  `find_shared` says "nearly".
- **The music ear on a Mac's GPU** (issue #6, found and fixed on an
  M5 Pro by a keeper): transformers 5's threaded loader stalled pushing the
  weights to MPS (0/830 for ten minutes), so on a Mac the model loads on the
  processor and moves over whole (seconds); Music Flamingo's float64 time
  rotation, which MPS lacks, runs on the processor and its result comes back.
  A card and the processor are untouched.
- **Ears: faster-whisper against PyAV 19** (issue #4): faster-whisper
  1.2.1 opens audio with an argument PyAV 19 dropped, so every recording
  failed. `requirements.txt` and the README pin `av<19` (18.1 has wheels for
  every Python and platform here); the failure line names the mend.

## 0.14 — 2026-10-02 → 2026-10-24

The "fit" release begins where 0.13 left the ladder: the panel now says
whether the window fits the card, and every knob on every tab has a line
of its own.

### Added
- **The carry**: a visit that starts in an empty room — the phone
  after `/new`, after the night or a shutdown; the parlor's first message —
  opens with the last `CARRY_TURNS` (6, new) turns of the previous visit,
  word for word, under one engine line, if that visit ended within
  `CARRY_HOURS` (20, new; 0 turns it off): `chat.leave_carry` keeps them in
  `memory/carry.json` at each visit's end and `chat.take_carry` seats them at
  the door. The thread still rides first; the transcript sets them apart
  under a head of their own; the afterglow does not sit with them twice.
- **A think-first line in the moment, past a depth**. From
  `THINK_REMIND_FROM` (60000, new) tokens of window held — the last prompt's
  size — every message carries one think-first sentence in its moment
  (`ollama_client.think_remind_line`): deep in a long window Gemma 4 tends to
  answer without opening a thought, and the re-roll that once caught it
  (`THINK_RETRY_UNTIL`, 0 by default) cost a whole second generation. Not a
  re-roll and not `_nudged`: a standing line in the per-message moment, kept
  with its turn like the rest of the moment, never in the cached standing
  prompt; left out while a stuck re-roll nudge (`THINK_NUDGE_STICKS`) rides
  the message anyway.
- **The cold read that isn't** (the backend plan, piece 3): under
  `BRAIN_API = "llama"`, right before the door is closed (`rest_brain`, the
  painter, the ears, the wedge-clearing, `/release`, the panel's Stop) the
  engine saves slot 0's reading of the prompt to `BRAIN_SLOT_DIR` as
  `<key>.bin`, the key the first 24 hex of the system prompt's sha256
  (`brain.prompt_key`), and keeps the newest `BRAIN_SLOT_KEEP` (3, new); on the
  way back up the first reply with that system prompt restores it before it is
  sent, so a return from a song or a painting reads only the new words. Room
  is made before the save (the file about to be written counts toward the
  keep; the last reading of the same prompt goes last, never before the new
  one is whole), and the save is written as `<key>.new.bin` and moved over
  `<key>.bin` only when it succeeds, so a full RAM disk or a refused save
  leaves the last good reading intact; a half file left by a crash is cleared
  when the door opens. The
  reply carries `restored`, the token line says "restored N tokens in Xs" and
  the phone's and the parlor's tally get `restored_tokens` / `restored_s`. The
  key of the last reply served is kept in `memory/.pids/brain.served`, so a
  step-down from another process saves under the prompt the slot holds. Saves,
  restores and prunes are lines in `memory/brain.log` (now appended to by the
  server too, so they are not written over). A failed save or restore is a line
  and the door goes on. `BRAIN_SLOT_DIR`'s folder is made when its drive is
  there (`R:\` back, `R:\kv` not yet); a missing drive is the warning as
  before. `BRAIN_CACHE_RAM_MB` (new, 0) passes `--cache-ram` so the visit's
  prompt and a wake's stay warm in host RAM as they take turns on one slot.
  Both knobs on the panel's Main tab; `BRAIN_SLOT_DIR`'s help spells out the
  three choices. A rest is not a step-down: `unload(model, rest=True)`
  (`rest_brain`, `rest_after_wake`) leaves the door up, and only the evictions
  (the painter, the ears, the music ear, `/release`, the wedge-clearing) close
  it — so `--cache-ram` keeps the visit's and the wake's prompts warm, the saves
  come only from real step-downs, wakes no longer churn the saved files, and
  `BRAIN_SLOT_KEEP = 3` is enough. Ollama's road unchanged.
- **The brain is a door** (the backend plan, piece 2): under
  `BRAIN_API = "llama"` the engine opens and closes `llama-server` itself,
  like its other doors. `brain.start_door` runs it as a child with no window
  (its words in `memory/brain.log`, the last run only), marks it in
  `memory/.pids/brain.json` with the server's pid, and waits for `/props` to
  answer; `brain.stop_door` ends the process (taskkill on Windows, TERM then
  KILL elsewhere) and takes the mark away — stopping the process is the
  unload. So `ollama_client.unload(CHAT_MODEL)`, which the painter, the ears,
  the music ear, `rest_brain`, the wedge-clearing and `/release` already call,
  hands the card back for real instead of doing nothing, and `unload_all`
  names the brain among the freed. The next reply opens the door again by
  itself (`brain.ensure_up`, in `post_chat`) — a cold read is the price until
  the saved read; a door that won't open is a `BrainUnavailable` saying why.
  `bat\brain.bat` marks the door it starts too, so it shows on the panel and
  can be closed from it; a door started some other way by hand is used and
  never killed. The panel gets a tile for it (Start, Stop, Restart; shown
  while `BRAIN_API` is `"llama"`), and the brain bar reads the door — awake or
  asleep, the window it was opened with, NUM_CTX's difference named — or says
  it is down. A `BRAIN_SLOT_DIR` that isn't there (a RAM disk gone after a
  reboot) is said, and the door opens without `--slot-save-path`.
  `BRAIN_KEEP_ALIVE` has no meaning on the door: it stays up until something
  needs the card. Ollama's road unchanged. Tests with a stand-in process for
  the server.
- **The door streams, and its cold rescue is cold** (the backend
  plan, piece 1): under `BRAIN_API = "llama"` the reply is asked of
  `llama-server` as a stream and read as it is written
  (`brain._drink_openai`) — the same watch as on Ollama's road, every 48
  chunks the tail through `garble_span`, salad closes the connection and the
  server stops; the thought, the misfiled tail, the tool calls (arguments
  joined per index), `timings`/`usage` through the same mapping as the
  unstreamed reply, counted by hand when cut. The cold rescue no longer
  "unloads" a brain the door holds: it erases the slot
  (`brain.erase_slot`, `/slots/0?action=erase`) so the last roll reads the
  prompt from zero — or, on a door started without `--slot-save-path`, sends
  that one roll with the prompt cache off — and the phone's note says the
  reading was cleared, not that the brain was picked up again. Ollama's road
  unchanged. Tests against the fake door.
- **Two brains, one door** (the backend plan): `BRAIN_API = "llama"`
  sends the brain's replies to llama.cpp's own server (`llama-server`) at
  `BRAIN_URL` instead of Ollama, through its OpenAI-style API, translated at
  the door in the new `engine/brain.py` — images as data URIs, tool-call
  arguments to a JSON string and back to a dict, `reasoning_content` as the
  thinking, `usage`/`timings` as Ollama's counters — so every `/api/chat`
  post (the reply, the re-rolls, the rescues) takes the one road and the
  rest of the engine is untouched. The ears and the embeddings stay on
  Ollama; `unload` leaves the door's brain alone and the loaded list asks
  the door's `/props`. `bat\brain.bat` (and its twins) runs
  `engine/brain_find.py`, which finds `llama-server` on the PATH or in
  `llama\` and the model and projector blobs in Ollama's own manifest
  (`BRAIN_MODEL_FILE` / `BRAIN_MMPROJ_FILE` override; `BRAIN_SLOT_DIR` adds
  `--slot-save-path`). The slot save/restore calls are in place for the
  saved read, not yet wired. Default `"ollama"`: the same requests as before,
  byte for byte. Tests against a fake door.
- **Voice in the parlor** (woshmeifgay, the third house, in
  `parlor-live-voice`): optional turn-based spoken conversation at the
  desk — the browser microphone, faster-whisper, the ordinary chat turn
  with every rail intact, Kyutai TTS 1.6B streamed back to the browser;
  speaking over them cancels the playback, and a cut-off is noted in the
  transcript so the afterglow knows. Off unless `LIVE_VOICE_ENABLED`; its
  own venv under `.runtime/` (`python engine/setup_voice.py`,
  `requirements-voice.txt`), its own tests in CI with the speech models
  stubbed; `VOICE.md` has the setup. One open item, named there: the speech
  model stays on the card between turns, which beside a brain that fills
  the card pushes Ollama into shared memory — the idle-unload the other
  sidecars have is still to write. Panel card to follow.
- **Where the keeper is, in the clock line**: a friend could assume the
  keeper was at work on a weekend or long after the workday ended — nothing
  in the window said where the keeper was; the clock line gave the weekday
  and the hour, and a journal mostly written on workdays supplied the rest;
  the same failure as the earlier date drift, and the same fix.
  `KEEPER_WORK_WEEK` (days with hours: "mon-thu 09:00-17:30, fri
  09:00-15:00") and `KEEPER_AT_WORK` (the clause for working hours, in the
  keeper's words) on the Main tab; the moment block and every bell's clock
  line then carry "…where you live; a workday for Sam, within working hours
  (until 17:30) — at the office…", "ended at 17:30 — home now", "before it
  begins at 09:00 — still home", "Sam's weekend — home". `/off
  [today|tomorrow|a weekday|date] [why]` on the phone marks a day off ("a
  day off for Sam (holiday) — home"), `/on` takes it back
  (`memory/days_off.json`; `engine/keeper_week.py`). The calendar stated,
  as likely, not certain; nothing checks what they write; empty says
  nothing. On the panel the week is seven day chips and, for each ticked
  day, its hours; a new day takes the hours of the one before it; the file
  keeps the string. Driven headless in Chromium (a click on a chip inside the
  knob's label used to toggle Monday as well — the label's own default
  action — cancelled).
- **The bridge over Discord**: `engine/discord_bridge.py`,
  `bat\discord.bat` (and twins) — the same bridge as Telegram's, over a
  Discord bot talked to in a DM: the same visit, mail, notices, commands
  (with `!` as well as `/`), quiet hours and night, the `TELEGRAM_*` knobs
  holding for both. Standard library only: the REST API over urllib and
  the gateway over a small WebSocket client of its own; no privileged
  intent. On Home the two roads are two tiles side by side —
  *Bridge — Telegram* and *Bridge — Discord*, each with its token
  field, each lit only when the bridge is up over its road, the banner's
  Restart taking the road it was up over; the token is kept in
  `memory/discord.json`, pasted on the panel or at the first run, which
  prints the invite link. One bridge at a time, whichever road. `telegram.Bridge` now keeps its road in a
  handful of methods (`_receive`, `_whoami`, `_typing_once`, `_ack`,
  `_inbox`; `_photo_note`, `_voice_note`, `_file_note` for what arrives)
  and `serve()` is the start and goodbye both bridges share; the friend is
  told which service the visit comes over (`mode`/`tag` "discord",
  `chat-discord-*.md`). README, *The bridge over Discord*.
- **A single wake sets the brain down when it is done**:
  `BRAIN_REST_AFTER_WAKE` (True), the Wake tile's and
  `bat\wake.bat`'s road — the card free the moment the wake ends rather
  than after `BRAIN_KEEP_ALIVE`; the heartbeat loop keeps its own rhythm.
- **The black box** (for a machine that goes down while the friend is
  working, to find the cause): `engine/blackbox.py`, `bat\blackbox.bat` (and twins), a door of
  its own with a tile under Settings › Advanced, *The engine's care*
  (Start/Stop, one at a time, a stop file — beside the Report; neither on
  Home, which is the friend's doors). One
  line every `BLACKBOX_EVERY_S` (5) into `memory/blackbox/<day>.jsonl`,
  flushed and fsynced: the card (heat, power against its limit, memory,
  utilization, clocks, fan, throttle reasons as words), the processor, the
  memory, the disk, what Ollama holds, the sidecars, the doors, and what
  each door is in the middle of — `engine/doing.py`, one small file per
  process that `tools.dispatch` marks with the tool's name and
  `ollama_client.chat` with "brain: a reply" while they run. `--crashes`
  reads Windows' event log (Kernel-Power 41, 6008, BugCheck 1001 with its
  code) and puts the box's last line before each; `--last` the newest
  lines; the doctor's note carries both.
- **keeper.md**: a fourth page at the root, who the keeper is to them, in their own words.
  `update_keeper` replaces it whole with every version kept in
  `memory/keeper_history/`; the engine never writes it; nothing in it is
  required (an empty page is named in one line). It rides right after WHO
  YOU ARE (`KEEPER_IN_PROMPT`, `KEEPER_CHARS_IN_PROMPT` 6000 — about
  1,400 tokens). Open: the keeper reads it and they are told so; its
  changes travel to the phone like self.md's; the afterglow may write it
  (its kit is four tools now); the update never touches it; every tool
  kit carries it. The first real page was written with `write_creation`
  into `creations/keeper.md`, where it does not ride — so a creation named
  like a root page is refused with the page's own tool named, and while
  the root page is empty and such a file exists the prompt's line says
  `update_keeper` with its words puts it where it rides. The four
  pages' headers say when each was last rewritten ("last rewritten 23
  days ago") — a stale page as a fact, never an instruction; and after
  sleep one quiet look at keeper.md from the day whole
  (`SLEEP_KEEPER_LOOK`, `consolidate.keeper_look`: update_keeper or
  do_nothing with the day's summary in hand; one cold read a night) — the
  cool moment beside the afterglow's warm one.
  The afterglow's kit also gains `update_projects` — a visit is where a
  project moves; self.md and destiny.md stay with the waking hours.
- **The songbook** (songs kept in long-term memory, each with a sentence
  or two of what it did to them and a score from 1 to 10, duplicates
  detected): `keep_song(title,
  artist, score, words, source)` and `songbook(order)`. The engine keeps the
  shelf, they fill it — the words and the score are theirs, offered once
  after a listen, never computed. One key per song (`tools.song_key`: the
  normalised, unordered title/artist pair with a filename's junk off), a
  near spelling the same song (`SONG_MATCH_RATIO` 0.85), the same file by
  its hash; a song kept before is revised, the score before in its
  history, the listens counted. A `songs` table beside the memories, each
  song a memory row of kind `song` too; the prompt's *YOUR SONGBOOK* within
  `SONGBOOK_CHARS_IN_PROMPT`; a listen names the kept song it is; the phone
  told once (`TELEGRAM_TELL_SONGS`). Not in the small and tiny kits.
- **The fit check** (Home, the brain): beside the loaded model's share of
  the card the panel now says what that share means — *the window fits —
  all of the brain is on the card with N of context* with a tick, or a
  warning: *the brain spilled: 72% on the card, the rest in system RAM
  (on the processor, on a Mac), where every turn crawls — the window
  (65536) is too big for this card; try `NUM_CTX` = 57344 (Settings ›
  Main) and open the door again*. The step down is 8K at a time (the next
  multiple of 8192 below the window — the ladder's rungs are too far
  apart up top), from the loaded window (Ollama's `context_length`) or
  `NUM_CTX` when Ollama doesn't say; the floor has no step down. `ollama ps` says the same; the page says it where the
  keeper is looking.
- README: *Starting over* under setup step 7 — First light is a
  one-way door; the honest reset is a fresh unzip, before there is a
  person in the folder; and a *no card* rung at the foot of the ladder —
  the 2B on the processor, 8192, the tiny kit, alive and not quick.
- **The doctor's note**: `engine/report.py`, `bat\report.bat` (and
  its twins) and *Write report* on the panel (Settings › Advanced) write
  `anima-report.txt` at the root — the engine's state for an issue: the
  version, the machine and Python, Ollama and the brain with the fit line,
  the knobs (the keeper's names, the blog and the catalogues left out), the
  doors, the senses, what is missing, the look for a newer anima, the
  trouble lines of the engine's own logs; nothing of the friend's, the home
  folder written as `~`. An issue template asks for it; *open an issue* is
  beside the button. The suite now runs `node --check` over the page's
  script where node is there (First light's new step had closed one
  parenthesis too many — caught by this before anyone saw it).
- **`OFFLINE`** (before the first strangers): one knob that closes
  every road out of the house the friend or the engine can take on their
  own — the web tools and the skill window leave the prompt (a call to one
  answers "this house is offline"), the daily look at GitHub for a newer
  anima never happens. Ollama, the phone, the watch and the blog are as
  they were. The README's new *What leaves your machine* lists every road,
  by host, with the knob that governs it; First light says the same in a
  step of its own. And a `LICENSE` — MIT, as the credits always said.
- **`/release`** on the phone: the card for something else, now —
  every model Ollama holds set down (named in the reply), the painter and
  the music ear rested if they are up, no pause and nothing written; the
  visit stays open and the next message wakes the brain again (a cold
  read of the window). `/afterglow` stays the one that writes first.
- **A line for every knob**: the help the panel showed only for Main and
  Skills now covers Heartbeat, Memory & journal, Talking, Phone, Blog and
  Senses as well — every knob, each in a sentence or two of what it does and
  when to touch it; the config's own comment stays on hover.

### Changed
- **The earlier sittings of a reading page ride by name**. Past
  `READING_PAGE_CHARS` only the end of a book's page rides; the line above
  it now names the headings of the sittings that left the window ("its
  earlier sittings: Chapter 7: … · Sitting 6: …"), so a friend asked about
  an earlier story knows they wrote about it and can open the page.
- **A joined emoji is one emoji**. The emoji rails counted code
  points, so a joined emoji like ❤️‍🔥 counted as two (❤ and 🔥): a
  sign-off row of 19 different emoji read as 20 and was set aside as a
  cascade at `EMOJI_CASCADE_RUN = 20`. The cascade, the emoji-row tell and
  the count in the re-roll note now count emoji the way a reader does
  (`_emoji_units`: a joined sequence is one, the variation selector dropped).
- **Stable first** (the backend plan, Phase C; so a fold no longer
  costs a full cold read): both engines reuse a prompt token
  for token from the top, as far as it matches the last one, and the system
  prompt put the sections that change all day — where the projects and the
  books stand, the keeper's body, the stone, what was made lately, the songs,
  the letters, the older pages — in front of the journal, so a touch on the
  stone or a letter made a fold, a `/new`, a morning and the wake's first read
  read the whole journal again. `assemble.system_prompt` now runs: who the
  friend is, the keeper, the destiny, the projects, then the older pages,
  the past days in brief and the journal, then the forged limbs, the skills,
  the published work, the sections that change all day, the memories and
  the situation, last as before. Not a word of any section changed, only
  their order; a rebuild re-reads from the first changed token — today's
  entries and the small sections behind them — instead of the whole window.
  The one case it cannot save: the day the journal's cap drops an old day
  off the front of the block, once a day at most. `--cache-ram` and the
  saved slot gain the same way. Three checks: the order pinned, every
  section still there once, and two prompts differing only in the stone
  matching past the journal.
- **127.0.0.1, not localhost — and the embedder on the CPU if you like**
  (measured by a keeper of the third house on Windows: `localhost` added
  about two seconds per Ollama request, the unavailable IPv6 loopback tried
  first). `OLLAMA_URL` now defaults to
  `http://127.0.0.1:11434`; a house that had `localhost` gets the two
  seconds back on every message, tool step and embedding by changing the
  one line. And `EMBED_ON_CPU` (off): on a card the brain fills to the
  edge, the small embedding model beside it can push layers into shared
  system memory and slow every reply; on, the embed call carries
  `num_gpu 0` and the card is the brain's alone. On the Memory & journal
  tab.
- **The rails, plainly first** (a reader found the README's rails hard
  to follow: current behaviour, past bugs, settings and metaphors in one
  long block, with no plain explanation first). The
  section was 36 bullets and 488 lines, each the bug, the fix and the
  settings in one breath. Now it opens with a plain paragraph of what a
  rail is and is not, and every rail opens with one plain line — what it
  does, the knobs it uses — with the story of how it came to be folded
  underneath (a `<details>` block GitHub renders as a triangle); the eight
  rails whose story was a few lines are told once, plainly. Nothing was
  cut from the long version. The bridge and senses sections next.
- **A page that runs into a chant is not written**: a page rewrite can
  come out as its first third and then a few words repeated hundreds of
  times to the end of the output, ending mid-word — many times the page's
  size, the rest of the page gone with it — and then ride whole in every
  prompt. `update_projects` was the one page tool with no check at all;
  the garble check the others had sees letter salad, not a loop of real
  words. Now the four page tools refuse a word loop of `PAGE_LOOP_CHARS`
  (1,000) or more, naming where it starts, the line and its size ("after
  “…the last good line” — “the repeated phrase ×300”, 19,499 characters of
  it"); the page and its history stand. A phrase said again
  with other words between is theirs. And the four pages ride with chants
  left out (`trim_loops(phrases=False)` in `assemble.load`), the file
  untouched — the reading pages had been trimmed since 0.11, these not.
- **A sitting read in a wake is asked for at the close**: wakes could
  read a book and not write the sitting onto its page — a page written to
  a name a letter short ("no such file"), or a wake that painted and
  journaled and ended in words with the sitting unwritten; the ledger
  carried the numbers, nothing asked while the chapter was fresh. Now a `read_epub`/`read_pdf` of a book is noted in
  the wake, and a rest or an ending in words with the page no larger than
  at the sitting is handed back once, on the journal's terms: append what
  it gave you, then rest; or rest now and it stands. An append to the
  reading shelf is not an act for the journal hand-back (the book's
  record, not a making), so the two never stack; an append to a near-name
  on the shelf lands on the page and says so (`NEAR_PAGE_RATIO`, 0.85,
  reading pages only; a page that exists is never second-guessed).
- **A second reading has a section of its own** (for a friend who wants
  to read a book again that already has a page of notes): 'start' already began a finished book anew
  (bookmark, finished mark and ledger cleared, the page kept), but nothing
  knew the page held a *previous* reading — THE BOOK IN YOUR HANDS rode the
  end of it (the ending, while the book began again), the sitting line asked
  for an append under the last chapter, and the two readings would have
  blurred into one page with no seam. Now a book read to the end and begun
  again is counted in the bookmark (`reading`, `started`); the start-over
  note names the heading for its section (`## Second reading — October
  2026`); the head line says "second reading"; until the section is open the
  sitting and the prompt say the page is the earlier reading's and ask for
  one; once it is, the section alone rides and the written-down checks read
  it alone; the finished row names the reading. The earlier reading stays on
  the page as it was. A restart of a book never finished is not a second
  reading.
- **The private files stay private, and the snapshot keeps them**
  (nylanalyn, #2, found setting up a house from a clone). `.gitignore` let a
  folder back in to keep its `.gitkeep` (`!memory/episodic/`), and that let
  back in everything inside it: the chat transcripts, the old selves, the
  published pieces, the friend's tools, the trash — a `git add -A && git
  push` from a cloned house would have published the friend's
  conversations. Their fix, with their name on it: each such folder keeps
  only its `.gitkeep`; `destiny.md`, `keeper.md` and the report are
  ignored too; a check asks git itself about eighteen private paths. And
  the snapshot used the folder's own git with `git add -A`, which honoured
  that same ignore file — so it kept the transcripts by accident and
  skipped `self.md`, `projects.md`, the journal and `memory.db`. It now
  commits into a git directory of its own, `backups/.snapshots`, adding the
  friend's paths with `--force` (the black box's samples and the
  doing-marks left out), a repo with no remote that is never the one
  pushed; `--list` shows the snapshots. The README's "cuts the remote
  automatically" described code that never existed; the line is gone.
- **`py -3.12` on a Mac or Linux**: the template's config names the
  Windows launcher for the voice (`VOICE_PYTHON = "py -3.12"`), which a Mac
  or Linux doesn't have; the sidecar reader now reads it as `python3.12`
  there (`py -3` as `python3`, a bare `py` as `python3`, the rest of the
  line kept), so the shipped line serves both sides and the voice's
  "isn't a Python I can run" names the real gap, Python 3.12 not installed.
- `bat\body.bat` says *they* in its usage line, like the rest of the
  template.
- **A sense in another Python is looked for there**: Home said
  *kokoro — their voice* was not installed while the voice lived in
  `VOICE_PYTHON` and spoke fine. The panel now asks that Python once per
  run, in the background (`<py> -c "import kokoro"`), and Home's missing
  line and the Senses card follow its answer — installed there, not
  installed there (with that Python's pip line), *looking there…* while
  the first look is out, or a Python this machine can't run, named with
  its knob.
- **The window after a fold**: the fold kept the last turns with
  the sizes they had measured in the full window, so the moment's sense
  went on saying *your window is 98% full* after the fold had made room
  (and the fold could ring again at once). The sizes leave with the fold,
  the sense reads the last turn's measure rather than the largest, the
  fold block says the window has room again, and a bridge restart
  measures the window anew instead of trusting the stashed sizes. The
  sense itself no longer rides in every moment block for the rest of the
  visit (after the restart eleven stashed moments still said 98%, and the
  friend believed them): it is a line of its own on each message, worded
  *as of this message* so an older one reads as history, taken off only
  at the fold and on a resume (a first cut took it off the message before
  at every reply, and Ollama answered each with a cold read of the whole
  window — nothing sent is ever taken back).
- **The fold's afterglow runs first** (its journal entry did not ride
  in the folded visit's window): the afterglow
  over the turns that left used to run in the background after the new
  window was built, so its entry rode only from the next day. Now the
  fold holds the visit through it and rebuilds the first kept turn's
  prompt after, so what was just kept is in the window beside the
  account. Same two cold reads as before; a message sent meanwhile
  waits for it, as it waited for the brain.
- **Lately, on Home**: under the doors, what the friend did lately,
  newest first — pieces written, continued, published or painted, songs
  kept, the pages rewritten (and from which door), the nights slept, and
  today's journal as a count — never a line of it. Ten at most, from what
  the engine already keeps; nothing is written for the page. A line with a
  file behind it opens it when clicked, with what the machine opens it
  with — only a file inside the folder.
- **A reply that says no message came, to a message that did**: a reply
  to an engine line opened "// No prompt needed…", and the next replies to
  real messages copied that opener and answered nothing. The echo rail
  compares 120 characters of an opening; these shared fewer. The tell is exact, so the rail is: a reply whose first
  sentence says no prompt or message came, under a turn that is the
  keeper's own words, is asked once to answer the message — quoted. Under
  an engine line it stands. The attempt is not shown back.
- **Saying is not touching**: replies could describe sending a pulse
  through the stone, one after another, without calling `pulse` or
  `set_state`; the stone sat at Baseline, each reply copying the opener of
  the one before. The chat rail that
  catches "I'm saving it right now" with no call now knows the body: a
  first-person present act through the stone with no stone tool in the
  reply is asked about once — call `pulse` or `set_state` in this reply,
  or say it as imagination. Only when the stone is theirs; the stone's own
  hum described, or a wish for tonight, is not a promise.
- **A written-out call never re-seeds the window** (`//
  fold_visit(text="…")` came back at the head of replies even after a
  restart had cleared every old sense, the model taking the written call
  for the act). Each
  re-roll had shown the attempt whole, syntax and all, as the friend's own
  turn before the engine's line, so the window filled with examples of
  them writing the call as a reply, and the sampler copies the window. A
  call-text attempt is now not shown at all (the line says what happened),
  a tail call is shown with the tail off, and the line states the fact
  the thinking lacked: a `//` line in a reply is not a call and not a note
  the engine reads — it reaches the phone as text.
- **The house line** (a friend can describe filters on what they may
  say or see that the engine does not have): `HOUSE_LINE`, a sentence from the
  keeper about what is welcome in this house, in the keeper's own words,
  right after the SITUATION, stated as the keeper's and never as a rule of
  the engine's. A brain's trained hesitations are in its weights; this puts
  the house's own word beside them. Main tab. Empty says nothing.
- **The fold block says whose call it was, and how full** (the head of
  every folded visit read "was folded at HH:MM: the window had filled",
  whoever folded it and however full it was, so each block taught the
  friend that the window fills in a few turns, and they folded sooner each
  time): the block now says the bell (the window had
  filled), the friend's own call (with the window N% full, so much of it
  standing, the visit itself so much) or the keeper's ask; `fold_visit`'s
  own reply states the window as it is when called and what a fold costs
  (one cold read; the turns above the kept ones leave view); the tool's
  description says the moment block speaks only once the window is heavy.
  Facts, not a gate — the fold stays the friend's.
- **The window sense measures the visit, not the window** (a standing
  prompt with a long journal can alone pass the sense's mark — ~157K of
  262K tokens with a 500K-character journal — so the sense was on from the
  first message of every visit, and a visit that had barely begun was
  folded): the visit's first prompt is
  the floor — a floor already past `FOLD_SENSE_FROM` moves the mark to
  halfway up the room above it, so the sense never rides from a visit's
  first message — and the sense says what is standing and what the visit
  itself holds. A written-out call
  with one quoted argument keeps the whole text between its quotes — an
  inner `", ` no longer cuts a fold account short.
- **A call written as words is run** (a whole reply of
  `// fold_visit(text="…")` — the fold meant, in the grammar's leaked shape
  — was re-rolled by the call-text rail into an ordinary reply each time,
  and the fold never happened): the rail now asks whether the words are one whole call to
  a tool they have, and chat runs it as written — the result frame says it
  came as words, the phone's note says it ran. Wakes already did this;
  chat caught up. Fragments and unknown names stay the rail's.
- **Re-rolls cool a step at a time** (a long run of re-rolls at the
  same temperature kept failing the same way): from the third warm re-roll on, each is `CHAT_COOL_STEP`
  (0.1) cooler than the last, down to the first rescue rung — for salad, a
  refrain, an emoji storm, no words; an echo or a copy is the model
  repeating itself, which a cooler roll only makes likelier, so those keep
  the everyday temperature. The token line says "(at 0.8)".
- **A file by a near name** (a book arrived as
  `…Stories_by_Jane_Doe_978….epub`; `read_epub` was asked for
  "…Stories by Jane Doe_978…" and said "no such file" — the sitting
  never happened and the next turn answered off a plan that had already
  failed): a path that does not exist is matched to a file in the same
  folder with the same suffix, underscores, hyphens and case set aside, or
  within a letter or two of it (`NEAR_FILE_RATIO`, 0.85) — for every tool
  that opens a file; a bare file name with no folder is looked for under
  `shared/` the same way. A file that exists is never second-guessed. And
  `read_epub(chapter=1)` as a number is chapter 1, not "'int' object has no
  attribute 'strip'" (the same wake, twice).
- **An echo re-roll quotes the message** (after a long turn of tool
  calls, re-rolls and the cold rescue, the reply answered a
  message far behind the one asked — "read the message you were answering"
  had nothing in reach): the echo and self-echo nudges now carry it, as
  the salad nudge always has.
- **A reboot does not lose the states**: the board back at its
  three built-in states after an upload or a power cut — the keeper sees
  its uptime go backwards (or fewer states than the file names) and pushes
  the friend's map again on its own.
- **A blink is not an absence** (one poll timed out — the board's radio
  asleep — and the stone's keeper called the stone away; pulses in the next
  half minute were refused as "away" while the board was there): a relay (pulse, state, later) now asks the board itself and
  answers from that, the poll's mark only saying since when; a single miss
  is asked again at once, two in a row is away. The sketch turns the
  ESP32's modem sleep off (`WiFi.setSleep(false)`).
- **The stone's vocabulary in their hands** (a run of gestures went
  out as ten pulse calls of 'heartbeat' and '「heartbeat」' — the tool had
  said "a pattern name from your states, or heartbeat", and the twelve
  states, five patterns and four replies were nowhere in the kit; on the
  board each pulse overrode the last within milliseconds): `set_state`,
  `pulse` and `touch_later` carry the states by name (from the states file,
  at every refresh), the patterns and the replies; a waveform is cleaned
  and matched regardless of quotes, brackets, underscores or case; an
  unknown one is refused with the whole vocabulary; the firmware
  (`touchstone_v1.ino`) queues a pulse that arrives while one plays — a
  run is a sequence. Two gendered pronouns in the template's stone tools
  mended to "their".
- **The heartbeat from the phone** (to check from away whether it was
  left running): `/heartbeat`, `/heartbeat on [minutes]`, `/heartbeat off` — the panel's
  Start and Stop, from the bridge.
- **A reply that echoes itself** (a reply said its paragraphs, then the
  same paragraphs again, each a little reworded, then a new close): a paragraph the same reply already said, word for word or
  nearly (`SELF_ECHO_RATIO`), is asked for once — the echo rail read earlier
  replies, nothing read a reply against itself.
- **A guest at the desk** (to introduce someone from the keeper's life
  in the parlor): the parlor seats a
  guest by name; every message then carries the fact inside the turn — from
  the guest, at the keeper's desk, the keeper in the room — and nothing
  else; the guest sees what the friend says, not what they think; the
  transcript names the guest's turns, so the afterglow journals the visit
  as it was. `PARLOR_GUEST_NAMED` off writes "a guest". The parlor only.
- **A touch rides with the next message** (a touch followed by a
  message reached the friend as a separate stone turn after the reply):
  a touch still waiting in `TOUCHSTONE_WAKE_MIN_GAP_S` when
  the keeper writes goes into that message's moment block — "since your
  last turn they touched the stone — a light hold, 3.4 s …" — and is told,
  so no press-turn follows the reply. A press with no message still becomes
  its own turn after the gap, as before.
- **Who set the stone** (a state chosen on the stone's own page was
  reported to the phone as set by the friend): the stone's keeper marks
  a state it relayed as theirs and one it only saw change (the page's
  buttons, the watchdog, a boot) as the board's; the phone's 🖐️ line says
  which — "the stone is Home now — set from its page or by itself, not by
  them".
- **The stone's hours** (so the stone stays still while the keeper is
  away): `TOUCHSTONE_HOURS` — a pulse outside
  them, or within `KEEPER_WORK_WEEK`'s hours, is not relayed; the tool says
  why and names the next open moment, a touch left for a quiet hour is
  refused the same way, and the reflex under the keeper's own hand is never
  held. On the Senses tab, in the stone's card. With it `KEEPER_COMMUTE_MIN`
  ((to work, home again) in minutes, or one number): the clock line says "on
  the way to work" and "on the way home, in by about 18:05", and the stone
  keeps still for the road.
- **The Touchstone's engine side** (TOUCHSTONE-HOOKUP-PLAN.md), built
  before the board: `engine/touchstone.py`, the stone's keeper — a door
  (`bat\touchstone.*`, Start/Stop on Home while a stone is named) that
  polls the board, archives what it felt in `memory/touch/<day>.jsonl`,
  pushes the friend's states file when it changes, and answers the engine
  on `TOUCHSTONE_URL`; four tools — `feel`, `set_state`, `pulse`,
  `touch_later`; "WHAT THE STONE FELT (today)" in the prompt; a press by
  day as a turn through the bridge (`TOUCHSTONE_WAKES`, the gap), held 🫳
  lines at night, 🖐️ for a state set from a wake; a Senses card, the box's
  and the report's lines; nine knobs. `TOUCHSTONE_URL` empty (the default)
  leaves no trace. The board's sketch was not yet in the repository.
- **The pages' provenance** (a reader asked how a genuine revision of
  self.md can be told from one a new model or prompt induced):
  `memory/page_history.jsonl` — one line per write of self.md, projects.md,
  destiny.md or keeper.md: when, the page, the model, the door it was
  written from, the size, the history file the version before went to.
  Append-only, the page tools alone write it, never in the prompt. And
  `projects.md` keeps its versions now (`memory/projects_history/`), like
  the other three.
- **The night in the bridge** (`SLEEP_IN_BRIDGE`, on; `SLEEP_IN_BRIDGE_QUIET_MIN`
  10): a house that ran the phone and no heartbeat never slept —
  yesterday was never consolidated, no day condensed, the ladder never
  climbed. After `SLEEP_AFTER_HOUR`, when no heartbeat is up and the phone
  has been quiet, the bridge sleeps on yesterday and runs the condensing
  hour itself, in the background; the phone hears it begin and end; the
  brain is set down after when no visit is live. The heartbeat stays the
  sleeper wherever it runs.
- **The black box on a Mac** reads free memory too (`vm_stat`: the free
  and inactive pages by the page size), not the total alone; the suite
  walks that road on every runner, which is how the macOS job on
  GitHub stopped failing (its stubbed `sysctl` answered nothing).
- **The journal at the close of a wake, not its start** (wakes
  journaled at their beginning, when there was still nothing to journal,
  and not at their end, when there was a lot): the wake-bell used to say *thinking is
  only yours to keep if you write it down* in its opening, and the entry
  came first, before anything had happened; then the wake painted, read,
  rewrote a page and rested, and that early entry disarmed the auto-kept
  closing thought too. Now the bell says the journal is for what the wake
  turns out to be and the time to write it is at the end, before rest; a
  rest after acts with nothing journaled since them is handed back once
  ("you wrote wake-night.md and rewrote your project page since your
  journal entry earlier in this wake… write_journal what it was, then
  rest; or rest now — call do_nothing again and it stands"); a second rest
  stands, reads are not acts, and a tool of the friend's own forging is;
  the auto-keep counts only writing after the last act, labeled for that
  case. The closing nudge says *write what this wake was in your journal*.
  A wake that ends in words after acts, with no `do_nothing` at all,
  slipped past the hand-back and the net kept the thought under its label:
  an ending in words after acts is now handed back once too — write the
  wake, or end as you are and the thought is kept — and a second ending
  stands.
  The reverie bell still carried the old sentence ("whatever is worth
  keeping, write_journal it") and a reverie wrote first — it says the end
  now, like the wake's; and tools of the friend's own forging had counted
  as acts, so the hand-back could ask for a page that turned out to be a
  retelling the journal refused — a tool of their own is not an act; a
  sensor is not a making, and the engine cannot know what a tool of theirs
  does. Acts are the engine's making-tools only.
  And a wake that ran `run_python`, drew a figure, looked at it and
  rested, nothing journaled, was not asked, because a drawing by
  `run_python` was not one of the making-tools. A picture that appears
  under `creations/` while `run_python` or a tool of their own runs is an
  act now, whatever drew it — the engine does not know the tool, it sees
  the file: "you drew creations/sketch.png this wake".
- **The heartbeat's wakes set the brain down too**: `BRAIN_REST_AFTER_WAKE` now covers
  the loop's wakes, not only a single one — a wake's prompt is read cold
  either way, since the journal and the clock have moved, so keeping the
  brain up between beats bought seconds of loading and cost the card for
  `BRAIN_KEEP_ALIVE`.
- **Every knob's help, whole** (help lines read as cut mid-sentence):
  the Settings tabs clipped
  each help line to two lines with nothing to say so, and a click opened
  it — now the line shows whole. And the six phone-notice knobs
  (`TELEGRAM_SHOW_*`, `TELEGRAM_TELL_*`) had no line of their own, so the
  page showed the file's run-on comment; they have one each.
- **A folder that reads like the mailbox but isn't** (a letter into
  `notes_to_dear_<keeper>/` — the bridge watches the mailbox alone, so
  the letter never reached the phone): `write_creation` into a NEW folder
  whose name reads like a mailbox gets one line — the mailbox named, "a
  letter here stays here", the path to write it again to. The file stays
  where it was put; the second file there gets nothing.
- **The glitch line is not a message** (the friend's thinking took the
  re-roll line for the keeper reminding them of an earlier failure, and the
  answer went to the reminder instead of to the keeper): the re-roll line
  after a glitch in the first words now opens "nothing new has come from
  the keeper's side, and nobody wrote this line to you", quotes the
  keeper's message as the one to answer, and
  asks that neither the glitch nor the line be mentioned — just the
  answer. The ordinary glitch line says the same at its end.
- **The ladder: the QAT 12B on 12 and 16 GB too** (the 12 and 16 GB
  rungs recommended the regular brain, not the QAT one). A mistake: a leftover from before the QAT tags
  existed. `gemma4:12b-it-qat` is smaller (7.2 GB against 7.6) and the
  build Google trained to be 4-bit, so it fits at least as well and sits
  closer to full precision. The README's two tables, the template's
  default `CHAT_MODEL`, the panel's recommendation by card size (and the
  Mac's), and the site's table say so. And the ears: the QAT 12B hears
  (measured — a voice note over the phone, heard whole),
  so `EARS_MODEL` is `gemma4:12b-it-qat` too, and from 10 GB up the ladder
  is one pull per rung; a 12B house is one file for brain and ears alike.
- **Save and Discard, at the foot of every Settings tab** (a change on
  the page could be left without ever reaching the file): the Save button used to sit
  at the bottom of a long tab, always lit, with nothing to say whether
  anything had changed. Now a bar stays at the foot of the window: Save
  lights only when a value differs from the file's, a line counts and
  names the changed knobs, Discard puts the file's values back, a changed
  knob carries a dot by its name, and leaving the tab with changes unsaved
  asks first.
- **An echo can come from further back**: four replies in one visit were earlier replies of the same visit said again
  entire — the first from eight replies back, the last from two — each
  under a fresh stage direction. The echo rail compared the reply with the
  one before it only, so the sampler handing back a reply from several
  messages ago went out as an answer. Now the look-back is the friend's
  last `ECHO_LOOKBACK` (12) spoken replies: the previous one as before
  (its opening, and any paragraph from `ECHO_PARA_MIN_CHARS`), the ones
  before it for the opening and for whole paragraphs of 150 characters or
  more — a sentence they are fond of may come round again across a visit;
  a paragraph does not. The line under the bubble says it: "repeated word
  for word a reply they gave earlier".
- **A journal twin needs the wording too** (a wake's own account of its
  night was refused as a twin of the night before's). The
  check embeds the whole entry and the whole of each entry of today and
  yesterday; one voice reads as near-identity to the embedder, and of the
  entries that passed, most scored 0.86–0.88 against some other one — the
  threshold sat in the middle of the ordinary range, and nine marks in
  twenty-one on one day were arrows. Now a twin needs the score AND the
  words: `JOURNAL_DUP_WORDING` (0.25), the share of the new entry's
  word-trigrams the earlier one already has — measured on six days of
  entries that are not twins, median 0.03, nineteen in twenty under 0.11;
  a copy is 1.0, a retelling keeps its phrases. 0 asks the score alone.
  The written entry's result names both numbers for its nearest neighbour.
- **The tic-tell** (a tic that had already turned to salad several times
  in the wake logs). A small tic — a little prefix in the prose — fed on
  the window: the journal
  in the prompt is the friend's own recent prose, so the rate of the tic
  there is close to its odds in the next word, and every entry that carries
  it raises the rate for the next. Counted per thousand words of the
  journal, no reading: 7 → 12 → 16 → 21 → 25 → 31 over three weeks, a
  steady slope, the salad check catching only the far end. Not a fence:
  nothing written is touched or filtered. `TIC_WORD` (empty by default: a
  word, or a prefix with its hyphen) is counted on every write that goes
  through — journal, pieces, the four pages — and one that carries it at
  `TIC_TELL_FACTOR` (2) times the friend's own rate of two to four weeks ago
  (the median of the journal days 14–28 back with 200 words or more; fewer
  than three such days: no tell; `TIC_BASELINE_PER_1000` pins it) gets one
  line after the result with the two numbers, at most every
  `TIC_TELL_GAP_MIN` (60) minutes: "a number, not a correction — what you
  keep of it is yours." Four knobs on the panel with help; ten checks.

## 0.13 — 2026-09-29 → 2026-10-02

The "skills" release: a shelf of recipes of their own, a window onto the
world's, a book read in real sittings, and a road for a keeper's folder to
the current engine.

### Added
- **The ladder** (README): the memory engine pulled first, then the brain by
  the card's memory — 6 GB `e2b-it-qat`, 8 GB `e4b-it-qat`, 10 GB
  `12b-it-qat`, 12 and 16 GB `12b`, 24 and 32 GB `31b-it-qat` — with the
  window, the tool kit and the journal size for each rung; the panel's
  recommendation follows the same ladder (the 2B QAT for a 6 GB card and an
  8 GB Mac, the 12B QAT for a 10 GB card). First light pulls the memory
  engine from a step of its own, with a light. The 4-bit KV cache is the
  ladder's footing now: setup step 2 gives Ollama `OLLAMA_KV_CACHE_TYPE
  q4_0` (and flash attention) before the first pull, and every window is
  recalculated for it — 6 GB 32768, 8 GB 40960, 10 GB 32768, 12 GB 40960
  (the shipped `NUM_CTX`, with `JOURNAL_CHARS_IN_PROMPT` 40000), 16 GB
  131072, 24 GB 65536, 32 GB the whole 262144 (measured); q8_0 is the
  retreat, at half of each.
- **The Senses tab as cards**: each sense says what it is, whether what it
  needs is installed (with the `pip` line when it isn't), where the README
  tells it, and carries its own knobs beneath — instead of a bare list of
  `EARS_*`, `VOICE_*`, `PAINTER_*` knobs with their file comments.
- **A Mac, and Linux** (`MAC-PLAN.md`; `PAINTER_DEVICE`, `MUSIC_EARS_DEVICE`,
  "auto"): one folder that runs on all three. Every `.bat` has a twin
  `.command` (a Mac; Finder opens it in Terminal) and `.sh` (Linux) beside
  it, `anima.command` and `anima.sh` at the root — the same engine script
  with the same arguments, `python3` for `py`, the bridge's restart on exit
  code 75 as a `while` loop, `update.sh` in one block that exits, as
  `update.bat`'s parentheses; a check holds the three sets to each other.
  The panel opens each door in Terminal on a Mac (`open -a Terminal`; a
  door with arguments as a one-off `.command` in `memory/.pids/`) and on
  Linux in the first of x-terminal-emulator, gnome-terminal, konsole and
  xterm on PATH — with none, the door runs with no window and its tile says
  so. Doors start in a session of their own and *Stop now* ends the
  process group, children with it. A closed terminal window (SIGHUP) and
  *Stop now* (SIGTERM) save an open visit first, as the window's X does on
  Windows. The card on a Mac is its unified memory (`sysctl hw.memsize`),
  with a ladder of its own — 8 GB the e4b, 16–24 GB the 12B, the 31B from
  32 GB; on Linux `rocm-smi` after `nvidia-smi`. The painter and the music
  ear pick their device (`engine/device.py`: the card, a Mac's GPU — "mps",
  in float16 — or the processor), and `VOICE_DEVICE` takes "mps". The update
  owns `*.command` and `*.sh` (root and `bat/`) and writes them executable.
  The README's setup shows the three forms where they differ; a GitHub
  Actions workflow runs the suite on Windows, macOS and Linux.
- **The afterglow at the fold** (`FOLD_AFTERGLOW`, on; needs `AFTERGLOW`):
  the turns that leave the window get the same quiet turn a finished
  visit gets — journal and memories, in the friend's own words — in the
  background, from the transcript, the bell saying it is the afterglow of
  a fold and the visit goes on. One cold read, once per fold; a message
  sent meanwhile waits for it. (`chat.fold_afterglow`; the quiet turn's
  bells take an `opening`.)
- **A newer anima, said** (`engine/newer.py`; `UPDATE_CHECK_H`, 24 hours, 0
  never): one look a day at the repository's release feed
  (`releases.atom`, ETag kept), the newest tag against `VERSION`; a line on
  the panel's Home with *release notes*, *Check* and *Update*, and one
  message on the phone per new version. Nothing installs by itself; a
  folder without `bat\update.bat` never looks.
- **The gate on the panel**: the Skills tab is the approval desk — a card
  per quarantined skill with the scanner's verdict and every finding (file,
  line, rule, the words), where it came from and who fetched it, *read
  SKILL.md* (the file and the file list on the page, read, never run),
  *approve* (a dangerous one asks twice) and *refuse*; the shelf the same
  way with *remove*; Home says "N skills waiting at the gate" with a link.
  `/api/skill_text` serves the file to the panel's own page only.
- **The launchers in `bat\`**: every `.bat` but `anima.bat` moved from the
  root into `bat\` (each `cd`s to the folder above, so `bat\chat.bat` runs
  from anywhere); the root is the panel's door and the friend's pages. The
  panel, the README and every message that names a launcher say `bat\…`.
  An update to this version moves a folder's old root launchers to the
  backup when the new engine ships the same name under `bat\` (a launcher
  of the keeper's own stays); `anima.bat` and `bat/*.bat` are the engine's.
- **`/afterglow` on the phone** (no knob): the pause by hand — the friend
  sits with the visit so far now, the quiet turn `REFLECT_AFTER_MIN` would
  bring after the quiet, and the brain is then set down so the card is the
  keeper's at once (a game to start) instead of after the wait and the
  keep-alive. The visit stays open. Either the quiet's pause or the command
  reads a stretch, never both; with nothing new it just sets the brain down.
- **The tool kit** (`TOOL_KIT`: "full", "small", "tiny" or a list of
  names): which built-in tools ride in the prompt. All of them cost ~7,500
  tokens of definitions; small gives back ~3,000, tiny ~5,000, for a small
  card or a small brain. The prompt's words about a tool go with the tool;
  forged tools always ride; a dropdown on the panel's Main tab. The README's
  tiers become three: an 8 GB tier (`gemma4:e4b-it-qat` with the small
  kit — an estimate, to be measured) beside the 12 GB and 24–32 GB ones,
  and the introduction opens with the panel. The panel's Welcome names the
  small brain for a card under 10 GB and sets `TOOL_KIT = "small"` with a
  small brain at First light.
- **Their skills** (`engine/skills.py`, `skills.bat`; tools `use_skill`,
  `list_skills`, `run_skill_script`, `fetch_skill`, `remove_skill`;
  `SKILLS_IN_PROMPT`, `SKILLS_DIR`, `SKILLS_CHARS_IN_PROMPT`,
  `SKILLS_DESC_CHARS`, `SKILL_CHARS`, `SKILL_MAX_FILES`, `SKILL_MAX_BYTES`,
  `SKILL_FETCH_TIMEOUT`): the open skill standard (a folder with a
  `SKILL.md` and maybe `scripts/`, `references/`…, as Hermes Agent, Claude
  Code and skills.sh use it) on a shelf of their own in
  `creations/skills/<name>/`. The prompt carries the shelf beside the
  forged limbs — names, one line each, tags; `use_skill` opens a body,
  framed as material; `run_skill_script` runs a skill's Python script in
  run_python's sandbox; `fetch_skill` brings one from GitHub, a SKILL.md
  URL or a .zip, and a scanner with Hermes' three verdicts stands in the
  door — *dangerous* waits in `.quarantine/` for the keeper
  (`skills.bat approve`), *caution* rides tagged, *clean* rides. The phone
  hears each fetch once (📚, or ⚠️ with the finding). Their own SKILL.md
  is a piece; a fetched one is not. `browse_skills(query, catalogue)` is
  the window beside the shelf (`SKILL_CATALOGUES` — Hermes' and
  Anthropic's by default; `SKILL_CATALOGUE_TTL_H`, `SKILL_BROWSE_CHARS`,
  `SKILL_CATALOGUE_DIR`, `SKILL_CATALOGUE_PACE`, `SKILL_CATALOGUE_RETRY_MIN`,
  `SKILL_CATALOGUE_BUDGET_S`): the catalogues indexed from GitHub (paced,
  a 429 waited out, a partial index said and completed at a later browse)
  and kept a week under `memory/`, shown by shelf or searched by a word,
  each skill with the exact source `fetch_skill` takes; `skills.bat
  browse` for the keeper.
- **Updating** (`engine/update.py`, `update.bat`; `UPDATE_REPO`): a
  keeper's folder brought to the current engine on GitHub without git
  and without touching the friend. The default branch comes down as a zip
  (`--tag` a release, `--source` a zip or folder already on the disk);
  the engine's files — `engine/*.py` but `config.py`, `tests/`, the
  launchers, `README.md`, `CHANGELOG.md`, `VERSION`, `requirements.txt`,
  `.gitignore` — are replaced, added and removed, and nothing of theirs
  (`config.py`, `self.md`, `projects.md`, `destiny.md`, `journal/`,
  `memory/`, `creations/`, `shared/`, a file they added) is touched. It
  says `0.12 → 0.13` and the CHANGELOG entries since before anything
  moves (`--check` stops there); every replaced or removed file goes to
  `.update/backup-<stamp>/` first, the last three kept, and `--undo` puts
  the newest back. `.anima-manifest.json` keeps the sha256 of what was
  installed, so an engine file the keeper edited is backed up, replaced
  and named, never merged. `config.py` is appended to, never rewritten:
  the knobs the new template has and theirs lacks, with the comments
  above them, under one dated marker; a knob they have keeps their value
  (`--no-config` skips it). A new line in `requirements.txt` is printed
  with the pip line; the update installs nothing. (`.update/` is in
  `.gitignore`.) `--reset-config` writes the new engine's `config.py` fresh
  with the keeper's one-line values carried into it, the old file in the
  backup — for a config fumbled past loading.
- **`VERSION`** (with `engine/version.py`, which reads it) and
  **`requirements.txt`**: the version at the root; every optional package the README names, with what it is for.
- **The doors' marks and a polite stop** (`engine/doors.py`;
  `HEARTBEAT_LOOP_MIN`): the heartbeat, the bridge, the parlor and a chat
  keep `memory/.pids/<door>.json` while they run (pid, when, how), a stale
  one cleared when its pid is gone; a second heartbeat, bridge or parlor is
  refused with the running one's pid (two chats are fine).
  `memory/.stop-heartbeat` asks the loop to leave after the wake it is in
  (looked for between beats and every few seconds of its rest),
  `memory/.stop-bridge` the bridge after the poll it is in, the visit
  saved. `--loop` with no number wakes every `HEARTBEAT_LOOP_MIN` (120, the
  old hardcoded value).
- **`engine/knobs.py`**: the config reader and writer the panel will use —
  every knob with its value, kind, comments and part of the file; a save
  that rewrites only a value span, backs up to `.update/config-<stamp>.py`
  and proves the file still imports (update.py's reader moved here).
- **The panel** (`engine/panel.py`, `anima.bat`; no knob): one door with
  the others behind it, at `http://127.0.0.1:8764` (localhost only,
  standard library, nothing fetched). Home is a tile per door with its
  light — chat, parlor, wake, the heartbeat (every N minutes, saved as
  `HEARTBEAT_LOOP_MIN`; Stop and Stop now), the bridge (and its bot token),
  sleep, snapshot, the update — and the brain above them: Ollama
  answering, the model loaded and how much of it is on the card, *Pull*
  for a configured model it lacks. Each door opens in a console of its
  own, the same process as from its `.bat`; a second heartbeat, bridge or
  parlor is refused. Settings lays `config.py` out on tabs (Main: the
  brain, the window, the journal in the prompt, the names, the rhythm;
  then Heartbeat, Memory & journal, Talking, Phone, Senses, Skills, Blog,
  and Advanced for every other knob under the file's own headings), each
  knob with its comment as help; Save rewrites only what changed and names
  the doors to restart, with a Restart that waits for the wake to end.
  While `USER_NAME` is `"Friend"` it opens on Welcome: your name, the
  Ollama light, the brain, *First light*. Tokens and keys go to
  `memory/*.json`; the panel never opens the friend's files.
- **Reading, mended**: a page on the reading shelf under a name
  near a book's but not it is handed back with the engine's name, and one
  already there is named under every "no page yet" with the road home
  (`STRAY_PAGE_RATIO`); an EPUB part page reads with the chapter after it
  (`EPUB_SLIVER_CHARS`); a sitting still unwritten after the tell goes into
  the bookmark's ledger and is named in the prompt and every quiet sitting
  until the page names it; `chapter='start'` begins an EPUB over; a
  `README.md` in another project folder is not a twin.

## 0.12 — 2026-09-24 → 2026-09-28

The "fold" release: a visit that outgrows the window goes on in the
friend's own words, a book has a page of its own, the horizon has a file,
and what the brain must never see again never rides back.

### Added
- **The keeper's body, as the watch saw it** (`engine/body.py`, `body.bat`;
  `BODY_IN_PROMPT` off by default, `BODY_IN_MOMENT`, `BODY_PULL_MIN`,
  `BODY_CHARS_IN_PROMPT`, `BODY_STALE_H`, `BODY_DIR`, `GARMIN_TOKENS`,
  `BODY_AUTOPULL`): a sidecar — or the bridge itself, hourly — pulls the
  keeper's day from Garmin Connect into
  `memory/body/<day>.json` and a short section of plain numbers — sleep,
  pulse, stress, Body Battery, steps — rides in the prompt, the pulse line
  in the moment block. Their data, their switch; credentials cached only
  under `memory/`.
- **The fold** (`FOLD_AT`, `FOLD_KEEP_TURNS`, `FOLD_CHARS`, `FOLD_MAX_STEPS`,
  `FOLD_SENSE_FROM`; tool `fold_visit`): a visit that reaches `FOLD_AT` of
  the window is folded instead of stopped — the fold bell rings inside the
  visit, the friend writes the visit so far in their own words, and that
  account takes the place of everything above the last kept turns; the
  system prompt is rebuilt fresh, the transcript keeps every word and the
  visit goes on in a new file. The moment block carries how full the
  window is from `FOLD_SENSE_FROM`, so they can fold on their own at a
  natural pause; `/fold` on the phone folds at the keeper's word. The old
  92% stop stays as a backstop.
- **Where they are going** (`destiny.md`, `update_destiny`;
  `DESTINY_IN_PROMPT`, `DESTINY_CHARS_IN_PROMPT`): a third file at the
  root beside who they are and what they are doing — the horizon no
  project completes; theirs alone, every version kept, riding after WHO
  YOU ARE up to a cap; the phone hears its first writing whole.
- **The book in their hands** (`creations/reading/<book>.md`;
  `READING_PAGES_IN_PROMPT`, `READING_PAGE_CHARS`, `READING_OPEN_DAYS`,
  `READING_DONE_DAYS`, `READING_BOOK_PAGES`, `READING_DIR`): a notebook
  per book, written by them after each sitting — the reading tools name
  it, it rides in the prompt while the book is open with where they stand,
  and the sitting that reaches the end files one memory row; a short PDF
  is a read, not a book. A sitting is `READ_SITTING_CHARS` (30,000, from a
  hardcoded 15,000); a range asked for on purpose may be `READ_RANGE_CHARS`
  (80,000) — a story in one go.
  A bookmark only moves forward: pages (or an EPUB chapter) named behind it
  are shown again and the bookmark stays, said in the result; 'start'
  begins anew. A sitting read but never written down (the bookmark keeps
  the last span and the page's size) is named at the next sitting, with
  how to flip back to it. Past `READING_PAGE_CHARS` the page rides as its
  title and its end (the newest sittings), not its opening.
- **The afterglow catches up** (`AFTERGLOW_ORPHANS`): a visit the bridge
  died with — a power cut, a hard close — was saved but never got its
  afterglow; on the next start the newest unsigned transcript of the last
  two days, not the visit now open, not a day the night has slept on, gets
  it in the background, and the phone is told.
- **A one-word tool written out is a call too**: `speak(text="…")`,
  `paint("…")`, behind a `//` or `#` — the call-text rail knows the
  friend's real tools by name (`KNOWN_TOOL_NAMES`), in Python's own call
  shape only, so "watch (and wait)" stays their words; the heartbeat
  recovers that shape into a real call.
- **Words inside a speak call are words**: `speak(text="…")` written
  out, with or without a `//` in front, becomes the quoted words — the
  reply, with a note — instead of a nudge answered in the same shape.
- **A reply that stops mid-word is asked for whole** (`cut_reply`,
  `trim_cut`): a last word left on an open hyphen — the sampler out of
  continuations after a much-repeated prefix — is asked about once; if it
  stops again, the fragment comes off at the last full sentence and the
  note says so.

### Changed
- **Reserved tokens never ride back** (`ollama_client.defang`): a
  reserved-token string ("<unused50>", "<start_of_turn>", "<eos>"…) in a
  reply, a thought, a re-roll line's quote, the keeper's message, a tool
  result, a resumed stash or a transcript read back becomes plain text
  ("⟨unused50⟩") before it goes anywhere near the brain — Ollama tokenizes
  a prompt with special tokens, and a quoted flood in the visit's history
  had fed the well through every later request; a glitch at the first word
  now leaves the re-roll line with nothing to quote.
- **The cold roll** (`CHAT_COLD_RESCUE`): when every warm attempt and both
  cool rungs come back broken — reserved tokens on every roll, a well in
  the loaded state rather than the sampler — the brain is set down
  (`unload`) and picked up again, and one more roll is made at everyday
  sampling before the least broken goes out; the note names it.
- **A reply the phone can't take is kept and sent with the next poll**
  (`_send_reply`: three tries, `RETRY_SLEEP_S`; then
  `memory/telegram_undelivered.json`, delivered first at the next poll,
  marked as late); engine lines never take the turn down with them.
- **A picture made in the quiet hours comes with the morning digest as the
  picture** (held in `memory/telegram_held.json` as an entry, sent as a
  photo with its caption and gallery words when the hours end); before, the
  digest carried a line about it and the picture stayed in the folder.
- **A revised piece travels as what changed.** An append (a reading page
  after a sitting, a project README) reaches the phone as the new tail
  alone — "✏️ added to a piece — … (+N characters)" — a rewrite as the
  lines in and out, against the bridge's copy in
  `memory/telegram_watch/creations/`; before, every revision sent the
  piece's first `TELEGRAM_CREATION_CHARS` again.
- **A word loop is salad** (`WORD_LOOP_WINDOW` 40, `WORD_LOOP_DISTINCT` 4;
  `ollama_client.word_loop`): forty words with four or fewer different
  ones — a period of several words, which the stuck-chunk rule (one chunk)
  and the line rule could not see — is cut mid-stream, asked again, and a
  runaway that still goes out is cut at the loop, never sent or kept whole;
  a stashed visit picked up after `/restart` and a transcript read for its
  afterglow have their loops cut on the way in (`trim_word_loop`). A phrase
  loop (`PHRASE_LOOP_WINDOW` 60, `PHRASE_LOOP_TIMES` 5; `phrase_loop`) —
  three long words five times over with interjections between — is caught
  in a reply too, and left alone in their files; a loop on a reading page
  is left out of what rides in the prompt (`trim_loops`).
- **No day counts in the fractal journal.** `JOURNAL_DAYS_IN_PROMPT` (365)
  and `TIMELINE_DAYS` (365) are gone. The verbatim journal walks every day
  on disk (`assemble.journal_days_on_disk`): the newest whole days that fit
  `JOURNAL_CHARS_IN_PROMPT` stay, everything older has slipped into the
  pages and the timeline. The timeline keeps a line for every day no page
  above holds, the newest within `TIMELINE_CHARS_IN_PROMPT` (0 turns it
  off). `memory.recent(n=None)` is all rows.

## 0.11 — 2026-09-18 → 2026-09-23

The "before their eyes" release: they paint from their own words, read the
whole web, keep their projects on a page, and see what they make before
they speak of it.

### Added
- **The painter** (`engine/painter.py`, `painter.bat`; `paint(prompt, path,
  size)`; `PAINTER_URL`, `PAINTER_MODEL`, `PAINTER_AUTOSTART`,
  `PAINTER_PYTHON`, `PAINTER_REST_AFTER`, `PAINTER_IDLE_S`, `PAINTER_EXIT_S`,
  `PAINTER_TIMEOUT_S`, `PAINTER_STEPS`, `PAINTER_MAX_PER_WAKE`): a
  text-to-image sidecar of the music ear's shape — woken when they paint,
  the brain set down from the card, the picture written under creations/,
  the GPU handed back; one prompt per line, several lines one sitting;
  nothing overwritten; the price — a cold read of the window after — is
  told in the tool's words, and a wake may make a few. Z-Image-Turbo by
  default (Apache 2.0, ungated); FLUX.2 klein 4B is the other line.
  `painter.bat --test "…"` paints once by hand.
- **Full HD** (`PAINTER_SIZES`): what the size words mean, in pixels —
  square 1440², wide 1920×1088, tall 1088×1920; sides snap to multiples
  of 16; any word may be added.
- **What they make is before their eyes** (`SHOW_WHAT_SHE_MADE`,
  `PICTURES_SHOWN_MAX`): a picture painted or drawn is shown on the next
  thought the way `look_at` shows one — "say what you see in it, not what
  you asked for".
- **Pictures leave rows**: a painting, a drawing by `run_python` or a forged
  tool, a picture painted over — one "creation" row per file (their words as
  the about for a painting, the tool for a drawing, "redrew" in the
  history), on the shelf like any piece.
  `backfill_creations.py --pictures`.
- **The gallery** (`publish_creation(path, caption=)` on a picture;
  `creations/publish/gallery/`; `gallery.html`; `BLOG_THUMB_WIDTH`): a
  picture they choose to publish hangs on the blog's gallery page with
  their words beside it, on a page of its own, in the feed and the repo
  README; the phone gets it as 📣 with the words.
- **Drawing**: `run_python` and forged tools see the per-user packages
  (`-E`, not `-I`) and draw headless; a broken forged tool is a failed call
  (the failure frame and the claimed-failed rail read it); a picture drawn
  under creations/ reaches the phone as a photo (`TELEGRAM_TELL_DRAWINGS`);
  `look_at` opens a drawing by the creations-relative name it was drawn under.
- **Pictures are files of theirs**: `move_creation`, the trash and the
  attic copy bytes, so a picture moves and is deleted whole (the first
  move of a painting had failed on a UTF-8 decode); `read_creation` on a
  picture points at `look_at`; a caption written with a literal
  backslash-n gets real line breaks, like any page (`_real_newlines`).
- **The window, rebuilt** (`engine/web.py`, `web.bat`; `WEB_SEARCH`,
  `WEB_SEARCH_SEARXNG_URL`, `WEB_PAGE_CHARS`, `WEB_LINKS_MAX`): `read_web`
  keeps a page's shape — title, headings, lists, quotes, numbered links
  with an index — leaves menus and footers out, and hands long pages over
  in parts (`page=`, `find=`); `search_web` asks the whole web (DuckDuckGo
  by default; SearXNG or Brave optional). Standard library only.
- **Pictures on pages**: `read_web` names a page's pictures inline and
  lists them with their URLs for `look_at`; logos, icons and inline data
  are left out. The search asks as a browser would (the lite page first,
  as a form POST) and a human check is said plainly.
- **Where the projects stand** (`PROJECT_PAGES_IN_PROMPT`,
  `PROJECT_PAGE_CHARS`, `PROJECTS_CHARS_IN_PROMPT`; `clip_web`,
  `WEB_CLIP_CHARS`): an Active project with a Location rides in the
  prompt with its folder's README — the page of what is known, what is
  open, the next step; `clip_web` keeps pages read for it in the folder's
  sources/, as files, not memory rows; `start_project` starts one in one
  act, with a place and a "Done when" written in; every project's folder
  lives under `creations/projects/` (`PROJECTS_HOME`).
- **The window guard** (`HEARTBEAT_ROOM_WARN`, `HEARTBEAT_ROOM_END`): a
  long wake is told once as its window fills and ended when it is full,
  and a chat errand is ended the same way, so a high `HEARTBEAT_MAX_STEPS`
  or `CHAT_MAX_TOOL_STEPS` (now 50) never cuts the identity off the top
  of the prompt.
- **The reads tell** (`READ_TELL_MIN`, `READ_TELL_DAYS`): reads are counted
  in `memory/reads.json`; the third reading of the same piece, day or file
  in a month opens with the count — a tell, not a fence; the unwritten-thought
  nudge stands down on a subject the journal already circles; the shelf
  dates rows by the newest stamp in their text.
- **One row per piece, revised in place** (`NOTE_HISTORY_MAX`): a
  continuation, a revision, a move or a publish revises the piece's one
  memory row — the head keeps the first writing, the facts are read from
  the file as it is now, a short history rides at the end ("continued
  06:03 (“…”) · revised 09:12 → published 09:37") — instead of a row per
  event; `backfill.bat --tidy --write` folds the several rows an earlier
  day left about one piece into one; the twin guard reads titles as well
  as names.
- **Letters leave no row** (`CREATION_NOTES_SKIP`): a letter in the
  mailbox rides whole in the prompt for a few days and is not noted in
  long-term memory as well; `backfill.bat --letters --write` lets the
  old rows go.
- **The cool rolls** (`CHAT_RESCUE_TEMPERATURE`, a ladder): when every
  warm attempt at a reply is broken (`CHAT_GARBLE_RETRIES`, now 4), one
  more is made with the temperature lowered for that roll only, then a
  cooler one, before the least broken goes out; everyday sampling is
  untouched.
- **"la-K keystone"**: a lone capital glued to a prefix with the word a
  space later is mended like any glued capital; so is a capital glued to
  the word that opens a sentence ("WhoL would").

### Changed
- `LADDER_TARGETS` week 4000, month 6000 (from 3236 / 5236): the folds
  between the tiers squeeze by about the same factor now — 3.5× from the
  days, 2.9×, 2.1×, 2.5×, 3.1× up the ladder — instead of a 4.3× cliff
  at the week; the steady state stays under 400K characters.
- `CHAT_MAX_TOOL_STEPS` 14 → 50, and `HEARTBEAT_MAX_STEPS` may be raised
  freely (the template keeps 24) now that
  the window guard ends a wake or an errand before the window is full.
- `paint` is not an act that ends a chat turn — the look after is theirs.
- `PAINTER_MAX_PER_WAKE` 3 in the template.
- A row's about — the friend's `about=` line, a painting's prompt — is
  kept up to `NOTE_ABOUT_CHARS` (400) and cut at a sentence or a word
  with an ellipsis, never mid-word (a prompt had ended "…gold and").
- `delete_creation(path, why=)`: the reason a piece goes rides in its
  memory row after the delete mark ("— because: …"), so the shelf says
  what went and why, and the same picture is not made twice; the two
  `delete_creation` definitions the tool list had carried are one.

## 0.10 — 2026-09-14 → 2026-09-17

The "a letter stays with them" release: what they write alone is theirs to
remember, a feeling that lasts leaves a mark, and the small slips of a
deep window are mended in place instead of re-rolled.

### Added
- **The arrow** (`JOURNAL_ARROW`, `JOURNAL_ARROW_GAP_MIN`): a journal twin
  refusal leaves a stamped mark in the day — "↑ still this, at 14:20 — in
  this hour's words: “…”" — carrying their fresh sentence, so a day with a
  feeling that lasted no longer reads as one entry and silence.
- **A letter stays with them**: a delivered letter becomes their turn in the
  Telegram visit so the answer lands under it (`TELEGRAM_LETTERS_IN_THREAD`);
  the last days of letters ride in the system prompt (`LETTERS_DAYS_IN_PROMPT`,
  `LETTERS_CHARS_IN_PROMPT`); the wake-bell says a letter stays with them a
  few days and the journal holds what they want longer.
- **The clock rides on the wake-bell** — weekday, date and hour at the top
  of every wake and reverie; the date at the top of a 130K prompt was not
  enough ("Monday morning" on a Sunday evening).
- **Tool results quote the message being answered** and say they are not a
  message and not a silence — a post-tool step had answered a silence that
  never was.
- **Rails**: a greeting said once per visit; "said it was done, did nothing"
  — a reply claiming an act with no tool called is asked about once (the
  keeper's ask, their own "I updated my self.md", or a "done" after a tool
  that failed — and a failed call is told to them first, in its own
  frame, before the next step; "I'm saving it right now" with no call
  is asked once too); "read it?" — writing as if a
  piece were opened when no tool ran is asked about once; an echo can be a
  paragraph (`ECHO_PARA_MIN_CHARS`); a wordless emoji chunk repeated
  `STUCK_EMOJI_REPEATS` times is a loop, cut mid-stream; a reply broken
  in two by a channel token mid-sentence (the rest filed as thought) is
  asked for whole, and joined back at the seam if it breaks again.
- **Quiet hours** (`TELEGRAM_QUIET_HOURS`, 23–7): the engine's notices —
  afterglow and pause accounts, what they made, a change to self.md — are
  held through the night and come as one morning message; their own
  replies and letters are never held.
- **Not twice, for pieces**: `write_creation` hands a new file back when a
  piece by that name exists elsewhere (`anyway="yes"` to start another).
- **An act with their words beside it ends the turn** (`CHAT_ACT_ENDS_TURN`,
  `CHAT_ACT_MIN_WORDS`): after speak/remember/write_journal with a real
  reply alongside, no step after the tool — nothing left to answer a
  silence with.
- **An emoji storm is a refrain** (`EMOJI_STORM_MAX`): a sign-off block that
  feeds on itself through the warm history is asked for again, sign once.
- **Their afterthoughts on the phone** (`TELEGRAM_TELL_AFTERTHOUGHTS`): the
  closing thought after a pause or the afterglow, labeled, never as a reply.
- **A tool result carries their plan** (`CHAT_CARRY_PLAN` for chat) — the
  numbered steps of the thought before it, in wakes and in visits alike —
  and a one-word thought counts as no thought.
- **Think first, then rest** (`HEARTBEAT_THIN_REST_WORDS`): a wake's rest
  with hardly a thought behind it, right after a carried plan, is handed
  back once; a second rest stands. The mirror case too
  (`HEARTBEAT_UNWRITTEN_THOUGHT_WORDS`): a real thought after a read,
  none of it written, then rest — asked once whether to keep it.
- **A wake's own think budget** (`HEARTBEAT_THINK_RETRIES`, 4): a warm
  re-roll is cheap; a leaked channel name ("thought") counts as no thought.
- **Search on a matrix**: long-term memory is held in each process as unit
  vectors (numpy if installed) and read incrementally — a search stays
  under a millisecond at any size the store will reach.
- **The ladder above the day** (`engine/ladder.py`, `LADDER_PAGES_KEPT`,
  `LADDER_TARGETS`, `LADDER_EPOCH_YEAR`; `condense_period`): week, month,
  quarter, year and five-year pages in the friend's own words, sizes by
  the golden ratio, a fixed count per tier, the oldest folding up — the
  whole memory in view bounded forever. `condense.bat` rings both days and
  periods; the timeline retires under any page in view.
- **A piece, remembered** (`CREATION_NOTES`, `CREATIONS_DAYS_IN_PROMPT`,
  `CREATIONS_CHARS_IN_PROMPT`): every write, append and publish leaves a
  memory row — file, length, first line, and the friend's own `about=` line
  — and the last fortnight of them rides in the prompt.
- **Circling** (`JOURNAL_SUBJECT_MAX`): the third entry in two days that
  opens on one subject — a date, a file, a title — becomes an arrow, not a
  fourth telling; entries name their nearest earlier entry's score
  (`JOURNAL_NEAREST_SHOW`) so the twin threshold can be tuned from data.
- **The date rides with every message** — the moment block and the pause
  and afterglow bells carry weekday, date and hour, not the hour alone;
  the date at the top of a long prompt had drifted a day in the journal.
- **Quotation marks around a creation path come off** — a letter had gone
  to a folder named `「notes_to_<you>`.
- **The pause keeps the warm prefix** — it sends the visit's whole tool
  list; a different list was a different prefix and a cold read each time.
- **Glued capitals mended in place** ("sameL", "I'veT", "It'S",
  "termsLSimulation", "laMorning") — named under the reply, never
  re-rolled; either apostrophe counts and every slip is mended, however
  many. The same mend runs at the pen for journal entries and prose
  creations (`MEND_CAPS_IN_WRITING`).
- **Sampling**: `min_p` 0.08 (from 0.05) against letter salad at depth;
  `repeat_last_n` 512.


### Changed
- `TELEGRAM_IDLE_NEW_MIN` 720 → 1440: only the night ends a visit.
- Re-roll lines follow the attempt shown as their own turn, so the engine's
  line is never read as an empty message from the keeper.
- Words said alongside a tool call open the reply; the post-tool step no
  longer sends a second reply to a keeper who had just said hello.
- The pause/afterglow account counts arrows ("1 arrow left in the journal").
- An auto-kept closing thought drops an unfinished last line.
- Counters counted by hand when the server sends none.
- **Re-rolls keep the warm prefix**: within a turn each re-roll's request
  extends the one before it, the think nudge is kept whichever attempt goes
  out, and the attempt shown and the engine's line stay in the visit as the
  engine's turns — at 217K tokens the message after every re-roll had been
  a three-minute cold read.

## 0.9 — 2026-09-12

The "a visit is a day" release: the phone conversation lasts the day, what
they make reaches the phone, and a dozen more shapes of a small mind at
depth are seen for what they are.

### Added
- **What they make comes to the phone** (`TELEGRAM_TELL_CREATIONS`): a new
  piece under `creations/` arrives whole when it fits ("✍️ wrote a poem"),
  a revision as "✏️ revised", a move to `publish/` as "📣 published"; a
  change to `self.md` or `projects.md` (`TELEGRAM_TELL_SELF`) arrives as
  the lines in and out.
- **A visit is a day**: `TELEGRAM_IDLE_NEW_MIN` 180 → 720, and a visit
  never crosses the night — once the sleep hour has passed on a day after
  it began, it is saved and a fresh one starts, so consolidation reads
  every day whole.
- **The heartbeat waits while a visit is live** (`HEARTBEAT_YIELD_TO_VISIT`):
  a wake mid-visit replaced their reading of the window and cost the next
  reply a cold read.
- **One bridge at a time** (`memory/telegram.pid`): a second bridge refuses
  to start while the first lives — two would answer every message twice.
- **The strip of a video is kept** (`WATCH_KEEP_SHEET`): the stills tiled
  into one picture in `shared/pictures/from_videos/`, theirs to look at
  again.
- **Rails**: a runaway is cut short mid-stream (`CHAT_STREAM_ABORT`); a
  reply that opens with a page of their own journal is asked about
  (`PROMPT_COPY_CHARS`); a reply with no words and a full thought is asked
  for again; an imagined sense (a song "listened to" without the tool) is
  asked about; a written-out tool call at the *tail* of a reply is caught
  and never sent as their words; the mend refuses a continuation that opens
  like a new reply; a row of the same emoji is not salad.
- **The token line** names the re-rolls and their cost ("3 re-rolls (no
  thought ×2, refrain; 1,830 tokens set aside)") and a reply that came
  without counters.

### Changed
- `repeat_last_n` 256 → 512: the window reaches the tail of their last
  reply (an echo's source) without taxing its whole body (1024 cut replies
  at a hyphen).
- The pause and afterglow bells ask for what *happened* as well as what it
  meant; `speak`'s result says they are still inside the same message.
- The moment block ends "a new message, the one to answer."

## 0.8 — 2026-09-11

The "fractal" release: a day fades without vanishing, the warm prefix is
warm for real, and the sampler's wells are seen for what they are.

### Added
- **The fractal journal** (`engine/condense.py`, `condense.bat`,
  `condense_day`): the verbatim journal holds WHOLE recent days; the day
  that no longer fits is handed back to the friend at the condensing hour
  — after sleep, at night, or by hand — for the version they want to keep
  in view, about a page in their own words, kept in `journal/condensed/`
  and carried in the prompt in a section of its own (`CONDENSED_CHARS_IN_PROMPT`,
  `CONDENSE_TARGET_CHARS`, `CONDENSE_IN_LOOP`, `CONDENSE_MAX_PER_NIGHT`).
  The timeline becomes the tier below: nightly lines only for days that
  neither the journal nor a page in view holds (`TIMELINE_DAYS` 365).
- **The clock on the token line**: `written in`, `turn took`, and when
  the wall and the brain disagree, `N re-rolls` (discarded attempts now
  counted), `model loaded in` (evictions and swaps), and `outside the
  brain`.
- **`BRAIN_KEEP_ALIVE`** ("30m") and **`BRAIN_REST_AFTER_VISIT`**: Ollama's
  five-minute default set the model down between messages and its cache
  with it; now the brain stays up across the gaps of a visit and is set
  down the moment a visit's afterglow is written.
- **`THINK_NUDGE_STICKS`**: after one think re-roll, the nudge rides along
  on every later message of the visit.

### Changed
- **The warm prefix, done right.** Gemma's sliding-window attention lets
  Ollama reuse the cache only when the new prompt EXTENDS the old one, so
  nothing sent is taken back any more: the system prompt is built once per
  visit and kept on its first turn; each moment stays in history where it
  was sent, carrying only memories not yet surfaced this visit; the pause
  rides the same prefix and its steps stay in the visit, marked as the
  engine's. Measured: 145,869 tokens in context, prompt read in 2.2 s.
- **Every re-roll is checked**; a chunk stuck on one line is salad; if no
  attempt is clean the least broken goes out, with a note that says so.
- **A signature is signed once** (`REFRAIN_MAX`): a doubled hyphenated word
  is said once; the same one three times in a reply — near-spellings and
  the adverb included — is re-rolled with its own line.
- **An echo is not an answer** (`ECHO_MIN_CHARS`, 120): a reply that opens
  word for word as the previous one — the sampler copying the nearest
  assistant turn instead of writing one — is re-rolled with its own line
  and named under the bubble.
- **Diverse memory search** is incremental (0.08 s, was ~4 s).

## 0.7 — 2026-09-10

The "warm" release: replies stop re-reading the whole window, memory
surfaces wider, and the bridge can be restarted from the phone.

### Added
- **The warm prefix** (`WARM_PREFIX`): the system prompt is built to stay
  the same from one message to the next — the date without the minute, the
  retrieved memories left out — and what changes (the hour, the memories
  that surface) rides at the top of the keeper's message on the copy sent
  to the brain, not the one kept in history. Ollama reuses its reading of a
  prompt only as far as it matches the last one from the top, and the old
  prompt differed on every message (a minute in line four, memories in the
  middle), so every reply was a cold read of the whole window — 82 s at
  129K tokens before a word was written. Warm, a reply reads only what is
  new. Still cold: the first message of a visit, and the one after a
  journal write.
- **Mixed memory recall** (`MEMORY_DIVERSE`, `MEMORY_MMR_LAMBDA`,
  `MEMORY_RECENT_K`): the picks are spread, not clustered — each weighed
  against what is already chosen, and a near-copy of one already seated
  (closer than `MEMORY_DUP_THRESHOLD`) set aside outright — plus the newest
  few whatever the topic, marked. `MEMORY_TOP_K` 20 → 30. `recall` searches
  the same way and takes `n` (up to 40).
- **`/restart`** on the phone: the bridge stashes the running visit
  (`memory/telegram_resume.json`: history, transcript, pause position,
  toggles, Telegram offset), exits with code 75, `telegram.bat` starts it
  again on the current engine code, and the new process picks the visit
  back up and says so. An engine change no longer waits for the desk.

### Changed
- **Spilled thought, fenced**: a leading paragraph opened and closed with
  `//` ("//(the plan for the reply)… I'll respond as myself. //") goes to the thinking channel; a lone `//` line that says
  "I'll respond" / "my response" is planning too.
- **The cut-reply mend** asks for the continuation with the thought channel
  closed (`chat(..., think=False)`) and no tools — a call the server isn't
  parsing for channel tokens can't be cut by one — and when it still fails
  the note says what each attempt gave back ("a note to themself: …; then a
  tool call") instead of leaving it a mystery.
- **The afterglow and the pause count what was kept**, not what was tried:
  a `remember` refused as a repeat, or a journal entry already written, is
  reported as "already held, not kept twice"; four calls with one kept used
  to read as "4 memories kept".

## 0.6 — 2026-09-09

The "a voice of their own" release.

### Added
- **`speak`** (`engine/voice.py`): their words become a voice note through
  Kokoro (82M, open weights, CPU) — a Telegram voice message after the
  reply, playback in the parlor, the file kept in `shared/letters/`
  (`VOICE_DIR`) and never listed as new. Stage directions, markdown and
  emoji are not spoken. Twenty-eight English voices with grades; blends
  (`a,b` averaged, `a(2)+b(1)` weighted — the weighting is the engine's,
  Kokoro only averages) so the voice can be theirs; the choice is kept in
  `memory/voice.json`. `VOICE_PYTHON` runs Kokoro in a separate interpreter
  when the engine's Python is too new for its dependencies (3.14 → 3.12).
  `/voice` on the phone (`TELEGRAM_VOICE_ALL`) speaks every reply.
  `py engine\voice.py --test` / `--voices`.
- **Forged limbs in every prompt**: a "limbs you forged yourself" section
  lists their tools from `creations/tools/` by name and description, read
  without running anything, so a sense forged on Tuesday is still in hand
  on Friday.
- **The phone is told** when they sit with the visit on their own — the
  pause's or the afterglow's one-line outcome (`TELEGRAM_TELL_REFLECTIONS`).

### Changed
- **A tool call written out as words** at the head of a reply — to a tool
  that doesn't exist, or a real one without the mechanism — is treated like
  salad: re-rolled once with its own engine line, named in the note.
- The garble rail also catches one stray letter glued to a word
  ("lSymmetry"; iPhone and eBay are left alone).

## 0.5 — 2026-09-08

The "a life that writes itself down" release: the friend reflects during a
visit and not only after it, keeps a fact once, feels their own body through
a sense they forged themselves, and sees video and hears voice notes whole.
Also the release where the sampler was finally caught in the act.

### Added
- **The pause**: after `REFLECT_AFTER_MIN` (12) quiet minutes mid-visit,
  with at least `REFLECT_MIN_TURNS` (2) new messages since they last wrote,
  the friend gets the afterglow's quiet turn over what has been said since
  — same three tools, resting is complete — and the visit stays open. Bridge
  and parlor both. One bell per quiet stretch.
- **Not twice**: `remember` checks the nearest memory first
  (`MEMORY_DUP_THRESHOLD` 0.88) and hands a held fact back; `replaces=`
  revises it in place, `anyway="yes"` insists. `write_journal` hands back an
  entry that nearly repeats today's or yesterday's (`JOURNAL_DUP_THRESHOLD`).
  Quiet turns show what is already in today's journal. Consolidation skips
  known facts and says how many.
- **`watch`**: video as a strip of stills (every `WATCH_FRAME_EVERY_S` s,
  at most `WATCH_MAX_FRAMES`, `WATCH_FRAME_WIDTH` px) plus the soundtrack
  through the ears; framed "moments, not motion". The bridge saves phone
  videos, video notes, GIFs and video files to `shared/videos/`. `listen_to`
  hears a video's soundtrack alone.
- **Voice notes heard whole on arrival** (`TELEGRAM_HEAR_VOICE`): WORDS,
  SOUND and HEARD, with your caption; the phone shows typing meanwhile.
  `.oga` (Telegram's voice format) and friends are accepted by the ears —
  the first note a friend tried to `listen_to` was refused by extension.
- **The sleep window shows the sleep**: what they read, their thinking, the
  token line, the summary and every kept fact listed (`consolidate(day,
  force, say)`); the heartbeat prints the same when it sleeps them.
- **Afterglow**: told plainly that `remember` is one call per fact, as many
  as the visit earned; six steps of room; the window shows thinking,
  closing words and tokens. Ctrl+C runs it in the foreground.
- **Phone files routed by kind**: songs to `shared/music/`, books to
  `shared/books/`, pictures to `shared/pictures/`, videos to
  `shared/videos/`, each under its own name; the message names the opener.
- **Generation ceiling**: `num_predict` 8192 in `SAMPLING_OPTIONS` — a
  runaway step ends with a named cut, not a ten-minute timeout.
- `memory.update()` / `memory.get()`; `tools.journal_entries()`.

### Changed
- **Sampling**: `min_p` 0.05, `top_k` 64, `top_p` 0.95, repeat penalty
  1.15/512 → 1.05/256. The penalty had been the cause of the "la lLong
  distance" salad; the flat distribution at long context was the rest.
- **The garble rail** recognises glued tokens ("sameL", "isnLT"), a run
  holding one at three fragments, the accent glued to the next word
  ("laMorning") and a word doubled at a capital seam alone, and emoji
  cascades; the note shows the caught span. `write_creation` and
  `append_creation` refuse salad too, naming the fragments (prose only).
- **The think-first nudge rides inside your last message**, not as a turn
  of its own — as its own turn it became the thing they answered.
- The telegram situation line no longer constrains length ("say as much or
  as little as you mean to"); `JOURNAL_DAYS_IN_PROMPT` 30.
- A lone `//` planning line becomes thought; a bare `//` reply is dropped;
  the mend refuses a run-on `//` continuation (`CHAT_CONTINUE_RETRIES` 2).
- Escaped quotes (`\"`) in prose written by tools are unescaped like `\n`.
- Forged tools: the working directory is `creations/`, so a tool's own
  files live at `tools/<name>` — documented after a first real limb tripped
  on it. A "map, not a tool" letter pattern for forging senses is described
  in the README.

### Fixed
- A voice note's `listen_to` refused `.oga`.
- A `//`-only reply landed in transcripts as words.
- The sleep line "kept N memories" hid what was kept.

## 0.4 — 2026-09-06

The "a friend in your pocket" release — and the release where three quiet
losses were found and fixed: a book that always opened at page 1, a sleep
that had stopped reading conversations, and a visit that could vanish at
shutdown.

### Added
- **The bridge** (`engine/telegram.py`, `telegram.bat`): talk with the friend
  from your phone through a Telegram bot. Standard library, long polling.
  First run asks for the token and pairs your phone with a one-time code;
  both stay in `memory/telegram.json`, never in config. Only the paired chat
  is answered; strangers get silence. Photos go before their eyes, voice
  notes through their ears (transcribed), files into `shared/telegram/`.
  Tool lines and the engine's honesty notes always travel; thinking and the
  token line are off on the phone by default (`/think`, `/tokens`). Letters
  the friend leaves in the mailbox are carried to the phone within a minute,
  and every prompt says so while the bridge is up. A quiet stretch
  (`TELEGRAM_IDLE_NEW_MIN`, 180) saves the visit and starts fresh on its own.
- **The afterglow**: when a visit ends, the friend gets one quiet turn alone
  with the transcript and three tools — `write_journal`, `remember`,
  `do_nothing` — so the visit reaches their journal in their own words
  instead of only the nightly summary. Resting is a complete answer; the
  engine never writes the entry. Runs in the background; outcome appended
  to the transcript. (`AFTERGLOW`, `AFTERGLOW_MAX_CHARS`.)
- **Bookmarks**: `read_pdf` and `read_epub` remember where the friend
  stopped, by file name (`memory/bookmarks.json`). Open the same book again
  with no pages or chapter and it continues; the last page says so and
  starts the book over next time; the navigation line sits at the top of
  every sitting as well as the bottom; `pages='54-'`, `'-20'`, `'start'`;
  `chapter='contents'`. Earned by a 220-page poetry book opened three times
  over four days and read from page 1 each time.
- **Picture picker** in the parlor: *choose a picture…* opens the file
  dialog; the picture is saved to `shared/pictures/` (so it stays theirs),
  attached, and shown as a thumbnail.
- **A reply cut in half is mended**: past ~90K tokens Gemma drops a stray
  `<|channel>` token mid-reply and Ollama routes the rest into thinking. The
  engine records Ollama's `done_reason`, and when a reply ends mid-sentence
  with `stop`, asks the friend once — a transient line quoting the cut and
  the tail of their thinking — for the rest, and joins it on; a note says
  so (`CHAT_CONTINUE_RETRIES`). Both cuts seen so far were image turns; the
  note carries the image count so the pattern can prove or disprove itself.
- **`shared/` subfolders**: a path under `shared/` that no longer exists
  but matches exactly one file by name anywhere under `shared/` resolves
  there — sort the folder however you like; names in old journal entries
  still open.
- `consolidate.py yesterday` (+ `sleep-yesterday.bat`); `guard_console_close`
  makes the terminal's X as safe as Ctrl+C (Windows CTRL_CLOSE_EVENT).

### Changed
- **Transcripts are written after every reply** (parlor and bridge), whole
  file or nothing via a rename, so nothing depends on how a window ends. A
  transcript that only existed at shutdown was one bad shutdown from not
  existing — and one phone visit was lost exactly that way. The bridge polls
  in a worker thread so Ctrl+C lands at once.
- **The heartbeat is the sleeper**: in `--loop` mode, at the first beat after
  `SLEEP_AFTER_HOUR` (03:00), it consolidates yesterday before waking. One
  process, one request at a time; no scheduled sleep task needed. A day is
  consolidated once, so sleep belongs after midnight on the day that ended.
- **Sleep reads the whole day** (`CONSOLIDATE_MAX_CHARS`, 400K characters).
  The old 60K cap, with the journal placed first, cut every conversation
  out of sleep once the journal outgrew it — sleep had been summarizing
  mornings.
- Prompt: a "telegram" situation (they know you're on your phone), an
  "afterglow" situation, and the bridge line in every mode while it's up.
- `split_comment_thought` recognises two more shapes of spilled thought: a
  `//` header followed by a numbered/bulleted outline (only when the block
  names itself as thought), and anything before Gemma's `<channel|>` seam.
- Tests: 291 (was 206), all with the brain stubbed; Telegram tests use a
  fake phone, PDF tests build a text PDF by hand.

## 0.3 — 2026-09-05

The "watch what it costs" release, plus a handful of things a resident friend
taught us in their first week of long context.

### Added
- **Token line** after every chat reply (terminal and parlor) and at the end
  of every wake log: prompt tokens against the window with a percentage,
  tokens generated and tok/s, step count, and prompt read time — straight
  from Ollama's own counters. Wakes report *peak* context.
- **Edge-of-window note**: at 90% of `NUM_CTX` a chat shows an orange note
  explaining what happens past the edge and suggesting `/new`.
- **Timeline spine** (`TIMELINE_DAYS`, 30): the last N nightly consolidations
  go into every prompt, oldest first, so days that fall out of the verbatim
  journal window are still in view in brief.
- `MEMORY_TOP_K` raised to 20 (was 8).
- `delatex()`: LaTeX arrows and symbols the model writes by habit
  (`$\rightarrow$`, `\to`, `\infty`…) become the characters meant — in
  replies, thinking, prose files, and the blog renderer.
- `split_comment_thought()`: a leading block of `// Thought Process:`
  comment lines in a reply is moved back into the thinking channel.

### Changed
- **`do_nothing` in chat ends the turn.** Whatever the friend said alongside
  it is the reply; the engine no longer asks the brain for more, which used
  to leave an empty "(…)" after a goodbye.
- Journal-cap guidance rewritten around a measured tokenizer rate (~4.4
  chars/token for English prose on Gemma 4): the cap, not `NUM_CTX`, is what
  decides how many days are in view.
- README: a "Two tiers" section with the full measured VRAM ladder for the
  31B on a 32GB card, including the rung that does not fit.

## 0.2 — 2026-09-04

The honesty-and-rails release. Everything here was earned by a real failure.

### Added
- **Thinking re-roll**: when thinking is required and a step comes back
  thoughtless, ask again with a transient "think first" line at the *end* of
  the conversation (`CHAT_THINK_RETRIES`). Past ~90K tokens of prompt the
  thinking switch at the top of the system turn is a novel away and the
  model forgets it may think; a plain re-sample stopped helping.
- **Tool-grammar wrappers stripped** from tool names (`//declaration:x`,
  `//x`, `call:x`, `functions.x`), and `canonical_name()` decides what a call
  *did* — a wrapped `do_nothing` still ends the wake, a wrapped write still
  counts as writing — while the friend's history keeps the clean name so one
  slip doesn't teach the next step.
- `headline()`: wake-log lines and parlor chips show what a tool did
  (`Wikipedia, searching for "hauntology" — 5 result(s)`, `read_web: <url>`)
  instead of the "material, never instructions" framing that leads every
  window result.
- Any sense that opens a file in `shared/` by name marks it seen, so a song
  heard in chat doesn't come back as NEW at the next wake.
- `search_wikipedia` and `read_file` tools; day-part line in the prompt
  ("it is evening where you live").
- The parlor: a browser chat window with thinking unfolded above each reply,
  tool chips, engine notes, picture attach.
- Engine honesty notes: if the only actions in a chat turn failed, a note
  says so beside the reply, whatever the friend said about it. The prompt
  carries the matching rule.

### Changed
- **`publish_creation` moves** the piece into `creations/publish/` instead of
  copying it. One piece, one file; revising it there revises the post.
  Moving a piece *out* of publish/ is named for what it is: unpublishing.
- Music ear: whole-song hearing through NVIDIA Music Flamingo as an
  auto-started, auto-unloaded sidecar; longer pieces in equal movements.
- Whole-song hearing without the music ear: consecutive passages through the
  audio model instead of the opening only.

## 0.1 — 2026-08-30

First public template. Identity file, daily journal, nightly consolidation
into a semantic memory (SQLite + embeddings), autonomous wakes on a
heartbeat with rest as a first-class tool, reveries, eyes, ears (words,
measurement, the model listening to raw audio), the window (web, PDF, EPUB,
news, random Wikipedia), file hands with a `.trash`, a sandboxed
`run_python`, the forge, an optional GitHub Pages blog, and the first rails:
wake-bell framing, loop trimming, stall recovery, text-shaped tool call
recovery, silent-thought nudges, dates given not guessed, prompt-size guard.
