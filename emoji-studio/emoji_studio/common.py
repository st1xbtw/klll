from __future__ import annotations

import re
from dataclasses import dataclass
from collections import Counter
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
import json
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


_SETTINGS_CACHE: tuple[float, dict] | None = None


def _settings() -> dict:
    """Настройки читаются с диска только когда файл изменился (по mtime)."""
    global _SETTINGS_CACHE
    try:
        mtime = config.SETTINGS_FILE.stat().st_mtime
    except OSError:
        return {}
    if _SETTINGS_CACHE is not None and _SETTINGS_CACHE[0] == mtime:
        return _SETTINGS_CACHE[1]
    try:
        data = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    _SETTINGS_CACHE = (mtime, data)
    return data


def font_scale() -> float:
    try:
        v = float(_settings().get("font_scale", 1.0))
    except (TypeError, ValueError):
        v = 1.0
    return min(1.5, max(0.5, v))


@lru_cache(maxsize=1)
def _default_font() -> Path:
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


def find_font() -> Path:
    """Шрифт, выбранный в настройках, либо встроенный по умолчанию."""
    chosen = _settings().get("font_path")
    if chosen and Path(chosen).is_file():
        return Path(chosen)
    return _default_font()


def supports_cyrillic(path: Path) -> bool:
    try:
        cmap = TTFont(str(path), lazy=True).getBestCmap() or {}
    except Exception:  # noqa: BLE001 — битый или нечитаемый файл
        return False
    return 0x0410 in cmap and 0x0430 in cmap and 0x0041 in cmap


def font_name(path: Path) -> str:
    try:
        names = TTFont(str(path), lazy=True)["name"]
        n = names.getDebugName(4) or names.getDebugName(1)
        return n or path.stem
    except Exception:  # noqa: BLE001
        return path.stem


def _font_dirs() -> list[Path]:
    dirs = [Path("C:/Windows/Fonts"), Path("/Library/Fonts"),
            Path("/System/Library/Fonts/Supplemental"), Path("/usr/share/fonts"),
            config.FONTS_DIR, config.USER_DIR / "fonts"]
    return [d for d in dirs if d.is_dir()]


_FONTS_CACHE: list[dict] | None = None


def invalidate_fonts() -> None:
    """Сбрасывает кэш списка шрифтов (после добавления нового файла)."""
    global _FONTS_CACHE
    _FONTS_CACHE = None


def list_fonts() -> list[dict]:
    """Установленные в системе и добавленные вручную шрифты с кириллицей.

    Сканирование системных папок тяжёлое, поэтому результат кэшируется до
    загрузки нового шрифта (см. invalidate_fonts).
    """
    global _FONTS_CACHE
    if _FONTS_CACHE is not None:
        return _FONTS_CACHE
    found: dict[str, dict] = {}
    for d in _font_dirs():
        for p in d.rglob("*"):
            if p.suffix.lower() not in (".ttf", ".otf") or not p.is_file():
                continue
            name = font_name(p)
            if name in found or not supports_cyrillic(p):
                continue
            found[name] = {"name": name, "path": str(p)}
    _FONTS_CACHE = sorted(found.values(), key=lambda f: f["name"].lower())
    return _FONTS_CACHE


@lru_cache(maxsize=4)
def _cmap(path: str) -> dict[int, str]:
    f = TTFont(path, lazy=True)
    return f.getBestCmap()


def font_supports(text: str) -> bool:
    cmap = _cmap(str(find_font()))
    return all(ord(c) in cmap for c in text)


def nick_region_frac(eid: str) -> tuple[float, float, float, float]:
    """Где менять надпись на эмодзи (доли кадра).

    Для эмодзи с известными контурами LOVEX — прямоугольник, охватывающий эту надпись,
    чтобы новый ник встал на её место. Для остальных — общая NICK_REGION.
    """
    if eid in config.LOVEX_NICK_FRAC:
        return config.LOVEX_NICK_FRAC[eid]
    boxes = config.LOVEX_BOXES.get(eid)
    if boxes:
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))
    return config.NICK_REGION


def region_bg(img, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Цвет фона вокруг области ника: самый частый цвет на кольце в 2 px снаружи.

    Внутри области может быть много букв (их цвет нельзя брать за фон), поэтому смотрим кольцо.
    img — PIL-изображение в RGB.
    """
    x0, y0, x1, y1 = box
    W, H = img.size
    ring = []
    for x in range(max(0, x0 - 2), min(W, x1 + 2)):
        for y in range(max(0, y0 - 2), min(H, y1 + 2)):
            if x0 <= x < x1 and y0 <= y < y1:
                continue
            ring.append(img.getpixel((x, y)))
    if ring:
        return Counter(ring).most_common(1)[0][0]
    hist = img.crop(box).getcolors(maxcolors=W * H) or [(0, (0, 0, 0))]
    return max(hist)[1]


def region_px(w: int, h: int, frac: tuple | None = None) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = frac or config.NICK_REGION
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
    return max(4, int(best * font_scale()))
