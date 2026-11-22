"""Сквозные тесты пайплайна на синтетическом видео.

Проверяется:
  * формат: 1080×1920, 30 fps, H.264 + AAC, длительность 30 ± 0.5 с, есть аудио;
  * кроп по лицу: лицо в центре кадра результата (детекция по выходным кадрам);
  * субтитры: подсветка синхронна речи (синий пиксель-счёт во время речи, ноль в паузах);
  * хук: виден в первые секунды (жёлтая плашка), пропадает после ~3 с;
  * режим «Игра»: ни субтитров, ни хука;
  * fallback без Whisper: клипы создаются, в отчёте есть предупреждение;
  * «Скачать всё»: ZIP открывается, содержит все клипы и metadata.json;
  * API: основные эндпоинты отвечают корректно.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "tests" / "assets"
os.environ["HARNESS_DATA_DIR"] = tempfile.mkdtemp(prefix="hc_test_")
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from harness import config, pipeline, storage, transcribe  # noqa: E402
from harness.server import create_app  # noqa: E402
from tests import make_assets  # noqa: E402

pytestmark = pytest.mark.slow


# ---------- фикстуры ----------

@pytest.fixture(scope="session")
def assets():
    need = ["test_talk.mp4", "transcript.json", "face.png"]
    if not all((ASSETS / n).exists() for n in need):
        make_assets.generate(ASSETS)
    return {"video": ASSETS / "test_talk.mp4", "transcript": ASSETS / "transcript.json"}


@pytest.fixture(scope="session")
def podcast_run(assets):
    """Подкаст с эталонным транскриптом: полный прогон, 6 клипов."""
    p = storage.create_project(str(assets["video"]), "file", "podcast", {
        "clip_count": 6, "subtitle_style": "violet", "whisper_model": "base",
        "export_preset": "tiktok", "transcript_override": str(assets["transcript"])})
    res = pipeline.run(p["id"], threading.Event())
    assert res["status"] == "done", res.get("error")
    return res


def _grab(path: Path, t: float) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
                          "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True, check=True).stdout
    img = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, f"кадр на {t} с не декодирован"
    return img


def _clip_path(proj: dict, clip: dict) -> Path:
    return storage.project_dir(proj["id"]) / clip["file"]


# ---------- формат ----------

def test_clip_count_and_ranking(podcast_run):
    clips = podcast_run["clips"]
    assert 5 <= len(clips) <= 10
    scores = [c["score"] for c in clips]
    assert scores == sorted(scores, reverse=True), "ранги должны идти по убыванию силы момента"
    assert [c["index"] for c in clips] == list(range(1, len(clips) + 1))
    for c in clips:
        assert c["reason"].startswith("Выбран за:")
        assert 0 <= c["score"] <= 100


def test_no_overlapping_windows(podcast_run):
    spans = sorted((c["start"], c["end"]) for c in podcast_run["clips"])
    for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
        assert a1 <= b0 + 1e-6, "окна клипов пересекаются"


def test_output_format_of_every_clip(podcast_run):
    for c in podcast_run["clips"]:
        info = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
             str(_clip_path(podcast_run, c))], capture_output=True, check=True).stdout)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next(s for s in info["streams"] if s["codec_type"] == "audio")
        assert (int(v["width"]), int(v["height"])) == (1080, 1920)
        assert v["codec_name"] == "h264"
        assert v["pix_fmt"] == "yuv420p"
        num, den = (int(x) for x in v["r_frame_rate"].split("/"))
        assert abs(num / den - 30) < 0.01
        assert a["codec_name"] == "aac"
        assert abs(float(info["format"]["duration"]) - 30.0) <= 0.5


# ---------- кроп по лицу ----------

def test_face_is_centered_in_output(podcast_run):
    """Лицо в выходном кадре детектируется около центра (допуск 12% ширины)."""
    det = cv2.CascadeClassifier(str(config.MODELS_DIR / "haarcascade_frontalface_default.xml"))
    tol = 0.12 * config.OUT_W
    checked = 0
    for c in podcast_run["clips"][:3]:
        path = _clip_path(podcast_run, c)
        for t in (6.0, 12.0, 18.0, 24.0):
            img = _grab(path, t)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            faces = det.detectMultiScale(small, 1.15, 5, minSize=(30, 30))
            if len(faces) == 0:
                continue
            x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
            cx = (x + w / 2) * 2
            checked += 1
            assert abs(cx - config.OUT_W / 2) <= tol, f"клип {c['index']} t={t}: лицо на x={cx:.0f}"
    assert checked >= 6, "лицо почти не детектируется в выходных кадрах"


# ---------- субтитры и хук ----------

def _sub_band_counts(img: np.ndarray) -> int:
    band = img[1200:1460, :, :].astype(int)
    b, g, r = band[:, :, 0], band[:, :, 1], band[:, :, 2]
    # подсветка стиля «violet»: RGB ≈ (91,138,255)
    return int(((abs(r - 91) < 40) & (abs(g - 138) < 40) & (abs(b - 255) < 40)).sum())


def test_subtitles_are_in_sync_with_speech(podcast_run, assets):
    clip = podcast_run["clips"][0]
    st, en = clip["start"], clip["end"]
    tr = json.loads(assets["transcript"].read_text(encoding="utf-8"))["segments"]
    words = [w for s in tr for w in s["words"] if st <= w["s"] < en]
    path = _clip_path(podcast_run, clip)

    speech_times = [((w["s"] + w["e"]) / 2 - st) for w in words[:12]]
    speech_hits = [_sub_band_counts(_grab(path, t)) for t in speech_times]
    assert min(speech_hits) > 500, f"субтитр не виден во время речи: {speech_hits}"

    pauses = []
    for a, b in zip(words, words[1:]):
        if b["s"] - a["e"] >= 0.8 and len(pauses) < 3:
            pauses.append(((a["e"] + b["s"]) / 2 - st))
    assert pauses, "в клипе нет пауз для проверки"
    pause_hits = [_sub_band_counts(_grab(path, t)) for t in pauses]
    assert max(pause_hits) < 100, f"субтитр висит в паузе: {pause_hits}"


def test_hook_visible_early_and_gone_later(podcast_run):
    clip = podcast_run["clips"][0]
    assert clip["hook"], "для подкаста хук обязателен"
    path = _clip_path(podcast_run, clip)

    # Хук выводится снизу кадра (над строкой субтитров), сверху ничего не появляется.
    def yellow(img, top, bottom):
        band = img[top:bottom, :, :].astype(int)
        b, g, r = band[:, :, 0], band[:, :, 1], band[:, :, 2]
        return int(((r > 230) & (g > 200) & (b < 80)).sum())

    assert yellow(_grab(path, 1.0), 950, 1450) > 20000, "жёлтая плашка хука не видна внизу в первую секунду"
    assert yellow(_grab(path, 2.0), 950, 1450) > 20000, "хук пропал раньше 2 с"
    assert yellow(_grab(path, 1.0), 0, 600) < 500, "хук не должен появляться вверху кадра"
    assert yellow(_grab(path, 6.0), 950, 1450) < 500, "хук не должен висеть после первых 3 с"


def test_hook_is_short_and_from_clip_text(podcast_run):
    for c in podcast_run["clips"]:
        words = c["hook"].split()
        assert 1 <= len(words) <= 7
        assert c["hook_source"] in ("rules", "llm")


# ---------- режим «Игра» ----------

def test_game_mode_has_no_subtitles_or_hook(assets):
    p = storage.create_project(str(assets["video"]), "file", "game", {
        "clip_count": 5, "subtitle_style": "violet", "whisper_model": "base",
        "export_preset": "tiktok", "transcript_override": str(assets["transcript"])})
    res = pipeline.run(p["id"], threading.Event())
    assert res["status"] == "done", res.get("error")
    assert len(res["clips"]) >= 5
    for c in res["clips"]:
        clip_dir = storage.project_dir(res["id"]) / "clips" / f"{c['index']:02d}"
        assert not (clip_dir / "sub.ass").exists(), "в режиме «Игра» не должно быть субтитров"
        assert c["hook"] == "" and c["subtitles"] is False
        path = _clip_path(res, c)
        band = _grab(path, 1.0)[150:450, :, :].astype(int)
        yellow = ((band[:, :, 2] > 230) & (band[:, :, 1] > 200) & (band[:, :, 0] < 80)).sum()
        assert yellow < 500, "жёлтая плашка хука найдена в режиме «Игра»"
        assert c["verify"]["ok"]


# ---------- fallback без Whisper ----------

def test_fallback_without_whisper(assets, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("веса недоступны (тест)")
    monkeypatch.setattr(transcribe, "_load_model", broken)
    p = storage.create_project(str(assets["video"]), "file", "podcast", {
        "clip_count": 5, "subtitle_style": "violet", "whisper_model": "base",
        "export_preset": "tiktok"})
    res = pipeline.run(p["id"], threading.Event())
    assert res["status"] == "done", res.get("error")
    assert len(res["clips"]) >= 5
    assert any("Транскрибация пропущена" in w for w in res["warnings"])
    assert all(c["hook"] == "" for c in res["clips"])
    assert all(c["verify"]["ok"] for c in res["clips"])


# ---------- экспорт ----------

def test_download_all_zip(podcast_run):
    from harness.pipeline import export_zip
    dest = Path(config.DATA_DIR) / "exports" / "test.zip"
    export_zip(podcast_run, dest)
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        names = z.namelist()
        meta = json.loads(z.read("metadata.json"))
    clip_files = [n for n in names if n.startswith("clip_") and n.endswith(".mp4")]
    assert len(clip_files) == len([c for c in podcast_run["clips"] if c.get("file")])
    assert len(meta["clips"]) == len(clip_files)


# ---------- API (без фоновой обработки) ----------

class _NoJobs:
    current = None

    def __init__(self):
        self.submitted = []

    def submit(self, pid, retry=False):
        self.submitted.append((pid, retry))

    def cancel(self, pid):
        return False

    def queued(self):
        return []


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    return TestClient(create_app(jobs=_NoJobs()))


def test_api_meta_and_settings(client):
    meta = client.get("/api/meta").json()
    assert meta["output"] == {"w": 1080, "h": 1920, "fps": 30}
    assert set(meta["content_types"]) == {"podcast", "game", "general", "parts"}
    r = client.put("/api/settings", json={"theme": "light", "clip_count": 7})
    assert r.status_code == 200
    assert client.get("/api/settings").json()["theme"] == "light"


def test_api_rejects_bad_input(client):
    assert client.post("/api/projects", json={"urls": ["not a url"], "content_type": "podcast"}).status_code == 400
    assert client.post("/api/projects", json={"urls": [], "content_type": "podcast"}).status_code == 400
    assert client.post("/api/projects", json={"urls": ["https://x.y/v"], "content_type": "bogus"}).status_code == 400
    assert client.get("/api/projects/does-not-exist").status_code == 404
    assert client.post("/api/projects/does-not-exist/retry").status_code == 404


def test_api_creates_and_deletes_project(client):
    r = client.post("/api/projects", json={"urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
                                           "content_type": "podcast", "clip_count": 8})
    assert r.status_code == 200
    pid = r.json()["ids"][0]
    assert client.get(f"/api/projects/{pid}").json()["status"] == "queued"
    assert any(p["id"] == pid for p in client.get("/api/projects").json())
    assert client.delete(f"/api/projects/{pid}").json()["ok"]
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Harness Cloud" in r.text
    assert client.get("/app.js").status_code == 200
