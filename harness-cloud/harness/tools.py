"""Поиск внешних утилит (ffmpeg / ffprobe) и вызов команд."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import config


class StepCancelled(Exception):
    """Пользователь отменил задачу."""


class ToolError(RuntimeError):
    """Ошибка внешней утилиты."""


def _find(name: str) -> str:
    exe = name + (".exe" if os.name == "nt" else "")
    # 1) рядом с приложением (для сборки PyInstaller / поставки с ffmpeg)
    for base in (config.BASE_DIR / "bin", config.BASE_DIR):
        cand = base / exe
        if cand.exists():
            return str(cand)
    env = os.environ.get("FFMPEG_DIR")
    if env and (Path(env) / exe).exists():
        return str(Path(env) / exe)
    found = shutil.which(name)
    if not found:
        raise ToolError(f"Не найден {name}. Установите ffmpeg и добавьте его в PATH или задайте FFMPEG_DIR.")
    return found


def ffmpeg_bin() -> str:
    return _find("ffmpeg")


def ffprobe_bin() -> str:
    return _find("ffprobe")


def run(args: list[str], cancel=None, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Запуск процесса с возможностью отмены."""
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    import time
    start = time.time()
    while True:
        try:
            out, err = proc.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.communicate()
                raise StepCancelled()
            if timeout and time.time() - start > timeout:
                proc.kill()
                proc.communicate()
                raise ToolError("Превышено время выполнения процесса")
    result = subprocess.CompletedProcess(args, proc.returncode, out, err)
    if result.returncode != 0:
        tail = err.decode("utf-8", "replace")[-600:]
        raise ToolError(f"{Path(args[0]).name} завершился с ошибкой: {tail}")
    return result


def probe(path: str | Path) -> dict:
    """Возвращает длительность, размер видео и наличие аудио."""
    res = run([ffprobe_bin(), "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)])
    data = json.loads(res.stdout.decode("utf-8", "replace"))
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = float(data.get("format", {}).get("duration") or 0)
    return {
        "duration": dur,
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "has_video": v is not None,
        "has_audio": a is not None,
        "fps": _rate(v.get("avg_frame_rate") or v.get("r_frame_rate")) if v else 0.0,
    }


def _rate(text: str | None) -> float:
    """'30000/1001' → 29.97."""
    try:
        num, den = (text or "0/1").split("/")
        return float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0
