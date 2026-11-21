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
from .tools import StepCancelled, ToolError

MODELS = ("tiny", "base", "small", "medium")

_model_cache: dict[str, object] = {}


WHISPER_SIZES = ("tiny", "base", "small", "medium")


def model_available(name: str) -> bool:
    """Модель есть локально: встроена в сборку или уже скачана в папку данных."""
    if (config.BUNDLED_WHISPER_DIR / name / "model.bin").exists():
        return True
    return config.WHISPER_DIR.is_dir() and any(config.WHISPER_DIR.glob(f"*faster-whisper-{name}*"))


def installed_models() -> list[str]:
    return [m for m in WHISPER_SIZES if model_available(m)]


def resolve_model(name: str) -> str:
    """В офлайн-режиме, если выбранной модели нет, берётся установленная (предпочтительно base)."""
    if not config.offline_mode() or model_available(name):
        return name
    have = installed_models()
    if not have:
        return name  # дальше понятная ошибка загрузки
    return "base" if "base" in have else have[-1]


def _load_model(name: str):
    if name in _model_cache:
        return _model_cache[name]
    from faster_whisper import WhisperModel
    bundled = config.BUNDLED_WHISPER_DIR / name
    local = model_available(name)
    offline = config.offline_mode()
    if offline and not local:
        have = ", ".join(installed_models()) or "нет"
        raise ToolError(f"Модель Whisper «{name}» не установлена. Для офлайн-работы доступны: {have}. "
                        "Выберите установленную модель или выключите офлайн-режим.")
    if (bundled / "model.bin").exists():
        source, kwargs = str(bundled), {}
    else:
        source, kwargs = name, {"download_root": str(config.WHISPER_DIR)}
    # local_files_only: без сети, если модель уже локально или включён офлайн-режим
    model = WhisperModel(source, device="cpu", compute_type="int8",
                         local_files_only=local or offline, **kwargs)
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
    model_name = resolve_model(model_name)
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
