import json
import math
from pathlib import Path

import ezdxf
import pytest

from planos.config import Config, DeclaredAreas, load_config
from planos.dxf.reader import read_dxf
from planos.geometry.openings import detect_openings
from planos.geometry.rooms import assign_adjacency, detect_rooms, unit_areas
from planos.geometry.walls import detect_walls
from planos.issues import IssueCode, Issues


def _pipeline(path: Path, cfg: Config):
    issues = Issues()
    d = read_dxf(path, cfg, issues)
    w = detect_walls(d, cfg, issues)
    o = detect_openings(d, w, cfg, issues)
    rooms = detect_rooms(d, o.closed_mask, cfg, issues)
    return d, w, o, rooms, issues


@pytest.fixture(scope="module")
def expected(samples_dir: Path) -> dict:
    return json.loads((samples_dir / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sample", ["depto_2d_limpio", "depto_2d_desordenado"])
def test_sample_rooms(samples_dir: Path, expected: dict, sample: str) -> None:
    _, _, _, rooms, issues = _pipeline(samples_dir / f"{sample}.dxf", load_config(samples_dir / f"{sample}.yaml"))
    got = sorted((r.name, round(r.net_area_m2, 2)) for r in rooms)
    want = sorted((r["name"], round(r["net_area_m2"], 2)) for r in expected["rooms"])
    assert got == want
    assert sorted(r.slug for r in rooms) == sorted(
        ["dorm_principal", "dorm_2", "s_h_1", "s_h_2", "hall", "sala_comedor", "cocina", "lavanderia", "terraza"]
    )
    assert [r.slug for r in rooms if r.is_outdoor] == ["terraza"]
    assert [r.slug for r in rooms if not r.has_ceiling] == ["terraza"]
    for code in (IssueCode.ROOM_WITHOUT_NAME, IssueCode.ROOM_MULTIPLE_LABELS, IssueCode.ROOM_AREA_MISMATCH,
                 IssueCode.SUSPICIOUS_AREA):
        assert not issues.by_code(code), code
    if sample.endswith("desordenado"):
        declared = {r.slug: r.declared_area_m2 for r in rooms if r.declared_area_m2}
        assert set(declared) == {"dorm_principal", "dorm_2", "sala_comedor", "cocina"}
        assert declared["sala_comedor"] == pytest.approx(18.82)


def test_unit_areas_clean_vs_messy(samples_dir: Path) -> None:
    results = []
    for sample in ("depto_2d_limpio", "depto_2d_desordenado"):
        cfg = load_config(samples_dir / f"{sample}.yaml")
        _, _, o, rooms, issues = _pipeline(samples_dir / f"{sample}.dxf", cfg)
        results.append(unit_areas(rooms, o.closed_mask, cfg, issues))
    a, b = results
    assert a.gross_area_m2 == pytest.approx(b.gross_area_m2, abs=0.05)
    assert a.covered_area_m2 == pytest.approx(63.36, abs=0.02)
    assert a.open_area_m2 == pytest.approx(4.88, abs=0.01)
    # roofed area includes walls: between the net roofed area and the whole outline
    assert a.covered_area_m2 < a.gross_area_m2 < a.covered_area_m2 + 12


def test_declared_area_mismatch(clean_dxf: Path) -> None:
    cfg = Config(units="m", declared=DeclaredAreas(area_techada_m2=60.0, area_libre_m2=4.9))
    _, _, o, rooms, issues = _pipeline(clean_dxf, cfg)
    unit_areas(rooms, o.closed_mask, cfg, issues)
    (issue,) = issues.by_code(IssueCode.AREA_MISMATCH)
    assert "techada" in issue.message  # 4.9 vs 4.88 is within 5 %, 60 vs ~73.6 is not


def test_wall_adjacency(clean_dxf: Path) -> None:
    _, w, o, rooms, _ = _pipeline(clean_dxf, Config(units="m"))
    by_id = {r.id: r.slug for r in rooms}
    adj = assign_adjacency(w.walls, rooms)

    def sides(x0, y0, x1, y1):
        for wall in w.walls:
            mid = ((wall.start[0] + wall.end[0]) / 2, (wall.start[1] + wall.end[1]) / 2)
            if wall.source == "line_pair" and math.dist(mid, ((x0 + x1) / 2, (y0 + y1) / 2)) < 0.3:
                return {by_id.get(s) for s in adj[id(wall)]}
        raise AssertionError("wall not found")

    assert sides(0, 3.8, 3.6, 3.8) == {"dorm_principal", "dorm_2"}  # partition between bedrooms
    assert sides(7.4, 6.0, 7.4, 7.1) == {"lavanderia", "cocina"}  # piece above the door
    assert sides(5.34, 4.4, 8.3, 4.4) == {"sala_comedor", "lavanderia"}  # mostly along the laundry
    assert sides(10.0, 4.1, 10.0, 6.875) == {"cocina", None}  # exterior wall: outside is None


# ------------------------------------------------------------------ synthetic cases

T = 0.15


def _wall(msp, a, b, t=T, layer="MUROS"):
    L = math.dist(a, b)
    dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    nx, ny = -dy * t / 2, dx * t / 2
    pts = [(a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny), (b[0] + nx, b[1] + ny), (a[0] + nx, a[1] + ny)]
    for p, q in zip(pts, pts[1:] + pts[:1]):
        msp.add_line(p, q, dxfattribs={"layer": layer})


def _open_plan(tmp_path: Path, texts: list[tuple[str, tuple[float, float]]], separator: bool = False,
               layer: str = "TEXTOS") -> Path:
    """6 x 4 box (one face) with the given texts inside."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    h = T / 2
    _wall(msp, (-h, 0), (6 + h, 0))
    _wall(msp, (-h, 4), (6 + h, 4))
    _wall(msp, (0, h), (0, 4 - h))
    _wall(msp, (6, h), (6, 4 - h))
    for s, p in texts:
        msp.add_text(s, height=0.15, dxfattribs={"layer": layer}).set_placement(p)
    if separator:
        msp.add_line((3.5, 0), (3.5, 4), dxfattribs={"layer": "LIMITE-AMBIENTE"})
    path = tmp_path / "plan.dxf"
    doc.saveas(path)
    return path


def test_open_kitchen_two_labels_then_separator(tmp_path: Path) -> None:
    texts = [("SALA-COMEDOR", (1.5, 2)), ("COCINA", (5, 2)), ("PISO PORCELANATO", (1.5, 1))]
    _, _, _, rooms, issues = _pipeline(_open_plan(tmp_path, texts), Config(units="m"))
    (room,) = rooms
    assert room.name in {"SALA-COMEDOR", "COCINA"} and room.other_names
    (issue,) = issues.by_code(IssueCode.ROOM_MULTIPLE_LABELS)
    assert "PISO" not in issue.message  # notes do not count as names
    assert "room_separators" in issue.message

    _, _, _, rooms2, issues2 = _pipeline(_open_plan(tmp_path, texts, separator=True), Config(units="m"))
    assert sorted(r.name for r in rooms2) == ["COCINA", "SALA-COMEDOR"]
    assert not issues2.by_code(IssueCode.ROOM_MULTIPLE_LABELS)
    assert sum(r.net_area_m2 for r in rooms2) == pytest.approx((6 - T) * (4 - T), abs=1e-6)


def test_multiline_label_and_area_text(tmp_path: Path) -> None:
    texts = [("DORM.", (3, 2.1)), ("PRINCIPAL", (3, 1.9)), ("A=20.00", (3, 1.5)), ("NPT +0.15", (3, 1.2))]
    _, _, _, rooms, issues = _pipeline(_open_plan(tmp_path, texts), Config(units="m"))
    (room,) = rooms
    assert room.name == "DORM. PRINCIPAL" and room.slug == "dorm_principal"
    assert room.declared_area_m2 == 20.0
    (mismatch,) = issues.by_code(IssueCode.ROOM_AREA_MISMATCH)  # real area is 22.52 m2
    assert "20.00" in mismatch.message


def test_room_without_name_and_fallback_to_any_layer(tmp_path: Path) -> None:
    _, _, _, rooms, issues = _pipeline(_open_plan(tmp_path, []), Config(units="m"))
    assert rooms[0].name is None and rooms[0].slug == "ambiente"
    assert issues.by_code(IssueCode.ROOM_WITHOUT_NAME)
    # texts on an unmapped layer are used when no room_labels layer exists
    _, _, _, rooms2, _ = _pipeline(_open_plan(tmp_path, [("ESTUDIO", (3, 2))], layer="CAPA1"), Config(units="m"))
    assert rooms2[0].name == "ESTUDIO"


def test_suspicious_area(tmp_path: Path) -> None:
    cfg = Config(units="m", tolerances={"max_room_area": 20})
    _, _, _, _, issues = _pipeline(_open_plan(tmp_path, [("SALA", (3, 2))]), cfg)
    assert issues.by_code(IssueCode.SUSPICIOUS_AREA)
