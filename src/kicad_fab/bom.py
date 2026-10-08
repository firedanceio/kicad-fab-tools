# Copyright 2026 Firedance Multimedia LLC
# SPDX-License-Identifier: Apache-2.0
"""BOM and placement files.

BOM CSV: one line per part, with a space- or comma-separated list of designators. Column names
are matched loosely (case-insensitive, several common spellings):

    Designators | Manufacturer | MPN | Footprint | LCSC | Assemble
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

COLUMNS = {
    "designators": ["designators", "designator", "reference", "references", "refs"],
    "manufacturer": ["manufacturer", "mfr"],
    "mpn": ["mpn", "manufacturer part number", "mfr part number", "part number"],
    "footprint": ["footprint", "footprint / package", "package"],
    "lcsc": ["lcsc", "lcsc part number", "lcsc part #", "jlcpcb part #", "jlc part"],
    "assemble": ["assemble", "assembly", "place", "populate"],
}

# Values in the Assemble column that mean "the factory places this part".
PLACED = {"", "yes", "y", "true", "1", "assemble", "smt", "place"}


@dataclass
class BomLine:
    designators: list[str]
    mpn: str = ""
    manufacturer: str = ""
    footprint: str = ""
    lcsc: str = ""
    assemble: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def placed(self) -> bool:
        """True when the factory should place this part (not DNP, not hand-fitted)."""
        return self.assemble.strip().lower() in PLACED


def _column(header: list[str], key: str) -> str | None:
    lowered = {h.strip().lower(): h for h in header}
    for name in COLUMNS[key]:
        if name in lowered:
            return lowered[name]
    return None


def read_bom(path: str | Path) -> list[BomLine]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        cols = {k: _column(header, k) for k in COLUMNS}
        if not cols["designators"]:
            raise ValueError(f"{path}: no designators column (looked for {', '.join(COLUMNS['designators'])})")
        lines = []
        for row in reader:
            refs = [d for d in re.split(r"[\s,;]+", row[cols["designators"]] or "") if d]
            if not refs:
                continue
            get = lambda k: (row.get(cols[k]) or "").strip() if cols[k] else ""
            lines.append(BomLine(refs, get("mpn"), get("manufacturer"), get("footprint"), get("lcsc"), get("assemble"), row))
        return lines


@dataclass
class Placement:
    ref: str
    value: str
    package: str
    x: float
    y: float
    rotation: float
    side: str  # "top" or "bottom"


def read_pos(path: str | Path) -> dict[str, Placement]:
    """Read `kicad-cli pcb export pos --format csv --units mm` output."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        out = {}
        for r in csv.DictReader(f):
            out[r["Ref"]] = Placement(r["Ref"], r["Val"], r["Package"], float(r["PosX"]), float(r["PosY"]),
                                      float(r["Rot"]), r["Side"].strip().lower())
        return out


def natural_key(ref: str):
    """Sort R2 before R10."""
    m = re.match(r"([A-Za-z_#]*)(\d*)(.*)", ref)
    return (m.group(1), int(m.group(2) or 0), m.group(3))


def check_bom_against_board(bom: list[BomLine], placements: dict[str, Placement],
                            ignore_footprint: set[str] = frozenset()) -> list[str]:
    """Every footprint has exactly one BOM line, every placed BOM designator is on the board, and
    the board's footprint matches the BOM's footprint column when one is given."""
    problems, seen = [], {}
    for line in bom:
        for ref in line.designators:
            if ref in seen:
                problems.append(f"{ref} is on two BOM lines")
            seen[ref] = line
            if ref not in placements:
                if line.placed:
                    problems.append(f"{ref} is in the BOM but not on the board")
                continue
            want, have = line.footprint, placements[ref].package
            if want and ref not in ignore_footprint and not (want.startswith(have) or have in want):
                problems.append(f"{ref} footprint on board is {have}, BOM says {want}")
    for ref in sorted(placements, key=natural_key):
        if ref not in seen:
            problems.append(f"{ref} is on the board but not in the BOM")
    return problems
