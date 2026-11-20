"""Генерация тестового ролика: синтетическая русская речь (espeak-ng) + движущееся лицо.

Речь собирается пословно, поэтому мы точно знаем таймкоды каждого слова —
это эталонный транскрипт для проверки субтитров (Whisper в тесте не нужен).

Лицо: фото астронавта из scikit-image (public domain, NASA), которое плавно едет по кадру.
Фон: однотонный (без жёлтого — чтобы пиксельная проверка хука была однозначной).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 22050
FACE_SIZE = 800
FACE_OFFSET_X, FACE_OFFSET_Y = 352, 178        # центр лица внутри наложенного фото
FACE_Y = 140
TRACK_X0, TRACK_X1 = 100, 1000                 # левый край фото движется от 100 до 1000 px
VIDEO_LEN = 240.0

SENTENCES = [
    "Главный секрет успеха в дисциплине каждый день",
    "Никогда не сдавайтесь, если результат пока не виден",
    "Важно не количество времени, а качество внимания",
    "Оказывается, большинство людей бросает дело на третьей неделе",
    "Вот почему я советую вести простой дневник прогресса",
    "Деньги приходят к тем, кто системно учится новому",
    "Это реально работает, проверено на собственном опыте",
    "Ошибка многих в том, что они ждут мотивации",
    "Правда в том, что мотивация приходит после первого действия",
    "Лучший совет, который я получил, звучал очень просто",
    "Давайте разберём, как устроена привычка и почему она ломается",
    "Обычный вечер без телефона дал мне больше, чем любой курс",
    "Расскажите, какой шаг вы сделали на этой неделе",
    "Интересно, почему мы так часто откладываем важные задачи",
    "Для меня это был настоящий шок, когда я увидел цифры",
    "Спокойный ритм работы побеждает спринты и выгорание",
    "Записывайте три вещи, которые сделали сегодня хорошо",
    "Что вы думаете о внутренней дисциплине и её границах",
]


def _espeak_word(word: str, out: Path) -> float:
    subprocess.run(["espeak-ng", "-v", "ru", "-s", "155", "-w", str(out), word],
                   check=True, capture_output=True)
    with wave.open(str(out), "rb") as w:
        return w.getnframes() / w.getframerate()


def build_speech(out_wav: Path, transcript_json: Path, length: float = VIDEO_LEN) -> None:
    """Собирает речь пословно, пишет WAV (22050 Гц, моно) и эталонный транскрипт."""
    tmp = out_wav.parent / "_words"
    tmp.mkdir(parents=True, exist_ok=True)
    pcm: list[np.ndarray] = []
    t = 0.0
    segments = []
    widx = 0
    sidx = 0
    while t < length - 2.0:
        sent = SENTENCES[sidx % len(SENTENCES)]
        sidx += 1
        seg_start = t
        words = []
        for w in sent.split():
            wf = tmp / f"w{widx}.wav"
            widx += 1
            dur = _espeak_word(w, wf)
            with wave.open(str(wf), "rb") as r:
                raw = np.frombuffer(r.readframes(r.getnframes()), dtype=np.int16)
                rate = r.getframerate()
            if rate != SR:  # espeak отдаёт 22050 — на всякий случай
                raw = np.interp(np.linspace(0, len(raw), int(len(raw) * SR / rate)),
                                np.arange(len(raw)), raw).astype(np.int16)
            pcm.append(raw)
            words.append({"w": w.strip(".,!?"), "s": round(t, 3), "e": round(t + dur, 3)})
            t += dur
            gap = np.zeros(int(0.12 * SR), dtype=np.int16)
            pcm.append(gap)
            t += 0.12
        pcm.append(np.zeros(int(0.9 * SR), dtype=np.int16))
        t += 0.9
        segments.append({"start": round(seg_start, 3), "end": round(words[-1]["e"], 3),
                         "text": sent, "words": words})
    audio = np.concatenate(pcm)[: int(length * SR)]
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(audio.tobytes())
    transcript_json.write_text(json.dumps({"segments": [s for s in segments if s["end"] <= length]},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)


def face_png(out: Path) -> None:
    import cv2
    from skimage import data
    im = data.astronaut()[:, :, ::-1].copy()
    big = cv2.resize(im, (FACE_SIZE, FACE_SIZE), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(out), big)


def build_video(out_mp4: Path, speech_wav: Path, face: Path, length: float = VIDEO_LEN) -> None:
    """1920×1080, 30 fps, лицо плавно движется слева направо, речь — AAC."""
    x_expr = f"{TRACK_X0}+({TRACK_X1 - TRACK_X0})*t/{length:.1f}"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=0x1d2446:size=1920x1080:rate=30",
        "-loop", "1", "-i", str(face),
        "-i", str(speech_wav),
        "-filter_complex", f"[0:v][1:v]overlay=x='{x_expr}':y={FACE_Y}:shortest=1[v]",
        "-map", "[v]", "-map", "2:a",
        "-t", f"{length:.1f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(out_mp4),
    ]
    subprocess.run(cmd, check=True)


def generate(outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    wav = outdir / "speech.wav"
    tr = outdir / "transcript.json"
    face = outdir / "face.png"
    video = outdir / "test_talk.mp4"
    build_speech(wav, tr)
    face_png(face)
    build_video(video, wav, face)
    return {"video": video, "transcript": tr, "face": face, "wav": wav}


if __name__ == "__main__":
    import sys
    paths = generate(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/assets"))
    print({k: str(v) for k, v in paths.items()})
