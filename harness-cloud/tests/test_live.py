"""Нарезка Live: проверка ссылок, разбиение на окна и полный цикл записи (запись подменена)."""
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from harness import live, server


def test_live_url_accepts_supported_hosts_only():
    for url in ("https://www.twitch.tv/somechannel", "https://kick.com/somechannel",
                "https://www.youtube.com/watch?v=abc", "https://youtu.be/abc"):
        assert live.validate_live_url(url) == url
    for bad in ("ftp://twitch.tv/x", "https://example.com/live", "twitch.tv/x", ""):
        with pytest.raises(ValueError):
            live.validate_live_url(bad)


def test_plan_windows_waits_for_complete_segments_and_tail_rule():
    per = live.WINDOW_SEC // live.SEGMENT_SEC
    assert live.plan_windows(0, per, final=False) == []            # последний сегмент ещё пишется
    assert live.plan_windows(0, per + 1, final=False) == [(0, per)]
    assert live.plan_windows(0, 7, final=True) == [(0, 5), (5, 7)]  # хвост 2 мин — берём
    assert live.plan_windows(0, 6, final=True) == [(0, 5)]          # хвост 1 мин — нет
    assert live.plan_windows(5, 7, final=True) == [(5, 7)]          # продолжение с нужного места


class _FakeProc:
    """Имитирует ffmpeg: работает, пока его не остановили."""
    def __init__(self):
        self._stopped = False
    def poll(self):
        return 0 if self._stopped else None
    def terminate(self):
        self._stopped = True
    def wait(self, timeout=None):
        return 0
    def kill(self):
        self._stopped = True


def _tiny_segments(folder, count):
    for i in range(count):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc=size=160x120:rate=10:duration=0.5", "-c:v", "libx264",
                        "-f", "mpegts", str(folder / f"seg_{i:05d}.ts")], check=True)


def test_session_cuts_window_and_hands_it_over(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "POLL_SEC", 0.05)
    windows = []

    def fake_recorder(url, out_dir):
        _tiny_segments(out_dir, live.WINDOW_SEC // live.SEGMENT_SEC)   # ровно одно окно
        return _FakeProc()

    def on_window(path, label, ctype, options):
        windows.append((path, label, ctype))
        return f"pid-{len(windows)}"

    mgr = live.LiveManager(tmp_path, on_window=on_window, recorder=fake_recorder)
    session = mgr.start("https://www.twitch.tv/somechannel", "general", {"clip_count": 8})
    for _ in range(200):
        if windows:
            break
        time.sleep(0.05)
    session.request_stop()
    for _ in range(200):
        if session.status in ("stopped", "ended", "error"):
            break
        time.sleep(0.05)

    assert session.status == "stopped", session.error
    assert len(windows) == 1
    path, label, ctype = windows[0]
    assert path.exists() and path.stat().st_size > 0
    assert ctype == "general" and label.startswith("Эфир")
    assert session.projects == ["pid-1"]
    assert not list(session.dir.glob("seg_*.ts"))                # сегменты удалены после склейки


def test_live_endpoint_requires_rights_confirmation():
    class _Jobs:
        def submit(self, pid, retry=False):
            pass
    client = TestClient(server.create_app(jobs=_Jobs()))
    r = client.post("/api/live", json={"url": "https://www.twitch.tv/x", "content_type": "general"})
    assert r.status_code == 400
    assert "права" in r.json()["detail"]


def test_real_time_hls_recording_cuts_windows(tmp_path, monkeypatch):
    """Настоящая запись живого потока: локальный HLS-плейлист растёт по сегменту каждые 2 с.

    Нарезка заранее делается ffmpeg, а отдельный поток дописывает её в живой плейлист,
    потому что ffmpeg с -re на слабой машине не успевает выдавать плейлист вовремя.
    Длины сегмента и окна уменьшены ради скорости; запись и склейка настоящие."""
    import http.server
    import os
    import shutil
    import threading

    monkeypatch.setattr(live, "SEGMENT_SEC", 2)
    monkeypatch.setattr(live, "WINDOW_SEC", 10)     # 5 сегментов по 2 с
    monkeypatch.setattr(live, "MIN_TAIL_SEC", 2)
    monkeypatch.setattr(live, "POLL_SEC", 0.2)
    monkeypatch.setattr(live, "START_CHECK_SEC", 1.0)
    monkeypatch.setattr(live, "START_RETRY_DELAY", 0.5)
    monkeypatch.setattr(live, "START_RETRIES", 12)

    vod = tmp_path / "vod"
    vod.mkdir()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=10:duration=24", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-g", "20", "-keyint_min", "20", "-sc_threshold", "0",
                    "-c:a", "aac", "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
                    str(vod / "index.m3u8")], check=True)
    segs = sorted((p for p in vod.glob("index*.ts")), key=lambda p: int(p.stem[5:]))
    assert len(segs) >= 10

    feed = tmp_path / "feed"
    feed.mkdir()
    stop_feed = threading.Event()

    def feeder():
        for i, seg in enumerate(segs):
            if stop_feed.is_set():
                return
            shutil.copy(seg, feed / seg.name)
            lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:2", "#EXT-X-MEDIA-SEQUENCE:0"]
            for j in range(i + 1):
                lines += ["#EXTINF:2.000,", segs[j].name]
            tmp = feed / "index.tmp"
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(tmp, feed / "index.m3u8")
            stop_feed.wait(2.0)

    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(feed), **k)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    threading.Thread(target=feeder, daemon=True).start()
    stream = f"http://127.0.0.1:{httpd.server_address[1]}/index.m3u8"

    windows = []

    def on_window(path, label, ctype, options):
        windows.append(path)
        return f"pid-{len(windows)}"

    mgr = live.LiveManager(tmp_path / "live", on_window=on_window,
                           recorder=lambda _url, out: live.record(stream, out))
    session = mgr.start("https://www.twitch.tv/somechannel", "general", {})
    try:
        for _ in range(400):
            if windows:
                break
            time.sleep(0.1)
        session.request_stop()
        for _ in range(300):
            if session.status in ("stopped", "ended", "error"):
                break
            time.sleep(0.1)
    finally:
        stop_feed.set()
        httpd.shutdown()

    assert session.status in ("stopped", "ended"), session.error
    assert windows, "окно не появилось за время записи"
    window = windows[0]
    assert window.exists() and window.stat().st_size > 1000
    probe = shutil.which("ffprobe")
    if probe:
        dur = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", str(window)],
                             capture_output=True, text=True).stdout.strip()
        assert 7.0 <= float(dur) <= 13.0, dur
