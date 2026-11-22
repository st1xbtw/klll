"""Отрезки клипа: клип — список [s, e] в секундах исходника, сумма длительностей = 30 с.

Операции (для ручной правки):
  custom_clip(t)          — новый клип 30 с, начиная с t;
  cut(segments, a, b)     — вырезать [a, b] из клипа; недостающие секунды добираются из исходника
                            за концом клипа, поэтому длина остаётся 30 с;
  merge(seg_a, seg_b)     — первые 15 с клипа A + первые 15 с клипа B.
"""
from __future__ import annotations

CLIP_LEN = 30.0
EPS = 1e-3


class SegmentError(ValueError):
    pass


def total(segments: list[list[float]]) -> float:
    return sum(e - s for s, e in segments)


def span(segments: list[list[float]]) -> tuple[float, float]:
    return segments[0][0], segments[-1][1]


def split_parts(total: float, part_len: float, min_tail: float = CLIP_LEN) -> list[list[float]]:
    """Режет видео подряд с начала на части по part_len секунд.

    Хвост короче min_tail присоединяется к последней части, чтобы не появлялся огрызок.
    Поэтому последняя часть может быть длиннее part_len на величину до min_tail.
    """
    if total < min_tail or part_len <= 0:
        return []
    n = int(total // part_len)
    spans = [[round(i * part_len, 3), round((i + 1) * part_len, 3)] for i in range(n)]
    tail_start = n * part_len
    if total - tail_start >= min_tail or not spans:
        spans.append([round(tail_start, 3), round(total, 3)])
    else:
        spans[-1][1] = round(total, 3)
    return spans


def custom_clip(start: float, src_duration: float) -> list[list[float]]:
    if start < 0 or start + CLIP_LEN > src_duration + EPS:
        raise SegmentError("Клип на 30 с не помещается в видео с этой точки")
    return [[round(start, 3), round(start + CLIP_LEN, 3)]]


def _contains(segments: list[list[float]], a: float, b: float) -> bool:
    return any(s - EPS <= a and b <= e + EPS for s, e in segments)


def cut(segments: list[list[float]], a: float, b: float, src_duration: float) -> list[list[float]]:
    if not (b > a + 0.2):
        raise SegmentError("Фрагмент для вырезки слишком короткий (минимум 0.2 с)")
    if not _contains(segments, a, b):
        raise SegmentError("Фрагмент должен лежать внутри клипа")
    removed = b - a
    out: list[list[float]] = []
    for s, e in segments:
        if e <= a + EPS or s >= b - EPS:
            out.append([s, e])
            continue
        if s < a - EPS:
            out.append([s, a])
        if e > b + EPS:
            out.append([b, e])
    # Добираем недостающее время за концом последнего отрезка.
    last_end = out[-1][1]
    new_end = last_end + removed
    if new_end > src_duration + EPS:
        raise SegmentError("Не хватает материала в конце видео, чтобы добрать клип до 30 с")
    if out[-1][1] == last_end and out[-1][0] < out[-1][1]:
        out[-1] = [out[-1][0], round(new_end, 3)]
    return _normalize(out)


def merge(seg_a: list[list[float]], seg_b: list[list[float]]) -> list[list[float]]:
    half = CLIP_LEN / 2
    return _normalize(take(seg_a, half) + take(seg_b, half))


def take(segments: list[list[float]], seconds: float) -> list[list[float]]:
    """Первые seconds секунд клипа как список отрезков."""
    out: list[list[float]] = []
    left = seconds
    for s, e in segments:
        if left <= EPS:
            break
        d = min(e - s, left)
        out.append([s, round(s + d, 3)])
        left -= d
    if left > EPS:
        raise SegmentError("Клип короче, чем нужно для склейки")
    return out


def _normalize(segments: list[list[float]]) -> list[list[float]]:
    return [[round(s, 3), round(e, 3)] for s, e in segments if e - s > EPS]


def map_time(segments: list[list[float]], t: float) -> float | None:
    """Время внутри клипа для момента t исходника (None, если t вне клипа)."""
    offset = 0.0
    for s, e in segments:
        if s - EPS <= t < e - EPS:
            return offset + (t - s)
        offset += e - s
    return None


def words_for_clip(segments: list[list[float]], words: list[dict]) -> list[dict]:
    """Слова клипа с таймкодами внутри клипа (секунды от начала клипа)."""
    out: list[dict] = []
    offset = 0.0
    for s, e in segments:
        for w in words:
            if s - EPS <= w["s"] < e:
                out.append({"w": w["w"], "s": offset + (w["s"] - s),
                            "e": offset + (min(w["e"], e) - s)})
        offset += e - s
    return out
