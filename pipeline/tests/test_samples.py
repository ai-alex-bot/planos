"""Sanity checks for the synthetic DXF samples and their ground truth."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import ezdxf
import pytest

import generate_samples as gs

from conftest import SAMPLES_DIR


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    out = tmp_path_factory.mktemp("samples")
    return out, gs.generate(out)


def _read(out: Path, name: str) -> ezdxf.document.Drawing:
    doc = ezdxf.readfile(out / name)
    auditor = doc.audit()
    assert not auditor.has_errors, [str(e) for e in auditor.errors]
    return doc


def test_ground_truth_matches_hand_calculation(generated: tuple[Path, dict]) -> None:
    _, exp = generated
    areas = {(r["name"], tuple(r["label"])): r["net_area_m2"] for r in exp["rooms"]}
    assert len(areas) == 9
    # interior faces: x 0.10..3.54, y 0.10..3.74 (minus tiny column corners)
    assert areas[("DORM. PRINCIPAL", (1.8, 1.9))] == pytest.approx(3.44 * 3.64, abs=0.02)
    assert areas[("SALA-COMEDOR", (7.6, 2.4))] == pytest.approx(4.44 * 4.24, abs=0.02)
    total = sum(areas.values())
    assert 60 < total < 72  # typical ~65 m2 two-bedroom unit in Lima


def test_committed_expected_json_is_up_to_date(generated: tuple[Path, dict]) -> None:
    out, _ = generated
    committed = json.loads((SAMPLES_DIR / "expected.json").read_text(encoding="utf-8"))
    fresh = json.loads((out / "expected.json").read_text(encoding="utf-8"))
    assert committed == fresh, "run: uv run python scripts/generate_samples.py"
    for name in fresh["files"]:
        assert (SAMPLES_DIR / name).exists()


def test_opening_counts(generated: tuple[Path, dict]) -> None:
    _, exp = generated
    clean = exp["files"]["depto_2d_limpio.dxf"]["openings"]
    messy = exp["files"]["depto_2d_desordenado.dxf"]["openings"]
    assert clean == {"door": 8, "glass_door": 1, "window": 7, "railing": 1}
    assert messy == {"door": 7, "passage": 1, "glass_door": 1, "window": 7, "railing": 1}
    assert sum(clean.values()) == sum(messy.values())


def test_clean_sample(generated: tuple[Path, dict]) -> None:
    out, _ = generated
    doc = _read(out, "depto_2d_limpio.dxf")
    msp = doc.modelspace()
    assert doc.header["$INSUNITS"] == 6
    assert len(msp.query("LINE[layer=='MUROS']")) > 50
    assert len(msp.query("LWPOLYLINE[layer=='COLUMNAS']")) == len(gs.COLUMNS)
    door_inserts = msp.query("INSERT[layer=='PUERTAS']")
    assert Counter(i.dxf.name.split("-")[0] for i in door_inserts) == {"PUERTA": 8, "MAMPARA": 1}
    assert len(msp.query("INSERT[layer=='VENTANAS']")) == 8
    labels = [t.dxf.text for t in msp.query("TEXT[layer=='TEXTOS']")]
    assert sorted(labels) == sorted(r.name for r in gs.ROOMS)


def test_messy_sample(generated: tuple[Path, dict]) -> None:
    out, _ = generated
    doc = _read(out, "depto_2d_desordenado.dxf")
    msp = doc.modelspace()
    assert doc.header["$INSUNITS"] == 0  # unitless: must be inferred or forced in YAML

    walls = msp.query("LINE[layer=='MUROS']")
    partitions = msp.query("LINE[layer=='TAB-01']")
    assert walls and partitions
    xs = [v for e in walls for v in (e.dxf.start.x, e.dxf.end.x)]
    assert max(xs) - min(xs) == pytest.approx(1000 + 20, abs=1)  # drawn in centimeters

    # duplicated lines (same segment regardless of direction)
    keys = Counter(
        tuple(sorted([(round(e.dxf.start.x, 3), round(e.dxf.start.y, 3)), (round(e.dxf.end.x, 3), round(e.dxf.end.y, 3))]))
        for e in [*walls, *partitions]
    )
    assert any(c > 1 for c in keys.values())

    # columns only as hatches in their own layer
    assert len(msp.query("HATCH[layer=='COLUMNAS']")) == len(gs.COLUMNS)
    assert not msp.query("LWPOLYLINE[layer=='COLUMNAS']")

    # one window drawn with plain lines, no block
    assert len(msp.query("LINE[layer=='VENTANAS']")) == 3
    assert len(msp.query("INSERT[layer=='VENTANAS']")) == 6  # 8 windows - lines one - bare railing gap
    assert len(msp.query("INSERT[layer=='PUERTAS']")) == 8  # 7 doors + glass door (passage is a gap)

    texts = [m.plain_text() for m in msp.query("MTEXT")]
    assert "DORM. PRINCIPAL" in texts
    assert any(t.startswith("A=") for t in texts)
    assert any("m²" in t for t in texts)
    assert any(t.upper().replace(".", "").startswith("NPT") for t in texts)

    for layer in ("COTAS", "MOBILIARIO", "MARCO", "ROTULO"):
        assert msp.query(f"*[layer=='{layer}']"), layer
    assert msp.query("DIMENSION")


def test_two_units_sample(generated: tuple[Path, dict]) -> None:
    out, exp = generated
    doc = _read(out, "planta_2_unidades.dxf")
    msp = doc.modelspace()
    xs = [v for e in msp.query("LINE[layer=='MUROS']") for v in (e.dxf.start.x, e.dxf.end.x)]
    (a, b) = exp["files"]["planta_2_unidades.dxf"]["units_bboxes_m"]
    assert min(xs) == pytest.approx(a[0], abs=0.03)  # bbox includes columns
    assert max(xs) == pytest.approx(b[2], abs=0.03)
    assert b[0] - a[2] > 2.5  # corridor between units keeps them disconnected
    assert len(msp.query("TEXT[layer=='TEXTOS']")) == 2 * len(gs.ROOMS)
