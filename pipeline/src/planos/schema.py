"""space.json models (see docs/esquema-space.md).

All lengths in meters, areas in m², 2D coordinates on the DXF XY plane (already in meters).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Polygon

from planos.config import Config, DeclaredAreas
from planos.dxf.units import SourceUnits, UnitsOrigin
from planos.issues import BBox2, Issue

Point2 = tuple[float, float]
SCHEMA_VERSION = "1.0"
COORD_DECIMALS = 4


def _r(p) -> Point2:
    return (round(float(p[0]), COORD_DECIMALS), round(float(p[1]), COORD_DECIMALS))


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Polygon2(_Model):
    exterior: list[Point2]  # counter-clockwise, first point not repeated
    holes: list[list[Point2]] = []

    @classmethod
    def from_shapely(cls, poly: Polygon) -> Polygon2:
        from shapely.geometry.polygon import orient

        poly = orient(poly, sign=1.0)
        return cls(
            exterior=[_r(c) for c in poly.exterior.coords[:-1]],
            holes=[[_r(c) for c in ring.coords[:-1]] for ring in poly.interiors],
        )

    def to_shapely(self) -> Polygon:
        return Polygon(self.exterior, self.holes)


WallSource = Literal["line_pair", "closed_polyline", "hatch", "polygonized", "structure", "railing", "opening_fill"]
OpeningKind = Literal["door", "window", "glass_door", "passage", "railing"]
WidthSource = Literal["wall_gap", "block_extent", "inferred_gap"]


class Wall(_Model):
    id: str
    start: Point2
    end: Point2
    thickness: float
    height: float
    footprint: Polygon2
    source: WallSource
    adjacent_room_ids: tuple[str | None, str | None] = (None, None)  # (left, right) looking start→end
    source_handles: list[str] = []


class Opening(_Model):
    id: str
    kind: OpeningKind
    wall_id: str | None
    center: Point2
    width: float
    sill_height: float
    head_height: float
    rotation_deg: float
    block_name: str | None = None
    width_source: WidthSource
    is_exterior: bool
    source_handle: str | None = None


class Room(_Model):
    id: str
    name: str | None
    slug: str
    polygon: Polygon2
    net_area_m2: float
    declared_area_m2: float | None = None
    is_outdoor: bool = False  # terrace, balcony, patio, garden: counts as área libre
    has_ceiling: bool = True  # 3D only; default = not is_outdoor, overridable in the YAML
    label_point: Point2
    label_handle: str | None = None


class Metadata(_Model):
    source_file: str
    source_sha256: str
    dxf_version: str
    source_units: SourceUnits
    units_origin: UnitsOrigin
    scale_to_m: float
    region: BBox2 | None = None
    pipeline_version: str
    generated_at: datetime
    config: Config
    gross_area_m2: float = Field(description="Área techada (calculada): ambientes techados + muros")
    covered_area_m2: float
    open_area_m2: float
    declared: DeclaredAreas | None = None


class Space(_Model):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    units: Literal["m"] = "m"
    metadata: Metadata
    walls: list[Wall]
    openings: list[Opening]
    rooms: list[Room]
    issues: list[Issue]
