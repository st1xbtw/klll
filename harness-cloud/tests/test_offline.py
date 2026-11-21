"""Офлайн-режим: без сети, модели Whisper из сборки, понятные ошибки."""
import json
import urllib.request

import pytest
from fastapi.testclient import TestClient

from harness import config, server, text_ai, transcribe
from harness.tools import ToolError


class _Jobs:
    current = None

    def submit(self, pid, retry=False):
        pass

    def cancel(self, pid):
        return False

    def queued(self):
        return []


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", path)
    monkeypatch.setattr(config, "WHISPER_DIR", tmp_path / "whisper")
    monkeypatch.setattr(config, "BUNDLED_WHISPER_DIR", tmp_path / "bundled")
    transcribe._model_cache.clear()
    yield path
    transcribe._model_cache.clear()


def _set_offline(path, offline: bool):
    path.write_text(json.dumps({"offline": offline}), encoding="utf-8")


def test_offline_mode_makes_no_network_calls(settings, monkeypatch):
    _set_offline(settings, True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def boom(*a, **k):
        raise AssertionError("сеть не должна вызываться в офлайн-режиме")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert text_ai.llm_hook("какой-то текст клипа", "podcast") is None
    assert text_ai.hook_for("какой-то текст клипа", ["Первая фраза."], "podcast")[1] == "rules"


def test_offline_mode_rejects_url_intake(settings):
    _set_offline(settings, True)
    client = TestClient(server.create_app(jobs=_Jobs()))
    r = client.post("/api/projects", json={"urls": ["https://example.com/v.mp4"]})
    assert r.status_code == 409 and "Офлайн" in r.json()["detail"]


def test_settings_store_offline_flag(settings):
    client = TestClient(server.create_app(jobs=_Jobs()))
    assert client.put("/api/settings", json={"offline": True}).json()["offline"] is True
    assert config.offline_mode() is True
    assert client.put("/api/settings", json={"offline": False}).json()["offline"] is False


class _FakeModel:
    calls = []

    def __init__(self, source, **kwargs):
        _FakeModel.calls.append((source, kwargs))


def test_bundled_model_loads_without_network(settings, monkeypatch):
    import faster_whisper
    monkeypatch.setattr(faster_whisper, "WhisperModel", _FakeModel)
    bundled = config.BUNDLED_WHISPER_DIR / "base"
    bundled.mkdir(parents=True)
    (bundled / "model.bin").write_bytes(b"x")
    _FakeModel.calls.clear()
    transcribe._load_model("base")
    source, kwargs = _FakeModel.calls[-1]
    assert source == str(bundled)
    assert kwargs["local_files_only"] is True


def test_missing_model_offline_gives_clear_error(settings, monkeypatch):
    import faster_whisper
    monkeypatch.setattr(faster_whisper, "WhisperModel", _FakeModel)
    _set_offline(settings, True)
    with pytest.raises(ToolError, match="не установлена"):
        transcribe._load_model("small")


def test_offline_falls_back_to_installed_model(settings, monkeypatch):
    _set_offline(settings, True)
    bundled = config.BUNDLED_WHISPER_DIR / "tiny"
    bundled.mkdir(parents=True)
    (bundled / "model.bin").write_bytes(b"x")
    assert transcribe.resolve_model("small") == "tiny"      # выбранной нет — берём установленную
    assert transcribe.resolve_model("tiny") == "tiny"


def test_online_missing_model_may_download(settings, monkeypatch):
    import faster_whisper
    monkeypatch.setattr(faster_whisper, "WhisperModel", _FakeModel)
    _set_offline(settings, False)
    _FakeModel.calls.clear()
    transcribe._load_model("small")
    source, kwargs = _FakeModel.calls[-1]
    assert source == "small" and kwargs["local_files_only"] is False
