"""Загрузка исходных эмодзи напрямую через Telegram Bot API по токену бота (бот-процесс не нужен).

Токен задаёт пользователь в приложении. Запросы идут с ПК на api.telegram.org.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Callable

from . import sources

TG_API = "https://api.telegram.org"
TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,}$")
CHUNK = 200  # лимит getCustomEmojiStickers на один запрос


class TelegramError(Exception):
    pass


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.match(token.strip()))


def _call(token: str, method: str, payload: dict | None = None, timeout: int = 60):
    req = urllib.request.Request(
        f"{TG_API}/bot{token}/{method}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except ValueError:
            body = {}
        if e.code == 401:
            raise TelegramError("Telegram не принял токен бота (проверьте, что он скопирован целиком)")
        raise TelegramError("Telegram: " + str(body.get("description", f"ошибка {e.code}")))
    except urllib.error.URLError:
        raise TelegramError("Нет связи с api.telegram.org. Проверьте интернет или доступ к Telegram.")
    if not body.get("ok"):
        raise TelegramError("Telegram: " + str(body.get("description", "неизвестная ошибка")))
    return body["result"]


def _download(token: str, file_path: str, timeout: int = 60) -> bytes:
    url = f"{TG_API}/file/bot{token}/{file_path}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read(sources.MAX_FILE_BYTES + 1)


def fetch_sources(token: str, ids: list[str],
                  call: Callable = _call, download: Callable = _download) -> dict:
    """Скачивает исходники для ids. Возвращает {'added': [...], 'missing': [...]}."""
    token = token.strip()
    if not valid_token(token):
        raise ValueError("Некорректный токен бота (формат 123456:ABC…)")
    ids = list(dict.fromkeys(ids))
    found: dict[str, dict] = {}
    for i in range(0, len(ids), CHUNK):
        for s in call(token, "getCustomEmojiStickers", {"custom_emoji_ids": ids[i:i + CHUNK]}):
            found[str(s.get("custom_emoji_id"))] = s

    added: list[str] = []
    missing: list[str] = []
    for eid in ids:
        s = found.get(eid)
        if s is None:
            missing.append(eid)
            continue
        ext = "tgs" if s.get("is_animated") else ("webm" if s.get("is_video") else "webp")
        try:
            info = call(token, "getFile", {"file_id": s["file_id"]})
            data = download(token, info["file_path"])
        except (TelegramError, KeyError, OSError):
            missing.append(eid)
            continue
        if len(data) > sources.MAX_FILE_BYTES or not sources._is_valid(ext, data):
            missing.append(eid)
            continue
        sources._store(eid, ext, data)
        added.append(eid)
    return {"added": added, "missing": missing}
