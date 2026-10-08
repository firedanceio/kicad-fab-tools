# kicad-fab-tools

Turn a KiCad board into a fab and assembly order, and catch the mistakes that cost a re-spin:
a footprint with no BOM line, a part that's out of stock, a connector placed 90° wrong.

```sh
kicad-fab fab board.kicad_pcb --bom bom.csv --fixes rotation-fixes.csv -o fab-out
```

That runs DRC (stopping on errors), zips Gerbers for every copper layer plus drill files, checks
the BOM against the board, and writes a JLCPCB BOM and CPL with your rotation fixes applied.

## Install

Needs Python 3.9+ and KiCad 8 or newer (`kicad-cli`). No other dependencies.

```sh
pip install git+https://github.com/firedanceio/kicad-fab-tools
```

kicad-fab finds `kicad-cli` on your PATH or in the macOS KiCad app; set `KICAD_CLI` otherwise.

## Commands

| Command | What it does |
|---|---|
| `kicad-fab drc board.kicad_pcb` | Run DRC and print counts by type and severity, then each error and open connection. Also reads an existing DRC JSON. Exits 1 on errors. |
| `kicad-fab bom-check --board board.kicad_pcb --bom bom.csv --qty 10` | Every footprint has one BOM line, every placed BOM part is on the board, footprint names agree, and each LCSC part has stock for your build plus spares. |
| `kicad-fab bom-cost --bom bom.csv --boards 10` | Price placed parts with live LCSC price tiers for your quantity and count extended parts. |
| `kicad-fab jlc --board board.kicad_pcb --bom bom.csv --fixes rotation-fixes.csv` | Write JLCPCB's BOM and CPL files, applying rotation and offset fixes per footprint. |
| `kicad-fab fab board.kicad_pcb --bom bom.csv` | All of the above, ready to upload. |

Run any command with `--help` for its options. `--pos placements.csv` can replace `--board` if you
already exported placements with `kicad-cli pcb export pos`.

## The BOM file

A CSV with one line per part. Column names are matched loosely:

| Column | Also accepted as | Notes |
|---|---|---|
| `Designators` | `Designator`, `Reference`, `Refs` | Space- or comma-separated: `R1 R2 R10` |
| `MPN` | `Manufacturer part number` | Shown in reports and the JLC BOM |
| `Footprint` | `Footprint / package`, `Package` | Optional; compared with the board |
| `LCSC` | `LCSC part number`, `JLCPCB Part #` | e.g. `C12345`; lines without one aren't sent to JLC |
| `Assemble` | `Assembly`, `Place`, `Populate` | `yes`/empty = factory places it; anything else (`no`, `DNP`, `hand`) = not placed |

See [`examples/bom.csv`](examples/bom.csv).

## Rotation fixes

KiCad and JLCPCB sometimes disagree about a footprint's zero rotation or origin. When JLC's
placement viewer shows a part turned or shifted, add one line for that footprint and every
instance is fixed from then on:

```csv
footprint,rotation,dx,dy
SOT-23,180,0,0
MyConnector,0,1.0,0
```

`rotation` is added to KiCad's angle. `dx`/`dy` are in mm in the footprint's own frame, so they
stay right whichever way the part is placed. `jlc` and `fab` list every placed footprint that has
no line yet, which is your checklist for the viewer.

## Tips

- Set the drill/place origin at the board's lower-left corner in KiCad so every coordinate is
  positive. Assembly houses ask about negative coordinates.
- Stock and prices come from the JSON endpoint behind JLCPCB's public parts search. It isn't a
  documented API and could change; failed lookups are reported, never treated as "in stock".
- Order a few spares on cheap passives. `bom-check` asks for 20 % plus 5 extra per line by default
  (`--spare`, `--attrition`).

## Licence

Apache-2.0. Made by [Firedance](https://firedance.io), where it builds our board orders.
