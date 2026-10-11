"""Voice contracts, with fake speech models and isolated temporary storage.

Run in the isolated smoke home, not the friend's live folder. No audio/model downloads.
"""
import base64
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import config
import chat
import live_voice
import parlor
import voice_worker


def wav(rate=16000, channels=1, frames=1600):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\0\0" * frames * channels)
    return buf.getvalue()


class Speech:
    def request(self, op, **kwargs):
        if op == "transcribe":
            return {"text": "hello the friend"}
        return {"audio": base64.b64encode(wav()).decode(), "seconds": .1}


class VoiceTests(unittest.TestCase):
    def test_voice_disabled_starts_no_worker_and_keeps_text_available(self):
        session = parlor.Session()
        with patch.object(config, "LIVE_VOICE_ENABLED", False), \
             patch.object(parlor, "SESSION", session), \
             patch.object(live_voice.WORKER, "request") as speech, \
             patch.object(session, "send", return_value={"reply": "A text reply."}) as send:
            server = parlor.ThreadingHTTPServer(("127.0.0.1", 0), parlor.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urllib.request.urlopen(base) as r:
                    page = r.read()
                self.assertNotIn(b'id="voiceToggle"', page)
                self.assertNotIn(b'<script src="/parlor-voice.js">', page)
                for path in ("/live-voice/settings", "/parlor-voice.js", "/voice-worklet.js"):
                    with self.assertRaises(urllib.error.HTTPError) as failure:
                        urllib.request.urlopen(base + path)
                    self.assertEqual(failure.exception.code, 404); failure.exception.close()
                request = urllib.request.Request(base + "/live-voice/warmup", data=b"{}")
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    urllib.request.urlopen(request)
                self.assertEqual(failure.exception.code, 404); failure.exception.close()
                request = urllib.request.Request(base + "/send", data=b'{"text":"Hello"}')
                with urllib.request.urlopen(request) as r:
                    self.assertEqual(json.load(r)["reply"], "A text reply.")
                send.assert_called_once_with("Hello")
                speech.assert_not_called()
            finally:
                server.shutdown(); server.server_close(); thread.join(2)

    def test_voice_uses_chat_context_and_inherits_thinking_and_tool_checks(self):
        history = []
        responses = [{"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": "remember", "arguments": {"text": "A synthetic fact", "type": "note"}}}]},
            {"role": "assistant", "content": "I remembered it."}]
        with patch.object(chat.assemble, "system_prompt", return_value="existing identity") as system, \
             patch.object(chat.assemble, "moment", return_value=("", [])), \
             patch.object(config, "LIVE_VOICE_THINK", None), \
             patch.object(chat.ollama_client, "chat", side_effect=responses) as run, \
             patch.object(chat.tools, "refresh_her_tools"), \
             patch.object(chat.tools, "dispatch", return_value="remembered") as dispatch, \
             patch.object(chat, "mark_visit_live"):
            reply = chat.one_turn(history, "Remember this", mode="voice", on_event=lambda *args: None)
        self.assertEqual(reply, "I remembered it.")
        self.assertEqual(system.call_args.kwargs["mode"], "chat")
        dispatch.assert_called_once()
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertIsNone(call.kwargs["think"])
            self.assertNotIn("think_retries", call.kwargs)
            self.assertTrue(call.kwargs["expect_words"])
            self.assertIs(call.kwargs["tools"], chat.tools.DEFINITIONS)

    def test_unused_cuda_cache_is_released_without_unloading_models(self):
        cuda = SimpleNamespace(is_initialized=lambda: True, empty_cache=Mock())
        stt, tts = object(), object()
        with patch.dict(sys.modules, {"torch": SimpleNamespace(cuda=cuda)}), \
             patch.object(voice_worker, "_stt", stt), patch.object(voice_worker, "_tts", tts):
            voice_worker.release_cuda_cache()
            self.assertIs(voice_worker._stt, stt)
            self.assertIs(voice_worker._tts, tts)
        cuda.empty_cache.assert_called_once()

    def test_cuda_cleanup_runs_after_completed_failed_and_cancelled_work(self):
        with patch.object(voice_worker, "release_cuda_cache") as cleanup:
            with patch.object(voice_worker, "_handle", return_value={"text": "That is Squadron 42."}):
                self.assertEqual(voice_worker.handle({"op": "transcribe"})["text"], "That is Squadron 42.")
            for failure in (RuntimeError("failure"), voice_worker.SpeechCancelled()):
                with patch.object(voice_worker, "_handle", side_effect=failure):
                    with self.assertRaises(type(failure)):
                        voice_worker.handle({"op": "synthesize_stream"})
        self.assertEqual(cleanup.call_count, 3)

    def test_cache_cleanup_error_does_not_discard_completed_speech(self):
        cuda = SimpleNamespace(is_initialized=lambda: True, empty_cache=Mock(side_effect=RuntimeError("driver cleanup failed")))
        with patch.dict(sys.modules, {"torch": SimpleNamespace(cuda=cuda)}), \
             patch.object(voice_worker, "_handle", return_value={"text": "That is Squadron 42."}), \
             patch.object(sys, "stderr", io.StringIO()):
            self.assertEqual(voice_worker.handle({"op": "transcribe"})["text"], "That is Squadron 42.")

    def test_recognition_model_cache_includes_device_and_precision(self):
        seen = []
        def model(name, **kwargs):
            seen.append((name, kwargs)); return object()
        with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=model)}), \
             patch.object(voice_worker, "_stt", None), patch.object(voice_worker, "_stt_key", None), \
             patch.object(voice_worker, "_stt_warmed", False):
            req = {"stt_model": "large-v3-turbo", "stt_device": "cuda", "offline": True}
            voice_worker.models(req, speech=False)
            voice_worker.models(req, speech=False)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][1]["device"], "cuda")
            self.assertEqual(seen[0][1]["compute_type"], "float16")
            voice_worker._stt_warmed = True
            voice_worker.models(dict(req, stt_device="cpu"), speech=False)
            self.assertEqual(len(seen), 2)
            self.assertEqual(seen[1][1]["compute_type"], "int8")
            self.assertFalse(voice_worker._stt_warmed)

    def test_recognition_preserves_statements_and_uses_wider_search(self):
        class Samples:
            shape = (1600, 1)
            def __len__(self): return 1600
        seen = {}
        class Recognizer:
            def transcribe(self, samples, **kwargs):
                seen.update(kwargs)
                return iter([SimpleNamespace(text="That is Squadron 42.")]), None
        with patch.dict(sys.modules, {"soundfile": SimpleNamespace(read=lambda *a, **k: (Samples(), 16000)),
                                     "numpy": SimpleNamespace(squeeze=lambda x, **k: x)}), \
             patch.object(voice_worker, "models"), patch.object(voice_worker, "_stt", Recognizer()):
            result = voice_worker.handle({"op": "transcribe", "audio": base64.b64encode(wav()).decode(),
                                          "language": "en", "stt_beam_size": 5, "vocab": "Squadron 42"})
        self.assertEqual(result["text"], "That is Squadron 42.")
        self.assertEqual(seen["beam_size"], 5)
        self.assertEqual(seen["initial_prompt"], "Squadron 42")
        self.assertTrue(seen["vad_filter"])

    def test_recognition_warmup_discards_synthetic_text_and_runs_once(self):
        seen = []
        class Recognizer:
            def transcribe(self, samples, **kwargs):
                seen.append(kwargs)
                return iter([SimpleNamespace(text="discard this")]), None
        with patch.object(voice_worker, "models"), patch.object(voice_worker, "_stt", Recognizer()), \
             patch.object(voice_worker, "_stt_warmed", False), patch.object(voice_worker, "_warmed", False), \
             patch.object(voice_worker, "generate"):
            for _ in range(2):
                self.assertEqual(voice_worker.handle({"op": "warmup", "language": "en", "stt_beam_size": 5}), {"ready": True})
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["max_new_tokens"], 1)
        self.assertFalse(seen[0]["vad_filter"])

    def test_recognition_request_keeps_names_and_adds_vocabulary(self):
        worker = live_voice.Worker()
        stream = io.StringIO()
        worker.proc = SimpleNamespace(stdin=stream)
        worker.responses.put({"id": "test", "text": "That is Squadron 42."})
        with patch.object(worker, "_start"), \
             patch.object(live_voice.uuid, "uuid4", return_value=SimpleNamespace(hex="test")), \
             patch.object(config, "LIVE_VOICE_STT_HINT", "Squadron 42"), \
             patch.object(config, "LIVE_VOICE_STT_DEVICE", "cuda"), \
             patch.object(config, "LIVE_VOICE_STT_BEAM_SIZE", 5):
            worker.request("transcribe", vocab="Names: Alex, the friend.", audio="unused")
        sent = json.loads(stream.getvalue())
        self.assertIn("Alex, the friend", sent["vocab"])
        self.assertIn("Squadron 42", sent["vocab"])
        self.assertEqual(sent["stt_device"], "cuda")
        self.assertEqual(sent["stt_beam_size"], 5)
        worker.proc = None

    def test_kyutai_generation_uses_the_selected_delivery(self):
        seen = {}
        class Kyutai:
            def synthesize(self, text, style, voice=None):
                seen.update(text=text, style=style, voice=voice)
                return [0., .1], 24000, .1
        with patch.object(voice_worker, "_tts", Kyutai()):
            samples, rate = voice_worker.generate({"backend": "kyutai", "style": "desire"}, "Hello.")
        self.assertEqual(seen["style"], "desire")
        self.assertEqual(rate, 24000)
        rendered = chat.render_turn({"role": "user", "content": "hello", "_voice_mode": True, "_voice_backend": "kyutai"})
        self.assertNotIn("[chuckle]", rendered["content"])
    def test_chunks_keep_expression_and_remove_written_format(self):
        chunks = live_voice.speech_chunks("**Hello.** [chuckle] Nice to see you. *leans closer*\n```python\nx=1\n```\n[site](https://example.com)", 65)
        self.assertIn("[chuckle]", " ".join(chunks))
        self.assertNotIn("leans closer", " ".join(chunks))
        self.assertNotIn("https", " ".join(chunks))
        self.assertNotIn("x=1", " ".join(chunks))
        self.assertTrue(all(len(c) <= 65 for c in chunks))

    def test_wav_contract(self):
        parlor.validate_wav(wav())
        for invalid in (b"not audio", wav(rate=48000), wav(channels=2), wav(frames=32*16000), wav()[:-10]):
            with self.assertRaises(ValueError):
                parlor.validate_wav(invalid)

    def test_short_sentences_share_prosodic_context(self):
        text = "Hey, Alex. Take your time. I'm listening."
        self.assertEqual(live_voice.speech_chunks(text), [text])
        longer = ("It is a longer thought, " + "with room to breathe " * 12).strip() + "."
        chunks = live_voice.speech_chunks(longer, 100)
        self.assertTrue(all(len(c) <= 100 for c in chunks))
        self.assertEqual(" ".join(chunks), longer.strip())

    def test_cancel_discards_in_flight_synthesis(self):
        begun = threading.Event(); release = threading.Event()
        class Slow(Speech):
            def request(self, *args, **kwargs):
                begun.set(); release.wait(3); return super().request(*args, **kwargs)
        playback = live_voice.Playback(Slow())
        epoch = playback.cancel(); job = playback.start("Hello.", epoch, {})
        self.assertTrue(begun.wait(2))
        playback.cancel(); release.set(); time.sleep(.03)
        self.assertTrue(playback.status(job)["cancelled"])
        self.assertIsNone(playback.audio(job, 0))
        self.assertIsNone(playback.start("Stale reply.", epoch, {}))

    def test_phrase_audio_has_backpressure_and_receipts(self):
        playback = live_voice.Playback(Speech(), stream=False)
        phrases = [word + " is a complete sentence with enough words to stand alone." for word in ("One", "Two", "Three", "Four")]
        with patch.object(config, "LIVE_VOICE_CHUNK_CHARS", 65):
            job = playback.start(" ".join(phrases), playback.cancel(), {})
        for _ in range(100):
            if len(playback.status(job)["chunks"]) == 2: break
            time.sleep(.01)
        self.assertEqual(len(playback.status(job)["chunks"]), 2)
        playback.acknowledge(job, 0)
        for _ in range(100):
            if len(playback.status(job)["chunks"]) == 3: break
            time.sleep(.01)
        self.assertEqual(len(playback.status(job)["chunks"]), 3)
        _, note = playback.delivery(job, 1, True)
        self.assertIn("1 of 4", note)
        self.assertIn("interrupted", note)
        self.assertNotIn(phrases[0], note)
        self.assertIn("not independently verified", note)
        playback.cancel()

    def test_progressive_audio_arrives_before_synthesis_finishes_and_cancels(self):
        emitted = threading.Event(); release = threading.Event(); cancelled = threading.Event()
        class StreamingSpeech(Speech):
            def request(self, op, on_audio=None, **kwargs):
                self.assert_op = op
                packet = super().request('synthesize')
                on_audio(packet); emitted.set(); release.wait(3)
                if on_audio(packet) is False:
                    cancelled.set()
                    return {"cancelled": True}
                return {"seconds": .2}
        worker = StreamingSpeech(); playback = live_voice.Playback(worker, stream=True)
        job = playback.start('One continuous reply. Another sentence.', playback.cancel(), {})
        self.assertTrue(emitted.wait(2))
        self.assertEqual(worker.assert_op, 'synthesize_stream')
        self.assertFalse(playback.status(job)['done'])
        self.assertIsNotNone(playback.audio(job, 0))
        playback.cancel(); release.set()
        self.assertTrue(cancelled.wait(2))
        self.assertIsNone(playback.audio(job, 0))

    def test_voice_uses_same_history_and_persists_delivery(self):
        session = parlor.Session(); session.playback = live_voice.Playback(Speech())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "visit.md"
            session.file = path
            def turn(history, text, **kwargs):
                self.assertEqual(kwargs["mode"], "voice")
                history.extend([{"role": "user", "content": text}, {"role": "assistant", "content": "Hello."}])
                return "Hello."
            with patch.object(chat, "one_turn", turn):
                result = session.send("hello", spoken=True, epoch=session.playback.cancel())
            self.assertEqual(result["transcript"], "hello")
            self.assertEqual(len(session.history), 2)
            for _ in range(100):
                if session.playback.status(result["speech_job"])["done"]: break
                time.sleep(.01)
            session.delivery(result["speech_job"], 0, True)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Playback interrupted", text)
            self.assertIn("Hello.", text)
            self.assertEqual(chat.render_turn(session.history[-1])["content"], "Hello.")
            session.playback.cancel()

    def test_ended_visit_does_not_receive_late_transcription(self):
        session = parlor.Session()
        session.generation = 2
        with patch.object(chat, "one_turn") as run:
            self.assertIn("ended", session.send("stale", generation=1)["error"])
            run.assert_not_called()

    def test_playback_diagnostics_cannot_become_dialogue(self):
        block = "[engine: voice delivery — 6 of 6 phrases finished playing. Completely played speech: Hello.]"
        original = {"role": "assistant", "content": "Hello.\n\n" + block, "_voice_delivery": "Playback completed; " + block}
        self.assertEqual(chat.render_turn(original)["content"], "Hello.")
        self.assertEqual(original["content"], "Hello.\n\n" + block)
        self.assertEqual(chat.strip_voice_delivery("Hello.\n\n" + block), "Hello.")
        self.assertEqual(chat.strip_voice_delivery("Hello. [engine: voice delivery — unfinished"), "Hello.")
        self.assertEqual(chat.strip_voice_delivery("I hear you [and understand]."), "I hear you [and understand].")
        self.assertEqual(chat.strip_voice_delivery("Hello. [application state, not spoken dialogue: interrupted]"), "Hello.")

    def test_voice_prompt_is_per_turn_and_thinking_is_per_call(self):
        turn = {"role": "user", "content": "Hello", "_voice_mode": True}
        self.assertIn("spoken conversation", chat.render_turn(turn)["content"])
        self.assertEqual(chat.render_turn({"role": "user", "content": "Hello"})["content"], "Hello")
        history = []
        old_think = config.CHAT_THINK
        with patch.object(chat.assemble, "system_prompt", return_value="existing identity"), \
             patch.object(chat.assemble, "moment", return_value=("", [])), \
             patch.object(config, "LIVE_VOICE_THINK", False), \
             patch.object(chat.ollama_client, "chat", return_value={"role": "assistant", "content": "Hi."}) as run, \
             patch.object(chat.tools, "refresh_her_tools"), patch.object(chat, "mark_visit_live"):
            chat.one_turn(history, "Hello", mode="voice", on_event=lambda *args: None)
        self.assertFalse(run.call_args.kwargs["think"])
        self.assertNotIn("think_retries", run.call_args.kwargs)
        self.assertEqual(config.CHAT_THINK, old_think)


    def test_local_http_contract_and_origin_checks(self):
        self.voice_enabled = patch.object(config, "LIVE_VOICE_ENABLED", True)
        self.voice_enabled.start(); self.addCleanup(self.voice_enabled.stop)
        server = parlor.ThreadingHTTPServer(("127.0.0.1", 0), parlor.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            for path, content in (("/", b"start voice"), ("/parlor-voice.js", b"getUserMedia"), ("/voice-worklet.js", b"registerProcessor")):
                with urllib.request.urlopen(base + path) as r: self.assertIn(content, r.read())
            req = urllib.request.Request(base + "/live-voice/interrupt", data=b"{}", headers={"Origin": "https://evil.example"})
            with self.assertRaises(urllib.error.HTTPError) as e: urllib.request.urlopen(req)
            self.assertEqual(e.exception.code, 403)
            e.exception.close()
            for payload in (b"[]", b"broken"):
                req = urllib.request.Request(base + "/live-voice/interrupt", data=payload)
                with self.assertRaises(urllib.error.HTTPError) as e: urllib.request.urlopen(req)
                self.assertEqual(e.exception.code, 400)
                e.exception.close()
            req = urllib.request.Request(base + "/live-voice/style", data=b'{"style":"invalid"}')
            with self.assertRaises(urllib.error.HTTPError) as e: urllib.request.urlopen(req)
            self.assertEqual(e.exception.code, 400)
            e.exception.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(2)



if __name__ == "__main__":
    unittest.main()
