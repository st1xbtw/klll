@echo off
REM Сборка HarnessCloud.exe. Перед запуском положите ffmpeg.exe и ffprobe.exe в папку bin\
setlocal
python -m pip install -r requirements.txt pyinstaller || goto :fail
python -m PyInstaller --noconfirm harness-cloud.spec || goto :fail
echo Готово: dist\HarnessCloud\HarnessCloud.exe
exit /b 0
:fail
echo Сборка не удалась
exit /b 1
