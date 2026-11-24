"""Ник и значки площадок в кадре: рисование значка, наложение в ffmpeg, опции проекта."""
import subprocess
import threading

from PIL import Image

from harness import badge, render, server, tools

URL = "https://www.tiktok.com/@streamer"


def _frame(video, t, out):
    subprocess.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-ss", str(t), "-i", str(video),
                    "-frames:v", "1", str(out)], check=True)
    return Image.open(out).convert("RGB")


def test_no_badge_without_nickname_or_links(tmp_path):
    assert badge.make_badge(tmp_path / "b.png", "", {}, 1080) is None
    assert badge.make_badge(tmp_path / "b.png", "   ", {"tiktok": "", "twitch": None}, 1080) is None


def test_badge_draws_only_configured_icons(tmp_path):
    out = badge.make_badge(tmp_path / "b.png", "streamer", {"tiktok": URL, "twitch": "", "youtube": None},
                           1080)
    im = Image.open(out)
    assert im.mode == "RGBA"
    assert im.height == badge.ICON_H + badge.PAD * 2
    assert 0 < im.width <= 1080
    # Подложка и значки: есть непрозрачные пиксели.
    assert im.getchannel("A").getextrema()[1] > 0


def test_badge_with_only_nickname_and_long_name_fits_width(tmp_path):
    long_nick = "очень_длинный_ник_стримера_" * 2
    out = badge.make_badge(tmp_path / "b.png", long_nick, {}, 1080)
    assert Image.open(out).width <= 1080


def test_render_clip_with_badge_changes_top_of_frame(tmp_path):
    src = tmp_path / "wide.mp4"
    subprocess.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=1920x1080:rate=30:duration=6", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=6", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    common = dict(framing="center", src_w=1920, src_h=1080, out_w=1080, out_h=1920, fps=30)
    plain = tmp_path / "plain.mp4"
    res = render.render_clip(src, 0.5, 3.0, None, None, plain, "tiktok", threading.Event(), **common)
    assert res["ok"], res

    png = badge.make_badge(tmp_path / "badge.png", "streamer", {"tiktok": URL}, 1080)
    with_badge = tmp_path / "badge_top.mp4"
    res = render.render_clip(src, 0.5, 3.0, None, None, with_badge, "tiktok", threading.Event(),
                             badge=png, badge_pos="top", **common)
    assert res["ok"], res

    a = _frame(plain, 1.0, tmp_path / "a.png").crop((0, 0, 1080, 400))
    b = _frame(with_badge, 1.0, tmp_path / "b.png").crop((0, 0, 1080, 400))
    assert a.tobytes() != b.tobytes()


def test_render_segments_with_badge_keeps_format(tmp_path):
    src = tmp_path / "wide.mp4"
    subprocess.run([tools.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=1920x1080:rate=30:duration=8", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=8", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    png = badge.make_badge(tmp_path / "badge.png", "streamer", {"telegram": URL}, 1080)
    out = tmp_path / "parts.mp4"
    res = render.render_segments(src, [(0.5, 2.5), (4.0, 6.0)], [None, None], "center", 1920, 1080,
                                 None, out, "tiktok", threading.Event(), out_w=1080, out_h=1920,
                                 fps=30, badge=png, badge_pos="center")
    assert res["ok"], res
    assert res["width"] == 1080 and res["height"] == 1920


def test_options_read_social_links_and_badge_flags(monkeypatch):
    settings = {**server.DEFAULT_SETTINGS, "nickname": "streamer", "social_tiktok": URL,
                "social_twitch": "http://insecure.example", "social_telegram": ""}
    monkeypatch.setattr(server, "_read_settings", lambda: settings)
    opts = server._options({"social_badge": "1", "social_pos": "center"})
    assert opts["social_badge"] is True
    assert opts["social_pos"] == "center"
    assert opts["socials"] == {"tiktok": URL}
    fallback = server._options({"social_pos": "left"})
    assert fallback["social_badge"] is False
    assert fallback["social_pos"] == "top"
