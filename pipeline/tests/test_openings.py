import json
import math
from collections import Counter
from pathlib import Path

import ezdxf
import pytest
from shapely.geometry import Polygon

import generate_samples as gs
from planos.config import Config, load_config
from planos.dxf.reader import read_dxf
from planos.geometry.openings import classify_inferred, detect_openings
from planos.geometry.rooms import detect_rooms
from planos.geometry.walls import detect_walls
from planos.issues import IssueCode, Issues


def _run(path: Path, cfg: Config):
    issues = Issues()
    d = read_dxf(path, cfg, issues)
    w = detect_walls(d, cfg, issues)
    res = detect_openings(d, w, cfg, issues)
    classify_inferred(res, detect_rooms(d, res.closed_mask, cfg, issues), cfg, issues)
    return res, issues


def _model_openings() -> dict[tuple[float, float], gs.OpeningSpec]:
    return {tuple(round(v, 3) for v in gs.opening_center(o)): o for o in gs.OPENINGS}


@pytest.mark.parametrize("sample", ["depto_2d_limpio", "depto_2d_desordenado"])
def test_sample_openings_match_model(samples_dir: Path, sample: str) -> None:
    res, issues = _run(samples_dir / f"{sample}.dxf", load_config(samples_dir / f"{sample}.yaml"))
    expected = json.loads((samples_dir / "expected.json").read_text(encoding="utf-8"))
    assert Counter(o.kind for o in res.openings) == expected["files"][f"{sample}.dxf"]["openings"]

    model = _model_openings()
    messy = sample.endswith("desordenado")
    for o in res.openings:
        spec = model[tuple(round(v, 3) for v in o.center)]  # exact center
        assert o.width == pytest.approx(spec.width, abs=0.005)
        assert o.thickness == pytest.approx(gs.WALLS[spec.wall].t, abs=0.005)
        assert o.kind == ((spec.messy_kind or spec.kind) if messy else spec.kind)
        assert o.wall is not None and o.fill is not None

    # closing every opening yields exactly the rooms of the model
    cm = res.closed_mask
    assert cm.geom_type == "Polygon"
    holes = sorted(Polygon(h).area for h in cm.interiors)
    assert holes == pytest.approx(sorted(r["net_area_m2"] for r in expected["rooms"]), abs=0.02)

    inferred = issues.by_code(IssueCode.OPENING_INFERRED)
    assert len(inferred) == (3 if messy else 0)
    assert all(i.location is not None for i in inferred)


def test_exterior_flags_and_heights(clean_dxf: Path, samples_dir: Path) -> None:
    res, _ = _run(clean_dxf, load_config(samples_dir / "depto_2d_limpio.yaml"))
    by_name = {}
    for o in res.openings:
        by_name.setdefault((o.kind, o.is_exterior), []).append(o)
    # every window faces the outside (facade, back or terrace railing)
    assert all(o.is_exterior for o in res.openings if o.kind == "window")
    # the glass door opens to the (enclosed) terrace: interior
    (glass,) = [o for o in res.openings if o.kind == "glass_door"]
    assert not glass.is_exterior and (glass.sill_height, glass.head_height) == (0.0, 2.10)
    # only the main entrance door is exterior
    ext_doors = [o for o in res.openings if o.kind == "door" and o.is_exterior]
    assert [tuple(round(v, 3) for v in o.center) for o in ext_doors] == [(10.0, 3.65)]
    win = next(o for o in res.openings if o.kind == "window")
    assert (win.sill_height, win.head_height) == (1.00, 2.10)


def test_messy_inferred_kinds(messy_dxf: Path, samples_dir: Path) -> None:
    res, issues = _run(messy_dxf, load_config(samples_dir / "depto_2d_desordenado.yaml"))
    inferred = {tuple(round(v, 3) for v in o.center): o for o in res.openings if o.width_source == "inferred_gap"}
    terrace = inferred[(8.2, -1.6)]
    assert terrace.kind == "railing"  # outer boundary of an outdoor room (the terrace)
    assert (terrace.sill_height, terrace.head_height) == (1.00, 2.40)
    assert inferred[(8.8, 4.4)].kind == "passage"  # kitchen <-> living, no block
    assert inferred[(8.8, 4.4)].head_height == 2.10 and inferred[(8.8, 4.4)].sill_height == 0.0
    assert inferred[(8.2, 7.0)].kind == "window"  # drawn with window lines only
    reasons = " ".join(i.message for i in issues.by_code(IssueCode.OPENING_INFERRED))
    assert "ambiente exterior" in reasons and "hueco interior" in reasons and "líneas de ventana" in reasons


# ------------------------------------------------------------------ synthetic cases

T = 0.15


def _wall(msp, a, b, t=T, layer="MUROS", closed=False):
    """Wall from a to b (centerline) drawn as two face lines + caps, or as one closed polyline."""
    L = math.dist(a, b)
    dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    nx, ny = -dy * t / 2, dx * t / 2
    pts = [(a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny), (b[0] + nx, b[1] + ny), (a[0] + nx, a[1] + ny)]
    if closed:
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
    else:
        for p, q in zip(pts, pts[1:] + pts[:1]):
            msp.add_line(p, q, dxfattribs={"layer": layer})


def _box_with_door_next_to_corner(closed: bool):
    """4 x 3 room; bottom wall has a 0.9 m gap right next to the left wall."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    h = T / 2
    _wall(msp, (0, -h), (0, 3 + h), closed=closed)  # left
    _wall(msp, (4, -h), (4, 3 + h), closed=closed)  # right
    _wall(msp, (h, 3), (4 - h, 3), closed=closed)  # top
    _wall(msp, (h + 0.9, 0), (4 - h, 0), closed=closed)  # bottom, gap from x=h to x=h+0.9
    return doc


@pytest.mark.parametrize("closed", [False, True])
def test_gap_next_to_perpendicular_wall(tmp_path: Path, closed: bool) -> None:
    doc = _box_with_door_next_to_corner(closed)
    path = tmp_path / "corner.dxf"
    doc.saveas(path)
    res, issues = _run(path, Config(units="m"))
    (o,) = res.openings
    assert o.width_source == "inferred_gap"
    assert o.width == pytest.approx(0.9, abs=0.005)
    assert o.center == pytest.approx((T / 2 + 0.45, 0.0), abs=0.005)
    assert o.kind == "window"  # leads outside an indoor room (unnamed) -> window
    assert len(res.closed_mask.interiors) == 1
    assert Polygon(res.closed_mask.interiors[0]).area == pytest.approx((4 - T) * (3 - T), abs=0.01)


def test_block_on_continuous_wall_uses_block_extent(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    blk = doc.blocks.new("VENTANA-120")
    blk.add_lwpolyline([(-0.6, -0.075), (0.6, -0.075), (0.6, 0.075), (-0.6, 0.075)], close=True)
    msp = doc.modelspace()
    _wall(msp, (0, 0), (5, 0))
    msp.add_blockref("VENTANA-120", (2.5, 0), dxfattribs={"layer": "VENTANAS"})
    path = tmp_path / "cont.dxf"
    doc.saveas(path)
    res, _ = _run(path, Config(units="m"))
    (o,) = res.openings
    assert o.width_source == "block_extent" and o.kind == "window"
    assert o.width == pytest.approx(1.2) and o.center == pytest.approx((2.5, 0.0), abs=1e-6)


def test_block_without_wall_is_reported(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    blk = doc.blocks.new("PUERTA-80")
    blk.add_line((0, 0), (0, 0.8))
    blk.add_arc((0, 0), 0.8, 0, 90)
    msp = doc.modelspace()
    _wall(msp, (0, 0), (5, 0))
    msp.add_blockref("PUERTA-80", (2, 3), dxfattribs={"layer": "PUERTAS"})
    path = tmp_path / "far.dxf"
    doc.saveas(path)
    res, issues = _run(path, Config(units="m"))
    (o,) = res.openings
    assert o.wall is None and o.fill is None
    assert issues.by_code(IssueCode.OPENING_WITHOUT_WALL)


def test_wide_gap_is_not_an_opening(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    _wall(msp, (0, 0), (2, 0))
    _wall(msp, (6.5, 0), (9, 0))  # 4.5 m apart > gap_opening_max
    path = tmp_path / "wide.dxf"
    doc.saveas(path)
    res, issues = _run(path, Config(units="m"))
    assert res.openings == []
    assert not issues.by_code(IssueCode.OPENING_INFERRED)
