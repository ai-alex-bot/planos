"""Wall detection: build the wall mask (plan footprint of all walls) and straight wall candidates.

Sources, in order:
1. pairs of parallel face lines (thickness within [wall_thickness_min, wall_thickness_max]);
2. thin closed polylines / hatches on wall layers;
3. structure polygons (columns, shear walls);
4. fallback: polygonize leftover lines and keep thin faces.

Collinear pieces of the same wall (split by T junctions) are merged, and a morphological closing
(radius below gap_opening_min/2, so real openings survive) welds L/T corners.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import shapely
from shapely import STRtree
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import polygonize, unary_union

from planos.config import Config, Tolerances
from planos.dxf.reader import Drawing
from planos.geometry.cleanup import CSeg, clean_segments
from planos.issues import IssueCode, Issues

P = tuple[float, float]
MAX_UNPAIRED_ISSUES = 15


@dataclass
class WallCandidate:
    start: P
    end: P
    thickness: float
    footprint: Polygon
    source: str  # line_pair | closed_polyline | hatch | polygonized | structure | opening_fill
    handles: tuple[str, ...] = ()
    joined: list[bool] = field(default_factory=lambda: [False, False])  # start/end extended into a junction
    height: float | None = None  # None = floor to ceiling; railings are low walls

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def direction(self) -> P:
        L = self.length or 1.0
        return ((self.end[0] - self.start[0]) / L, (self.end[1] - self.start[1]) / L)


@dataclass
class WallResult:
    walls: list[WallCandidate]
    mask: Polygon | MultiPolygon  # union of all wall footprints after closing
    segments: list[CSeg]  # cleaned wall line work (used later to find gaps)


# ------------------------------------------------------------------ interval helpers


def _subtract(intervals: list[tuple[float, float]], cut: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = intervals
    for c0, c1 in cut:
        nxt = []
        for a, b in out:
            if c1 <= a or c0 >= b:
                nxt.append((a, b))
                continue
            if c0 > a:
                nxt.append((a, c0))
            if c1 < b:
                nxt.append((c1, b))
        out = nxt
    return out


# ------------------------------------------------------------------ pairing


def _pair_lines(segs: list[CSeg], tol: Tolerances) -> list[WallCandidate]:
    sin_tol = math.sin(math.radians(tol.angle_deg))
    usable = [i for i, s in enumerate(segs) if s.length >= tol.min_wall_length]
    lines = [segs[i].line() for i in usable]
    tree = STRtree(lines)
    reach = tol.wall_thickness_max + tol.snap

    cands = []
    for k, i in enumerate(usable):
        s = segs[i]
        dx, dy = s.direction
        nx, ny = -dy, dx
        for kk in tree.query(lines[k].buffer(reach, cap_style="flat")):
            j = usable[kk]
            if j <= i:
                continue
            o = segs[j]
            ex, ey = o.direction
            if abs(dx * ey - dy * ex) > sin_tol:
                continue
            off_a = (o.a[0] - s.a[0]) * nx + (o.a[1] - s.a[1]) * ny
            off_b = (o.b[0] - s.a[0]) * nx + (o.b[1] - s.a[1]) * ny
            if off_a * off_b <= 0 or abs(off_a - off_b) > max(tol.snap, sin_tol * o.length):
                continue
            off = (off_a + off_b) / 2
            if not (tol.wall_thickness_min - tol.snap <= abs(off) <= tol.wall_thickness_max + tol.snap):
                continue
            ta = (o.a[0] - s.a[0]) * dx + (o.a[1] - s.a[1]) * dy
            tb = (o.b[0] - s.a[0]) * dx + (o.b[1] - s.a[1]) * dy
            lo, hi = max(0.0, min(ta, tb)), min(s.length, max(ta, tb))
            if hi - lo < tol.min_wall_length:
                continue
            cands.append((abs(off), i, j, lo, hi, off))

    cands.sort(key=lambda c: (round(c[0], 4), -(c[4] - c[3])))
    claimed: dict[int, list[tuple[float, float]]] = {}
    walls: list[WallCandidate] = []
    for _, i, j, lo, hi, off in cands:
        s, o = segs[i], segs[j]
        dx, dy = s.direction
        nx, ny = -dy, dx
        ox, oy = o.direction

        def to_j(t: float) -> float:
            px, py = s.a[0] + dx * t, s.a[1] + dy * t
            return (px - o.a[0]) * ox + (py - o.a[1]) * oy

        def to_i(u: float) -> float:
            px, py = o.a[0] + ox * u, o.a[1] + oy * u
            return (px - s.a[0]) * dx + (py - s.a[1]) * dy

        for a, b in _subtract([(lo, hi)], claimed.get(i, [])):
            ja, jb = sorted((to_j(a), to_j(b)))
            for c, d in _subtract([(ja, jb)], claimed.get(j, [])):
                ia, ib = sorted((to_i(c), to_i(d)))
                if ib - ia < tol.min_wall_length:
                    continue
                p0 = (s.a[0] + dx * ia, s.a[1] + dy * ia)
                p1 = (s.a[0] + dx * ib, s.a[1] + dy * ib)
                p2 = (p1[0] + nx * off, p1[1] + ny * off)
                p3 = (p0[0] + nx * off, p0[1] + ny * off)
                h = off / 2
                walls.append(
                    WallCandidate(
                        start=(p0[0] + nx * h, p0[1] + ny * h),
                        end=(p1[0] + nx * h, p1[1] + ny * h),
                        thickness=abs(off),
                        footprint=Polygon([p0, p1, p2, p3]),
                        source="line_pair",
                        handles=tuple(dict.fromkeys(s.handles + o.handles)),
                    )
                )
                claimed.setdefault(i, []).append((ia, ib))
                claimed.setdefault(j, []).append((c, d))
    return walls


def _merge_collinear_walls(walls: list[WallCandidate], tol: Tolerances) -> list[WallCandidate]:
    """Join pieces of the same wall (same axis and thickness) separated by less than an opening."""
    max_gap = tol.gap_opening_min - tol.snap
    sin_tol = math.sin(math.radians(tol.angle_deg))
    pending = sorted(walls, key=lambda w: -w.length)
    out: list[WallCandidate] = []
    while pending:
        ref = pending.pop(0)
        dx, dy = ref.direction
        nx, ny = -dy, dx
        group = [ref]
        rest = []
        for w in pending:
            ex, ey = w.direction
            same_dir = abs(dx * ey - dy * ex) <= sin_tol
            offs = [(p[0] - ref.start[0]) * nx + (p[1] - ref.start[1]) * ny for p in (w.start, w.end)]
            if same_dir and max(abs(v) for v in offs) <= tol.snap and abs(w.thickness - ref.thickness) <= tol.snap:
                group.append(w)
            else:
                rest.append(w)
        pending = rest

        def t(p: P) -> float:
            return (p[0] - ref.start[0]) * dx + (p[1] - ref.start[1]) * dy

        spans = sorted((min(t(w.start), t(w.end)), max(t(w.start), t(w.end)), w) for w in group)
        runs: list[list] = []
        for lo, hi, w in spans:
            if runs and lo <= runs[-1][1] + max_gap:
                runs[-1][1] = max(runs[-1][1], hi)
                runs[-1][2].append(w)
            else:
                runs.append([lo, hi, [w]])
        leftovers = []
        for lo, hi, ws in runs:
            if len(ws) == 1:
                out.append(ws[0])
                continue
            h = ref.thickness / 2
            a = (ref.start[0] + dx * lo, ref.start[1] + dy * lo)
            b = (ref.start[0] + dx * hi, ref.start[1] + dy * hi)
            fp = Polygon(
                [
                    (a[0] - nx * h, a[1] - ny * h),
                    (b[0] - nx * h, b[1] - ny * h),
                    (b[0] + nx * h, b[1] + ny * h),
                    (a[0] + nx * h, a[1] + ny * h),
                ]
            )
            handles = tuple(dict.fromkeys(hh for w in ws for hh in w.handles))
            out.append(WallCandidate(a, b, ref.thickness, fp, "line_pair", handles))
        pending = leftovers + pending
    return out


def _rect(a: P, b: P, thickness: float) -> Polygon:
    L = math.dist(a, b) or 1.0
    dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    nx, ny, h = -dy, dx, thickness / 2
    return Polygon(
        [
            (a[0] - nx * h, a[1] - ny * h),
            (b[0] - nx * h, b[1] - ny * h),
            (b[0] + nx * h, b[1] + ny * h),
            (a[0] + nx * h, a[1] + ny * h),
        ]
    )


def _complete_junctions(walls: list[WallCandidate], tol: Tolerances) -> None:
    """Extend wall ends that stop at another (non-parallel) wall up to that wall's far face.

    Pairing face lines leaves the corner square of an L junction (and the core of a T or X)
    uncovered; a closing cannot fill a convex corner, so we extend the centerlines instead.
    Only extends, never shortens. Works in place on line-pair walls.
    """
    min_sin = math.sin(math.radians(30))
    pairs = [w for w in walls if w.source in ("line_pair", "railing")]
    new_ends: dict[int, list[P]] = {id(w): [w.start, w.end] for w in pairs}
    for w in pairs:
        for k in (0, 1):
            e = w.start if k == 0 else w.end
            d = (-w.direction[0], -w.direction[1]) if k == 0 else w.direction
            best_t = 0.0
            for o in pairs:
                if o is w or (o.source == "railing" and w.source != "railing"):
                    continue  # a full-height wall never grows into a low railing
                ox, oy = o.direction
                cross = d[0] * oy - d[1] * ox
                if abs(cross) < min_sin:
                    continue
                wx, wy = o.start[0] - e[0], o.start[1] - e[1]
                t = (wx * oy - wy * ox) / cross  # along d from e to o's centerline
                u = (wx * d[1] - wy * d[0]) / cross  # along o from o.start
                reach = o.thickness / 2 + w.thickness / 2 + tol.gap_close
                if not (-(o.thickness / 2 + tol.snap) <= t <= reach):
                    continue
                ext = w.thickness / 2 + tol.snap
                if not (-ext <= u <= o.length + ext):
                    continue
                target = t + o.thickness / 2 / abs(cross)
                best_t = max(best_t, target)
            if best_t > 0:
                new_ends[id(w)][k] = (e[0] + d[0] * best_t, e[1] + d[1] * best_t)
                w.joined[k] = True
    for w in pairs:
        a, b = new_ends[id(w)]
        if (a, b) != (w.start, w.end):
            w.start, w.end = a, b
            w.footprint = _rect(a, b, w.thickness)


# ------------------------------------------------------------------ polygons


def _is_thin(poly: Polygon, tol: Tolerances) -> bool:
    return poly.buffer(-(tol.wall_thickness_max / 2 + tol.snap)).is_empty


def _from_polygon(poly: Polygon, source: str, handles: tuple[str, ...]) -> WallCandidate:
    rect = poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)[:4] if isinstance(rect, Polygon) else list(poly.exterior.coords)[:4]
    e1 = (coords[0], coords[1])
    e2 = (coords[1], coords[2])
    long_e, short_e = (e1, e2) if math.dist(*e1) >= math.dist(*e2) else (e2, e1)
    length = math.dist(*long_e) or 1.0
    thickness = poly.area / length
    # centerline: long edge shifted by half the short edge
    sx = (short_e[1][0] - short_e[0][0]) / 2
    sy = (short_e[1][1] - short_e[0][1]) / 2
    a, b = long_e
    if long_e == e1:  # short edge starts at long edge's end: shift towards it
        start, end = (a[0] + sx, a[1] + sy), (b[0] + sx, b[1] + sy)
    else:
        start, end = (a[0] - sx, a[1] - sy), (b[0] - sx, b[1] - sy)
    return WallCandidate(start, end, thickness, poly, source, handles)


def _polygon_walls(drawing: Drawing, tol: Tolerances, issues: Issues) -> list[WallCandidate]:
    out = []
    for item in drawing.polygons.get("walls", []):
        if _is_thin(item.polygon, tol):
            source = "hatch" if item.source == "hatch" else "closed_polyline"
            out.append(_from_polygon(item.polygon, source, (item.handle,)))
        # thick closed polylines: their edges are already in the segments and get paired
    for item in drawing.polygons.get("structure", []):
        out.append(_from_polygon(item.polygon, "structure", (item.handle,)))
    return out


def _railing_walls(drawing: Drawing, cfg: Config, issues: Issues) -> list[WallCandidate]:
    """Railings/parapets drawn with lines: low walls (paired faces, or one line → railing_thickness)."""
    tol = cfg.tolerances
    segs = clean_segments(drawing.segments.get("railings", []), tol, None)
    if not segs:
        return []
    out = _merge_collinear_walls(_pair_lines(segs, tol), tol)
    covered = unary_union([w.footprint for w in out]) if out else Polygon()
    t = cfg.geometry.railing_thickness
    for s in segs:
        if covered.is_empty or not _explained(s, covered, tol):
            out.append(WallCandidate(s.a, s.b, t, _rect(s.a, s.b, t), "railing", s.handles))
    for w in out:
        w.source = "railing"
        w.height = cfg.heights.railing
    return out


# ------------------------------------------------------------------ main


COORD_GRID = 1e-6  # m; removes float noise (near-duplicate vertices break mitre buffers)


def closing(geom, r: float):
    """Morphological closing with square corners, on a 1 µm grid."""
    geom = shapely.set_precision(geom, COORD_GRID)
    return geom.buffer(r, join_style="mitre").buffer(-r, join_style="mitre")


def _explained(seg: CSeg, mask, tol: Tolerances) -> bool:
    outside = seg.line().difference(mask.buffer(tol.snap * 2, join_style="mitre"))
    return outside.length < tol.min_wall_length


def detect_walls(drawing: Drawing, cfg: Config, issues: Issues) -> WallResult:
    tol = cfg.tolerances
    segs = clean_segments(drawing.segments.get("walls", []), tol, issues)
    walls = _merge_collinear_walls(_pair_lines(segs, tol), tol)
    walls += _railing_walls(drawing, cfg, issues)
    _complete_junctions(walls, tol)
    walls += _polygon_walls(drawing, tol, issues)

    r = max(tol.gap_opening_min / 2 - tol.snap, tol.snap)
    mask = closing(unary_union([w.footprint for w in walls]), r) if walls else Polygon()

    # fallback: polygonize line work the mask does not explain and keep the thin faces
    leftover = [s for s in segs if not _explained(s, mask, tol)]
    if leftover:
        faces = [f for f in polygonize(unary_union([s.line() for s in leftover])) if _is_thin(f, tol)]
        for f in faces:
            walls.append(_from_polygon(f, "polygonized", ()))
        if faces:
            mask = closing(unary_union([mask, *faces]), r)
            leftover = [s for s in leftover if not _explained(s, mask, tol)]

    for s in leftover[:MAX_UNPAIRED_ISSUES]:
        mid = ((s.a[0] + s.b[0]) / 2, (s.a[1] + s.b[1]) / 2)
        issues.add(
            IssueCode.UNPAIRED_WALL_LINE,
            f"Línea de muro de {s.length:.2f} m sin pareja paralela (espesor fuera de "
            f"[{tol.wall_thickness_min:.2f}, {tol.wall_thickness_max:.2f}] m o línea suelta); se ignora.",
            location=mid,
            handles=s.handles,
        )
    if len(leftover) > MAX_UNPAIRED_ISSUES:
        issues.add(
            IssueCode.UNPAIRED_WALL_LINE,
            f"… y {len(leftover) - MAX_UNPAIRED_ISSUES} línea(s) de muro más sin pareja.",
        )

    walls.sort(key=lambda w: (round(min(w.start[1], w.end[1]), 3), round(min(w.start[0], w.end[0]), 3)))
    return WallResult(walls=walls, mask=mask, segments=segs)
