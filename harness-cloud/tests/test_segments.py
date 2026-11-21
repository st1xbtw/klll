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
            assert len(style_lines) == 3              # Sub, Hook, Mark
            for line in style_lines:
                fields = line.split(",")
                name = fields[0].split(":")[1].strip()
                if name == "Mark":
                    assert fields[18] == "9", line      # водяной знак: верхний правый угол
                else:
                    assert fields[18] == "2", line      # субтитры и хук: нижний центр
                    assert int(fields[21]) > 0, line    # MarginV: отступ от низа
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


def test_watermark_top_right_whole_clip(tmp_path):
    """Водяной знак: стиль Mark, выравнивание 9 (верхний правый угол), на весь клип, экранируется."""
    from harness import subtitles as sub
    text = sub.build_ass([], 30, None, "violet", tmp_path / "wm.ass", subtitles=False,
                         watermark="{@канал}\\x").read_text(encoding="utf-8")
    mark_style = [l for l in text.splitlines() if l.startswith("Style: Mark")][0]
    assert mark_style.split(",")[18] == "9"
    dialog = [l for l in text.splitlines() if ",Mark,," in l]
    assert len(dialog) == 1 and dialog[0].startswith("Dialogue: 2,0:00:00.00,0:00:30.00")
    assert "{" not in dialog[0].split(",,", 1)[1] and "\\x" not in dialog[0]


def test_font_position_effects_in_ass(tmp_path):
    from harness import subtitles as sub
    words = [{"w": "секрет", "s": 0.2, "e": 0.6}, {"w": "денег", "s": 0.7, "e": 1.1}]
    # шрифт попадает в стили всех строк
    ass = sub.build_ass(words, 30, "Хук", "violet", tmp_path / "f.ass", font="DejaVu Sans",
                        out_w=1080, out_h=1920).read_text(encoding="utf-8")
    assert ass.count("Style: Sub,DejaVu Sans,") == 1 and ",DejaVu Sans,70," in ass
    # по умолчанию субтитры не получают \pos — стандартное место внизу
    dlg = [l for l in ass.splitlines() if l.startswith("Dialogue: 0,")][0]
    assert "\\pos(" not in dlg and "\\move(" not in dlg
    # позиция: \pos в каждой реплике субтитров
    moved = sub.build_ass(words, 30, None, "violet", tmp_path / "p.ass", pos=(300.0, 900.0),
                          out_w=1080, out_h=1920).read_text(encoding="utf-8")
    assert all("\\pos(300,900)" in l for l in moved.splitlines() if l.startswith("Dialogue: 0,"))
    # эффекты: плавное появление, выезд, свечение, всплеск (= анимация слов)
    fade = sub.build_ass(words, 30, None, "violet", tmp_path / "e1.ass", effect="fade",
                         out_w=1080, out_h=1920).read_text(encoding="utf-8")
    assert "\\fad(150,150)" in fade
    slide = sub.build_ass(words, 30, None, "violet", tmp_path / "e2.ass", effect="slide",
                          out_w=1080, out_h=1920).read_text(encoding="utf-8")
    assert "\\move(" in slide
    glow = sub.build_ass(words, 30, None, "violet", tmp_path / "e3.ass", effect="glow",
                         out_w=1080, out_h=1920).read_text(encoding="utf-8")
    assert "\\blur2" in glow
    pop = sub.build_ass(words, 30, None, "violet", tmp_path / "e4.ass", effect="pop",
                        out_w=1080, out_h=1920).read_text(encoding="utf-8")
    assert "\\t(" in pop


def test_font_names_are_sanitized():
    from harness import server
    assert server._clean_family("Inter") == "Inter"
    assert server._clean_family("DejaVu Sans") == "DejaVu Sans"
    assert server._clean_family("Bad,Name") == "" and server._clean_family("x}{y") == ""
    assert server._pct("150") == 100.0 and server._pct("-3") == 0.0 and server._pct(None) is None
    assert server._pct("abc") is None


def test_bundled_fonts_listed():
    from harness import fonts
    fams = [f["family"] for f in fonts.list_fonts()]
    assert "DejaVu Sans" in fams and "Inter" in fams
    assert fonts.resolve("DejaVu Sans") is not None
    assert fonts.resolve("No Such Font") is None
    assert fonts.resolve("a,b") is None
