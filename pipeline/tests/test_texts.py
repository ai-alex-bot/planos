import pytest

from planos.geometry.texts import Label, classify, is_roofed, is_room_word, merge_multiline, slugify, unique_slugs


@pytest.mark.parametrize(
    "text, kind, value",
    [
        ("SALA-COMEDOR", "name", None),
        ("DORM. PRINCIPAL", "name", None),
        ("S.H.", "name", None),
        ("SS.HH.", "name", None),
        ("LAVANDERÍA", "name", None),
        ("12.50 m2", "area", 12.5),
        ("12,50 M²", "area", 12.5),
        ("12.50m²", "area", 12.5),
        ("A=12.50", "area", 12.5),
        ("A = 12.5 m2", "area", 12.5),
        ("ÁREA: 18.82 M2", "area", 18.82),
        ("NPT +0.15", "other", None),
        ("N.P.T. ±0.00", "other", None),
        ("N.P.T.+0.13", "other", None),
        ("3.44", "other", None),
        ("+0.15", "other", None),
        ("1.20x2.10", "other", None),
        ("60X60", "other", None),
        ("h=2.10", "other", None),
        ("P1", "other", None),
        ("ESCALA 1/50", "other", None),
        ("-", "other", None),
    ],
)
def test_classify(text: str, kind: str, value: float | None) -> None:
    assert classify(text) == (kind, value)


def test_room_vocabulary() -> None:
    for t in ["DORM. 2", "S.H.", "SS.HH. VISITAS", "COC.", "LAV.", "Baño", "terraza", "HALL", "ESTAR"]:
        assert is_room_word(t), t
    for t in ["PISO PORCELANATO", "CONTRAZÓCALO", "PROYECCIÓN DE VIGA"]:
        assert not is_room_word(t), t


@pytest.mark.parametrize(
    "name, roofed",
    [("TERRAZA", False), ("BALCÓN", False), ("balcon", False), ("PATIO", False), ("JARDÍN", False),
     ("SALA-COMEDOR", True), ("DORM. 1", True), (None, True)],
)
def test_is_roofed(name, roofed) -> None:
    assert is_roofed(name) is roofed


@pytest.mark.parametrize(
    "text, slug",
    [("SALA-COMEDOR", "sala_comedor"), ("DORM. PRINCIPAL", "dorm_principal"), ("S.H.", "s_h"),
     ("SS.HH.", "ss_hh"), ("LAVANDERÍA", "lavanderia"), ("BAÑO", "bano"), ("DORM. 2", "dorm_2"), ("...", "ambiente")],
)
def test_slugify(text: str, slug: str) -> None:
    assert slugify(text) == slug


def test_unique_slugs() -> None:
    assert unique_slugs(["s_h", "sala", "s_h", "dorm", "s_h"]) == ["s_h_1", "sala", "s_h_2", "dorm", "s_h_3"]


def test_merge_multiline_labels() -> None:
    labels = [
        Label("DORM.", (2.0, 2.1), 0.15, "a"),
        Label("PRINCIPAL", (2.0, 1.9), 0.15, "b"),
        Label("COCINA", (6.0, 2.0), 0.15, "c"),  # same height, far away: separate
    ]
    merged = merge_multiline(labels, 0.15)
    assert sorted(l.text for l in merged) == ["COCINA", "DORM. PRINCIPAL"]
