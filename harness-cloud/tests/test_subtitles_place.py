"""Положение субтитров, отдельный хук и новые пресеты (ASS-теги)."""
from pathlib import Path

from harness import config, subtitles

WORDS = [{"w": "Это", "s": 0.5, "e": 0.9}, {"w": "тест", "s": 1.0, "e": 1.4}]


def _build(tmp_path, **kw):
    out = tmp_path / "sub.ass"
    subtitles.build_ass(WORDS, 6.0, kw.pop("hook", "Главный секрет"), kw.pop("style", "capcut"),
                        out, out_w=1080, out_h=1920, **kw)
    return out.read_text(encoding="utf-8-sig")


def test_subtitle_anchor_per_place(tmp_path):
    top = _build(tmp_path, place="top")
    center = _build(tmp_path, place="center")
    bottom = _build(tmp_path, place="bottom")
    assert "\\an8" in [l for l in top.splitlines() if ",Sub," in l][0]
    assert "\\an5" in [l for l in center.splitlines() if ",Sub," in l][0]
    assert "\\an2" in [l for l in bottom.splitlines() if ",Sub," in l][0]


def test_hook_moves_to_other_side_of_subtitles(tmp_path):
    top = _build(tmp_path, place="top")
    hook_line = [l for l in top.splitlines() if ",Hook," in l][0]
    assert "\\an8" in hook_line  # хук под субтитрами сверху
    bottom = _build(tmp_path, place="bottom")
    hook_line = [l for l in bottom.splitlines() if ",Hook," in l][0]
    assert "\\an2" in hook_line  # хук над субтитрами снизу


def test_drag_position_overrides_preset(tmp_path):
    text = _build(tmp_path, place="top", pos=(300.0, 900.0))
    sub_line = [l for l in text.splitlines() if ",Sub," in l][0]
    assert "\\pos(300,900)" in sub_line and "\\an2" in sub_line


def test_hook_can_be_absent(tmp_path):
    text = _build(tmp_path, hook=None)
    assert ",Hook," not in text
    assert ",Sub," in text


def test_all_presets_and_places_are_valid():
    assert config.DEFAULT_SUBTITLE_STYLE in config.SUBTITLE_STYLES
    assert set(subtitles.PLACE_ALIGN) == set(config.SUB_PLACES)
    for key, st in config.SUBTITLE_STYLES.items():
        assert st["size"] >= 90 and st["outline_w"] >= 6, key
