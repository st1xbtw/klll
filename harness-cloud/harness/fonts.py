"""Шрифты для субтитров: встроенные (папка fonts/ рядом с приложением) и загруженные пользователем.

В ASS шрифт задаётся именем семейства (nameID 1 внутри файла), файл копируется в рабочую папку клипа
и подхватывается libass через fontsdir. Имя семейства проходит строгую проверку: в ASS оно попадает
в строку стиля, поэтому запятые, фигурные скобки и переводы строк запрещены.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import config

EXTS = {".ttf", ".otf"}
MAX_BYTES = 15 * 1024 * 1024
_SAFE_FAMILY = re.compile(r"^[\w .\-]{1,60}$", re.UNICODE)
_cache: dict = {"key": None, "items": []}


def _family(path: Path) -> str | None:
    try:
        from fontTools.ttLib import TTFont
        t = TTFont(str(path), lazy=True, fontNumber=0)
        name = t["name"].getDebugName(1)
        t.close()
    except Exception:
        return None
    return name if name and _SAFE_FAMILY.match(name) else None


def _dirs() -> list[Path]:
    return [config.FONTS_DIR, config.USER_FONTS_DIR]


def list_fonts() -> list[dict]:
    """[{family, file}] по семействам, без дублей (Regular/Bold одного семейства — одна запись)."""
    files = []
    for d in _dirs():
        if d.is_dir():
            files += [p for p in sorted(d.iterdir()) if p.suffix.lower() in EXTS]
    key = tuple((str(p), p.stat().st_mtime_ns) for p in files)
    if _cache["key"] != key:
        seen: dict[str, dict] = {}
        members: dict[str, list[Path]] = {}
        for p in files:
            fam = _family(p)
            if not fam:
                continue
            members.setdefault(fam, []).append(p)
            if fam not in seen:
                seen[fam] = {"family": fam, "file": p.name, "builtin": p.parent == config.FONTS_DIR}
        _cache["items"] = sorted(seen.values(), key=lambda x: (not x["builtin"], x["family"].lower()))
        _cache["members"] = members
        _cache["key"] = key
    return list(_cache["items"])


def _members(family: str) -> list[Path]:
    """Все файлы семейства (Regular и Bold): libass выбирает начертание по стилю."""
    list_fonts()
    return list(_cache.get("members", {}).get(family, []))


def resolve(family: str | None) -> Path | None:
    """Файл шрифта по имени семейства или None (тогда используется шрифт стиля)."""
    if not family or not _SAFE_FAMILY.match(family):
        return None
    for item in list_fonts():
        if item["family"] == family:
            for d in _dirs():
                p = d / item["file"]
                if p.exists():
                    return p
    return None


def add_user_font(src: Path, original_name: str) -> dict:
    """Проверяет и сохраняет пользовательский шрифт. Бросает ValueError при неверном файле."""
    ext = Path(original_name).suffix.lower()
    if ext not in EXTS:
        raise ValueError("Нужен файл .ttf или .otf")
    if src.stat().st_size > MAX_BYTES:
        raise ValueError("Файл шрифта больше 15 МБ")
    fam = _family(src)
    if not fam:
        raise ValueError("Не удалось прочитать шрифт или у него неподходящее имя семейства")
    config.USER_FONTS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]", "_", Path(original_name).name)[:80]
    dest = config.USER_FONTS_DIR / safe
    shutil.copyfile(src, dest)
    _cache["key"] = None  # сбросить кэш списка
    return {"family": fam, "file": dest.name}


def copy_for_clip(family: str | None, clip_dir: Path) -> str | None:
    """Копирует все файлы семейства в clip_dir/fonts и возвращает имя семейства для ASS (или None)."""
    if resolve(family) is None:
        return None
    dest = clip_dir / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    for p in _members(family):
        shutil.copyfile(p, dest / p.name)
    return family
