"""Фильтр рекламных вставок: окна с рекламным текстом не попадают в клипы.

Решение по тексту транскрипции, без распознавания звука. Сильное слово (промокод, спонсор,
#ad) отсекает окно сразу; слабые фразы (ссылка в описании, подпишитесь) — только вместе.
Ложные срабатывания возможны, если в эфире сами обсуждают рекламу: это зафиксировано в README."""
from __future__ import annotations

import re

STRONG_AD_RE = re.compile(
    r"промокод|спонсор|реклам\w*|promo\s?code|sponsor\w*|#ad\b|use code|скидк\w*\s+\d+\s?%",
    re.IGNORECASE)
WEAK_AD_RE = re.compile(
    r"ссылк\w*\s+в\s+описани|по\s+ссылке|подписывайтесь|подпишись|поддержать\s+стрим|донат\w*|link in (the )?bio",
    re.IGNORECASE)


def is_ad_text(text: str) -> bool:
    """True, если текст окна похож на рекламную вставку."""
    if not text:
        return False
    if STRONG_AD_RE.search(text):
        return True
    return len(WEAK_AD_RE.findall(text)) >= 2
