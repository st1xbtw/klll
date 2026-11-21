"""Модули 7–8: детекция лиц (OpenCV Haar), трекинг по клипу и расчёт окна 9:16.

Детектор: Haar frontal face (встроенный каскад). Fallback: если лица не найдены,
окно кадра центрируется по середине исходного кадра.
Сглаживание: медианный фильтр по выборкам + ограничение скорости движения окна
(чтобы кадр не дёргался) + линейная интерполяция между ключевыми кадрами.
"""
from __future__ import annotations
import threading

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import config

SAMPLE_STEP = 0.5          # секунд между детекциями
KEY_STEP = 1.0             # шаг ключевых кадров для ffmpeg-выражения
_local = threading.local()  # каскад не потокобезопасен: по одному экземпляру на поток


def _get_cascade():
    c = getattr(_local, "cascade", None)
    if c is None:
        path = config.MODELS_DIR / "haarcascade_frontalface_default.xml"
        if not path.exists():
            raise FileNotFoundError(f"Нет файла каскада: {path}")
        c = cv2.CascadeClassifier(str(path))
        if c.empty():
            raise RuntimeError("Не удалось загрузить каскад Haar")
        _local.cascade = c
    return c


@dataclass
class CropPlan:
    src_w: int
    src_h: int
    crop_w: int
    crop_h: int
    keys: list[tuple[float, float, float]]   # (t_rel, x, y) в пикселях исходника
    faces_found: int
    samples: int
    fallback: bool


def crop_size(src_w: int, src_h: int, out_w: int = 1080, out_h: int = 1920) -> tuple[int, int]:
    """Максимальное окно нужного соотношения сторон, вписанное в исходный кадр (чётные размеры)."""
    ratio = out_w / out_h
    if src_w / src_h >= ratio:
        ch = src_h
        cw = ch * ratio
    else:
        cw = src_w
        ch = cw / ratio
        if ch > src_h:
            ch = src_h
            cw = ch * ratio
    cw, ch = int(cw) // 2 * 2, int(ch) // 2 * 2
    return cw, ch


def _detect(frame_gray: np.ndarray, scale: float) -> tuple[float, float, float] | None:
    small = cv2.resize(frame_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    faces = _get_cascade().detectMultiScale(
        small, scaleFactor=1.15, minNeighbors=5, minSize=(30, 30))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda r: r[2] * r[3])   # самое крупное лицо — говорящий
    inv = 1.0 / scale
    return ((x + w / 2) * inv, (y + h / 2) * inv, w * inv)


def track_clip(src: Path, start: float, duration: float, src_w: int, src_h: int,
               out_w: int = 1080, out_h: int = 1920) -> CropPlan:
    cw, ch = crop_size(src_w, src_h, out_w, out_h)
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError("OpenCV не открыл видео для детекции лиц")
    scale = min(1.0, 960.0 / src_w)
    times = np.arange(0.0, duration + 1e-6, SAMPLE_STEP)
    cx = np.full(len(times), np.nan)
    cy = np.full(len(times), np.nan)
    try:
        for i, t in enumerate(times):
            cap.set(cv2.CAP_PROP_POS_MSEC, (start + t) * 1000.0)
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            hit = _detect(gray, scale)
            if hit:
                cx[i], cy[i], _ = hit
    finally:
        cap.release()

    found = int(np.sum(~np.isnan(cx)))
    fallback = found == 0
    if fallback:
        cx[:] = src_w / 2
        cy[:] = src_h / 2
    else:
        cx = _fill_and_smooth(cx, max_step=cw * 0.12)
        cy = _fill_and_smooth(cy, max_step=ch * 0.12)

    # Окно кадра: центр на лице, с границами исходника.
    xs = np.clip(cx - cw / 2, 0, src_w - cw)
    ys = np.clip(cy - ch / 2, 0, src_h - ch)
    key_t = np.arange(0.0, duration + 1e-6, KEY_STEP)
    if key_t[-1] < duration:
        key_t = np.append(key_t, duration)
    kx = np.interp(key_t, times, xs)
    ky = np.interp(key_t, times, ys)
    keys = [(float(t), float(x), float(y)) for t, x, y in zip(key_t, kx, ky)]
    return CropPlan(src_w, src_h, cw, ch, keys, found, len(times), fallback)


def _fill_and_smooth(v: np.ndarray, max_step: float) -> np.ndarray:
    idx = np.arange(len(v))
    good = ~np.isnan(v)
    filled = np.interp(idx, idx[good], v[good])
    # медиана по 5 выборкам — убирает выбросы детектора
    pad = np.pad(filled, 2, mode="edge")
    med = np.array([np.median(pad[i:i + 5]) for i in range(len(filled))])
    # ограничение скорости: окно не может «прыгнуть» дальше max_step за выборку
    out = med.copy()
    for i in range(1, len(out)):
        d = out[i] - out[i - 1]
        if abs(d) > max_step:
            out[i] = out[i - 1] + np.sign(d) * max_step
    # экспоненциальное сглаживание
    alpha = 0.35
    for i in range(1, len(out)):
        out[i] = alpha * out[i] + (1 - alpha) * out[i - 1]
    return out


def ffmpeg_crop_expr(keys: list[tuple[float, float, float]], axis: int) -> str:
    """Кусочно-линейное выражение для фильтра crop по времени t (сек от начала клипа)."""
    pts = [(k[0], k[axis]) for k in keys]
    if len(pts) == 1:
        return f"{pts[0][1]:.2f}"
    expr = f"{pts[-1][1]:.2f}"
    for i in range(len(pts) - 2, -1, -1):
        t0, v0 = pts[i]
        t1, v1 = pts[i + 1]
        seg = f"{v0:.2f}+({v1 - v0:.4f})*(t-{t0:.3f})/{max(t1 - t0, 1e-3):.3f}"
        expr = f"if(lt(t,{t1:.3f}),{seg},{expr})"
    return expr
