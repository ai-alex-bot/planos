"""Clean wall line work: merge collinear duplicates/overlaps, close millimetric gaps.

Order matters:
1. drop degenerate segments;
2. merge collinear segments that overlap or nearly touch (duplicates, split lines, gaps along a line);
3. extend/trim dangling endpoints onto the nearest segment (gaps at L and T junctions).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely import STRtree
from shapely.geometry import LineString, Point

from planos.config import Tolerances
from planos.dxf.reader import Seg
from planos.issues import IssueCode, Issues

P = tuple[float, float]
CONNECTED_EPS = 1e-6
EXTEND_PASSES = 2


@dataclass
class CSeg:
    """Cleaned segment (may come from several DXF entities)."""

    a: P
    b: P
    handles: tuple[str, ...] = ()
    layers: tuple[str, ...] = ()

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)

    @property
    def direction(self) -> P:
        L = self.length
        return ((self.b[0] - self.a[0]) / L, (self.b[1] - self.a[1]) / L)

    def line(self) -> LineString:
        return LineString([self.a, self.b])


@dataclass
class CleanupStats:
    duplicates_removed: int = 0
    duplicate_handles: list[str] = field(default_factory=list)
    gaps_closed: int = 0
    gap_locations: list[P] = field(default_factory=list)


def _canonical(s: Seg | CSeg) -> tuple[float, float]:
    """(angle in [0, pi), signed offset of the infinite line from the origin)."""
    dx, dy = s.b[0] - s.a[0], s.b[1] - s.a[1]
    theta = math.atan2(dy, dx) % math.pi
    nx, ny = -math.sin(theta), math.cos(theta)
    rho = nx * s.a[0] + ny * s.a[1]
    return theta, rho


def _angle_diff(t1: float, t2: float) -> float:
    d = abs(t1 - t2) % math.pi
    return min(d, math.pi - d)


def merge_collinear(segs: list[Seg], tol: Tolerances, stats: CleanupStats) -> list[CSeg]:
    ang = math.radians(tol.angle_deg)
    items = [(s, *_canonical(s)) for s in segs if s.length > tol.snap / 10]
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # group segments lying on the same infinite line (angle and offset within tolerance)
    order = sorted(range(n), key=lambda i: items[i][1])
    thetas = [items[i][1] for i in order]
    for pos, i in enumerate(order):
        si, ti, _ = items[i]
        for pos2 in range(pos + 1, n):
            j = order[pos2]
            if thetas[pos2] - ti > ang:
                break
            sj = items[j][0]
            if _angle_diff(ti, items[j][1]) <= ang and _on_same_line(si, sj, tol.snap):
                parent[find(i)] = find(j)
        # wrap-around: angles near pi are parallel to angles near 0
        if ti > math.pi - ang:
            for pos2 in range(0, n):
                j = order[pos2]
                if thetas[pos2] > ang - (math.pi - ti):
                    break
                if _on_same_line(si, items[j][0], tol.snap):
                    parent[find(i)] = find(j)

    groups: dict[int, list[Seg]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(items[i][0])

    out: list[CSeg] = []
    for members in groups.values():
        ref = max(members, key=lambda s: s.length)
        ux, uy = (ref.b[0] - ref.a[0]) / ref.length, (ref.b[1] - ref.a[1]) / ref.length
        ox, oy = ref.a

        def proj(p: P) -> float:
            return (p[0] - ox) * ux + (p[1] - oy) * uy

        intervals = sorted(
            ((min(proj(s.a), proj(s.b)), max(proj(s.a), proj(s.b)), s) for s in members),
            key=lambda iv: (iv[0], iv[1]),
        )
        cur_lo, cur_hi, cur = intervals[0][0], intervals[0][1], [intervals[0][2]]
        merged: list[tuple[float, float, list[Seg]]] = []
        for lo, hi, s in intervals[1:]:
            if lo <= cur_hi + tol.gap_close:
                if lo < cur_hi - tol.snap:
                    stats.duplicates_removed += 1
                    stats.duplicate_handles.append(s.handle)
                elif lo > cur_hi + CONNECTED_EPS:
                    stats.gaps_closed += 1
                    stats.gap_locations.append((ox + ux * cur_hi, oy + uy * cur_hi))
                cur_hi = max(cur_hi, hi)
                cur.append(s)
            else:
                merged.append((cur_lo, cur_hi, cur))
                cur_lo, cur_hi, cur = lo, hi, [s]
        merged.append((cur_lo, cur_hi, cur))
        for lo, hi, ss in merged:
            out.append(
                CSeg(
                    (ox + ux * lo, oy + uy * lo),
                    (ox + ux * hi, oy + uy * hi),
                    tuple(dict.fromkeys(s.handle for s in ss)),
                    tuple(dict.fromkeys(s.layer for s in ss)),
                )
            )
    return out


def _on_same_line(s1: Seg, s2: Seg, eps: float) -> bool:
    """Both endpoints of the shorter segment lie within eps of the longer one's infinite line."""
    long_, short = (s1, s2) if s1.length >= s2.length else (s2, s1)
    ux, uy = (long_.b[0] - long_.a[0]) / long_.length, (long_.b[1] - long_.a[1]) / long_.length
    for p in (short.a, short.b):
        d = abs((p[0] - long_.a[0]) * uy - (p[1] - long_.a[1]) * ux)
        if d > eps:
            return False
    return True


def _line_intersection(p: P, d: P, q: P, e: P) -> tuple[float, float] | None:
    """Parameters (t, u) with p + t*d == q + u*e, or None if parallel."""
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9:
        return None
    wx, wy = q[0] - p[0], q[1] - p[1]
    t = (wx * e[1] - wy * e[0]) / den
    u = (wx * d[1] - wy * d[0]) / den
    return t, u


def close_junction_gaps(segs: list[CSeg], tol: Tolerances, stats: CleanupStats) -> list[CSeg]:
    """Extend (or trim) dangling endpoints onto the nearest non-parallel segment within gap_close."""
    for _ in range(EXTEND_PASSES):
        lines = [s.line() for s in segs]
        tree = STRtree(lines)
        changed = False
        for i, s in enumerate(segs):
            for end in (0, 1):
                p = s.a if end == 0 else s.b
                pt = Point(p)
                near = [j for j in tree.query(pt.buffer(tol.gap_close)) if j != i]
                if not near:
                    continue
                dists = {j: lines[j].distance(pt) for j in near}
                if min(dists.values()) <= CONNECTED_EPS:
                    continue  # already connected
                # direction pointing outwards from the segment at this end
                d = s.direction if end == 1 else (-s.direction[0], -s.direction[1])
                best = None
                for j in sorted(near, key=dists.get):
                    if dists[j] > tol.gap_close:
                        break
                    o = segs[j]
                    hit = _line_intersection(p, d, o.a, (o.b[0] - o.a[0], o.b[1] - o.a[1]))
                    if hit is None:
                        continue
                    t, u = hit
                    slack = tol.gap_close / o.length
                    if abs(t) <= tol.gap_close * 1.5 and -slack <= u <= 1 + slack and t > -s.length / 2:
                        best = (p[0] + d[0] * t, p[1] + d[1] * t)
                        break
                if best is None:
                    continue
                stats.gaps_closed += 1
                stats.gap_locations.append(best)
                if end == 0:
                    s.a = best
                else:
                    s.b = best
                lines[i] = s.line()
                changed = True
        if not changed:
            break
    return [s for s in segs if s.length > tol.snap / 10]


def clean_segments(segs: list[Seg], tol: Tolerances, issues: Issues | None = None) -> list[CSeg]:
    stats = CleanupStats()
    merged = merge_collinear(segs, tol, stats)
    cleaned = close_junction_gaps(merged, tol, stats)
    if issues is not None:
        if stats.duplicates_removed:
            issues.add(
                IssueCode.DUPLICATE_REMOVED,
                f"Se fusionaron {stats.duplicates_removed} línea(s) de muro duplicadas o superpuestas.",
                handles=stats.duplicate_handles[:20],
            )
        if stats.gaps_closed:
            issues.add(
                IssueCode.GAP_CLOSED,
                f"Se cerraron {stats.gaps_closed} hueco(s) de hasta {tol.gap_close * 100:.0f} cm entre líneas de muro.",
                location=stats.gap_locations[0],
            )
    return cleaned
