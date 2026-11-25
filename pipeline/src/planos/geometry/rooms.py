"""Rooms: interior faces of the closed wall mask, named by the texts inside them."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import polylabel, split, unary_union

from planos.config import Config
from planos.dxf.reader import Drawing, TextItem
from planos.geometry.texts import Label, classify, is_roofed, is_room_word, merge_multiline, normalize, slugify, unique_slugs
from planos.geometry.walls import WallCandidate
from planos.issues import IssueCode, Issues

P = tuple[float, float]
DEFAULT_TEXT_HEIGHT = 0.15  # m, when a text has no height
SIDE_PROBE = 0.05  # m, width of the strip sampled on each side of a wall


@dataclass
class RoomCandidate:
    id: str
    polygon: Polygon
    name: str | None
    slug: str
    net_area_m2: float
    declared_area_m2: float | None
    is_roofed: bool
    label_point: P
    label_handle: str | None
    other_names: list[str] = field(default_factory=list)


@dataclass
class UnitAreas:
    gross_area_m2: float  # área techada (calculada), incluye muros
    covered_area_m2: float  # suma del área útil de ambientes techados
    open_area_m2: float  # área libre: suma del área útil de ambientes sin techar


def _faces(closed_mask, separators: list[LineString], tol) -> list[Polygon]:
    polys = list(getattr(closed_mask, "geoms", [closed_mask]))
    faces = [Polygon(h) for p in polys for h in p.interiors]
    faces = [f for f in faces if f.area >= tol.min_void_area]
    if not separators:
        return faces
    out: list[Polygon] = []
    for f in faces:
        pieces = [f]
        for line in separators:
            nxt = []
            for piece in pieces:
                if line.intersects(piece):
                    nxt += [g for g in split(piece, line).geoms if isinstance(g, Polygon)]
                else:
                    nxt.append(piece)
            pieces = nxt
        out += [p for p in pieces if p.area >= tol.min_void_area]
    return out


def _extend(line: LineString, d: float) -> LineString:
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    L = math.dist((x0, y0), (x1, y1)) or 1.0
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    return LineString([(x0 - ux * d, y0 - uy * d), (x1 + ux * d, y1 + uy * d)])


def _candidate_texts(drawing: Drawing) -> list[TextItem]:
    labelled = [t for t in drawing.texts if t.category == "room_labels"]
    if labelled:
        return labelled
    return [t for t in drawing.texts if t.category != "ignore"]


def detect_rooms(
    drawing: Drawing, closed_mask: Polygon | MultiPolygon, cfg: Config, issues: Issues
) -> list[RoomCandidate]:
    tol = cfg.tolerances
    seps = [_extend(LineString([s.a, s.b]), tol.wall_thickness_max) for s in drawing.segments.get("room_separators", [])]
    faces = _faces(closed_mask, seps, tol)
    faces.sort(key=lambda f: (-round(f.centroid.y, 2), round(f.centroid.x, 2)))
    texts = _candidate_texts(drawing)

    rooms_raw = []
    for f in faces:
        inside = [t for t in texts if f.contains(Point(t.position))]
        names: list[Label] = []
        areas: list[float] = []
        for t in inside:
            kind, value = classify(t.text)
            if kind == "area":
                areas.append(value)  # type: ignore[arg-type]
            elif kind == "name":
                names.append(Label(normalize(t.text), t.position, t.height, t.handle))
        names = merge_multiline(names, DEFAULT_TEXT_HEIGHT)
        known = [n for n in names if is_room_word(n.text)]
        if known:
            names = known  # notes like "PISO PORCELANATO" do not compete with real names
        names.sort(key=lambda n: (-(n.height or 0), f.centroid.distance(Point(n.position))))
        rooms_raw.append((f, names, areas))

    bases = []
    for f, names, _ in rooms_raw:
        bases.append(slugify(" ".join(n.text for n in names[:1])) if names else "ambiente")
    slugs = unique_slugs(bases)

    rooms: list[RoomCandidate] = []
    for i, ((f, names, areas), slug) in enumerate(zip(rooms_raw, slugs), 1):
        rid = f"room_{i:02d}"
        area = f.area
        name = names[0].text if names else None
        if names:
            label_point, handle = names[0].position, names[0].handle
        else:
            lp = polylabel(f, tolerance=0.05)
            label_point, handle = (lp.x, lp.y), None
        room = RoomCandidate(
            id=rid,
            polygon=f,
            name=name,
            slug=slug,
            net_area_m2=area,
            declared_area_m2=areas[0] if areas else None,
            is_roofed=is_roofed(name),
            label_point=label_point,
            label_handle=handle,
            other_names=[n.text for n in names[1:]],
        )
        rooms.append(room)
        where = f"'{name}'" if name else f"{rid}"
        if not names:
            issues.add(
                IssueCode.ROOM_WITHOUT_NAME,
                f"Ambiente de {area:.2f} m² sin texto de nombre dentro (se llama '{slug}').",
                location=label_point,
            )
        if len(names) > 1:
            issues.add(
                IssueCode.ROOM_MULTIPLE_LABELS,
                f"El ambiente {where} contiene varios nombres ({', '.join(n.text for n in names)}): "
                "probablemente falta un muro o un vano. Se usa el primero; si son ambientes distintos, "
                "dibuja una línea en una capa de 'room_separators'.",
                location=label_point,
                handles=[n.handle for n in names],
            )
        if room.declared_area_m2 is not None and room.declared_area_m2 > 0:
            diff = abs(area - room.declared_area_m2) / room.declared_area_m2 * 100
            if diff > tol.area_mismatch_pct:
                issues.add(
                    IssueCode.ROOM_AREA_MISMATCH,
                    f"El ambiente {where} dice {room.declared_area_m2:.2f} m² en el plano pero mide "
                    f"{area:.2f} m² ({diff:.1f} % de diferencia).",
                    location=label_point,
                )
        if area < tol.min_room_area or area > tol.max_room_area:
            issues.add(
                IssueCode.SUSPICIOUS_AREA,
                f"El ambiente {where} mide {area:.2f} m², fuera del rango esperado "
                f"[{tol.min_room_area:g}, {tol.max_room_area:g}] m².",
                location=label_point,
            )
    return rooms


def assign_adjacency(walls: list[WallCandidate], rooms: list[RoomCandidate]) -> dict[int, tuple[str | None, str | None]]:
    """For each wall (by id()), the room on its left and right side looking start→end."""
    out: dict[int, tuple[str | None, str | None]] = {}
    for w in walls:
        if w.length == 0:
            out[id(w)] = (None, None)
            continue
        dx, dy = w.direction
        nx, ny = -dy, dx
        sides = []
        for sign in (1, -1):
            o1, o2 = sign * (w.thickness / 2), sign * (w.thickness / 2 + SIDE_PROBE)
            strip = Polygon(
                [
                    (w.start[0] + nx * o1, w.start[1] + ny * o1),
                    (w.end[0] + nx * o1, w.end[1] + ny * o1),
                    (w.end[0] + nx * o2, w.end[1] + ny * o2),
                    (w.start[0] + nx * o2, w.start[1] + ny * o2),
                ]
            )
            best, best_area = None, 0.0
            for r in rooms:
                a = r.polygon.intersection(strip).area
                if a > best_area:
                    best, best_area = r.id, a
            sides.append(best if best_area > strip.area * 0.05 else None)
        out[id(w)] = (sides[0], sides[1])
    return out


def unit_areas(rooms: list[RoomCandidate], closed_mask, cfg: Config, issues: Issues) -> UnitAreas:
    tol = cfg.tolerances
    polys = list(getattr(closed_mask, "geoms", [closed_mask]))
    shell = unary_union([Polygon(p.exterior) for p in polys])
    roofed = unary_union([r.polygon for r in rooms if r.is_roofed])
    open_ = unary_union([r.polygon for r in rooms if not r.is_roofed])
    covered = sum(r.net_area_m2 for r in rooms if r.is_roofed)
    open_area = sum(r.net_area_m2 for r in rooms if not r.is_roofed)
    if open_.is_empty:
        gross_geom = shell
    else:
        # walls that only bound unroofed spaces (terrace parapets) are not roofed area
        reach = tol.wall_thickness_max
        open_walls = open_.buffer(reach, join_style="mitre").difference(roofed.buffer(reach, join_style="mitre"))
        gross_geom = shell.difference(open_).difference(open_walls)
    gross = gross_geom.area

    declared = cfg.declared
    if declared is not None:
        for label, decl, calc in (
            ("techada", declared.area_techada_m2, gross),
            ("libre", declared.area_libre_m2, open_area),
        ):
            if decl is None:
                continue
            base = decl if decl > 0 else 1.0
            diff = abs(calc - decl) / base * 100
            if diff > tol.area_mismatch_pct:
                issues.add(
                    IssueCode.AREA_MISMATCH,
                    f"Área {label} declarada {decl:.2f} m² vs calculada {calc:.2f} m² ({diff:.1f} % de diferencia).",
                )
    return UnitAreas(gross_area_m2=gross, covered_area_m2=covered, open_area_m2=open_area)
