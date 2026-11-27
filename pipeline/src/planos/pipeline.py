"""DXF → Space: runs every stage and assigns stable ids."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from planos import __version__
from planos.config import Config
from planos.dxf.reader import Drawing, read_dxf
from planos.geometry.clusters import find_clusters, report_clusters
from planos.geometry.openings import OpeningResult, classify_inferred, detect_openings
from planos.geometry.rooms import RoomCandidate, assign_adjacency, detect_rooms, unit_areas
from planos.geometry.walls import WallResult, detect_walls
from planos.issues import BBox2, Issues
from planos.schema import Metadata, Opening, Polygon2, Room, Space, Wall, _r

OPENING_PREFIX = {"door": "door", "window": "window", "glass_door": "glass_door", "passage": "passage", "railing": "railing"}


@dataclass
class PipelineResult:
    space: Space
    drawing: Drawing
    walls: WallResult
    openings: OpeningResult
    rooms: list[RoomCandidate]
    issues: Issues


def build_space(dxf: Path | str, cfg: Config) -> PipelineResult:
    dxf = Path(dxf)
    issues = Issues()
    drawing = read_dxf(dxf, cfg, issues)
    report_clusters(find_clusters(drawing, cfg.tolerances.cluster_gap), issues, cfg.region is not None)
    walls = detect_walls(drawing, cfg, issues)
    openings = detect_openings(drawing, walls, cfg, issues)
    rooms = detect_rooms(drawing, openings.closed_mask, cfg, issues)
    classify_inferred(openings, rooms, cfg, issues)
    areas = unit_areas(rooms, openings.closed_mask, cfg, issues)

    all_walls = walls.walls + openings.fill_walls
    adjacency = assign_adjacency(all_walls, rooms)
    height = cfg.heights.floor_to_ceiling

    wall_ids: dict[int, str] = {}
    wall_models: list[Wall] = []
    for i, w in enumerate(all_walls, 1):
        wid = f"wall_{i:03d}"
        wall_ids[id(w)] = wid
        wall_models.append(
            Wall(
                id=wid,
                start=_r(w.start),
                end=_r(w.end),
                thickness=round(w.thickness, 4),
                height=w.height if w.height is not None else height,
                footprint=Polygon2.from_shapely(w.footprint),
                source=w.source,  # type: ignore[arg-type]
                adjacent_room_ids=adjacency[id(w)],
                source_handles=list(w.handles),
            )
        )

    counters: Counter[str] = Counter()
    opening_models: list[Opening] = []
    ordered = sorted(openings.openings, key=lambda o: (round(o.center[1], 3), round(o.center[0], 3)))
    for o in ordered:
        counters[o.kind] += 1
        opening_models.append(
            Opening(
                id=f"opening_{OPENING_PREFIX[o.kind]}_{counters[o.kind]:02d}",
                kind=o.kind,  # type: ignore[arg-type]
                wall_id=wall_ids.get(id(o.wall)) if o.wall is not None else None,
                center=_r(o.center),
                width=round(o.width, 4),
                sill_height=o.sill_height,
                head_height=o.head_height,
                rotation_deg=round(o.rotation_deg, 3),
                block_name=o.block_name,
                width_source=o.width_source,  # type: ignore[arg-type]
                is_exterior=o.is_exterior,
                source_handle=o.handle,
            )
        )

    room_models = [
        Room(
            id=r.id,
            name=r.name,
            slug=r.slug,
            polygon=Polygon2.from_shapely(r.polygon),
            net_area_m2=round(r.net_area_m2, 3),
            declared_area_m2=r.declared_area_m2,
            is_outdoor=r.is_outdoor,
            has_ceiling=r.has_ceiling,
            label_point=_r(r.label_point),
            label_handle=r.label_handle,
        )
        for r in rooms
    ]

    region = None
    if drawing.region_m:
        x0, y0, x1, y1 = drawing.region_m
        region = BBox2(min=(x0, y0), max=(x1, y1))
    meta = Metadata(
        source_file=dxf.name,
        source_sha256=drawing.sha256,
        dxf_version=drawing.dxf_version,
        source_units=drawing.units.source_units,
        units_origin=drawing.units.origin,
        scale_to_m=drawing.units.scale_to_m,
        region=region,
        pipeline_version=__version__,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0),
        config=cfg,
        gross_area_m2=round(areas.gross_area_m2, 3),
        covered_area_m2=round(areas.covered_area_m2, 3),
        open_area_m2=round(areas.open_area_m2, 3),
        declared=cfg.declared,
    )
    space = Space(metadata=meta, walls=wall_models, openings=opening_models, rooms=room_models, issues=issues.items)
    return PipelineResult(space, drawing, walls, openings, rooms, issues)
