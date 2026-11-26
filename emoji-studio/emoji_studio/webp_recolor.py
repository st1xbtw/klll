from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config
from .common import fit_font_size, find_font, make_tint, parse_hex, region_px

SIZE = 100
SS = 4  # суперсэмплинг для текста


def recolor_webp(src: Path, dst: Path, nick: str, color_hex: str) -> None:
    """Меняет только ник: фон и рисунок эмодзи остаются как были."""
    tint = make_tint(parse_hex(color_hex))
    img = Image.open(src).convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
    x0, y0, x1, y1 = region_px(SIZE, SIZE)
    alpha = img.getchannel("A")

    # стираем старый ник: заливаем область ника фоном, который уже есть у эмодзи
    rgb = img.convert("RGB")
    hist = rgb.crop((x0, y0, x1, y1)).getcolors(maxcolors=SIZE * SIZE) or [(0, (0, 0, 0))]
    bg = max(hist)[1]
    base = img.copy()
    ImageDraw.Draw(base).rectangle((x0, y0, x1 - 1, y1 - 1), fill=(*bg, 255))
    base.putalpha(alpha)

    # новый ник: рисуем в 4x с тонкой обводкой, затем уменьшаем — гладкие края
    big = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    bw, bh = (x1 - x0) * SS, (y1 - y0) * SS
    size = fit_font_size(nick, bw - 2 * SS, bh - 2 * SS)
    font = ImageFont.truetype(str(find_font()), size)
    ImageDraw.Draw(big).text(
        ((x0 + x1) / 2 * SS, (y0 + y1) / 2 * SS),
        nick, font=font, fill=(*tint.text, 255), anchor="mm",
        stroke_width=max(1, SS // 2), stroke_fill=(*tint.dark, 255),
    )
    text_layer = big.resize((SIZE, SIZE), Image.LANCZOS)
    result = Image.alpha_composite(base, text_layer)

    result.save(dst, "WEBP", lossless=True, quality=100, method=6)
    if dst.stat().st_size <= config.WEBP_MAX_BYTES:
        return
    for q in (90, 80, 70, 60, 50, 40):
        result.save(dst, "WEBP", quality=q, method=6)
        if dst.stat().st_size <= config.WEBP_MAX_BYTES:
            return
    raise ValueError("WEBP слишком большой даже после сжатия")
