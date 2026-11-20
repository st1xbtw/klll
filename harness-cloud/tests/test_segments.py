"""Юнит-тесты отрезков клипа (без ffmpeg)."""
import pytest

from harness import segments as sg


def test_custom_clip_is_30s_and_bounded():
    assert sg.total(sg.custom_clip(10, 100)) == pytest.approx(30)
    with pytest.raises(sg.SegmentError):
        sg.custom_clip(80, 100)


def test_cut_inside_keeps_30s_and_fills_from_source():
    segs = [[10, 40]]
    out = sg.cut(segs, 20, 23, src_duration=200)
    assert sg.total(out) == pytest.approx(30)
    assert out == [[10, 20], [23, 43]]


def test_cut_at_clip_edge_and_bounds():
    out = sg.cut([[10, 40]], 10, 12, src_duration=200)
    assert sg.total(out) == pytest.approx(30)
    with pytest.raises(sg.SegmentError):
        sg.cut([[10, 40]], 5, 8, src_duration=200)      # вне клипа
    with pytest.raises(sg.SegmentError):
        sg.cut([[10, 40]], 20, 20.1, src_duration=200)  # слишком короткий
    with pytest.raises(sg.SegmentError):
        sg.cut([[10, 40]], 20, 23, src_duration=40)     # нет материала для добора


def test_merge_takes_15s_from_each():
    out = sg.merge([[10, 40]], [[100, 130]])
    assert out == [[10, 25], [100, 115]]
    assert sg.total(out) == pytest.approx(30)


def test_merge_with_short_source_clip_is_not_possible():
    with pytest.raises(sg.SegmentError):
        sg.take([[0, 5]], 15)


def test_words_mapped_across_segments():
    segs = [[10, 15], [100, 115]]
    words = [{"w": "a", "s": 10.5, "e": 10.9}, {"w": "b", "s": 101.0, "e": 101.4},
             {"w": "x", "s": 50.0, "e": 50.2}]
    mapped = sg.words_for_clip(segs, words)
    assert [w["w"] for w in mapped] == ["a", "b"]
    assert mapped[0]["s"] == pytest.approx(0.5)
    assert mapped[1]["s"] == pytest.approx(5 + 1.0)   # второй отрезок начинается после 5 с первого
    assert sg.map_time(segs, 101.0) == pytest.approx(6.0)
    assert sg.map_time(segs, 50.0) is None


def test_subtitle_options_reach_ass(tmp_path):
    """Плашка, эмодзи и анимация попадают в ASS, по умолчанию их нет."""
    from harness import subtitles as sub
    words = [{"w": "секрет", "s": 0.2, "e": 0.6}, {"w": "денег", "s": 0.7, "e": 1.1},
             {"w": "вот", "s": 1.2, "e": 1.5}, {"w": "правда", "s": 1.6, "e": 2.1}]
    plain = sub.build_ass(words, 30, "Хук", "violet", tmp_path / "a.ass").read_text(encoding="utf-8")
    assert "\\t(" not in plain and ",3,&HA0000000&" not in plain
    fancy = sub.build_ass(words, 30, "Хук", "violet", tmp_path / "b.ass",
                          box=True, anim=True, emoji=True).read_text(encoding="utf-8")
    assert "\\t(" in fancy                       # анимация появления
    assert "🔑" in fancy or "💰" in fancy        # эмодзи из карты
    assert "BorderStyle" in fancy or ",3," in fancy   # плашка


def test_subtitles_and_hook_always_bottom(tmp_path):
    """Все стили и хук выравниваются по низу (alignment 2), размер PlayRes совпадает с кадром."""
    from harness import config, subtitles as sub
    words = [{"w": "секрет", "s": 0.2, "e": 0.6}, {"w": "денег", "s": 0.7, "e": 1.1}]
    for key in config.SUBTITLE_STYLES:
        for aspect, (w, h) in config.ASPECTS.items():
            text = sub.build_ass(words, 30, "Хук дня", key, tmp_path / f"{key}_{w}.ass",
                                 out_w=w, out_h=h).read_text(encoding="utf-8")
            assert f"PlayResX: {w}" in text and f"PlayResY: {h}" in text
            style_lines = [l for l in text.splitlines() if l.startswith("Style:")]
            assert len(style_lines) == 2
            for line in style_lines:
                fields = line.split(",")
                assert fields[18] == "2", line          # Alignment: нижний центр
                assert int(fields[21]) > 0, line        # MarginV: отступ от низа
            assert "\\an8" not in text and "\\an5" not in text


def test_subtitles_off_removes_text_and_hook(tmp_path):
    from harness import subtitles as sub
    words = [{"w": "секрет", "s": 0.2, "e": 0.6}]
    text = sub.build_ass(words, 30, "Хук", "violet", tmp_path / "off.ass",
                         subtitles=False).read_text(encoding="utf-8")
    assert "Dialogue: 0," not in text   # без субтитров
    assert "Dialogue: 1," in text       # хук выводится, если передан
    text2 = sub.build_ass(words, 30, None, "violet", tmp_path / "off2.ass",
                          subtitles=False).read_text(encoding="utf-8")
    assert "Dialogue:" not in text2
