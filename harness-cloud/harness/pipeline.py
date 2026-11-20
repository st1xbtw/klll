"""Оркестрация пайплайна: модули 1–11 в одном проходе с сохранением состояния.

Каждый шаг пишет статус в project.json. Если шаг упал, проект получает failed_step,
и повтор (retry) продолжает с этого шага, уже готовые артефакты не пересчитываются.
Отмена — через threading.Event, которое проверяется внутри каждого долгого шага.
"""
from __future__ import annotations

import json
import threading
import traceback
from pathlib import Path

import numpy as np

from . import audio, config, faces, ingest, render, scoring, segments as sg, storage, subtitles, text_ai, tools, transcribe
from .tools import StepCancelled, ToolError

STEPS = ["source", "audio", "transcribe", "analyze", "clips"]
STEP_LABELS = {
    "source": "Загрузка видео",
    "audio": "Извлечение аудио",
    "transcribe": "Транскрибация",
    "analyze": "Поиск сильных моментов",
    "clips": "Нарезка и рендер клипов",
}


class Reporter:
    def __init__(self, proj: dict):
        self.proj = proj

    def stage(self, step: str, frac: float = 0.0, text: str = "") -> None:
        self.proj["stage"] = STEP_LABELS.get(step, step) + (f": {text}" if text else "")
        self.proj["progress"] = round(frac, 3)
        storage.save_project(self.proj)

    def clip(self, idx: int, status: str, error: str | None = None) -> None:
        for c in self.proj["clips"]:
            if c["index"] == idx:
                c["status"] = status
                c["error"] = error
        storage.save_project(self.proj)


def _pdir(pid: str) -> Path:
    return storage.project_dir(pid)


def _checkpoint(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise StepCancelled()


def run(pid: str, cancel: threading.Event, retry: bool = False) -> dict:
    proj = storage.load_project(pid)
    rep = Reporter(proj)
    d = _pdir(pid)
    done = set(proj.get("steps_done", []))
    if not retry:
        done = set()
    proj["status"] = "running"
    proj["error"] = None
    proj["failed_step"] = None
    proj["warnings"] = []
    storage.save_project(proj)
    step = "source"
    try:
        # 1) Источник
        step = "source"
        src = d / "source.mp4"
        if "source" not in done:
            rep.stage("source")
            if proj["source_kind"] == "url":
                src = ingest.download(proj["source"], d, cancel,
                                      lambda f, t: rep.stage("source", f, t))
            else:
                src = ingest.copy_upload(Path(proj["source"]), d)
            proj["source_file"] = src.name
            done.add("source")
            _mark(proj, done)
        src = d / proj["source_file"]
        info = tools.probe(src)
        if not info["has_video"]:
            raise ToolError("В источнике нет видеодорожки")
        proj["duration"] = info["duration"]
        proj["src_w"], proj["src_h"] = info["width"], info["height"]
        _checkpoint(cancel)

        # 2) Аудио
        step = "audio"
        wav = d / "audio.wav"
        if "audio" not in done:
            rep.stage("audio")
            if not info["has_audio"]:
                raise ToolError("В видео нет аудиодорожки: без речи и громкости поиск моментов невозможен")
            audio.extract_wav(src, wav, cancel)
            done.add("audio")
            _mark(proj, done)
        _checkpoint(cancel)

        # 3) Транскрибация (с fallback)
        step = "transcribe"
        tr_path = d / "transcript.json"
        if "transcribe" not in done:
            rep.stage("transcribe")
            override = Path(proj["options"]["transcript_override"]) if proj["options"].get("transcript_override") else None
            segs, reason = transcribe.transcribe(
                wav, proj["options"].get("whisper_model", "base"), cancel,
                lambda f, t: rep.stage("transcribe", f, t), override)
            if segs is None:
                proj["warnings"].append(
                    f"Транскрибация пропущена: {reason}. Субтитры и текст хука не добавлены, "
                    "клипы выбраны по громкости, речи и паузам.")
                segs = []
            tr_path.write_text(json.dumps({"segments": segs}, ensure_ascii=False), encoding="utf-8")
            done.add("transcribe")
            _mark(proj, done)
        segments = json.loads(tr_path.read_text(encoding="utf-8"))["segments"]
        words = transcribe.flatten_words(segments) or None
        _checkpoint(cancel)

        # 4–6) Скоринг, выбор и ранжирование
        step = "analyze"
        if "analyze" not in done:
            rep.stage("analyze")
            samples = audio.read_samples(wav)
            ctype = proj["content_type"]
            feat = scoring.build_features(samples, words, ctype, info["duration"])
            cands = scoring.score_windows(feat, config.CLIP_LEN, ctype)
            if not cands:
                raise ToolError("Видео короче 30 секунд — клипы не из чего собрать")
            count = int(proj["options"].get("clip_count", 8))
            count = max(config.MIN_CLIPS, min(config.MAX_CLIPS, count))
            chosen = scoring.select_clips(cands, feat, count, config.CLIP_LEN, ctype, words)
            if len(chosen) < config.MIN_CLIPS:
                raise ToolError(f"Найдено непересекающихся окон по 30 с: {len(chosen)}, нужно минимум "
                                f"{config.MIN_CLIPS}. Видео слишком короткое или речи слишком мало.")
            if len(chosen) < count:
                proj["warnings"].append(f"Запрошено {count} клипов, найдено {len(chosen)} непересекающихся.")
            scores = [c.score for c in chosen]
            lo, hi = min(scores), max(scores)
            clips = []
            for rank, c in enumerate(chosen, start=1):
                pct = 99 if hi - lo < 1e-9 else int(round(78 + 21 * (c.score - lo) / (hi - lo)))
                clips.append({
                    "index": rank, "start": c.start, "end": c.end,
                    "original_start": c.start, "original_end": c.end,
                    "segments": [[c.start, c.end]], "origin": "auto",
                    "framing": proj["options"].get("framing", "face"),
                    "aspect": proj["options"].get("aspect", config.DEFAULT_ASPECT),
                    "sub_box": bool(proj["options"].get("sub_box")),
                    "sub_emoji": bool(proj["options"].get("sub_emoji")),
                    "sub_anim": bool(proj["options"].get("sub_anim")),
                    "duration": config.CLIP_LEN, "score": pct,
                    "parts": {k: round(v, 3) for k, v in c.parts.items()},
                    "reason": c.reason, "text": "", "hook": "", "hook_source": "",
                    "description": "", "hashtags": [], "status": "queued", "error": None,
                    "file": None, "thumb": None, "verify": None,
                    "subtitles": proj["options"].get("subtitles", ctype != "game"),
                    "style": proj["options"].get("subtitle_style", "violet"),
                    "timeline": [round(float(x), 3) for x in feat["loud"][::2]],
                })
            proj["clips"] = clips
            proj["timeline_seconds"] = feat["n"]
            done.add("analyze")
            _mark(proj, done)
        _checkpoint(cancel)

        # 7–11) По клипам
        step = "clips"
        preset = proj["options"].get("export_preset", "tiktok")
        total = len(proj["clips"])
        rep.stage("clips", 0.0, f"0/{total}")
        for i, clip in enumerate(proj["clips"]):
            _checkpoint(cancel)
            if clip.get("status") == "done" and clip.get("file") and (d / clip["file"]).exists():
                continue
            rep.clip(clip["index"], "processing")
            try:
                _render_one(proj, clip, src, d, words, segments, preset, cancel)
                rep.clip(clip["index"], "done")
            except StepCancelled:
                raise
            except Exception as exc:  # один клип не валит весь проект
                msg = str(exc)[:400]
                rep.clip(clip["index"], "error", msg)
                proj["warnings"].append(f"Клип {clip['index']}: {msg}")
            rep.stage("clips", (i + 1) / total, f"{i + 1}/{total}")
        done.add("clips")
        _mark(proj, done)

        proj["status"] = "done"
        proj["stage"] = "Готово"
        proj["progress"] = 1.0
        proj["steps_done"] = sorted(done)
        storage.save_project(proj)
        return proj
    except StepCancelled:
        proj["status"] = "cancelled"
        proj["stage"] = "Отменено"
        proj["failed_step"] = step
        storage.save_project(proj)
        return proj
    except Exception as exc:
        proj["status"] = "error"
        proj["failed_step"] = step
        proj["error"] = f"{STEP_LABELS.get(step, step)}: {exc}"
        proj["trace"] = traceback.format_exc()[-1500:] if not isinstance(exc, ToolError) else None
        proj["stage"] = "Ошибка"
        proj["steps_done"] = sorted(done)
        storage.save_project(proj)
        return proj


def _mark(proj: dict, done: set) -> None:
    proj["steps_done"] = sorted(done)
    storage.save_project(proj)


def _render_one(proj: dict, clip: dict, src: Path, d: Path, words, segments, preset: str,
                cancel: threading.Event) -> None:
    """Рендер одного клипа: отрезки, текст, кадр, субтитры, хук, файл и метаданные."""
    idx = clip["index"]
    cdir = d / "clips" / f"{idx:02d}"
    cdir.mkdir(parents=True, exist_ok=True)
    segs = clip.get("segments") or [[clip["start"], clip["end"]]]
    start, end = sg.span(segs)
    dur = sg.total(segs)
    ctype = proj["content_type"]

    clip_words = sg.words_for_clip(segs, words or [])
    clip_text = " ".join(w["w"] for w in clip_words)
    clip["text"] = clip_text
    sentences = [s["text"] for s in segments
                 if any(a - 0.05 <= s["start"] and s["end"] <= b + 0.05 for a, b in segs) and s["text"]]

    framing = clip.get("framing") or "face"
    out_w, out_h = config.out_size(clip.get("aspect"))
    plans: list = []
    if framing == "face":
        for a, b in segs:
            plans.append(faces.track_clip(src, a, b - a, proj["src_w"], proj["src_h"], out_w, out_h))
    else:
        plans = [None] * len(segs)
    first = plans[0] if plans and plans[0] is not None else None
    clip["face"] = ({"found": first.faces_found, "samples": first.samples, "fallback_center": first.fallback}
                    if first is not None else {"found": 0, "samples": 0, "fallback_center": False})

    use_subs = bool(clip.get("subtitles", ctype != "game"))
    hook, hook_src = "", ""
    if use_subs:
        hook, hook_src = text_ai.hook_for(clip_text, sentences, ctype)
    clip["hook"] = hook
    clip["hook_source"] = hook_src if hook else ""

    ass = None
    if use_subs or hook:
        ass = subtitles.build_ass(
            clip_words, dur, hook or None, clip["style"], cdir / "sub.ass", subtitles=use_subs,
            box=bool(clip.get("sub_box")), anim=bool(clip.get("sub_anim")),
            emoji=bool(clip.get("sub_emoji")), out_w=out_w, out_h=out_h)
    out = cdir / "clip.mp4"
    if len(segs) == 1:
        res = render.render_clip(src, start, dur, plans[0], ass, out, preset, cancel,
                                 framing=framing, src_w=proj["src_w"], src_h=proj["src_h"],
                                 out_w=out_w, out_h=out_h)
    else:
        res = render.render_segments(src, [tuple(x) for x in segs], plans, framing,
                                     proj["src_w"], proj["src_h"], ass, out, preset, cancel,
                                     out_w=out_w, out_h=out_h)
    render.make_thumb(out, cdir / "thumb.jpg")
    meta = text_ai.describe(clip_text, hook, ctype)
    platforms = text_ai.describe_platforms(clip_text, hook, ctype)
    clip.update({
        "description": meta["description"], "hashtags": meta["hashtags"],
        "platforms": platforms,
        "file": f"clips/{idx:02d}/clip.mp4", "thumb": f"clips/{idx:02d}/thumb.jpg",
        "verify": res, "error": None,
    })
    if not res["ok"]:
        raise ToolError(f"Проверка клипа не пройдена: {res}")
    clip["status"] = "done"


def export_zip(proj: dict, dest: Path) -> Path:
    import zipfile
    d = _pdir(proj["id"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    ready = [c for c in proj["clips"] if c.get("file") and (d / c["file"]).exists()]
    if not ready:
        raise ToolError("Нет готовых клипов для архива")
    meta = {
        "project": proj["id"], "source": proj["source"], "content_type": proj["content_type"],
        "clips": [{k: c.get(k) for k in ("index", "start", "end", "duration", "score", "reason",
                                         "hook", "description", "hashtags", "text", "file")}
                  for c in ready],
    }
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for c in ready:
            z.write(d / c["file"], arcname=f"clip_{c['index']:02d}.mp4")
        z.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))
    return dest
