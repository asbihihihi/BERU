"""Streaming Silero VAD recorder for browser PCM microphone audio."""

from __future__ import annotations

from collections import deque
import io
import wave
from dataclasses import dataclass
from typing import Callable

import numpy as np
import torch


SAMPLE_RATE = 16_000


def initialize_vad():
    """Reuse the Silero VAD model used by the original desktop voice loop."""
    torch.set_num_threads(1)
    model, _ = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
    model.eval()
    return model


@dataclass(frozen=True)
class VADResult:
    recording_started: bool = False
    audio: bytes | None = None


class VoiceRecorder:
    """Keeps only an in-memory utterance and completes it after real silence."""

    def __init__(
        self,
        vad: object,
        threshold: float = 0.55,
        silence_timeout: float = 0.85,
        min_record_seconds: float = 0.8,
        sample_rate: int = SAMPLE_RATE,
        scorer: Callable[[np.ndarray], float] | None = None,
    ):
        self.vad = vad
        self.threshold = threshold
        self.silence_timeout = silence_timeout
        self.min_record_seconds = min_record_seconds
        self.sample_rate = sample_rate
        self.scorer = scorer
        self.reset()

    def reset(self) -> None:
        if hasattr(self.vad, "reset_states"):
            self.vad.reset_states()
        self._pre: deque[np.ndarray] = deque(maxlen=16)
        self._chunks: list[np.ndarray] = []
        self._recording = False
        self._elapsed = 0.0
        self._silence = 0.0

    @property
    def recording(self) -> bool:
        return self._recording

    def feed(self, pcm16: bytes) -> VADResult:
        if len(pcm16) % 2:
            raise ValueError("PCM 16-bit tidak valid")
        samples = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        if not len(samples):
            return VADResult()
        speech = self._score(samples) >= self.threshold
        duration = len(samples) / self.sample_rate

        if not self._recording:
            self._pre.append(samples.copy())
            if not speech:
                return VADResult()
            self._recording = True
            self._chunks.extend(self._pre)
            self._elapsed = sum(len(chunk) for chunk in self._chunks) / self.sample_rate
            self._silence = 0.0
            return VADResult(recording_started=True)

        self._chunks.append(samples.copy())
        self._elapsed += duration
        self._silence = 0.0 if speech else self._silence + duration
        if self._elapsed >= self.min_record_seconds and self._silence >= self.silence_timeout:
            return VADResult(audio=self._wav_bytes())
        return VADResult()

    def _score(self, samples: np.ndarray) -> float:
        if self.scorer:
            return float(self.scorer(samples))
        with torch.no_grad():
            return float(self.vad(torch.from_numpy(samples), self.sample_rate).item())

    def _wav_bytes(self) -> bytes:
        pcm = np.clip(np.concatenate(self._chunks), -1, 1)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes((pcm * 32767).astype("<i2").tobytes())
        self.reset()
        return output.getvalue()
