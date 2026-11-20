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
_SAFE_TOP_MARGIN = 260     # px от верха


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ts(sec: float) -> str:
    sec = max(sec, 0.0)
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


HOOK_LINE_CHARS = 16


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


def _karaoke_text(group: list[dict], clip_start: float) -> str:
    """Текст строки с тегами \\k (сантисекунды подсветки на слово) и переносами."""
    parts: list[str] = []
    line_len = 0
    for i, w in enumerate(group):
        nxt = group[i + 1]["s"] if i + 1 < len(group) else w["e"]
        dur_cs = max(int(round((max(nxt, w["e"]) - w["s"]) * 100)), 5)
        word = _esc(w["w"])
        if line_len and line_len + len(word) > MAX_LINE_CHARS:
            parts.append("\\N")
            line_len = 0
        elif parts:
            parts.append(" ")
            line_len += 1
        parts.append(f"{{\\k{dur_cs}}}{word}")
        line_len += len(word)
    return "".join(parts)


def _style_line(name: str, font: str, size: int, primary: str, secondary: str,
                outline: str, back: str, border_style: int, outline_w: int,
                shadow: int, align: int, margin_v: int, bold: int = -1) -> str:
    return (f"Style: {name},{font},{size},{primary},{secondary},{outline},{back},"
            f"{bold},0,0,0,100,100,0,0,{border_style},{outline_w},{shadow},"
            f"{align},60,60,{margin_v},1")


def build_ass(words: list[dict], clip_len: float, hook_text: str | None,
              style_key: str, out: Path, subtitles: bool = True) -> Path:
    """words: слова клипа с временами уже в секундах от начала клипа."""
    style = config.SUBTITLE_STYLES.get(style_key, config.SUBTITLE_STYLES["violet"])
    highlight = style["highlight"]
    margin = _SAFE_LOWER_MARGIN if style["position"] == "lower" else 760
    align = 2 if style["position"] == "lower" else 5

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line("Sub", style["font"], 92, highlight, "&H00FFFFFF&", "&H00000000&",
                    "&H66000000&", 1, 7, 2, align, margin),
        _style_line("Hook", style["font"], 70, "&H00000000&", "&H00000000&", "&H0000E5FF&",
                    "&H00000000&", 3, 22, 0, 8, _SAFE_TOP_MARGIN),
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
            text = _karaoke_text(group, 0.0)
            lines.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Sub,,0,0,0,,{text}")

    if hook_text:
        hook = "\\N".join(_wrap_words(_esc(hook_text).strip(), HOOK_LINE_CHARS))
        lines.append(
            f"Dialogue: 1,{_ts(0.0)},{_ts(HOOK_DURATION)},Hook,,0,0,0,,"
            f"{{\\fad(150,300)\\fscx100\\fscy100}}{hook}")

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
