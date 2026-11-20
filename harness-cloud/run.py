"""Точка входа Harness Cloud.

  python run.py              — окно pywebview (fallback: браузер по адресу сервера)
  python run.py --browser    — открыть в браузере без окна pywebview
  python run.py --server     — только сервер (для тестов и отладки), порт по умолчанию 8765
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from harness import config
from harness.server import create_app


def free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 50)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # SO_REUSEADDR — как у uvicorn: порт в TIME_WAIT после перезапуска считается свободным.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Не найден свободный порт")


def serve(port: int) -> uvicorn.Server:
    app = create_app()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, name="harness-http", daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server


def _ensure_std_streams() -> None:
    """В оконной сборке PyInstaller (console=False) sys.stdout/sys.stderr равны None.
    Тогда любой print или лог uvicorn роняет процесс. Пишем вывод в harness.log в папке данных."""
    if sys.stdout is None or sys.stderr is None:
        log = open(config.DATA_DIR / "harness.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log


def main(argv: list[str] | None = None) -> int:
    _ensure_std_streams()
    ap = argparse.ArgumentParser(description=config.APP_NAME)
    ap.add_argument("--browser", action="store_true", help="открыть в браузере")
    ap.add_argument("--server", action="store_true", help="только сервер")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)

    port = free_port(args.port)
    server = serve(port)
    url = f"http://127.0.0.1:{port}/"
    print(f"{config.APP_NAME} {config.APP_VERSION}: {url}  (данные: {config.DATA_DIR})", flush=True)

    if args.server:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        server.should_exit = True
        return 0

    if not args.browser:
        try:
            import webview  # pywebview: окно на нативном WebView
            webview.create_window(config.APP_NAME, url, width=1280, height=820, min_size=(960, 640))
            webview.start()
            server.should_exit = True
            return 0
        except Exception as exc:  # нет GUI / нет WebView — не падаем
            print(f"Окно недоступно ({exc}); открываю браузер.", file=sys.stderr)

    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    server.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
