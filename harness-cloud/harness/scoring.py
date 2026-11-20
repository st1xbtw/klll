"""Модули 5–6: поиск сильных моментов и ранжирование.

Признаки считаются по секундам:
  loud      — громкость (RMS, нормирована по всему видео)
  density   — плотность речи (слов/сек; если текста нет — доля голосовой энергии)
  emotion   — смена эмоций: скачок энергии и спектрального центроида между половинами окна
  keywords  — ключевые слова (словарь зависит от типа контента)
  pauses    — доля длинных пауз (штраф)
Окна по 30 с с шагом 1 с; выбираются непересекающиеся лучшие окна с фильтром дубликатов.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from . import config
from .audio import SR

KEYWORDS_COMMON = {
    "секрет", "главное", "важно", "никогда", "всегда", "ошибка", "правда", "деньги",
    "лучший", "лучшая", "невероятно", "серьёзно", "серьезно", "оказывается", "причина",
    "история", "совет", "вывод", "реально", "безумие", "шок", "почему", "как", "зачем",
    "secret", "never", "always", "mistake", "truth", "money", "best", "crazy", "why", "how",
}
KEYWORDS_GAME = {
    "убил", "убила", "победа", "босс", "вау", "жесть", "гг", "катка", "рампаж", "клатч",
    "ахах", "ааа", "нет", "да", "сейчас", "попал", "промах", "ушёл", "ушел",
    "wow", "clutch", "gg", "boss", "insane", "no way", "headshot", "win", "dead",
}
PUNCT_HOOK = re.compile(r"[!?]")


@dataclass
class Candidate:
    start: float
    end: float
    score: float
    parts: dict = field(default_factory=dict)
    text: str = ""
    reason: str = ""


def _rms_per_sec(samples: np.ndarray, sr: int) -> np.ndarray:
    hop = sr
    n = max(len(samples) // hop, 1)
    frames = samples[: n * hop].reshape(n, hop) if len(samples) >= hop else samples[None, :]
    return np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)


def _centroid_per_sec(samples: np.ndarray, sr: int) -> np.ndarray:
    hop = sr
    n = max(len(samples) // hop, 1)
    out = np.zeros(n)
    freqs = np.fft.rfftfreq(hop, 1.0 / sr)
    for i in range(n):
        chunk = samples[i * hop:(i + 1) * hop]
        if len(chunk) < hop:
            chunk = np.pad(chunk, (0, hop - len(chunk)))
        spec = np.abs(np.fft.rfft(chunk * np.hanning(hop)))
        tot = spec.sum() + 1e-9
        out[i] = float((spec * freqs).sum() / tot)
    return out


def _norm(x: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(x, 5), np.percentile(x, 95)
    if hi - lo < 1e-9:
        return np.zeros_like(x)
    return np.clip((x - lo) / (hi - lo), 0.0, 1.0)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Zа-яА-ЯёЁ']+", text.lower())


def build_features(samples: np.ndarray, words: list[dict] | None, content_type: str,
                   duration: float) -> dict:
    n = int(np.ceil(duration))
    rms = _rms_per_sec(samples, SR)[:n]
    cen = _centroid_per_sec(samples, SR)[:n]
    rms = np.pad(rms, (0, max(0, n - len(rms))))
    cen = np.pad(cen, (0, max(0, n - len(cen))))

    voiced = (rms > np.percentile(rms, 40) * 1.5).astype(float)  # грубый VAD по энергии

    kw_set = KEYWORDS_GAME if content_type == "game" else KEYWORDS_COMMON
    word_per_sec = np.zeros(n)
    kw_per_sec = np.zeros(n)
    text_per_sec = [[] for _ in range(n)]
    if words:
        for w in words:
            i = min(int(w["s"]), n - 1)
            if i < 0:
                continue
            word_per_sec[i] += 1
            text_per_sec[i].append(w["w"])
            if w["w"].lower().strip(".,!?;:") in kw_set:
                kw_per_sec[i] += 1
    else:
        word_per_sec = voiced * 2.5  # прокси плотности речи без транскрипта

    # Пауза — секунда без голоса (энергия ниже порога).
    silent = (rms < np.percentile(rms, 25) * 0.8).astype(float)

    return {
        "n": n,
        "loud": _norm(rms),
        "density": _norm(word_per_sec),
        "centroid": cen,
        "kw": kw_per_sec,
        "silent": silent,
        "rms": rms,
        "text": text_per_sec,
        "has_words": bool(words),
    }


def score_windows(feat: dict, clip_len: float, content_type: str) -> list[Candidate]:
    n = feat["n"]
    L = int(round(clip_len))
    cands: list[Candidate] = []
    if n < L:
        return cands
    cen_n = _norm(feat["centroid"])
    for s in range(0, n - L + 1):
        e = s + L
        loud = float(feat["loud"][s:e].mean())
        dens = float(feat["density"][s:e].mean())
        half = L // 2
        e1 = float(feat["rms"][s:s + half].mean())
        e2 = float(feat["rms"][s + half:e].mean())
        emo_jump = abs(e2 - e1) / (max(e1, e2) + 1e-9)
        emo = float(min(emo_jump, 1.0) * 0.6 + abs(cen_n[s + half:e].mean() - cen_n[s:s + half].mean()) * 0.4)
        kw = float(min(feat["kw"][s:e].sum() / 6.0, 1.0))
        pause = float(feat["silent"][s:e].mean())
        total = 0.25 * loud + 0.25 * dens + 0.2 * emo + 0.2 * kw + 0.1 * (1 - pause)
        parts = {"loud": loud, "density": dens, "emotion": emo, "keywords": kw, "calm": 1 - pause}
        cands.append(Candidate(start=float(s), end=float(e), score=total, parts=parts))
    return cands


def _snap_to_pause(start: float, feat: dict, max_shift: float = 1.5) -> float:
    """Сдвигает начало к ближайшей паузе, чтобы не резать фразу посередине."""
    s = int(round(start))
    best, best_d = s, None
    lo, hi = max(0, int(s - max_shift)), min(feat["n"] - 1, int(s + max_shift))
    for i in range(lo, hi + 1):
        if feat["silent"][i] > 0.5:
            d = abs(i - s)
            if best_d is None or d < best_d:
                best, best_d = i, d
    return float(best) if best_d is not None else float(s)


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(_tokens(a)), set(_tokens(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def select_clips(cands: list[Candidate], feat: dict, count: int, clip_len: float,
                 content_type: str, words: list[dict] | None) -> list[Candidate]:
    """Жадный выбор: лучшие непересекающиеся окна, без дубликатов по тексту."""
    ordered = sorted(cands, key=lambda c: c.score, reverse=True)
    chosen: list[Candidate] = []
    for c in ordered:
        if len(chosen) >= count:
            break
        if any(not (c.end <= x.start or c.start >= x.end) for x in chosen):
            continue
        c.text = " ".join(
            w["w"] for w in (words or []) if c.start <= w["s"] < c.end
        )
        if any(_jaccard(c.text, x.text) > 0.6 for x in chosen if c.text and x.text):
            continue
        c.start = _snap_to_pause(c.start, feat)
        c.end = c.start + clip_len
        if c.end > feat["n"]:
            c.end = float(feat["n"])
            c.start = c.end - clip_len
        if any(not (c.end <= x.start or c.start >= x.end) for x in chosen):
            continue
        c.reason = explain(c.parts, content_type)
        chosen.append(c)
    return sorted(chosen, key=lambda c: c.score, reverse=True)


def explain(parts: dict, content_type: str) -> str:
    labels = {
        "density": "плотная речь",
        "loud": "высокая энергия",
        "emotion": "резкая смена эмоций",
        "keywords": "сильные ключевые слова" if content_type != "game" else "игровой экшн",
        "calm": "без длинных пауз",
    }
    top = sorted(parts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return "Выбран за: " + ", ".join(labels[k] for k, _ in top)


def to_percent(score: float) -> int:
    return int(round(max(0.0, min(1.0, score)) * 100))
