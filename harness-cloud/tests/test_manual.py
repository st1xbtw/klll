"""Ручная правка клипов: API (без ffmpeg) и рендер склеенного клипа с фоном «fit»."""
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness import render, server, storage
from harness import segments as sg

ROOT = Path(__file__).resolve().parent.parent


class _Jobs:
    current = None

    def __init__(self):
        self.submitted = []

    def submit(self, pid, retry=False):
        self.submitted.append((pid, retry))

    def cancel(self, pid):
        return False

    def queued(self):
        return []


def _clip(index: int, start: float, segs=None) -> dict:
    segs = segs or [[start, start + 30]]
    s, e = sg.span(segs)
    return {"index": index, "start": s, "end": e, "original_start": s, "original_end": e,
            "segments": segs, "origin": "auto", "framing": "face", "sub_box": False,
            "sub_emoji": False, "sub_anim": False, "duration": 30, "score": 50, "parts": {},
            "reason": "", "text": "", "hook": "", "hook_source": "", "description": "",
            "hashtags": [], "platforms": {}, "status": "done", "error": None,
            "file": f"clips/clip_{index}.mp4", "thumb": None, "verify": None,
            "subtitles": True, "style": "violet", "timeline": [0.5] * 240}


@pytest.fixture()
def project():
    p = storage.create_project("/nonexistent/src.mp4", "file", "podcast", {
        "clip_count": 5, "subtitle_style": "violet", "whisper_model": "tiny",
        "export_preset": "tiktok", "framing": "face", "sub_box": False,
        "sub_emoji": False, "sub_anim": False})
    p["status"] = "done"
    p["duration"] = 240.0
    p["src_w"], p["src_h"] = 1920, 1080
    p["clips"] = [_clip(1, 10), _clip(2, 100)]
    storage.save_project(p)
    yield p
    storage.delete_project(p["id"])


@pytest.fixture()
def client():
    jobs = _Jobs()
    c = TestClient(server.create_app(jobs=jobs))
    c.jobs = jobs
    return c


def test_custom_clip_from_point(client, project):
    pid = project["id"]
    r = client.post(f"/api/projects/{pid}/clips/custom", json={"start": 50})
    assert r.status_code == 200 and r.json()["index"] == 3
    clip = storage.load_project(pid)["clips"][-1]
    assert clip["segments"] == [[50, 80]]
    assert clip["origin"] == "manual" and clip["score"] is None
    assert clip["status"] == "queued"
    assert client.jobs.submitted[-1] == (pid, True)


def test_custom_clip_bounds(client, project):
    pid = project["id"]
    assert client.post(f"/api/projects/{pid}/clips/custom", json={"start": 230}).status_code == 400
    assert client.post(f"/api/projects/{pid}/clips/custom", json={"start": -1}).status_code == 400


def test_cut_inside_clip_builds_two_segments(client, project):
    pid = project["id"]
    r = client.post(f"/api/projects/{pid}/clips/1/cut", json={"a": 20, "b": 23})
    assert r.status_code == 200
    clip = storage.load_project(pid)["clips"][0]
    assert clip["segments"] == [[10, 20], [23, 43]]
    assert clip["start"] == 10 and clip["end"] == 43
    assert clip["status"] == "queued" and clip["file"] is None


def test_cut_outside_clip_is_rejected(client, project):
    pid = project["id"]
    assert client.post(f"/api/projects/{pid}/clips/1/cut", json={"a": 60, "b": 63}).status_code == 400
    assert client.post(f"/api/projects/{pid}/clips/1/cut", json={"a": 20}).status_code == 400


def test_merge_two_clips(client, project):
    pid = project["id"]
    r = client.post(f"/api/projects/{pid}/clips/merge", json={"a": 1, "b": 2})
    assert r.status_code == 200
    new = storage.load_project(pid)["clips"][-1]
    assert new["origin"] == "merged" and new["index"] == 3
    assert sg.total(new["segments"]) == pytest.approx(30)
    assert new["segments"] == [[10, 25], [100, 115]]


def test_merge_same_clip_rejected(client, project):
    assert client.post(f"/api/projects/{project['id']}/clips/merge", json={"a": 1, "b": 1}).status_code == 400


def test_shift_refused_for_multi_segment_clip(client, project):
    pid = project["id"]
    client.post(f"/api/projects/{pid}/clips/1/cut", json={"a": 20, "b": 23})
    r = client.post(f"/api/projects/{pid}/clips/1/shift", json={"shift": 1})
    assert r.status_code == 400


def test_edit_refused_while_running(client, project):
    pid = project["id"]
    p = storage.load_project(pid)
    p["status"] = "running"
    storage.save_project(p)
    assert client.post(f"/api/projects/{pid}/clips/custom", json={"start": 50}).status_code == 409


def test_restyle_passes_framing_and_subtitle_flags(client, project):
    pid = project["id"]
    r = client.post(f"/api/projects/{pid}/restyle",
                    json={"framing": "fit", "sub_box": True, "sub_emoji": True, "sub_anim": "0"})
    assert r.status_code == 200
    p = storage.load_project(pid)
    assert p["options"]["framing"] == "fit"
    assert p["options"]["sub_box"] is True and p["options"]["sub_emoji"] is True
    assert p["options"]["sub_anim"] is False
    assert all(c["framing"] == "fit" and c["sub_box"] for c in p["clips"])


def test_flag_parsing_from_form_strings():
    assert server._flag("0") is False and server._flag("false") is False
    assert server._flag("1") is True and server._flag(True) is True and server._flag(None) is False


def test_render_merged_clip_fit_framing(tmp_path):
    """Склейка двух отрезков с фоном «fit» даёт 1080×1920, 30 с и звук."""
    src = ROOT / "tests" / "assets" / "test_talk.mp4"
    if not src.exists():
        pytest.skip("нет тестового видео: запустите tests/make_assets.py")
    out = tmp_path / "merged_fit.mp4"
    render.render_segments(src, [(10.0, 25.0), (100.0, 115.0)], [None, None], "fit",
                           1920, 1080, None, out, "tiktok", threading.Event())
    v = render.verify(out)
    assert v["ok"], v
    assert (v["width"], v["height"]) == (1080, 1920)
    assert v["duration"] == pytest.approx(30, abs=0.5)


@pytest.mark.parametrize("aspect", ["16:9", "4:3", "1:1"])
def test_render_other_aspects(tmp_path, aspect):
    """Формат кадра из опций: размер выхода совпадает с выбранным соотношением, фон fit."""
    from harness import config
    src = ROOT / "tests" / "assets" / "test_talk.mp4"
    if not src.exists():
        pytest.skip("нет тестового видео: запустите tests/make_assets.py")
    w, h = config.out_size(aspect)
    out = tmp_path / f"clip_{aspect.replace(':', '_')}.mp4"
    res = render.render_clip(src, 20.0, 30.0, None, None, out, "tiktok", threading.Event(),
                             framing="fit", src_w=1920, src_h=1080, out_w=w, out_h=h)
    assert res["ok"], res
    assert (res["width"], res["height"]) == (w, h)
    assert res["duration"] == pytest.approx(30, abs=0.5)
