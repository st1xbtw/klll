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



def test_subtitle_lines_never_overlap(tmp_path):
    """Паузы 0.02 с между группами слов не должны давать две реплики одновременно в одной точке."""
    words, t = [], 0.0
    for k in range(40):  # длинная речь: группы делятся по длительности и по длине строки
        words.append({"w": f"слово{k}", "s": t, "e": t + 0.3})
        t += 0.32
    out = tmp_path / "ov.ass"
    subtitles.build_ass(words, t, None, "capcut", out, out_w=1080, out_h=1920, font="Inter")
    spans = []
    for line in out.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("Dialogue:") and ",Sub," in line:
            fields = line.split(",", 9)
            spans.append((fields[1], fields[2]))

    def secs(x):
        h, m, rest = x.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)

    spans = [(secs(a), secs(b)) for a, b in spans]
    assert len(spans) >= 3
    for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
        assert b1 <= a2 + 1e-6, f"реплики пересекаются: {b1} > {a2}"


def test_new_subtitle_effects_write_expected_tags(tmp_path):
    for effect, marker in [("bounce", "\\fscx70"), ("rise", "\\alpha&HFF&"), ("fade", "\\fad(150,150)")]:
        text = _build(tmp_path, effect=effect)
        sub = [l for l in text.splitlines() if ",Sub," in l][0]
        assert marker in sub, effect
    hook_line = [l for l in _build(tmp_path, effect="bounce").splitlines() if ",Hook," in l][0]
    assert "\\fscx70" not in hook_line  # у хука своя анимация, пружина его не трогает


def test_zoom_and_drop_effects_write_expected_tags():
    from harness import config, subtitles
    assert "zoom" in config.SUB_EFFECTS and "drop" in config.SUB_EFFECTS
    zoom = subtitles._tags("zoom", 540, 1500, 2, 1920, False)
    assert "\\fscx60" in zoom and "\\t(0,200," in zoom
    drop = subtitles._tags("drop", 540, 1500, 2, 1920, False)
    assert "\\move(" in drop and "\\fad(120,0)" in drop
    # Хук не получает эти эффекты: у него своё \fad.
    assert "\\fscx60" not in subtitles._tags("zoom", 540, 1500, 2, 1920, True)
