"""Модули 5–6: поиск сильных моментов и ранжирование.

Сильный момент — это не «громко в среднем», а динамика: что-то резко меняется на фоне остального видео.
Признаки считаются по секундам и нормируются по всему видео:
  peak      — пик громкости относительно локального фона (контраст в 2^k раз, окно фона 31 с)
  burst     — доля секунд окна, где громкость выше фона примерно вдвое
  rise      — нарастание: вторая половина окна громче первой (сборка к кульминации)
  variance  — разброс громкости внутри окна (ровный шум не набирает баллы)
  hits      — резкие удары: скачки громкости больше 6 дБ за 0.1 с
  tempo     — смена темпа речи (слов/сек относительно соседних секунд; без текста — энергия речи)
  keywords  — ключевые слова (словарь зависит от типа контента)
Штрафы: много пауз, нет пика вообще.
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


def _db_per_tenth(samples: np.ndarray, sr: int) -> np.ndarray:
    hop = max(sr // 10, 1)
    n = max(len(samples) // hop, 1)
    if len(samples) >= hop:
        frames = samples[: n * hop].reshape(n, hop)
    else:
        frames = np.pad(samples, (0, hop - len(samples)))[None, :]
    return 20.0 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12) + 1e-6)


def _rolling_median(x: np.ndarray, win: int) -> np.ndarray:
    pad = win // 2
    padded = np.pad(x, (pad, pad), mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(padded, win)
    return np.median(view, axis=1)


def build_features(samples: np.ndarray, words: list[dict] | None, content_type: str,
                   duration: float) -> dict:
    n = int(np.ceil(duration))
    rms = _rms_per_sec(samples, SR)[:n]
    cen = _centroid_per_sec(samples, SR)[:n]
    rms = np.pad(rms, (0, max(0, n - len(rms))))
    cen = np.pad(cen, (0, max(0, n - len(cen))))

    # Контраст с фоном: громкость секунды относительно медианы соседних 31 секунд.
    baseline = _rolling_median(rms, 31)
    contrast = np.log2((rms + 1e-6) / (baseline + 1e-6))  # 1.0 = вдвое громче фона
    up = np.clip(contrast, 0.0, 3.0) / 3.0

    # Резкие удары: скачки громкости больше 6 дБ между соседними десятыми долями секунды.
    db = _db_per_tenth(samples, SR)
    jumps = np.diff(db, prepend=db[0]) > 6.0
    per_sec = int(np.ceil(len(jumps) / 10.0))
    jumps = np.pad(jumps.astype(float), (0, per_sec * 10 - len(jumps)))
    hits = jumps.reshape(per_sec, 10).sum(axis=1)[:n]
    hits = np.pad(hits, (0, max(0, n - len(hits))))

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
        word_per_sec = (rms > np.percentile(rms, 40) * 1.5).astype(float) * 2.5  # прокси темпа речи

    # Темп: сглаженная плотность речи за 5 секунд; смена темпа — разница с соседним окном.
    tempo = np.convolve(word_per_sec, np.ones(5) / 5.0, mode="same")

    # Пауза — секунда без голоса (энергия ниже порога).
    silent = (rms < np.percentile(rms, 25) * 0.8).astype(float)

    return {
        "n": n,
        "rms": rms,
        "loud": _norm(rms),  # для полосы громкости в редакторе
        "contrast": contrast,
        "up": up,
        "hits": hits,
        "tempo": tempo,
        "centroid": cen,
        "kw": kw_per_sec,
        "silent": silent,
        "text": text_per_sec,
        "has_words": bool(words),
    }


WEIGHTS = {"peak": 0.22, "burst": 0.13, "rise": 0.15, "variance": 0.15,
           "hits": 0.13, "tempo": 0.10, "keywords": 0.12}


def score_windows(feat: dict, clip_len: float, content_type: str) -> list[Candidate]:
    n = feat["n"]
    L = int(round(clip_len))
    if n < L:
        return []
    half = L // 2
    rms, up, contrast = feat["rms"], feat["up"], feat["contrast"]
    hits, tempo, silent, kwv = feat["hits"], feat["tempo"], feat["silent"], feat["kw"]

    starts = np.arange(0, n - L + 1)
    raw = {k: np.zeros(len(starts)) for k in WEIGHTS}
    pause = np.zeros(len(starts))
    for j, s in enumerate(starts):
        e = s + L
        raw["peak"][j] = up[s:e].max()
        raw["burst"][j] = float((up[s:e] > 0.33).mean())
        raw["rise"][j] = max(0.0, contrast[s + half:e].mean() - contrast[s:s + half].mean())
        seg = rms[s:e]
        raw["variance"][j] = float(seg.std() / (seg.mean() + 1e-9))
        raw["hits"][j] = float(hits[s:e].sum()) / L
        t = tempo[s:e]
        raw["tempo"][j] = float(t.std() / (t.mean() + 0.5))
        raw["keywords"][j] = float(min(kwv[s:e].sum() / 6.0, 1.0))
        pause[j] = float(silent[s:e].mean())

    norm = {k: _norm(v) for k, v in raw.items()}
    total = sum(WEIGHTS[k] * norm[k] for k in WEIGHTS)
    # Штрафы: почти тишина и много пауз; ровное видео без пиков не должно выигрывать.
    total = total - 0.3 * np.clip(pause - 0.35, 0.0, 1.0) - 0.2 * (raw["peak"] < 0.2)

    cands: list[Candidate] = []
    for j, s in enumerate(starts):
        parts = {k: float(norm[k][j]) for k in WEIGHTS}
        cands.append(Candidate(start=float(s), end=float(s + L), score=float(max(total[j], 0.0)), parts=parts))
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
        "peak": "резкий всплеск громкости",
        "burst": "несколько всплесков подряд",
        "rise": "нарастание к кульминации",
        "variance": "перепады громкости",
        "hits": "резкие удары звука",
        "tempo": "смена темпа речи",
        "keywords": "сильные ключевые слова" if content_type != "game" else "игровой экшн",
    }
    top = sorted(parts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return "Выбран за: " + ", ".join(labels[k] for k, _ in top)


def to_percent(score: float) -> int:
    return int(round(max(0.0, min(1.0, score)) * 100))
