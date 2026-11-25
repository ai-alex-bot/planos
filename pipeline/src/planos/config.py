"""Project mapping config (YAML) with defaults and layer/block heuristics.

Every value has a default, so an empty YAML (or no YAML at all) is valid. When a layer category is
defined in the YAML it fully replaces the heuristic for that category.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

LayerCategory = Literal["walls", "structure", "doors", "windows", "room_labels", "room_separators", "ignore"]
LAYER_CATEGORIES: tuple[LayerCategory, ...] = (
    "walls",
    "structure",
    "doors",
    "windows",
    "room_labels",
    "room_separators",
    "ignore",
)

# Case-insensitive regexes matched against the whole layer name.
DEFAULT_LAYER_PATTERNS: dict[LayerCategory, list[str]] = {
    "walls": [r"MUROS?", r"WALLS?", r"A-WALL.*", r"TABIQUE(RIA|S)?", r"ALBA[ÑN]ILER[IÍ]A", r"MUROS?[-_ ].*"],
    "structure": [r"COLUMNAS?", r"PLACAS?", r"ESTRUCTURAS?", r"CONCRETO", r"S-COL.*", r"COLUMNAS?[-_ ].*"],
    "doors": [r"PUERTAS?", r"DOORS?", r"A-DOOR.*", r"PUERTAS?[-_ ].*"],
    "windows": [r"VENTANAS?", r"WINDOWS?", r"A-GLAZ.*", r"MAMPARAS?", r"VENTANAS?[-_ ].*"],
    "room_labels": [r"TEXTOS?", r"AMBIENTES?", r"A-AREA-IDEN.*", r"NOMBRES?", r"ROOMS?"],
    "room_separators": [r"LIMITES?[-_ ]AMBIENTES?", r"SEPARADOR(ES)?"],
    "ignore": [
        r"COTAS?",
        r"DIM.*",
        r"EJES?",
        r"MOBILIARIO",
        r"MUEBLES?",
        r"MARCO",
        r"R[OÓ]TULO",
        r"DEFPOINTS",
        r"ACHURADO",
        r"NPT",
    ],
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LayerMap(_Strict):
    """Explicit layer names (glob patterns allowed) per category. None → use heuristics."""

    walls: list[str] | None = None
    structure: list[str] | None = None
    doors: list[str] | None = None
    windows: list[str] | None = None
    room_labels: list[str] | None = None
    room_separators: list[str] | None = None
    ignore: list[str] | None = None


class BlockMap(_Strict):
    """Block name glob patterns (case-insensitive), used together with layers."""

    doors: list[str] = Field(default_factory=lambda: ["PUERTA*", "P-*", "P[0-9]*", "DOOR*"])
    windows: list[str] = Field(default_factory=lambda: ["VENT*", "V-*", "V[0-9]*", "WINDOW*", "BARANDA*"])
    glass_doors: list[str] = Field(default_factory=lambda: ["MAMP*"])


class DeclaredAreas(_Strict):
    area_techada_m2: float | None = Field(default=None, gt=0)
    area_libre_m2: float | None = Field(default=None, ge=0)


class Heights(_Strict):
    floor_to_ceiling: float = Field(default=2.40, gt=0)
    door_head: float = Field(default=2.10, gt=0)
    window_sill: float = Field(default=1.00, ge=0)
    window_head: float = Field(default=2.10, gt=0)

    @model_validator(mode="after")
    def _check(self) -> Heights:
        if self.window_sill >= self.window_head:
            raise ValueError("window_sill debe ser menor que window_head")
        if max(self.door_head, self.window_head) > self.floor_to_ceiling:
            raise ValueError("door_head/window_head no pueden superar floor_to_ceiling")
        return self


class Tolerances(_Strict):
    """All lengths in meters."""

    snap: float = Field(default=0.01, gt=0)
    gap_close: float = Field(default=0.03, gt=0)
    angle_deg: float = Field(default=1.0, gt=0)
    wall_thickness_min: float = Field(default=0.07, gt=0)
    wall_thickness_max: float = Field(default=0.40, gt=0)
    min_wall_length: float = Field(default=0.10, gt=0)  # shorter overlaps are not walls (e.g. jambs)
    gap_opening_min: float = Field(default=0.40, gt=0)
    gap_opening_max: float = Field(default=4.00, gt=0)
    cluster_gap: float = Field(default=0.50, gt=0)
    arc_flatten: float = Field(default=0.01, gt=0)
    min_void_area: float = Field(default=0.05, ge=0)  # smaller enclosed voids are drawing artifacts
    min_room_area: float = Field(default=1.5, ge=0)
    max_room_area: float = Field(default=60.0, gt=0)
    area_mismatch_pct: float = Field(default=5.0, ge=0)


class Geometry(_Strict):
    ceiling: bool = False
    opening_cut_margin: float = Field(default=0.05, ge=0)  # extra depth of opening cutters (m)


class Config(_Strict):
    units: Literal["auto", "m", "cm", "mm"] = "auto"
    region: tuple[float, float, float, float] | None = None  # drawing units: xmin, ymin, xmax, ymax
    layers: LayerMap = Field(default_factory=LayerMap)
    blocks: BlockMap = Field(default_factory=BlockMap)
    declared: DeclaredAreas | None = None
    heights: Heights = Field(default_factory=Heights)
    tolerances: Tolerances = Field(default_factory=Tolerances)
    geometry: Geometry = Field(default_factory=Geometry)

    @model_validator(mode="after")
    def _check_region(self) -> Config:
        if self.region is not None:
            xmin, ymin, xmax, ymax = self.region
            if xmin >= xmax or ymin >= ymax:
                raise ValueError("region debe ser [xmin, ymin, xmax, ymax] con min < max")
        return self


def load_config(path: Path | str | None) -> Config:
    """Load a mapping YAML. ``None`` returns the defaults."""
    if path is None:
        return Config()
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: el YAML debe ser un mapa (clave: valor)")
    return Config.model_validate(data)


def _glob_match(name: str, patterns: list[str]) -> bool:
    up = name.upper()
    return any(fnmatch.fnmatchcase(up, p.upper()) for p in patterns)


class LayerClassifier:
    """Maps layer names to categories: explicit YAML lists first, then heuristics."""

    def __init__(self, layers: LayerMap) -> None:
        self.explicit: dict[LayerCategory, list[str]] = {}
        self.heuristic: dict[LayerCategory, list[re.Pattern[str]]] = {}
        for cat in LAYER_CATEGORIES:
            names = getattr(layers, cat)
            if names is not None:
                self.explicit[cat] = names
            else:
                self.heuristic[cat] = [re.compile(p, re.IGNORECASE) for p in DEFAULT_LAYER_PATTERNS[cat]]
        self._cache: dict[str, LayerCategory | None] = {}

    def category(self, layer: str) -> LayerCategory | None:
        if layer in self._cache:
            return self._cache[layer]
        result: LayerCategory | None = None
        for cat, names in self.explicit.items():
            if _glob_match(layer, names):
                result = cat
                break
        if result is None:
            stripped = layer.strip()
            for cat, patterns in self.heuristic.items():
                if any(p.fullmatch(stripped) for p in patterns):
                    result = cat
                    break
        self._cache[layer] = result
        return result

    def source(self, layer: str) -> Literal["yaml", "heuristic", "unmapped"]:
        cat = self.category(layer)
        if cat is None:
            return "unmapped"
        return "yaml" if cat in self.explicit else "heuristic"


OpeningKindFromBlock = Literal["door", "window", "glass_door"]


def classify_block(name: str, layer_category: LayerCategory | None, blocks: BlockMap) -> OpeningKindFromBlock | None:
    """Opening kind of an INSERT from its block name and layer category (None = not an opening).

    Glass-door names win (a mampara may sit on the doors or windows layer); then the layer;
    then the block name patterns.
    """
    if _glob_match(name, blocks.glass_doors):
        return "glass_door"
    if layer_category == "doors":
        return "door"
    if layer_category == "windows":
        return "window"
    if layer_category in (None, "room_labels"):
        if _glob_match(name, blocks.doors):
            return "door"
        if _glob_match(name, blocks.windows):
            return "window"
    return None
