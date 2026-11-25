import math

import pytest

from planos.config import Tolerances
from planos.dxf.reader import Seg
from planos.geometry.cleanup import clean_segments
from planos.issues import IssueCode, Issues

TOL = Tolerances()


def S(a, b, h="x") -> Seg:
    return Seg(a, b, "MUROS", h)


def _key(s) -> tuple:
    a, b = sorted([tuple(round(v, 6) for v in s.a), tuple(round(v, 6) for v in s.b)])
    return a, b


def test_exact_and_reversed_duplicates_are_merged() -> None:
    issues = Issues()
    out = clean_segments([S((0, 0), (4, 0), "1"), S((4, 0), (0, 0), "2"), S((0, 0), (4, 0), "3")], TOL, issues)
    assert [_key(s) for s in out] == [((0, 0), (4, 0))]
    assert set(out[0].handles) == {"1", "2", "3"}
    assert issues.by_code(IssueCode.DUPLICATE_REMOVED)


def test_overlapping_split_line_and_mm_gap_along_line() -> None:
    issues = Issues()
    segs = [S((0, 0), (2.4, 0)), S((1.6, 0), (4, 0)), S((4.004, 0), (6, 0))]  # overlap + 4 mm gap
    out = clean_segments(segs, TOL, issues)
    assert [_key(s) for s in out] == [((0, 0), (6, 0))]
    assert issues.by_code(IssueCode.GAP_CLOSED)


def test_nearly_collinear_offset_within_snap_is_merged() -> None:
    out = clean_segments([S((0, 0), (3, 0)), S((2, 0.003), (5, 0.003))], TOL)
    assert len(out) == 1 and out[0].length == pytest.approx(5, abs=1e-3)


def test_parallel_faces_of_a_wall_are_not_merged() -> None:
    out = clean_segments([S((0, 0), (3, 0)), S((0, 0.12), (3, 0.12))], TOL)
    assert len(out) == 2


def test_real_opening_gap_is_not_closed() -> None:
    out = clean_segments([S((0, 0), (2, 0)), S((2.8, 0), (5, 0))], TOL)
    assert len(out) == 2


def test_l_corner_gap_closed_exactly() -> None:
    issues = Issues()
    # both lines stop a few mm short of the corner (0, 0)
    out = clean_segments([S((0.006, 0), (3, 0)), S((0, 0.004), (0, 3))], TOL, issues)
    ends = {tuple(round(v, 9) for v in p) for s in out for p in (s.a, s.b)}
    assert (0.0, 0.0) in ends
    assert issues.by_code(IssueCode.GAP_CLOSED)


def test_t_junction_gap_closed_and_overshoot_trimmed() -> None:
    out = clean_segments([S((0, 0), (5, 0)), S((2, 0.007), (2, 3)), S((4, -0.008), (4, 3))], TOL)
    stems = sorted((s for s in out if abs(s.a[0] - s.b[0]) < 1e-9), key=lambda s: s.a[0])
    assert [round(min(s.a[1], s.b[1]), 9) for s in stems] == [0.0, 0.0]


def test_far_gap_is_left_alone() -> None:
    out = clean_segments([S((0.10, 0), (3, 0)), S((0, 0.10), (0, 3))], TOL)
    ends = {tuple(round(v, 6) for v in p) for s in out for p in (s.a, s.b)}
    assert (0.0, 0.0) not in ends


def test_diagonal_lines() -> None:
    a = (math.cos(math.radians(30)), math.sin(math.radians(30)))
    out = clean_segments([S((0, 0), (3 * a[0], 3 * a[1])), S((2 * a[0], 2 * a[1]), (5 * a[0], 5 * a[1]))], TOL)
    assert len(out) == 1 and out[0].length == pytest.approx(5, abs=1e-6)
