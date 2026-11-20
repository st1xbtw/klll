"""Модуль 3: извлечение аудио в WAV 16 кГц моно и чтение его сэмплов."""
from __future__ import annotations

import threading
import wave
from pathlib import Path

import numpy as np

from . import tools

SR = 16000


def extract_wav(src: Path, dest: Path, cancel: threading.Event) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tools.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-i", str(src),
               "-vn", "-ac", "1", "-ar", str(SR), "-acodec", "pcm_s16le", str(dest)],
              cancel=cancel)
    return dest


def read_samples(path: Path) -> np.ndarray:
    """Возвращает float32 сэмплы в диапазоне [-1, 1]."""
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return data
