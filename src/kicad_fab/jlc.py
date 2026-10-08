# Copyright 2026 Firedance Multimedia LLC
# SPDX-License-Identifier: Apache-2.0
"""JLCPCB assembly files: BOM and CPL (centroid) with per-footprint rotation and offset fixes.

KiCad and JLCPCB don't always agree on a footprint's zero rotation or origin. Corrections live in
a small CSV you keep with the board, built up as JLC's placement viewer shows you mistakes:

    footprint,rotation,dx,dy
    SOT-23,180,0,0
    MyConnector,90,0.35,0

`rotation` is added to KiCad's angle. `dx`/`dy` (mm) are in the footprint's own frame (before
rotation), so one line fixes every instance however it's placed.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from .bom import BomLine, Placement, natural_key


@dataclass
class Fix:
    rotation: float = 0.0
    dx: float = 0.0
    dy: float = 0.0


def read_fixes(path: str | Path | None) -> dict[str, Fix]:
    if not path:
        return {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {r["footprint"].strip(): Fix(float(r.get("rotation") or 0), float(r.get("dx") or 0), float(r.get("dy") or 0))
                for r in csv.DictReader(f) if r.get("footprint", "").strip()}


def _rotate(x: float, y: float, deg: float) -> tuple[float, float]:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return x * c - y * s, x * s + y * c


def cpl_row(p: Placement, fix: Fix | None) -> list[str]:
    fix = fix or Fix()
    ox, oy = _rotate(fix.dx, fix.dy, p.rotation)
    rot = (p.rotation + fix.rotation) % 360
    return [p.ref, f"{p.x + ox:.3f}mm", f"{p.y + oy:.3f}mm", p.side.capitalize(), f"{rot:g}"]


def write_jlc(bom: list[BomLine], placements: dict[str, Placement], fixes: dict[str, Fix],
              bom_out: str | Path, cpl_out: str | Path) -> list[str]:
    """Write JLC's BOM (placed parts with an LCSC number) and CPL. Returns the footprints placed
    without a fix line, which are worth a look in JLC's placement viewer."""
    by_ref = {ref: line for line in bom for ref in line.designators}
    placed = lambda ref: ref in by_ref and by_ref[ref].placed and by_ref[ref].lcsc.upper().startswith("C")

    with open(bom_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "JLCPCB Part #"])
        for line in bom:
            refs = sorted((r for r in line.designators if r in placements and placed(r)), key=natural_key)
            if refs:
                w.writerow([line.mpn or placements[refs[0]].value, ",".join(refs), placements[refs[0]].package, line.lcsc])

    unchecked = set()
    with open(cpl_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for ref in sorted(placements, key=natural_key):
            if not placed(ref):
                continue
            p = placements[ref]
            if p.package not in fixes:
                unchecked.add(p.package)
            w.writerow(cpl_row(p, fixes.get(p.package)))
    return sorted(unchecked)
