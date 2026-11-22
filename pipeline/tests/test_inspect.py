import json
from pathlib import Path

import ezdxf
import pytest
from typer.testing import CliRunner

from planos.cli import app
from planos.config import Config, load_config
from planos.dxf.inspect import inspect_dxf
from planos.dxf.reader import read_dxf
from planos.geometry.clusters import find_clusters, significant
from planos.issues import IssueCode, Issues

runner = CliRunner()


def _expected(samples_dir: Path) -> dict:
    return json.loads((samples_dir / "expected.json").read_text(encoding="utf-8"))


def test_inspect_clean(clean_dxf: Path, samples_dir: Path) -> None:
    rep = inspect_dxf(clean_dxf)
    cats = {l.name: l.category for l in rep.layers}
    assert cats == {
        "COLUMNAS": "structure",
        "MUROS": "walls",
        "PUERTAS": "doors",
        "TEXTOS": "room_labels",
        "VENTANAS": "windows",
    }
    kinds = {b.name: b.kind for b in rep.blocks}
    assert kinds["PUERTA-80"] == "door"
    assert kinds["MAMPARA-200"] == "glass_door"
    assert kinds["BARANDA-290"] == "window"
    assert len(rep.texts) == 9
    assert len(rep.clusters) == 1
    assert rep.clusters[0].bbox_m == pytest.approx(_expected(samples_dir)["unit_bbox_m"], abs=1e-3)
    assert rep.issues == []


def test_inspect_messy_is_one_unit_even_with_unmapped_partitions(messy_dxf: Path, samples_dir: Path) -> None:
    for cfg in (Config(), load_config(samples_dir / "depto_2d_desordenado.yaml")):
        rep = inspect_dxf(messy_dxf, cfg)
        assert len(rep.clusters) == 1
        assert rep.clusters[0].bbox_m == pytest.approx(_expected(samples_dir)["unit_bbox_m"], abs=0.02)
        assert not [i for i in rep.issues if i.code == IssueCode.MULTIPLE_UNITS_DETECTED]


def test_inspect_two_units(two_units_dxf: Path, samples_dir: Path) -> None:
    rep = inspect_dxf(two_units_dxf)
    expected = _expected(samples_dir)["files"]["planta_2_unidades.dxf"]["units_bboxes_m"]
    got = sorted(c.bbox_m for c in rep.clusters)
    assert len(got) == 2
    for g, e in zip(got, expected):
        assert g == pytest.approx(e, abs=1e-3)
    (issue,) = [i for i in rep.issues if i.code == IssueCode.MULTIPLE_UNITS_DETECTED]
    assert "region: [12.875, -1.725, 23.125, 7.125]" in issue.message

    # region picks one unit: the warning goes away
    rep2 = inspect_dxf(two_units_dxf, Config(region=(12, -3, 25, 9)))
    assert len(rep2.clusters) == 1
    assert not [i for i in rep2.issues if i.code == IssueCode.MULTIPLE_UNITS_DETECTED]


def test_column_island_and_stray_line(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # 6 x 4 room, walls as closed rectangles
    for x0, y0, x1, y1 in [(0, 0, 6, 0.15), (0, 3.85, 6, 4), (0, 0, 0.15, 4), (5.85, 0, 6, 4)]:
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": "MUROS"})
    # free-standing column in the middle of the room
    msp.add_lwpolyline([(2.9, 1.9), (3.2, 1.9), (3.2, 2.2), (2.9, 2.2)], close=True, dxfattribs={"layer": "COLUMNAS"})
    # stray short line far away
    msp.add_line((50, 50), (50.5, 50), dxfattribs={"layer": "MUROS"})
    path = tmp_path / "isla.dxf"
    doc.saveas(path)
    d = read_dxf(path, Config(units="m"), Issues())
    clusters = find_clusters(d, 0.5)
    units = significant(clusters)
    assert len(units) == 1
    assert units[0].bbox_m == pytest.approx((0, 0, 6, 4), abs=1e-6)
    assert len(clusters) == 2  # the stray line is reported but not significant


# ------------------------------------------------------------------ CLI


@pytest.mark.parametrize("name", ["depto_2d_limpio.dxf", "depto_2d_desordenado.dxf", "planta_2_unidades.dxf"])
def test_cli_inspect_runs_on_samples(samples_dir: Path, name: str) -> None:
    result = runner.invoke(app, ["inspect", str(samples_dir / name)])
    assert result.exit_code == 0, result.output
    assert "MUROS" in result.output
    assert "Grupos de muros" in result.output


def test_cli_inspect_json_with_config(messy_dxf: Path, samples_dir: Path) -> None:
    result = runner.invoke(
        app, ["inspect", str(messy_dxf), "--config", str(samples_dir / "depto_2d_desordenado.yaml"), "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["units"] == "cm" and data["units_origin"] == "config"
    assert {l["name"]: l["category"] for l in data["layers"]}["TAB-01"] == "walls"


def test_cli_inspect_bad_inputs(tmp_path: Path) -> None:
    assert runner.invoke(app, ["inspect", str(tmp_path / "nope.dxf")]).exit_code == 2
    dwg = tmp_path / "plano.dwg"
    dwg.write_bytes(b"AC1032")
    res = runner.invoke(app, ["inspect", str(dwg)])
    assert res.exit_code == 2 and "ODA" in res.output
    bad = tmp_path / "bad.yaml"
    bad.write_text("unidades: cm\n", encoding="utf-8")
    dxf = tmp_path / "a.dxf"
    ezdxf.new().saveas(dxf)
    assert runner.invoke(app, ["inspect", str(dxf), "-c", str(bad)]).exit_code == 2
