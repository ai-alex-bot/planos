"""Read a DXF into flat, metric primitives grouped by layer category.

Blocks are exploded recursively (except door/window blocks, kept as inserts), arcs/splines are
flattened, hatches become polygons, everything is scaled to meters and clipped to ``region``.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import reduce
from pathlib import Path
from typing import Iterable

import ezdxf
from ezdxf import bbox as ezbbox
from ezdxf import path as ezpath
from ezdxf.entities import DXFGraphic, Insert
from ezdxf.math import Matrix44
from shapely.geometry import Point, Polygon, box
from shapely.validation import make_valid

from planos.config import Config, LayerCategory, LayerClassifier, OpeningKindFromBlock, classify_block
from planos.dxf.units import UnitInfo, detect_units
from planos.issues import IssueCode, Issues

P = tuple[float, float]

MAX_BLOCK_DEPTH = 8
CURVED = {"LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "SOLID", "TRACE"}
TEXTS = {"TEXT", "MTEXT", "ATTRIB"}
SKIPPED = {"DIMENSION", "ARC_DIMENSION", "POINT", "ATTDEF", "VIEWPORT", "LEADER", "MLEADER", "MULTILEADER",
           "XLINE", "RAY", "IMAGE", "WIPEOUT", "OLE2FRAME", "TOLERANCE"}
GEOMETRY_CATEGORIES: set[LayerCategory] = {"walls", "structure", "doors", "windows", "room_separators"}


@dataclass(frozen=True)
class Seg:
    a: P
    b: P
    layer: str
    handle: str

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)


@dataclass
class PolyItem:
    polygon: Polygon
    layer: str
    handle: str
    source: str  # "closed_polyline" | "hatch" | "solid" | "circle" | ...


@dataclass
class InsertItem:
    name: str
    layer: str
    handle: str
    kind: OpeningKindFromBlock
    position: P  # insertion point (m)
    rotation_deg: float
    xscale: float
    yscale: float
    x_dir: P  # world direction of the block's local +X axis (unit vector)
    footprint: Polygon | None  # transformed local extents (m)
    local_size: tuple[float, float] | None  # block extents along local X/Y, scaled (m)


@dataclass
class TextItem:
    text: str  # plain text (formatting codes removed)
    raw: str
    position: P  # center of the text (m)
    layer: str
    category: LayerCategory | None
    handle: str
    height: float  # m


@dataclass
class Drawing:
    path: Path
    sha256: str
    dxf_version: str
    insunits: int
    units: UnitInfo
    region_m: tuple[float, float, float, float] | None
    segments: dict[LayerCategory, list[Seg]] = field(default_factory=lambda: defaultdict(list))
    polygons: dict[LayerCategory, list[PolyItem]] = field(default_factory=lambda: defaultdict(list))
    inserts: list[InsertItem] = field(default_factory=list)
    texts: list[TextItem] = field(default_factory=list)

    def wall_segments(self) -> list[Seg]:
        return self.segments.get("walls", [])

    def bounds(self, categories: Iterable[LayerCategory] = ("walls", "structure")) -> tuple[float, float, float, float] | None:
        xs: list[float] = []
        ys: list[float] = []
        for cat in categories:
            for s in self.segments.get(cat, []):
                xs += [s.a[0], s.b[0]]
                ys += [s.a[1], s.b[1]]
            for p in self.polygons.get(cat, []):
                x0, y0, x1, y1 = p.polygon.bounds
                xs += [x0, x1]
                ys += [y0, y1]
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _effective_layer(e: DXFGraphic, parent_layer: str | None) -> str:
    layer = e.dxf.get("layer", "0")
    if layer == "0" and parent_layer:
        return parent_layer  # BYBLOCK-style inheritance of layer 0
    return layer


def _is_xref(doc: ezdxf.document.Drawing, name: str) -> bool:
    block = doc.blocks.get(name)
    return block is not None and bool(block.block_record.is_xref)


# --------------------------------------------------------------------------------------------
# Pass 1: wall extent in drawing units (for unit detection)
# --------------------------------------------------------------------------------------------


def _wall_extent(msp, clf: LayerClassifier, region: tuple[float, float, float, float] | None) -> float | None:
    region_box = box(*region) if region else None
    picked = []
    for e in msp:
        if e.dxftype() in SKIPPED or e.dxftype() in TEXTS:
            continue
        if clf.category(e.dxf.get("layer", "0")) in ("walls", "structure"):
            picked.append(e)
    if not picked:
        return None
    if region_box is None:
        ext = ezbbox.extents(picked, fast=True)
        return max(ext.size.x, ext.size.y) if ext.has_data else None
    acc = ezbbox.BoundingBox()
    for e in picked:
        eb = ezbbox.extents([e], fast=True)
        if eb.has_data and region_box.intersects(box(eb.extmin.x, eb.extmin.y, eb.extmax.x, eb.extmax.y)):
            acc.extend([eb.extmin, eb.extmax])
    return max(acc.size.x, acc.size.y) if acc.has_data else None


# --------------------------------------------------------------------------------------------
# Pass 2: flatten
# --------------------------------------------------------------------------------------------


class _Flattener:
    def __init__(self, doc, cfg: Config, clf: LayerClassifier, scale: float, issues: Issues, drawing: Drawing) -> None:
        self.doc = doc
        self.cfg = cfg
        self.clf = clf
        self.s = scale
        self.issues = issues
        self.d = drawing
        self.flatten_dist = cfg.tolerances.arc_flatten / scale  # drawing units
        self.region = box(*drawing.region_m) if drawing.region_m else None
        self.block_extents: dict[str, ezbbox.BoundingBox] = {}
        self.unsupported: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.unmapped: Counter[str] = Counter()
        self.xrefs: dict[str, list[tuple[str, P]]] = defaultdict(list)

    # helpers --------------------------------------------------------------------------
    def pt(self, v) -> P:
        return (v[0] * self.s, v[1] * self.s)

    def inside(self, p: P) -> bool:
        return self.region is None or self.region.covers(Point(p))

    def add_seg(self, cat: LayerCategory, a: P, b: P, layer: str, handle: str) -> None:
        if math.dist(a, b) < 1e-9:
            return
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if self.inside(mid):
            self.d.segments[cat].append(Seg(a, b, layer, handle))

    def add_poly(self, cat: LayerCategory, pts: list[P], layer: str, handle: str, source: str) -> None:
        if len(pts) < 3:
            return
        poly = make_valid(Polygon(pts))
        for g in getattr(poly, "geoms", [poly]):
            if isinstance(g, Polygon) and g.area > 1e-9 and self.inside(g.representative_point().coords[0]):
                self.d.polygons[cat].append(PolyItem(g, layer, handle, source))

    # entities -------------------------------------------------------------------------
    def walk(self, entities: Iterable[DXFGraphic], parent_layer: str | None = None, depth: int = 0,
             parent_handle: str | None = None) -> None:
        for e in entities:
            t = e.dxftype()
            layer = _effective_layer(e, parent_layer)
            handle = parent_handle or e.dxf.get("handle", "")
            if t == "INSERT":
                self.insert(e, layer, depth, handle)  # type: ignore[arg-type]
            elif t in TEXTS:
                self.text(e, layer, handle)
            elif t in SKIPPED:
                continue
            else:
                self.geometry(e, layer, handle)

    def geometry(self, e: DXFGraphic, layer: str, handle: str) -> None:
        cat = self.clf.category(layer)
        if cat is None:
            self.unmapped[layer] += 1
            return
        if cat not in GEOMETRY_CATEGORIES:
            return
        t = e.dxftype()
        if t == "LINE":
            self.add_seg(cat, self.pt(e.dxf.start), self.pt(e.dxf.end), layer, handle)
        elif t == "HATCH":
            self.hatch(e, cat, layer, handle)
        elif t in CURVED:
            self.curve(e, cat, layer, handle)
        else:
            self.unsupported[(layer, t)].append(handle)

    def curve(self, e: DXFGraphic, cat: LayerCategory, layer: str, handle: str) -> None:
        try:
            p = ezpath.make_path(e)
        except (TypeError, ValueError):
            self.unsupported[(layer, e.dxftype())].append(handle)
            return
        pts = [self.pt(v) for v in p.flattening(self.flatten_dist)]
        if len(pts) < 2:
            return
        for a, b in zip(pts[:-1], pts[1:]):
            self.add_seg(cat, a, b, layer, handle)
        t = e.dxftype()
        closed = (
            (t == "LWPOLYLINE" and e.closed)
            or (t == "POLYLINE" and e.is_closed)
            or t in ("CIRCLE", "SOLID", "TRACE")
            or (t == "SPLINE" and e.closed)
            or (t == "ELLIPSE" and math.isclose(abs(e.dxf.end_param - e.dxf.start_param), math.tau))
            or (len(pts) > 3 and math.dist(pts[0], pts[-1]) < 1e-9)
        )
        if closed:
            if math.dist(pts[0], pts[-1]) > 1e-9:
                self.add_seg(cat, pts[-1], pts[0], layer, handle)
            source = {"CIRCLE": "circle", "SOLID": "solid", "TRACE": "solid"}.get(t, "closed_polyline")
            self.add_poly(cat, pts, layer, handle, source)

    def hatch(self, e: DXFGraphic, cat: LayerCategory, layer: str, handle: str) -> None:
        polys = []
        for p in ezpath.from_hatch(e):
            pts = [self.pt(v) for v in p.flattening(self.flatten_dist)]
            if len(pts) >= 3:
                poly = make_valid(Polygon(pts))
                if not poly.is_empty:
                    polys.append(poly)
        if not polys:
            return
        merged = reduce(lambda a, b: a.symmetric_difference(b), polys)  # even-odd fill rule
        for g in getattr(merged, "geoms", [merged]):
            if isinstance(g, Polygon) and g.area > 1e-9 and self.inside(g.representative_point().coords[0]):
                self.d.polygons[cat].append(PolyItem(g, layer, handle, "hatch"))

    def text(self, e: DXFGraphic, layer: str, handle: str) -> None:
        t = e.dxftype()
        raw = e.text if t == "MTEXT" else e.dxf.get("text", "")
        plain = e.plain_text().strip()
        if not plain:
            return
        ext = ezbbox.extents([e])
        if ext.has_data:
            c = ext.center
            pos = self.pt((c.x, c.y))
        else:
            pos = self.pt(e.dxf.insert)
        height = (e.dxf.get("char_height", 0) if t == "MTEXT" else e.dxf.get("height", 0)) * self.s
        if not self.inside(pos):
            return
        self.d.texts.append(TextItem(" ".join(plain.split()), raw, pos, layer, self.clf.category(layer), handle, height))

    def insert(self, e: Insert, layer: str, depth: int, handle: str) -> None:
        name = e.dxf.name
        if _is_xref(self.doc, name):
            self.xrefs[name].append((handle, self.pt(e.dxf.insert)))
            return
        if self.doc.blocks.get(name) is None:
            return
        if e.mcount > 1:  # MINSERT arrays
            for sub in e.multi_insert():
                self.insert(sub, layer, depth, handle)
            return
        cat = self.clf.category(layer)
        kind = classify_block(name, cat, self.cfg.blocks)
        if kind is not None:
            self.opening_insert(e, name, layer, handle, kind)
        elif cat == "ignore":
            return
        elif depth >= MAX_BLOCK_DEPTH:
            self.unsupported[(layer, f"INSERT>{MAX_BLOCK_DEPTH}")].append(handle)
        else:
            self.walk(e.virtual_entities(), parent_layer=layer, depth=depth + 1, parent_handle=handle)
        for attrib in e.attribs:
            self.text(attrib, _effective_layer(attrib, layer), handle)

    def _local_extents(self, name: str) -> ezbbox.BoundingBox:
        if name not in self.block_extents:
            block = self.doc.blocks.get(name)
            ents = [x for x in block if x.dxftype() not in ("ATTDEF",)]
            self.block_extents[name] = ezbbox.extents(ents, fast=True)
        return self.block_extents[name]

    def opening_insert(self, e: Insert, name: str, layer: str, handle: str, kind: OpeningKindFromBlock) -> None:
        pos = self.pt(e.dxf.insert)
        if not self.inside(pos):
            return
        m: Matrix44 = e.matrix44()
        ux = m.transform_direction((1, 0, 0))
        n = math.hypot(ux.x, ux.y) or 1.0
        ext = self._local_extents(name)
        footprint = None
        local_size = None
        if ext.has_data:
            x0, y0, x1, y1 = ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y
            corners = [self.pt(m.transform((x, y, 0))) for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
            footprint = make_valid(Polygon(corners))
            sx, sy = abs(e.dxf.get("xscale", 1.0)), abs(e.dxf.get("yscale", 1.0))
            local_size = ((x1 - x0) * sx * self.s, (y1 - y0) * sy * self.s)
        self.d.inserts.append(
            InsertItem(
                name=name,
                layer=layer,
                handle=handle,
                kind=kind,
                position=pos,
                rotation_deg=math.degrees(math.atan2(ux.y, ux.x)),
                xscale=e.dxf.get("xscale", 1.0),
                yscale=e.dxf.get("yscale", 1.0),
                x_dir=(ux.x / n, ux.y / n),
                footprint=footprint if isinstance(footprint, Polygon) else None,
                local_size=local_size,
            )
        )

    # issues ---------------------------------------------------------------------------
    def report(self) -> None:
        for name, refs in self.xrefs.items():
            self.issues.add(
                IssueCode.XREF_UNRESOLVED,
                f"El plano referencia el XREF '{name}' ({len(refs)} vez/veces), que no está incrustado: "
                "falta geometría. Usa 'Bind' en AutoCAD o exporta el XREF dentro del DXF.",
                location=refs[0][1],
                handles=[h for h, _ in refs][:20],
            )
        for (layer, t), handles in sorted(self.unsupported.items()):
            self.issues.add(
                IssueCode.ENTITY_UNSUPPORTED,
                f"{len(handles)} entidad(es) {t} en la capa '{layer}' no se pudieron procesar.",
                handles=handles[:20],
            )
        for layer, count in sorted(self.unmapped.items()):
            self.issues.add(
                IssueCode.LAYER_UNMAPPED,
                f"La capa '{layer}' tiene {count} entidad(es) geométricas y no está mapeada "
                "(ni en el YAML ni por heurística); se ignora.",
            )


def read_dxf(path: Path | str, cfg: Config, issues: Issues) -> Drawing:
    path = Path(path)
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    clf = LayerClassifier(cfg.layers)
    insunits = int(doc.header.get("$INSUNITS", 0) or 0)

    extent = _wall_extent(msp, clf, cfg.region)
    units = detect_units(insunits, extent, cfg.units)
    if units.warning:
        issues.add(IssueCode.UNITS_ASSUMED, units.warning)

    region_m = tuple(v * units.scale_to_m for v in cfg.region) if cfg.region else None
    drawing = Drawing(
        path=path,
        sha256=file_sha256(path),
        dxf_version=doc.dxfversion,
        insunits=insunits,
        units=units,
        region_m=region_m,  # type: ignore[arg-type]
    )
    fl = _Flattener(doc, cfg, clf, units.scale_to_m, issues, drawing)
    fl.walk(msp)
    fl.report()

    if not drawing.segments.get("walls") and not drawing.polygons.get("walls"):
        where = " dentro de 'region'" if cfg.region else ""
        issues.add(
            IssueCode.REGION_EMPTY if cfg.region else IssueCode.NO_WALLS,
            f"No se encontró geometría de muros{where}. Revisa 'layers.walls' en el YAML "
            "(usa 'planos inspect' para ver las capas).",
        )
    return drawing
