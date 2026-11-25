"""Общие константы и пути приложения."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "Harness Cloud"
APP_VERSION = "2.5.0"

# Выходной формат клипов (спецификация).
OUT_W = 1080
OUT_H = 1920
# Форматы кадра: ключ → (ширина, высота). По умолчанию вертикальный 9:16.
ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "4:3": (1440, 1080), "1:1": (1080, 1080)}
DEFAULT_ASPECT = "9:16"


def render_workers() -> int:
    """Сколько клипов рендерить параллельно (HARNESS_RENDER_WORKERS или по числу ядер)."""
    import os
    env = os.environ.get("HARNESS_RENDER_WORKERS", "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    return max(1, min(3, (os.cpu_count() or 2)))


def out_size(aspect: str | None, quality: str | None = None) -> tuple[int, int]:
    """Размер кадра: короткая сторона = выбранное качество, соотношение сторон — из формата кадра."""
    aw, ah = (int(x) for x in (aspect or DEFAULT_ASPECT).split(":"))
    short = QUALITIES.get(quality or DEFAULT_QUALITY, QUALITIES[DEFAULT_QUALITY])
    if aw < ah:
        w, h = short, short * ah / aw
    elif aw > ah:
        w, h = short * aw / ah, short
    else:
        w = h = short
    return _even(w), _even(h)


def _even(x: float) -> int:
    return int(round(x / 2) * 2)  # кодек H.264 требует чётные размеры


# Скорость рендера по умолчанию: пикселей×кадров в секунду видео, которые кодируются за секунду
# (замер: клип 1080×1920, 30 fps, 30 с — около 20 с на двух ядрах). Уточняется по фактическим рендерам.
RENDER_SPEED_DEFAULT = 9.0e7


def estimate_seconds(count: int, quality: str | None, fps: int, aspect: str | None,
                     clip_len: float, workers: int, speed: float) -> float:
    """Оценка времени рендера клипов: батчами по числу параллельных рабочих."""
    w, h = out_size(aspect, quality)
    per_clip = (w * h * fps * clip_len) / max(speed, 1.0)
    batches = -(-count // max(workers, 1))  # округление вверх
    return batches * per_clip


def parse_fps(value) -> int | None:
    """Частота кадров из запроса: целое от FPS_MIN до FPS_MAX, иначе None."""
    try:
        fps = int(float(value))
    except (TypeError, ValueError):
        return None
    return fps if FPS_MIN <= fps <= FPS_MAX else None


# Качество: короткая сторона кадра в пикселях.
QUALITIES = {"480p": 480, "720p": 720, "1080p": 1080, "2k": 1440, "4k": 2160}
QUALITY_LABELS = {"480p": "480p — экономия места, быстрый экспорт", "720p": "720p — HD",
                  "1080p": "1080p — Full HD", "2k": "2K — 1440p, повышенная детализация",
                  "4k": "4K — 2160p, рендер заметно дольше"}
DEFAULT_QUALITY = "1080p"
FPS_MIN, FPS_MAX = 20, 120
FPS_CHOICES = [20, 24, 25, 30, 48, 50, 60, 90, 120]
DEFAULT_FPS = 30
LOUDNESS_LUFS = -14     # целевая громкость звука клипа (стандарт платформ коротких видео)
OUT_FPS = DEFAULT_FPS
CLIP_LEN = 30.0          # секунд
CLIP_TOL = 0.5           # допуск ± секунд
MIN_CLIPS = 5
MAX_CLIPS = 10

CONTENT_TYPES = {
    "podcast": "Подкаст / разговор",
    "game": "Стрим / Игра",
    "general": "Общее",
    "parts": "Видео по частям",
}

# Видео по частям: видео режется подряд с начала на части выбранной длины, без выбора лучших моментов.
CLIP_LENS = (30, 45, 60, 90, 120, 150, 180)   # выбор длины клипа (сек) для всех типов контента
DEFAULT_CLIP_LEN = 30
PART_MIN = 30.0
PART_MAX = 180.0


def clamp_clip_len(value) -> float:
    """Длина клипа или части в секундах: число из PART_MIN..PART_MAX, иначе значение по умолчанию."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = float(DEFAULT_CLIP_LEN)
    return min(PART_MAX, max(PART_MIN, v))

# Пресеты экспорта: битрейт видео и аудио.
EXPORT_PRESETS = {
    "tiktok": {"label": "TikTok", "video_bitrate": "6M", "audio_bitrate": "160k", "crf": 20},
    "shorts": {"label": "YouTube Shorts", "video_bitrate": "8M", "audio_bitrate": "192k", "crf": 18},
    "reels": {"label": "Instagram Reels", "video_bitrate": "5M", "audio_bitrate": "128k", "crf": 21},
}

# Стили субтитров: шрифт, цвет подсветки (ASS BGR), позиция (MarginV от низа).
# Пресеты субтитров в духе CapCut: жирный шрифт, толстая чёрная обводка, пословная подсветка.
# highlight — цвет уже произнесённого слова (ASS PrimaryColour), base — цвет ещё не произнесённого.
# pop — включает «всплеск» каждого слова (масштаб 118% → 100%).
SUBTITLE_STYLES = {
    "capcut": {"label": "CapCut: белый + жёлтое слово", "font": "Inter", "highlight": "&H0000FFFF&",
               "base": "&H00FFFFFF&", "outline": "&H00000000&", "size": 104, "outline_w": 10,
               "shadow": 3, "pop": True},
    "violet": {"label": "Фиолетовый", "font": "Inter", "highlight": "&H00FF8A5B&",
               "base": "&H00FFFFFF&", "outline": "&H00000000&", "size": 100, "outline_w": 9,
               "shadow": 2, "pop": False},
    "yellow": {"label": "Жёлтый", "font": "Inter", "highlight": "&H0000E5FF&",
               "base": "&H00FFFFFF&", "outline": "&H00000000&", "size": 100, "outline_w": 9,
               "shadow": 2, "pop": False},
    "neon": {"label": "Неон: голубое слово", "font": "Inter", "highlight": "&H00FFFF00&",
             "base": "&H00FFFFFF&", "outline": "&H00201000&", "size": 100, "outline_w": 9,
             "shadow": 0, "pop": True},
    "white": {"label": "Белый минимал", "font": "Inter", "highlight": "&H00FFFFFF&",
              "base": "&H00D9D9D9&", "outline": "&H00000000&", "size": 92, "outline_w": 6,
              "shadow": 0, "pop": False},
}
DEFAULT_SUBTITLE_STYLE = "capcut"

# Положение субтитров: верх, центр или низ кадра. Перетаскивание маркера в редакторе важнее пресета.
SUB_PLACES = {"bottom": "Внизу", "center": "По центру", "top": "Вверху"}
DEFAULT_SUB_PLACE = "bottom"


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
BUNDLED_WHISPER_DIR = MODELS_DIR / "whisper"  # модели Whisper в сборке: работают без интернета
DATA_DIR = _data_dir()
PROJECTS_DIR = DATA_DIR / "projects"
WHISPER_DIR = DATA_DIR / "whisper"
SETTINGS_FILE = DATA_DIR / "settings.json"
CALIBRATION_FILE = DATA_DIR / "calibration.json"


def offline_mode() -> bool:
    """Офлайн-режим из настроек: без обращения к сети (ИИ-заголовки и загрузка по ссылке отключены)."""
    try:
        return bool(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("offline"))
    except (OSError, ValueError, AttributeError):
        return False  # скорость рендера, измеренная на этой машине

for _p in (DATA_DIR, PROJECTS_DIR, WHISPER_DIR):
    _p.mkdir(parents=True, exist_ok=True)

FONTS_DIR = BASE_DIR / "fonts"            # встроенные шрифты субтитров (OFL), см. fonts/LICENSES.txt
USER_FONTS_DIR = DATA_DIR / "fonts"       # шрифты, загруженные пользователем
SUB_EFFECTS = {"none": "Без эффекта", "fade": "Плавное появление", "slide": "Выезд снизу",
               "rise": "Подъём с проявлением", "bounce": "Пружина", "glow": "Свечение",
               "zoom": "Приближение", "drop": "Падение",
               "pop": "Всплеск слов"}
