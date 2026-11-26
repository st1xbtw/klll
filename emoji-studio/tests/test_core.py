"""Проверки ядра и сервера. Запуск: python -m unittest discover -s tests -v (из папки проекта)."""
from __future__ import annotations

import gzip
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from emoji_studio import config  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="es_test_"))
config.SOURCES_DIR = TMP / "sources"
config.OUTPUT_DIR = TMP / "output"
config.TMP_DIR = TMP / "tmp"
for d in (config.SOURCES_DIR, config.OUTPUT_DIR, config.TMP_DIR):
    d.mkdir(parents=True, exist_ok=True)

from PIL import Image, ImageDraw  # noqa: E402
import app  # noqa: E402
from emoji_studio import generator, sources  # noqa: E402

ID_WEBP = "5343837741777990559"   # калиброванный (есть в NICK_BOXES)
ID_TGS = "5346093188018904738"
ID_WEBM = "5344013753832747766"
ID_EXTRA = "5447520167858830385"  # дополнительный, без калибровки


def make_webp() -> bytes:
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((10, 10, 90, 70), fill=(255, 200, 0, 255))
    d.rectangle((20, 75, 80, 90), fill=(60, 60, 60, 255))
    buf = io.BytesIO()
    img.save(buf, "WEBP", lossless=True)
    return buf.getvalue()


def make_tgs() -> bytes:
    """Минимальный Lottie: тело + слой ника (имя содержит старый ник)."""
    def rect(x, y, w, h, color):
        return {"ty": "gr", "it": [
            {"ty": "rc", "p": {"a": 0, "k": [x, y]}, "s": {"a": 0, "k": [w, h]}, "r": {"a": 0, "k": 0}},
            {"ty": "fl", "c": {"a": 0, "k": color}, "o": {"a": 0, "k": 100}},
            {"ty": "tr", "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]},
             "s": {"a": 0, "k": [100, 100]}, "r": {"a": 0, "k": 0}, "o": {"a": 0, "k": 100}},
        ]}
    doc = {
        "v": "5.7.4", "fr": 60, "ip": 0, "op": 120, "w": 512, "h": 512,
        "layers": [
            {"ty": 4, "ind": 1, "nm": "body", "ks": {}, "shapes": [rect(100, 100, 300, 250, [1, 0.8, 0, 1])]},
            {"ty": 4, "ind": 2, "nm": "st1xlox", "ks": {}, "shapes": [rect(120, 380, 260, 60, [0.2, 0.2, 0.2, 1])]},
        ],
    }
    return gzip.compress(json.dumps(doc).encode("utf-8"))


def make_webm(tmp: Path) -> bytes:
    out = tmp / "src.webm"
    subprocess.run([config.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=orange:s=100x100:d=1",
                    "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", str(out)], check=True)
    return out.read_bytes()


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.webm = make_webm(TMP)

    def test_zip_import_and_scan(self):
        data = make_zip({
            f"sub/{ID_WEBP}.webp": make_webp(),
            f"{ID_TGS}.tgs": make_tgs(),
            f"{ID_WEBM}.webm": self.webm,
            "readme.txt": b"hi",
            f"{ID_EXTRA}.tgs": b"not a tgs",
        })
        res = sources.import_bytes("sources.zip", data)
        self.assertEqual(sorted(res["added"]), sorted([ID_WEBP, ID_TGS, ID_WEBM]))
        self.assertTrue(any(ID_EXTRA in s for s in res["skipped"]))
        found = sources.scan()
        self.assertEqual(found[ID_TGS]["fmt"], "animated")
        self.assertEqual(found[ID_WEBM]["fmt"], "video")
        self.assertEqual(found[ID_WEBP]["fmt"], "static")

    def test_single_file_and_bad_name(self):
        res = sources.import_bytes(f"{ID_EXTRA}.webp", make_webp())
        self.assertEqual(res["added"], [ID_EXTRA])
        with self.assertRaises(ValueError):
            sources.import_bytes("photo.png", b"\x89PNG")

    def test_generate_all_formats(self):
        # тест самодостаточен: импортирует свои исходники (порядок тестов не важен)
        sources.import_bytes(f"{ID_WEBP}.webp", make_webp())
        sources.import_bytes(f"{ID_TGS}.tgs", make_tgs())
        sources.import_bytes(f"{ID_WEBM}.webm", self.webm)
        opts = generator.Options(nick="Lunar", color="#FF3B30", nick_color="original")
        res = generator.generate_sync([ID_WEBP, ID_TGS, ID_WEBM], opts)
        names = sorted(p.name for p in Path(res.out_dir).iterdir())
        self.assertIn("report.txt", names)
        self.assertIn(f"{ID_WEBP}.webp", res.ok)
        self.assertIn(f"{ID_TGS}.tgs", res.ok, res.failed)
        self.assertIn(f"{ID_WEBM}.webm", res.ok, res.failed)
        tgs = json.loads(gzip.decompress((Path(res.out_dir) / f"{ID_TGS}.tgs").read_bytes()))
        names_in = [l.get("nm") for l in tgs["layers"]]
        self.assertIn("nick", names_in)
        self.assertNotIn("st1xlox", names_in)
        self.assertLessEqual((Path(res.out_dir) / f"{ID_TGS}.tgs").stat().st_size, config.TGS_MAX_BYTES)
        self.assertLessEqual((Path(res.out_dir) / f"{ID_WEBM}.webm").stat().st_size, config.WEBM_MAX_BYTES)

    def test_validation(self):
        with self.assertRaises(ValueError):
            generator.validate(generator.Options(nick=""))
        with self.assertRaises(ValueError):
            generator.validate(generator.Options(nick="x" * 16))
        with self.assertRaises(ValueError):
            generator.validate(generator.Options(nick="ok", color="#ZZZZZZ"))


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def request(self, method, path, body=None, headers=None, host=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=60)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, data

    def test_state_and_guards(self):
        st, _ = self.request("GET", "/api/state")
        self.assertEqual(st, 200)
        st, _ = self.request("GET", "/api/state", host="evil.example")
        self.assertEqual(st, 403)  # DNS rebinding
        st, _ = self.request("POST", "/api/settings", body=b"{}", headers={"Content-Type": "application/json"})
        self.assertEqual(st, 403)  # нет заголовка защиты от CSRF

    def test_settings_and_generate_error(self):
        payload = json.dumps({"bot_username": "@my_emoji_bot"}).encode()
        st, data = self.request("POST", "/api/settings", body=payload,
                                headers={"X-Emoji-Studio": "1", "Content-Type": "application/json"})
        self.assertEqual(st, 200, data)
        self.assertEqual(json.loads(data)["bot_username"], "my_emoji_bot")
        bad = json.dumps({"nick": "a", "color": "original", "nick_color": "original", "ids": ["1"]}).encode()
        st, data = self.request("POST", "/api/generate", body=bad,
                                headers={"X-Emoji-Studio": "1", "Content-Type": "application/json"})
        self.assertEqual(st, 400)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
