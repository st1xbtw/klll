"""Модули 9 и 10 (рендер): нарезка, кадрирование, вшивание ASS, склейка фрагментов.

Клип описан списком отрезков исходника: segments = [[s, e], ...], сумма длительностей = 30 с.
  * один отрезок — обычный путь: точная обрезка -ss/-t, кроп по лицу или вписывание с фоном;
  * несколько отрезков (склейка, вырезка внутри клипа) — каждый отрезок рендерится отдельно,
    затем склеивается concat, и поверх накладываются субтитры и хук.
Выход: H.264 (High, yuv420p) + AAC, 1080×1920, 30 fps, MP4.
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from . import config, tools
from .faces import CropPlan, ffmpeg_crop_expr
from .tools import ToolError


def _framing_chain(plan: CropPlan | None, framing: str, src_w: int, src_h: int,
                   out_w: int = config.OUT_W, out_h: int = config.OUT_H, fps: int = config.DEFAULT_FPS) -> str:
    """Фильтрграф от [0:v] до [v0]: нужный формат кадра (out_w×out_h), 30 fps, yuv420p."""
    if framing == "fit":
        # Фон — тот же кадр, растянутый на весь кадр и размытый; поверх — исходник целиком.
        return (f"[0:v]split=2[fa][fb];"
                f"[fa]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
                f"crop={out_w}:{out_h},boxblur=luma_radius=40:luma_power=2[bg];"
                f"[fb]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={fps},format=yuv420p[v0]")
    if plan is not None:
        x = ffmpeg_crop_expr(plan.keys, 1)
        y = ffmpeg_crop_expr(plan.keys, 2)
        crop = f"crop={plan.crop_w}:{plan.crop_h}:'{x}':'{y}'"
    else:
        crop = f"crop=ih*{out_w}/{out_h}:ih:(iw-ih*{out_w}/{out_h})/2:0"
    return (f"[0:v]{crop},scale={out_w}:{out_h}:flags=lanczos,"
            f"fps={fps},format=yuv420p[v0]")


def _run_ffmpeg(cmd: list[str], cwd: Path, cancel: threading.Event, what: str) -> None:
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.time() + 1200
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
                raise ToolError(f"{what}: превышено время рендера")
    if proc.returncode != 0:
        raise ToolError(f"{what}: ffmpeg завершился с ошибкой: " + err.decode("utf-8", "replace")[-400:])


def _scaled_bitrate(value: str, factor: float) -> str:
    """Битрейт пресета (например «6M») умножается на коэффициент разрешения и частоты кадров."""
    num, unit = float(value[:-1]), value[-1]
    return f"{max(0.5, round(num * factor * 2) / 2):g}{unit}"


def _encode_args(preset_key: str, fast: bool = False, out_w: int = config.OUT_W,
                 out_h: int = config.OUT_H, fps: int = config.DEFAULT_FPS) -> list[str]:
    preset = config.EXPORT_PRESETS.get(preset_key, config.EXPORT_PRESETS["tiktok"])
    if fast:  # промежуточные отрезки: быстрее и без потерь для последующей склейки
        return ["-c:v", "libx264", "-preset", "superfast", "-crf", "18", "-pix_fmt", "yuv420p",
                "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000"]
    # Битрейт пропорционален числу пикселей в секунду относительно 1080×1920 при 30 fps.
    factor = min(10.0, max(0.4, (out_w * out_h * fps) / (1080 * 1920 * 30)))
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(preset["crf"]),
            "-maxrate", _scaled_bitrate(preset["video_bitrate"], factor),
            "-bufsize", _scaled_bitrate("2M", factor),
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", preset["audio_bitrate"], "-ac", "2", "-ar", "48000",
            "-movflags", "+faststart"]


def _fontsdir(clip_dir: Path) -> str:
    """Опция fontsdir для фильтра ass: шрифты, скопированные в папку клипа (относительный путь)."""
    return ":fontsdir=fonts" if (clip_dir / "fonts").is_dir() else ""


def render_clip(src: Path, start: float, duration: float, plan: CropPlan | None,
                ass_file: Path | None, out: Path, preset_key: str, cancel: threading.Event,
                framing: str = "face", src_w: int = 0, src_h: int = 0,
                out_w: int = config.OUT_W, out_h: int = config.OUT_H, fps: int = config.DEFAULT_FPS) -> dict:
    """Один непрерывный отрезок. ass_file кладётся рядом с out (cwd), поэтому путь короткий."""
    out.parent.mkdir(parents=True, exist_ok=True)
    chain = _framing_chain(plan, framing, src_w, src_h, out_w, out_h, fps)
    if ass_file is not None:
        chain = chain[:-len("[v0]")] + f"[v0];[v0]ass={ass_file.name}{_fontsdir(out.parent)}[v]"
    else:
        chain = chain[:-len("[v0]")] + "[v0];[v0]null[v]"
    cmd = [tools.ffmpeg_bin(), "-y", "-v", "error",
           "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
           "-filter_complex", chain, "-map", "[v]", "-map", "0:a?",
           *_encode_args(preset_key, False, out_w, out_h, fps), out.name]
    _run_ffmpeg(cmd, out.parent, cancel, "рендер клипа")
    return verify(out, out_w, out_h, fps)


def render_segments(src: Path, segments: list[tuple[float, float]], plans: list[CropPlan | None],
                    framing: str, src_w: int, src_h: int, ass_file: Path | None, out: Path,
                    preset_key: str, cancel: threading.Event,
                    out_w: int = config.OUT_W, out_h: int = config.OUT_H, fps: int = config.DEFAULT_FPS) -> dict:
    """Несколько отрезков: каждый рендерится в промежуточный файл, затем склейка и субтитры."""
    work = out.parent / "parts"
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for i, ((s, e), plan) in enumerate(zip(segments, plans)):
        part = work / f"part_{i}.mp4"
        chain = _framing_chain(plan, framing, src_w, src_h, out_w, out_h, fps)[:-len("[v0]")] + "[v]"
        cmd = [tools.ffmpeg_bin(), "-y", "-v", "error",
               "-ss", f"{s:.3f}", "-i", str(src), "-t", f"{e - s:.3f}",
               "-filter_complex", chain, "-map", "[v]", "-map", "0:a?",
               *_encode_args("tiktok", True, out_w, out_h, fps), part.name]
        _run_ffmpeg(cmd, work, cancel, f"отрезок {i + 1}")
        parts.append(part)
    # Склейка и финальная кодировка (+ субтитры, если есть).
    n = len(parts)
    inputs: list[str] = []
    for p in parts:
        inputs += ["-i", str(p.resolve())]
    fc = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][ca]"
    if ass_file is not None:
        fc += f";[cv]ass={ass_file.name}{_fontsdir(out.parent)}[v]"
        vmap = "[v]"
    else:
        fc += ";[cv]null[v]"
        vmap = "[v]"
    cmd = [tools.ffmpeg_bin(), "-y", "-v", "error", *inputs,
           "-filter_complex", fc, "-map", vmap, "-map", "[ca]",
           *_encode_args(preset_key, False, out_w, out_h, fps), out.name]
    _run_ffmpeg(cmd, out.parent, cancel, "склейка клипа")
    for p in parts:
        p.unlink(missing_ok=True)
    try:
        work.rmdir()
    except OSError:
        pass
    return verify(out, out_w, out_h, fps)


def verify(path: Path, out_w: int = config.OUT_W, out_h: int = config.OUT_H,
           fps: int = config.DEFAULT_FPS) -> dict:
    info = tools.probe(path)
    return {
        "width": info["width"], "height": info["height"],
        "duration": round(info["duration"], 3), "fps": round(info["fps"], 2),
        "has_audio": info["has_audio"], "has_video": info["has_video"],
        "ok": (info["width"], info["height"]) == (out_w, out_h)
              and abs(info["fps"] - fps) <= 0.5
              and abs(info["duration"] - config.CLIP_LEN) <= config.CLIP_TOL
              and info["has_audio"],
    }


def make_thumb(video: Path, out: Path) -> None:
    # 3.2 с — уже после исчезновения хука (он на экране первые 2.8 с).
    tools.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-ss", "3.2", "-i", str(video),
               "-frames:v", "1", "-vf", "scale=360:-2", str(out)])
