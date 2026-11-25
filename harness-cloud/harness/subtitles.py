"""Модули 10–11: субтитры (ASS, пословная подсветка) и хук-заголовок в первые секунды.

Безопасные зоны: верх ~250 px и низ ~420 px кадра 1080×1920 заняты интерфейсом
TikTok / Shorts / Reels, поэтому текст держим между ними.
"""
from __future__ import annotations

from pathlib import Path

from . import config

HOOK_DURATION = 2.8        # секунд на экране
MAX_LINE_CHARS = 18
MAX_GROUP_SECONDS = 2.6
MAX_HOOK_WORDS = 7

_SAFE_LOWER_MARGIN = 430   # px от низа
_SAFE_TOP_MARGIN = 260     # px от верха (не используется: всё выводится снизу)
_HOOK_LIFT = 330           # px: насколько хук отодвинут от строки субтитров (две строки по 104 px)


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ts(sec: float) -> str:
    sec = max(sec, 0.0)
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


HOOK_LINE_CHARS = 16

# Эмодзи добавляются к словам из этого словаря (только если включена опция «эмодзи»).
EMOJI_MAP = {
    "секрет": "🔑", "деньги": "💰", "успех": "🚀", "ошибка": "⚠️", "важно": "❗",
    "никогда": "🚫", "правда": "💡", "совет": "💡", "лучший": "🏆", "лучшая": "🏆",
    "шок": "😱", "вывод": "✅", "вот": "👉", "дисциплина": "💪", "дисциплине": "💪",
    "мотивация": "🔥", "реально": "🔥", "невероятно": "🤯", "почему": "🤔",
}


def _wrap_words(text: str, max_chars: int) -> list[str]:
    """Переносы по словам: строка не длиннее max_chars (слово длиннее — отдельной строкой)."""
    out: list[str] = []
    cur = ""
    for w in text.split():
        cand = (cur + " " + w).strip()
        if cur and len(cand) > max_chars:
            out.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def _group_words(words: list[dict], max_words: int = 0) -> list[list[dict]]:
    """Группы слов для строк субтитров. max_words > 0 — ровно столько слов в строке (1–4)."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    cur_len = 0
    for w in words:
        if cur:
            span = w["e"] - cur[0]["s"]
            if max_words and len(cur) >= max_words:
                groups.append(cur)
                cur, cur_len = [], 0
            elif span > MAX_GROUP_SECONDS or cur_len + len(w["w"]) + 1 > MAX_LINE_CHARS * 2:
                groups.append(cur)
                cur, cur_len = [], 0
        cur.append(w)
        cur_len += len(w["w"]) + 1
    if cur:
        groups.append(cur)
    return groups


def _karaoke_text(group: list[dict], line_start: float, emoji: bool = False,
                  anim: bool = False) -> str:
    """Текст строки: \\k — подсветка каждого слова, \\t — «всплытие» слова, эмодзи, переносы."""
    parts: list[str] = []
    line_len = 0
    for i, w in enumerate(group):
        nxt = group[i + 1]["s"] if i + 1 < len(group) else w["e"]
        dur_cs = max(int(round((max(nxt, w["e"]) - w["s"]) * 100)), 5)
        raw = w["w"]
        if emoji:
            key = raw.lower().strip(".,!?;:")
            if key in EMOJI_MAP:
                raw = raw + " " + EMOJI_MAP[key]
        word = _esc(raw)
        if line_len and line_len + len(word) > MAX_LINE_CHARS:
            parts.append("\\N")
            line_len = 0
        elif parts:
            parts.append(" ")
            line_len += 1
        tags = f"\\k{dur_cs}"
        if anim:
            t0 = int(round((w["s"] - line_start) * 1000))
            tags = (f"\\t({t0},{t0 + 140},\\fscx118\\fscy118)"
                    f"\\t({t0 + 140},{t0 + 280},\\fscx100\\fscy100)" + tags)
        parts.append(f"{{{tags}}}{word}")
        line_len += len(word)
    return "".join(parts)


def _style_line(name: str, font: str, size: int, primary: str, secondary: str,
                outline: str, back: str, border_style: int, outline_w: int,
                shadow: int, align: int, margin_v: int, bold: int = -1) -> str:
    return (f"Style: {name},{font},{size},{primary},{secondary},{outline},{back},"
            f"{bold},0,0,0,100,100,0,0,{border_style},{outline_w},{shadow},"
            f"{align},60,60,{margin_v},1")


def _margin(out_h: int, px_at_1920: float) -> int:
    """Отступ от низа в пикселях, пересчитанный под высоту кадра."""
    return max(20, round(out_h * px_at_1920 / 1920))


NO_OVERLAP_GAP = 0.02  # с: зазор между репликами субтитров, чтобы они не пересекались

PLACE_ALIGN = {"bottom": 2, "center": 5, "top": 8}   # ASS: 2 — низ по центру, 5 — середина, 8 — верх
_TOP_MARGIN_PX = 260                                   # верхняя граница безопасной зоны


def _tags(effect: str, x: float, y: float, align: int, out_h: int, hook: bool) -> str:
    """Якорь (\\an), позиция и эффект одной реплики. Координаты — точка якоря в пикселях кадра.

    Эффекты для субтитров: slide — выезд, fade — проявление, glow — свечение,
    bounce — «пружина» (сжатие и перескок), rise — подъём снизу с проявлением,
    zoom — приближение из меньшего размера, drop — падение с проявлением.
    Для хука действуют только позиция и свечение: у него своя анимация \\fad."""
    parts = [f"\\an{align}"]
    sign = -1 if align == 8 else 1          # сверху выезжает сверху, снизу — снизу
    if not hook and effect == "slide":
        d = _margin(out_h, 80) * sign
        parts.append(f"\\move({x:.0f},{y + d:.0f},{x:.0f},{y:.0f},0,220)")
    elif not hook and effect == "rise":
        d = _margin(out_h, 60) * sign
        parts.append(f"\\move({x:.0f},{y + d:.0f},{x:.0f},{y:.0f},0,240)")
        parts.append("\\alpha&HFF&\\t(0,220,\\alpha&H00&)")
    else:
        parts.append(f"\\pos({x:.0f},{y:.0f})")
    if not hook and effect == "fade":
        parts.append("\\fad(150,150)")
    if not hook and effect == "bounce":
        parts.append("\\fscx70\\fscy70\\t(0,130,\\fscx115\\fscy115)\\t(130,260,\\fscx100\\fscy100)")
    if not hook and effect == "zoom":
        # Приближение: слово появляется меньше, за 200 мс вырастает до полного размера.
        parts.append("\\fscx60\\fscy60\\alpha&HFF&\\t(0,200,\\fscx100\\fscy100\\alpha&H00&)")
    if not hook and effect == "drop":
        # Падение: сверху вниз (для верхней строки — наоборот) с коротким проявлением.
        d = _margin(out_h, 120) * -sign
        parts.append(f"\\move({x:.0f},{y + d:.0f},{x:.0f},{y:.0f},0,260)")
        parts.append("\\fad(120,0)")
    if effect == "glow":
        parts.append("\\blur2")
    return "{" + "".join(parts) + "}"


def _sub_anchor(place: str, pos, out_w: int, out_h: int, bottom_m: int, top_m: int):
    """Точка, куда привязаны субтитры: (выравнивание, x, y). Перетаскивание (pos) важнее пресета."""
    if pos is not None:
        return 2, pos[0], pos[1]
    if place == "top":
        return 8, out_w / 2, top_m
    if place == "center":
        return 5, out_w / 2, out_h / 2
    return 2, out_w / 2, out_h - bottom_m


def _hook_anchor(place: str, has_subs: bool, pos, out_w: int, out_h: int,
                 bottom_m: int, top_m: int, lift: int):
    """Хук ставится с противоположной стороны от субтитров, чтобы не перекрывать их."""
    if pos is not None:
        return 2, pos[0], pos[1] - (lift if has_subs else 0)
    if place == "top":
        return 8, out_w / 2, top_m + (lift if has_subs else 0)
    if place == "center":
        return 8, out_w / 2, top_m
    return 2, out_w / 2, out_h - bottom_m - (lift if has_subs else 0)


def build_ass(words: list[dict], clip_len: float, hook_text: str | None,
              style_key: str, out: Path, subtitles: bool = True, box: bool = False,
              anim: bool = False, emoji: bool = False,
              out_w: int = config.OUT_W, out_h: int = config.OUT_H,
              watermark: str | None = None, font: str | None = None, group_size: int = 0,
              pos: tuple[float, float] | None = None, effect: str = "none",
              place: str = config.DEFAULT_SUB_PLACE, scale: int = 100) -> Path:
    """Строит ASS-файл субтитров, хука и водяного знака.

    words: слова клипа с временами в секундах от начала клипа.
    place — bottom|center|top: где стоят субтитры; хук уходит на противоположную сторону.
    pos — (x, y) в пикселях кадра: точка субтитров, заданная маркером; перекрывает place.
    font — семейство шрифта (лежит в fontsdir), effect — none|fade|slide|glow|pop."""
    style = config.SUBTITLE_STYLES.get(style_key, config.SUBTITLE_STYLES[config.DEFAULT_SUBTITLE_STYLE])
    family = font or style["font"]
    if effect == "pop" or style.get("pop"):
        anim = True
    place = place if place in PLACE_ALIGN else config.DEFAULT_SUB_PLACE
    has_subs = bool(subtitles and words)
    bottom_m = _margin(out_h, _SAFE_LOWER_MARGIN)
    top_m = _margin(out_h, _TOP_MARGIN_PX)
    lift = _margin(out_h, _HOOK_LIFT) if has_subs else 0
    sub_align, sub_x, sub_y = _sub_anchor(place, pos, out_w, out_h, bottom_m, top_m)
    hook_align, hook_x, hook_y = _hook_anchor(place, has_subs, pos, out_w, out_h,
                                              bottom_m, top_m, lift)

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {out_w}",
        f"PlayResY: {out_h}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # Подложка: непрозрачный бокс (BorderStyle 3) полупрозрачного чёрного цвета.
        _style_line("Sub", family, max(1, round(style["size"] * max(50, min(200, scale)) / 100)), style["highlight"], style["base"],
                    "&HA0000000&" if box else style["outline"], "&H66000000&",
                    3 if box else 1, 20 if box else style["outline_w"],
                    0 if box else style["shadow"], sub_align, bottom_m, bold=-1),
        _style_line("Hook", family, 74, "&H00000000&", "&H00000000&", "&H0000E5FF&",
                    "&H00000000&", 3, 22, 0, hook_align, 0, bold=-1),
        # Водяной знак: название канала в правом верхнем углу, весь клип.
        _style_line("Mark", family, 44, "&HE6FFFFFF&", "&H00FFFFFF&", "&H00000000&",
                    "&H00000000&", 1, 3, 0, 9, _margin(out_h, 90)),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines = list(header)

    if has_subs:
        groups = _group_words(words, group_size)
        for i, group in enumerate(groups):
            s = min(max(group[0]["s"], 0.0), clip_len)
            # Конец реплики не может зайти на начало следующей: иначе две строки висят одна поверх другой.
            e = group[-1]["e"] + 0.15
            if i + 1 < len(groups):
                e = min(e, groups[i + 1][0]["s"] - NO_OVERLAP_GAP)
            e = min(e, clip_len)
            if e <= s:
                continue
            text = _karaoke_text(group, s, emoji=emoji, anim=anim)
            tags = _tags(effect, sub_x, sub_y, sub_align, out_h, hook=False)
            lines.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Sub,,0,0,0,,{tags}{text}")

    if hook_text:
        hook = "\\N".join(_wrap_words(_esc(hook_text).strip(), HOOK_LINE_CHARS))
        htags = _tags(effect, hook_x, hook_y, hook_align, out_h, hook=True)
        inner = htags[1:-1]
        lines.append(
            f"Dialogue: 1,{_ts(0.0)},{_ts(HOOK_DURATION)},Hook,,0,0,0,,"
            f"{{{inner}\\fad(150,300)\\fscx100\\fscy100}}{hook}")

    if watermark:
        mark = _esc(watermark.strip()[:40])
        lines.append(f"Dialogue: 2,{_ts(0.0)},{_ts(clip_len)},Mark,,0,0,0,,{mark}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return out


def make_hook(text_candidates: list[str]) -> str:
    """Правила: берём самую «цепляющую» фразу и укорачиваем до MAX_HOOK_WORDS слов."""
    if not text_candidates:
        return ""
    best = max(text_candidates, key=lambda t: (("?" in t) + ("!" in t) * 1.2
                                                + min(len(t.split()), 7) * 0.1))
    words = best.strip().rstrip(".,;:").split()
    if len(words) > MAX_HOOK_WORDS:
        words = words[:MAX_HOOK_WORDS]
    return " ".join(words).strip(" -–—,")
