"""The messy variant (and transformed copies) must give the same apartment as the clean one,
and every difference must come with a clear issue."""

from __future__ import annotations

import math
from pathlib import Path

import ezdxf
import pytest
from ezdxf.math import Matrix44
from shapely.affinity import affine_transform
from shapely.ops import unary_union

import generate_samples as gs
from planos.config import Config, load_config
from planos.pipeline import build_space
from planos.schema import Space

AREA_TOL = 0.02  # m²
POS_TOL = 0.01  # m


@pytest.fixture(scope="module")
def clean(samples_dir: Path) -> Space:
    return build_space(samples_dir / "depto_2d_limpio.dxf", load_config(samples_dir / "depto_2d_limpio.yaml")).space


@pytest.fixture(scope="module")
def messy(samples_dir: Path) -> Space:
    return build_space(
        samples_dir / "depto_2d_desordenado.dxf", load_config(samples_dir / "depto_2d_desordenado.yaml")
    ).space


def _rooms(space: Space) -> dict[str, tuple]:
    return {r.slug: (r.name, r.net_area_m2, r.is_roofed) for r in space.rooms}


def _assert_same_apartment(a: Space, b: Space, transform=None, kinds_may_differ=frozenset()) -> None:
    """b may be a transformed copy of a: transform maps a's plan coordinates into b's."""
    ra, rb = _rooms(a), _rooms(b)
    assert ra.keys() == rb.keys()
    for slug in ra:
        assert ra[slug][0] == rb[slug][0] and ra[slug][2] == rb[slug][2], slug
        assert ra[slug][1] == pytest.approx(rb[slug][1], abs=AREA_TOL), slug

    # room polygons coincide
    pa = {r.slug: r.polygon.to_shapely() for r in a.rooms}
    pb = {r.slug: r.polygon.to_shapely() for r in b.rooms}
    for slug, poly in pa.items():
        if transform is not None:
            poly = affine_transform(poly, transform)
        assert poly.symmetric_difference(pb[slug]).area < AREA_TOL, slug

    # walls cover the same footprint
    wa = unary_union([w.footprint.to_shapely() for w in a.walls])
    wb = unary_union([w.footprint.to_shapely() for w in b.walls])
    if transform is not None:
        wa = affine_transform(wa, transform)
    assert wa.symmetric_difference(wb).area < 0.05

    # openings: same positions and widths; kinds equal unless listed
    def key(o, t=None):
        x, y = o.center
        if t is not None:
            x, y = t[0] * x + t[1] * y + t[4], t[2] * x + t[3] * y + t[5]
        return x, y

    assert len(a.openings) == len(b.openings)
    for oa in a.openings:
        xa, ya = key(oa, transform)
        ob = min(b.openings, key=lambda o: math.dist(o.center, (xa, ya)))
        assert math.dist(ob.center, (xa, ya)) < POS_TOL, oa.id
        assert ob.width == pytest.approx(oa.width, abs=POS_TOL), oa.id
        assert ob.is_exterior == oa.is_exterior, oa.id
        if oa.kind != ob.kind:
            assert (oa.kind, ob.kind) in kinds_may_differ, (oa.id, oa.kind, ob.kind)

    for attr in ("gross_area_m2", "covered_area_m2", "open_area_m2"):
        assert getattr(a.metadata, attr) == pytest.approx(getattr(b.metadata, attr), abs=0.05), attr

    # adjacency: same pairs of rooms share walls
    def pairs(space: Space) -> set[frozenset]:
        slug = {r.id: r.slug for r in space.rooms}
        out = set()
        for w in space.walls:
            l, r = w.adjacent_room_ids
            if l and r and l != r:
                out.add(frozenset((slug[l], slug[r])))
        return out

    assert pairs(a) == pairs(b)


# ------------------------------------------------------------------ the committed samples


def test_messy_equals_clean(clean: Space, messy: Space) -> None:
    _assert_same_apartment(clean, messy, kinds_may_differ={("door", "passage")})


def test_every_difference_is_reported(clean: Space, messy: Space) -> None:
    assert clean.issues == []
    codes = sorted({i.code.value for i in messy.issues})
    assert codes == ["duplicate_removed", "gap_closed", "opening_inferred"]
    inferred = [i for i in messy.issues if i.code == "opening_inferred"]
    # the three openings drawn without blocks: railing, kitchen passage, window drawn with lines
    assert len(inferred) == 3 and all(i.location for i in inferred)
    # the only kind change (kitchen door -> passage) is one of them
    changed = [o for o in messy.openings if o.kind == "passage"]
    assert len(changed) == 1
    assert any(math.dist(i.location, changed[0].center) < POS_TOL for i in inferred)


def test_messy_without_yaml_explains_what_is_missing(messy_dxf: Path, clean: Space) -> None:
    space = build_space(messy_dxf, Config()).space
    codes = {i.code.value for i in space.issues}
    # units guessed (and right) and the misnamed partitions layer is flagged
    assert space.metadata.source_units == "cm"
    assert "units_assumed" in codes
    assert any("TAB-01" in i.message for i in space.issues if i.code == "layer_unmapped")
    # without partitions rooms merge, and that is visible as multi-label rooms
    assert len(space.rooms) < len(clean.rooms)
    assert "room_multiple_labels" in codes


# ------------------------------------------------------------------ generated variants


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_other_random_messes(tmp_path: Path, samples_dir: Path, clean: Space, seed: int) -> None:
    style = gs.Style(**{**gs.MESSY.__dict__, "seed": seed})
    path = tmp_path / f"messy_{seed}.dxf"
    gs.write_sample(path, [style], extras=True)
    space = build_space(path, load_config(samples_dir / "depto_2d_desordenado.yaml")).space
    _assert_same_apartment(clean, space, kinds_may_differ={("door", "passage")})
    assert not any(i.severity == "error" for i in space.issues)


def _transformed_copy(src: Path, dst: Path, m: Matrix44) -> None:
    doc = ezdxf.readfile(src)
    for e in doc.modelspace():
        e.transform(m)
    doc.saveas(dst)


def _plan_affine(m: Matrix44, scale_to_m: float) -> list[float]:
    """shapely affine params mapping plan meters of the original into the transformed copy."""
    a, b = m.transform_direction((1, 0, 0)), m.transform_direction((0, 1, 0))
    o = m.transform((0, 0, 0))
    return [a.x, b.x, a.y, b.y, o.x * scale_to_m, o.y * scale_to_m]


# The messy sample is drawn in centimeters: matrices are in drawing units.
TRANSFORMS = {
    "rotated_30": Matrix44.z_rotate(math.radians(30)),
    # rotated and moved to UTM-like coordinates (500 km E, 8600 km N)
    "rotated_90_far_away": Matrix44.chain(
        Matrix44.z_rotate(math.radians(90)), Matrix44.translate(500_000 * 100, 8_600_000 * 100, 0)
    ),
}


@pytest.mark.parametrize("name", list(TRANSFORMS))
def test_rotated_and_far_away_plans(tmp_path: Path, samples_dir: Path, messy: Space, name: str) -> None:
    m = TRANSFORMS[name]
    dst = tmp_path / f"{name}.dxf"
    _transformed_copy(samples_dir / "depto_2d_desordenado.dxf", dst, m)
    space = build_space(dst, load_config(samples_dir / "depto_2d_desordenado.yaml")).space
    _assert_same_apartment(messy, space, transform=_plan_affine(m, 0.01))


def test_far_away_plan_glb_is_recentered(tmp_path: Path, samples_dir: Path, messy: Space) -> None:
    import trimesh

    from planos.model3d.build import build_glb

    dst = tmp_path / "far.dxf"
    _transformed_copy(samples_dir / "depto_2d_desordenado.dxf", dst, TRANSFORMS["rotated_90_far_away"])
    space = build_space(dst, load_config(samples_dir / "depto_2d_desordenado.yaml")).space
    data, stats = build_glb(space)
    _, ref = build_glb(messy)
    assert stats.wall_volume_m3 == pytest.approx(ref.wall_volume_m3, rel=0.002)
    path = tmp_path / "far.glb"
    path.write_bytes(data)
    (x0, _, z0), (x1, _, z1) = trimesh.load(path).bounds
    assert max(abs(x0), abs(x1), abs(z0), abs(z1)) < 10  # meters around the origin, not 8.6e6
