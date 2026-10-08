# Copyright 2026 Firedance Multimedia LLC
# SPDX-License-Identifier: Apache-2.0
"""Thin wrappers over `kicad-cli` (KiCad 8 or newer) and its DRC report."""
from __future__ import annotations

import collections
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

NON_COPPER = ["F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen", "F.Mask", "B.Mask", "Edge.Cuts"]


def kicad_cli() -> str:
    found = os.environ.get("KICAD_CLI") or shutil.which("kicad-cli")
    mac = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
    if not found and Path(mac).exists():
        found = mac
    if not found:
        raise RuntimeError("kicad-cli not found. Install KiCad 8+ or set KICAD_CLI=/path/to/kicad-cli.")
    return found


def run(*args: str) -> None:
    subprocess.run([kicad_cli(), *args], check=True, stdout=subprocess.DEVNULL)


def copper_layers(board: str | Path) -> list[str]:
    """The board's copper layers in stack order, read from the .kicad_pcb `(layers ...)` block."""
    text = Path(board).read_text(encoding="utf-8")
    block = re.search(r"\(layers\s*(.*?)\n\s*\)", text, re.S)
    names = re.findall(r'\(\s*\d+\s+"([^"]+\.Cu)"\s+(?:signal|power|mixed|jumper)', block.group(1) if block else text)
    if not names:
        raise ValueError(f"{board}: no copper layers found")
    order = lambda n: (0 if n == "F.Cu" else 2 if n == "B.Cu" else 1, int(re.sub(r"\D", "", n) or 0))
    return sorted(dict.fromkeys(names), key=order)


def drc(board: str | Path, report_json: str | Path) -> dict:
    run("pcb", "drc", "--format", "json", "--severity-all", "-o", str(report_json), str(board))
    return json.loads(Path(report_json).read_text(encoding="utf-8"))


def summarize_drc(report: dict, show: int = 20) -> tuple[list[str], int]:
    """Human-readable lines and the number of errors (violations with severity "error" plus
    unconnected items)."""
    violations = report.get("violations", [])
    unconnected = report.get("unconnected_items", [])
    counts = collections.Counter((v.get("severity", "?"), v.get("type", "?")) for v in violations)
    lines = [f"{sev:8} {typ:32} {n}" for (sev, typ), n in sorted(counts.items())]
    lines.append(f"unconnected items: {len(unconnected)}")
    errors = [v for v in violations if v.get("severity") == "error"]
    for v in errors[:show]:
        lines.append("  error  " + v.get("type", "?") + " | " + " / ".join(i.get("description", "")[:70] for i in v.get("items", [])))
    for u in unconnected[:show]:
        lines.append("  open   " + " / ".join(i.get("description", "")[:70] for i in u.get("items", [])))
    return lines, len(errors) + len(unconnected)


def gerbers_zip(board: str | Path, out_zip: str | Path, work: str | Path) -> Path:
    """Gerbers for every copper layer plus paste/silk/mask/outline, and Excellon drill files with a
    map, zipped flat (the layout fab houses expect)."""
    work = Path(work)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    layers = ",".join(copper_layers(board) + NON_COPPER)
    run("pcb", "export", "gerbers", "-o", f"{work}/", "--layers", layers, "--subtract-soldermask", str(board))
    run("pcb", "export", "drill", "-o", f"{work}/", "--format", "excellon", "--excellon-units", "mm",
        "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", str(board))
    out = Path(out_zip)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(work.iterdir()):
            z.write(f, f.name)
    return out


def positions(board: str | Path, out_csv: str | Path) -> Path:
    """Placement file in mm relative to the drill/place origin. Set that origin at the board's
    lower-left corner in KiCad so every coordinate is positive; fab houses ask about negatives."""
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--use-drill-file-origin", "-o", str(out_csv), str(board))
    return Path(out_csv)
