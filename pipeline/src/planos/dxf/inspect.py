"""`planos inspect`: everything needed to write the mapping YAML for a new plan."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezbbox
from pydantic import BaseModel

from planos.config import Config, LayerClassifier, classify_block
from planos.dxf.reader import read_dxf
from planos.geometry.clusters import find_clusters, report_clusters, significant
from planos.issues import Issue, Issues


class LayerRow(BaseModel):
    name: str
    category: str | None
    source: str  # yaml | heuristic | unmapped
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class BlockRow(BaseModel):
    name: str
    count: int
    layers: list[str]
    kind: str | None  # door | window | glass_door | None
    local_size: tuple[float, float] | None  # block definition extents (drawing units)
    xscales: list[float]


class TextRow(BaseModel):
    text: str
    layer: str
    category: str | None
    position_m: tuple[float, float]


class ClusterRow(BaseModel):
    bbox_drawing: tuple[float, float, float, float]
    bbox_m: tuple[float, float, float, float]
    size_m: float
    n_items: int


class InspectReport(BaseModel):
    file: str
    dxf_version: str
    insunits: int
    units: str
    units_origin: str
    scale_to_m: float
    region: tuple[float, float, float, float] | None
    layers: list[LayerRow]
    empty_layers: list[str]
    blocks: list[BlockRow]
    texts: list[TextRow]
    clusters: list[ClusterRow]
    issues: list[Issue]


def inspect_dxf(path: Path | str, cfg: Config | None = None) -> InspectReport:
    cfg = cfg or Config()
    path = Path(path)
    issues = Issues()
    drawing = read_dxf(path, cfg, issues)
    clusters = find_clusters(drawing, cfg.tolerances.cluster_gap)
    report_clusters(clusters, issues, cfg.region is not None)

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    clf = LayerClassifier(cfg.layers)

    counts: dict[str, Counter[str]] = defaultdict(Counter)
    block_uses: dict[str, list] = defaultdict(list)
    for e in msp:
        layer = e.dxf.get("layer", "0")
        counts[layer][e.dxftype()] += 1
        if e.dxftype() == "INSERT":
            block_uses[e.dxf.name].append(e)

    layers = [
        LayerRow(name=name, category=clf.category(name), source=clf.source(name), counts=dict(c.most_common()))
        for name, c in sorted(counts.items(), key=lambda kv: kv[0].upper())
    ]
    empty = sorted(l.dxf.name for l in doc.layers if l.dxf.name not in counts)

    blocks = []
    for name, uses in sorted(block_uses.items()):
        block = doc.blocks.get(name)
        size = None
        if block is not None:
            ext = ezbbox.extents([x for x in block if x.dxftype() != "ATTDEF"], fast=True)
            if ext.has_data:
                size = (round(ext.size.x, 6), round(ext.size.y, 6))
        use_layers = sorted({u.dxf.get("layer", "0") for u in uses})
        kinds = {classify_block(name, clf.category(l), cfg.blocks) for l in use_layers}
        kinds.discard(None)
        blocks.append(
            BlockRow(
                name=name,
                count=len(uses),
                layers=use_layers,
                kind=kinds.pop() if len(kinds) == 1 else (None if not kinds else "/".join(sorted(kinds))),
                local_size=size,
                xscales=sorted({round(u.dxf.get("xscale", 1.0), 4) for u in uses}),
            )
        )

    texts = [
        TextRow(text=t.text, layer=t.layer, category=t.category, position_m=(round(t.position[0], 3), round(t.position[1], 3)))
        for t in drawing.texts
    ]
    cluster_rows = [
        ClusterRow(
            bbox_drawing=tuple(round(v, 4) for v in c.bbox_drawing),
            bbox_m=tuple(round(v, 4) for v in c.bbox_m),
            size_m=round(c.size_m, 3),
            n_items=c.n_items,
        )
        for c in significant(clusters)
    ]
    return InspectReport(
        file=str(path),
        dxf_version=drawing.dxf_version,
        insunits=drawing.insunits,
        units=drawing.units.source_units,
        units_origin=drawing.units.origin,
        scale_to_m=drawing.units.scale_to_m,
        region=cfg.region,
        layers=layers,
        empty_layers=empty,
        blocks=blocks,
        texts=texts,
        clusters=cluster_rows,
        issues=issues.items,
    )
