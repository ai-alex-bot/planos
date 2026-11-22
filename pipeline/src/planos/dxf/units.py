"""Unit detection: YAML override > $INSUNITS (sanity-checked) > extent heuristic."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

SourceUnits = Literal["m", "cm", "mm", "in", "ft", "unknown"]
UnitsOrigin = Literal["insunits", "config", "heuristic"]

INSUNITS_TO_M: dict[int, tuple[SourceUnits, float]] = {
    1: ("in", 0.0254),
    2: ("ft", 0.3048),
    4: ("mm", 0.001),
    5: ("cm", 0.01),
    6: ("m", 1.0),
}
NAME_TO_M: dict[str, float] = {"m": 1.0, "cm": 0.01, "mm": 0.001}

# Plausible size (largest side, meters) of the walls of one or a few apartments.
PLAUSIBLE_MIN_M = 2.0
PLAUSIBLE_MAX_M = 200.0
TYPICAL_SIZE_M = 12.0


@dataclass(frozen=True)
class UnitInfo:
    source_units: SourceUnits
    scale_to_m: float
    origin: UnitsOrigin
    warning: str | None = None  # message for a units_assumed issue


def _heuristic(size: float) -> tuple[SourceUnits, float]:
    """Pick the unit that makes ``size`` closest (log scale) to a typical apartment."""
    best = min(NAME_TO_M.items(), key=lambda kv: abs(math.log((size * kv[1]) / TYPICAL_SIZE_M)))
    return best[0], best[1]  # type: ignore[return-value]


def _plausible(size_m: float) -> bool:
    return PLAUSIBLE_MIN_M <= size_m <= PLAUSIBLE_MAX_M


def detect_units(insunits: int | None, wall_extent: float | None, forced: str = "auto") -> UnitInfo:
    """Resolve the drawing units.

    ``wall_extent`` is the largest side of the bounding box of the mapped wall entities in drawing
    units (None if there are none).
    """
    if forced != "auto":
        return UnitInfo(forced, NAME_TO_M[forced], "config")  # type: ignore[arg-type]

    declared = INSUNITS_TO_M.get(insunits or 0)
    if wall_extent is None or wall_extent <= 0:
        if declared:
            return UnitInfo(declared[0], declared[1], "insunits")
        return UnitInfo(
            "m",
            1.0,
            "heuristic",
            "No hay $INSUNITS ni muros para inferir unidades; se asumen metros. Define 'units' en el YAML.",
        )

    if declared:
        if _plausible(wall_extent * declared[1]):
            return UnitInfo(declared[0], declared[1], "insunits")
        name, scale = _heuristic(wall_extent)
        if _plausible(wall_extent * scale):
            return UnitInfo(
                name,
                scale,
                "heuristic",
                f"$INSUNITS dice '{declared[0]}' pero los muros medirían {wall_extent * declared[1]:.1f} m; "
                f"se asume '{name}' ({wall_extent * scale:.1f} m). Confírmalo con 'units' en el YAML.",
            )
        return UnitInfo(declared[0], declared[1], "insunits")

    name, scale = _heuristic(wall_extent)
    return UnitInfo(
        name,
        scale,
        "heuristic",
        f"El DXF no declara unidades ($INSUNITS={insunits or 0}); por la extensión de los muros "
        f"({wall_extent:.1f} unidades) se asume '{name}' ({wall_extent * scale:.1f} m). "
        "Confírmalo con 'units' en el YAML.",
    )
