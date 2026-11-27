"""Space → GLB.

* Wall meshes come from the union of all wall footprints split into disjoint pieces (one per wall),
  so there are no overlapping faces (no z-fighting at junctions).
* Each piece is extruded to its wall height (floor_to_ceiling; railings are low walls) and every
  opening box (sill..head) is subtracted with manifold3d: lintels over doors/passages, sill + lintel
  at windows, only a parapet at railings (the cutter goes past the top).
* One floor per room (``floor_<slug>``), a ceiling per room with ``has_ceiling`` (facing down,
  ``hidden_by_default``: the viewer shows it only when walking), empty ``opening_*`` nodes.
* glTF is Y-up: plan (x, y) and height h map to (x, h, -y). The model is re-centered on the
  origin (float32 precision); the offset is stored in the scene extras.
* Node extras (room name/area, wall data, opening data) are written with pygltflib after export.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import manifold3d as mf
import numpy as np
import pygltflib
import shapely
import trimesh
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from planos.schema import Space

COPLANAR_EPS = 0.001  # m; cutters overshoot a little to avoid coplanar boolean faces
COORD_GRID = 1e-6
MIN_PIECE_AREA = 1e-6  # m²

COLORS = {
    "wall": (0.93, 0.92, 0.89, 1.0),
    "column": (0.85, 0.84, 0.82, 1.0),
    "floor": (0.69, 0.55, 0.42, 1.0),
    "floor_exterior": (0.62, 0.62, 0.59, 1.0),
    "ceiling": (0.97, 0.97, 0.97, 1.0),
}


@dataclass
class BuildStats:
    wall_volume_m3: float
    floor_area_m2: float
    n_wall_nodes: int
    n_floor_nodes: int
    n_opening_nodes: int


def _material(name: str, color: tuple, roughness: float) -> trimesh.visual.material.PBRMaterial:
    return trimesh.visual.material.PBRMaterial(
        name=name, baseColorFactor=color, metallicFactor=0.0, roughnessFactor=roughness, doubleSided=False
    )


def _to_gltf(v: np.ndarray) -> np.ndarray:
    """Plan (x, y, h) → glTF (x, h, -y)."""
    return np.column_stack([v[:, 0], v[:, 2], -v[:, 1]])


def _polys(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon) and not g.is_empty]


def _cross_section(geom) -> mf.CrossSection:
    rings = []
    for p in _polys(geom):
        rings.append(np.asarray(p.exterior.coords[:-1], dtype=float))
        rings += [np.asarray(r.coords[:-1], dtype=float) for r in p.interiors]
    return mf.CrossSection(rings, mf.FillRule.EvenOdd)


def _mesh_from_manifold(m: mf.Manifold) -> trimesh.Trimesh | None:
    mesh = m.to_mesh64()
    verts = np.asarray(mesh.vert_properties, dtype=float)[:, :3]
    faces = np.asarray(mesh.tri_verts, dtype=np.int64)
    if len(faces) == 0:
        return None
    tm = trimesh.Trimesh(vertices=_to_gltf(verts), faces=faces, process=False)
    tm.unmerge_vertices()  # flat shading: sharp edges between faces
    tm.vertex_normals = np.repeat(tm.face_normals, 3, axis=0)  # each face owns its 3 vertices
    return tm


def _flat_mesh(poly: Polygon, height: float, up: bool) -> trimesh.Trimesh:
    rings = [np.asarray(poly.exterior.coords[:-1], dtype=float)]
    rings += [np.asarray(r.coords[:-1], dtype=float) for r in poly.interiors]
    tris = np.asarray(mf.triangulate(rings), dtype=np.int64)
    pts2 = np.vstack(rings)
    verts = _to_gltf(np.column_stack([pts2, np.full(len(pts2), height)]))
    if not up:
        tris = tris[:, ::-1]
    tm = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
    tm.vertex_normals = np.tile([0.0, 1.0 if up else -1.0, 0.0], (len(verts), 1))
    uv = np.column_stack([pts2[:, 0], pts2[:, 1]])  # 1 UV unit = 1 m, for tiling textures later
    tm.visual = trimesh.visual.TextureVisuals(uv=uv)
    return tm


def _pieces(space: Space, offset: tuple[float, float]) -> list[tuple[str, str, object]]:
    """Disjoint footprint pieces (wall id, source, geometry): real walls first, fills last."""
    # taller walls first: where a railing meets a wall the overlap belongs to the wall
    order = sorted(space.walls, key=lambda w: (w.source == "opening_fill", -w.height))
    taken = Polygon()
    out = []
    for w in order:
        fp = translate(w.footprint.to_shapely(), -offset[0], -offset[1])
        fp = shapely.set_precision(fp, COORD_GRID)
        piece = fp.difference(taken) if not taken.is_empty else fp
        taken = unary_union([taken, fp])
        if piece.area > MIN_PIECE_AREA:
            out.append((w.id, w.source, piece))
    return out


def _cutter(
    o, thickness: float, margin: float, offset: tuple[float, float], top: float
) -> tuple[mf.Manifold, Polygon]:
    lo = o.sill_height if o.sill_height > 0 else -COPLANAR_EPS
    # a head at the ceiling (railings) cuts past the top: nothing is left above the parapet
    hi = o.head_height if o.head_height < top - COPLANAR_EPS else top + COPLANAR_EPS
    w = o.width + 2 * COPLANAR_EPS
    d = thickness + 2 * margin
    cx, cy = o.center[0] - offset[0], o.center[1] - offset[1]
    cube = mf.Manifold.cube((w, d, hi - lo), True).rotate((0.0, 0.0, o.rotation_deg)).translate((cx, cy, (lo + hi) / 2))
    a = math.radians(o.rotation_deg)
    dx, dy = math.cos(a), math.sin(a)
    nx, ny = -dy, dx
    hw, hd = w / 2, d / 2
    foot = Polygon(
        [
            (cx - dx * hw - nx * hd, cy - dy * hw - ny * hd),
            (cx + dx * hw - nx * hd, cy + dy * hw - ny * hd),
            (cx + dx * hw + nx * hd, cy + dy * hw + ny * hd),
            (cx - dx * hw + nx * hd, cy - dy * hw + ny * hd),
        ]
    )
    return cube, foot


def unit_display_area(space: Space) -> tuple[float, str]:
    """Area shown for the unit: the declared one when available, never the calculated one."""
    d = space.metadata.declared
    if d is not None and d.area_techada_m2:
        return d.area_techada_m2, "declarada"
    return space.metadata.gross_area_m2, "calculada"


def build_glb(space: Space, ceiling: bool | None = None) -> tuple[bytes, BuildStats]:
    cfg = space.metadata.config
    height = cfg.heights.floor_to_ceiling
    margin = cfg.geometry.opening_cut_margin
    with_ceiling = cfg.geometry.ceiling if ceiling is None else ceiling

    geoms = [w.footprint.to_shapely() for w in space.walls] + [r.polygon.to_shapely() for r in space.rooms]
    if geoms:
        x0, y0, x1, y1 = unary_union(geoms).bounds
        offset = ((x0 + x1) / 2, (y0 + y1) / 2)
    else:
        offset = (0.0, 0.0)

    thickness = {w.id: w.thickness for w in space.walls}
    walls_by_id = {w.id: w for w in space.walls}
    cutters = [
        _cutter(o, thickness.get(o.wall_id, cfg.tolerances.wall_thickness_max), margin, offset, height)
        for o in space.openings
        if o.wall_id is not None and o.width > 0
    ]

    mats = {
        "wall": _material("wall", COLORS["wall"], 0.9),
        "column": _material("column", COLORS["column"], 0.85),
        "floor": _material("floor", COLORS["floor"], 0.7),
        "floor_exterior": _material("floor_exterior", COLORS["floor_exterior"], 0.9),
        "ceiling": _material("ceiling", COLORS["ceiling"], 0.95),
    }
    scene = trimesh.Scene()
    extras: dict[str, dict] = {}
    wall_volume = 0.0

    for wid, source, piece in _pieces(space, offset):
        solid = _cross_section(piece).extrude(walls_by_id[wid].height)
        pb = box(*piece.bounds)
        for cube, foot in cutters:
            if foot.intersects(pb) and foot.intersects(piece):
                solid = solid - cube
        if solid.is_empty():
            continue
        wall_volume += solid.volume()
        tm = _mesh_from_manifold(solid)
        if tm is None:
            continue
        tm.visual = trimesh.visual.TextureVisuals(material=mats["column" if source == "structure" else "wall"])
        scene.add_geometry(tm, node_name=wid, geom_name=wid)
        w = walls_by_id[wid]
        extras[wid] = {
            "type": "wall",
            "wall_id": wid,
            "source": source,
            "thickness": w.thickness,
            "height": w.height,
            "adjacent_room_ids": list(w.adjacent_room_ids),
        }

    floor_area = 0.0
    for r in space.rooms:
        poly = translate(r.polygon.to_shapely(), -offset[0], -offset[1])
        tm = _flat_mesh(poly, 0.0, up=True)
        tm.visual.material = mats["floor_exterior" if r.is_outdoor else "floor"]
        name = f"floor_{r.slug}"
        scene.add_geometry(tm, node_name=name, geom_name=name)
        floor_area += float(tm.area)
        extras[name] = {
            "type": "floor",
            "room_id": r.id,
            "name": r.name,
            "slug": r.slug,
            "net_area_m2": r.net_area_m2,
            "declared_area_m2": r.declared_area_m2,
            "is_outdoor": r.is_outdoor,
            "has_ceiling": r.has_ceiling,
            # where to put the room label (glTF coordinates, on the floor)
            "label_position": [r.label_point[0] - offset[0], 0.0, -(r.label_point[1] - offset[1])],
        }
        if with_ceiling and r.has_ceiling:
            cname = f"ceiling_{r.slug}"
            ctm = _flat_mesh(poly, height, up=False)  # faces down: seen from inside the room
            ctm.visual.material = mats["ceiling"]
            scene.add_geometry(ctm, node_name=cname, geom_name=cname)
            extras[cname] = {"type": "ceiling", "room_id": r.id, "slug": r.slug, "hidden_by_default": True}

    glb = scene.export(file_type="glb", include_normals=True)
    gltf = pygltflib.GLTF2.load_from_bytes(glb)
    for node in gltf.nodes:
        if node.name in extras:
            node.extras = extras[node.name]

    # empty opening nodes (position at the bottom-center of the opening, rotated with its wall)
    root = gltf.scenes[gltf.scene or 0]
    for o in space.openings:
        a = math.radians(o.rotation_deg)
        cx, cy = o.center[0] - offset[0], o.center[1] - offset[1]
        gltf.nodes.append(
            pygltflib.Node(
                name=o.id,
                translation=[cx, o.sill_height, -cy],
                rotation=[0.0, math.sin(a / 2), 0.0, math.cos(a / 2)],
                extras={
                    "type": "opening",
                    "opening_id": o.id,
                    "kind": o.kind,
                    "width": o.width,
                    "sill_height": o.sill_height,
                    "head_height": o.head_height,
                    "wall_id": o.wall_id,
                    "is_exterior": o.is_exterior,
                },
            )
        )
        root.nodes.append(len(gltf.nodes) - 1)

    m = space.metadata
    display_area, display_kind = unit_display_area(space)
    root.extras = {
        "type": "unit",
        "schema_version": space.schema_version,
        "source_file": m.source_file,
        "floor_to_ceiling": height,
        "origin_offset_m": [offset[0], offset[1]],
        "gross_area_m2": m.gross_area_m2,
        "covered_area_m2": m.covered_area_m2,
        "open_area_m2": m.open_area_m2,
        "declared": m.declared.model_dump() if m.declared else None,
        "display_area_m2": display_area,
        "display_area_kind": display_kind,
    }
    out = gltf.save_to_bytes()
    data = b"".join(out) if isinstance(out, list) else out
    stats = BuildStats(
        wall_volume_m3=wall_volume,
        floor_area_m2=floor_area,
        n_wall_nodes=sum(1 for e in extras.values() if e["type"] == "wall"),
        n_floor_nodes=sum(1 for e in extras.values() if e["type"] == "floor"),
        n_opening_nodes=len(space.openings),
    )
    return data, stats
