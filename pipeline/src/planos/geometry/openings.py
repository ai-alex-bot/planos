"""Openings: door/window/glass-door blocks and inferred gaps (passages, unmarked windows).

1. Gaps: from every *free* wall end, cast a ray along the wall axis; the first wall/column hit at a
   distance in [gap_opening_min, gap_opening_max] defines a gap (a wall interrupted, or a wall
   ending next to a perpendicular wall or column).
2. Each block is matched to the parallel gap it overlaps (width from the real gap). Without a gap
   (wall drawn continuous) it goes to the nearest parallel wall with the block extent as width.
3. Gaps left without a block are inferred: window lines inside → window; on the outer boundary →
   window (railing/parapet heights); interior → passage.

Every opening gets a fill rectangle (wall thickness deep, overlapping the walls a little) that
closes the wall mask so rooms can be found; the 3D step later cuts sill..head out of it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely import STRtree
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from planos.config import Config
from planos.dxf.reader import Drawing, InsertItem
from planos.geometry.walls import WallCandidate, WallResult, closing
from planos.issues import IssueCode, Issues

P = tuple[float, float]
PARALLEL_SIN = math.sin(math.radians(10))  # block axis vs wall axis tolerance
EXTERIOR_PROBE = 0.05  # m beyond the wall faces when testing indoor/outdoor


@dataclass
class Gap:
    start: P  # on the wall axis, at the free end
    end: P  # on the wall axis, where the ray hit
    thickness: float
    wall: WallCandidate
    used: bool = False

    @property
    def width(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def center(self) -> P:
        return ((self.start[0] + self.end[0]) / 2, (self.start[1] + self.end[1]) / 2)

    @property
    def direction(self) -> P:
        w = self.width or 1.0
        return ((self.end[0] - self.start[0]) / w, (self.end[1] - self.start[1]) / w)


@dataclass
class OpeningCandidate:
    kind: str  # door | window | glass_door | passage
    center: P
    width: float
    direction: P  # wall axis (unit)
    thickness: float
    wall: WallCandidate | None
    width_source: str  # wall_gap | block_extent | inferred_gap
    sill_height: float
    head_height: float
    block_name: str | None = None
    handle: str | None = None
    is_exterior: bool = False
    fill: Polygon | None = None

    @property
    def rotation_deg(self) -> float:
        return math.degrees(math.atan2(self.direction[1], self.direction[0])) % 180.0


@dataclass
class OpeningResult:
    openings: list[OpeningCandidate]
    fill_walls: list[WallCandidate]
    closed_mask: Polygon | MultiPolygon  # wall mask with every opening filled
    gaps: list[Gap] = field(default_factory=list)


def _rect(center: P, d: P, length: float, depth: float) -> Polygon:
    nx, ny = -d[1], d[0]
    hl, hd = length / 2, depth / 2
    cx, cy = center
    return Polygon(
        [
            (cx - d[0] * hl - nx * hd, cy - d[1] * hl - ny * hd),
            (cx + d[0] * hl - nx * hd, cy + d[1] * hl - ny * hd),
            (cx + d[0] * hl + nx * hd, cy + d[1] * hl + ny * hd),
            (cx - d[0] * hl + nx * hd, cy - d[1] * hl + ny * hd),
        ]
    )


# ------------------------------------------------------------------ gaps


def _free_ends(walls: list[WallCandidate], snap: float):
    """(wall, end point, outward direction) for wall ends not touching any other wall."""
    others = [w.footprint for w in walls]
    tree = STRtree(others)
    for idx, w in enumerate(walls):
        if w.source != "line_pair":
            continue
        dx, dy = w.direction
        nx, ny = -dy, dx
        h = w.thickness / 2
        for k, (e, d) in enumerate(((w.start, (-dx, -dy)), (w.end, (dx, dy)))):
            if w.joined[k]:
                continue
            cap = LineString([(e[0] - nx * h, e[1] - ny * h), (e[0] + nx * h, e[1] + ny * h)]).buffer(snap)
            if any(j != idx and others[j].intersects(cap) and not _same_wall(w, walls[j]) for j in tree.query(cap)):
                continue
            yield w, e, d


def _same_wall(w: WallCandidate, o: WallCandidate) -> bool:
    """The other candidate is the same physical wall (e.g. its closed-polyline duplicate)."""
    inter = w.footprint.intersection(o.footprint).area
    return inter > 0.5 * min(w.footprint.area, o.footprint.area)


def find_gaps(result: WallResult, cfg: Config) -> list[Gap]:
    tol = cfg.tolerances
    mask = result.mask
    gaps: list[Gap] = []
    for w, e, d in _free_ends(result.walls, tol.snap):
        start = (e[0] + d[0] * tol.snap, e[1] + d[1] * tol.snap)
        far = (e[0] + d[0] * (tol.gap_opening_max + tol.snap), e[1] + d[1] * (tol.gap_opening_max + tol.snap))
        hit = LineString([start, far]).intersection(mask)
        if hit.is_empty:
            continue
        coords = [c for g in getattr(hit, "geoms", [hit]) for c in g.coords]
        dist = min((c[0] - e[0]) * d[0] + (c[1] - e[1]) * d[1] for c in coords)
        if not (tol.gap_opening_min - tol.snap <= dist <= tol.gap_opening_max + tol.snap):
            continue
        end = (e[0] + d[0] * dist, e[1] + d[1] * dist)
        gap = Gap(e, end, w.thickness, w)
        # the same gap is found from both sides: keep one
        if any(math.dist(g.center, gap.center) < tol.gap_close and abs(g.width - gap.width) < tol.gap_close for g in gaps):
            continue
        gaps.append(gap)
    return gaps


# ------------------------------------------------------------------ blocks


def _block_span(ins: InsertItem, d: P) -> tuple[P, float] | None:
    """Center and length of the block footprint projected on axis d."""
    if ins.footprint is None:
        return None
    pts = list(ins.footprint.exterior.coords)
    ts = [p[0] * d[0] + p[1] * d[1] for p in pts]
    lo, hi = min(ts), max(ts)
    # perpendicular coordinate: the wall-side edge for doors (hinge line), center for panels
    nx, ny = -d[1], d[0]
    if ins.kind == "door":
        s = ins.position[0] * nx + ins.position[1] * ny
    else:
        ss = [p[0] * nx + p[1] * ny for p in pts]
        s = (min(ss) + max(ss)) / 2
    tc = (lo + hi) / 2
    return (d[0] * tc + nx * s, d[1] * tc + ny * s), hi - lo


def _heights(kind: str, cfg: Config) -> tuple[float, float]:
    h = cfg.heights
    if kind == "window":
        return h.window_sill, h.window_head
    return 0.0, h.door_head


def _match_gap(ins: InsertItem, gaps: list[Gap], tol) -> Gap | None:
    best, best_overlap = None, 0.0
    for g in gaps:
        if g.used:
            continue
        d = g.direction
        if abs(ins.x_dir[0] * d[1] - ins.x_dir[1] * d[0]) > PARALLEL_SIN:
            continue
        span = _block_span(ins, d)
        if span is None:
            continue
        c, length = span
        # perpendicular distance from block axis to gap axis
        nx, ny = -d[1], d[0]
        off = abs((c[0] - g.start[0]) * nx + (c[1] - g.start[1]) * ny)
        if off > g.thickness / 2 + tol.wall_thickness_max / 2:
            continue
        t0 = 0.0
        t1 = g.width
        tc = (c[0] - g.start[0]) * d[0] + (c[1] - g.start[1]) * d[1]
        overlap = min(t1, tc + length / 2) - max(t0, tc - length / 2)
        if overlap > best_overlap and overlap >= 0.5 * min(length, g.width):
            best, best_overlap = g, overlap
    return best


def _nearest_wall(ins: InsertItem, walls: list[WallCandidate], tol) -> tuple[WallCandidate, P, float] | None:
    best = None
    for w in walls:
        if w.source not in ("line_pair", "closed_polyline", "hatch", "polygonized"):
            continue
        d = w.direction
        if abs(ins.x_dir[0] * d[1] - ins.x_dir[1] * d[0]) > PARALLEL_SIN:
            continue
        span = _block_span(ins, d)
        if span is None:
            continue
        c, length = span
        nx, ny = -d[1], d[0]
        off = abs((c[0] - w.start[0]) * nx + (c[1] - w.start[1]) * ny)
        tc = (c[0] - w.start[0]) * d[0] + (c[1] - w.start[1]) * d[1]
        if off > w.thickness / 2 + tol.wall_thickness_max / 2 or not (-length / 2 <= tc <= w.length + length / 2):
            continue
        proj = (w.start[0] + d[0] * tc, w.start[1] + d[1] * tc)
        if best is None or off < best[3]:
            best = (w, proj, length, off)
    return None if best is None else best[:3]


# ------------------------------------------------------------------ main


def _is_exterior(o: OpeningCandidate, shell) -> bool:
    nx, ny = -o.direction[1], o.direction[0]
    k = o.thickness / 2 + EXTERIOR_PROBE
    probes = [Point(o.center[0] + nx * k, o.center[1] + ny * k), Point(o.center[0] - nx * k, o.center[1] - ny * k)]
    return any(not shell.covers(p) for p in probes)


def detect_openings(drawing: Drawing, walls: WallResult, cfg: Config, issues: Issues) -> OpeningResult:
    tol = cfg.tolerances
    gaps = find_gaps(walls, cfg)
    openings: list[OpeningCandidate] = []

    for ins in sorted(drawing.inserts, key=lambda i: (round(i.position[1], 3), round(i.position[0], 3))):
        sill, head = _heights(ins.kind, cfg)
        gap = _match_gap(ins, gaps, tol)
        if gap is not None:
            gap.used = True
            openings.append(
                OpeningCandidate(ins.kind, gap.center, gap.width, gap.direction, gap.thickness, gap.wall,
                                 "wall_gap", sill, head, ins.name, ins.handle)
            )
            continue
        near = _nearest_wall(ins, walls.walls, tol)
        if near is not None:
            w, center, length = near
            openings.append(
                OpeningCandidate(ins.kind, center, length, w.direction, w.thickness, w, "block_extent",
                                 sill, head, ins.name, ins.handle)
            )
            continue
        issues.add(
            IssueCode.OPENING_WITHOUT_WALL,
            f"El bloque '{ins.name}' ({ins.kind}) no está sobre ningún muro compatible; no se recorta.",
            location=ins.position,
            handles=[ins.handle],
        )
        length = ins.local_size[0] if ins.local_size else 0.0
        openings.append(
            OpeningCandidate(ins.kind, ins.position, length, ins.x_dir, 0.0, None, "block_extent",
                             sill, head, ins.name, ins.handle)
        )

    window_lines = [LineString([s.a, s.b]) for s in drawing.segments.get("windows", [])]
    pending = [g for g in gaps if not g.used]

    # fills first (needed to tell exterior from interior)
    for o in openings:
        if o.wall is not None and o.width > 0:
            o.fill = _rect(o.center, o.direction, o.width + 2 * tol.snap, o.thickness)
    gap_fills = [_rect(g.center, g.direction, g.width + 2 * tol.snap, g.thickness) for g in pending]
    closed = unary_union([walls.mask] + [o.fill for o in openings if o.fill is not None] + gap_fills)
    closed = closing(closed, tol.snap / 2)
    shell = unary_union([Polygon(p.exterior) for p in getattr(closed, "geoms", [closed])])

    for g, fill in zip(pending, gap_fills):
        probe = fill.buffer(tol.snap)
        has_lines = any(probe.intersects(l) and probe.intersection(l).length > tol.min_wall_length for l in window_lines)
        o = OpeningCandidate("window", g.center, g.width, g.direction, g.thickness, g.wall, "inferred_gap",
                             *_heights("window", cfg), fill=fill)
        exterior = _is_exterior(o, shell)
        if not has_lines and not exterior:
            o.kind = "passage"
            o.sill_height, o.head_height = _heights("passage", cfg)
        reason = "líneas de ventana" if has_lines else ("borde exterior" if exterior else "hueco interior")
        issues.add(
            IssueCode.OPENING_INFERRED,
            f"Hueco de {g.width:.2f} m sin bloque: se asume '{o.kind}' ({reason}).",
            location=g.center,
            handles=g.wall.handles[:5],
        )
        openings.append(o)

    for o in openings:
        o.is_exterior = o.fill is not None and _is_exterior(o, shell)

    fill_walls = [
        WallCandidate(
            start=(o.center[0] - o.direction[0] * o.width / 2, o.center[1] - o.direction[1] * o.width / 2),
            end=(o.center[0] + o.direction[0] * o.width / 2, o.center[1] + o.direction[1] * o.width / 2),
            thickness=o.thickness,
            footprint=o.fill,
            source="opening_fill",
        )
        for o in openings
        if o.fill is not None
    ]
    return OpeningResult(openings=openings, fill_walls=fill_walls, closed_mask=closed, gaps=gaps)
