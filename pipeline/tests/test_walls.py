from collections import Counter
from pathlib import Path

import ezdxf
import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

import generate_samples as gs
from planos.config import Config, load_config
from planos.dxf.reader import read_dxf
from planos.geometry.walls import detect_walls
from planos.issues import IssueCode, Issues


def _ideal_drawn_mask():
    """Walls + columns of the generator model, with the openings cut out."""
    cuts = unary_union([gs.opening_cut(o) for o in gs.OPENINGS])
    cols = unary_union([gs.column_poly(c) for c in gs.COLUMNS])
    return gs.solid_mask().difference(cuts).union(cols)


def _opening_fills(overlap: float = 0.005):
    """Rectangles closing each opening (wall thickness deep, slightly longer than the gap)."""
    fills = []
    for o in gs.OPENINGS:
        w = gs.WALLS[o.wall]
        cx, cy = gs.opening_center(o)
        dx, dy = w.direction
        nx, ny = -dy, dx
        hw, hd = o.width / 2 + overlap, w.t / 2
        fills.append(
            Polygon(
                [
                    (cx - dx * hw - nx * hd, cy - dy * hw - ny * hd),
                    (cx + dx * hw - nx * hd, cy + dy * hw - ny * hd),
                    (cx + dx * hw + nx * hd, cy + dy * hw + ny * hd),
                    (cx - dx * hw + nx * hd, cy - dy * hw + ny * hd),
                ]
            )
        )
    return unary_union(fills)


def _detect(path: Path, cfg: Config):
    issues = Issues()
    d = read_dxf(path, cfg, issues)
    return detect_walls(d, cfg, issues), issues


@pytest.mark.parametrize("sample", ["depto_2d_limpio", "depto_2d_desordenado"])
def test_mask_matches_ideal_and_closes_rooms(samples_dir: Path, sample: str) -> None:
    cfg = load_config(samples_dir / f"{sample}.yaml")
    res, issues = _detect(samples_dir / f"{sample}.dxf", cfg)

    ideal = _ideal_drawn_mask()
    assert res.mask.symmetric_difference(ideal).area < 0.01

    closed = unary_union([res.mask, _opening_fills()])
    assert closed.geom_type == "Polygon"
    holes = sorted(Polygon(h).area for h in closed.interiors)
    expected = sorted(r.area for r in [Polygon(h) for h in gs.solid_mask().interiors])
    assert holes == pytest.approx(expected, abs=0.02)

    assert {round(w.thickness, 3) for w in res.walls if w.source == "line_pair"} == {0.12, 0.15, 0.20}
    assert Counter(w.source for w in res.walls)["structure"] == len(gs.COLUMNS)
    assert not issues.by_code(IssueCode.UNPAIRED_WALL_LINE)


def test_messy_cleanup_is_reported(samples_dir: Path) -> None:
    cfg = load_config(samples_dir / "depto_2d_desordenado.yaml")
    _, issues = _detect(samples_dir / "depto_2d_desordenado.dxf", cfg)
    assert issues.by_code(IssueCode.DUPLICATE_REMOVED)
    assert issues.by_code(IssueCode.GAP_CLOSED)
    clean_cfg = load_config(samples_dir / "depto_2d_limpio.yaml")
    _, clean_issues = _detect(samples_dir / "depto_2d_limpio.dxf", clean_cfg)
    assert len(clean_issues) == 0


def test_messy_without_partitions_layer_loses_rooms(messy_dxf: Path) -> None:
    """Without the YAML, TAB-01 partitions are unmapped: the mask must not invent them."""
    res, issues = _detect(messy_dxf, Config())
    closed = unary_union([res.mask, _opening_fills()])
    assert sum(len(p.interiors) for p in getattr(closed, "geoms", [closed])) < 9
    assert issues.by_code(IssueCode.LAYER_UNMAPPED)


# ------------------------------------------------------------------ synthetic plans


def _save(doc, tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    doc.saveas(path)
    return path


def _room_box(msp, x0, y0, x1, y1, t, layer="MUROS", as_hatch=False):
    """A rectangular room enclosed by walls of thickness t (outer box x0..x1, y0..y1)."""
    outer = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    inner = [(x0 + t, y0 + t), (x1 - t, y0 + t), (x1 - t, y1 - t), (x0 + t, y1 - t)]
    if as_hatch:
        h = msp.add_hatch(dxfattribs={"layer": layer})
        h.paths.add_polyline_path(outer, is_closed=True)
        h.paths.add_polyline_path(inner, is_closed=True)
    else:
        msp.add_lwpolyline(outer, close=True, dxfattribs={"layer": layer})
        msp.add_lwpolyline(inner, close=True, dxfattribs={"layer": layer})


@pytest.mark.parametrize("as_hatch", [False, True])
def test_walls_as_nested_closed_outlines_or_hatch(tmp_path: Path, as_hatch: bool) -> None:
    doc = ezdxf.new("R2010")
    _room_box(doc.modelspace(), 0, 0, 4, 3, 0.15, as_hatch=as_hatch)
    res, issues = _detect(_save(doc, tmp_path, "box.dxf"), Config(units="m"))
    assert res.mask.geom_type == "Polygon"
    assert len(res.mask.interiors) == 1
    assert Polygon(res.mask.interiors[0]).area == pytest.approx(3.7 * 2.7, abs=1e-6)
    assert not issues.by_code(IssueCode.UNPAIRED_WALL_LINE)
    if as_hatch:
        assert {w.source for w in res.walls} == {"hatch"}


def test_thick_wall_is_reported_not_guessed(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (5, 0), dxfattribs={"layer": "MUROS"})
    msp.add_line((0, 0.6), (5, 0.6), dxfattribs={"layer": "MUROS"})  # 60 cm apart: not a wall
    res, issues = _detect(_save(doc, tmp_path, "thick.dxf"), Config(units="m"))
    assert res.walls == []
    unpaired = issues.by_code(IssueCode.UNPAIRED_WALL_LINE)
    assert len(unpaired) == 2 and all(i.location is not None for i in unpaired)


def test_tapered_wall_falls_back_to_polygonize(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # 4 m wall whose faces diverge by ~2.6 degrees: no parallel pair, but a closed thin quad
    pts = [(0, 0), (4, 0), (4, 0.30), (0, 0.12)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        msp.add_line(a, b, dxfattribs={"layer": "MUROS"})
    res, issues = _detect(_save(doc, tmp_path, "taper.dxf"), Config(units="m"))
    assert [w.source for w in res.walls] == ["polygonized"]
    assert res.mask.area == pytest.approx(Polygon(pts).area, abs=1e-6)
    assert not issues.by_code(IssueCode.UNPAIRED_WALL_LINE)


def test_open_wall_ends_without_caps_still_pair(tmp_path: Path) -> None:
    """Openings drawn without jamb lines: the face lines alone define the wall pieces."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for x0, x1 in [(0, 2), (2.9, 6)]:  # 0.9 m door gap, no caps
        msp.add_line((x0, 0), (x1, 0), dxfattribs={"layer": "MUROS"})
        msp.add_line((x0, 0.12), (x1, 0.12), dxfattribs={"layer": "MUROS"})
    res, _ = _detect(_save(doc, tmp_path, "nocaps.dxf"), Config(units="m"))
    assert len(res.walls) == 2
    assert res.mask.geom_type == "MultiPolygon"  # the 0.9 m gap survives the closing
    assert res.mask.area == pytest.approx(5.1 * 0.12, abs=1e-6)
