#!/usr/bin/env python3
"""Emoji Studio — создание эмодзи с новым ником на ПК.

Запуск: python app.py  (откроется браузер на http://127.0.0.1:<порт>).
Сервер слушает только 127.0.0.1 и принимает запросы с Host localhost/127.0.0.1.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from emoji_studio import config, generator, sources, telegram_fetch  # noqa: E402

WEB_INDEX = config.BUNDLE_DIR / "web" / "index.html"
ASSETS_DIR = config.BUNDLE_DIR / "web" / "assets"
ASSET_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".js": "application/javascript"}
MAX_UPLOAD = 200 * 1024 * 1024
MAX_JSON = 1024 * 1024
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
HOSTS_OK = {"127.0.0.1", "localhost"}
PORTS = range(8765, 8785)


def load_settings() -> dict:
    try:
        return json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    config.SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def state() -> dict:
    found = sources.scan()
    settings = load_settings()
    return {
        "sources": [
            {
                "id": eid,
                "group": "main" if eid in config.SOURCE_IDS else "extra",
                "ready": eid in found,
                "fmt": found[eid]["fmt"] if eid in found else None,
                "calibrated": eid in config.CALIBRATED_IDS,
            }
            for eid in config.ALL_IDS
        ],
        "ready_count": sum(1 for e in config.ALL_IDS if e in found),
        "total": len(config.ALL_IDS),
        "ids_text": "\n".join(config.ALL_IDS),
        "palette": [{"key": k, "label": label, "hex": hx} for k, label, hx in config.PALETTE],
        "nick_max": config.NICK_MAX_LEN,
        "bot_username": settings.get("bot_username", ""),
        "has_token": bool(settings.get("bot_token")),
        "ffmpeg": shutil.which(config.FFMPEG) is not None,
        "output_dir": str(config.OUTPUT_DIR),
        "version": config.APP_VERSION,
    }


def open_folder(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Handler(BaseHTTPRequestHandler):
    server_version = "EmojiStudio"

    def log_message(self, fmt, *args):  # тихий сервер
        pass

    # ── общие проверки ──
    def _host_ok(self) -> bool:
        return self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]") in HOSTS_OK

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, f: Path, ctype: str) -> None:
        body = f.read_bytes()
        self.send_response(200)
        if f.suffix.lower() == ".tgs":
            ctype = "application/json"
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    CTYPES = {".webp": "image/webp", ".webm": "video/webm", ".tgs": "application/json"}

    def _body(self, limit: int) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > limit:
            raise ValueError("Слишком большой или пустой запрос")
        return self.rfile.read(length)

    def _post_ok(self) -> bool:
        # кастомный заголовок: кросс-доменные страницы не смогут отправить POST без preflight
        return self.headers.get("X-Emoji-Studio") == "1"

    # ── GET ──
    def do_GET(self):
        if not self._host_ok():
            self._json(403, {"error": "forbidden"})
            return
        path = urlparse(self.path).path
        if path == "/":
            body = WEB_INDEX.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            self._json(200, state())
        elif path.startswith("/assets/"):
            name = Path(path[len("/assets/"):]).name
            f = ASSETS_DIR / name
            ctype = ASSET_TYPES.get(f.suffix.lower())
            if name != path[len("/assets/"):] or not f.is_file() or ctype is None:
                self._json(404, {"error": "not found"})
                return
            self._send_file(f, ctype)
        elif path == "/api/preview":
            q = parse_qs(urlparse(self.path).query)
            d = Path(q.get("dir", [""])[0]).name
            fn = Path(q.get("file", [""])[0]).name
            f = config.OUTPUT_DIR / d / fn
            if not (d and fn and f.suffix.lower() in self.CTYPES and f.is_file()):
                self._json(404, {"error": "not found"})
                return
            self._send_file(f, self.CTYPES[f.suffix.lower()])
        elif path == "/api/source":
            q = parse_qs(urlparse(self.path).query)
            eid = q.get("id", [""])[0]
            info = sources.scan().get(eid) if re.fullmatch(r"\d{15,20}", eid) else None
            if info is None:
                self._json(404, {"error": "not found"})
                return
            self._send_file(info["path"], self.CTYPES[info["path"].suffix.lower()])
        else:
            self._json(404, {"error": "not found"})

    # ── POST ──
    def do_POST(self):
        if not self._host_ok() or not self._post_ok():
            self._json(403, {"error": "forbidden"})
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/import":
                name = unquote(self.headers.get("X-Filename", "upload"))
                data = self._body(MAX_UPLOAD)
                self._json(200, sources.import_bytes(name, data))
            elif path == "/api/generate":
                req = json.loads(self._body(MAX_JSON))
                self._generate(req)
            elif path == "/api/settings":
                req = json.loads(self._body(MAX_JSON))
                username = str(req.get("bot_username", "")).strip().lstrip("@")
                if username and not USERNAME_RE.match(username):
                    raise ValueError("Некорректное имя бота")
                settings = load_settings()
                settings["bot_username"] = username
                if "bot_token" in req:
                    token = str(req.get("bot_token") or "").strip()
                    if token and not telegram_fetch.valid_token(token):
                        raise ValueError("Некорректный токен бота (формат 123456:ABC…)")
                    if token:
                        settings["bot_token"] = token
                    else:
                        settings.pop("bot_token", None)
                save_settings(settings)
                self._json(200, {"bot_username": username, "has_token": bool(settings.get("bot_token"))})
            elif path == "/api/fetch-sources":
                settings = load_settings()
                token = settings.get("bot_token", "")
                if not token:
                    raise ValueError("Сначала укажите токен бота и нажмите «Сохранить»")
                req = json.loads(self._body(MAX_JSON) or b"{}")
                wanted = [str(i) for i in req.get("ids", [])] or config.ALL_IDS
                if not all(re.fullmatch(r"\d{15,20}", i) for i in wanted):
                    raise ValueError("Некорректный список эмодзи")
                have = set(sources.scan())
                todo = [i for i in wanted if i not in have]
                result = telegram_fetch.fetch_sources(token, todo) if todo else {"added": [], "missing": []}
                self._json(200, result)
            elif path == "/api/open-output":
                req = json.loads(self._body(MAX_JSON) or b"{}")
                name = Path(str(req.get("dir", ""))).name
                target = config.OUTPUT_DIR / name if name else config.OUTPUT_DIR
                if not target.is_dir() or target.parent != config.OUTPUT_DIR:
                    raise ValueError("Папка результата не найдена")
                open_folder(target)
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            self._json(400, {"error": str(e)})
        except FileNotFoundError as e:
            self._json(400, {"error": f"Шрифт не найден: {e}"})
        except telegram_fetch.TelegramError as e:
            self._json(502, {"error": str(e)})

    def _generate(self, req: dict) -> None:
        nick = str(req.get("nick", "")).strip()
        body_spec = str(req.get("color", "original"))
        nick_spec = str(req.get("nick_color", "original"))
        ids = [str(i) for i in req.get("ids", [])]
        if not ids:
            raise ValueError("Выберите хотя бы одно эмодзи")
        if len(ids) > 200 or not all(re.fullmatch(r"\d{15,20}", i) for i in ids):
            raise ValueError("Некорректный список эмодзи")
        opts = generator.Options(
            nick=nick,
            color=None if body_spec == generator.ORIGINAL else body_spec,
            nick_color=nick_spec,
        )
        available = sources.scan()
        missing = [i for i in ids if i not in available]
        if missing:
            raise ValueError(f"Не импортированы исходники: {len(missing)} шт. Сначала импортируйте архив от бота.")
        result = generator.generate_sync(ids, opts)
        self._json(200, {
            "out_dir": result.out_dir,
            "out_dir_name": Path(result.out_dir).name,
            "ok": result.ok,
            "failed": result.failed,
        })


def pick_server() -> ThreadingHTTPServer:
    for port in PORTS:
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            continue
    raise SystemExit("Не удалось занять порты 8765–8784: закройте другие копии приложения.")


def main() -> None:
    server = pick_server()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        import webview  # pywebview: отдельное окно приложения (WebView2 на Windows)
    except Exception:  # noqa: BLE001 — нет webview: откроем в браузере
        webview = None
    if webview is None:
        print(f"Emoji Studio запущен: {url}\nДля выхода нажмите Ctrl+C.")
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        webview.create_window("Emoji Studio", url, width=1280, height=820, min_size=(980, 640),
                              background_color="#0b0a12")
        webview.start()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
