from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import ImageFont

from . import config

RGB = tuple[int, int, int]
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def parse_hex(value: str) -> RGB:
    m = _HEX_RE.match(value.strip())
    if not m:
        raise ValueError("Неверный HEX-цвет")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def to_hex(rgb: RGB) -> str:
    return "#%02X%02X%02X" % rgb


@dataclass(frozen=True)
class Tint:
    dark: RGB    # во что превращается чёрный (яркость 0)
    light: RGB   # во что превращается белый (яркость 1)
    text: RGB    # цвет нового ника


def make_tint(rgb: RGB) -> Tint:
    if max(rgb) >= 50:
        return Tint(tuple(round(c * 0.25) for c in rgb), rgb, rgb)  # type: ignore[arg-type]
    # очень тёмный цвет: оставляем читаемую «светлую» часть
    return Tint(rgb, (90, 90, 90), rgb)


def shade(tint: Tint, lum: float) -> tuple[float, float, float]:
    lum = min(max(lum, 0.0), 1.0)
    return tuple(d + (l - d) * lum for d, l in zip(tint.dark, tint.light))  # type: ignore[return-value]


_SYSTEM_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


@lru_cache(maxsize=1)
def find_font() -> Path:
    local = sorted(
        p for p in config.FONTS_DIR.iterdir() if p.suffix.lower() in (".ttf", ".otf")
    )
    if local:
        bold = [p for p in local if "bold" in p.stem.lower()]
        return (bold or local)[0]
    for s in _SYSTEM_FONTS:
        if Path(s).exists():
            return Path(s)
    raise FileNotFoundError(
        "Положите TTF-шрифт с кириллицей и латиницей в папку fonts/ (например DejaVuSans-Bold.ttf)"
    )


@lru_cache(maxsize=4)
def _cmap(path: str) -> dict[int, str]:
    f = TTFont(path, lazy=True)
    return f.getBestCmap()


def font_supports(text: str) -> bool:
    cmap = _cmap(str(find_font()))
    return all(ord(c) in cmap for c in text)


def region_px(w: int, h: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = config.NICK_REGION
    return round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)


def fit_font_size(text: str, max_w: int, max_h: int, upper: int = 400) -> int:
    """Подбирает максимальный размер шрифта, при котором текст влезает в область."""
    path = str(find_font())
    lo, hi, best = 4, upper, 4
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(path, mid)
        l, t, r, b = font.getbbox(text)
        if r - l <= max_w and b - t <= max_h:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best
