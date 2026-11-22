"""Фильтр рекламных вставок и отбор клипов без рекламы."""
import numpy as np

from harness import adfilter, scoring


def test_strong_ad_words_mark_window():
    assert adfilter.is_ad_text("сегодня спонсор стрима — промокод НАСТЯ, скидка 10%")
    assert adfilter.is_ad_text("this video is sponsored, use code FOO")


def test_weak_phrases_need_two_hits():
    assert not adfilter.is_ad_text("ссылка в описании, но больше ничего")
    assert adfilter.is_ad_text("подписывайтесь и ссылка в описании")


def test_normal_talk_is_not_ad():
    assert not adfilter.is_ad_text("мы обсуждали игру и новый патч, все согласны")
    assert not adfilter.is_ad_text("")


def test_select_clips_skips_ad_window_and_keeps_others():
    words = []
    t = 0.0
    # Окно 0–30 с — рекламная вставка, 30–60 с — обычный разговор.
    for w in "сегодня спонсор промокод скидка".split() * 3:
        words.append({"w": w, "s": t, "e": t + 0.4}); t += 0.5
    t = 30.0
    for w in "мы обсуждали новый патч и игру подробно".split() * 2:
        words.append({"w": w, "s": t, "e": t + 0.4}); t += 0.5
    feat = {"n": 120, "silent": np.zeros(120)}
    cands = [scoring.Candidate(0.0, 30.0, 0.95, {}), scoring.Candidate(30.0, 60.0, 0.8, {})]
    chosen = scoring.select_clips(cands, feat, 2, 30.0, "podcast", words)
    texts = [c.text for c in chosen]
    assert all("промокод" not in t for t in texts)
    assert any("патч" in t for t in texts)
