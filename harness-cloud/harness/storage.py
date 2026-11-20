"""Хранилище проектов: один каталог на проект, метаданные в project.json."""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import config

_lock = threading.RLock()


def project_dir(pid: str) -> Path:
    if not pid or "/" in pid or "\\" in pid or ".." in pid:
        raise ValueError("Некорректный id проекта")
    return config.PROJECTS_DIR / pid


def _meta_path(pid: str) -> Path:
    return project_dir(pid) / "project.json"


def create_project(source: str, source_kind: str, content_type: str, options: dict[str, Any]) -> dict:
    pid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    now = time.time()
    proj = {
        "id": pid,
        "title": "",
        "source": source,
        "source_kind": source_kind,          # url | file
        "content_type": content_type,        # podcast | game | general
        "options": options,                  # clip_count, clip_length, subtitle_style, whisper_model, export_preset
        "status": "queued",                  # queued | running | done | error | cancelled
        "stage": "",
        "error": None,
        "failed_step": None,
        "duration": None,
        "clips": [],
        "created": now,
        "updated": now,
    }
    with _lock:
        project_dir(pid).mkdir(parents=True, exist_ok=True)
        save_project(proj)
    return proj


def save_project(proj: dict) -> None:
    proj["updated"] = time.time()
    path = _meta_path(proj["id"])
    tmp = path.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def load_project(pid: str) -> dict:
    path = _meta_path(pid)
    if not path.exists():
        raise FileNotFoundError(pid)
    return json.loads(path.read_text(encoding="utf-8"))


def list_projects() -> list[dict]:
    items = []
    if not config.PROJECTS_DIR.exists():
        return items
    for d in config.PROJECTS_DIR.iterdir():
        if (d / "project.json").exists():
            try:
                p = json.loads((d / "project.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items.append({k: p.get(k) for k in (
                "id", "title", "source", "content_type", "status", "stage",
                "created", "updated", "duration")} | {"clip_count": len(p.get("clips", []))})
    return sorted(items, key=lambda x: x["created"] or 0, reverse=True)


def delete_project(pid: str) -> None:
    with _lock:
        d = project_dir(pid)
        if d.exists():
            shutil.rmtree(d)
