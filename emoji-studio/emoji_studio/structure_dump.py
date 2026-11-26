"""Полная структура TGS: слои, родители, группы, имена и габариты — для разбора и правки ника."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from .nickmap import _layer_affine
from .tgs_recolor import _affine_from, _bbox, _collect, _compose


def _items(items: list, aff: tuple, depth: int, w: float, h: float, lines: list[str]) -> None:
    pad = "  " * depth
    for it in items:
        if not isinstance(it, dict):
            continue
        ty, nm = it.get("ty"), it.get("nm")
        if ty == "gr":
            tr = next((x for x in it.get("it", []) if isinstance(x, dict) and x.get("ty") == "tr"), None)
            gaff = _compose(aff, _affine_from(tr)) if tr else aff
            pts: list = []
            _collect([it], aff, pts)
            bb = _bbox(pts)
            box = (f" x[{bb[0]/w:.3f},{bb[2]/w:.3f}] y[{bb[1]/h:.3f},{bb[3]/h:.3f}]" if bb else "")
            n_sh = sum(1 for x in it.get("it", []) if isinstance(x, dict) and x.get("ty") == "sh")
            lines.append(f"{pad}gr nm={nm!r} shapes={n_sh}{box}")
            _items(it.get("it", []), gaff, depth + 1, w, h, lines)
        else:
            lines.append(f"{pad}{ty} nm={nm!r}")


def dump_tgs(path: Path) -> list[str]:
    data = json.loads(gzip.decompress(path.read_bytes()))
    w = float(data.get("w", 512))
    h = float(data.get("h", 512))
    layers = [l for l in data.get("layers", []) if isinstance(l, dict)]
    by_ind = {int(l["ind"]): l for l in layers if "ind" in l}
    lines = [f"кадр {w:g}x{h:g}, слоёв: {len(layers)}"]
    for L in layers:
        lines.append(f"\n[слой ind={L.get('ind')} ty={L.get('ty')} nm={L.get('nm')!r} "
                     f"parent={L.get('parent')} op={L.get('op')}]")
        if L.get("ty") == 4:
            _items(L.get("shapes", []), _layer_affine(L, by_ind), 1, w, h, lines)
    return lines
