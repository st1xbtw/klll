"""HTTP-слой (FastAPI). Отдаёт интерфейс и API для окна pywebview или браузера."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import clipedit, config, fonts, ingest, live, notify as notify_mod, pipeline, storage, tools, segments as sg
from .jobs import JobManager

DEFAULT_SETTINGS = {"theme": "dark", "clip_count": 8, "clip_length": 30, "subtitle_style": config.DEFAULT_SUBTITLE_STYLE,
                    "whisper_model": "base", "export_preset": "tiktok", "notify": True, "save_dir": "",
                    "quality": "1080p", "fps": 30, "save_min_score": 0,
                    "offline": False}
# Нативный выбор папки. Задаёт run.py при запуске окна pywebview; None — выбор недоступен (браузер).
FOLDER_PICKER = None
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
CONTENT_OK = set(config.CONTENT_TYPES)
FRAMINGS = {"face": "По лицу", "fit": "Вписать с фоном"}


def _checked_dir(value) -> str:
    """Проверяет папку сохранения: пусто или абсолютный путь, который можно создать."""
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise HTTPException(400, "Укажите полный путь к папке")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(400, f"Не удалось создать папку: {exc}")
    return str(path)


def _read_settings() -> dict:
    if config.SETTINGS_FILE.exists():
        try:
            return {**DEFAULT_SETTINGS, **json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError):
            pass
    return dict(DEFAULT_SETTINGS)


def _clean_family(value) -> str:
    """Имя шрифта из запроса: только безопасные символы (оно попадает в строку стиля ASS)."""
    v = str(value or "").strip()
    return v if re.fullmatch(r"[\w .\-]{1,60}", v, re.UNICODE) else ""


def _pct(value) -> float | None:
    """Положение субтитров в процентах кадра 0..100; None — стандартное место внизу."""
    if value in (None, "", "null"):
        return None
    try:
        return round(min(100.0, max(0.0, float(value))), 2)
    except (TypeError, ValueError):
        return None


def _flag(value) -> bool:
    """Булево из JSON или из формы: строки 'false', '0', '' — ложь."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _options(payload: dict) -> dict:
    s = _read_settings()
    cnt = int(payload.get("clip_count") or s["clip_count"])
    return {
        "clip_count": max(config.MIN_CLIPS, min(config.MAX_CLIPS, cnt)),
        "subtitle_style": payload.get("subtitle_style") or s["subtitle_style"],
        "whisper_model": payload.get("whisper_model") or s["whisper_model"],
        "export_preset": payload.get("export_preset") or s["export_preset"],
        "framing": payload.get("framing") if payload.get("framing") in FRAMINGS else "face",
        "aspect": payload.get("aspect") if payload.get("aspect") in config.ASPECTS else config.DEFAULT_ASPECT,
        "quality": payload.get("quality") if payload.get("quality") in config.QUALITIES else s["quality"],
        "fps": config.parse_fps(payload.get("fps")) or config.parse_fps(s["fps"]) or config.DEFAULT_FPS,
        "subtitles": _flag(payload["subtitles"]) if "subtitles" in payload else True,
        "watermark": str(payload.get("watermark") or "").strip()[:40],
        "sub_font": _clean_family(payload.get("sub_font")),
        "sub_effect": payload.get("sub_effect") if payload.get("sub_effect") in config.SUB_EFFECTS else "none",
        "sub_x": _pct(payload.get("sub_x")), "sub_y": _pct(payload.get("sub_y")),
        "sub_box": _flag(payload.get("sub_box")),
        "sub_emoji": _flag(payload.get("sub_emoji")),
        "sub_anim": _flag(payload.get("sub_anim")),
        "clip_len": config.clamp_clip_len(payload.get("clip_len")),
        "show_hook": _flag(payload["show_hook"]) if "show_hook" in payload else True,
        "sub_place": payload.get("sub_place") if payload.get("sub_place") in config.SUB_PLACES
        else config.DEFAULT_SUB_PLACE,
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

    def _live_window(path: Path, label: str, content_type: str, options: dict) -> str:
        """Окно эфира становится обычным проектом и уходит в очередь обработки."""
        proj = storage.create_project(str(path), "file", content_type, options)
        proj["title"] = label
        dest = storage.project_dir(proj["id"]) / "source.mp4"
        shutil.copy2(path, dest)
        proj["source"] = str(dest)
        storage.save_project(proj)
        holder["jobs"].submit(proj["id"])
        return proj["id"]

    holder["live"] = live.LiveManager(live.live_root(), on_window=_live_window)

    @app.get("/api/fonts")
    def list_fonts():
        try:
            items = fonts.list_fonts()
        except Exception as exc:  # шрифты — необязательная часть: эффекты и работа приложения не должны зависеть от них
            print(f"Список шрифтов недоступен: {exc}", flush=True)
            items = []
        return {"fonts": items, "effects": config.SUB_EFFECTS}

    @app.post("/api/fonts")
    async def upload_font(file: UploadFile = File(...)):
        """Пользовательский шрифт .ttf/.otf для субтитров."""
        tmp = Path(tempfile.mkdtemp(prefix="font-")) / "upload"
        try:
            with open(tmp, "wb") as fh:
                shutil.copyfileobj(file.file, fh, length=1024 * 1024)
            try:
                item = fonts.add_user_font(tmp, file.filename or "font.ttf")
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            return {"ok": True, "font": item, "fonts": fonts.list_fonts()}
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)

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
                "output": {"w": config.OUT_W, "h": config.OUT_H, "fps": config.DEFAULT_FPS},
                "aspects": {k: list(v) for k, v in config.ASPECTS.items()},
                "qualities": config.QUALITY_LABELS, "fps_choices": config.FPS_CHOICES,
                "fps_min": config.FPS_MIN, "fps_max": config.FPS_MAX}

    @app.get("/api/settings")
    def get_settings():
        return _read_settings()

    @app.put("/api/settings")
    async def put_settings(request: Request):
        body = await request.json()
        s = {**_read_settings(), **{k: v for k, v in body.items() if k in DEFAULT_SETTINGS}}
        if "save_dir" in s:
            s["save_dir"] = _checked_dir(s["save_dir"])
        s["offline"] = bool(s.get("offline"))
        if s.get("quality") not in config.QUALITIES:
            s["quality"] = DEFAULT_SETTINGS["quality"]
        s["fps"] = config.parse_fps(s.get("fps")) or DEFAULT_SETTINGS["fps"]
        try:
            s["save_min_score"] = max(0, min(100, int(float(s.get("save_min_score") or 0))))
        except (TypeError, ValueError):
            s["save_min_score"] = 0
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
        if config.offline_mode():
            raise HTTPException(409, "Офлайн-режим включён: загрузка по ссылке недоступна. "
                                     "Добавьте видеофайл или выключите офлайн-режим в настройках.")
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
                     clip_count: int = Form(8), subtitle_style: str = Form(config.DEFAULT_SUBTITLE_STYLE),
                     whisper_model: str = Form("base"), export_preset: str = Form("tiktok"),
                     framing: str = Form("face"), sub_box: str = Form("0"),
                     sub_emoji: str = Form("0"), sub_anim: str = Form("0"),
                     aspect: str = Form("9:16"), quality: str = Form("1080p"), fps: int = Form(30),
                     subtitles: str = Form("1"), show_hook: str = Form("1"),
                     sub_place: str = Form("bottom"), clip_len: float = Form(config.DEFAULT_CLIP_LEN),
                     watermark: str = Form(""), sub_font: str = Form(""), sub_effect: str = Form("none")):
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
                "whisper_model": whisper_model, "export_preset": export_preset,
                "framing": framing, "sub_box": sub_box, "sub_emoji": sub_emoji, "sub_anim": sub_anim,
                "aspect": aspect, "quality": quality, "fps": fps,
                "subtitles": subtitles, "show_hook": show_hook, "sub_place": sub_place,
                "clip_len": clip_len,
                "watermark": watermark, "sub_font": sub_font, "sub_effect": sub_effect}))
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
        if body.get("framing") in FRAMINGS:
            proj["options"]["framing"] = body["framing"]
        if body.get("aspect") in config.ASPECTS:
            proj["options"]["aspect"] = body["aspect"]
        if body.get("quality") in config.QUALITIES:
            proj["options"]["quality"] = body["quality"]
        if config.parse_fps(body.get("fps")):
            proj["options"]["fps"] = config.parse_fps(body["fps"])
        if "subtitles" in body:
            proj["options"]["subtitles"] = _flag(body["subtitles"])
        if "watermark" in body:
            proj["options"]["watermark"] = str(body.get("watermark") or "").strip()[:40]
        if "sub_font" in body:
            proj["options"]["sub_font"] = _clean_family(body.get("sub_font"))
        if "sub_effect" in body and body.get("sub_effect") in config.SUB_EFFECTS:
            proj["options"]["sub_effect"] = body["sub_effect"]
        if "sub_x" in body or "sub_y" in body:
            proj["options"]["sub_x"] = _pct(body.get("sub_x"))
            proj["options"]["sub_y"] = _pct(body.get("sub_y"))
        for flag in ("sub_box", "sub_emoji", "sub_anim", "show_hook"):
            if flag in body:
                proj["options"][flag] = _flag(body[flag])
        if body.get("sub_place") in config.SUB_PLACES:
            proj["options"]["sub_place"] = body["sub_place"]
            # Выбор места из списка сбрасывает ручную позицию маркера, иначе она перекроет пресет.
            proj["options"]["sub_x"] = None
            proj["options"]["sub_y"] = None
        for c in proj["clips"]:
            c["file"] = None
            c["status"] = "queued"
            c["framing"] = proj["options"].get("framing", "face")
            c["sub_box"] = _flag(proj["options"].get("sub_box"))
            c["sub_emoji"] = bool(proj["options"].get("sub_emoji"))
            c["sub_anim"] = bool(proj["options"].get("sub_anim"))
            c["show_hook"] = bool(proj["options"].get("show_hook", proj["content_type"] != "game"))
            c["sub_place"] = proj["options"].get("sub_place", config.DEFAULT_SUB_PLACE)
            c["aspect"] = proj["options"].get("aspect", config.DEFAULT_ASPECT)
            c["quality"] = proj["options"].get("quality", config.DEFAULT_QUALITY)
            c["fps"] = proj["options"].get("fps", config.DEFAULT_FPS)
            c["watermark"] = proj["options"].get("watermark", "")
            c["sub_font"] = proj["options"].get("sub_font", "")
            c["sub_effect"] = proj["options"].get("sub_effect", "none")
            c["sub_x"] = proj["options"].get("sub_x")
            c["sub_y"] = proj["options"].get("sub_y")
            c["subtitles"] = proj["options"].get("subtitles", proj["content_type"] != "game")
            if body.get("subtitle_style") in config.SUBTITLE_STYLES:
                c["style"] = body["subtitle_style"]
        proj["status"] = "queued"          # до старта рабочего потока показываем «В очереди», а не «Готово»
        proj["stage"] = "В очереди"
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
        new_end = new_start + float(clip.get("duration") or config.CLIP_LEN)
        if new_start < 0 or new_end > proj.get("duration", 0):
            raise HTTPException(400, "Сдвиг выходит за пределы видео")
        if len(clip.get("segments") or []) > 1:
            raise HTTPException(400, "Клип собран из нескольких фрагментов: сдвиг начала недоступен")
        clip.update({"start": new_start, "end": new_end, "shift": shift_s,
                     "segments": [[new_start, new_end]],
                     "file": None, "status": "queued"})
        storage.save_project(proj)
        holder["jobs"].submit(pid, retry=True)
        return {"ok": True, "start": new_start, "end": new_end}

    def _load_idle(pid: str) -> dict:
        try:
            proj = storage.load_project(pid)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "Проект не найден")
        if proj["status"] == "running":
            raise HTTPException(409, "Дождитесь окончания обработки")
        return proj

    def _find(proj: dict, idx: int) -> dict:
        clip = next((c for c in proj["clips"] if c["index"] == idx), None)
        if clip is None:
            raise HTTPException(404, "Клип не найден")
        return clip

    def _new_clip(proj: dict, segs: list, origin: str, reason: str) -> dict:
        idx = max([c["index"] for c in proj["clips"]] + [0]) + 1
        start, end = sg.span(segs)
        ctype = proj["content_type"]
        return {
            "index": idx, "start": start, "end": end,
            "original_start": start, "original_end": end,
            "segments": segs, "origin": origin,
            "framing": proj["options"].get("framing", "face"),
            "aspect": proj["options"].get("aspect", config.DEFAULT_ASPECT),
            "quality": proj["options"].get("quality", config.DEFAULT_QUALITY),
            "fps": proj["options"].get("fps", config.DEFAULT_FPS),
            "watermark": proj["options"].get("watermark", ""),
            "sub_font": proj["options"].get("sub_font", ""),
            "sub_effect": proj["options"].get("sub_effect", "none"),
            "sub_x": proj["options"].get("sub_x"), "sub_y": proj["options"].get("sub_y"),
            "sub_box": bool(proj["options"].get("sub_box")),
            "sub_emoji": bool(proj["options"].get("sub_emoji")),
            "sub_anim": bool(proj["options"].get("sub_anim")),
            "show_hook": bool(proj["options"].get("show_hook", ctype != "game")),
            "sub_place": proj["options"].get("sub_place", config.DEFAULT_SUB_PLACE),
            "duration": config.CLIP_LEN, "score": None, "parts": {},
            "reason": reason, "text": "", "hook": "", "hook_source": "",
            "description": "", "hashtags": [], "platforms": {},
            "status": "queued", "error": None, "file": None, "thumb": None, "verify": None,
            "subtitles": proj["options"].get("subtitles", ctype != "game"),
            "style": proj["options"].get("subtitle_style", config.DEFAULT_SUBTITLE_STYLE),
            "timeline": proj["clips"][0]["timeline"] if proj["clips"] else [],
        }

    @app.post("/api/projects/{pid}/clips/custom")
    async def custom_clip(pid: str, request: Request):
        """Новый клип на 30 с, начиная с выбранной точки на таймлайне исходника."""
        body = await request.json()
        proj = _load_idle(pid)
        try:
            segs = sg.custom_clip(float(body.get("start", 0)), float(proj.get("duration") or 0))
        except sg.SegmentError as exc:
            raise HTTPException(400, str(exc))
        clip = _new_clip(proj, segs, "manual", "Выбрано вручную")
        proj["clips"].append(clip)
        storage.save_project(proj)
        holder["jobs"].submit(pid, retry=True)
        return {"ok": True, "index": clip["index"]}

    @app.post("/api/projects/{pid}/clips/{idx}/cut")
    async def cut_clip(pid: str, idx: int, request: Request):
        """Вырезать фрагмент [a, b] из клипа; недостающие секунды добираются из исходника."""
        body = await request.json()
        proj = _load_idle(pid)
        clip = _find(proj, idx)
        try:
            segs = sg.cut(clip.get("segments") or [[clip["start"], clip["end"]]],
                          float(body["a"]), float(body["b"]), float(proj.get("duration") or 0))
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc))
        clip.update({"segments": segs, "start": segs[0][0], "end": segs[-1][1],
                     "origin": "edited", "file": None, "status": "queued",
                     "reason": "Отредактировано вручную"})
        storage.save_project(proj)
        holder["jobs"].submit(pid, retry=True)
        return {"ok": True, "segments": segs}

    @app.post("/api/projects/{pid}/clips/merge")
    async def merge_clips(pid: str, request: Request):
        """Склейка: первые 15 с клипа a + первые 15 с клипа b → новый клип 30 с."""
        body = await request.json()
        proj = _load_idle(pid)
        a = _find(proj, int(body.get("a", 0)))
        b = _find(proj, int(body.get("b", 0)))
        if a["index"] == b["index"]:
            raise HTTPException(400, "Выберите два разных клипа")
        try:
            segs = sg.merge(a.get("segments") or [[a["start"], a["end"]]],
                            b.get("segments") or [[b["start"], b["end"]]])
        except sg.SegmentError as exc:
            raise HTTPException(400, str(exc))
        clip = _new_clip(proj, segs, "merged", f"Склеено из клипов {a['index']} и {b['index']}")
        proj["clips"].append(clip)
        storage.save_project(proj)
        holder["jobs"].submit(pid, retry=True)
        return {"ok": True, "index": clip["index"], "segments": segs}

    @app.delete("/api/projects/{pid}")
    def delete(pid: str):
        if holder["jobs"].current == pid:
            holder["jobs"].cancel(pid)
        storage.delete_project(pid)
        return {"ok": True}

    @app.post("/api/projects/{pid}/clips/{idx}/subtitles")
    async def clip_subtitles(pid: str, idx: int, request: Request):
        """Правка текста субтитров клипа. Пустой текст возвращает автоматическую расшифровку."""
        body = await request.json()
        try:
            text = clipedit.normalize_text(body.get("text"))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        proj = _load_idle(pid)
        clip = _find(proj, idx)
        if text:
            d = storage.project_dir(pid)
            base = clipedit.clip_base_words(clip, clipedit.load_words(d))
            segs = clip.get("segments") or [[clip["start"], clip["end"]]]
            clip["sub_words"] = clipedit.retime(text, base, sg.total(segs))
        else:
            clip.pop("sub_words", None)
        clip.update({"file": None, "status": "queued", "error": None})
        storage.save_project(proj)
        holder["jobs"].submit(pid, retry=True)
        return {"ok": True, "words": len(clip.get("sub_words") or [])}

    @app.post("/api/projects/{pid}/clips/{idx}/preview")
    def clip_preview(pid: str, idx: int):
        """Собирает предпросмотр первых 4 секунд клипа в 480p с текущими настройками."""
        proj = _load_idle(pid)
        clip = _find(proj, idx)
        try:
            clipedit.render_preview(proj, clip, storage.project_dir(pid))
        except tools.ToolError as exc:
            raise HTTPException(500, str(exc))
        return {"ok": True, "url": f"/api/projects/{pid}/clips/{idx}/preview/video?v={int(time.time())}"}

    @app.get("/api/projects/{pid}/clips/{idx}/preview/video")
    def clip_preview_video(pid: str, idx: int, request: Request):
        path = storage.project_dir(pid) / "clips" / f"{idx:02d}" / "preview.mp4"
        if not path.exists():
            raise HTTPException(404, "Предпросмотр ещё не собран")
        return _ranged_file(path, request, "video/mp4")

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

    @app.get("/api/estimate")
    def estimate(count: int = 5, quality: str = "1080p", fps: int = 30, aspect: str = "9:16",
                 clip_len: float = config.DEFAULT_CLIP_LEN):
        """Оценка времени рендера клипов по выбранным качеству, частоте кадров и формату."""
        q = quality if quality in config.QUALITIES else config.DEFAULT_QUALITY
        f = config.parse_fps(fps) or config.DEFAULT_FPS
        a = aspect if aspect in config.ASPECTS else config.DEFAULT_ASPECT
        cnt = max(config.MIN_CLIPS, min(config.MAX_CLIPS, int(count)))
        sec = config.estimate_seconds(cnt, q, f, a, config.clamp_clip_len(clip_len), config.render_workers(),
                                      pipeline.render_speed())
        w, h = config.out_size(a, q)
        return {"seconds": round(sec), "clips": cnt, "width": w, "height": h, "fps": f,
                "calibrated": config.CALIBRATION_FILE.exists()}

    @app.post("/api/projects/{pid}/clips/{idx}/schedule")
    async def schedule_clip(pid: str, idx: int, request: Request):
        """Дата и время публикации клипа. Приложение не публикует сам: это план для ручной публикации."""
        from datetime import datetime
        body = await request.json()
        value = str(body.get("publish_at") or "").strip()
        if value:
            try:
                datetime.fromisoformat(value)
            except ValueError:
                raise HTTPException(400, "Некорректная дата публикации")
        proj = storage.load_project(pid)
        clip = next((c for c in proj["clips"] if c["index"] == idx), None)
        if clip is None:
            raise HTTPException(404, "Клип не найден")
        clip["publish_at"] = value
        storage.save_project(proj)
        return {"ok": True, "publish_at": value}

    @app.post("/api/projects/{pid}/save")
    def save_project_files(pid: str):
        root = pipeline.save_dir_setting()
        if not root:
            raise HTTPException(400, "Папка сохранения не выбрана: укажите её в настройках")
        proj = storage.load_project(pid)
        try:
            dest = pipeline.save_to_folder(proj, Path(root))
        except tools.ToolError as exc:
            raise HTTPException(409, str(exc))
        except OSError as exc:
            raise HTTPException(500, f"Не удалось записать в папку: {exc}")
        return {"path": str(dest)}

    @app.post("/api/pick-folder")
    def pick_folder():
        if FOLDER_PICKER is None:
            raise HTTPException(501, "Выбор папки доступен в окне приложения. Введите путь вручную.")
        try:
            chosen = FOLDER_PICKER()
        except Exception as exc:
            raise HTTPException(500, f"Не удалось открыть диалог: {exc}")
        return {"path": chosen or ""}

    @app.get("/api/projects/{pid}/zip")
    def download_all(pid: str):
        proj = storage.load_project(pid)
        out = config.DATA_DIR / "exports" / f"{pid}.zip"
        try:
            pipeline.export_zip(proj, out)
        except tools.ToolError as exc:
            raise HTTPException(409, str(exc))
        return FileResponse(out, media_type="application/zip", filename=f"{pid}_clips.zip")

    @app.post("/api/live")
    async def live_start(body: dict = Body(...)):
        """Запись эфира по ссылке. Обязательно подтверждение прав: body.rights = true."""
        if not body.get("rights"):
            raise HTTPException(400, "Подтвердите, что у вас есть права на эту трансляцию")
        ctype = _content_type(body.get("content_type"))
        try:
            session = holder["live"].start(str(body.get("url") or ""), ctype, _options(body))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"id": session.id}

    @app.get("/api/live")
    def live_list():
        return {"sessions": holder["live"].all()}

    @app.post("/api/live/{sid}/stop")
    def live_stop(sid: str):
        session = holder["live"].get(sid)
        if session is None:
            raise HTTPException(404, "Запись не найдена")
        session.request_stop()
        return {"ok": True}

    @app.post("/api/notify")
    async def notify(request: Request):
        """Системное уведомление о завершении обработки (тост Windows)."""
        body = await request.json()
        ok = notify_mod.show(str(body.get("title") or "Harness Cloud"), str(body.get("body") or ""))
        return {"ok": ok}

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
