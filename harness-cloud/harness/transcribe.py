"""Модуль 4: транскрибация через faster-whisper с таймкодами по словам.

Fallback: если модель не загрузилась (нет сети, нет весов), возвращаем None и причину.
Пайплайн тогда продолжает работу без текста: клипы режутся и кадрируются,
субтитры и хук пропускаются, и это явно пишется в отчёт проекта.
Готовый транскрипт (JSON) можно передать вручную через override_path.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from . import config
from .tools import StepCancelled

MODELS = ("tiny", "base", "small", "medium")

_model_cache: dict[str, object] = {}


def _load_model(name: str):
    if name in _model_cache:
        return _model_cache[name]
    from faster_whisper import WhisperModel
    model = WhisperModel(name, device="cpu", compute_type="int8",
                         download_root=str(config.WHISPER_DIR))
    _model_cache[name] = model
    return model


def transcribe(wav: Path, model_name: str, cancel: threading.Event,
               progress: Callable[[float, str], None],
               override_path: Path | None = None) -> tuple[list[dict] | None, str | None]:
    """Возвращает (сегменты, причина_пропуска). Сегмент: {start,end,text,words:[{w,s,e}]}."""
    if override_path is not None and override_path.exists():
        data = json.loads(override_path.read_text(encoding="utf-8"))
        progress(1.0, "Транскрипт загружен из файла")
        return data.get("segments", data), None

    if model_name not in MODELS:
        model_name = "base"
    try:
        model = _load_model(model_name)
    except Exception as exc:  # нет сети / нет весов / нет библиотеки
        return None, f"Модель Whisper «{model_name}» недоступна: {str(exc)[:200]}"

    progress(0.05, f"Транскрибация (модель {model_name})")
    try:
        segs, info = model.transcribe(
            str(wav), language=None, vad_filter=True, word_timestamps=True,
            beam_size=1, condition_on_previous_text=False)
        total = max(info.duration, 1.0)
        out: list[dict] = []
        for seg in segs:
            if cancel.is_set():
                raise StepCancelled()
            words = [{"w": w.word.strip(), "s": float(w.start), "e": float(w.end)}
                     for w in (seg.words or []) if w.word.strip()]
            out.append({"start": float(seg.start), "end": float(seg.end),
                        "text": seg.text.strip(), "words": words})
            progress(min(0.05 + 0.95 * seg.end / total, 0.99), "Транскрибация")
    except StepCancelled:
        raise
    except Exception as exc:
        return None, f"Ошибка транскрибации: {str(exc)[:200]}"
    progress(1.0, "Транскрибация завершена")
    return out, None


def flatten_words(segments: list[dict]) -> list[dict]:
    words: list[dict] = []
    for seg in segments:
        words.extend(seg.get("words") or [])
    return sorted(words, key=lambda w: w["s"])
