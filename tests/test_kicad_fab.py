from pathlib import Path
import csv
import json

import pytest

from kicad_fab import jlc, kicad, lcsc
from kicad_fab.bom import check_bom_against_board, natural_key, read_bom, read_pos
from kicad_fab.cli import main

F = Path(__file__).parent / "fixtures"


def test_reads_bom_with_loose_column_names_and_assemble_flag():
    bom = read_bom(F / "bom.csv")
    assert bom[0].designators == ["R1", "R2", "R10"]
    assert bom[0].lcsc == "C0000001" and bom[0].placed
    assert not bom[-1].placed


def test_natural_sort():
    assert sorted(["R10", "R2", "R1", "C1"], key=natural_key) == ["C1", "R1", "R2", "R10"]


def test_bom_matches_board():
    assert check_bom_against_board(read_bom(F / "bom.csv"), read_pos(F / "pos.csv")) == []


def test_bom_problems_are_reported():
    pos = read_pos(F / "pos.csv")
    del pos["C1"]
    pos["R99"] = pos["R1"]
    problems = check_bom_against_board(read_bom(F / "bom.csv"), pos)
    assert "C1 is in the BOM but not on the board" in problems
    assert "R99 is on the board but not in the BOM" in problems


def test_jlc_cpl_applies_rotation_and_offset_fixes(tmp_path):
    unchecked = jlc.write_jlc(read_bom(F / "bom.csv"), read_pos(F / "pos.csv"), jlc.read_fixes(F / "fixes.csv"),
                              tmp_path / "bom.csv", tmp_path / "cpl.csv")
    assert unchecked == []
    cpl = {r["Designator"]: r for r in csv.DictReader(open(tmp_path / "cpl.csv"))}
    assert "TP1" not in cpl                       # not placed
    assert cpl["U1"]["Rotation"] == "270"         # 90 + 180
    assert cpl["J1"]["Mid X"] == "30.000mm"       # dx=1 in the footprint frame, rotated 90 deg -> +y
    assert cpl["J1"]["Mid Y"] == "6.000mm"
    assert cpl["R10"]["Layer"] == "Bottom"
    bom = list(csv.DictReader(open(tmp_path / "bom.csv")))
    assert bom[0]["Designator"] == "R1,R2,R10" and bom[0]["JLCPCB Part #"] == "C0000001"


def test_unknown_footprints_are_listed(tmp_path):
    unchecked = jlc.write_jlc(read_bom(F / "bom.csv"), read_pos(F / "pos.csv"), {}, tmp_path / "b.csv", tmp_path / "c.csv")
    assert "SOT-23" in unchecked and "TestPoint" not in unchecked


def test_drc_summary_counts_errors_and_opens():
    lines, errors = kicad.summarize_drc(json.loads((F / "drc.json").read_text()))
    assert errors == 2
    assert any("clearance" in l for l in lines) and "unconnected items: 1" in lines


def test_drc_command_exit_code(capsys):
    assert main(["drc", str(F / "drc.json")]) == 1
    assert "clearance" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["four-layer.kicad_pcb", "four-layer-v10.kicad_pcb"])
def test_copper_layers_in_stack_order(name):
    assert kicad.copper_layers(F / name) == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


def test_price_tiers():
    tiers = [{"startNumber": 1, "endNumber": 9, "productPrice": 0.10},
             {"startNumber": 10, "endNumber": 99, "productPrice": 0.05},
             {"startNumber": 100, "endNumber": -1, "productPrice": 0.02}]
    assert lcsc.tier_price(tiers, 5) == 0.10
    assert lcsc.tier_price(tiers, 50) == 0.05
    assert lcsc.tier_price(tiers, 5000) == 0.02


def test_bom_check_offline(capsys):
    assert main(["bom-check", "--pos", str(F / "pos.csv"), "--bom", str(F / "bom.csv"), "--no-stock"]) == 0
