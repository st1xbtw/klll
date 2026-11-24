"""Монтаж и оформление: данные для интерфейса, настройки ника и соцсетей, разбор опций."""
import pytest
from fastapi.testclient import TestClient

from harness import config, server


class _Jobs:
    current = None

    def submit(self, pid, retry=False):
        pass

    def cancel(self, pid):
        return False

    def queued(self):
        return []


@pytest.fixture()
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", path)
    return path


@pytest.fixture()
def client(settings_file):
    return TestClient(server.create_app(jobs=_Jobs()))


def test_meta_exposes_layouts_and_subtitle_colors(client):
    meta = client.get("/api/meta").json()
    assert meta["layouts"] == ["game", "webcam_bottom", "webcam_top", "random"]
    assert set(meta["sub_places"]) == {"bottom", "center", "top"}
    colors = meta["subtitle_colors"]
    assert set(colors) == set(config.SUBTITLE_STYLES)
    for key in colors:
        for field in ("highlight", "base", "outline"):
            assert colors[key][field].startswith("&H") and colors[key][field].endswith("&")


def test_encoders_endpoint_reports_cpu_available(client):
    data = client.get("/api/encoders").json()
    assert data["cpu"]["available"] is True
    assert {"nvenc", "qsv", "amf"} <= set(data)


def test_settings_nickname_and_social_links_are_sanitized(client):
    body = {
        "nickname": "@mychannel",
        "social_telegram": "https://t.me/mychannel",
        "social_twitch": "http://twitch.tv/insecure",
        "social_youtube": "javascript:alert(1)",
        "social_tiktok": "https://www.tiktok.com/@mychannel",
        "encoder": "bogus",
    }
    saved = client.put("/api/settings", json=body).json()
    assert saved["nickname"] == "mychannel"
    assert saved["social_telegram"] == "https://t.me/mychannel"
    assert saved["social_twitch"] == ""
    assert saved["social_youtube"] == ""
    assert saved["social_tiktok"] == "https://www.tiktok.com/@mychannel"
    assert saved["encoder"] == "auto"


def test_options_fall_back_on_bad_montage_values(settings_file):
    opts = server._options({"layout": "diagonal", "webcam_corner": "xx", "webcam_size": 99,
                            "sub_group": 9, "encoder": "vulkan", "bitrate": "1M",
                            "censor": "1", "end_card": True, "end_text": ""})
    assert opts["layout"] == "game"
    assert opts["webcam_corner"] == "br"
    assert opts["webcam_size"] == 50
    assert opts["sub_group"] == 4
    assert opts["encoder"] == "auto"
    assert opts["bitrate"] == "auto"
    assert opts["censor"] is True
    assert opts["end_card"] is True
    assert opts["end_text"] == "Подпишись"


def test_options_keep_valid_montage_values(settings_file):
    opts = server._options({"layout": "webcam_top", "webcam_corner": "tl", "webcam_size": 30,
                            "sub_group": 2, "encoder": "nvenc", "bitrate": "12M"})
    assert opts["layout"] == "webcam_top"
    assert opts["webcam_corner"] == "tl"
    assert opts["webcam_size"] == 30
    assert opts["sub_group"] == 2
    assert opts["encoder"] == "nvenc"
    assert opts["bitrate"] == "12M"
