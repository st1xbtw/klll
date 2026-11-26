@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv || goto :err
  .venv\Scripts\python -m pip install -r requirements.txt || goto :err
)
.venv\Scripts\python app.py
goto :eof
:err
echo Не удалось установить зависимости. Проверьте, что установлен Python 3.11+ и добавлен в PATH.
pause
