"""Баннер в середине клипа: кадр останавливается, поверх него показывается картинка, затем видео продолжается.

Работает как постобработка готового клипа: субтитры и значки уже вшиты, поэтому стоп-кадр их сохраняет.
Звук на время баннера заменяется тишиной. Картинка масштабируется по ширине кадра с сохранением пропорций
и центрируется по вертикали."""
from __future__ import annotations

import threading
from pathlib import Path

from . import config, tools
from .render import _encode_args, _run_ffmpeg

BANNER_SEC = 3.0          # длительность по умолчанию; задаётся настройкой, допустимо 0.5–600 с
MAX_BANNER_SEC = 600.0
MIN_BANNER_SEC = 0.5


def clamp_banner_sec(value, default: float = BANNER_SEC) -> float:
    try:
        return round(max(MIN_BANNER_SEC, min(MAX_BANNER_SEC, float(value))), 2)
    except (TypeError, ValueError):
        return default
MIN_CLIP = 8.0            # короче этого клипа баннер не вставляем, иначе он закроет весь ролик


def banner_position(duration: float, fraction: float = 0.5) -> float:
    """Точка вставки: по умолчанию ровно середина клипа (15 с у ролика 30 с)."""
    return round(max(1.0, min(duration - 1.0, duration * max(0.1, min(0.9, fraction)))), 3)


def banner_filter(at: float, banner_sec: float, out_w: int, out_h: int, fps: int) -> str:
    """Фильтрграф: [0:v]/[0:a] — клип, [1:v] — картинка баннера. Итог: [v] и [a]."""
    end_of_hold = at + 1.0 / fps
    return (
        f"[1:v]scale={out_w}:-2:flags=lanczos,format=rgba[bn];"
        f"[0:v]split=3[va][vb][vc];"
        f"[va]trim=0:{at:.3f},setpts=PTS-STARTPTS[pa];"
        f"[vb]trim={at:.3f}:{end_of_hold:.3f},setpts=PTS-STARTPTS,"
        f"loop=loop=-1:size=1:start=0,trim=duration={banner_sec:.3f},setpts=PTS-STARTPTS,"
        f"format=yuv420p,fps={fps}[hold];"
        f"[hold][bn]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p[pb];"
        f"[vc]trim=start={at:.3f},setpts=PTS-STARTPTS[pc];"
        f"[pa][pb][pc]concat=n=3:v=1:a=0[v];"
        f"[0:a]asplit=2[aa][ab];"
        f"[aa]atrim=0:{at:.3f},asetpts=PTS-STARTPTS[xa];"
        f"anullsrc=r=48000:cl=stereo,atrim=duration={banner_sec:.3f},asetpts=PTS-STARTPTS[xs];"
        f"[ab]atrim=start={at:.3f},asetpts=PTS-STARTPTS[xc];"
        f"[xa][xs][xc]concat=n=3:v=0:a=1[a]"
    )


def add_banner(clip: Path, banner: Path, out: Path, duration: float, out_w: int, out_h: int,
               fps: int, cancel: threading.Event, fraction: float = 0.5,
               banner_sec: float = BANNER_SEC, encoder: str = "cpu",
               bitrate: str | None = None) -> float:
    """Вставляет баннер в клип. Возвращает время вставки; при короткой длительности ничего не делает."""
    if duration < MIN_CLIP:
        raise tools.ToolError("Клип слишком короткий для баннера")
    banner_sec = clamp_banner_sec(banner_sec)
    at = banner_position(duration, fraction)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [tools.ffmpeg_bin(), "-y", "-v", "error",
           "-i", str(clip.resolve()), "-loop", "1", "-i", str(banner.resolve()),
           "-filter_complex", banner_filter(at, banner_sec, out_w, out_h, fps),
           "-map", "[v]", "-map", "[a]",
           *_encode_args("tiktok", False, out_w, out_h, fps, encoder, bitrate), out.name]
    _run_ffmpeg(cmd, out.parent, cancel, "баннер")
    return at
