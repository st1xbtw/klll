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
_HOOK_LIFT = 230           # px: насколько хук поднят над строкой субтитров


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


def _group_words(words: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    cur: list[dict] = []
    cur_len = 0
    for w in words:
        if cur:
            span = w["e"] - cur[0]["s"]
            if span > MAX_GROUP_SECONDS or cur_len + len(w["w"]) + 1 > MAX_LINE_CHARS * 2:
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


def _tags(effect: str, px: float, py: float, out_h: int, pos_given: bool, hook: bool) -> str:
    """Теги позиции и эффекта одной реплики. Якорь — нижний центр строки (alignment 2)."""
    parts = []
    if effect == "slide":
        d = _margin(out_h, 80)
        parts.append(f"\\move({px:.0f},{py + d:.0f},{px:.0f},{py:.0f},0,220)")
    elif pos_given:
        parts.append(f"\\pos({px:.0f},{py:.0f})")
    if effect == "fade" and not hook:
        parts.append("\\fad(150,150)")
    if effect == "glow":
        parts.append("\\blur2")
    return "{" + "".join(parts) + "}" if parts else ""


def build_ass(words: list[dict], clip_len: float, hook_text: str | None,
              style_key: str, out: Path, subtitles: bool = True, box: bool = False,
              anim: bool = False, emoji: bool = False,
              out_w: int = config.OUT_W, out_h: int = config.OUT_H,
              watermark: str | None = None, font: str | None = None,
              pos: tuple[float, float] | None = None, effect: str = "none") -> Path:
    """pos — (x, y) в пикселях кадра для нижнего центра строки субтитров; None — стандартное место внизу.
    font — имя семейства (шрифт должен лежать в fontsdir), effect — none|fade|slide|glow|pop."""
    """words: слова клипа с временами уже в секундах от начала клипа.

    Субтитры и хук выводятся только внизу кадра (выравнивание 2 — нижний центр).
    Хук стоит над строкой субтитров, если они включены."""
    style = config.SUBTITLE_STYLES.get(style_key, config.SUBTITLE_STYLES["violet"])
    highlight = style["highlight"]
    family = font or style["font"]
    if effect == "pop":
        anim = True
    align = 2
    margin = _margin(out_h, _SAFE_LOWER_MARGIN)
    hook_margin = margin + (_margin(out_h, _HOOK_LIFT) if subtitles and words else 0)
    pos_given = pos is not None
    px, py = pos if pos_given else (out_w / 2, out_h - margin)
    lift = _margin(out_h, _HOOK_LIFT) if subtitles and words else 0
    hook_y = py - lift

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
        _style_line("Sub", family, 92, highlight, "&H00FFFFFF&",
                    "&HA0000000&" if box else "&H00000000&",
                    "&H66000000&", 3 if box else 1, 20 if box else 7, 0 if box else 2, align, margin),
        _style_line("Hook", family, 70, "&H00000000&", "&H00000000&", "&H0000E5FF&",
                    "&H00000000&", 3, 22, 0, align, hook_margin),
        # Водяной знак: название канала в правом верхнем углу, весь клип.
        _style_line("Mark", family, 44, "&HE6FFFFFF&", "&H00FFFFFF&", "&H00000000&",
                    "&H00000000&", 1, 3, 0, 9, _margin(out_h, 90)),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines = list(header)

    if subtitles and words:
        for group in _group_words(words):
            s = group[0]["s"]
            e = group[-1]["e"] + 0.15
            s = min(max(s, 0.0), clip_len)
            e = min(e, clip_len)
            if e <= s:
                continue
            text = _karaoke_text(group, s, emoji=emoji, anim=anim)
            tags = _tags(effect, px, py, out_h, pos_given, hook=False)
            lines.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Sub,,0,0,0,,{tags}{text}")

    if hook_text:
        hook = "\\N".join(_wrap_words(_esc(hook_text).strip(), HOOK_LINE_CHARS))
        htags = _tags(effect, px, hook_y, out_h, pos_given or lift > 0, hook=True)
        inner = htags[1:-1] if htags else ""
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
