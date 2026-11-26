from pathlib import Path

import pygltflib
import pytest
import trimesh
from shapely.ops import unary_union

from planos.config import DeclaredAreas, load_config
from planos.model3d.build import build_glb
from planos.pipeline import build_space
from planos.schema import Space


@pytest.fixture(scope="module")
def built(samples_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = {}
    d = tmp_path_factory.mktemp("glb")
    for sample in ("depto_2d_limpio", "depto_2d_desordenado"):
        space = build_space(samples_dir / f"{sample}.dxf", load_config(samples_dir / f"{sample}.yaml")).space
        data, stats = build_glb(space)
        path = d / f"{sample}.glb"
        path.write_bytes(data)
        out[sample] = (space, path, stats)
    return out


def _expected_wall_volume(space: Space) -> float:
    h = space.metadata.config.heights.floor_to_ceiling
    area = unary_union([w.footprint.to_shapely() for w in space.walls]).area
    thickness = {w.id: w.thickness for w in space.walls}
    cut = sum(
        o.width * thickness[o.wall_id] * (o.head_height - o.sill_height) for o in space.openings if o.wall_id
    )
    return area * h - cut


@pytest.mark.parametrize("sample", ["depto_2d_limpio", "depto_2d_desordenado"])
def test_glb_reloads_with_trimesh(built: dict, sample: str) -> None:
    space, path, stats = built[sample]
    scene = trimesh.load(path)
    assert isinstance(scene, trimesh.Scene)
    names = set(scene.graph.nodes_geometry)
    assert {f"floor_{r.slug}" for r in space.rooms} <= names
    assert "floor_sala_comedor" in names and "floor_s_h_2" in names
    assert any(n.startswith("wall_") for n in names)
    (x0, y0, z0), (x1, y1, z1) = scene.bounds
    assert y0 == pytest.approx(0.0, abs=1e-6) and y1 == pytest.approx(2.40, abs=1e-6)  # Y up
    assert abs(x0 + x1) < 1e-6 and abs(z0 + z1) < 1e-6  # re-centered on the origin
    assert stats.n_floor_nodes == 9 and stats.n_opening_nodes == 17


@pytest.mark.parametrize("sample", ["depto_2d_limpio", "depto_2d_desordenado"])
def test_wall_volume_matches_booleans(built: dict, sample: str) -> None:
    space, path, stats = built[sample]
    expected = _expected_wall_volume(space)
    assert stats.wall_volume_m3 == pytest.approx(expected, rel=0.002)
    scene = trimesh.load(path)
    walls = [g for n, g in scene.geometry.items() if n.startswith("wall_")]
    assert sum(g.volume for g in walls) == pytest.approx(expected, rel=0.002)


def test_wall_pieces_do_not_overlap(built: dict) -> None:
    """Meshes are generated from disjoint footprint pieces: no z-fighting at junctions."""
    space, path, _ = built["depto_2d_limpio"]
    scene = trimesh.load(path)
    from shapely.geometry import Polygon

    footprints = []
    for name, g in scene.geometry.items():
        if not name.startswith("wall_"):
            continue
        # footprint of the mesh = its faces at floor level projected onto the plan
        bottom = g.vertices[:, 1] < 1e-6
        tris = [f for f in g.faces if bottom[f].all()]
        poly = unary_union([Polygon(g.vertices[f][:, [0, 2]]) for f in tris])
        footprints.append(poly)
    total = sum(p.area for p in footprints)
    union = unary_union(footprints).area
    assert total == pytest.approx(union, abs=1e-4)


def test_node_extras_are_written(built: dict) -> None:
    space, path, _ = built["depto_2d_desordenado"]
    gltf = pygltflib.GLTF2().load(str(path))
    by_name = {n.name: n for n in gltf.nodes if n.name}
    for r in space.rooms:
        ex = by_name[f"floor_{r.slug}"].extras
        assert ex["type"] == "floor"
        assert ex["name"] == r.name and ex["net_area_m2"] == pytest.approx(r.net_area_m2)
        assert ex["is_roofed"] is r.is_roofed
    assert by_name["floor_terraza"].extras["is_roofed"] is False
    # label position lies inside its room (glTF x, -z back to plan, minus the re-centering offset)
    from shapely.geometry import Point

    ox, oy = gltf.scenes[0].extras["origin_offset_m"]
    for r in space.rooms:
        x, _, z = by_name[f"floor_{r.slug}"].extras["label_position"]
        assert r.polygon.to_shapely().contains(Point(x + ox, -z + oy)), r.slug
    openings = [n for n in gltf.nodes if n.extras and n.extras.get("type") == "opening"]
    assert len(openings) == 17
    assert {n.name for n in openings} == {o.id for o in space.openings}
    door = by_name["opening_door_01"].extras
    assert door["kind"] == "door" and door["head_height"] == 2.10
    wall = next(n for n in gltf.nodes if n.name == "wall_001")
    assert wall.extras["type"] == "wall" and len(wall.extras["adjacent_room_ids"]) == 2
    unit = gltf.scenes[0].extras
    assert unit["display_area_kind"] == "calculada"
    assert unit["display_area_m2"] == pytest.approx(space.metadata.gross_area_m2)
    assert {m.name for m in gltf.materials} >= {"wall", "floor", "floor_exterior"}


def test_declared_area_is_displayed(built: dict) -> None:
    space, _, _ = built["depto_2d_limpio"]
    meta = space.metadata.model_copy(update={"declared": DeclaredAreas(area_techada_m2=72.5, area_libre_m2=4.9)})
    data, _ = build_glb(space.model_copy(update={"metadata": meta}))
    gltf = pygltflib.GLTF2.load_from_bytes(data)
    unit = gltf.scenes[0].extras
    assert unit["display_area_m2"] == 72.5 and unit["display_area_kind"] == "declarada"


def test_ceiling_option(built: dict) -> None:
    space, _, _ = built["depto_2d_limpio"]
    data, _ = build_glb(space, ceiling=True)
    gltf = pygltflib.GLTF2.load_from_bytes(data)
    ceilings = [n.name for n in gltf.nodes if n.name and n.name.startswith("ceiling_")]
    assert len(ceilings) == 8  # every roofed room, not the terrace
    assert "ceiling_terraza" not in ceilings


def test_clean_and_messy_models_match(built: dict) -> None:
    a = built["depto_2d_limpio"][2]
    b = built["depto_2d_desordenado"][2]
    assert a.wall_volume_m3 == pytest.approx(b.wall_volume_m3, rel=0.001)
    assert a.floor_area_m2 == pytest.approx(b.floor_area_m2, abs=0.01)
