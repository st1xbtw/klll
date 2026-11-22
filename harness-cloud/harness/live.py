"""Нарезка Live: запись прямого эфира по ссылке и передача готовых окон в обычную обработку.

Поток: ffmpeg пишет эфир сегментами по SEGMENT_SEC секунд. Когда набирается окно WINDOW_SEC,
сегменты склеиваются без перекодирования в один файл, и он становится обычным проектом
(транскрипция, поиск моментов, субтитры и рендер — как у загруженного видео).
Запись и сессии живут в памяти приложения: при перезапуске незавершённая запись останавливается.
"""
from __future__ import annotations

import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import config, tools
from .tools import ToolError
from .winproc import hidden_kwargs

LIVE_HOSTS = {"twitch.tv", "kick.com", "youtube.com", "youtu.be"}
SEGMENT_SEC = 60        # длина одного сегмента записи
WINDOW_SEC = 300        # окно, которое уходит в обработку
MIN_TAIL_SEC = 120      # последний неполный кусок обрабатывается, если он не короче этого
POLL_SEC = 5.0          # как часто проверяем, появилось ли готовое окно
START_CHECK_SEC = 5.0  # если запись упала раньше, это ошибка старта, а не конец эфира
START_RETRIES = 6      # стрим может только начинаться: плейлист ещё не готов
START_RETRY_DELAY = 2.0


def validate_live_url(url: str) -> str:
    url = (url or "").strip()
    p = urlparse(url)
    host = (p.hostname or "").lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    if p.scheme not in ("http", "https") or host not in LIVE_HOSTS:
        raise ValueError("Нужна ссылка на эфир Twitch, YouTube или Kick (https://…)")
    return url


def plan_windows(start: int, count: int, final: bool) -> list[tuple[int, int]]:
    """Диапазоны готовых сегментов [a, b) для окон.

    count — сколько сегментов уже записано. Пока запись идёт, последний сегмент может
    дописываться, поэтому он не берётся, если final=False. Окно берётся только полным,
    кроме финального хвоста, который обрабатывается, если он не короче MIN_TAIL_SEC."""
    per = max(1, WINDOW_SEC // SEGMENT_SEC)
    complete = count if final else max(0, count - 1)
    out: list[tuple[int, int]] = []
    a = start
    while a < complete:
        b = min(a + per, complete)
        full = (b - a) == per
        tail_ok = final and (b - a) * SEGMENT_SEC >= MIN_TAIL_SEC
        if not (full or tail_ok):
            break
        out.append((a, b))
        a = b
    return out


def _ffmpeg(args: list[str], cwd: Path) -> None:
    proc = subprocess.run([tools.ffmpeg_bin(), "-y", "-v", "error", *args], cwd=str(cwd),
                          capture_output=True, text=True, **hidden_kwargs())
    if proc.returncode != 0:
        raise ToolError("ffmpeg: " + proc.stderr[-300:])


def concat_segments(names: list[str], out_name: str, cwd: Path) -> Path:
    """Склейка сегментов без перекодирования (concat demuxer, -c copy)."""
    lst = cwd / f"{out_name}.list.txt"
    lst.write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy",
             "-movflags", "+faststart", out_name], cwd)
    lst.unlink(missing_ok=True)
    return cwd / out_name


def resolve_stream(url: str) -> str:
    """Адрес потока эфира через yt-dlp. Ошибка, если эфира сейчас нет."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise ToolError("Не установлен yt-dlp") from exc
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # yt-dlp бросает свои типы ошибок
        raise ToolError("Не удалось открыть ссылку: " + str(exc)[-200:]) from exc
    if not info or not info.get("is_live"):
        raise ToolError("Сейчас нет прямого эфира по этой ссылке")
    stream = info.get("url")
    if not stream:
        raise ToolError("Не удалось получить поток эфира")
    return stream


def record(stream: str, out_dir: Path) -> subprocess.Popen:
    """ffmpeg пишет поток в сегменты seg_NNNNN.ts длиной SEGMENT_SEC без перекодирования."""
    log = open(out_dir / "recorder.log", "w", encoding="utf-8")
    cmd = [tools.ffmpeg_bin(), "-y", "-v", "error", "-i", stream, "-c", "copy",
           "-f", "segment", "-segment_time", str(SEGMENT_SEC), "-reset_timestamps", "1",
           "-segment_format", "mpegts", "seg_%05d.ts"]
    return subprocess.Popen(cmd, cwd=str(out_dir), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=log, **hidden_kwargs())


def start_recorder(url: str, out_dir: Path) -> subprocess.Popen:
    return record(resolve_stream(url), out_dir)


class LiveSession:
    """Одна запись эфира: фоновый поток пишет сегменты и отдаёт окна в on_window."""

    def __init__(self, sid: str, url: str, root: Path, content_type: str, options: dict,
                 on_window: Callable[[Path, str, str, dict], str],
                 recorder: Callable[[str, Path], subprocess.Popen] = start_recorder):
        self.id = sid
        self.url = url
        self.dir = root / sid
        self.dir.mkdir(parents=True, exist_ok=True)
        self.content_type = content_type
        self.options = options
        self.status = "starting"         # starting | recording | stopping | stopped | ended | error
        self.error: str | None = None
        self.started_at = time.time()
        self.projects: list[str] = []
        self._on_window = on_window
        self._recorder = recorder
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._next = 0                   # индекс первого сегмента, ещё не отданного в обработку
        self._thread = threading.Thread(target=self._run, name=f"live-{sid}", daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        if self.status in ("starting", "recording"):
            self.status = "stopping"
        self._stop.set()

    def info(self) -> dict:
        return {"id": self.id, "url": self.url, "status": self.status, "error": self.error,
                "started_at": self.started_at, "projects": list(self.projects),
                "windows": len(self.projects), "content_type": self.content_type}

    def _run(self) -> None:
        try:
            self._proc = self._start_with_retries()
            self.status = "recording"
            while not self._stop.is_set():
                self._flush(final=False)
                if self._proc.poll() is not None:   # эфир закончился сам
                    break
                self._stop.wait(POLL_SEC)
            ended_by_stream = not self._stop.is_set()
            self._kill_proc()
            self._flush(final=True)
            self.status = "ended" if ended_by_stream else "stopped"
        except Exception as exc:
            self._kill_proc()
            self.status = "error"
            self.error = str(exc)[-300:]

    def _start_with_retries(self) -> subprocess.Popen:
        """Запускает запись; если ffmpeg падает сразу, повторяет попытку, а потом сообщает ошибку."""
        for _ in range(START_RETRIES):
            proc = self._recorder(self.url, self.dir)
            t0 = time.time()
            while time.time() - t0 < START_CHECK_SEC and not self._stop.is_set():
                if proc.poll() is not None:
                    break
                self._stop.wait(0.1)
            if proc.poll() is None or self._stop.is_set():
                return proc
            self._stop.wait(START_RETRY_DELAY)
        log = self.dir / "recorder.log"
        tail = log.read_text(encoding="utf-8", errors="replace")[-200:] if log.exists() else ""
        raise ToolError("Запись не запустилась" + (": " + tail if tail else ""))

    def _flush(self, final: bool) -> None:
        count = len(list(self.dir.glob("seg_*.ts")))
        for a, b in plan_windows(self._next, count, final):
            names = [f"seg_{i:05d}.ts" for i in range(a, b)]
            label = f"Эфир {time.strftime('%H:%M', time.localtime(self.started_at))} · окно {len(self.projects) + 1}"
            window = concat_segments(names, f"window_{a:05d}.mp4", self.dir)
            pid = self._on_window(window, label, self.content_type, self.options)
            self.projects.append(pid)
            for n in names:                # окно уже скопировано в проект, сегменты больше не нужны
                (self.dir / n).unlink(missing_ok=True)
            self._next = b

    def _kill_proc(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()


class LiveManager:
    def __init__(self, root: Path, on_window: Callable[[Path, str, str, dict], str],
                 recorder: Callable[[str, Path], subprocess.Popen] = start_recorder):
        self.root = root
        self._on_window = on_window
        self._recorder = recorder
        self._sessions: dict[str, LiveSession] = {}
        self._lock = threading.Lock()

    def start(self, url: str, content_type: str, options: dict) -> LiveSession:
        url = validate_live_url(url)
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        session = LiveSession(sid, url, self.root, content_type, options,
                              self._on_window, self._recorder)
        with self._lock:
            self._sessions[sid] = session
        return session

    def get(self, sid: str) -> LiveSession | None:
        with self._lock:
            return self._sessions.get(sid)

    def all(self) -> list[dict]:
        with self._lock:
            items = list(self._sessions.values())
        return [s.info() for s in sorted(items, key=lambda s: s.started_at, reverse=True)]


def live_root() -> Path:
    root = config.DATA_DIR / "live"
    root.mkdir(parents=True, exist_ok=True)
    return root
