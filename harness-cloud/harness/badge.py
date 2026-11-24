"""Значок-строка для кадра: иконки площадок и ник. Рисуется один раз на клип в PNG,
затем накладывается в фильтре ffmpeg (см. render.py), поэтому попадает в видео как субтитры."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config

ORDER = ("telegram", "twitch", "youtube", "tiktok")   # порядок значков слева направо
ICON_DIR = config.UI_DIR / "icons"
ICON_H = 96          # высота значка в пикселях кадра
GAP = 18             # расстояние между значками и до ника
PAD = 14             # поля вокруг строки
NICK_SIZE = 52
FONT_FILE = config.FONTS_DIR / "Inter-Bold.otf"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT_FILE), size)
    except OSError:
        return ImageFont.load_default(size=size)


def make_badge(out: Path, nickname: str, socials: dict, width: int) -> Path | None:
    """PNG со значками и ником по центру ширины width. None, если показывать нечего."""
    icons = [k for k in ORDER if socials.get(k) and (ICON_DIR / f"{k}.png").exists()]
    nick = (nickname or "").strip()
    if not icons and not nick:
        return None
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    icon_room = len(icons) * (ICON_H + GAP) + (GAP * 2 if icons and nick else 0)
    size = NICK_SIZE
    font = _font(size)
    nick_w = int(probe.textlength(nick, font=font)) if nick else 0
    # Ник не должен вылезать за кадр: уменьшаем шрифт, пока строка не поместится.
    while nick and icon_room + nick_w + PAD * 2 > width and size > 24:
        size -= 4
        font = _font(size)
        nick_w = int(probe.textlength(nick, font=font))
    icon_imgs = []
    for k in icons:
        im = Image.open(ICON_DIR / f"{k}.png").convert("RGBA").resize((ICON_H, ICON_H), Image.LANCZOS)
        icon_imgs.append(im)
    parts_w = len(icon_imgs) * ICON_H + max(0, len(icon_imgs) - 1) * GAP
    if nick and icon_imgs:
        parts_w += GAP * 2
    total_w = min(width, parts_w + nick_w + PAD * 2 + ICON_H // 2)
    h = ICON_H + PAD * 2
    canvas = Image.new("RGBA", (total_w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    # Подложка: полупрозрачная пилюля, чтобы значки читались на любом фоне видео.
    draw.rounded_rectangle((0, 0, total_w - 1, h - 1), radius=h // 2, fill=(0, 0, 0, 120))
    x = (total_w - (parts_w + nick_w)) // 2
    y = PAD
    for im in icon_imgs:
        canvas.alpha_composite(im, (x, y))
        x += ICON_H + GAP
    if nick:
        if icon_imgs:
            x += GAP
        draw.text((x, h // 2), nick, font=font, fill=(255, 255, 255, 255),
                  anchor="lm", stroke_width=4, stroke_fill=(0, 0, 0, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, optimize=True)
    return out
