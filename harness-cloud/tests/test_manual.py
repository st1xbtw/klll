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


def test_font_upload_rejects_non_font(client, tmp_path):
    bad = tmp_path / "bad.ttf"
    bad.write_bytes(b"not a font at all")
    with open(bad, "rb") as fh:
        r = client.post("/api/fonts", files={"file": ("bad.ttf", fh, "font/ttf")})
    assert r.status_code == 400
    with open(bad, "rb") as fh:
        r = client.post("/api/fonts", files={"file": ("bad.txt", fh, "text/plain")})
    assert r.status_code == 400


def test_font_list_endpoint(client):
    r = client.get("/api/fonts")
    assert r.status_code == 200
    body = r.json()
    assert any(f["family"] == "Inter" for f in body["fonts"])
    assert set(body["effects"]) >= {"none", "fade", "slide", "glow", "pop"}


def test_subtitle_position_and_font_via_restyle(client, project):
    pid = project["id"]
    r = client.post(f"/api/projects/{pid}/restyle",
                    json={"sub_x": 40, "sub_y": 60.5, "sub_font": "Inter", "sub_effect": "glow"})
    assert r.status_code == 200
    p = storage.load_project(pid)
    assert p["options"]["sub_x"] == 40 and p["options"]["sub_y"] == 60.5
    assert p["options"]["sub_font"] == "Inter" and p["options"]["sub_effect"] == "glow"
    assert all(c["sub_x"] == 40 and c["sub_font"] == "Inter" for c in p["clips"])
    r = client.post(f"/api/projects/{pid}/restyle", json={"sub_x": None, "sub_y": None})
    assert r.status_code == 200
    assert storage.load_project(pid)["options"]["sub_x"] is None


@pytest.mark.parametrize("effect", ["fade", "slide", "glow"])
def test_render_with_font_position_and_effect(tmp_path, effect):
    """Сгенерированный ASS с встроенным шрифтом, позицией и эффектом проходит реальный рендер."""
    from harness import fonts, subtitles as sub
    src = ROOT / "tests" / "assets" / "test_talk.mp4"
    if not src.exists():
        pytest.skip("нет тестового видео: запустите tests/make_assets.py")
    clip_dir = tmp_path / "clip"
    clip_dir.mkdir()
    family = fonts.copy_for_clip("DejaVu Sans", clip_dir)
    assert family == "DejaVu Sans" and (clip_dir / "fonts" / "DejaVuSans.ttf").exists()
    words = [{"w": "секрет", "s": 1.0, "e": 1.6}, {"w": "денег", "s": 1.7, "e": 2.3}]
    ass = sub.build_ass(words, 30, "Хук дня", "violet", clip_dir / "sub.ass", font=family,
                        pos=(540.0, 1100.0), effect=effect, out_w=1080, out_h=1920)
    res = render.render_clip(src, 20.0, 30.0, None, ass, clip_dir / "clip.mp4", "tiktok",
                             threading.Event(), framing="fit", src_w=1920, src_h=1080,
                             out_w=1080, out_h=1920)
    assert res["ok"], res
    assert res["duration"] == pytest.approx(30, abs=0.5)
