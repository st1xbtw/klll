# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec для Harness Cloud.
# Сборка: pyinstaller --noconfirm harness-cloud.spec
# Windows → dist/HarnessCloud/HarnessCloud.exe ; macOS → dist/HarnessCloud.app
# ffmpeg/ffprobe кладутся в папку bin/ рядом со spec (см. scripts/).

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

datas = [("ui", "ui"), ("models", "models"), ("fonts", "fonts")]
binaries = []
hiddenimports = []

for pkg in ("faster_whisper", "ctranslate2", "yt_dlp", "webview", "tokenizers"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("uvicorn") + collect_submodules("starlette")
# pkg_resources (setuptools) тянет platformdirs в своём рантайм-хуке — собираем явно.
d, b, h = collect_all("platformdirs")
datas += d
hiddenimports += h + ["platformdirs"]

import os
if os.path.isdir("bin"):
    for f in os.listdir("bin"):
        binaries.append((os.path.join("bin", f), "bin"))

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HarnessCloud",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(SPECPATH, "ui", "assets", "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="HarnessCloud")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="HarnessCloud.app",
        bundle_identifier="cloud.harness.clips",
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "1.0.0"},
    )
