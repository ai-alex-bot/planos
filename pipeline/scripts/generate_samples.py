"""Generate synthetic DXF samples of a typical Lima 2-bedroom apartment.

The plan is described as an ideal model (wall centerlines + thickness, openings, columns and room
labels). From that model we derive:

* the drawing (wall face lines with gaps at openings, door/window blocks, labels, ...), and
* the ground truth used by the tests (room net areas, opening counts per kind).

Three samples are produced:

* ``depto_2d_limpio.dxf``       - clean drawing in meters.
* ``depto_2d_desordenado.dxf``  - same apartment drawn in centimeters with real-world mess.
* ``planta_2_unidades.dxf``     - two clean apartments side by side.

Usage (from ``pipeline/``)::

    uv run python scripts/generate_samples.py            # writes into ../samples
    uv run python scripts/generate_samples.py --out DIR
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import ezdxf
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

P = tuple[float, float]
OpeningKind = Literal["door", "window", "glass_door", "passage", "railing"]

# --------------------------------------------------------------------------------------------
# Ideal plan model (meters)
# --------------------------------------------------------------------------------------------

EXT_T = 0.20  # exterior wall thickness
INT_T = 0.12  # interior partition (tabique) thickness
TERRACE_T = 0.15
COLUMN = 0.25


@dataclass(frozen=True)
class WallSpec:
    a: P
    b: P
    t: float
    interior: bool = False  # partitions: drawn on a different layer in the messy sample

    @property
    def line(self) -> LineString:
        return LineString([self.a, self.b])

    @property
    def direction(self) -> tuple[float, float]:
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        n = math.hypot(dx, dy)
        return dx / n, dy / n

    def rect(self) -> Polygon:
        # square caps extend t/2 past each end so corners and T-junctions overlap
        return self.line.buffer(self.t / 2, cap_style="square", join_style="mitre")


@dataclass(frozen=True)
class OpeningSpec:
    kind: OpeningKind
    wall: int  # index into WALLS
    along: float  # distance from wall.a to the opening center
    width: float
    # how the messy sample draws it: "block" (default) or "lines" (window drawn with lines) or
    # "none" (bare gap, e.g. a passage or an unmarked railing)
    messy: Literal["block", "lines", "none"] = "block"
    messy_kind: OpeningKind | None = None  # kind the messy drawing intends (if different)
    flip: bool = False  # door swing side
    clean_block: str | None = None  # override block name in the clean sample


@dataclass(frozen=True)
class RoomSpec:
    name: str
    label: P
    area_text: bool = False  # messy: write an area text below the name
    npt_text: str | None = None  # messy: write a level text (NPT) inside


WALLS: list[WallSpec] = [
    # exterior envelope
    WallSpec((0, 0), (10, 0), EXT_T),  # 0 facade (sala/terrace boundary on the right)
    WallSpec((10, -1.6), (10, 7), EXT_T),  # 1 right
    WallSpec((10, 7), (0, 7), EXT_T),  # 2 back
    WallSpec((0, 7), (0, 0), EXT_T),  # 3 left
    # terrace (recessed balcony) side wall + front parapet line
    WallSpec((6.4, 0), (6.4, -1.6), TERRACE_T),  # 4
    WallSpec((6.4, -1.6), (10, -1.6), TERRACE_T),  # 5
    # interior partitions
    WallSpec((3.6, 0), (3.6, 7), INT_T, True),  # 6 bedrooms | middle strip
    WallSpec((0, 3.8), (3.6, 3.8), INT_T, True),  # 7 dorm principal | dorm 2
    WallSpec((5.4, 0), (5.4, 7), INT_T, True),  # 8 middle strip | right zone
    WallSpec((5.4, 4.4), (10, 4.4), INT_T, True),  # 9 sala | cocina + lav
    WallSpec((7.4, 4.4), (7.4, 7), INT_T, True),  # 10 lav | cocina
    WallSpec((3.6, 2.0), (5.4, 2.0), INT_T, True),  # 11 s.h.1 | hall
    WallSpec((3.6, 5.2), (5.4, 5.2), INT_T, True),  # 12 hall | s.h.2
]

OPENINGS: list[OpeningSpec] = [
    # doors
    OpeningSpec("door", 6, 3.0, 0.80),  # hall -> dorm principal
    OpeningSpec("door", 6, 4.6, 0.80, flip=True),  # hall -> dorm 2
    OpeningSpec("door", 6, 1.15, 0.70),  # dorm principal -> s.h.1
    OpeningSpec("door", 12, 0.85, 0.70),  # hall -> s.h.2
    OpeningSpec("door", 8, 3.45, 0.90),  # hall -> sala
    OpeningSpec("door", 10, 1.25, 0.70, flip=True),  # cocina -> lavanderia
    OpeningSpec("door", 1, 5.25, 0.90),  # main entrance (x=10, y=3.65)
    # cocina <-> sala: door in the clean drawing, bare gap (passage) in the messy one
    OpeningSpec("door", 9, 3.4, 1.00, messy="none", messy_kind="passage"),
    # glass door sala -> terrace
    OpeningSpec("glass_door", 0, 8.2, 2.00),
    # windows
    OpeningSpec("window", 0, 1.7, 1.40),  # dorm principal (facade)
    OpeningSpec("window", 0, 4.5, 0.60),  # s.h.1 (facade)
    OpeningSpec("window", 2, 8.2, 1.40),  # dorm 2 (back), along from (10,7)
    OpeningSpec("window", 2, 5.5, 0.60),  # s.h.2 (back)
    OpeningSpec("window", 2, 1.8, 1.20, messy="lines"),  # cocina (back): lines only in messy
    OpeningSpec("window", 2, 3.6, 0.80),  # lavanderia (back)
    OpeningSpec("window", 1, 3.2, 1.60),  # sala (right facade, y=1.6)
    # terrace open side: railing (parapet, nothing above). Block in clean, bare gap in messy
    OpeningSpec("railing", 5, 1.8, 2.90, messy="none", clean_block="BARANDA-290"),
]

COLUMNS: list[P] = [(0, 0), (0, 7), (10, 7), (10, -1.6), (6.4, -1.6), (3.6, 0), (5.4, 7), (10, 0)]

ROOMS: list[RoomSpec] = [
    RoomSpec("DORM. PRINCIPAL", (1.8, 1.9), area_text=True),
    RoomSpec("DORM. 2", (1.8, 5.4), area_text=True),
    RoomSpec("S.H.", (4.5, 1.0)),
    RoomSpec("HALL", (4.5, 3.6), npt_text="N.P.T. +0.15"),
    RoomSpec("S.H.", (4.5, 6.1)),
    RoomSpec("SALA-COMEDOR", (7.6, 2.4), area_text=True, npt_text="NPT +0.15"),
    RoomSpec("COCINA", (8.7, 5.7), area_text=True),
    RoomSpec("LAVANDERÍA", (6.4, 5.7)),
    RoomSpec("TERRAZA", (8.2, -0.8), npt_text="NPT +0.13"),
]


# --------------------------------------------------------------------------------------------
# Geometry derived from the model
# --------------------------------------------------------------------------------------------


def opening_center(o: OpeningSpec) -> P:
    w = WALLS[o.wall]
    dx, dy = w.direction
    return (w.a[0] + dx * o.along, w.a[1] + dy * o.along)


def opening_cut(o: OpeningSpec) -> Polygon:
    """Rectangle that removes the opening from the wall (slightly deeper than the wall)."""
    w = WALLS[o.wall]
    cx, cy = opening_center(o)
    dx, dy = w.direction
    nx, ny = -dy, dx
    hw, hd = o.width / 2, w.t / 2 + 0.05
    pts = [
        (cx - dx * hw - nx * hd, cy - dy * hw - ny * hd),
        (cx + dx * hw - nx * hd, cy + dy * hw - ny * hd),
        (cx + dx * hw + nx * hd, cy + dy * hw + ny * hd),
        (cx - dx * hw + nx * hd, cy - dy * hw + ny * hd),
    ]
    return Polygon(pts)


def column_poly(c: P) -> Polygon:
    h = COLUMN / 2
    return box(c[0] - h, c[1] - h, c[0] + h, c[1] + h)


def solid_mask() -> Polygon:
    """Walls + columns without openings: its holes are the rooms."""
    return unary_union([w.rect() for w in WALLS] + [column_poly(c) for c in COLUMNS])


def ground_truth() -> dict:
    mask = solid_mask()
    assert mask.geom_type == "Polygon", mask.geom_type
    holes = [Polygon(r) for r in mask.interiors]
    rooms = []
    for spec in ROOMS:
        pt = Point(spec.label)
        matches = [h for h in holes if h.contains(pt)]
        assert len(matches) == 1, spec
        rooms.append({"name": spec.name, "net_area_m2": round(matches[0].area, 4), "label": spec.label})
    assert len(holes) == len(ROOMS), (len(holes), len(ROOMS))
    return {"rooms": rooms, "gross_outline_area_m2": round(Polygon(mask.exterior).area, 4)}


def opening_counts(messy: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    for o in OPENINGS:
        kind = (o.messy_kind or o.kind) if messy else o.kind
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def wall_face_segments() -> list[tuple[P, P, bool]]:
    """Face lines of the walls as a draftsman draws them.

    Returns (start, end, is_interior_partition). Walls stop at columns and at openings (with
    jamb lines closing each side of the gap).
    """
    walls_only = unary_union([w.rect() for w in WALLS])
    cuts = unary_union([opening_cut(o) for o in OPENINGS])
    cols = unary_union([column_poly(c) for c in COLUMNS])
    drawn = walls_only.difference(cuts).difference(cols)
    rings = []
    for poly in getattr(drawn, "geoms", [drawn]):
        poly = poly.simplify(1e-9)
        rings.append(poly.exterior)
        rings.extend(poly.interiors)
    cols_boundary = cols.boundary
    segs: list[tuple[P, P, bool]] = []
    for ring in rings:
        coords = list(ring.coords)
        for p, q in zip(coords[:-1], coords[1:]):
            seg = LineString([p, q])
            if seg.length < 1e-6:
                continue
            # skip edges lying on a column outline: the column is drawn by itself
            if seg.difference(cols_boundary.buffer(1e-6)).length < 1e-6:
                continue
            mid = seg.interpolate(0.5, normalized=True)
            nearest = min(WALLS, key=lambda w: w.line.distance(mid))
            segs.append(((round(p[0], 6), round(p[1], 6)), (round(q[0], 6), round(q[1], 6)), nearest.interior))
    return segs


# --------------------------------------------------------------------------------------------
# DXF writing
# --------------------------------------------------------------------------------------------


@dataclass
class Style:
    """Everything that differs between the clean and the messy drawing."""

    scale: float  # drawing units per meter
    insunits: int  # $INSUNITS header value
    walls_layer: str
    partitions_layer: str
    columns_as_hatch: bool
    text_height: float  # meters
    use_mtext: bool
    unit_blocks: bool  # one scaled unit block per kind instead of real-size blocks
    mess: bool
    offset: P = (0.0, 0.0)  # meters
    seed: int = 7
    extra: dict = field(default_factory=dict)


CLEAN = Style(
    scale=1.0,
    insunits=6,
    walls_layer="MUROS",
    partitions_layer="MUROS",
    columns_as_hatch=False,
    text_height=0.15,
    use_mtext=False,
    unit_blocks=False,
    mess=False,
)

MESSY = Style(
    scale=100.0,
    insunits=0,  # unitless: the pipeline must infer (or be told) centimeters
    walls_layer="MUROS",
    partitions_layer="TAB-01",  # badly named layer: heuristics will not recognise it
    columns_as_hatch=True,
    text_height=0.20,
    use_mtext=True,
    unit_blocks=True,
    mess=True,
)


class Writer:
    def __init__(self, style: Style, doc: ezdxf.document.Drawing | None = None) -> None:
        self.s = style
        self.doc = doc or ezdxf.new("R2010", setup=True)
        self.doc.header["$INSUNITS"] = style.insunits
        self.msp = self.doc.modelspace()
        self.rng = random.Random(style.seed)
        for name, color in [
            (style.walls_layer, 7),
            (style.partitions_layer, 7),
            ("COLUMNAS", 8),
            ("PUERTAS", 3),
            ("VENTANAS", 5),
            ("TEXTOS", 2),
        ]:
            if name not in self.doc.layers:
                self.doc.layers.add(name, color=color)
        if style.mess:
            for name, color in [("COTAS", 1), ("MOBILIARIO", 9), ("MARCO", 7), ("ROTULO", 7)]:
                self.doc.layers.add(name, color=color)

    # coordinates ------------------------------------------------------------------------
    def xy(self, p: P) -> tuple[float, float]:
        return ((p[0] + self.s.offset[0]) * self.s.scale, (p[1] + self.s.offset[1]) * self.s.scale)

    def d(self, v: float) -> float:
        return v * self.s.scale

    # blocks -----------------------------------------------------------------------------
    def _door_block(self, name: str, w: float) -> None:
        """Hinge at origin, wall along +X, leaf open along +Y, swing arc."""
        if name in self.doc.blocks:
            return
        b = self.doc.blocks.new(name=name)
        b.add_line((0, 0), (0, w))
        b.add_arc((0, 0), w, 0, 90)

    def _panel_block(self, name: str, w: float, depth: float, lines: int) -> None:
        """Window/glass door/railing: centered at origin, wall along +X."""
        if name in self.doc.blocks:
            return
        b = self.doc.blocks.new(name=name)
        hw, hd = w / 2, depth / 2
        b.add_lwpolyline([(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)], close=True)
        for i in range(1, lines + 1):
            y = -hd + i * depth / (lines + 1)
            b.add_line((-hw, y), (hw, y))

    def ensure_blocks(self) -> None:
        if self.s.unit_blocks:
            self._door_block("P1", 1.0)
            self._panel_block("V1", 1.0, 1.0, 2)
            self._panel_block("MAMP-1", 1.0, 1.0, 1)

    # entities ---------------------------------------------------------------------------
    def line(self, a: P, b: P, layer: str) -> None:
        self.msp.add_line(self.xy(a), self.xy(b), dxfattribs={"layer": layer})

    def text(self, s: str, p: P, layer: str = "TEXTOS", height: float | None = None) -> None:
        h = self.d(height or self.s.text_height)
        if self.s.use_mtext:
            m = self.msp.add_mtext(s, dxfattribs={"layer": layer, "char_height": h})
            m.set_location(self.xy(p), attachment_point=MTextEntityAlignment.MIDDLE_CENTER)
        else:
            t = self.msp.add_text(s, height=h, dxfattribs={"layer": layer})
            t.set_placement(self.xy(p), align=TextEntityAlignment.MIDDLE_CENTER)

    def opening(self, o: OpeningSpec) -> None:
        w = WALLS[o.wall]
        cx, cy = opening_center(o)
        dx, dy = w.direction
        rot = math.degrees(math.atan2(dy, dx))
        mode = o.messy if self.s.mess else "block"
        if mode == "none":
            return
        if mode == "lines":  # window drawn with plain lines across the gap
            nx, ny = -dy, dx
            hw = o.width / 2
            for off in (-w.t / 2, 0.0, w.t / 2):
                a = (cx - dx * hw + nx * off, cy - dy * hw + ny * off)
                b = (cx + dx * hw + nx * off, cy + dy * hw + ny * off)
                self.line(a, b, "VENTANAS")
            return

        if o.kind == "door":
            # hinge at one jamb; the leaf opens to the left of the wall direction (or right if flip)
            hinge = (cx - dx * o.width / 2, cy - dy * o.width / 2)
            if self.s.unit_blocks:
                name, xs = "P1", self.d(o.width)
            else:
                name, xs = f"PUERTA-{round(o.width * 100)}", 1.0
                self._door_block(name, o.width)
            self.msp.add_blockref(
                name,
                self.xy(hinge),
                dxfattribs={"layer": "PUERTAS", "rotation": rot, "xscale": xs, "yscale": -xs if o.flip else xs},
            )
            return

        layer = "VENTANAS"
        if self.s.unit_blocks:
            name = "MAMP-1" if o.kind == "glass_door" else "V1"
            xs, ys = self.d(o.width), self.d(w.t)
        else:
            prefix = "MAMPARA" if o.kind == "glass_door" else "VENTANA"
            name = o.clean_block or f"{prefix}-{round(o.width * 100)}"
            self._panel_block(name, o.width, w.t, 1 if o.kind == "glass_door" else 2)
            xs = ys = 1.0
        if o.kind == "glass_door":
            layer = "PUERTAS"
        self.msp.add_blockref(name, self.xy((cx, cy)), dxfattribs={"layer": layer, "rotation": rot, "xscale": xs, "yscale": ys})

    def column(self, c: P) -> None:
        h = COLUMN / 2
        pts = [self.xy((c[0] + sx * h, c[1] + sy * h)) for sx, sy in [(-1, -1), (1, -1), (1, 1), (-1, 1)]]
        if self.s.columns_as_hatch:
            hatch = self.msp.add_hatch(color=8, dxfattribs={"layer": "COLUMNAS"})
            hatch.set_solid_fill()
            hatch.paths.add_polyline_path(pts, is_closed=True)
        else:
            self.msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "COLUMNAS"})


def _mess_up(segs: list[tuple[P, P, bool]], rng: random.Random) -> list[tuple[P, P, bool]]:
    """Duplicates, overlapping splits and millimetric gaps."""
    out: list[tuple[P, P, bool]] = []
    for a, b, interior in segs:
        length = math.dist(a, b)
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        r = rng.random()
        if r < 0.12:  # exact duplicate
            out += [(a, b, interior), (b, a, interior)]
        elif r < 0.24 and length > 1.0:  # split into two overlapping pieces
            m1 = (a[0] + ux * length * 0.6, a[1] + uy * length * 0.6)
            m2 = (a[0] + ux * length * 0.4, a[1] + uy * length * 0.4)
            out += [(a, m1, interior), (m2, b, interior)]
        elif r < 0.50 and length > 0.3:  # shorten one end by 2-8 mm
            g = rng.uniform(0.002, 0.008)
            if rng.random() < 0.5:
                out.append(((a[0] + ux * g, a[1] + uy * g), b, interior))
            else:
                out.append((a, (b[0] - ux * g, b[1] - uy * g), interior))
        else:
            out.append((a, b, interior))
    return out


def draw_apartment(w: Writer) -> None:
    s = w.s
    w.ensure_blocks()
    segs = wall_face_segments()
    if s.mess:
        segs = _mess_up(segs, w.rng)
    for a, b, interior in segs:
        w.line(a, b, s.partitions_layer if interior else s.walls_layer)
    for c in COLUMNS:
        w.column(c)
    for o in OPENINGS:
        w.opening(o)

    truth = {r["name"] + str(r["label"]): r["net_area_m2"] for r in ground_truth()["rooms"]}
    for room in ROOMS:
        name = room.name
        if s.use_mtext and room.name.startswith("DORM. PRINCIPAL"):
            name = r"{\fArial|b1|i0;DORM. PRINCIPAL}"  # inline formatting codes
        w.text(name, room.label)
        if s.mess and room.area_text:
            area = truth[room.name + str(room.label)]
            txt = f"A={area:.2f}" if room.name.startswith("DORM") else f"{area:.2f} m²"
            w.text(txt, (room.label[0], room.label[1] - 0.35), height=0.12)
        if s.mess and room.npt_text:
            w.text(room.npt_text, (room.label[0], room.label[1] + 0.35), height=0.10)


def draw_mess_extras(w: Writer) -> None:
    """Dimensions, furniture, a stray number, frame and title block."""
    msp = w.msp
    # dimensions (rendered into anonymous blocks with their own texts)
    dim_style = {
        "dimtxt": w.d(0.12),
        "dimasz": w.d(0.08),
        "dimexo": w.d(0.05),
        "dimexe": w.d(0.05),
        "dimgap": w.d(0.03),
        "dimlfac": 1.0 / w.s.scale,  # show meters
        "dimdec": 2,
        "dimclrd": 1,
        "dimclre": 1,
        "dimclrt": 1,
    }
    for p1, p2, dist in [((0, 7), (10, 7), 0.8), ((0, 7), (0, 0), -0.8), ((0, 0), (3.6, 0), -1.0)]:
        dim = msp.add_aligned_dim(
            p1=w.xy(p1), p2=w.xy(p2), distance=w.d(dist), override=dim_style, dxfattribs={"layer": "COTAS"}
        )
        dim.render()
    w.text("3.44", (1.8, 0.4), layer="COTAS", height=0.10)  # loose number inside a room
    # furniture: beds and a sofa
    for x0, y0, x1, y1 in [(0.6, 0.6, 2.2, 2.6), (0.5, 4.3, 1.5, 6.3), (6.0, 0.6, 8.2, 1.5)]:
        pts = [w.xy(p) for p in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "MOBILIARIO"})
    # frame + title block (far larger than the unit)
    frame = [w.xy(p) for p in [(-3, -5), (19, -5), (19, 10), (-3, 10)]]
    msp.add_lwpolyline(frame, close=True, dxfattribs={"layer": "MARCO"})
    tb = [w.xy(p) for p in [(12, -5), (19, -5), (19, -2), (12, -2)]]
    msp.add_lwpolyline(tb, close=True, dxfattribs={"layer": "ROTULO"})
    for i, t in enumerate(["PROYECTO: EDIFICIO DEMO", "TIPOLOGÍA: 2 DORMITORIOS", "ESCALA 1/50", "LÁMINA A-01"]):
        w.text(t, (15.5, -2.5 - i * 0.6), layer="ROTULO", height=0.25)


def write_sample(path: Path, styles: list[Style], extras: bool = False) -> None:
    doc = None
    for st in styles:
        wr = Writer(st, doc)
        doc = wr.doc
        draw_apartment(wr)
        if extras:
            draw_mess_extras(wr)
    assert doc is not None
    doc.saveas(path)


UNIT_2_OFFSET: P = (13.0, 0.0)  # second unit 3 m to the right of the first (corridor between)


def generate(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    write_sample(out / "depto_2d_limpio.dxf", [CLEAN])
    write_sample(out / "depto_2d_desordenado.dxf", [MESSY], extras=True)
    second = Style(**{**CLEAN.__dict__, "offset": UNIT_2_OFFSET})
    write_sample(out / "planta_2_unidades.dxf", [CLEAN, second])

    truth = ground_truth()
    outline = Polygon(solid_mask().exterior)
    minx, miny, maxx, maxy = outline.bounds
    expected = {
        "_comment": "Ground truth generated by pipeline/scripts/generate_samples.py (meters).",
        "rooms": truth["rooms"],
        "gross_outline_area_m2": truth["gross_outline_area_m2"],
        "unit_bbox_m": [minx, miny, maxx, maxy],
        "files": {
            "depto_2d_limpio.dxf": {"units": "m", "insunits": CLEAN.insunits, "openings": opening_counts(False)},
            "depto_2d_desordenado.dxf": {
                "units": "cm",
                "insunits": MESSY.insunits,
                "openings": opening_counts(True),
            },
            "planta_2_unidades.dxf": {
                "units": "m",
                "insunits": CLEAN.insunits,
                "units_bboxes_m": [
                    [minx, miny, maxx, maxy],
                    [minx + UNIT_2_OFFSET[0], miny + UNIT_2_OFFSET[1], maxx + UNIT_2_OFFSET[0], maxy + UNIT_2_OFFSET[1]],
                ],
            },
        },
    }
    (out / "expected.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "samples")
    args = parser.parse_args()
    exp = generate(args.out)
    total = sum(r["net_area_m2"] for r in exp["rooms"])
    print(f"Samples written to {args.out}")
    for r in exp["rooms"]:
        print(f"  {r['name']:<16} {r['net_area_m2']:7.2f} m2")
    print(f"  {'TOTAL':<16} {total:7.2f} m2")


if __name__ == "__main__":
    main()
