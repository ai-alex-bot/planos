"""Detect disconnected groups of walls (several units, stray geometry) in a drawing."""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString
from shapely.ops import unary_union

from planos.dxf.reader import Drawing
from planos.issues import IssueCode, Issues

# A cluster smaller than this (largest bbox side, m) is stray geometry, not an apartment.
MIN_UNIT_SIZE_M = 2.0


@dataclass
class Cluster:
    bbox_m: tuple[float, float, float, float]
    bbox_drawing: tuple[float, float, float, float]
    n_items: int

    @property
    def size_m(self) -> float:
        x0, y0, x1, y1 = self.bbox_m
        return max(x1 - x0, y1 - y0)


CONTAINED_FRACTION = 0.8


def _bbox_area(b: tuple[float, float, float, float]) -> float:
    return max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)


def _contained(inner: tuple[float, float, float, float], outer: tuple[float, float, float, float]) -> bool:
    ix0, iy0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix1, iy1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = _bbox_area((ix0, iy0, ix1, iy1))
    area = _bbox_area(inner)
    if area == 0:  # degenerate (a single straight wall): test its extent instead
        return ix0 <= ix1 and iy0 <= iy1 and (ix1 - ix0 + iy1 - iy0) >= CONTAINED_FRACTION * (
            inner[2] - inner[0] + inner[3] - inner[1]
        )
    return inter >= CONTAINED_FRACTION * area


def find_clusters(drawing: Drawing, cluster_gap: float) -> list[Cluster]:
    """Groups of wall/structure geometry that belong together (one group per apartment).

    Items closer than ``cluster_gap`` are connected. Door/window blocks and window lines act as
    bridges across their gaps. Groups whose bbox lies inside a larger group's bbox (islands, a
    wall split by an unmarked opening) are merged into it. Sorted by size, largest first; may
    include small stray groups (see ``significant``).
    """
    r = cluster_gap / 2
    walls = []
    for cat in ("walls", "structure"):
        walls += [LineString([s.a, s.b]).buffer(r, cap_style="flat") for s in drawing.segments.get(cat, [])]
        walls += [p.polygon.buffer(r) for p in drawing.polygons.get(cat, [])]
    if not walls:
        return []
    bridges = [i.footprint.buffer(r) for i in drawing.inserts if i.footprint is not None]
    for cat in ("windows", "doors"):
        bridges += [LineString([s.a, s.b]).buffer(r, cap_style="flat") for s in drawing.segments.get(cat, [])]
    merged = unary_union(walls + bridges)
    comps = list(getattr(merged, "geoms", [merged]))

    groups: list[dict] = []
    wall_union = unary_union(walls)
    for comp in comps:
        own = comp.intersection(wall_union)
        if own.is_empty:
            continue  # only bridges (an opening block far from any wall)
        inner = own.buffer(-r)
        x0, y0, x1, y1 = (inner if not inner.is_empty else own).bounds
        n = sum(1 for w in walls if comp.intersects(w.representative_point()))
        groups.append({"bbox": (x0, y0, x1, y1), "n": n})

    groups.sort(key=lambda g: _bbox_area(g["bbox"]) + (g["bbox"][2] - g["bbox"][0]), reverse=True)
    kept: list[dict] = []
    for g in groups:
        host = next((k for k in kept if _contained(g["bbox"], k["bbox"])), None)
        if host is None:
            kept.append(g)
            continue
        hb, gb = host["bbox"], g["bbox"]
        host["bbox"] = (min(hb[0], gb[0]), min(hb[1], gb[1]), max(hb[2], gb[2]), max(hb[3], gb[3]))
        host["n"] += g["n"]

    s = drawing.units.scale_to_m
    clusters = [
        Cluster(g["bbox"], tuple(v / s for v in g["bbox"]), g["n"])  # type: ignore[arg-type]
        for g in kept
    ]
    clusters.sort(key=lambda c: c.size_m, reverse=True)
    return clusters


def significant(clusters: list[Cluster]) -> list[Cluster]:
    return [c for c in clusters if c.size_m >= MIN_UNIT_SIZE_M]


def report_clusters(clusters: list[Cluster], issues: Issues, region_set: bool) -> None:
    units = significant(clusters)
    if len(units) < 2:
        return
    lines = []
    for i, c in enumerate(units, 1):
        x0, y0, x1, y1 = c.bbox_drawing
        lines.append(f"  {i}. region: [{x0:.6g}, {y0:.6g}, {x1:.6g}, {y1:.6g}]  ({c.size_m:.1f} m)")
    hint = "" if region_set else " Usa 'region' en el YAML para elegir una (unidades del dibujo, agrega un margen):"
    issues.add(
        IssueCode.MULTIPLE_UNITS_DETECTED,
        f"Se detectaron {len(units)} grupos de muros desconectados (¿varias unidades, o un muro "
        f"interrumpido?).{hint}\n" + "\n".join(lines),
        bbox=units[0].bbox_m,
    )
