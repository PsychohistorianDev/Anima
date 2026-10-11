"""Optional Chromium integration with synthetic microphone/audio; no speech models."""
import base64
import io
import json
import sys
import tempfile
import threading
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import parlor
import live_voice
from playwright.sync_api import sync_playwright


class Speech:
    def request(self, op, **kwargs):
        if op == "check": return {"installed": True}
        if op == "warmup": return {"ready": True}
        if op == "transcribe": return {"text": "hello friend"}
        data = io.BytesIO()
        with wave.open(data, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\0\0" * 8000)
        packet = {"audio": base64.b64encode(data.getvalue()).decode(), "seconds": .5}
        for _ in range(3):
            if kwargs["on_audio"](packet) is False: return {"cancelled": True}
        return {"seconds": 1.5}


def turn(history, text, **kwargs):
    reply = ("Hello. I'm here.\n\n[engine: voice delivery — internal note]"
             if kwargs.get("mode") == "voice" else "Typed reply.")
    history.extend([{"role": "user", "content": text}, {"role": "assistant", "content": reply}])
    return reply


def main():
    root = parlor.config.ROOT
    with tempfile.TemporaryDirectory() as directory, \
         patch.object(parlor, "SESSION", parlor.Session()), \
         patch.object(live_voice, "WORKER", Speech()), \
         patch.object(parlor.chat, "one_turn", turn), \
         patch.object(parlor.chat, "friend_name", return_value="Friend"), \
         patch.object(parlor.config, "ROOT", Path(directory)), \
         patch.object(parlor.config, "AFTERGLOW", False), \
         patch.object(parlor.config, "LIVE_VOICE_ENABLED", False), \
         patch.object(parlor.config, "LIVE_VOICE_KYUTAI_STYLE", "calm"):
        parlor.SESSION.playback = live_voice.Playback(live_voice.WORKER)
        parlor.SESSION.file = Path(directory) / "synthetic-visit.md"
        server = parlor.ThreadingHTTPServer(("127.0.0.1", 0), parlor.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
                page = browser.new_page(viewport={"width": 1050, "height": 760})
                errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
                page.add_init_script("""
                  window.voiceSchedule = [];
                  const createBuffer = AudioContext.prototype.createBufferSource;
                  AudioContext.prototype.createBufferSource = function() {
                    const node = createBuffer.call(this), start = node.start.bind(node);
                    node.start = when => { window.voiceSchedule.push({when, duration: node.buffer.duration}); start(when); };
                    return node;
                  };
                  navigator.mediaDevices.getUserMedia = async () => {
                    const context = new AudioContext(); await context.resume();
                    const oscillator = context.createOscillator(); oscillator.frequency.value = 220;
                    const gain = context.createGain(); gain.gain.value = 0;
                    const destination = context.createMediaStreamDestination();
                    oscillator.connect(gain); gain.connect(destination); oscillator.start();
                    window.testMicrophone = {context, gain, destination};
                    return destination.stream;
                  };
                """)
                page.goto(base)
                assert page.locator("#voiceToggle").count() == 0
                page.locator("#box").fill("A typed message")
                page.locator("#send").click()
                page.wait_for_function("document.querySelector('.msg.her')?.textContent === 'Typed reply.'")
                assert page.evaluate("window.testMicrophone") is None
                parlor.SESSION.history.clear()
                parlor.config.LIVE_VOICE_ENABLED = True
                page.reload(); page.locator("#voiceToggle").wait_for()
                import knobs
                with patch.object(knobs, "save", return_value=(["LIVE_VOICE_KYUTAI_STYLE"], [], "")) as saved:
                    page.locator("#kyutaiStyle").select_option("desire")
                    page.wait_for_function("document.querySelector('#log').textContent.includes('Delivery changed')")
                    assert saved.call_args.args[1] == {"LIVE_VOICE_KYUTAI_STYLE": "desire"}
                page.locator("#voiceToggle").click()
                page.wait_for_function("document.getElementById('voiceState').textContent === 'listening'")
                page.evaluate("testMicrophone.gain.gain.value = .12")
                page.wait_for_timeout(400)
                page.evaluate("testMicrophone.gain.gain.value = 0")
                page.wait_for_function("document.getElementById('voiceState').textContent.startsWith('speaking')")
                assert page.locator(".msg.me").first.inner_text() == "hello friend"
                assert page.locator(".msg.her").first.inner_text() == "Hello. I'm here."
                assert "[engine: voice delivery" not in parlor.SESSION.file.read_text(encoding="utf-8")
                page.evaluate("testMicrophone.gain.gain.value = .12")
                page.wait_for_timeout(120)
                page.evaluate("testMicrophone.gain.gain.value = 0")
                page.wait_for_timeout(180)
                assert page.locator("#voiceState").inner_text().startswith("speaking")
                schedule = page.evaluate("voiceSchedule")
                assert len(schedule) >= 2, schedule
                assert abs(schedule[1]["when"] - schedule[0]["when"] - schedule[0]["duration"]) < .001, schedule
                assert "Playback interrupted" not in parlor.SESSION.file.read_text(encoding="utf-8")
                page.evaluate("testMicrophone.gain.gain.value = .12")
                page.wait_for_timeout(550)
                page.evaluate("testMicrophone.gain.gain.value = 0")
                page.wait_for_timeout(200)
                assert "Playback interrupted" in parlor.SESSION.file.read_text(encoding="utf-8")
                page.locator("#voiceToggle").click()
                page.wait_for_function("document.getElementById('voiceState').textContent === 'voice is off'")
                assert page.evaluate("testMicrophone.destination.stream.getAudioTracks()[0].readyState") == "ended"
                metrics = Path(directory) / ".runtime" / "voice-latency.jsonl"
                assert json.loads(metrics.read_text().splitlines()[-1])["end_to_first_audio_ms"] > 0
                page.locator("#leave").click()
                page.wait_for_function("document.getElementById('box').disabled")
                assert errors == [], errors
                artifacts = root / ".runtime" / "voice-tests"; artifacts.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(artifacts / "voice-browser.png"))
                browser.close()
                print("PASS browser: disabled text chat, voice capture, continuous playback, noise rejection, interruption, style and microphone release")
        finally:
            parlor.SESSION.playback.cancel()
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == "__main__": main()
