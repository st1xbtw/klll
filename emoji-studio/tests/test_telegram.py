"""Загрузка исходников через Bot API. Сеть не нужна: вызовы подменяются заглушками."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from emoji_studio import config  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="es_tg_"))
config.SOURCES_DIR = TMP / "sources"
config.SOURCES_DIR.mkdir(parents=True, exist_ok=True)

import test_core as tc  # noqa: E402  (тот же каталог tests)
from emoji_studio import sources, telegram_fetch  # noqa: E402

GOOD_TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


class FetchTests(unittest.TestCase):
    def test_token_format(self):
        self.assertTrue(telegram_fetch.valid_token(GOOD_TOKEN))
        self.assertFalse(telegram_fetch.valid_token("hello"))
        with self.assertRaises(ValueError):
            telegram_fetch.fetch_sources("bad", [tc.ID_WEBP])

    def test_fetch_stores_each_format_and_reports_missing(self):
        stickers = [
            {"custom_emoji_id": tc.ID_TGS, "is_animated": True, "file_id": "f1"},
            {"custom_emoji_id": tc.ID_WEBM, "is_video": True, "file_id": "f2"},
            {"custom_emoji_id": tc.ID_WEBP, "file_id": "f3"},
        ]
        payloads = {"f1": tc.make_tgs(), "f2": tc.make_webm(TMP), "f3": tc.make_webp()}
        files = {"f1": "a/1.tgs", "f2": "a/2.webm", "f3": "a/3.webp"}
        calls: list[str] = []

        def fake_call(token, method, payload=None, timeout=60):
            calls.append(method)
            if method == "getCustomEmojiStickers":
                self.assertLessEqual(len(payload["custom_emoji_ids"]), 200)
                return [s for s in stickers if s["custom_emoji_id"] in payload["custom_emoji_ids"]]
            if method == "getFile":
                return {"file_path": files[payload["file_id"]], "_fid": payload["file_id"]}
            raise AssertionError(method)

        def fake_download(token, file_path, timeout=60):
            fid = next(k for k, v in files.items() if v == file_path)
            return payloads[fid]

        ids = [tc.ID_TGS, tc.ID_WEBM, tc.ID_WEBP, tc.ID_EXTRA]
        res = telegram_fetch.fetch_sources(GOOD_TOKEN, ids, call=fake_call, download=fake_download)
        self.assertEqual(sorted(res["added"]), sorted([tc.ID_TGS, tc.ID_WEBM, tc.ID_WEBP]))
        self.assertEqual(res["missing"], [tc.ID_EXTRA])
        found = sources.scan()
        self.assertEqual(found[tc.ID_TGS]["fmt"], "animated")
        self.assertEqual(found[tc.ID_WEBM]["fmt"], "video")
        self.assertEqual(found[tc.ID_WEBP]["fmt"], "static")

    def test_network_error_marks_missing(self):
        def fake_call(token, method, payload=None, timeout=60):
            if method == "getCustomEmojiStickers":
                return [{"custom_emoji_id": tc.ID_EXTRA, "file_id": "x"}]
            return {"file_path": "p"}
        def bad_download(token, file_path, timeout=60):
            raise OSError("reset")
        res = telegram_fetch.fetch_sources(GOOD_TOKEN, [tc.ID_EXTRA], call=fake_call, download=bad_download)
        self.assertEqual(res, {"added": [], "missing": [tc.ID_EXTRA]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
