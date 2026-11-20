"""HTTP-слой (FastAPI). Отдаёт интерфейс и API для окна pywebview или браузера."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, ingest, pipeline, storage, tools
from .jobs import JobManager

DEFAULT_SETTINGS = {"theme": "dark", "clip_count": 8, "clip_length": 30, "subtitle_style": "violet",
                    "whisper_model": "base", "export_preset": "tiktok", "notify": True}
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
CONTENT_OK = set(config.CONTENT_TYPES)


def _read_settings() -> dict:
    if config.SETTINGS_FILE.exists():
        try:
            return {**DEFAULT_SETTINGS, **json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError):
            pass
    return dict(DEFAULT_SETTINGS)


def _options(payload: dict) -> dict:
    s = _read_settings()
    cnt = int(payload.get("clip_count") or s["clip_count"])
    return {
        "clip_count": max(config.MIN_CLIPS, min(config.MAX_CLIPS, cnt)),
        "subtitle_style": payload.get("subtitle_style") or s["subtitle_style"],
        "whisper_model": payload.get("whisper_model") or s["whisper_model"],
        "export_preset": payload.get("export_preset") or s["export_preset"],
    }


def _content_type(value: str | None) -> str:
    value = (value or "general").strip()
    if value not in CONTENT_OK:
        raise HTTPException(400, "Неизвестный тип контента")
    return value


def _ranged_file(path: Path, request: Request, media: str) -> Response:
    size = path.stat().st_size
    rng = request.headers.get("range")
    if not rng:
        return FileResponse(path, media_type=media)
    m = RANGE_RE.match(rng)
    if not m:
        return Response(status_code=416)
    start = int(m.group(1)) if m.group(1) else max(size - int(m.group(2)), 0)
    end = int(m.group(2)) if (m.group(2) and m.group(1)) else size - 1
    end = min(end, size - 1)
    if start > end:
        return Response(status_code=416)
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(end - start + 1)
    return Response(content=data, status_code=206, media_type=media, headers={
        "Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes",
        "Content-Length": str(len(data))})


def create_app(jobs: JobManager | None = None) -> FastAPI:
    app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION)
    holder = {"jobs": jobs or JobManager()}

    @app.get("/api/meta")
    def meta():
        try:
            ffmpeg = tools.ffmpeg_bin()
        except tools.ToolError as exc:
            ffmpeg = f"ОШИБКА: {exc}"
        return {"name": config.APP_NAME, "version": config.APP_VERSION,
                "content_types": config.CONTENT_TYPES, "presets": config.EXPORT_PRESETS,
                "subtitle_styles": {k: v["label"] for k, v in config.SUBTITLE_STYLES.items()},
                "whisper_models": list(transcribe_models()), "ffmpeg": ffmpeg,
                "clip": {"count_min": config.MIN_CLIPS, "count_max": config.MAX_CLIPS,
                         "length": config.CLIP_LEN, "tolerance": config.CLIP_TOL},
                "output": {"w": config.OUT_W, "h": config.OUT_H, "fps": config.OUT_FPS}}

    @app.get("/api/settings")
    def get_settings():
        return _read_settings()

    @app.put("/api/settings")
    async def put_settings(request: Request):
        body = await request.json()
        s = {**_read_settings(), **{k: v for k, v in body.items() if k in DEFAULT_SETTINGS}}
        config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        return s

    @app.get("/api/queue")
    def queue_state():
        j = holder["jobs"]
        return {"current": j.current, "queued": j.queued()}

    @app.get("/api/projects")
    def projects():
        return storage.list_projects()

    @app.get("/api/projects/{pid}")
    def project(pid: str):
        try:
            return storage.load_project(pid)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "Проект не найден")

    @app.post("/api/projects")
    async def create(request: Request):
        """Создание проектов по ссылкам: body {urls: [..], content_type, ...options}."""
        body = await request.json()
        urls_raw = body.get("urls") or ([body["url"]] if body.get("url") else [])
        urls = [u for u in (x.strip() for x in urls_raw) if u]
        if not urls:
            raise HTTPException(400, "Вставьте хотя бы одну ссылку")
        ctype = _content_type(body.get("content_type"))
        created = []
        for raw in urls:
            try:
                url = ingest.validate_url(raw)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            proj = storage.create_project(url, "url", ctype, _options(body))
            created.append(proj["id"])
            holder["jobs"].submit(proj["id"])
        return {"ids": created}

    @app.post("/api/projects/upload")
    async def upload(file: UploadFile = File(...), content_type: str = Form("general"),
                     clip_count: int = Form(8), subtitle_style: str = Form("violet"),
                     whisper_model: str = Form("base"), export_preset: str = Form("tiktok")):
        ctype = _content_type(content_type)
        suffix = Path(file.filename or "video.mp4").suffix.lower()
        if suffix not in ingest.VIDEO_EXT:
            raise HTTPException(400, f"Неподдерживаемый формат {suffix or '(без расширения)'}")
        tmp = Path(tempfile.mkdtemp(prefix="harness_up_"))
        tmp_file = tmp / ("upload" + suffix)
        try:
            with open(tmp_file, "wb") as f:
                shutil.copyfileobj(file.file, f)
            ingest.validate_file(tmp_file)
            proj = storage.create_project(str(tmp_file), "file", ctype, _options({
                "clip_count": clip_count, "subtitle_style": subtitle_style,
                "whisper_model": whisper_model, "export_preset": export_preset}))
            # Оригинал переносим в папку проекта, исходник не трогаем.
            dest = storage.project_dir(proj["id"]) / ("source" + suffix)
            shutil.copy2(tmp_file, dest)
            proj["source"] = str(dest)
            storage.save_project(proj)
        except ValueError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise HTTPException(400, str(exc))
        shutil.rmtree(tmp, ignore_errors=True)
        holder["jobs"].submit(proj["id"])
        return {"ids": [proj["id"]]}

    @app.post("/api/projects/{pid}/cancel")
    def cancel(pid: str):
        ok = holder["jobs"].cancel(pid)
        return {"cancelled": ok}

    @app.post("/api/projects/{pid}/retry")
    def retry(pid: str):
        try:
            proj = storage.load_project(pid)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "Проект не найден")
        if proj["status"] in ("running",):
            raise HTTPException(409, "Проект уже обрабатывается")
        holder["jobs"].submit(pid, retry=True)
        return {"ok": True}

    @app.post("/api/projects/{pid}/restyle")
    async def restyle(pid: str, request: Request):
        """Смена стиля субтитров или пресета экспорта: перерендер клипов без повторной транскрибации."""
        body = await request.json()
        proj = storage.load_project(pid)
        if proj["status"] == "running":
            raise HTTPException(409, "Дождитесь окончания обработки")
        if body.get("subtitle_style") in config.SUBTITLE_STYLES:
            proj["options"]["subtitle_style"] = body["subtitle_style"]
            for c in proj["clips"]:
                c["style"] = body["subtitle_style"]
        if body.get("export_preset") in config.EXPORT_PRESETS:
            proj["options"]["export_preset"] = body["export_preset"]
        for c in proj["clips"]:
            c["file"] = None
            c["status"] = "queued"
        storage.save_project(proj)
        holder["jobs"].submit(pid, retry=True)
        return {"ok": True}

    @app.post("/api/projects/{pid}/clips/{idx}/shift")
    async def shift(pid: str, idx: int, request: Request):
        """Ручная подрезка начала клипа: сдвиг ±3 с, длина клипа остаётся 30 с."""
        body = await request.json()
        shift_s = float(body.get("shift", 0.0))
        if abs(shift_s) > 3.0:
            raise HTTPException(400, "Сдвиг ограничен ±3 секундами")
        proj = storage.load_project(pid)
        if proj["status"] == "running":
            raise HTTPException(409, "Дождитесь окончания обработки")
        clip = next((c for c in proj["clips"] if c["index"] == idx), None)
        if clip is None:
            raise HTTPException(404, "Клип не найден")
        new_start = clip["original_start"] + shift_s
        new_end = new_start + config.CLIP_LEN
        if new_start < 0 or new_end > proj.get("duration", 0):
            raise HTTPException(400, "Сдвиг выходит за пределы видео")
        clip.update({"start": new_start, "end": new_end, "shift": shift_s,
                     "file": None, "status": "queued"})
        storage.save_project(proj)
        holder["jobs"].submit(pid, retry=True)
        return {"ok": True, "start": new_start, "end": new_end}

    @app.delete("/api/projects/{pid}")
    def delete(pid: str):
        if holder["jobs"].current == pid:
            holder["jobs"].cancel(pid)
        storage.delete_project(pid)
        return {"ok": True}

    @app.get("/api/projects/{pid}/clips/{idx}/video")
    def clip_video(pid: str, idx: int, request: Request):
        proj = storage.load_project(pid)
        clip = next((c for c in proj["clips"] if c["index"] == idx), None)
        if not clip or not clip.get("file"):
            raise HTTPException(404, "Клип ещё не готов")
        path = storage.project_dir(pid) / clip["file"]
        return _ranged_file(path, request, "video/mp4")

    @app.get("/api/projects/{pid}/clips/{idx}/thumb")
    def clip_thumb(pid: str, idx: int):
        proj = storage.load_project(pid)
        clip = next((c for c in proj["clips"] if c["index"] == idx), None)
        if not clip or not clip.get("thumb"):
            raise HTTPException(404)
        return FileResponse(storage.project_dir(pid) / clip["thumb"], media_type="image/jpeg")

    @app.get("/api/projects/{pid}/clips/{idx}/download")
    def clip_download(pid: str, idx: int):
        proj = storage.load_project(pid)
        clip = next((c for c in proj["clips"] if c["index"] == idx), None)
        if not clip or not clip.get("file"):
            raise HTTPException(404, "Клип ещё не готов")
        return FileResponse(storage.project_dir(pid) / clip["file"], media_type="video/mp4",
                            filename=f"clip_{idx:02d}.mp4")

    @app.get("/api/projects/{pid}/zip")
    def download_all(pid: str):
        proj = storage.load_project(pid)
        out = config.DATA_DIR / "exports" / f"{pid}.zip"
        try:
            pipeline.export_zip(proj, out)
        except tools.ToolError as exc:
            raise HTTPException(409, str(exc))
        return FileResponse(out, media_type="application/zip", filename=f"{pid}_clips.zip")

    @app.get("/api/projects/{pid}/source")
    def source_info(pid: str):
        proj = storage.load_project(pid)
        return {"duration": proj.get("duration"), "width": proj.get("src_w"),
                "height": proj.get("src_h"), "timeline_seconds": proj.get("timeline_seconds")}

    @app.get("/api/projects/{pid}/source/video")
    def source_video(pid: str, request: Request):
        proj = storage.load_project(pid)
        name = proj.get("source_file")
        if not name:
            raise HTTPException(404, "Исходник ещё не загружен")
        return _ranged_file(storage.project_dir(pid) / name, request, "video/mp4")

    if config.UI_DIR.exists():
        app.mount("/", StaticFiles(directory=str(config.UI_DIR), html=True), name="ui")
    return app


def transcribe_models():
    return ("tiny", "base", "small", "medium")
