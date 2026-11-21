"""Качество (480p…4K) и частота кадров (20…120 fps): размеры, битрейт, API и реальный рендер."""
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness import config, render, server, storage
from harness import segments as sg

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("aspect,quality,expected", [
    ("9:16", "1080p", (1080, 1920)),
    ("16:9", "720p", (1280, 720)),
    ("4:3", "480p", (640, 480)),
    ("1:1", "2k", (1440, 1440)),
    ("9:16", "4k", (2160, 3840)),
    ("9:16", "480p", (480, 854)),   # 853.3 округляется до чётного
])
def test_out_size_follows_quality_and_aspect(aspect, quality, expected):
    assert config.out_size(aspect, quality) == expected


def test_default_quality_keeps_previous_size():
    assert config.out_size("9:16") == (1080, 1920)


@pytest.mark.parametrize("value,expected", [("20", 20), (120, 120), (59.6, 59),
                                            (19, None), (121, None), ("abc", None), (None, None)])
def test_parse_fps_range(value, expected):
    assert config.parse_fps(value) == expected


def test_bitrate_scales_with_pixels_and_fps():
    base = render._encode_args("tiktok", False, 1080, 1920, 30)
    big = render._encode_args("tiktok", False, 2160, 3840, 60)
    small = render._encode_args("tiktok", False, 480, 854, 20)
    rate = lambda args: args[args.index("-maxrate") + 1]
    assert rate(base) == "6M"
    assert float(rate(big)[:-1]) > 6 and rate(big).endswith("M")
    assert float(rate(small)[:-1]) < 6
    assert base[base.index("-r") + 1] == "30" and big[big.index("-r") + 1] == "60"


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    p = storage.create_project("/nonexistent/src.mp4", "file", "podcast", {
        "clip_count": 5, "subtitle_style": "violet", "whisper_model": "tiny",
        "export_preset": "tiktok", "framing": "face", "sub_box": False,
        "sub_emoji": False, "sub_anim": False})
    p["status"] = "done"
    p["clips"] = []
    storage.save_project(p)
    yield p
    storage.delete_project(p["id"])


class _Jobs:
    current = None

    def submit(self, pid, retry=False):
        pass

    def cancel(self, pid):
        return False

    def queued(self):
        return []


def test_restyle_stores_quality_and_fps(project):
    client = TestClient(server.create_app(jobs=_Jobs()))
    pid = project["id"]
    r = client.post(f"/api/projects/{pid}/restyle", json={"quality": "4k", "fps": 60})
    assert r.status_code == 200
    opts = storage.load_project(pid)["options"]
    assert opts["quality"] == "4k" and opts["fps"] == 60
    client.post(f"/api/projects/{pid}/restyle", json={"quality": "8k", "fps": 500})
    opts = storage.load_project(pid)["options"]
    assert opts["quality"] == "4k" and opts["fps"] == 60   # недопустимые значения игнорируются


def test_meta_lists_qualities_and_fps_range():
    meta = TestClient(server.create_app(jobs=_Jobs())).get("/api/meta").json()
    assert set(meta["qualities"]) == {"480p", "720p", "1080p", "2k", "4k"}
    assert meta["fps_min"] == 20 and meta["fps_max"] == 120
    assert 30 in meta["fps_choices"]


@pytest.mark.parametrize("aspect,quality,fps", [("9:16", "480p", 20), ("16:9", "720p", 60)])
def test_render_matches_chosen_quality_and_fps(tmp_path, aspect, quality, fps):
    src = ROOT / "tests" / "assets" / "test_talk.mp4"
    if not src.exists():
        pytest.skip("нет тестового видео: запустите tests/make_assets.py")
    w, h = config.out_size(aspect, quality)
    out = tmp_path / f"clip_{quality}_{fps}.mp4"
    res = render.render_clip(src, 20.0, 30.0, None, None, out, "tiktok", threading.Event(),
                             framing="fit", src_w=1920, src_h=1080, out_w=w, out_h=h, fps=fps)
    assert res["ok"], res
    assert (res["width"], res["height"]) == (w, h)
    assert res["fps"] == pytest.approx(fps, abs=0.5)
