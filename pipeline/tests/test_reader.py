from collections import Counter
from pathlib import Path

import ezdxf
import pytest

from planos.config import Config, LayerMap, load_config
from planos.dxf.reader import read_dxf
from planos.dxf.units import detect_units
from planos.issues import IssueCode, Issues


# ------------------------------------------------------------------ units


@pytest.mark.parametrize(
    "insunits, extent, forced, unit, origin, warns",
    [
        (6, 10.2, "auto", "m", "insunits", False),
        (5, 1020, "auto", "cm", "insunits", False),
        (4, 10200, "auto", "mm", "insunits", False),
        (0, 1020, "auto", "cm", "heuristic", True),
        (0, 10.2, "auto", "m", "heuristic", True),
        (0, 10200, "auto", "mm", "heuristic", True),
        (6, 1020, "auto", "cm", "heuristic", True),  # $INSUNITS wrong: 1 km apartment is implausible
        (0, 1020, "m", "m", "config", False),  # YAML always wins
        (4, None, "auto", "mm", "insunits", False),
    ],
)
def test_detect_units(insunits, extent, forced, unit, origin, warns) -> None:
    info = detect_units(insunits, extent, forced)
    assert info.source_units == unit
    assert info.origin == origin
    assert (info.warning is not None) == warns


# ------------------------------------------------------------------ samples


def test_clean_sample(clean_dxf: Path) -> None:
    issues = Issues()
    d = read_dxf(clean_dxf, Config(), issues)
    assert d.units.source_units == "m" and d.units.origin == "insunits"
    assert not issues.by_code(IssueCode.UNITS_ASSUMED)
    assert not issues.has_errors
    assert len(d.segments["walls"]) > 50
    structure = d.polygons["structure"]
    assert len(structure) == 8 and {p.source for p in structure} == {"closed_polyline"}
    assert Counter(i.kind for i in d.inserts) == {"door": 8, "window": 8, "glass_door": 1}
    labels = [t for t in d.texts if t.category == "room_labels"]
    assert len(labels) == 9
    x0, y0, x1, y1 = d.bounds()
    assert (x0, y0, x1, y1) == pytest.approx((-0.125, -1.725, 10.125, 7.125), abs=1e-6)


def test_clean_door_insert_geometry(clean_dxf: Path) -> None:
    d = read_dxf(clean_dxf, Config(), Issues())
    # main entrance: 0.90 m door in the right wall (x=10), wall direction +Y
    entrance = [i for i in d.inserts if i.kind == "door" and abs(i.position[0] - 10) < 1e-6]
    assert len(entrance) == 1
    door = entrance[0]
    assert door.local_size == pytest.approx((0.90, 0.90), abs=1e-6)
    assert door.x_dir == pytest.approx((0.0, 1.0), abs=1e-9)
    assert door.footprint is not None and door.footprint.area == pytest.approx(0.81, abs=1e-6)


def test_messy_sample_without_yaml(messy_dxf: Path) -> None:
    issues = Issues()
    d = read_dxf(messy_dxf, Config(), issues)
    # centimeters inferred from the walls (not from the frame/title block)
    assert d.units.source_units == "cm" and d.units.origin == "heuristic"
    assert issues.by_code(IssueCode.UNITS_ASSUMED)
    unmapped = " ".join(i.message for i in issues.by_code(IssueCode.LAYER_UNMAPPED))
    assert "TAB-01" in unmapped
    assert "MARCO" not in unmapped and "COTAS" not in unmapped
    x0, y0, x1, y1 = d.bounds()
    assert x1 - x0 == pytest.approx(10.25, abs=0.02)  # in meters now
    structure = d.polygons["structure"]
    assert len(structure) == 8 and {p.source for p in structure} == {"hatch"}
    assert all(p.polygon.area == pytest.approx(0.0625, abs=1e-6) for p in structure)
    assert Counter(i.kind for i in d.inserts) == {"door": 7, "window": 6, "glass_door": 1}
    assert len(d.segments["windows"]) == 3  # window drawn with plain lines


def test_messy_sample_with_yaml(messy_dxf: Path, samples_dir: Path) -> None:
    issues = Issues()
    cfg = load_config(samples_dir / "depto_2d_desordenado.yaml")
    d = read_dxf(messy_dxf, cfg, issues)
    assert d.units.origin == "config" and d.units.scale_to_m == 0.01
    assert not issues.by_code(IssueCode.UNITS_ASSUMED)
    assert not issues.by_code(IssueCode.LAYER_UNMAPPED)
    assert {s.layer for s in d.segments["walls"]} == {"MUROS", "TAB-01"}
    texts = {t.text for t in d.texts if t.category == "room_labels"}
    assert "DORM. PRINCIPAL" in texts  # MTEXT formatting codes removed
    assert any(t.startswith("A=") for t in texts)
    # door blocks are unit-size and scaled by the width (80 cm)
    sizes = sorted(round(i.local_size[0], 2) for i in d.inserts if i.kind == "door")
    assert sizes == [0.7, 0.7, 0.7, 0.8, 0.8, 0.9, 0.9]


def test_region_selects_one_unit(two_units_dxf: Path) -> None:
    cfg = Config(region=(12, -3, 25, 9))
    d = read_dxf(two_units_dxf, cfg, Issues())
    x0, _, x1, _ = d.bounds()
    assert x0 == pytest.approx(12.875, abs=1e-6) and x1 == pytest.approx(23.125, abs=1e-6)
    assert len(d.inserts) == 17
    assert len([t for t in d.texts if t.category == "room_labels"]) == 9


def test_empty_region_is_an_error(two_units_dxf: Path) -> None:
    issues = Issues()
    read_dxf(two_units_dxf, Config(region=(100, 100, 120, 120)), issues)
    assert issues.by_code(IssueCode.REGION_EMPTY) and issues.has_errors


# ------------------------------------------------------------------ synthetic edge cases


def test_xref_unresolved(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    doc.add_xref_def("otro_plano.dxf", "XREF_MUROS")
    msp = doc.modelspace()
    msp.add_line((0, 0), (5, 0), dxfattribs={"layer": "MUROS"})
    msp.add_blockref("XREF_MUROS", (0, 0), dxfattribs={"layer": "MUROS"})
    path = tmp_path / "xref.dxf"
    doc.saveas(path)
    issues = Issues()
    read_dxf(path, Config(units="m"), issues)
    (issue,) = issues.by_code(IssueCode.XREF_UNRESOLVED)
    assert issue.severity == "error" and "XREF_MUROS" in issue.message
    assert issues.has_errors


def test_walls_inside_nested_blocks_are_exploded(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    inner = doc.blocks.new("TRAMO")
    inner.add_line((0, 0), (1, 0))  # layer 0 -> inherits the INSERT layer
    outer = doc.blocks.new("MURO_COMPUESTO")
    outer.add_blockref("TRAMO", (0, 0))
    outer.add_line((0, 0.15), (1, 0.15), dxfattribs={"layer": "MUROS"})
    msp = doc.modelspace()
    msp.add_blockref("MURO_COMPUESTO", (10, 0), dxfattribs={"layer": "MUROS", "rotation": 90, "xscale": 3, "yscale": 1})
    msp.add_arc((0, 0), 1, 0, 90, dxfattribs={"layer": "MUROS"})
    path = tmp_path / "nested.dxf"
    doc.saveas(path)
    d = read_dxf(path, Config(units="m"), Issues())
    straight = sorted(
        (tuple(round(v, 6) for v in s.a), tuple(round(v, 6) for v in s.b))
        for s in d.segments["walls"]
        if s.length > 2
    )
    assert straight == [((9.85, 0.0), (9.85, 3.0)), ((10.0, 0.0), (10.0, 3.0))]
    arc_segments = [s for s in d.segments["walls"] if s.length < 2]
    assert len(arc_segments) >= 8  # flattened arc
    assert sum(s.length for s in arc_segments) == pytest.approx(3.14159 / 2, abs=0.01)


def test_unsupported_and_unmapped(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (5, 0), dxfattribs={"layer": "MUROS"})
    msp.add_3dface([(0, 0), (1, 0), (1, 1)], dxfattribs={"layer": "MUROS"})
    msp.add_line((0, 0), (1, 1), dxfattribs={"layer": "CAPA_RARA"})
    path = tmp_path / "x.dxf"
    doc.saveas(path)
    issues = Issues()
    read_dxf(path, Config(units="m", layers=LayerMap()), issues)
    assert "3DFACE" in issues.by_code(IssueCode.ENTITY_UNSUPPORTED)[0].message
    assert "CAPA_RARA" in issues.by_code(IssueCode.LAYER_UNMAPPED)[0].message
