"""Модуль 11 (LLM-вариант) и автогенерация описания/хештегов.

Хук: если задан ANTHROPIC_API_KEY — короткий заголовок через Messages API;
иначе или при ошибке — правила из subtitles.make_hook (fallback).
Описание и хештеги формируются правилами из текста клипа.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter

from . import config
from .subtitles import make_hook

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-5-5"

STOP = set("и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по "
           "только ее её мне было вот от меня еще нет о из ему теперь когда уже для вас ни "
           "быть был до вам нибудь опять без это этот эта эти the a an and of to is in it".split())


def llm_hook(clip_text: str, content_type: str) -> str | None:
    if config.offline_mode():
        return None  # офлайн: только правила
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not clip_text.strip():
        return None
    prompt = ("Придумай короткий цепляющий заголовок (до 6 слов, на языке текста) "
              "для вертикального видео. Ответь только заголовком.\n\nТекст клипа:\n" + clip_text[:1500])
    body = json.dumps({"model": MODEL, "max_tokens": 40,
                       "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        text = text.strip().strip('"«»').strip()
        return text or None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def hook_for(clip_text: str, sentences: list[str], content_type: str) -> tuple[str, str]:
    """Возвращает (текст хука, источник: llm|rules)."""
    ai = llm_hook(clip_text, content_type)
    if ai:
        return ai, "llm"
    return make_hook(sentences or [clip_text]), "rules"


def describe(clip_text: str, hook: str, content_type: str) -> dict:
    words = [w.lower() for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", clip_text)]
    top = [w for w, _ in Counter(w for w in words if w not in STOP).most_common(4)]
    base_tags = ["#shorts", "#reels", "#tiktok"]
    if content_type == "game":
        base_tags = ["#gaming", "#стрим", "#игры", "#shorts"]
    elif content_type == "podcast":
        base_tags = ["#подкаст", "#интервью", "#shorts"]
    tags = base_tags + ["#" + re.sub(r"[^\wа-яё]", "", t) for t in top]
    tags = list(dict.fromkeys(t for t in tags if len(t) > 1))[:8]
    desc = hook if hook else (clip_text[:140].strip() or "Лучший момент из длинного видео")
    if top:
        desc = f"{desc}. Про: {', '.join(top[:3])}."
    return {"description": desc, "hashtags": tags}


# ---------- варианты под платформы ----------

PLATFORM_LIMITS = {
    # TikTok: короткая подпись и 3–5 хештегов, видна первая строка.
    "tiktok": {"title": None, "text": 150, "tags": 5},
    # YouTube Shorts: заголовок до 70 символов, описание до 200, 3 хештега (#shorts обязателен).
    "shorts": {"title": 70, "text": 200, "tags": 3},
    # Instagram Reels: до 125 символов видны без нажатия «ещё», 5 хештегов.
    "reels": {"title": None, "text": 125, "tags": 5},
}


def _cut_words(text: str, limit: int) -> str:
    """Обрезка по словам без разрыва слова, с многоточием при необходимости."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return (cut or text[: limit - 1]) + "…"


def _tags(content_type: str, clip_text: str, n: int, must: list[str]) -> list[str]:
    base = {"game": ["#gaming", "#стрим", "#игры"],
            "podcast": ["#подкаст", "#интервью"]}.get(content_type, [])
    topics = describe(clip_text, "", content_type)["hashtags"]
    platform_tags = {"#shorts", "#reels", "#tiktok"}
    topics = [t for t in topics if t not in base and t not in platform_tags]
    tags = list(dict.fromkeys(must + base + topics))
    return tags[:n]


def describe_platforms(clip_text: str, hook: str, content_type: str) -> dict:
    """Тексты и хештеги под TikTok, YouTube Shorts и Instagram Reels по лимитам каждой платформы."""
    base_desc = hook or clip_text[:200]
    topics = describe(clip_text, hook, content_type)["hashtags"]
    out = {}
    lim = PLATFORM_LIMITS["tiktok"]
    out["tiktok"] = {
        "text": _cut_words(base_desc, lim["text"]),
        "hashtags": _tags(content_type, clip_text, lim["tags"], ["#tiktok"]),
    }
    lim = PLATFORM_LIMITS["shorts"]
    title = _cut_words(hook or (clip_text[:lim["title"]] or "Лучший момент"), lim["title"])
    body = _cut_words(clip_text or hook, lim["text"])
    out["shorts"] = {
        "title": title,
        "text": body,
        "hashtags": _tags(content_type, clip_text, lim["tags"], ["#shorts"]),
    }
    lim = PLATFORM_LIMITS["reels"]
    out["reels"] = {
        "text": _cut_words(base_desc, lim["text"]),
        "hashtags": _tags(content_type, clip_text, lim["tags"], ["#reels"]),
    }
    return out
