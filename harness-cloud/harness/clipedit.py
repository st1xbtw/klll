"""Правка текста субтитров и быстрый предпросмотр клипа.

Предпросмотр: первые PREVIEW_SECONDS секунд клипа в 480p с текущими настройками (стиль, положение,
шрифт, хук, водяной знак). Кадр — центральный, без распознавания лиц, чтобы не ждать анализа.
Правка текста: новый текст раскладывается по таймингам расшифровки; если число слов не совпало,
слова делятся поровну по длине клипа.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from . import config, fonts, render, segments as sg, subtitles, transcribe
from .tools import ToolError

PREVIEW_SECONDS = 4.0
PREVIEW_QUALITY = "480p"
MAX_TEXT_CHARS = 3000


def load_words(d: Path) -> list[dict]:
    """Слова всей расшифровки проекта (с таймкодами в секундах видео)."""
    try:
        segs = json.loads((d / "transcript.json").read_text(encoding="utf-8"))["segments"]
    except (OSError, ValueError, KeyError):
        return []
    return transcribe.flatten_words(segs)


def clip_base_words(clip: dict, words_all: list[dict]) -> list[dict]:
    segs = clip.get("segments") or [[clip["start"], clip["end"]]]
    return sg.words_for_clip(segs, words_all)


def retime(text: str, base: list[dict], dur: float) -> list[dict]:
    """Раскладывает слова текста по таймингам (секунды от начала клипа)."""
    tokens = text.split()
    if not tokens or dur <= 0:
        return []
    if base and len(base) == len(tokens):
        return [{"w": t, "s": b["s"], "e": b["e"]} for t, b in zip(tokens, base)]
    step = dur / len(tokens)
    return [{"w": t, "s": i * step, "e": (i + 1) * step - min(0.02, step / 4)}
            for i, t in enumerate(tokens)]


def normalize_text(raw: str) -> str:
    text = " ".join(str(raw or "").split())
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"Текст длиннее {MAX_TEXT_CHARS} символов")
    return text


def render_preview(proj: dict, clip: dict, d: Path) -> Path:
    """Четырёхсекундный предпросмотр клипа в 480p. Возвращает путь к preview.mp4."""
    idx = clip["index"]
    cdir = d / "clips" / f"{idx:02d}"
    cdir.mkdir(parents=True, exist_ok=True)
    src = d / (proj.get("source_file") or "source.mp4")
    if not src.exists():
        raise ToolError("Исходное видео не найдено")
    segs = clip.get("segments") or [[clip["start"], clip["end"]]]
    start = float(segs[0][0])
    dur = PREVIEW_SECONDS
    words = clip.get("sub_words") or clip_base_words(clip, load_words(d))
    words = [{"w": w["w"], "s": w["s"], "e": min(w["e"], dur)} for w in words if w["s"] < dur]

    out_w, out_h = config.out_size(clip.get("aspect"), PREVIEW_QUALITY)
    ctype = proj["content_type"]
    use_subs = bool(clip.get("subtitles", ctype != "game"))
    show_hook = bool(clip.get("show_hook", ctype != "game"))
    hook = (clip.get("hook") or "") if show_hook else ""
    family = fonts.copy_for_clip(clip.get("sub_font"), cdir)
    pos = None
    if clip.get("sub_x") is not None and clip.get("sub_y") is not None:
        pos = (float(clip["sub_x"]) / 100 * out_w, float(clip["sub_y"]) / 100 * out_h)
    ass = subtitles.build_ass(
        words, dur, hook or None, clip["style"], cdir / "preview.ass", subtitles=use_subs,
        box=bool(clip.get("sub_box")), anim=bool(clip.get("sub_anim")),
        emoji=bool(clip.get("sub_emoji")), out_w=out_w, out_h=out_h,
        watermark=(clip.get("watermark") or "").strip() or None, font=family, pos=pos,
        effect=clip.get("sub_effect") or "none",
        place=clip.get("sub_place") or config.DEFAULT_SUB_PLACE)
    framing = clip.get("framing") or "face"
    if framing == "face":
        framing = "center"
    out = cdir / "preview.mp4"
    res = render.render_clip(
        src, start, dur, None, ass, out, proj["options"].get("export_preset", "tiktok"),
        threading.Event(), framing=framing, src_w=proj["src_w"], src_h=proj["src_h"],
        out_w=out_w, out_h=out_h, fps=config.DEFAULT_FPS)
    # render.verify проверяет длину 30 с под полный клип, поэтому здесь свои проверки.
    if ((res.get("width"), res.get("height")) != (out_w, out_h) or not res.get("has_video")
            or abs(float(res.get("duration") or 0) - dur) > 0.3):
        raise ToolError(f"Предпросмотр не собрался: {res}")
    return out
