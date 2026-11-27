"""Генерация эмодзи: перекраска и новый ник. Логика совпадает с services/pack_builder._render бота."""
from __future__ import annotations

import asyncio
import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import datetime

from . import config
from .common import font_supports, parse_hex
from .sources import scan
from .tgs_recolor import recolor_tgs
from .webm_recolor import recolor_webm
from .webp_recolor import recolor_webp

ORIGINAL = "original"


@dataclass
class Options:
    nick: str
    color: str | None = None          # None — оригинальный цвет тела; "#RRGGBB" или "#AAAAAA|#BBBBBB"
    nick_color: str = ORIGINAL        # "original" или "#RRGGBB"


@dataclass
class GenResult:
    out_dir: str
    ok: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)


def validate(opts: Options) -> None:
    nick = opts.nick.strip()
    if not nick:
        raise ValueError("Введите ник")
    if len(nick) > config.NICK_MAX_LEN:
        raise ValueError(f"Ник длиннее {config.NICK_MAX_LEN} символов")
    if not font_supports(nick):
        raise ValueError("В шрифте fonts/ нет некоторых символов ника")
    if opts.color is not None:
        for part in opts.color.split("|"):
            parse_hex(part)
    if opts.nick_color != ORIGINAL:
        parse_hex(opts.nick_color)


def _plain_color(spec: str | None) -> str:
    """Для WEBM/WEBP: один цвет (для градиента — светлый)."""
    if not spec:
        return "#FFFFFF"
    return spec.split("|")[-1]


def _nick_plain(nick_color: str | None, color: str | None) -> str:
    if nick_color is None:
        return _plain_color(color)
    if nick_color == ORIGINAL:
        return "#FFFFFF"
    return nick_color


async def _render_one(eid: str, fmt: str, src, opts: Options, workdir) -> tuple[str, str]:
    """Возвращает (путь к результату, предупреждение или '').

    На эмодзи с надписью LOVEX она заменяется на config.LOVEX_REPLACEMENT (st1xlox),
    ник пользователя на них не ставится. Остальные эмодзи — как раньше.
    """
    nick = config.LOVEX_REPLACEMENT if eid in config.LOVEX_IDS else opts.nick.strip()
    if fmt == "animated":
        out = workdir / f"{eid}.tgs"
        removed = await asyncio.to_thread(
            recolor_tgs, src, out, nick, opts.color, opts.nick_color)
        warn = "" if removed or eid in config.CALIBRATED_IDS or eid in config.LOVEX_IDS else "старый ник не найден, ник добавлен по зоне по умолчанию"
        return str(out), warn
    if fmt == "video":
        out = workdir / f"{eid}.webm"
        await recolor_webm(src, out, nick, _nick_plain(opts.nick_color, opts.color))
        return str(out), ""
    out = workdir / f"{eid}.webp"
    await asyncio.to_thread(recolor_webp, src, out, nick, _nick_plain(opts.nick_color, opts.color))
    return str(out), ""


async def generate(ids: list[str], opts: Options, concurrency: int = 3) -> GenResult:
    validate(opts)
    available = scan()
    safe_nick = re.sub(r"[^\w-]+", "_", opts.nick.strip())[:20] or "nick"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = config.OUTPUT_DIR / f"{stamp}_{safe_nick}"
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = config.TMP_DIR / secrets.token_hex(6)
    workdir.mkdir(parents=True, exist_ok=True)
    result = GenResult(out_dir=str(out_dir))
    sem = asyncio.Semaphore(max(1, concurrency))

    async def worker(eid: str) -> None:
        info = available.get(eid)
        if info is None:
            result.failed.append({"id": eid, "error": "исходник не импортирован"})
            return
        async with sem:
            try:
                path, warn = await _render_one(eid, info["fmt"], info["path"], opts, workdir)
                dst = out_dir / os.path.basename(path)
                shutil.move(path, dst)
                result.ok.append(dst.name)
                if warn:
                    result.failed.append({"id": eid, "error": "сохранено, но: " + warn})
            except Exception as e:  # noqa: BLE001 — одна ошибка не должна ронять весь пакет
                result.failed.append({"id": eid, "error": str(e)[-300:] or type(e).__name__})

    try:
        await asyncio.gather(*(worker(e) for e in ids))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    result.ok.sort()
    lines = [
        f"Ник: {opts.nick.strip()}",
        f"Цвет тела: {opts.color or 'как в оригинале'}",
        f"Цвет ника: {opts.nick_color}",
        f"Готово: {len(result.ok)}",
        "",
    ]
    lines += [f"ОК   {n}" for n in result.ok]
    lines += [f"ОШИБКА/ПРЕДУПРЕЖДЕНИЕ {f['id']}: {f['error']}" for f in result.failed]
    (out_dir / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    return result


def generate_sync(ids: list[str], opts: Options) -> GenResult:
    return asyncio.run(generate(ids, opts, concurrency=config.GEN_CONCURRENCY))
