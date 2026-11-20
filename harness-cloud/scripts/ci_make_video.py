"""CI: тестовое видео 150 с для сквозной проверки собранного exe (без espeak, только ffmpeg + фото лица)."""
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
from skimage import data

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
face = out / "face.png"
big = cv2.resize(data.astronaut()[:, :, ::-1].copy(), (800, 800), interpolation=cv2.INTER_AREA)
cv2.imwrite(str(face), big)
ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
subprocess.run([
    ffmpeg, "-y", "-v", "error",
    "-f", "lavfi", "-i", "color=c=0x1d2446:size=1920x1080:rate=30",
    "-loop", "1", "-i", str(face),
    "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100",
    "-filter_complex", "[0:v][1:v]overlay=x='100+900*t/150':y=140:shortest=1[v]",
    "-map", "[v]", "-map", "2:a", "-t", "150",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "128k", str(out / "test.mp4"),
], check=True)
print("video:", out / "test.mp4")
