"""Громкость и фейды звука в финальном клипе."""
import re
import subprocess
import threading

from harness import config, render


def _integrated_lufs(path) -> float:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                           "-af", "ebur128=peak=true", "-f", "null", "-"],
                          capture_output=True, text=True)
    found = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", proc.stderr)
    assert found, proc.stderr[-400:]
    return float(found[-1])


def test_audio_filter_targets_configured_loudness_and_fades():
    f = render.audio_filter(10.0)
    assert f"I={config.LOUDNESS_LUFS:g}" in f
    assert "afade=t=in:st=0:d=0.03" in f
    assert "afade=t=out:st=9.950:d=0.05" in f


def test_rendered_clip_is_normalised_to_target_loudness(tmp_path):
    src = tmp_path / "quiet.mp4"
    # Тихий тон (примерно -40 LUFS), чтобы нормализация была заметна.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=640x360:rate=30:duration=8", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=8", "-af", "volume=-30dB",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(src)], check=True)
    out = tmp_path / "clip.mp4"
    before = _integrated_lufs(src)
    render.render_clip(src, 1.0, 4.0, None, None, out, "tiktok", threading.Event(),
                       framing="center", src_w=640, src_h=360, out_w=360, out_h=640, fps=30)
    after = _integrated_lufs(out)
    assert before < -30
    assert abs(after - config.LOUDNESS_LUFS) <= 1.5
