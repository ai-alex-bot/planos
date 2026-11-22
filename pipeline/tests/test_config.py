from pathlib import Path

import pytest
from pydantic import ValidationError

from planos.config import (
    BlockMap,
    Config,
    LayerClassifier,
    LayerMap,
    classify_block,
    load_config,
)


def test_defaults_without_yaml() -> None:
    cfg = load_config(None)
    assert cfg.units == "auto"
    assert cfg.heights.floor_to_ceiling == 2.40
    assert cfg.heights.door_head == 2.10
    assert cfg.heights.window_sill == 1.00
    assert cfg.tolerances.max_room_area == 60.0
    assert cfg.tolerances.area_mismatch_pct == 5.0
    assert cfg.geometry.ceiling is False


@pytest.mark.parametrize(
    "layer, expected",
    [
        ("MUROS", "walls"),
        ("muro", "walls"),
        ("A-WALL", "walls"),
        ("A-WALL-EXT", "walls"),
        ("TABIQUERIA", "walls"),
        ("COLUMNAS", "structure"),
        ("PLACA", "structure"),
        ("S-COL", "structure"),
        ("PUERTAS", "doors"),
        ("VENTANA", "windows"),
        ("MAMPARAS", "windows"),
        ("TEXTOS", "room_labels"),
        ("AMBIENTES", "room_labels"),
        ("COTAS", "ignore"),
        ("MOBILIARIO", "ignore"),
        ("Defpoints", "ignore"),
        ("TAB-01", None),
        ("0", None),
    ],
)
def test_layer_heuristics(layer: str, expected: str | None) -> None:
    assert LayerClassifier(LayerMap()).category(layer) == expected


def test_yaml_category_replaces_heuristic() -> None:
    clf = LayerClassifier(LayerMap(walls=["MUROS", "TAB-*"]))
    assert clf.category("TAB-01") == "walls"
    assert clf.source("TAB-01") == "yaml"
    # walls heuristics no longer apply because the category is explicit
    assert clf.category("A-WALL") is None
    # other categories keep their heuristics
    assert clf.category("PUERTAS") == "doors"
    assert clf.source("PUERTAS") == "heuristic"


def test_load_yaml(tmp_path: Path) -> None:
    p = tmp_path / "m.yaml"
    p.write_text(
        """
units: cm
region: [0, 0, 1200, 900]
layers:
  walls: [MUROS, TAB-01]
declared:
  area_techada_m2: 62.4
heights:
  floor_to_ceiling: 2.5
tolerances:
  max_room_area: 80
""",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.units == "cm"
    assert cfg.region == (0, 0, 1200, 900)
    assert cfg.layers.walls == ["MUROS", "TAB-01"]
    assert cfg.declared is not None and cfg.declared.area_techada_m2 == 62.4
    assert cfg.heights.floor_to_ceiling == 2.5
    assert cfg.heights.door_head == 2.10
    assert cfg.tolerances.max_room_area == 80


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    p = tmp_path / "m.yaml"
    p.write_text("layers:\n  murso: [MUROS]\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(p)


def test_invalid_values() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"region": [10, 0, 0, 5]})
    with pytest.raises(ValidationError):
        Config.model_validate({"heights": {"window_sill": 2.2, "window_head": 2.1}})
    with pytest.raises(ValidationError):
        Config.model_validate({"units": "km"})


@pytest.mark.parametrize(
    "name, layer_cat, expected",
    [
        ("PUERTA-80", "doors", "door"),
        ("P1", "doors", "door"),
        ("MAMPARA-200", "doors", "glass_door"),
        ("MAMP-1", "windows", "glass_door"),
        ("VENTANA-140", "windows", "window"),
        ("BARANDA-290", "windows", "window"),
        ("P-02", None, "door"),
        ("V1", None, "window"),
        ("CAMA", None, None),
        ("PUERTA-80", "ignore", None),  # furniture/ignored layers never produce openings
    ],
)
def test_classify_block(name: str, layer_cat: str | None, expected: str | None) -> None:
    assert classify_block(name, layer_cat, BlockMap()) == expected
