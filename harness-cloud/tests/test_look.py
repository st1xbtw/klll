"""Постановка клипа: сдвиг и зум кадра, блюр, размер субтитров, эндпоинт /look."""
import pytest
from fastapi.testclient import TestClient

from harness import pipeline, render, server, storage, subtitles as sub


class _Jobs:
    def __init__(self):
        self.submitted = []

    def submit(self, pid, retry=False):
        self.submitted.append((pid, retry))

    def cancel(self, pid):
        return False

    def queued(self):
        return []


@pytest.fixture()
def project(monkeypatch):
    proj = {"id": "p1", "status": "done", "duration": 600,
            "clips": [{"index": 1, "file": "clip.mp4", "status": "done", "layout": "game",
                       "webcam_corner": "br", "webcam_size": 25}]}
    saved = []
    monkeypatch.setattr(storage, "load_project", lambda pid: proj)
    monkeypatch.setattr(storage, "save_project", lambda p: saved.append(p))
    return proj, saved


@pytest.fixture()
def jobs():
    return _Jobs()


@pytest.fixture()
def client(jobs):
    return TestClient(server.create_app(jobs=jobs))


def test_default_crop_is_unchanged_without_look():
    """Без постановки фильтр остаётся прежним: центрированный кроп."""
    chain = render._framing_chain(None, "face", 1920, 1080)
    assert "crop=ih*1080/1920:ih:(iw-ih*1080/1920)/2:0" in chain


def test_centered_manual_look_matches_default_position():
    """Сдвиг 50 и зум 0 дают центр кадра, а не распознавание лица."""
    look = {"pan_x": 50, "pan_y": 50, "zoom": 0, "blur": 40}
    assert not render._manual_crop(look)
    assert render._manual_crop({**look, "pan_x": 20})


def test_manual_pan_and_zoom_replace_face_plan():
    class Plan:  # план лица не должен использоваться, когда задана ручная постановка
        keys = []
        crop_w = 10
        crop_h = 10

    chain = render._framing_chain(Plan(), "face", 1920, 1080,
                                  look={"pan_x": 0, "pan_y": 100, "zoom": 50, "blur": 40})
    assert "crop=w='min(iw,ih*0.56250*0.7500)'" in chain
    assert "x='(iw-min(iw,ih*0.56250*0.7500))*0.0000'" in chain
    assert "y='(ih-ih*0.7500)*1.0000'" in chain
    assert "crop=10:10" not in chain


def test_split_layout_uses_manual_crop_for_game_area():
    chain = render._framing_chain(None, "face", 1920, 1080, layout="webcam_bottom",
                                  look={"pan_x": 70, "pan_y": 50, "zoom": 10, "blur": 40})
    assert "[gsrc]crop=w='min(iw,ih*0.87097*0.9500)'" in chain
    assert "vstack" in chain


def test_blur_strength_reaches_fit_background():
    chain = render._framing_chain(None, "fit", 1920, 1080, look={"blur": 17})
    assert "boxblur=luma_radius=17:luma_power=2" in chain
    assert "luma_radius=40" not in chain


def test_look_values_are_clamped_to_bounds():
    clip = {"pan_x": "999", "pan_y": -5, "zoom": 80, "blur": 1, "sub_scale": None}
    assert pipeline.look_of(clip) == {"pan_x": 100, "pan_y": 0, "zoom": 50, "blur": 5}
    assert pipeline.look_of({}) == {"pan_x": 50, "pan_y": 50, "zoom": 0, "blur": 40}


def test_subtitle_scale_changes_font_size(tmp_path):
    words = [{"w": "секрет", "s": 0.2, "e": 0.6}, {"w": "денег", "s": 0.7, "e": 1.1}]
    base = sub.build_ass(words, 30, None, "violet", tmp_path / "a.ass").read_text(encoding="utf-8")
    big = sub.build_ass(words, 30, None, "violet", tmp_path / "b.ass", scale=150).read_text(encoding="utf-8")
    small = sub.build_ass(words, 30, None, "violet", tmp_path / "c.ass", scale=50).read_text(encoding="utf-8")

    def size(text):
        line = next(x for x in text.splitlines() if x.startswith("Style: Sub,"))
        return int(line.split(",")[2])

    assert size(small) < size(base) < size(big)


def test_look_endpoint_rejects_bad_values(client, project):
    assert client.post("/api/projects/p1/clips/1/look", json={"layout": "random"}).status_code == 400
    assert client.post("/api/projects/p1/clips/1/look", json={"webcam_corner": "xx"}).status_code == 400
    assert client.post("/api/projects/p1/clips/1/look", json={"sub_place": "left"}).status_code == 400
    assert client.post("/api/projects/p1/clips/1/look", json={}).status_code == 400
    assert client.post("/api/projects/p1/clips/9/look", json={"zoom": 5}).status_code == 404


def test_look_endpoint_requeues_clip_with_clamped_values(client, project, jobs):
    proj, saved = project
    r = client.post("/api/projects/p1/clips/1/look",
                    json={"layout": "webcam_top", "zoom": 90, "pan_x": 30, "blur": 2, "sub_scale": 130})
    assert r.status_code == 200
    clip = proj["clips"][0]
    assert clip["layout"] == "webcam_top"
    assert clip["zoom"] == 50 and clip["pan_x"] == 30 and clip["blur"] == 5 and clip["sub_scale"] == 130
    assert clip["status"] == "queued" and clip["file"] is None
    assert saved and jobs.submitted == [("p1", True)]


def test_look_endpoint_refuses_while_running(client, project, monkeypatch):
    proj, _ = project
    proj["status"] = "running"
    assert client.post("/api/projects/p1/clips/1/look", json={"zoom": 5}).status_code == 409


def test_manual_look_renders_and_changes_frame(tmp_path):
    """Реальный рендер: сдвиг и зум меняют кадр, вебка снизу и блюр проходят через ffmpeg."""
    import subprocess
    import threading

    from harness import tools
    src = tmp_path / "wide.mp4"
    subprocess.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=1920x1080:rate=30:duration=6", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=6", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    common = dict(framing="face", src_w=1920, src_h=1080, out_w=1080, out_h=1920, fps=30)
    centered = tmp_path / "centered.mp4"
    assert render.render_clip(src, 0.5, 3.0, None, None, centered, "tiktok",
                              threading.Event(), **common)["ok"]
    moved = tmp_path / "moved.mp4"
    res = render.render_clip(src, 0.5, 3.0, None, None, moved, "tiktok", threading.Event(),
                             look={"pan_x": 0, "pan_y": 50, "zoom": 30, "blur": 40}, **common)
    assert res["ok"], res

    def frame(path, name):
        out = tmp_path / f"{name}.png"
        subprocess.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-ss", "1", "-i", str(path),
                        "-frames:v", "1", str(out)], check=True)
        return out.read_bytes()

    assert frame(centered, "a") != frame(moved, "b")

    boxed = tmp_path / "boxed.mp4"
    res = render.render_clip(src, 0.5, 3.0, None, None, boxed, "tiktok", threading.Event(),
                             layout="webcam_bottom", corner="tr", size_pct=30,
                             look={"pan_x": 60, "pan_y": 50, "zoom": 0, "blur": 20}, **common)
    assert res["ok"], res
