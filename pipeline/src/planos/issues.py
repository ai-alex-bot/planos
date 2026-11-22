"""Issues (warnings/errors) collected along the pipeline instead of failing silently."""

from __future__ import annotations

from enum import StrEnum
from typing import Iterable, Literal

from pydantic import BaseModel

Point2 = tuple[float, float]
Severity = Literal["info", "warning", "error"]


class IssueCode(StrEnum):
    UNITS_ASSUMED = "units_assumed"
    LAYER_UNMAPPED = "layer_unmapped"
    ENTITY_UNSUPPORTED = "entity_unsupported"
    XREF_UNRESOLVED = "xref_unresolved"
    MULTIPLE_UNITS_DETECTED = "multiple_units_detected"
    REGION_EMPTY = "region_empty"
    NO_WALLS = "no_walls"
    DUPLICATE_REMOVED = "duplicate_removed"
    GAP_CLOSED = "gap_closed"
    UNPAIRED_WALL_LINE = "unpaired_wall_line"
    OPEN_WALL_END = "open_wall_end"
    OPENING_WITHOUT_WALL = "opening_without_wall"
    OPENING_INFERRED = "opening_inferred"
    ROOM_WITHOUT_NAME = "room_without_name"
    ROOM_MULTIPLE_LABELS = "room_multiple_labels"
    ROOM_AREA_MISMATCH = "room_area_mismatch"
    SUSPICIOUS_AREA = "suspicious_area"
    AREA_MISMATCH = "area_mismatch"


DEFAULT_SEVERITY: dict[IssueCode, Severity] = {
    IssueCode.UNITS_ASSUMED: "warning",
    IssueCode.LAYER_UNMAPPED: "info",
    IssueCode.ENTITY_UNSUPPORTED: "warning",
    IssueCode.XREF_UNRESOLVED: "error",
    IssueCode.MULTIPLE_UNITS_DETECTED: "warning",
    IssueCode.REGION_EMPTY: "error",
    IssueCode.NO_WALLS: "error",
    IssueCode.DUPLICATE_REMOVED: "info",
    IssueCode.GAP_CLOSED: "info",
    IssueCode.UNPAIRED_WALL_LINE: "warning",
    IssueCode.OPEN_WALL_END: "warning",
    IssueCode.OPENING_WITHOUT_WALL: "warning",
    IssueCode.OPENING_INFERRED: "warning",
    IssueCode.ROOM_WITHOUT_NAME: "warning",
    IssueCode.ROOM_MULTIPLE_LABELS: "warning",
    IssueCode.ROOM_AREA_MISMATCH: "warning",
    IssueCode.SUSPICIOUS_AREA: "warning",
    IssueCode.AREA_MISMATCH: "warning",
}


class BBox2(BaseModel):
    min: Point2
    max: Point2


class Issue(BaseModel):
    code: IssueCode
    severity: Severity
    message: str
    location: Point2 | None = None
    bbox: BBox2 | None = None
    handles: list[str] = []


class Issues:
    """Ordered collector of issues."""

    def __init__(self) -> None:
        self.items: list[Issue] = []

    def add(
        self,
        code: IssueCode,
        message: str,
        *,
        severity: Severity | None = None,
        location: Point2 | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        handles: Iterable[str] = (),
    ) -> Issue:
        issue = Issue(
            code=code,
            severity=severity or DEFAULT_SEVERITY[code],
            message=message,
            location=(round(location[0], 4), round(location[1], 4)) if location else None,
            bbox=BBox2(min=(bbox[0], bbox[1]), max=(bbox[2], bbox[3])) if bbox else None,
            handles=list(handles),
        )
        self.items.append(issue)
        return issue

    def by_code(self, code: IssueCode) -> list[Issue]:
        return [i for i in self.items if i.code == code]

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)
