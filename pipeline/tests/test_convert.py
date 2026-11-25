import json
from collections import Counter
from pathlib import Path

import ezdxf
import pytest
from typer.testing import CliRunner

from planos.cli import app
from planos.schema import Space

runner = CliRunner()


def _convert(dxf: Path, out: Path, config: Path | None = None) -> tuple[int, Space | None, str]:
    args = ["convert", str(dxf), "-o", str(out)]
    if config:
        args += ["-c", str(config)]
    res = runner.invoke(app, args)
    space = None
    if (out / "space.json").exists():
        space = Space.model_validate_json((out / "space.json").read_text(encoding="utf-8"))
    report = (out / "report.md").read_text(encoding="utf-8") if (out / "report.md").exists() else ""
    return res.exit_code, space, report


@pytest.fixture(scope="module")
def expected(samples_dir: Path) -> dict:
    return json.loads((samples_dir / "expected.json").read_text(encoding="utf-8"))


def _check_references(space: Space) -> None:
    wall_ids = [w.id for w in space.walls]
    room_ids = {r.id for r in space.rooms}
    assert len(set(wall_ids)) == len(wall_ids)
    assert len({o.id for o in space.openings}) == len(space.openings)
    assert len({r.slug for r in space.rooms}) == len(space.rooms)
    for o in space.openings:
        assert o.wall_id is None or o.wall_id in wall_ids
    for w in space.walls:
        assert all(a is None or a in room_ids for a in w.adjacent_room_ids)


@pytest.mark.parametrize("sample", ["depto_2d_limpio", "depto_2d_desordenado"])
def test_convert_samples(tmp_path: Path, samples_dir: Path, expected: dict, sample: str) -> None:
    code, space, report = _convert(samples_dir / f"{sample}.dxf", tmp_path, samples_dir / f"{sample}.yaml")
    assert code == 0
    assert space is not None
    _check_references(space)
    assert space.units == "m" and space.schema_version == "1.0"
    assert sorted((r.name, round(r.net_area_m2, 2)) for r in space.rooms) == sorted(
        (r["name"], round(r["net_area_m2"], 2)) for r in expected["rooms"]
    )
    assert Counter(o.kind for o in space.openings) == expected["files"][f"{sample}.dxf"]["openings"]
    assert all(w.height == 2.40 for w in space.walls)
    assert space.metadata.open_area_m2 == pytest.approx(4.88, abs=0.01)
    # report content
    assert "Área techada (calculada" in report
    assert "SALA-COMEDOR" in report and "`s_h_2`" in report
    assert ("Sin avisos." in report) == (sample == "depto_2d_limpio")


def test_opening_ids_are_stable_between_clean_and_messy(tmp_path: Path, samples_dir: Path) -> None:
    spaces = []
    for sample in ("depto_2d_limpio", "depto_2d_desordenado"):
        _, space, _ = _convert(samples_dir / f"{sample}.dxf", tmp_path / sample, samples_dir / f"{sample}.yaml")
        spaces.append(space)
    clean, messy = spaces
    pos = lambda s: {o.id: o.center for o in s.openings if o.kind in ("window", "glass_door")}  # noqa: E731
    assert pos(clean) == pos(messy)


def test_convert_without_config_warns_but_succeeds(tmp_path: Path, messy_dxf: Path) -> None:
    code, space, report = _convert(messy_dxf, tmp_path)
    assert code == 0  # warnings only
    codes = {i.code for i in space.issues}
    assert {"units_assumed", "layer_unmapped"} <= codes
    assert space.metadata.source_units == "cm"
    assert "TAB-01" in report


def test_two_units_with_and_without_region(tmp_path: Path, two_units_dxf: Path) -> None:
    code, space, _ = _convert(two_units_dxf, tmp_path / "all")
    assert code == 0
    assert len(space.rooms) == 18
    assert any(i.code == "multiple_units_detected" for i in space.issues)

    cfg = tmp_path / "region.yaml"
    cfg.write_text("region: [12, -3, 25, 9]\n", encoding="utf-8")
    code, space, report = _convert(two_units_dxf, tmp_path / "one", cfg)
    assert code == 0 and len(space.rooms) == 9
    assert not any(i.code == "multiple_units_detected" for i in space.issues)
    assert space.metadata.region is not None
    assert "Región recortada" in report


def test_errors_give_nonzero_exit_code(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    doc.add_xref_def("vecino.dxf", "XREF_VECINO")
    msp = doc.modelspace()
    msp.add_blockref("XREF_VECINO", (0, 0))
    msp.add_line((0, 0), (1, 1), dxfattribs={"layer": "COTAS"})
    path = tmp_path / "roto.dxf"
    doc.saveas(path)
    code, space, report = _convert(path, tmp_path / "out", None)
    assert code == 1
    codes = {i.code for i in space.issues if i.severity == "error"}
    assert codes == {"xref_unresolved", "no_walls"}
    assert "❌" in report and "### ERROR" in report
    assert space.rooms == [] and space.walls == []


def test_declared_areas_in_report(tmp_path: Path, clean_dxf: Path) -> None:
    cfg = tmp_path / "decl.yaml"
    cfg.write_text("declared:\n  area_techada_m2: 73.0\n  area_libre_m2: 4.9\n", encoding="utf-8")
    code, space, report = _convert(clean_dxf, tmp_path / "out", cfg)
    assert code == 0
    assert space.metadata.declared.area_techada_m2 == 73.0
    assert not any(i.code == "area_mismatch" for i in space.issues)  # within 5 %
    assert "73.00" in report and "declarada" in report
