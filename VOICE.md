# Optional turn-based voice in Parlor

Parlor can listen through the browser microphone and speak replies locally.
Voice is **off by default**: `LIVE_VOICE_ENABLED = False`. Ordinary text chat
requires no speech packages and starts no speech worker.

## Setup

From the project folder, run:

```text
python engine/setup_voice.py --download
```

The installer creates a separate Python 3.12 environment at
`.runtime/voice-env` using uv, then installs `requirements-voice.txt`.
It keeps packages, downloaded models and runtime logs under `.runtime/`.
The initial installation and model download need internet access and several
gigabytes of disk space. It does not change the engine's Python environment.

Set `LIVE_VOICE_ENABLED = True` in `engine/config.py`, then restart Parlor.
Click **start voice** and allow microphone access. Speak, pause for about
one second, and listen to the reply. Speaking for a sustained interval
interrupts playback; brief clicks do not. **Stop voice**, **leave** and
closing the page release the microphone. Headphones help prevent speaker
audio from being recognized as your speech.

Use a browser with AudioWorklet and microphone support at Parlor's local
address (`127.0.0.1`). Delivery can be changed among four released Kyutai
voices/styles; changing it stops voice mode, then Start voice resumes it.

## Models and conversation

Speech recognition uses faster-whisper with `large-v3-turbo`, beam size 5.
Recognition defaults to CPU/int8 to leave room for the brain. Set
`LIVE_VOICE_STT_DEVICE = "cuda"` for GPU/float16 when the card has headroom.
`LIVE_VOICE_STT_HINT` can supply uncommon names or vocabulary. The browser
submits mono 16 kHz PCM utterances, capped at 30 seconds.

Speech uses the standalone PyTorch implementation of
[Kyutai TTS 1.6B](https://huggingface.co/kyutai/tts-1.6b-en_fr), through
[Moshi](https://github.com/kyutai-labs/moshi), with 32 audio codebooks.
The default speech device is CUDA. The Windows implementation disables
torch.compile; it does not require WSL or the complete Unmute system.
The native Windows CUDA path has been exercised in the original local
implementation. Other operating systems and CPU speech generation need
real-model validation; the mocked contracts do not establish their performance.

This is a continuous microphone with a **turn-based brain**. Each recognized
utterance goes through the existing `chat.one_turn` path, identity, memories,
tools and reply checks. The complete accepted reply is generated before
speech begins; Kyutai then streams adjacent audio buffers to the browser.
Gemma tokens are not streamed directly into the speech model.

`LIVE_VOICE_THINK = None` inherits `CHAT_THINK` and its existing thought retry
rail. Setting it to `False` disables thinking only for spoken calls. Voice
requests retain the normal tools and reply-repair checks either way.

Typed and spoken turns share the same Parlor visit and transcript. Playback
receipts record completion or interruption as application metadata. They do
not claim the speech was independently verified and do not become dialogue
sent back to the model. The next spoken turn can acknowledge that an earlier
written reply may not have been heard in full.

## Resources and privacy

Speech models stay loaded in a separate worker during use. Unused PyTorch
CUDA allocator cache is released after warmup, recognition, synthesis,
cancellation and failures; live model weights remain resident. Large Gemma
context allocations plus GPU speech can still exceed the card's budget.
Upstream's `EMBED_ON_CPU` setting can help leave room. These changes do not
replace the memory store or change its embeddings.

**Known open item — residency.** The speech worker keeps Kyutai on the card
between turns (about 6.7 GB). Beside a brain that fills the card — a 31B at
a long window, or any brain on a 24 GB card — that pushes Ollama into shared
system memory, and prompt processing falls to a crawl (measured by the
contributor: ~33 tokens a second, a ten-minute timeout before thinking). The
engine's pattern for its other sidecars (the ears, the painter) is that a
model leaves the card when idle and comes back for the next turn — a second
or two on a big card, nothing for a turn-based conversation. That is the
piece still to write: an idle timeout after which the worker moves the
speech model to the CPU or frees it. Until then, run the parlor voice with
the painter down and watch `ollama ps` for a brain that is no longer 100% on
the card.

Microphone and generated audio are held in memory, not saved as recordings.
Only recognized text and the ordinary reply enter the transcript. Existing
Anima tools still have their normal behavior. Speech-worker diagnostics go
to `.runtime/voice-worker.log`; latency measurements in
`.runtime/voice-latency.jsonl` contain durations, not conversation text.
These runtime files and model caches are ignored by Git.

With `OFFLINE = True`, the worker uses cached models; install/download them
before enabling offline mode. Restart Parlor after changing config settings.

## Validation

```text
python tests/test_live_voice.py
```

The contracts stub speech models and cover audio validation, recognition
options, cancellation, progressive playback, receipts, endpoint restrictions,
and preserving the ordinary conversation path. They do not download models.

An optional Chromium integration test uses a synthetic microphone:

```text
python -m pip install playwright
python -m playwright install chromium
python tests/test_voice_browser.py
```

Run the full smoke suite in an isolated checkout; it writes synthetic memory,
journal and creation fixtures. No panel changes are included in this feature.
