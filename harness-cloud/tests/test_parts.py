"""Видео по частям: нарезка подряд с самого начала видео, без выбора моментов."""
import os
import sys
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "tests" / "assets"
os.environ.setdefault("HARNESS_DATA_DIR", tempfile.mkdtemp(prefix="hc_parts_"))
sys.path.insert(0, str(ROOT))

from harness import config, pipeline, segments as sg, storage, tools  # noqa: E402
from tests import make_assets  # noqa: E402


def test_split_parts_cover_video_from_start():
    assert sg.split_parts(300, 60) == [[0, 60], [60, 120], [120, 180], [180, 240], [240, 300]]


def test_split_parts_merges_short_tail_into_last_part():
    spans = sg.split_parts(310, 60)
    assert len(spans) == 5 and spans[0] == [0, 60] and spans[-1] == [240, 310]


def test_split_parts_keeps_tail_when_long_enough():
    assert sg.split_parts(100, 60) == [[0, 60], [60, 100]]


def test_split_parts_short_video():
    assert sg.split_parts(20, 60) == []
    assert sg.split_parts(45, 60) == [[0, 45]]


def test_clamp_clip_len_limits_range():
    assert config.clamp_clip_len(5) == config.PART_MIN
    assert config.clamp_clip_len(999) == config.PART_MAX
    assert config.clamp_clip_len("abc") == float(config.DEFAULT_CLIP_LEN)
    assert config.clamp_clip_len(90) == 90.0


@pytest.mark.slow
def test_parts_pipeline_cuts_consecutively_from_start():
    assets_video = ASSETS / "test_talk.mp4"
    if not assets_video.exists():
        make_assets.generate(ASSETS)
    duration = float(tools.probe(assets_video)["duration"])
    part = 60.0
    expected = sg.split_parts(duration, part)
    assert len(expected) >= 2, "синтетическое видео должно давать минимум две части"

    proj = storage.create_project(str(assets_video), "file", "parts", {
        "clip_len": part, "quality": "480p", "whisper_model": "base", "export_preset": "tiktok",
        "transcript_override": str(ASSETS / "transcript.json")})
    res = pipeline.run(proj["id"], threading.Event())
    assert res["status"] == "done", res.get("error")

    clips = sorted(res["clips"], key=lambda c: c["index"])
    assert [c["index"] for c in clips] == list(range(1, len(expected) + 1))
    for clip, (start, end) in zip(clips, expected):
        assert clip["segments"][0][0] == pytest.approx(start, abs=0.01)
        assert clip["segments"][-1][1] == pytest.approx(end, abs=0.01)
        assert clip["reason"] == f"Часть {clip['index']} из {len(expected)}"
        assert clip["score"] is None
        path = storage.project_dir(proj["id"]) / clip["file"]
        assert abs(float(tools.probe(path)["duration"]) - (end - start)) <= config.CLIP_TOL + 0.5
