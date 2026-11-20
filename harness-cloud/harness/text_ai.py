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

from .subtitles import make_hook

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-5-5"

STOP = set("и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по "
           "только ее её мне было вот от меня еще нет о из ему теперь когда уже для вас ни "
           "быть был до вам нибудь опять без это этот эта эти the a an and of to is in it".split())


def llm_hook(clip_text: str, content_type: str) -> str | None:
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
