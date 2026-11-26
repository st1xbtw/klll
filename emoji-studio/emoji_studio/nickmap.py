"""Карта позиций: где в каждом исходном TGS лежат группы, похожие на строку букв ника.

Учитывает цепочку родителей (`parent`), поэтому координаты совпадают с тем, что видно в кадре.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from .tgs_recolor import _affine_from, _bbox, _collect, _compose


def _layer_affine(layer: dict, by_ind: dict, depth: int = 0) -> tuple[float, float, float, float]:
    local = _affine_from(layer.get("ks"))
    par = layer.get("parent")
    parent = by_ind.get(par) if par is not None and depth < 32 else None
    if parent is None or parent is layer:
        return local
    return _compose(_layer_affine(parent, by_ind, depth + 1), local)


def describe_tgs(path: Path, max_h: float = 0.25) -> list[str]:
    """Строки с группами, у которых высота не больше max_h кадра (кандидаты в буквы ника)."""
    data = json.loads(gzip.decompress(path.read_bytes()))
    w = float(data.get("w", 512))
    h = float(data.get("h", 512))
    layers = [l for l in data.get("layers", []) if isinstance(l, dict)]
    by_ind = {int(l["ind"]): l for l in layers if "ind" in l}

    found = []
    for layer in layers:
        if layer.get("ty") != 4:
            continue
        aff = _layer_affine(layer, by_ind)
        for g in layer.get("shapes", []):
            if not isinstance(g, dict) or g.get("ty") != "gr":
                continue
            pts: list = []
            _collect([g], aff, pts)
            bb = _bbox(pts)
            if not bb:
                continue
            x0, y0, x1, y1 = bb[0] / w, bb[1] / h, bb[2] / w, bb[3] / h
            if (y1 - y0) <= max_h:
                found.append((y0, x0, layer.get("ind"), x0, x1, y0, y1))
    found.sort()
    return [f"  слой {ind}: x {a:.2f}–{b:.2f}, y {c:.2f}–{d:.2f}"
            for _, _, ind, a, b, c, d in found]
