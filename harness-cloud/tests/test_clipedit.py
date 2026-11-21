"""Правка текста субтитров, предпросмотр клипа и уведомления."""
import json
import subprocess
import sys

import pytest

from harness import clipedit, notify, tools, winproc


def test_retime_keeps_timings_when_word_count_matches():
    base = [{"w": "а", "s": 0.0, "e": 0.4}, {"w": "б", "s": 0.5, "e": 0.9}]
    out = clipedit.retime("раз два", base, 2.0)
    assert [(w["w"], w["s"], w["e"]) for w in out] == [("раз", 0.0, 0.4), ("два", 0.5, 0.9)]


def test_retime_spreads_words_evenly_when_count_differs():
    out = clipedit.retime("один два три", [], 3.0)
    assert [w["w"] for w in out] == ["один", "два", "три"]
    assert out[0]["s"] == 0 and out[-1]["s"] == pytest.approx(2.0)
    assert all(w["e"] > w["s"] for w in out)


def test_normalize_text_collapses_spaces_and_limits_length():
    assert clipedit.normalize_text("  привет   мир \n") == "привет мир"
    with pytest.raises(ValueError):
        clipedit.normalize_text("я" * (clipedit.MAX_TEXT_CHARS + 1))


def test_winproc_and_notify_are_noops_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert winproc.hidden_kwargs() == {}
    assert notify.show("Harness Cloud", "готово") is False


def test_preview_renders_four_seconds_at_480p(tmp_path):
    src = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=1280x720:rate=30:duration=10", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=10", "-shortest", "-c:v", "libx264",
                    "-c:a", "aac", str(src)], check=True)
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": [
        {"start": 0.5, "end": 3.0, "text": "тестовый текст для предпросмотра", "words": [
            {"w": "тестовый", "s": 0.5, "e": 1.0},
            {"w": "текст", "s": 1.1, "e": 1.6},
            {"w": "для", "s": 1.7, "e": 2.0},
            {"w": "предпросмотра", "s": 2.1, "e": 3.0}]}]}), encoding="utf-8")
    proj = {"source_file": "source.mp4", "content_type": "talk", "src_w": 1280, "src_h": 720,
            "options": {"export_preset": "tiktok"}}
    clip = {"index": 1, "start": 0.0, "end": 30.0, "segments": [[0.0, 30.0]], "aspect": "9:16",
            "framing": "center", "style": "capcut", "subtitles": True, "show_hook": False,
            "hook": "", "sub_font": None, "watermark": "", "sub_x": None, "sub_y": None}
    out = clipedit.render_preview(proj, clip, tmp_path)
    assert out.exists() and out.name == "preview.mp4"
    probe = subprocess.run([tools.ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height:format=duration",
                            "-of", "json", str(out)], capture_output=True, text=True, check=True)
    info = json.loads(probe.stdout)
    assert (info["streams"][0]["width"], info["streams"][0]["height"]) == (480, 854)
    assert float(info["format"]["duration"]) == pytest.approx(4.0, abs=0.3)
