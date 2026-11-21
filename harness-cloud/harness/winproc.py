"""Запуск внешних программ (ffmpeg, ffprobe) без окна консоли.

В оконной сборке (PyInstaller, console=False) каждый дочерний консольный процесс на Windows
открывает собственное окно консоли. CREATE_NO_WINDOW этого не даёт.
"""
from __future__ import annotations

import subprocess
import sys


def hidden_kwargs() -> dict:
    """Аргументы для subprocess.Popen: на Windows скрывает окно, на других системах ничего не меняет."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
