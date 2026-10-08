# Copyright 2026 Firedance Multimedia LLC
# SPDX-License-Identifier: Apache-2.0
"""kicad-fab: command line."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import __version__, jlc, kicad, lcsc
from .bom import check_bom_against_board, read_bom, read_pos


def _positions(args, tmp: Path):
    if args.pos:
        return read_pos(args.pos)
    return read_pos(kicad.positions(args.board, tmp / "pos.csv"))


def cmd_drc(args) -> int:
    if args.target.endswith(".json"):
        report = json.loads(Path(args.target).read_text(encoding="utf-8"))
    else:
        out = Path(args.out or Path(args.target).with_suffix(".drc.json"))
        report = kicad.drc(args.target, out)
    lines, errors = kicad.summarize_drc(report, args.show)
    print("\n".join(lines))
    return 1 if errors else 0


def cmd_bom_check(args) -> int:
    bom = read_bom(args.bom)
    with tempfile.TemporaryDirectory() as t:
        placements = _positions(args, Path(t))
    problems = check_bom_against_board(bom, placements, set(args.ignore_footprint or []))
    if not args.no_stock:
        for line in bom:
            if not (line.placed and line.lcsc.upper().startswith("C")):
                continue
            need = int(len(line.designators) * args.qty * (1 + args.spare / 100)) + args.attrition
            try:
                part = lcsc.lookup(line.lcsc)
            except Exception as e:  # network or API change: report, don't guess
                problems.append(f"{line.lcsc}: stock lookup failed ({e})")
                continue
            if part is None:
                problems.append(f"{line.lcsc} ({line.mpn}) not found at LCSC")
                continue
            note = "" if part.stock >= need else "  <-- short"
            if line.mpn and part.model.replace(" ", "").lower() != line.mpn.replace(" ", "").lower():
                note += f"  (LCSC lists {part.model})"
            print(f"{line.lcsc:10} {line.mpn[:28]:28} {'basic' if part.basic else 'ext':5} stock {part.stock:>8} need {need:>5}{note}")
            if part.stock < need:
                problems.append(f"{line.lcsc} has {part.stock} in stock, need {need}")
    for p in problems:
        print("PROBLEM:", p)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_bom_cost(args) -> int:
    total, extended, rows = 0.0, 0, []
    for line in read_bom(args.bom):
        if not (line.placed and line.lcsc.upper().startswith("C")):
            continue
        n = len(line.designators)
        part = lcsc.lookup(line.lcsc)
        if part is None or not part.prices:
            print(f"  {line.lcsc}: no price found, left out of the total", file=sys.stderr)
            continue
        unit = part.unit_price(n * args.boards)
        total += unit * n
        extended += not part.basic
        rows.append((unit * n, line.lcsc, line.mpn[:30], n, unit, "basic" if part.basic else "ext"))
    for cost, code, mpn, n, unit, lib in sorted(rows, reverse=True)[: args.top]:
        print(f"{cost:8.3f}  {code:10} {mpn:30} {n:3} x {unit:8.4f} {lib}")
    print(f"{len(rows)} lines, {extended} extended")
    print(f"parts per board at {args.boards} boards: ${total:.2f}")
    if args.extended_fee:
        print(f"extended-part fees per board: ${extended * args.extended_fee / args.boards:.2f} (${args.extended_fee:g} x {extended} lines / {args.boards} boards)")
    return 0


def cmd_jlc(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = args.name or Path(args.board or args.pos).stem
    with tempfile.TemporaryDirectory() as t:
        placements = _positions(args, Path(t))
    unchecked = jlc.write_jlc(read_bom(args.bom), placements, jlc.read_fixes(args.fixes),
                              out / f"{name}-bom.csv", out / f"{name}-cpl.csv")
    print(f"wrote {out / f'{name}-bom.csv'} and {out / f'{name}-cpl.csv'}")
    if unchecked:
        print("no rotation fix on file for (check these in JLC's placement viewer):")
        for fp in unchecked:
            print("  ", fp)
    return 0


def cmd_fab(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = Path(args.board).stem
    status = 0
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        report = kicad.drc(args.board, out / f"{name}-drc.json")
        lines, errors = kicad.summarize_drc(report, 10)
        print("\n".join(lines))
        if errors and not args.allow_drc_errors:
            print(f"{errors} DRC error(s); fix them or pass --allow-drc-errors")
            return 1
        print("gerbers:", kicad.gerbers_zip(args.board, out / f"{name}-gerbers.zip", t / "gerbers"))
        if args.bom:
            placements = read_pos(kicad.positions(args.board, t / "pos.csv"))
            problems = check_bom_against_board(read_bom(args.bom), placements)
            for p in problems:
                print("PROBLEM:", p)
            status = 1 if problems else 0
            unchecked = jlc.write_jlc(read_bom(args.bom), placements, jlc.read_fixes(args.fixes),
                                      out / f"{name}-bom.csv", out / f"{name}-cpl.csv")
            print(f"jlc: {out / f'{name}-bom.csv'}, {out / f'{name}-cpl.csv'}")
            if unchecked:
                print("no rotation fix on file for:", ", ".join(unchecked))
    return status


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kicad-fab", description="Turn a KiCad board into a fab and assembly order.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("drc", help="run DRC (or read a kicad-cli DRC JSON) and summarise it")
    p.add_argument("target", help="board.kicad_pcb, or an existing DRC .json report")
    p.add_argument("-o", "--out", help="where to write the JSON report")
    p.add_argument("--show", type=int, default=20, help="how many errors to list")
    p.set_defaults(func=cmd_drc)

    def board_or_pos(p):
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--board", help="board.kicad_pcb (placements are exported with kicad-cli)")
        g.add_argument("--pos", help="an existing kicad-cli placement CSV")

    p = sub.add_parser("bom-check", help="check the BOM against the board and live LCSC stock")
    board_or_pos(p)
    p.add_argument("--bom", required=True)
    p.add_argument("--qty", type=int, default=5, help="boards to build (default 5)")
    p.add_argument("--spare", type=float, default=20, help="extra stock wanted, percent (default 20)")
    p.add_argument("--attrition", type=int, default=5, help="extra parts per line for machine losses (default 5)")
    p.add_argument("--no-stock", action="store_true", help="skip the network stock check")
    p.add_argument("--ignore-footprint", nargs="*", metavar="REF", help="designators whose footprint name may differ")
    p.set_defaults(func=cmd_bom_check)

    p = sub.add_parser("bom-cost", help="price placed parts with live LCSC price tiers")
    p.add_argument("--bom", required=True)
    p.add_argument("--boards", type=int, default=5)
    p.add_argument("--top", type=int, default=12, help="how many of the most expensive lines to list")
    p.add_argument("--extended-fee", type=float, default=0, help="per-line fee for extended parts, per order")
    p.set_defaults(func=cmd_bom_cost)

    p = sub.add_parser("jlc", help="write JLCPCB BOM and CPL with rotation fixes")
    board_or_pos(p)
    p.add_argument("--bom", required=True)
    p.add_argument("--fixes", help="CSV of footprint,rotation,dx,dy corrections")
    p.add_argument("--name", help="file name prefix (default: board name)")
    p.add_argument("-o", "--out", default="fab-out")
    p.set_defaults(func=cmd_jlc)

    p = sub.add_parser("fab", help="DRC, Gerber + drill zip, and (with --bom) JLC BOM/CPL in one go")
    p.add_argument("board")
    p.add_argument("--bom")
    p.add_argument("--fixes")
    p.add_argument("-o", "--out", default="fab-out")
    p.add_argument("--allow-drc-errors", action="store_true")
    p.set_defaults(func=cmd_fab)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        print(f"kicad-fab: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
