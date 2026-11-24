"""Раскладка с вебкой, цензура, группировка субтитров, выбор кодировщика."""
import subprocess
import threading

import pytest

from harness import censor, config, encoders, render, subtitles


def test_random_layout_is_deterministic_and_valid():
    assert render.resolve_layout("random", 3) == render.resolve_layout("random", 3)
    assert {render.resolve_layout("random", i) for i in range(20)} == {"webcam_top", "webcam_bottom"}
    assert render.resolve_layout("game", 0) == "game"
    assert render.resolve_layout("bogus", 0) == "game"


def test_split_only_for_vertical_frame():
    assert render.split_supported(1080, 1920)
    assert not render.split_supported(1920, 1080)
    # Для горизонтального кадра раскладка не применяется, цепочка совпадает с обычной.
    plain = render._framing_chain(None, "center", 1920, 1080, 1920, 1080, 30, "webcam_bottom")
    assert "vstack" not in plain


def test_webcam_box_stays_inside_source():
    cw, ch, cx, cy = render._webcam_box("br", 25)
    assert cw == "iw*0.2500" and ch == "iw*0.1875"
    assert cx.startswith("iw*") and cy.startswith("ih-")
    assert render._webcam_box("tl", 20)[3] == "ih*0.0200"


def test_split_render_produces_vertical_clip_with_both_zones(tmp_path):
    src = tmp_path / "wide.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=1920x1080:rate=30:duration=6", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=6", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    out = tmp_path / "split.mp4"
    res = render.render_clip(src, 0.5, 3.0, None, None, out, "tiktok", threading.Event(),
                             framing="center", src_w=1920, src_h=1080, out_w=1080, out_h=1920,
                             fps=30, layout="webcam_bottom", corner="br", size_pct=25)
    assert res["ok"], res
    assert res["width"] == 1080 and res["height"] == 1920


def test_profanity_detection_and_masking():
    assert censor.is_profane("блять,")
    assert censor.is_profane("Fuck!")
    assert censor.is_profane("ПИЗДЕЦ")
    assert not censor.is_profane("привет")
    assert not censor.is_profane("стол")
    words = [{"w": "ну", "s": 0.0, "e": 0.3}, {"w": "блять", "s": 1.0, "e": 1.4}]
    masked, mutes = censor.censor_words(words)
    assert masked[1]["w"] == "*****" and masked[0]["w"] == "ну"
    assert mutes == [(1.0, 1.45)]
    assert words[1]["w"] == "блять"                        # исходные слова не меняются
    assert "volume=0" in censor.mute_filter(mutes) and censor.mute_filter([]) == ""


def test_audio_filter_adds_mute_only_when_needed():
    assert "volume=0" in render.audio_filter(10.0, None, [(1.0, 1.5)])
    assert "volume=0" not in render.audio_filter(10.0, None, None)


def test_group_words_respects_word_count():
    words = [{"w": f"w{i}", "s": i * 0.3, "e": i * 0.3 + 0.25} for i in range(7)]
    groups = subtitles._group_words(words, 2)
    assert all(len(g) <= 2 for g in groups)
    assert sum(len(g) for g in groups) == 7
    assert len(subtitles._group_words(words, 0)) >= 1


def test_encoder_falls_back_to_cpu_when_gpu_missing(monkeypatch):
    monkeypatch.setattr(encoders, "available", lambda name: False)
    assert encoders.resolve("auto") == "cpu"
    assert encoders.resolve("nvenc") == "cpu"
    assert encoders.resolve("cpu") == "cpu"
    monkeypatch.setattr(encoders, "available", lambda name: name == "nvenc")
    assert encoders.resolve("auto") == "nvenc"
    assert encoders.resolve("amf") == "cpu"


def test_gpu_video_args_use_named_encoder():
    args = encoders.video_args("nvenc", 23, "8M", "16M", 30)
    assert args[:2] == ["-c:v", "h264_nvenc"] and "-cq" in args
    assert encoders.video_args("cpu", 23, "8M", "16M", 30) is None
    enc = render._encode_args("tiktok", False, 1080, 1920, 30, "cpu", "8M")
    assert "-maxrate" in enc and enc[enc.index("-maxrate") + 1] == "8M"
    assert enc[enc.index("-bufsize") + 1] == "16M"


def test_end_card_adds_three_seconds_and_keeps_format(tmp_path):
    src = tmp_path / "wide.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=1280x720:rate=30:duration=5", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=5", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    clip = tmp_path / "clip.mp4"
    render.render_clip(src, 0.2, 2.0, None, None, clip, "tiktok", threading.Event(),
                       framing="center", src_w=1280, src_h=720, out_w=1080, out_h=1920, fps=30)
    card = render.make_end_card(tmp_path / "card.mp4", 1080, 1920, 30, ["Подпишись", "@nick"],
                                "tiktok")
    joined = render.append_end_card(clip, card, tmp_path / "joined.mp4")
    res = render.verify(joined, 1080, 1920, 30, expected=2.0 + render.END_CARD_SECONDS)
    assert res["ok"], res
    assert res["width"] == 1080 and res["height"] == 1920


def test_server_options_clamp_and_whitelist(tmp_path, monkeypatch):
    from harness import server
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    opts = server._options({"layout": "nonsense", "webcam_corner": "xx", "webcam_size": 900,
                            "sub_group": 9, "encoder": "gpu-magic", "bitrate": "1G",
                            "end_text": "   ", "censor": "1"})
    assert opts["layout"] == "game" and opts["webcam_corner"] == "br"
    assert opts["webcam_size"] == 50 and opts["sub_group"] == 4
    assert opts["encoder"] in server.ENCODER_CHOICES and opts["bitrate"] == "auto"
    assert opts["end_text"] == "Подпишись" and opts["censor"] is True
    ok = server._options({"layout": "webcam_top", "webcam_corner": "tl", "bitrate": "12M"})
    assert ok["layout"] == "webcam_top" and ok["webcam_corner"] == "tl" and ok["bitrate"] == "12M"


def test_settings_sanitize_social_links(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from harness import server
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")

    class _Jobs:
        def submit(self, pid, retry=False):
            pass
    client = TestClient(server.create_app(jobs=_Jobs()))
    r = client.put("/api/settings", json={"nickname": "@AcLLo", "social_twitch": "http://insecure",
                                           "social_telegram": "https://t.me/example", "encoder": "bad"})
    assert r.status_code == 200
    data = client.get("/api/settings").json()
    assert data["nickname"] == "AcLLo"
    assert data["social_twitch"] == "" and data["social_telegram"] == "https://t.me/example"
    assert data["encoder"] == "auto"
    enc = client.get("/api/encoders").json()
    assert enc["cpu"]["available"] is True
