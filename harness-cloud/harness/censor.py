"""Цензура мата по таймкодам слов: слово маскируется в субтитрах, звук на нём приглушается.

Список корней намеренно короткий и правится в одном месте. Совпадение по корню
(«бляд», «блят», «пизд»…) ловит и производные формы. Это фильтр по словам, не понимание смысла."""
from __future__ import annotations

import re

_RU_ROOTS = ["хуй", "хуё", "хуя", "пизд", "еб", "ёб", "бля", "блят", "сука", "сучк", "мудак",
             "залуп", "дроч", "гандон", "шлюх"]
_EN_ROOTS = ["fuck", "shit", "bitch", "asshole", "cunt"]
_PATTERN = re.compile(r"^(" + "|".join(map(re.escape, _RU_ROOTS + _EN_ROOTS)) + r")", re.IGNORECASE)


def is_profane(token: str) -> bool:
    core = re.sub(r"[^\wёЁ]", "", token.lower())
    return bool(core) and bool(_PATTERN.match(core))


def censor_words(words: list[dict]) -> tuple[list[dict], list[tuple[float, float]]]:
    """Возвращает копию слов с замаскированными словами и отрезки (сек), где звук глушим."""
    out: list[dict] = []
    mutes: list[tuple[float, float]] = []
    for w in words:
        item = dict(w)
        if is_profane(w["w"]):
            core_len = len(re.sub(r"[^\wёЁ]", "", w["w"]))
            item["w"] = "*" * max(3, core_len)
            mutes.append((float(w["s"]), float(w["e"]) + 0.05))
        out.append(item)
    return out, mutes


def mute_filter(mutes: list[tuple[float, float]]) -> str:
    """Фильтр volume, который выключает звук на отрезках mutes (время в секундах клипа)."""
    if not mutes:
        return ""
    cond = "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})" for a, b in mutes)
    return f"volume=0:enable='{cond}'"
