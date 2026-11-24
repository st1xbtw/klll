"""Выбор кодировщика видео: процессор (x264) или видеокарта (NVENC, QSV, AMF).

Видеокарта проверяется пробным кодированием 0.2 с при первом обращении и кешируется.
Если кодировщика нет или пробный запуск упал, выбирается процессор: рендер не ломается."""
from __future__ import annotations

import subprocess
import threading

from . import tools
from .winproc import hidden_kwargs

ENCODERS = {
    "cpu": ("libx264", "Процессор (x264)"),
    "nvenc": ("h264_nvenc", "NVIDIA (NVENC)"),
    "qsv": ("h264_qsv", "Intel (Quick Sync)"),
    "amf": ("h264_amf", "AMD (AMF)"),
}
GPU_ORDER = ("nvenc", "qsv", "amf")
_cache: dict[str, bool] = {}
_lock = threading.Lock()


def available(name: str) -> bool:
    if name == "cpu":
        return True
    if name not in ENCODERS:
        return False
    with _lock:
        if name in _cache:
            return _cache[name]
    ok = False
    try:
        proc = subprocess.run(
            [tools.ffmpeg_bin(), "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
             "color=c=black:s=256x256:d=0.2", "-c:v", ENCODERS[name][0], "-f", "null", "-"],
            capture_output=True, timeout=20, **hidden_kwargs())
        ok = proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    with _lock:
        _cache[name] = ok
    return ok


def resolve(choice: str | None) -> str:
    """auto — лучшая доступная видеокарта, иначе процессор. Недоступный выбор — процессор."""
    c = choice or "auto"
    if c == "auto":
        for name in GPU_ORDER:
            if available(name):
                return name
        return "cpu"
    return c if c in ENCODERS and available(c) else "cpu"


def status() -> dict:
    """Что доступно на этой машине, для интерфейса."""
    return {name: {"title": title, "available": available(name)} for name, (_, title) in ENCODERS.items()}


def video_args(name: str, crf: int, maxrate: str, bufsize: str, fps: int) -> list[str] | None:
    """Аргументы видеокодека для видеокарты. Для процессора возвращает None (тогда используется x264)."""
    common = ["-maxrate", maxrate, "-bufsize", bufsize, "-profile:v", "high",
              "-pix_fmt", "yuv420p", "-r", str(fps)]
    if name == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(crf), "-b:v", "0", *common]
    if name == "qsv":
        return ["-c:v", "h264_qsv", "-global_quality", str(crf), *common]
    if name == "amf":
        return ["-c:v", "h264_amf", "-rc", "vbr_peak", "-qp_i", str(crf), "-qp_p", str(crf), *common]
    return None
