"""Перекраска TGS (Lottie) и замена ника.

Telegram не рендерит текстовые слои Lottie, поэтому новый ник строится из
векторных контуров глифов шрифта (fontTools) и добавляется как shape-слой.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
from pathlib import Path
from typing import Any

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

from . import config
from .common import Tint, find_font, make_tint, parse_hex, shade

log = logging.getLogger(__name__)

NICK_NAME_RE = re.compile(r"(nick|nik|username|ник|text|txt|" + re.escape(config.OLD_NICK) + r")", re.I)


class TgsError(Exception):
    pass


# ───────────────────────── перекраска ─────────────────────────

def _recolor_vec(vec: Any, tint: Tint) -> Any:
    if not isinstance(vec, list) or len(vec) < 3:
        return vec
    if not all(isinstance(x, (int, float)) for x in vec[:3]):
        return vec
    scale = 255.0 if max(vec[:3]) > 1.0 else 1.0
    lum = (0.299 * vec[0] + 0.587 * vec[1] + 0.114 * vec[2]) / scale
    r, g, b = shade(tint, lum)
    return [r / 255 * scale, g / 255 * scale, b / 255 * scale, *vec[3:]]


def _recolor_prop(prop: Any, tint: Tint) -> None:
    if not isinstance(prop, dict):
        return
    k = prop.get("k")
    if isinstance(k, list) and k and isinstance(k[0], dict):
        for kf in k:
            for key in ("s", "e"):
                if key in kf:
                    kf[key] = _recolor_vec(kf[key], tint)
    else:
        prop["k"] = _recolor_vec(k, tint)


def _recolor_gradient(g: dict, tint: Tint) -> None:
    n = int(g.get("p", 0) or 0)
    prop = g.get("k")
    if not isinstance(prop, dict):
        return

    def fix(arr: list) -> None:
        for i in range(n):
            j = i * 4
            if j + 3 < len(arr):
                arr[j + 1:j + 4] = _recolor_vec(arr[j + 1:j + 4], tint)[:3]

    k = prop.get("k")
    if isinstance(k, list) and k and isinstance(k[0], dict):
        for kf in k:
            for key in ("s", "e"):
                if isinstance(kf.get(key), list):
                    fix(kf[key])
    elif isinstance(k, list):
        fix(k)


def _walk_recolor(node: Any, tint: Tint) -> None:
    if isinstance(node, dict):
        ty = node.get("ty")
        if ty in ("fl", "st") and isinstance(node.get("c"), dict):
            _recolor_prop(node["c"], tint)
        elif ty in ("gf", "gs") and isinstance(node.get("g"), dict):
            _recolor_gradient(node["g"], tint)
        elif ty == 1 and isinstance(node.get("sc"), str):
            m = re.fullmatch(r"#([0-9a-fA-F]{6})", node["sc"])
            if m:
                h = m.group(1)
                r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
                lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
                nr, ng, nb = shade(tint, lum)
                node["sc"] = "#%02x%02x%02x" % (round(nr), round(ng), round(nb))
        for v in node.values():
            _walk_recolor(v, tint)
    elif isinstance(node, list):
        for v in node:
            _walk_recolor(v, tint)


# ───────────────────── поиск и удаление старого ника ─────────────────────

def _static(prop: Any, default: Any) -> Any:
    if not isinstance(prop, dict):
        return default
    k = prop.get("k")
    if isinstance(k, list) and k and isinstance(k[0], dict):
        s = k[0].get("s")
        return s if s is not None else default
    return k if k is not None else default


def _affine_from(tr: dict | None) -> tuple[float, float, float, float]:
    if not isinstance(tr, dict):
        return 1.0, 1.0, 0.0, 0.0
    p = _static(tr.get("p"), [0, 0])
    a = _static(tr.get("a"), [0, 0])
    s = _static(tr.get("s"), [100, 100])

    def ok(v: Any) -> bool:
        return isinstance(v, list) and len(v) >= 2 and all(isinstance(x, (int, float)) for x in v[:2])

    p = p if ok(p) else [0, 0]
    a = a if ok(a) else [0, 0]
    s = s if ok(s) else [100, 100]
    sx, sy = s[0] / 100.0, s[1] / 100.0
    return sx, sy, p[0] - a[0] * sx, p[1] - a[1] * sy


def _compose(outer: tuple, inner: tuple) -> tuple[float, float, float, float]:
    osx, osy, otx, oty = outer
    isx, isy, itx, ity = inner
    return isx * osx, isy * osy, itx * osx + otx, ity * osy + oty


def _collect(items: list, aff: tuple, pts: list) -> None:
    for it in items:
        if not isinstance(it, dict):
            continue
        ty = it.get("ty")
        if ty == "gr":
            sub = it.get("it", [])
            tr = next((x for x in sub if isinstance(x, dict) and x.get("ty") == "tr"), None)
            _collect(sub, _compose(aff, _affine_from(tr)) if tr else aff, pts)
        elif ty == "sh":
            k = (it.get("ks") or {}).get("k")
            if isinstance(k, list) and k and isinstance(k[0], dict):
                s = k[0].get("s") or [None]
                k = s[0]
            if isinstance(k, dict):
                for v in k.get("v", []):
                    pts.append((v[0] * aff[0] + aff[2], v[1] * aff[1] + aff[3]))


def _bbox(pts: list) -> tuple[float, float, float, float] | None:
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _center_in(bb: tuple, region: tuple) -> bool:
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def _layer_affine(layer: dict, by_ind: dict, depth: int = 0) -> tuple[float, float, float, float]:
    """Полная матрица слоя с учётом цепочки родителей (поле `parent`).

    В исходниках Telegram большинство слоёв привязаны к родителям. Без учёта
    родителя координаты контуров неверны, и ник ищется/удаляется не там, где он на самом деле.
    """
    local = _affine_from(layer.get("ks"))
    par = layer.get("parent")
    parent = by_ind.get(par) if par is not None and depth < 32 else None
    if parent is None or parent is layer:
        return local
    return _compose(_layer_affine(parent, by_ind, depth + 1), local)


TEXT_GROUP_NAMES = {"#TEXT", "#TEXT_wrapper"}


SLOT_NAME = "__NICK_SLOT__"


IDENT = (1.0, 1.0, 0.0, 0.0)


def _drop_named_groups(items: list, pts: list, aff) -> tuple[list, int]:
    """Рекурсивно удаляет группы с именем текста ника. Их контуры попадают в pts (для bbox).

    На месте первой удалённой группы оставляется метка SLOT_NAME. В ней запоминаются:
    _local — рамка старого текста в координатах его группы, _tr — трансформ этой группы.
    Новый ник рисуется в тех же координатах и с тем же трансформом, поэтому анимация
    совпадает с оригинальным текстом.
    """
    kept: list = []
    removed = 0
    for it in items:
        if isinstance(it, dict) and it.get("ty") == "gr":
            if it.get("nm") in TEXT_GROUP_NAMES:
                if aff is not None:
                    _collect([it], aff, pts)
                    if not any(isinstance(k, dict) and k.get("nm") == SLOT_NAME for k in kept):
                        kept.append(_make_slot(it.get("it", []), it))
                removed += 1
                continue
            tr = next((x for x in it.get("it", []) if isinstance(x, dict) and x.get("ty") == "tr"), None)
            child_aff = _compose(aff, _affine_from(tr)) if (aff is not None and tr) else aff
            sub, k = _drop_named_groups(it.get("it", []), pts, child_aff)
            it["it"] = sub
            removed += k
        kept.append(it)
    return kept, removed


def _make_slot(children: list, group: dict | None) -> dict:
    pts: list = []
    _collect(children, IDENT, pts)
    local: list = []
    if pts:
        xs = [x for x, _ in pts]
        ys = [y for _, y in pts]
        local = [min(xs), min(ys), max(xs), max(ys)]
    tr = None
    if group is not None:
        tr = next((x for x in group.get("it", []) if isinstance(x, dict) and x.get("ty") == "tr"), None)
    return {"ty": "gr", "nm": SLOT_NAME, "it": [], "_local": local,
            "_tr": json.loads(json.dumps(tr)) if tr else None}


def _find_slot(node: Any):
    """Ищет метку под новый ник: (список, индекс, матрица контейнера) или None."""
    if isinstance(node, dict):
        if node.get("ty") == "gr":
            for i, it in enumerate(node.get("it", [])):
                if isinstance(it, dict) and it.get("nm") == SLOT_NAME:
                    return node["it"], i, it
            for sub in node.get("it", []):
                found = _find_slot(sub)
                if found:
                    return found
        for v in node.values():
            if isinstance(v, (dict, list)):
                found = _find_slot(v)
                if found:
                    return found
    elif isinstance(node, list):
        for i, it in enumerate(node):
            if isinstance(it, dict) and it.get("nm") == SLOT_NAME:
                return node, i, it
        for v in node:
            found = _find_slot(v)
            if found:
                return found
    return None


def _purge_slots(node: Any) -> None:
    """Убирает оставшиеся метки SLOT_NAME (если текст нашёлся в нескольких местах)."""
    if isinstance(node, list):
        node[:] = [x for x in node if not (isinstance(x, dict) and x.get("nm") == SLOT_NAME)]
        for x in node:
            _purge_slots(x)
    elif isinstance(node, dict):
        for v in node.values():
            _purge_slots(v)


def _place_nick(data: dict, nick: str, tint: Tint, bbox) -> bool:
    """Ставит ник на место старого текста внутри его слоя/группы.

    Глифы рисуются в координатах группы старого текста, а её трансформ копируется,
    поэтому ник двигается точно так же, как оригинальный текст (вращение, масштаб, путь).
    """
    w = float(data.get("w", 512))
    h = float(data.get("h", 512))
    found = None
    for L in data.get("layers", []):
        found = _find_slot(L)
        if found:
            break
    if not found:
        for a in data.get("assets", []):
            if isinstance(a, dict) and "layers" in a:
                found = _find_slot(a["layers"])
                if found:
                    break
    if not found:
        return False
    lst, idx, ph = found
    local = ph.get("_local") or []
    if len(local) < 4 or local[2] - local[0] < 1 or local[3] - local[1] < 1:
        lst[idx] = {"ty": "gr", "nm": "nick_slot", "it": []}
        return False

    # область — рамка оригинального текста в его координатах (с небольшим отступом)
    x0, y0, x1, y1 = local[:4]
    padx = (x1 - x0) * 0.03
    padv = (y1 - y0) * 0.1
    region = (x0 - padx, y0 - padv, x1 + padx, y1 + padv)
    items = _nick_shape_items(nick, region)
    r, g, b = (c / 255 for c in tint.text)
    tr = ph.get("_tr") or {"ty": "tr", "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]},
                           "s": {"a": 0, "k": [100, 100]}, "r": {"a": 0, "k": 0},
                           "o": {"a": 0, "k": 100}, "sk": {"a": 0, "k": 0}, "sa": {"a": 0, "k": 0}}
    lst[idx] = {"ty": "gr", "nm": "nick_slot", "it": items + [
        {"ty": "fl", "c": {"a": 0, "k": [r, g, b, 1]}, "o": {"a": 0, "k": 100},
         "r": 1, "bm": 0, "nm": "Fill"},
        tr,
    ]}
    return True


def _strip_nick(data: dict, search_region: tuple) -> tuple[tuple[float, float, float, float] | None, int]:
    """Удаляет старый ник.

    Возвращает (bbox удалённого ника или None, сколько элементов удалено).
    Удаляются только текстовые слои, слои с именем ника и группы-строки букв
    в узкой зоне NICK_SEARCH_REGION. Целые слои по области не удаляются: в них бывают детали тела эмодзи.
    """
    w = float(data.get("w", 512))
    h = float(data.get("h", 512))
    sx0, sy0, sx1, sy1 = search_region
    search = (sx0 * w, sy0 * h, sx1 * w, sy1 * h)
    max_text_h = 0.2 * h

    layers = data.get("layers", [])
    by_ind = {int(l["ind"]): l for l in layers if isinstance(l, dict) and "ind" in l}

    pts: list = []
    removed = 0
    keep: list = []

    # 1) текстовые слои и слои с «говорящим» именем
    for layer in layers:
        ty = layer.get("ty")
        if ty == 5:
            removed += 1
            continue
        if ty == 4 and NICK_NAME_RE.search(str(layer.get("nm", ""))):
            aff = _layer_affine(layer, by_ind)
            _collect(layer.get("shapes", []), aff, pts)
            removed += 1
            # слой остаётся на своём месте (с его трансформом), содержимое заменяем меткой под ник
            layer["nm"] = "nick_slot"
            layer["shapes"] = [_make_slot(layer.get("shapes", []), None)]
            keep.append(layer)
            continue
        keep.append(layer)

    # 1b) группы с именем текста ника (#TEXT, #TEXT_wrapper) — где угодно: в слоях,
    # в предкомпозициях (assets), в том числе вложенных друг в друга
    assets = {a["id"]: a for a in data.get("assets", []) if isinstance(a, dict) and "id" in a and "layers" in a}
    named = 0

    def sweep(layer_list: list, base: tuple | None, depth: int) -> None:
        nonlocal named
        if depth > 8:
            return
        lby = {int(l["ind"]): l for l in layer_list if isinstance(l, dict) and "ind" in l}
        for L in layer_list:
            if not isinstance(L, dict):
                continue
            own = _layer_affine(L, lby)
            aff = _compose(base, own) if base is not None else None
            if L.get("ty") == 4:
                L["shapes"], k = _drop_named_groups(L.get("shapes", []), pts, aff)
                named += k
            elif L.get("ty") == 0 and L.get("refId") in assets:
                sweep(assets[L["refId"]]["layers"], aff, depth + 1)

    sweep(keep, (1.0, 1.0, 0.0, 0.0), 0)
    # ассеты, на которые нет ссылок из слоёв верхнего уровня: тоже чистим по имени
    for a in assets.values():
        for L in a["layers"]:
            if isinstance(L, dict) and L.get("ty") == 4:
                L["shapes"], k = _drop_named_groups(L.get("shapes", []), [], None)
                named += k
    removed += named

    # 2) геометрия (буквы ника по координатам) — только если именованного текста не нашлось
    for layer in (keep if named == 0 else []):
        if layer.get("ty") != 4:
            continue
        aff = _layer_affine(layer, by_ind)
        shapes = []
        for item in layer.get("shapes", []):
            if isinstance(item, dict) and item.get("ty") == "gr":
                gp: list = []
                _collect([item], aff, gp)
                gb = _bbox(gp)
                gw = (gb[2] - gb[0]) if gb else 0.0
                # ник — это строка букв: не слишком узкая (не точка-деталь) и не во всю ширину (не арт)
                if gb and (gb[3] - gb[1]) <= max_text_h and 0.15 * w <= gw <= 0.7 * w \
                        and _center_in(gb, search):
                    pts.extend(gp)
                    removed += 1
                    continue
            shapes.append(item)
        layer["shapes"] = shapes

    data["layers"] = keep
    return _bbox(pts), removed


# ───────────────────── построение нового ника ─────────────────────

class _LottiePen(BasePen):
    """Переводит контуры глифа в формат безье-вершин Lottie."""

    def __init__(self, glyph_set, dx: float):
        super().__init__(glyph_set)
        self.dx = dx
        self.contours: list[dict] = []
        self._c: dict | None = None

    def _pt(self, p):
        return p[0] + self.dx, p[1]

    def _moveTo(self, p):
        self._c = {"v": [self._pt(p)], "i": [(0, 0)], "o": [(0, 0)]}

    def _lineTo(self, p):
        c = self._c
        c["v"].append(self._pt(p))
        c["i"].append((0, 0))
        c["o"].append((0, 0))

    def _cubic(self, c1, c2, p3):
        c = self._c
        v0 = c["v"][-1]
        c["o"][-1] = (c1[0] - v0[0], c1[1] - v0[1])
        c["v"].append(p3)
        c["i"].append((c2[0] - p3[0], c2[1] - p3[1]))
        c["o"].append((0, 0))

    def _curveToOne(self, p1, p2, p3):
        self._cubic(self._pt(p1), self._pt(p2), self._pt(p3))

    def _qCurveToOne(self, p1, p2):
        v0 = self._c["v"][-1]
        q1, q2 = self._pt(p1), self._pt(p2)
        c1 = (v0[0] + 2 / 3 * (q1[0] - v0[0]), v0[1] + 2 / 3 * (q1[1] - v0[1]))
        c2 = (q2[0] + 2 / 3 * (q1[0] - q2[0]), q2[1] + 2 / 3 * (q1[1] - q2[1]))
        self._cubic(c1, c2, q2)

    def _closePath(self):
        c = self._c
        if c is None:
            return
        v = c["v"]
        if len(v) > 1 and abs(v[-1][0] - v[0][0]) < 1e-6 and abs(v[-1][1] - v[0][1]) < 1e-6:
            c["i"][0] = c["i"][-1]
            for key in ("v", "i", "o"):
                c[key].pop()
        self.contours.append(c)
        self._c = None

    def _endPath(self):
        self._closePath()


def _nick_shape_items(nick: str, region: tuple, ) -> list[dict]:
    font = TTFont(str(find_font()))
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    upem = font["head"].unitsPerEm

    contours: list[dict] = []
    dx = 0.0
    for ch in nick:
        gname = cmap.get(ord(ch))
        if gname is None:
            raise TgsError(f"В шрифте нет символа {ch!r}")
        pen = _LottiePen(gs, dx)
        gs[gname].draw(pen)
        contours.extend(pen.contours)
        dx += hmtx[gname][0]
    if not contours:
        raise TgsError("Ник не содержит видимых символов")

    xs = [p[0] for c in contours for p in c["v"]]
    ys = [p[1] for c in contours for p in c["v"]]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    x0, y0, x1, y1 = region
    sc = min((x1 - x0) / max(maxx - minx, 1.0), (y1 - y0) / (0.85 * upem))
    tx = (x0 + x1) / 2 - (minx + maxx) / 2 * sc
    ty = (y0 + y1) / 2 + (miny + maxy) / 2 * sc

    def P(p):
        return [round(p[0] * sc + tx, 2), round(-p[1] * sc + ty, 2)]

    def T(p):
        return [round(p[0] * sc, 2), round(-p[1] * sc, 2)]

    return [
        {
            "ty": "sh",
            "nm": "g",
            "ks": {"a": 0, "k": {
                "i": [T(p) for p in c["i"]],
                "o": [T(p) for p in c["o"]],
                "v": [P(p) for p in c["v"]],
                "c": True,
            }},
        }
        for c in contours
    ]


def _add_nick_layer(data: dict, nick: str, tint: Tint, bbox) -> None:
    w = float(data.get("w", 512))
    h = float(data.get("h", 512))
    if bbox:
        x0, y0, x1, y1 = bbox
        cx = (x0 + x1) / 2
        half = max((x1 - x0) / 2 * 1.04, 0.3 * w)  # для длинных ников нужна ширина
        padv = (y1 - y0) * 0.1
        region = (max(0.0, cx - half), max(0.0, y0 - padv), min(w, cx + half), min(h, y1 + padv))
    else:
        rx0, ry0, rx1, ry1 = config.NICK_REGION
        region = (rx0 * w, ry0 * h, rx1 * w, ry1 * h)

    items = _nick_shape_items(nick, region)
    r, g, b = (c / 255 for c in tint.text)
    layers = data.setdefault("layers", [])
    ind = max([int(l.get("ind", 0)) for l in layers if isinstance(l, dict)] + [0]) + 1
    group = {
        "ty": "gr",
        "nm": "nick",
        "it": items + [
            {"ty": "fl", "c": {"a": 0, "k": [r, g, b, 1]}, "o": {"a": 0, "k": 100},
             "r": 1, "bm": 0, "nm": "Fill"},
            {"ty": "tr", "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]},
             "s": {"a": 0, "k": [100, 100]}, "r": {"a": 0, "k": 0},
             "o": {"a": 0, "k": 100}, "sk": {"a": 0, "k": 0}, "sa": {"a": 0, "k": 0}},
        ],
    }
    layers.insert(0, {
        "ddd": 0, "ind": ind, "ty": 4, "nm": "nick", "sr": 1,
        "ks": {"o": {"a": 0, "k": 100}, "r": {"a": 0, "k": 0},
               "p": {"a": 0, "k": [0, 0, 0]}, "a": {"a": 0, "k": [0, 0, 0]},
               "s": {"a": 0, "k": [100, 100, 100]}},
        "ao": 0, "shapes": [group],
        "ip": data.get("ip", 0), "op": data.get("op", 60), "st": 0, "bm": 0,
    })


# ───────────────────── сжатие и ограничения ─────────────────────

_DROP = {"nm", "mn", "cl", "ln"}


def _round(node: Any, nd: int, slim: bool) -> Any:
    if isinstance(node, float):
        r = round(node, nd)
        return int(r) if r == int(r) else r
    if isinstance(node, dict):
        return {k: _round(v, nd, slim) for k, v in node.items() if not (slim and k in _DROP)}
    if isinstance(node, list):
        return [_round(v, nd, slim) for v in node]
    return node


def _limit(data: dict) -> None:
    fr = float(data.get("fr", 30) or 30)
    if fr > 60:
        data["fr"] = 60
        fr = 60.0
    ip = float(data.get("ip", 0))
    op = float(data.get("op", 60))
    if (op - ip) / fr > 3.0:
        data["op"] = ip + 3.0 * fr


def _original_nick_rgb(data: dict) -> tuple[int, int, int]:
    """Цвет исходного ника: заливка группы #TEXT. Если не нашли — белый."""
    def find(items: list):
        for it in items or []:
            if isinstance(it, dict) and it.get("ty") == "gr":
                if it.get("nm") in ("#TEXT", "#TEXT_wrapper"):
                    for sub in it.get("it", []):
                        if isinstance(sub, dict) and sub.get("ty") == "fl":
                            k = (sub.get("c") or {}).get("k")
                            if isinstance(k, list) and k and isinstance(k[0], dict):
                                k = k[0].get("s", k)  # анимированный цвет — берём первый кадр
                            if isinstance(k, list) and len(k) >= 3 and all(isinstance(x, (int, float)) for x in k[:3]):
                                return tuple(max(0, min(255, round(x * 255))) for x in k[:3])
                found = find(it.get("it", []))
                if found:
                    return found
        return None
    for L in data.get("layers", []):
        if isinstance(L, dict) and L.get("ty") == 4:
            found = find(L.get("shapes", []))
            if found:
                return found
    for a in data.get("assets", []):
        for L in (a.get("layers", []) if isinstance(a, dict) else []):
            if isinstance(L, dict) and L.get("ty") == 4:
                found = find(L.get("shapes", []))
                if found:
                    return found
    return (255, 255, 255)


def tint_from_spec(spec: str) -> Tint:
    """'#RRGGBB' — один цвет (тёмные и светлые части окрашиваются в его оттенки);
    '#AAAAAA|#BBBBBB' — два цвета: тёмные части становятся A, светлые — B (градиент по яркости)."""
    if "|" in spec:
        dark_hex, light_hex = spec.split("|", 1)
        dark, light = parse_hex(dark_hex), parse_hex(light_hex)
        return Tint(dark, light, light)
    return make_tint(parse_hex(spec))



def iter_shape_layers(data: dict):
    """Все слои-фигуры (ty=4) с их полной матрицей, включая предкомпозиции (assets, ty=0)."""
    assets = {a["id"]: a for a in data.get("assets", []) if isinstance(a, dict) and "id" in a and "layers" in a}

    def rec(layers: list, base, depth: int):
        by_ind = {int(l["ind"]): l for l in layers if isinstance(l, dict) and "ind" in l}
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            local = _layer_affine(layer, by_ind)
            aff = _compose(base, local) if base is not None else local
            ty = layer.get("ty")
            if ty == 4:
                yield layer, aff
            elif ty == 0 and depth < 6:
                asset = assets.get(layer.get("refId"))
                if asset is not None:
                    yield from rec([l for l in asset["layers"] if isinstance(l, dict)], aff, depth + 1)

    yield from rec(data.get("layers", []), None, 0)


_IDENT = (1.0, 1.0, 0.0, 0.0)


def _letter_bands(shapes: list, aff: tuple, w: float, h: float) -> list:
    """Пятибуквенные полосы: группы N, у которых ровно 5 дочерних групп-букв в одной строке.

    Возвращает список (N, kids, global_bbox, inner_bbox). Внутренний bbox — в системе координат N
    (без её собственного tr), поэтому новый ник, вставленный внутрь N, движется вместе с буквами.
    """
    out: list = []
    tol_y = 0.03 * max(w, h)
    max_h = 0.25 * max(w, h)

    def visit(items: list, gaff_parent: tuple, depth: int) -> None:
        if depth > 32:
            return
        for it in items:
            if not (isinstance(it, dict) and it.get("ty") == "gr"):
                continue
            tr = next((x for x in it.get("it", []) if isinstance(x, dict) and x.get("ty") == "tr"), None)
            gaff = _compose(gaff_parent, _affine_from(tr)) if tr else gaff_parent
            kids = []
            for c in it.get("it", []):
                if isinstance(c, dict) and c.get("ty") == "gr":
                    gpts: list = []
                    _collect([c], gaff, gpts)
                    ipts: list = []
                    _collect([c], _IDENT, ipts)
                    gb, ib = _bbox(gpts), _bbox(ipts)
                    if gb and ib and ib[2] > ib[0]:
                        kids.append((c, gb, ib))
            if len(kids) >= 5:
                kids.sort(key=lambda t: t[2][0])
                band = [kids[0]]
                for k in kids[1:]:
                    ref = band[0][2]
                    ib = k[2]
                    if abs(ib[1] - ref[1]) < tol_y and abs(ib[3] - ref[3]) < tol_y and (ib[3] - ib[1]) <= max_h:
                        band.append(k)
                if len(band) == 5:
                    gU = (min(b[1][0] for b in band), min(b[1][1] for b in band),
                          max(b[1][2] for b in band), max(b[1][3] for b in band))
                    iU = (min(b[2][0] for b in band), min(b[2][1] for b in band),
                          max(b[2][2] for b in band), max(b[2][3] for b in band))
                    out.append((it, [b[0] for b in band], gU, iU))
            visit(it.get("it", []), gaff, depth + 1)

    visit(shapes, aff, 0)
    return out


def letter_band_layers(data: dict) -> list:
    """Слои-фигуры в фиксированном порядке (тот же, что у iter_shape_layers) и их полосы."""
    w = float(data.get("w", 512))
    h = float(data.get("h", 512))
    return [(li, layer, _letter_bands(layer.get("shapes", []), aff, w, h))
            for li, (layer, aff) in enumerate(iter_shape_layers(data))]


def _letters_fill(kids: list):
    """Цвет заливки букв LOVEX (первый статичный fl в их поддереве), 0..255 — или None."""
    stack = list(kids)
    while stack:
        it = stack.pop(0)
        if not isinstance(it, dict):
            continue
        if it.get("ty") == "fl":
            k = (it.get("c") or {}).get("k")
            if isinstance(k, list) and len(k) >= 3 and all(isinstance(x, (int, float)) for x in k[:3]):
                return [x * 255 for x in k[:3]]
        stack.extend(it.get("it", []))
    return None


def apply_letter_bands(data: dict, pairs: list, nick: str, tint: Tint) -> int:
    """Для каждой пары (layer_index, band_index): удаляет буквы LOVEX по ссылке и ставит ник внутрь той же группы."""
    layers = {li: (layer, bands) for li, layer, bands in letter_band_layers(data)}
    targets = []
    for li, bi in pairs:
        if li not in layers:
            raise TgsError(f"Нет слоя {li}")
        bands = layers[li][1]
        if bi >= len(bands):
            raise TgsError(f"Нет полосы {bi} в слое {li}")
        targets.append(bands[bi])
    removed = 0
    for N, kids, _gbox, ibox in targets:
        keep = [x for x in N.get("it", []) if not any(x is k for k in kids)]
        removed += len(N.get("it", [])) - len(keep)
        N["it"] = keep
        x0, y0, x1, y1 = ibox
        cx = (x0 + x1) / 2
        half = max((x1 - x0) / 2 * 1.04, 0.3 * 512)
        padv = (y1 - y0) * 0.1
        region = (cx - half, y0 - padv, cx + half, y1 + padv)
        items = _nick_shape_items(nick, region)
        col = _letters_fill(kids) or _letters_fill([x for x in N.get('it', []) if isinstance(x, dict) and x.get('ty') == 'fl']) or tint.text
        r, g, b = (c / 255 for c in col) if max(col) > 1 else col[:3]
        wrapper = {
            "ty": "gr", "nm": "nick",
            "it": items + [
                {"ty": "fl", "c": {"a": 0, "k": [r, g, b, 1]}, "o": {"a": 0, "k": 100},
                 "r": 1, "bm": 0, "nm": "Fill"},
                {"ty": "tr", "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]},
                 "s": {"a": 0, "k": [100, 100]}, "r": {"a": 0, "k": 0},
                 "o": {"a": 0, "k": 100}, "sk": {"a": 0, "k": 0}, "sa": {"a": 0, "k": 0}},
            ],
        }
        its = N.setdefault("it", [])
        if its and isinstance(its[-1], dict) and its[-1].get("ty") == "tr":
            its.insert(len(its) - 1, wrapper)
        else:
            its.append(wrapper)
    return removed


def _strip_in_boxes(data: dict, boxes: list) -> int:
    """Удаляет группы-буквы внутри заданных прямоугольников (доли кадра x0,y0,x1,y1).

    Группа удаляется, если её bbox целиком лежит в прямоугольнике (с допуском 1%).
    Работает на любой вложенности групп; остальной арт не трогается.
    """
    w = float(data.get("w", 512))
    h = float(data.get("h", 512))
    pxboxes = [(b[0] * w, b[1] * h, b[2] * w, b[3] * h) for b in boxes]
    tol = 0.01 * max(w, h)
    removed = 0

    def inside(bb: tuple) -> bool:
        return any(bb[0] >= b[0] - tol and bb[1] >= b[1] - tol and bb[2] <= b[2] + tol and bb[3] <= b[3] + tol
                   for b in pxboxes)

    def visit(items: list, aff: tuple, depth: int) -> list:
        nonlocal removed
        if depth > 32:
            return items
        keep = []
        for it in items:
            if isinstance(it, dict) and it.get("ty") == "gr":
                pts: list = []
                _collect([it], aff, pts)
                bb = _bbox(pts)
                if bb and inside(bb):
                    removed += 1
                    continue
                tr = next((x for x in it.get("it", []) if isinstance(x, dict) and x.get("ty") == "tr"), None)
                gaff = _compose(aff, _affine_from(tr)) if tr else aff
                it["it"] = visit(it.get("it", []), gaff, depth + 1)
            keep.append(it)
        return keep

    for layer, aff in list(iter_shape_layers(data)):
        layer["shapes"] = visit(layer.get("shapes", []), aff, 0)
    return removed

def recolor_tgs(src: Path, dst: Path, nick: str, color_hex: str | None,
                nick_hex: str | None = None) -> int:
    """Заменяет ник.
    color_hex — цвет тела эмодзи (None — оставить оригинальным).
    nick_hex — цвет ника: None (как раньше: в цвете тела/исходного ника), "original" (цвет исходного ника)
    или "#RRGGBB". Возвращает число удалённых элементов старого ника."""
    raw = src.read_bytes()
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    data = json.loads(raw)

    # исходный цвет ника читаем до перекраски тела: перекраска затронет и #TEXT
    needs_orig = nick_hex == "original" or (nick_hex is None and not color_hex)
    orig_rgb = _original_nick_rgb(data) if needs_orig else None
    body_tint = tint_from_spec(color_hex) if color_hex else None
    if body_tint is not None:
        _walk_recolor(data, body_tint)
    if nick_hex is None:
        nick_tint = body_tint if body_tint is not None else Tint(orig_rgb, orig_rgb, orig_rgb)
    elif nick_hex == "original":
        nick_tint = Tint(orig_rgb, orig_rgb, orig_rgb)
    else:
        rgb = parse_hex(nick_hex)
        nick_tint = Tint(rgb, rgb, rgb)
    bands = config.LOVEX_BANDS.get(src.stem)
    if bands:
        # буквы LOVEX — отдельные группы внутри полосы; ник ставится внутрь той же группы
        removed = apply_letter_bands(data, [tuple(p) for p in bands], nick, nick_tint)
    elif src.stem in config.EXTRA_IDS:
        removed = 0  # новые эмодзи без найденной полосы LOVEX: надписи не трогаем, ник не ставим
    else:
        region = config.NICK_OVERRIDES.get(src.stem, config.NICK_SEARCH_REGION)
        bbox, removed = _strip_nick(data, region)
        box = config.NICK_BOXES.get(src.stem)
        if box:
            bw, bh = float(data.get("w", 512)), float(data.get("h", 512))
            bbox = (box[0] * bw, box[1] * bh, box[2] * bw, box[3] * bh)
        if not removed:
            log.warning("Старый ник в %s не найден — новый ник будет добавлен в NICK_REGION", src.name)
        placed = _place_nick(data, nick, nick_tint, bbox)
        _purge_slots(data)
        if not placed:
            _add_nick_layer(data, nick, nick_tint, bbox)
    _limit(data)

    for nd, slim in ((3, False), (2, False), (2, True)):
        payload = json.dumps(_round(data, nd, slim), separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")
        blob = gzip.compress(payload, compresslevel=9, mtime=0)
        if len(blob) <= config.TGS_MAX_BYTES:
            dst.write_bytes(blob)
            return removed
    raise TgsError("Эмодзи не влезает в 64 КБ даже после сжатия")