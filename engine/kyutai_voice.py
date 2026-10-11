"""Kyutai TTS 1.6B adapter using released expressive voice embeddings.

Models remain in the speech sidecar. Windows uses the PyTorch reference
implementation with torch.compile disabled; no system/WSL installation.
"""
from __future__ import annotations
import os
import re
import time

STYLES = {
    "calm": "expresso/ex04-ex02_calm_001_channel2_336s.wav",
    "desire": "expresso/ex04-ex02_desire_001_channel2_694s.wav",
    "happy": "expresso/ex04-ex02_happy_001_channel2_140s.wav",
    "neutral": "expresso/ex01-ex02_default_001_channel2_198s.wav",
}


class KyutaiVoice:
    def __init__(self, device="cuda", offline=False):
        os.environ.setdefault("NO_TORCH_COMPILE", "1")
        if offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
        from moshi.models.loaders import CheckpointInfo
        from moshi.models.tts import TTSModel
        checkpoint = CheckpointInfo.from_hf_repo("kyutai/tts-1.6b-en_fr")
        self.model = TTSModel.from_checkpoint_info(checkpoint, n_q=32, temp=.6, device=device)
        self.sample_rate = int(self.model.mimi.sample_rate)
        self.conditions = {}

    def synthesize(self, text, style="calm", voice=None, on_audio=None):
        import numpy as np
        import torch
        if style not in STYLES:
            raise ValueError("Kyutai style must be calm, desire, happy or neutral.")
        selected = voice or STYLES[style]
        if selected not in self.conditions:
            path = self.model.get_voice_path(selected)
            self.conditions[selected] = self.model.make_condition_attributes([path], cfg_coef=2.)
        text = re.sub(r"\[(?:laugh|chuckle|sigh|gasp|cough|clear throat|sniff)\]", "", text).strip()
        entries = self.model.prepare_script([text], padding_between=1)
        pieces = []
        started = time.monotonic()
        first_audio = None
        pending = []
        pending_samples = 0
        def frame_ready(frame):
            nonlocal first_audio, pending_samples
            if (frame != -1).all():
                pcm = self.model.mimi.decode(frame[:, 1:, :]).detach().cpu().numpy()[0, 0]
                if first_audio is None:
                    first_audio = time.monotonic() - started
                pcm = np.clip(pcm, -1, 1)
                if on_audio is None:
                    pieces.append(pcm)
                else:
                    pending.append(pcm)
                    pending_samples += len(pcm)
                    if pending_samples >= self.sample_rate * .48:
                        on_audio(np.concatenate(pending), self.sample_rate)
                        pending.clear(); pending_samples = 0
        with torch.inference_mode(), self.model.mimi.streaming(1):
            self.model.generate([entries], [self.conditions[selected]], on_frame=frame_ready)
        if on_audio is not None:
            if first_audio is None:
                raise RuntimeError("Kyutai produced no speech.")
            if pending:
                on_audio(np.concatenate(pending), self.sample_rate)
            return None, self.sample_rate, first_audio
        if not pieces:
            raise RuntimeError("Kyutai produced no speech.")
        return np.concatenate(pieces, axis=-1), self.sample_rate, first_audio
