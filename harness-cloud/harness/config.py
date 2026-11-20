"""Общие константы и пути приложения."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Harness Cloud"
APP_VERSION = "1.0.0"

# Выходной формат клипов (спецификация).
OUT_W = 1080
OUT_H = 1920
# Форматы кадра: ключ → (ширина, высота). По умолчанию вертикальный 9:16.
ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "4:3": (1440, 1080), "1:1": (1080, 1080)}
DEFAULT_ASPECT = "9:16"


def out_size(aspect: str | None) -> tuple[int, int]:
    return ASPECTS.get(aspect or DEFAULT_ASPECT, ASPECTS[DEFAULT_ASPECT])
OUT_FPS = 30
CLIP_LEN = 30.0          # секунд
CLIP_TOL = 0.5           # допуск ± секунд
MIN_CLIPS = 5
MAX_CLIPS = 10

CONTENT_TYPES = {
    "podcast": "Подкаст / разговор",
    "game": "Стрим / Игра",
    "general": "Общее",
}

# Пресеты экспорта: битрейт видео и аудио.
EXPORT_PRESETS = {
    "tiktok": {"label": "TikTok", "video_bitrate": "6M", "audio_bitrate": "160k", "crf": 20},
    "shorts": {"label": "YouTube Shorts", "video_bitrate": "8M", "audio_bitrate": "192k", "crf": 18},
    "reels": {"label": "Instagram Reels", "video_bitrate": "5M", "audio_bitrate": "128k", "crf": 21},
}

# Стили субтитров: шрифт, цвет подсветки (ASS BGR), позиция (MarginV от низа).
SUBTITLE_STYLES = {
    "violet": {"label": "Фиолетовый", "font": "Segoe UI", "highlight": "&H00FF8A5B&", "position": "lower"},
    "yellow": {"label": "Жёлтый", "font": "Arial", "highlight": "&H0000E5FF&", "position": "lower"},
    "white": {"label": "Белый минимал", "font": "Arial", "highlight": "&H00FFFFFF&", "position": "center"},
}


def _base_dir() -> Path:
    """Папка с кодом; в PyInstaller-сборке — каталог распаковки."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    """Пользовательская папка данных (проекты, модели, настройки)."""
    env = os.environ.get("HARNESS_DATA_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "HarnessCloud"


BASE_DIR = _base_dir()
UI_DIR = BASE_DIR / "ui"
MODELS_DIR = BASE_DIR / "models"          # встроенные ресурсы (каскад Haar)
DATA_DIR = _data_dir()
PROJECTS_DIR = DATA_DIR / "projects"
WHISPER_DIR = DATA_DIR / "whisper"
SETTINGS_FILE = DATA_DIR / "settings.json"

for _p in (DATA_DIR, PROJECTS_DIR, WHISPER_DIR):
    _p.mkdir(parents=True, exist_ok=True)
