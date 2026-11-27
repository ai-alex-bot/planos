"""Terrace open side: a railing (low wall) and nothing above it."""

from __future__ import annotations

from pathlib import Path

import pygltflib
import pytest
import trimesh
from shapely.geometry import MultiPoint, Polygon

import generate_samples as gs
from planos.config import load_config
from planos.model3d.build import build_glb
from planos.pipeline import build_space

RAILING_HEIGHT = 1.00
TERRACE_OPEN_SIDE = next(o for o in gs.OPENINGS if o.wall == 5)  # 2.90 m gap at y = -1.6


def wall_heights_over(path: Path, area: Polygon) -> list[float]:
    """Max height of every wall triangle whose plan projection touches `area` (plan meters)."""
    gltf = pygltflib.GLTF2().load(str(path))
    ox, oy = gltf.scenes[0].extras["origin_offset_m"]
    scene = trimesh.load(path)
    out = []
    for node in scene.graph.nodes_geometry:
        if not node.startswith("wall_"):
            continue
        T, gname = scene.graph[node]
        m = scene.geometry[gname].copy()
        m.apply_transform(T)
        for tri in m.vertices[m.faces]:
            hull = MultiPoint([(x + ox, -z + oy) for x, _, z in tri]).convex_hull
            if hull.intersects(area):
                out.append(float(tri[:, 1].max()))
    return out


def _open_side_footprint(shrink: float = 0.01) -> Polygon:
    o = TERRACE_OPEN_SIDE
    w = gs.WALLS[o.wall]
    cx, cy = gs.opening_center(o)
    hw, hd = o.width / 2 - shrink, w.t / 2 + 0.02
    return Polygon([(cx - hw, cy - hd), (cx + hw, cy - hd), (cx + hw, cy + hd), (cx - hw, cy + hd)])


@pytest.mark.parametrize("sample", ["depto_2d_limpio", "depto_2d_desordenado"])
def test_nothing_above_the_terrace_railing(tmp_path: Path, samples_dir: Path, sample: str) -> None:
    space = build_space(samples_dir / f"{sample}.dxf", load_config(samples_dir / f"{sample}.yaml")).space
    data, _ = build_glb(space)
    path = tmp_path / "m.glb"
    path.write_bytes(data)
    over = wall_heights_over(path, _open_side_footprint())
    assert over, "the railing itself must exist"
    assert max(over) == pytest.approx(RAILING_HEIGHT, abs=1e-6), f"geometry up to {max(over):.2f} m over the railing"


def _glb(space, tmp_path: Path, name: str = "m.glb") -> Path:
    data, _ = build_glb(space)
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_railing_kinds_in_samples(samples_dir: Path) -> None:
    clean = build_space(samples_dir / "depto_2d_limpio.dxf", load_config(samples_dir / "depto_2d_limpio.yaml")).space
    messy = build_space(samples_dir / "depto_2d_desordenado.dxf", load_config(samples_dir / "depto_2d_desordenado.yaml")).space
    (rc,) = [o for o in clean.openings if o.kind == "railing"]
    (rm,) = [o for o in messy.openings if o.kind == "railing"]
    assert rc.block_name == "BARANDA-290" and rc.width_source == "wall_gap"  # block name wins over its layer
    assert rm.width_source == "inferred_gap"  # bare gap next to the (outdoor) terrace
    for o in (rc, rm):
        assert (o.sill_height, o.head_height) == (1.00, 2.40) and o.is_exterior
    assert not [o for o in clean.openings if o.block_name and o.block_name.startswith("BARANDA") and o.kind == "window"]


# ------------------------------------------------------------------ balcony with railings drawn as lines

import ezdxf  # noqa: E402

from planos.config import Config  # noqa: E402

T = 0.15


def _wall(msp, a, b, t, layer):
    import math

    L = math.dist(a, b)
    dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    nx, ny = -dy * t / 2, dx * t / 2
    pts = [(a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny), (b[0] + nx, b[1] + ny), (a[0] + nx, a[1] + ny)]
    for p, q in zip(pts, pts[1:] + pts[:1]):
        msp.add_line(p, q, dxfattribs={"layer": layer})


def _balcony_plan(tmp_path: Path, single_lines: bool) -> Path:
    """6 x 4 living room; a 3 x 1.2 m projecting balcony enclosed by railings on its 3 sides."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    h = T / 2
    _wall(msp, (-h, 0), (6 + h, 0), T, "MUROS")  # facade
    _wall(msp, (-h, 4), (6 + h, 4), T, "MUROS")
    _wall(msp, (0, h), (0, 4 - h), T, "MUROS")
    _wall(msp, (6, h), (6, 4 - h), T, "MUROS")
    path_pts = [(1.5, -h), (1.5, -1.2), (4.5, -1.2), (4.5, -h)]
    if single_lines:
        for a, b in zip(path_pts, path_pts[1:]):
            msp.add_line(a, b, dxfattribs={"layer": "BARANDAS"})
    else:
        for a, b in zip(path_pts, path_pts[1:]):
            _wall(msp, a, b, 0.10, "BARANDAS")
    for text, p in [("SALA", (3, 2)), ("BALCÓN", (3, -0.6))]:
        msp.add_text(text, height=0.15, dxfattribs={"layer": "TEXTOS"}).set_placement(p)
    path = tmp_path / "balcon.dxf"
    doc.saveas(path)
    return path


@pytest.mark.parametrize("single_lines", [False, True], ids=["paired_lines", "single_lines"])
def test_projecting_balcony_with_railing_layer(tmp_path: Path, single_lines: bool) -> None:
    res = build_space(_balcony_plan(tmp_path, single_lines), Config(units="m"))
    space = res.space
    rooms = {r.slug: r for r in space.rooms}
    assert set(rooms) == {"sala", "balcon"}
    balcony = rooms["balcon"]
    assert balcony.is_outdoor and not balcony.has_ceiling
    assert balcony.net_area_m2 == pytest.approx(2.9 * (1.2 - 0.05 - T / 2), abs=0.02)
    assert space.metadata.open_area_m2 == pytest.approx(balcony.net_area_m2)
    assert {w.height for w in space.walls if w.source == "railing"} == {1.00}
    assert not [i for i in space.issues if i.code == "unpaired_wall_line"]

    path = _glb(space, tmp_path)
    # everything in front of the facade (the whole balcony) stays at railing height
    in_front = Polygon([(1.3, -1.4), (4.7, -1.4), (4.7, -T / 2 - 0.005), (1.3, -T / 2 - 0.005)])
    heights = wall_heights_over(path, in_front)
    assert heights and max(heights) == pytest.approx(RAILING_HEIGHT, abs=1e-6)
    names = {n.name for n in pygltflib.GLTF2().load(str(path)).nodes if n.name}
    assert "ceiling_sala" in names and "ceiling_balcon" not in names


def test_terrace_under_the_slab_above(tmp_path: Path, samples_dir: Path) -> None:
    """has_ceiling forced in the YAML: railing in front, ceiling above, nothing in between."""
    cfg_path = tmp_path / "techada.yaml"
    cfg_path.write_text(
        (samples_dir / "depto_2d_desordenado.yaml").read_text(encoding="utf-8")
        + 'rooms:\n  "TERRAZA": {has_ceiling: true}\n',
        encoding="utf-8",
    )
    space = build_space(samples_dir / "depto_2d_desordenado.dxf", load_config(cfg_path)).space
    terrace = next(r for r in space.rooms if r.slug == "terraza")
    assert terrace.is_outdoor and terrace.has_ceiling
    assert space.metadata.open_area_m2 == pytest.approx(terrace.net_area_m2)  # still área libre
    assert any(o.kind == "railing" for o in space.openings)  # rule uses is_outdoor, not the ceiling
    path = _glb(space, tmp_path)
    assert max(wall_heights_over(path, _open_side_footprint())) == pytest.approx(RAILING_HEIGHT, abs=1e-6)
    gltf = pygltflib.GLTF2().load(str(path))
    assert "ceiling_terraza" in {n.name for n in gltf.nodes}


def test_report_mentions_railings(samples_dir: Path) -> None:
    from planos.report import render_report

    space = build_space(samples_dir / "depto_2d_limpio.dxf", load_config(samples_dir / "depto_2d_limpio.yaml")).space
    report = render_report(space)
    assert "| baranda |" in report and "1 baranda" in report
    assert "baranda 1.00 m" in report
    assert "| Exterior | Techo 3D |" in report
