"""Баннер посреди клипа: кадр останавливается, поверх него играет баннер, затем видео продолжается.

Баннер может быть картинкой (стоит заданное число секунд) или видео (играет целиком, со своим звуком).
Работает как постобработка готового клипа: субтитры и значки уже вшиты, поэтому стоп-кадр их сохраняет.
Звук картинки-баннера — тишина; у видео-баннера звук его собственный."""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from . import config, tools
from .render import _encode_args, _run_ffmpeg
from .winproc import hidden_kwargs

BANNER_SEC = 3.0          # длительность картинки-баннера по умолчанию, 0.5–600 с
MAX_BANNER_SEC = 600.0
MIN_BANNER_SEC = 0.5
MIN_CLIP = 8.0            # короче этого клипа баннер не вставляем
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")
IMAGE_EXT = (".png", ".jpg", ".jpeg")


def clamp_banner_sec(value, default: float = BANNER_SEC) -> float:
    try:
        return round(max(MIN_BANNER_SEC, min(MAX_BANNER_SEC, float(value))), 2)
    except (TypeError, ValueError):
        return default


def banner_position(duration: float, fraction: float = 0.5) -> float:
    """Точка вставки: по умолчанию ровно середина клипа (15 с у ролика 30 с)."""
    return round(max(1.0, min(duration - 1.0, duration * max(0.1, min(0.9, fraction)))), 3)


def current_banner() -> Path | None:
    """Загруженный баннер: banner.png/jpg или banner.mp4/mov/webm/mkv в папке данных."""
    for path in sorted(config.DATA_DIR.glob("banner.*")):
        if path.suffix.lower() in VIDEO_EXT + IMAGE_EXT:
            return path
    return None


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXT


def probe(path: Path) -> dict:
    """Длительность, наличие видеодорожки и звука. Ошибка — ToolError, файл не подходит."""
    proc = subprocess.run([tools.ffprobe_bin(), "-v", "error", "-show_entries",
                           "format=duration:stream=codec_type", "-of", "json", str(path)],
                          capture_output=True, text=True, **hidden_kwargs())
    if proc.returncode != 0:
        raise tools.ToolError("Не удалось прочитать файл баннера")
    data = json.loads(proc.stdout or "{}")
    kinds = {s.get("codec_type") for s in data.get("streams", [])}
    try:
        duration = float(data.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {"duration": duration, "video": "video" in kinds, "audio": "audio" in kinds}


def banner_filter(at: float, hold: float, out_w: int, out_h: int, fps: int,
                  video_banner: bool = False, banner_audio: bool = False) -> str:
    """Фильтрграф: [0:v]/[0:a] — клип, [1] — баннер. Итог: [v] и [a]."""
    end_of_hold = at + 1.0 / fps
    return (
        f"[1:v]scale={out_w}:-2:flags=lanczos,format=rgba[bn];"
        f"[0:v]split=3[va][vb][vc];"
        f"[va]trim=0:{at:.3f},setpts=PTS-STARTPTS[pa];"
        f"[vb]trim={at:.3f}:{end_of_hold:.3f},setpts=PTS-STARTPTS,"
        f"loop=loop=-1:size=1:start=0,trim=duration={hold:.3f},setpts=PTS-STARTPTS,"
        f"format=yuv420p,fps={fps}[hold];"
        f"[hold][bn]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p[pb];"
        f"[vc]trim=start={at:.3f},setpts=PTS-STARTPTS[pc];"
        f"[pa][pb][pc]concat=n=3:v=1:a=0[v];"
        f"[0:a]asplit=2[aa][ab];"
        f"[aa]atrim=0:{at:.3f},asetpts=PTS-STARTPTS[xa];"
        + (f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=duration={hold:.3f},"
           f"asetpts=PTS-STARTPTS[xs];" if banner_audio else
           f"anullsrc=r=48000:cl=stereo,atrim=duration={hold:.3f},asetpts=PTS-STARTPTS[xs];")
        + f"[ab]atrim=start={at:.3f},asetpts=PTS-STARTPTS[xc];"
        f"[xa][xs][xc]concat=n=3:v=0:a=1[a]"
    )


def add_banner(clip: Path, banner: Path, out: Path, duration: float, out_w: int, out_h: int,
               fps: int, cancel: threading.Event, fraction: float = 0.5,
               banner_sec: float = BANNER_SEC, encoder: str = "cpu",
               bitrate: str | None = None) -> dict:
    """Вставляет баннер в клип. Возвращает {"at": точка вставки, "hold": сколько секунд добавлено}."""
    if duration < MIN_CLIP:
        raise tools.ToolError("Клип слишком короткий для баннера")
    at = banner_position(duration, fraction)
    out.parent.mkdir(parents=True, exist_ok=True)
    if is_video(banner):
        info = probe(banner)
        if not info["video"] or info["duration"] <= 0:
            raise tools.ToolError("Видео-баннер не содержит картинки")
        hold = round(info["duration"], 3)
        banner_audio = info["audio"]
        banner_input = ["-i", str(banner.resolve())]
    else:
        hold = clamp_banner_sec(banner_sec)
        banner_audio = False
        banner_input = ["-loop", "1", "-i", str(banner.resolve())]
    cmd = [tools.ffmpeg_bin(), "-y", "-v", "error",
           "-i", str(clip.resolve()), *banner_input,
           "-filter_complex", banner_filter(at, hold, out_w, out_h, fps, is_video(banner), banner_audio),
           "-map", "[v]", "-map", "[a]",
           *_encode_args("tiktok", False, out_w, out_h, fps, encoder, bitrate), out.name]
    _run_ffmpeg(cmd, out.parent, cancel, "баннер")
    return {"at": at, "hold": hold}
