from __future__ import annotations

import asyncio
import io
from pathlib import Path

from PIL import Image

from . import config
from .common import fit_font_size, find_font, make_tint, parse_hex, region_px

SIZE = 100


class WebmError(Exception):
    pass


async def _first_frame(src: Path) -> Image.Image | None:
    proc = await asyncio.create_subprocess_exec(
        config.FFMPEG, "-v", "error", "-c:v", "libvpx-vp9", "-i", str(src),
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if not out:
        return None
    return Image.open(io.BytesIO(out)).convert("RGBA")


def _esc_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", r"\:")


async def recolor_webm(src: Path, dst: Path, nick: str, color_hex: str) -> None:
    """Меняет только ник: фон и рисунок эмодзи остаются как были."""
    tint = make_tint(parse_hex(color_hex))
    x0, y0, x1, y1 = region_px(SIZE, SIZE)
    fsize = fit_font_size(nick, x1 - x0 - 2, y1 - y0 - 2)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    textfile = dst.with_suffix(".txt")
    textfile.write_text(nick, encoding="utf-8")

    # стираем старый ник заливкой цветом фона, который уже есть у эмодзи
    drawbox = ""
    frame = await _first_frame(src)
    if frame is not None:
        rgb = frame.convert("RGB")
        hist = rgb.crop((x0, y0, x1, y1)).getcolors(maxcolors=SIZE * SIZE) or [(0, (0, 0, 0))]
        bg = max(hist)[1]
        drawbox = (
            f"drawbox=x={x0}:y={y0}:w={x1 - x0}:h={y1 - y0}:"
            f"color=0x{bg[0]:02X}{bg[1]:02X}{bg[2]:02X}:t=fill,"
        )
    text_hex = "0x%02X%02X%02X" % tint.text
    border_hex = "0x%02X%02X%02X" % tint.dark
    drawtext = (
        f"drawtext=fontfile='{_esc_path(find_font())}':textfile='{_esc_path(textfile)}':"
        f"expansion=none:fontcolor={text_hex}:fontsize={fsize}:"
        f"borderw=1:bordercolor={border_hex}:"
        f"x={cx}-text_w/2:y={cy}-text_h/2"
    )

    attempts = [(30, 32), (30, 40), (24, 48), (20, 55), (15, 60)]
    tmp = dst.with_name(dst.stem + "_tmp.webm")
    try:
        for fps, crf in attempts:
            vf = (
                f"fps={fps},scale={SIZE}:{SIZE}:flags=lanczos,format=rgba,"
                f"{drawbox}{drawtext},format=yuva420p"
            )
            cmd = [
                config.FFMPEG, "-y", "-v", "error",
                "-c:v", "libvpx-vp9", "-i", str(src),
                "-vf", vf, "-t", "3", "-an",
                "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                "-b:v", "0", "-crf", str(crf),
                "-deadline", "good", "-cpu-used", "4", "-row-mt", "1",
                "-auto-alt-ref", "0",
                "-metadata:s:v:0", "alpha_mode=1",
                str(tmp),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise WebmError(err.decode("utf-8", "ignore")[-500:] or "ffmpeg завершился с ошибкой")
            if tmp.stat().st_size <= config.WEBM_MAX_BYTES:
                tmp.replace(dst)
                return
        raise WebmError(f"WEBM больше {config.WEBM_MAX_BYTES // 1024} КБ даже после сжатия")
    finally:
        textfile.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)