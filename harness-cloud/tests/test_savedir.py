"""Папка сохранения: настройка, ручное сохранение и выбор папки через API."""
import json

import pytest
from fastapi.testclient import TestClient

from harness import config, pipeline, server, storage
from harness import segments as sg


class _Jobs:
    current = None

    def submit(self, pid, retry=False):
        pass

    def cancel(self, pid):
        return False

    def queued(self):
        return []


def _clip(index: int) -> dict:
    segs = [[10.0, 40.0]]
    s, e = sg.span(segs)
    return {"index": index, "start": s, "end": e, "original_start": s, "original_end": e,
            "segments": segs, "origin": "auto", "framing": "face", "sub_box": False,
            "sub_emoji": False, "sub_anim": False, "duration": 30, "score": 50, "parts": {},
            "reason": "", "text": "", "hook": "", "hook_source": "", "description": "",
            "hashtags": [], "platforms": {}, "status": "done", "error": None,
            "file": f"clips/clip_{index}.mp4", "thumb": None, "verify": None,
            "subtitles": True, "style": "violet", "timeline": [0.5] * 240}


@pytest.fixture()
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", path)
    return path


@pytest.fixture()
def project(settings_file):
    p = storage.create_project("/nonexistent/src.mp4", "file", "podcast", {
        "clip_count": 2, "subtitle_style": "violet", "whisper_model": "tiny",
        "export_preset": "tiktok", "framing": "face", "sub_box": False,
        "sub_emoji": False, "sub_anim": False})
    p["status"] = "done"
    p["title"] = "Интервью: часть 1"
    p["clips"] = [_clip(1), _clip(2)]
    storage.save_project(p)
    clips_dir = storage.project_dir(p["id"]) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    for i in (1, 2):
        (clips_dir / f"clip_{i}.mp4").write_bytes(b"fake-mp4-%d" % i)
    yield p
    storage.delete_project(p["id"])


@pytest.fixture()
def client():
    return TestClient(server.create_app(jobs=_Jobs()))


def test_save_dir_must_be_absolute_and_is_created(client, settings_file, tmp_path):
    r = client.put("/api/settings", json={"save_dir": "relative/dir"})
    assert r.status_code == 400
    target = tmp_path / "Клипы" / "новые"
    r = client.put("/api/settings", json={"save_dir": str(target)})
    assert r.status_code == 200 and r.json()["save_dir"] == str(target)
    assert target.is_dir()
    assert json.loads(settings_file.read_text(encoding="utf-8"))["save_dir"] == str(target)


def test_manual_save_copies_clips_and_zip(client, settings_file, project, tmp_path):
    pid = project["id"]
    assert client.post(f"/api/projects/{pid}/save").status_code == 400  # папка не задана
    client.put("/api/settings", json={"save_dir": str(tmp_path / "out")})
    r = client.post(f"/api/projects/{pid}/save")
    assert r.status_code == 200, r.text
    dest = tmp_path / "out" / f"Интервью_ часть 1 [{pid}]"
    assert dest.is_dir() and r.json()["path"] == str(dest)
    assert (dest / "clip_01.mp4").read_bytes() == b"fake-mp4-1"
    assert (dest / "clip_02.mp4").read_bytes() == b"fake-mp4-2"
    assert (dest / f"{pid}_clips.zip").exists()


def test_auto_save_after_processing(settings_file, project, tmp_path):
    from harness import jobs
    client_root = tmp_path / "auto"
    settings_file.write_text(json.dumps({"save_dir": str(client_root)}), encoding="utf-8")
    jobs._auto_save(project["id"])
    assert any(client_root.iterdir())


def test_pick_folder_unavailable_in_browser(client):
    server.FOLDER_PICKER = None
    assert client.post("/api/pick-folder").status_code == 501


def test_pick_folder_returns_chosen_path(client):
    server.FOLDER_PICKER = lambda: "D:/Клипы"
    try:
        r = client.post("/api/pick-folder")
        assert r.status_code == 200 and r.json()["path"] == "D:/Клипы"
    finally:
        server.FOLDER_PICKER = None
