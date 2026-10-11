/* Turn-based voice on the same visit as text chat. No browser speech APIs or cloud STT. */
(() => {
  const toggle = document.getElementById('voiceToggle');
  const state = document.getElementById('voiceState');
  let enabled = false, starting = false, context, stream, source, microphone, mute;
  let settings, recording = [], preRoll = [], preLength = 0, sampleCount = 0;
  let voicedMs = 0, candidateMs = 0, silenceMs = 0, active = false;
  let pending = [], draining = false, lifecycle = 0, playbackGeneration = 0;
  let visitGeneration = 0, interruptTask = Promise.resolve();
  let currentJob = null, player = null, completed = 0, phase = 'off', noise = .002;
  const players = new Set();
  let lastVoiceAt = 0;
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  function status(text) { state.textContent = text; }
  function resetUtterance() { recording = []; sampleCount = 0; voicedMs = 0; candidateMs = 0; silenceMs = 0; active = false; }
  function resetCapture() { resetUtterance(); preRoll = []; preLength = 0; }
  function bytes64(bytes) {
    let binary = '';
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return btoa(binary);
  }
  function wav64(blocks, rate) {
    const size = blocks.reduce((n, a) => n + a.length, 0);
    const input = new Float32Array(size);
    let offset = 0;
    for (const block of blocks) { input.set(block, offset); offset += block.length; }
    const ratio = rate / 16000, length = Math.floor(size / ratio);
    const buffer = new ArrayBuffer(44 + length * 2), view = new DataView(buffer);
    const ascii = (position, text) => { for (let i = 0; i < text.length; i++) view.setUint8(position + i, text.charCodeAt(i)); };
    ascii(0, 'RIFF'); view.setUint32(4, 36 + length * 2, true); ascii(8, 'WAVE'); ascii(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    ascii(36, 'data'); view.setUint32(40, length * 2, true);
    for (let i = 0; i < length; i++) {
      const start = Math.floor(i * ratio), end = Math.min(size, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = start; j < end; j++) sum += input[j];
      const value = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
      view.setInt16(44 + i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
    }
    return bytes64(new Uint8Array(buffer));
  }
  async function receipt(job, count, partial, reason = 'unknown') {
    if (!job) return;
    try { await post('/live-voice/delivery', {job, completed: count, partial, reason}); } catch (_) {}
  }
  async function interrupt(reason = 'unknown') {
    playbackGeneration++;
    const job = currentJob, count = completed, partial = !!player;
    currentJob = null; completed = 0;
    for (const node of players) { node.onended = null; node.stop(); }
    players.clear(); player = null;
    // Submit the receipt before cancellation replaces the current job.
    interruptTask = interruptTask.then(async () => {
      await receipt(job, count, partial, reason);
      try { await post('/live-voice/interrupt'); } catch (_) {}
    });
    await interruptTask;
    if (enabled && !draining && !active) { phase = 'listening'; status('listening'); }
  }
  window.interruptLiveVoice = interrupt;
  window.voiceVisitChanged = () => { visitGeneration++; };

  async function play(job, token, endedAt, timings) {
    const generation = playbackGeneration;
    currentJob = job; completed = 0;
    let next = 0;
    let nextAudioAt = 0, first = true;
    try {
      while (enabled && token === lifecycle && generation === playbackGeneration) {
        // Fetch while the current buffer plays, but bound queued audio.
        if (nextAudioAt - context.currentTime > 1.2) { await delay(35); continue; }
        const result = await post('/live-voice/status', {job});
        if (result.cancelled) break;
        const chunk = (result.chunks || []).find(c => c.index === next);
        if (chunk) {
          const response = await fetch('/live-voice/audio/' + job + '/' + next, {cache: 'no-store'});
          if (!response.ok) throw new Error('speech audio became unavailable');
          const audio = await context.decodeAudioData(await response.arrayBuffer());
          if (!enabled || token !== lifecycle || generation !== playbackGeneration) break;
          phase = 'speaking'; if (!active) status('speaking — you can interrupt');
          const node = context.createBufferSource(); node.buffer = audio; node.connect(context.destination); player = node;
          const startAt = Math.max(nextAudioAt, context.currentTime + (first ? .08 : .015));
          if (first) {
            // Smooth only a digital start discontinuity; do not trim speech.
            node.disconnect(); const gain = context.createGain(); node.connect(gain); gain.connect(context.destination);
            gain.gain.setValueAtTime(0, startAt); gain.gain.linearRampToValueAtTime(1, startAt + .005);
            post('/live-voice/timing', {end_to_first_audio_ms: endedAt ? performance.now() - endedAt + (startAt-context.currentTime)*1000 : null,
              recognition_s: timings && timings.recognition_s, turn_s: timings && timings.turn_s,
              first_audio_s: result.first_audio_s}).catch(() => {});
          }
          const index = next++;
          players.add(node);
          node.onended = () => {
            players.delete(node); player = players.values().next().value || null;
            if (generation !== playbackGeneration) return;
            completed++; post('/live-voice/ack', {job, index}).catch(() => {});
          };
          node.start(startAt); nextAudioAt = startAt + audio.duration; first = false;
          continue;
        }
        if (result.error) throw new Error(result.error);
        if (result.done) {
          if (players.size) { await delay(35); continue; }
          break;
        }
        if (!active && !players.size) status('preparing voice…');
        await delay(50);
      }
      if (generation === playbackGeneration && currentJob === job) {
        await receipt(job, completed, false); currentJob = null;
      }
    } catch (e) {
      sys('Voice: ' + e.message);
      if (generation === playbackGeneration && currentJob === job) await interrupt('playback_error');
    }
    if (enabled && token === lifecycle && !active) { phase = 'listening'; status('listening'); }
  }

  async function drain() {
    if (draining) return;
    draining = true;
    try {
      while (enabled && pending.length) {
        while (busy && enabled) await delay(100);
        if (!enabled) break;
        const item = pending.shift(), audio = item.audio, token = lifecycle, visit = visitGeneration, speechGeneration = playbackGeneration;
        busy = true; send.disabled = true; phase = 'thinking';
        if (!active) status('listening to your words, then thinking…');
        const typing = add('typing', '<span>●</span><span>●</span><span>●</span>');
        let result;
        try {
          await interruptTask;
          result = await post('/live-voice/turn', {audio});
          if (visit !== visitGeneration) continue;
          if (result.error) sys('Voice: ' + result.error);
          else if (result.empty) { if (!active) status('no words detected — listening'); }
          else {
            add('msg me', md(result.transcript));
            addThinking(result.thinking); addChips(result.tools); add('msg her', md(result.reply));
            (result.voices || []).forEach(v => add('msg her voice', '<audio controls src="' + v.url + '"></audio><small> voice note</small>'));
            (result.notes || []).forEach(n => add('sys warn', esc(n)));
            if (result.tokens) add('sys tokens', esc(result.tokens.line));
          }
        } catch (e) { sys('Voice connection failed: ' + e.message); }
        finally { typing.remove(); busy = false; send.disabled = box.disabled; }
        if (result && result.speech_job && token === lifecycle && speechGeneration === playbackGeneration && enabled && !pending.length) {
          // Do not block recognition of another utterance on audio playback.
          play(result.speech_job, token, item.endedAt, result.timings);
        }
      }
    } finally {
      draining = false;
      if (enabled && !currentJob && !active) { phase = 'listening'; status('listening'); }
    }
  }

  function finish() {
    if (voicedMs >= settings.min_speech_ms && sampleCount) {
      if (pending.length < 2) { pending.push({audio: wav64(recording, context.sampleRate), endedAt: lastVoiceAt}); drain(); }
      else sys('Voice: two turns are already queued; wait for the current reply.');
    }
    resetCapture();
    if (!draining && !currentJob) { phase = 'listening'; status('listening'); }
  }
  function capture(pcm) {
    if (!enabled || !(pcm instanceof Float32Array)) return;
    let energy = 0;
    for (const v of pcm) energy += v * v;
    const rms = Math.sqrt(energy / pcm.length), ms = pcm.length / context.sampleRate * 1000;
    // Adapt only to quiet frames; avoid learning the friend's or the user's speech as noise.
    if (!active && phase !== 'speaking' && rms < settings.threshold) noise = noise * .98 + rms * .02;
    const threshold = Math.max(settings.threshold, noise * 3);
    const voiced = rms > threshold;
    if (voiced) lastVoiceAt = performance.now();
    if (!active) {
      preRoll.push(pcm); preLength += pcm.length;
      const leadInSeconds = Math.max(settings.min_speech_ms, settings.interrupt_ms || 350) / 1000 + .15;
      while (preLength > context.sampleRate * leadInSeconds && preRoll.length > 1) preLength -= preRoll.shift().length;
      candidateMs = voiced ? candidateMs + ms : 0;
      const confirmation = Math.max(settings.min_speech_ms, phase === 'speaking' ? (settings.interrupt_ms || 350) : 200);
      if (candidateMs < confirmation) return;
      active = true; recording = preRoll.slice(); sampleCount = preLength; voicedMs = candidateMs; silenceMs = 0;
      interrupt('microphone'); status('hearing you…'); return;
    }
    recording.push(pcm); sampleCount += pcm.length;
    if (voiced) { voicedMs += ms; silenceMs = 0; } else silenceMs += ms;
    if (silenceMs >= settings.silence_ms || sampleCount >= context.sampleRate * settings.max_seconds) finish();
  }

  async function stop() {
    enabled = false; starting = false; lifecycle++; pending = []; resetCapture();
    await interrupt('voice_stopped');
    if (stream) stream.getTracks().forEach(t => t.stop());
    if (microphone) { microphone.port.onmessage = null; microphone.disconnect(); }
    if (source) source.disconnect(); if (mute) mute.disconnect();
    if (context && context.state !== 'closed') await context.close();
    stream = source = microphone = mute = context = null;
    phase = 'off'; toggle.textContent = 'start voice'; toggle.disabled = box.disabled; status('voice is off');
  }
  window.stopLiveVoice = stop;
  async function loadStyle() {
    const values = await (await fetch('/live-voice/settings')).json();
    document.getElementById('kyutaiStyle').value = values.style || 'calm';
  }
  loadStyle().catch(e => sys('Voice settings: ' + e.message));
  document.getElementById('kyutaiStyle').onchange = async event => {
    const style = event.target.value;
    try {
      await stop();
      const result = await post('/live-voice/style', {style});
      if (result.error) throw new Error(result.error);
      sys('Delivery changed. Start voice to continue.');
    } catch (e) { sys('Delivery: ' + e.message); await loadStyle(); }
  };
  toggle.onclick = async () => {
    if (enabled || starting) { await stop(); return; }
    if (!navigator.mediaDevices || !window.AudioWorkletNode) { sys('This browser needs microphone and AudioWorklet support; use current Chrome, Edge or Firefox on localhost.'); return; }
    starting = true; const token = ++lifecycle; toggle.textContent = 'stop voice'; status('opening microphone…');
    try {
      settings = await (await fetch('/live-voice/settings')).json();
      const captured = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}});
      if (token !== lifecycle) { captured.getTracks().forEach(t => t.stop()); return; }
      stream = captured; context = new AudioContext(); await context.resume();
      phase = 'warming'; status('loading voice and hearing models… first use may download them');
      const result = await post('/live-voice/warmup');
      if (token !== lifecycle) return;
      if (result.error) throw new Error(result.error);
      await context.audioWorklet.addModule('/voice-worklet.js');
      microphone = new AudioWorkletNode(context, 'parlor-microphone'); source = context.createMediaStreamSource(stream);
      mute = context.createGain(); mute.gain.value = 0; source.connect(microphone); microphone.connect(mute); mute.connect(context.destination);
      microphone.port.onmessage = event => capture(event.data);
      stream.getTracks().forEach(track => track.onended = () => { if (enabled) stop(); });
      enabled = true; starting = false; resetCapture(); phase = 'listening'; status('listening');
    } catch (e) { if (token === lifecycle) { sys('Voice: ' + e.message); await stop(); } }
  };
  window.addEventListener('pagehide', () => {
    if (stream) stream.getTracks().forEach(t => t.stop());
    if (currentJob) navigator.sendBeacon('/live-voice/delivery', new Blob([JSON.stringify({job: currentJob, completed, partial: !!player, reason: 'page_closed'})], {type: 'application/json'}));
    navigator.sendBeacon('/live-voice/interrupt', new Blob(['{}'], {type: 'application/json'}));
  });
})();
