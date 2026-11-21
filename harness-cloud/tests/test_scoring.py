"""Поиск сильных моментов: динамика, а не средняя громкость."""
import numpy as np

from harness import scoring
from harness.audio import SR


def _synthetic(seconds=150):
    rng = np.random.default_rng(0)
    n = seconds * SR
    t = np.arange(n) / SR
    x = rng.normal(0, 0.02, n)                       # фон: тихая речь
    flat = (t >= 20) & (t < 50)
    x[flat] = rng.normal(0, 0.25, flat.sum())        # громко, но ровно (гул, музыка)
    ramp = (t >= 88) & (t < 93)
    env = np.interp(t[ramp], [88, 93], [0.03, 0.6])  # нарастание к кульминации
    x[ramp] = env * np.sin(2 * np.pi * 220 * t[ramp])
    burst = (t >= 93) & (t < 95)
    x[burst] = 0.6 * np.sign(np.sin(2 * np.pi * 3 * t[burst]))  # резкий удар
    return x


def test_dynamic_moment_beats_flat_loud_section():
    x = _synthetic()
    feat = scoring.build_features(x, None, "podcast", 150)
    cands = scoring.score_windows(feat, 30, "podcast")
    best = max(cands, key=lambda c: c.score)
    assert best.start <= 93 and best.end >= 95, (best.start, best.end)

    flat = max((c for c in cands if c.start >= 20 and c.end <= 50), key=lambda c: c.score)
    assert best.score > flat.score


def test_selection_is_non_overlapping_and_explained():
    x = _synthetic()
    feat = scoring.build_features(x, None, "podcast", 150)
    cands = scoring.score_windows(feat, 30, "podcast")
    chosen = scoring.select_clips(cands, feat, 3, 30, "podcast", None)
    assert chosen
    for a in chosen:
        for b in chosen:
            if a is not b:
                assert a.end <= b.start or a.start >= b.end
        assert a.reason.startswith("Выбран за:")
