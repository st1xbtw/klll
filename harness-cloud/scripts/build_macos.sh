#!/usr/bin/env bash
# Сборка HarnessCloud.app. ffmpeg и ffprobe положите в bin/ (статические сборки для macOS).
set -euo pipefail
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --noconfirm harness-cloud.spec
echo "Готово: dist/HarnessCloud.app"
