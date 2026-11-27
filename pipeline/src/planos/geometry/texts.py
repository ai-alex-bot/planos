"""Classification of plan texts (room names, area labels, other notes) and slugs."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

TextKind = Literal["name", "area", "other"]

_NUM = r"(\d+(?:[.,]\d+)?)"
_AREA_UNIT = r"(?:M2|M²|MT2|MTS2|M\^2|M\.2)"
# "12.50 m2", "12,50 M²", "A=12.50", "A: 12.5 m2", "ÁREA = 12.50", "AREA 12.50 M2"
AREA_RE = re.compile(
    rf"^(?:(?:A|AREA|ÁREA|AT|AU)\s*[=:]?\s*{_NUM}\s*{_AREA_UNIT}?|{_NUM}\s*{_AREA_UNIT})$",
    re.IGNORECASE,
)
OTHER_RES = [
    re.compile(r"^N\.?\s*P\.?\s*T\.?", re.IGNORECASE),  # NPT +0.15, N.P.T. ±0.00
    re.compile(r"^N\.?\s*[FT]\.?\s*[PT]\.?", re.IGNORECASE),  # NFP, NTT
    re.compile(r"^[+±\-]?\s*\d+(?:[.,]\d+)?\s*(?:M|CM|MM)?$", re.IGNORECASE),  # loose numbers / dims
    re.compile(r"^\d+(?:[.,]\d+)?\s*[xX×]\s*\d+(?:[.,]\d+)?", re.IGNORECASE),  # 1.20x2.10, 60x60
    re.compile(r"^(?:H|ALT|ALF|ALFEIZAR)\s*[=:]", re.IGNORECASE),  # h=2.10, alf=1.00
    re.compile(r"^(?:ESC(?:ALA)?\.?|ESC:)\s*\d", re.IGNORECASE),  # escala 1/50
    re.compile(r"^[A-Z]?\d{1,3}$"),  # tags like P1, V2, 12
]
# Usual room words in Lima plans (prefix match, accents optional)
ROOM_WORDS_RE = re.compile(
    r"\b(DORM|DORMITORIO|HAB|HABITACI[OÓ]N|RECAMARA|S\.?\s?H\.?|SS\.?\s?HH\.?|BA[ÑN]O|1/2\s?BA[ÑN]O|"
    r"COC|COCINA|KITCHENETTE|LAV|LAVANDER[IÍ]A|PATIO\s?DE\s?SERVICIO|HALL|ESTAR|SALA|COMEDOR|"
    r"TERRAZA|BALC[OÓ]N|PATIO|JARD[IÍ]N|ESTUDIO|WALK|CLOSET|VESTIDOR|DEP[OÓ]SITO|DESPENSA|"
    r"CUARTO|SERVICIO|PASADIZO|CIRCULACI[OÓ]N|CORREDOR|RECIBO|INGRESO|FOYER|VEST[IÍ]BULO|DUCTO|"
    r"TENDAL|LOGGIA|OFICINA|ESCALERA)",
    re.IGNORECASE,
)
OUTDOOR_RE = re.compile(r"TERRAZA|BALC[OÓ]N|PATIO|JARD[IÍ]N", re.IGNORECASE)


def normalize(text: str) -> str:
    return " ".join(text.replace("\n", " ").split()).upper()


def classify(text: str) -> tuple[TextKind, float | None]:
    """Kind of a text inside a room; for area texts also the value in m²."""
    t = normalize(text)
    m = AREA_RE.match(t)
    if m:
        value = next(g for g in m.groups() if g is not None)
        return "area", float(value.replace(",", "."))
    if len(t) < 2 or any(r.match(t) for r in OTHER_RES):
        return "other", None
    if not re.search(r"[A-ZÁÉÍÓÚÑ]", t):
        return "other", None
    return "name", None


def is_room_word(text: str) -> bool:
    return bool(ROOM_WORDS_RE.search(normalize(text)))


def is_outdoor(name: str | None) -> bool:
    """Terraces, balconies, patios and gardens (área libre), whether or not they have a slab above."""
    return bool(name and OUTDOOR_RE.search(name))


def slugify(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_ = "".join(c for c in nfkd if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_")
    return slug or "ambiente"


def unique_slugs(bases: list[str]) -> list[str]:
    """Duplicated slugs get a 1-based suffix on every occurrence: s_h_1, s_h_2."""
    counts: dict[str, int] = {}
    for b in bases:
        counts[b] = counts.get(b, 0) + 1
    seen: dict[str, int] = {}
    out = []
    for b in bases:
        if counts[b] == 1:
            out.append(b)
        else:
            seen[b] = seen.get(b, 0) + 1
            out.append(f"{b}_{seen[b]}")
    return out


@dataclass
class Label:
    text: str
    position: tuple[float, float]
    height: float
    handle: str


def merge_multiline(labels: list[Label], default_height: float) -> list[Label]:
    """Join name texts stacked on top of each other ("DORM." over "PRINCIPAL")."""
    items = sorted(labels, key=lambda l: (-l.position[1], l.position[0]))
    merged: list[Label] = []
    for lab in items:
        h = lab.height or default_height
        for k in range(len(merged) - 1, -1, -1):
            prev = merged[k]
            ph = prev.height or default_height
            dy = prev.position[1] - lab.position[1]
            dx = abs(prev.position[0] - lab.position[0])
            if 0 < dy <= 2.0 * max(h, ph) and dx <= 3.0 * max(h, ph):
                merged[k] = Label(
                    f"{prev.text} {lab.text}",
                    ((prev.position[0] + lab.position[0]) / 2, (prev.position[1] + lab.position[1]) / 2),
                    max(h, ph),
                    prev.handle,
                )
                break
        else:
            merged.append(lab)
    return merged
