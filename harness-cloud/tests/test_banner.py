"""Баннер посреди клипа: положение вставки, фильтр, настоящий рендер и загрузка картинки."""
import subprocess
import threading

import pytest
from fastapi.testclient import TestClient

from harness import banner, config, server, tools


def test_banner_sits_in_the_middle_by_default():
    assert banner.banner_position(30.0) == 15.0
    assert banner.banner_position(30.0, 0.25) == 7.5
    # Вставка не выходит за пределы клипа.
    assert 1.0 <= banner.banner_position(8.0, 0.9) <= 7.0


def test_banner_filter_freezes_then_resumes_video_and_pauses_audio():
    chain = banner.banner_filter(15.0, 3.0, 1080, 1920, 30)
    assert "loop=loop=-1:size=1" in chain
    assert "trim=duration=3.000" in chain
    assert "concat=n=3:v=1:a=0[v]" in chain and "concat=n=3:v=0:a=1[a]" in chain
    assert "anullsrc" in chain


def test_short_clip_gets_no_banner(tmp_path):
    with pytest.raises(tools.ToolError):
        banner.add_banner(tmp_path / "a.mp4", tmp_path / "b.png", tmp_path / "o.mp4", 5.0,
                          1080, 1920, 30, threading.Event())


def test_banner_render_adds_three_seconds_and_holds_the_frame(tmp_path):
    src = tmp_path / "clip.mp4"
    subprocess.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=1080x1920:rate=30:duration=10", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=10", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    png = tmp_path / "banner.png"
    subprocess.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=0x2a1030:size=800x400:d=1", "-frames:v", "1", str(png)], check=True)
    out = tmp_path / "out.mp4"
    at = banner.add_banner(src, png, out, 10.0, 1080, 1920, 30, threading.Event())
    assert at == 5.0

    result = subprocess.run([tools.ffprobe_bin(), "-v", "error", "-show_entries", "format=duration", "-of",
                             "default=nw=1:nk=1", str(out)], capture_output=True, text=True)
    assert abs(float(result.stdout.strip()) - 13.0) < 0.15

    def frame(t, name):
        png_out = tmp_path / f"{name}.png"
        subprocess.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{t}", "-i", str(out),
                        "-frames:v", "1", str(png_out)], check=True)
        return png_out.read_bytes()

    # Во время баннера кадр стоит: два момента внутри окна дают одинаковый результат
    # с точностью до шума сжатия.
    from PIL import Image, ImageChops
    a = tmp_path / "h1.png"
    b = tmp_path / "h2.png"
    frame(6.0, "h1")
    frame(7.5, "h2")
    diff = ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB"))
    assert max(max(ext) for ext in diff.getextrema()) < 12


def test_banner_upload_rejects_non_images_and_saves_png(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BANNER_FILE", tmp_path / "banner.png")

    class _Jobs:
        def submit(self, *a, **k):
            pass

        def cancel(self, pid):
            return False

        def queued(self):
            return []

    client = TestClient(server.create_app(jobs=_Jobs()))
    bad = client.post("/api/banner", files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 400
    from PIL import Image
    src = tmp_path / "src.png"
    Image.new("RGB", (400, 120), (42, 16, 48)).save(src)
    ok = client.post("/api/banner", files={"file": ("b.png", src.read_bytes(), "image/png")})
    assert ok.status_code == 200 and ok.json()["size"] == [400, 120]
    assert client.get("/api/banner").json() == {"exists": True}
    client.delete("/api/banner")
    assert client.get("/api/banner").json() == {"exists": False}
