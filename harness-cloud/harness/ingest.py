"""Модули 1–2: валидация ввода, загрузка по ссылке (yt-dlp), приём локального файла."""
from __future__ import annotations

import shutil
import threading
from pathlib import Path
from urllib.parse import urlparse

from . import tools
from .tools import StepCancelled, ToolError

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts", ".flv"}
MAX_UPLOAD_BYTES = 8 * 1024 ** 3   # 8 ГБ


def validate_url(url: str) -> str:
    url = (url or "").strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("Ссылка должна начинаться с http:// или https:// и содержать адрес сайта")
    return url


def validate_file(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_file():
        raise ValueError("Файл не найден")
    if p.suffix.lower() not in VIDEO_EXT:
        raise ValueError(f"Неподдерживаемый формат {p.suffix or '(без расширения)'}")
    if p.stat().st_size > MAX_UPLOAD_BYTES:
        raise ValueError("Файл больше 8 ГБ")
    info = tools.probe(p)
    if not info["has_video"] or info["duration"] <= 0:
        raise ValueError("В файле нет видеодорожки или длительность не определена")
    return p


def download(url: str, dest_dir: Path, cancel: threading.Event, progress) -> Path:
    """Скачивает видео через yt-dlp. progress(0..1, текст)."""
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover
        raise ToolError("Не установлен yt-dlp") from exc

    dest_dir.mkdir(parents=True, exist_ok=True)

    def hook(d):
        if cancel.is_set():
            raise StepCancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0.0
            progress(min(frac, 0.99), "Загрузка видео")
        elif d.get("status") == "finished":
            progress(1.0, "Загрузка завершена")

    ffdir = str(Path(tools.ffmpeg_bin()).parent)
    opts = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "ffmpeg_location": ffdir,
        "retries": 3,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            out = Path(ydl.prepare_filename(info))
            if out.suffix.lower() != ".mp4" and out.with_suffix(".mp4").exists():
                out = out.with_suffix(".mp4")
    except StepCancelled:
        raise
    except Exception as exc:  # yt-dlp бросает свои типы ошибок
        raise ToolError(f"Не удалось скачать видео: {str(exc)[:300]}") from exc
    if not out.exists():
        raise ToolError("yt-dlp не создал файл")
    return out


def copy_upload(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / ("source" + src.suffix.lower())
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest
