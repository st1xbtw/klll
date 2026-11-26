"""Импорт исходных эмодзи: zip-архив от бота (/getids) или отдельные файлы <id>.tgs / .webp / .webm."""
from __future__ import annotations

import gzip
import json
import posixpath
import re
import zipfile
from io import BytesIO

from . import config

ID_RE = re.compile(r"^(\d{15,20})\.(tgs|webp|webm)$", re.IGNORECASE)
FMT_BY_EXT = {"tgs": "animated", "webm": "video", "webp": "static"}
MAX_FILE_BYTES = 5 * 1024 * 1024       # один исходник Telegram весит десятки КБ
MAX_ARCHIVE_ENTRIES = 500


def _is_valid(ext: str, data: bytes) -> bool:
    if ext == "tgs":
        try:
            json.loads(gzip.decompress(data))
            return True
        except (OSError, ValueError):
            try:  # на всякий случай: несжатый Lottie-JSON тоже принимаем
                json.loads(data)
                return True
            except ValueError:
                return False
    if ext == "webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if ext == "webm":
        return data[:4] == b"\x1a\x45\xdf\xa3"  # EBML-заголовок Matroska/WebM
    return False


def _store(eid: str, ext: str, data: bytes) -> None:
    for old in config.SOURCES_DIR.glob(f"{eid}.*"):
        old.unlink()
    (config.SOURCES_DIR / f"{eid}.{ext}").write_bytes(data)


def import_bytes(filename: str, data: bytes) -> dict:
    """Сохраняет исходники. Возвращает {'added': [...], 'skipped': [...]}."""
    added: list[str] = []
    skipped: list[str] = []
    name = posixpath.basename(filename.replace("\\", "/"))

    if data[:4] == b"PK\x03\x04" or name.lower().endswith(".zip"):
        with zipfile.ZipFile(BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise ValueError("В архиве слишком много файлов")
            for info in infos:
                if info.is_dir():
                    continue
                base = posixpath.basename(info.filename)  # путь внутри архива не используем
                m = ID_RE.match(base)
                if not m:
                    continue
                if info.file_size > MAX_FILE_BYTES:
                    skipped.append(f"{base}: слишком большой файл")
                    continue
                payload = zf.read(info)
                ext = m.group(2).lower()
                if not _is_valid(ext, payload):
                    skipped.append(f"{base}: повреждённый файл")
                    continue
                _store(m.group(1), ext, payload)
                added.append(m.group(1))
        if not added and not skipped:
            raise ValueError("В архиве нет файлов вида <ID>.tgs / .webp / .webm")
        return {"added": sorted(set(added)), "skipped": skipped}

    m = ID_RE.match(name)
    if not m:
        raise ValueError("Ожидается zip-архив от бота или файл <ID>.tgs / .webp / .webm")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Файл слишком большой")
    ext = m.group(2).lower()
    if not _is_valid(ext, data):
        raise ValueError("Файл повреждён или не похож на эмодзи")
    _store(m.group(1), ext, data)
    return {"added": [m.group(1)], "skipped": []}


def scan() -> dict[str, dict]:
    """Все импортированные исходники: {id: {'fmt': ..., 'file': ...}}."""
    found: dict[str, dict] = {}
    for p in config.SOURCES_DIR.iterdir():
        m = ID_RE.match(p.name)
        if m:
            ext = m.group(2).lower()
            found[m.group(1)] = {"fmt": FMT_BY_EXT[ext], "file": p.name, "path": p}
    return found


def source_path(eid: str) -> tuple[str, object]:
    info = scan().get(eid)
    if info is None:
        raise FileNotFoundError(eid)
    return info["fmt"], info["path"]
