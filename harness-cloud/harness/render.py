"""Модули 9 и 10 (рендер): точная нарезка, кроп 9:16 по траектории лица, вшивание ASS.

Выход: H.264 (High, yuv420p) + AAC, 1080×1920, 30 fps, MP4.
Нарезка — декодирование с точным seek (-ss после -i), поэтому аудио и видео не расходятся.
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import config, tools
from .faces import CropPlan, ffmpeg_crop_expr
from .tools import ToolError


def render_clip(src: Path, start: float, duration: float, plan: CropPlan | None,
                ass_file: Path | None, out: Path, preset_key: str,
                cancel: threading.Event) -> dict:
    preset = config.EXPORT_PRESETS.get(preset_key, config.EXPORT_PRESETS["tiktok"])
    out.parent.mkdir(parents=True, exist_ok=True)
    filters: list[str] = []
    if plan is not None:
        x = ffmpeg_crop_expr(plan.keys, 1)
        y = ffmpeg_crop_expr(plan.keys, 2)
        filters.append(f"crop={plan.crop_w}:{plan.crop_h}:'{x}':'{y}'")
    else:
        filters.append("crop=ih*9/16:ih:(iw-ih*9/16)/2:0")
    filters.append(f"scale={config.OUT_W}:{config.OUT_H}:flags=lanczos")
    filters.append(f"fps={config.OUT_FPS}")
    filters.append("format=yuv420p")
    if ass_file is not None:
        # Файл лежит в cwd процесса, поэтому путь без экранирования.
        filters.append(f"ass={ass_file.name}")

    cmd = [
        tools.ffmpeg_bin(), "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-i", str(src),
        "-t", f"{duration:.3f}",
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "medium", "-crf", str(preset["crf"]),
        "-maxrate", preset["video_bitrate"], "-bufsize", "2M",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(config.OUT_FPS),
        "-c:a", "aac", "-b:a", preset["audio_bitrate"], "-ac", "2", "-ar", "48000",
        "-movflags", "+faststart",
        str(out.name),
    ]
    cwd = out.parent
    # Запуск с cwd = папка клипа, чтобы фильтр ass видел файл по короткому имени.
    import subprocess, time
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.time() + 900
    while True:
        try:
            _, err = proc.communicate(timeout=0.3)
            break
        except subprocess.TimeoutExpired:
            if cancel.is_set():
                proc.kill()
                proc.communicate()
                raise tools.StepCancelled()
            if time.time() > deadline:
                proc.kill()
                proc.communicate()
                raise ToolError("Рендер клипа занял слишком много времени")
    if proc.returncode != 0:
        raise ToolError("ffmpeg не смог отрендерить клип: " + err.decode("utf-8", "replace")[-400:])
    return verify(out)


def verify(path: Path) -> dict:
    info = tools.probe(path)
    return {
        "width": info["width"], "height": info["height"],
        "duration": round(info["duration"], 3),
        "has_audio": info["has_audio"], "has_video": info["has_video"],
        "ok": (info["width"], info["height"]) == (config.OUT_W, config.OUT_H)
              and abs(info["duration"] - config.CLIP_LEN) <= config.CLIP_TOL
              and info["has_audio"],
    }


def make_thumb(video: Path, out: Path) -> None:
    # 3.2 с — уже после исчезновения хука (он на экране первые 2.8 с), бейджи карточки не перекрываются.
    tools.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-ss", "3.2", "-i", str(video),
               "-frames:v", "1", "-vf", "scale=360:-2", str(out)])
