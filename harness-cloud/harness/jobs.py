"""Модуль 12: очередь задач. Один рабочий поток, проекты обрабатываются по порядку.

Поддерживает пакетную очередь (несколько ссылок), отмену и повтор с последнего упавшего шага.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable

from pathlib import Path

from . import pipeline, storage


def _auto_save(pid: str) -> None:
    """Если в настройках задана папка сохранения, копирует туда готовые клипы. Ошибки — в предупреждения проекта."""
    root = pipeline.save_dir_setting()
    if not root:
        return
    proj = storage.load_project(pid)
    if proj.get("status") != "done":
        return
    try:
        pipeline.save_to_folder(proj, Path(root))
    except Exception as exc:  # сохранение не должно ломать готовый проект
        proj = storage.load_project(pid)
        proj.setdefault("warnings", []).append(f"Не удалось сохранить в папку: {exc}")
        storage.save_project(proj)


class JobManager:
    def __init__(self, on_event: Callable[[str, str], None] | None = None):
        self._q: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._on_event = on_event or (lambda kind, pid: None)
        self._current: str | None = None
        t = threading.Thread(target=self._worker, name="harness-worker", daemon=True)
        t.start()

    def submit(self, pid: str, retry: bool = False) -> None:
        with self._lock:
            self._cancels.setdefault(pid, threading.Event()).clear()
        self._q.put((pid, retry))

    def cancel(self, pid: str) -> bool:
        with self._lock:
            ev = self._cancels.get(pid)
            if ev is None:
                return False
            ev.set()
        return True

    def queued(self) -> list[str]:
        with self._q.mutex:
            return [pid for pid, _ in list(self._q.queue)]

    @property
    def current(self) -> str | None:
        return self._current

    def _worker(self) -> None:
        while True:
            pid, retry = self._q.get()
            with self._lock:
                ev = self._cancels.setdefault(pid, threading.Event())
            self._current = pid
            try:
                if ev.is_set():
                    proj = storage.load_project(pid)
                    proj["status"] = "cancelled"
                    proj["stage"] = "Отменено"
                    storage.save_project(proj)
                else:
                    pipeline.run(pid, ev, retry=retry)
                    _auto_save(pid)
            except Exception as exc:  # защита рабочего потока
                try:
                    proj = storage.load_project(pid)
                    proj["status"] = "error"
                    proj["error"] = str(exc)[:400]
                    storage.save_project(proj)
                except Exception:
                    pass
            finally:
                self._current = None
                self._on_event("finished", pid)
                self._q.task_done()
