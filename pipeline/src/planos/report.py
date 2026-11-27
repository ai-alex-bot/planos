"""report.md: human summary of a conversion (Spanish, for the internal team)."""

from __future__ import annotations

from collections import Counter

from planos.schema import Space

KIND_ES = {"door": "puerta", "window": "ventana", "glass_door": "mampara", "passage": "vano libre", "railing": "baranda"}
KIND_ES_PLURAL = {
    "door": "puertas",
    "window": "ventanas",
    "glass_door": "mamparas",
    "passage": "vanos libres",
    "railing": "barandas",
}
SEVERITY_ES = {"error": "ERROR", "warning": "Advertencia", "info": "Info"}
UNITS_ORIGIN_ES = {"insunits": "$INSUNITS del DXF", "config": "YAML", "heuristic": "inferidas"}
WIDTH_SOURCE_ES = {"wall_gap": "hueco del muro", "block_extent": "tamaño del bloque", "inferred_gap": "hueco inferido"}


def _m2(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}"


def _count(items: Counter, labels: dict[str, str], plural: dict[str, str]) -> str:
    parts = [f"{n} {plural[k] if n != 1 else labels[k]}" for k, n in sorted(items.items())]
    return ", ".join(parts) or "ninguno"


def render_report(space: Space) -> str:
    m = space.metadata
    walls = [w for w in space.walls if w.source not in ("opening_fill", "structure", "railing")]
    railings = sum(1 for w in space.walls if w.source == "railing")
    structure = sum(1 for w in space.walls if w.source == "structure")
    fills = sum(1 for w in space.walls if w.source == "opening_fill")
    kinds = Counter(o.kind for o in space.openings)
    sev = Counter(i.severity for i in space.issues)
    lines: list[str] = []
    add = lines.append

    add(f"# Reporte de conversión – {m.source_file}")
    add("")
    add(f"Generado {m.generated_at:%Y-%m-%d %H:%M} UTC · planos {m.pipeline_version} · esquema {space.schema_version}")
    add("")
    status = "❌ Con errores" if sev["error"] else ("⚠️ Con advertencias" if sev["warning"] else "✅ Sin observaciones")
    add(f"**Estado:** {status} ({sev['error']} errores, {sev['warning']} advertencias, {sev['info']} avisos informativos)")
    add("")

    add("## Resumen")
    add("")
    add("| Dato | Valor |")
    add("|---|---|")
    add(f"| Unidades del dibujo | {m.source_units} ({UNITS_ORIGIN_ES[m.units_origin]}), ×{m.scale_to_m:g} → m |")
    if m.region:
        add(f"| Región recortada (m) | [{m.region.min[0]:.2f}, {m.region.min[1]:.2f}] – [{m.region.max[0]:.2f}, {m.region.max[1]:.2f}] |")
    extra = f", {railings} tramos de baranda dibujados" if railings else ""
    add(f"| Muros | {len(walls)} muros, {structure} columnas/placas{extra} (+{fills} rellenos de vano) |")
    add(f"| Vanos | {len(space.openings)}: {_count(kinds, KIND_ES, KIND_ES_PLURAL)} |")
    add(f"| Ambientes | {len(space.rooms)} |")
    h = m.config.heights
    add(
        f"| Alturas | piso-techo {h.floor_to_ceiling:.2f} m · dintel {h.door_head:.2f} m · "
        f"alféizar {h.window_sill:.2f} m · baranda {h.railing:.2f} m |"
    )
    add("")

    add("## Áreas de la unidad")
    add("")
    add("| Concepto | Calculada (m²) | Declarada (m²) |")
    add("|---|---:|---:|")
    decl = m.declared
    add(f"| Área techada (calculada, incluye muros) | {_m2(m.gross_area_m2)} | {_m2(decl.area_techada_m2 if decl else None)} |")
    add(f"| Área útil de ambientes techados | {_m2(m.covered_area_m2)} | — |")
    add(f"| Área libre (terrazas, balcones, patios) | {_m2(m.open_area_m2)} | {_m2(decl.area_libre_m2 if decl else None)} |")
    add("")
    if decl and (decl.area_techada_m2 or decl.area_libre_m2):
        add("> El visor muestra el área **declarada** de la unidad cuando existe.")
        add("")

    add("## Ambientes")
    add("")
    if space.rooms:
        add("| ID | Ambiente | Slug | Área útil (m²) | Área en plano (m²) | Exterior | Techo 3D |")
        add("|---|---|---|---:|---:|---|---|")
        for r in space.rooms:
            add(
                f"| {r.id} | {r.name or '_(sin nombre)_'} | `{r.slug}` | {r.net_area_m2:.2f} | "
                f"{_m2(r.declared_area_m2)} | {'sí' if r.is_outdoor else 'no'} | {'sí' if r.has_ceiling else 'no'} |"
            )
        total = sum(r.net_area_m2 for r in space.rooms)
        add(f"| | **Total** | | **{total:.2f}** | | | |")
    else:
        add("_No se detectaron ambientes._")
    add("")

    add("## Vanos")
    add("")
    if space.openings:
        add("| ID | Tipo | Ancho (m) | Alféizar–dintel (m) | Muro | Exterior | Ancho según | Bloque |")
        add("|---|---|---:|---|---|---|---|---|")
        for o in space.openings:
            add(
                f"| {o.id} | {KIND_ES[o.kind]} | {o.width:.2f} | {o.sill_height:.2f}–{o.head_height:.2f} | "
                f"{o.wall_id or '—'} | {'sí' if o.is_exterior else 'no'} | {WIDTH_SOURCE_ES[o.width_source]} | "
                f"{o.block_name or '—'} |"
            )
    else:
        add("_No se detectaron vanos._")
    add("")

    add("## Avisos")
    add("")
    if not space.issues:
        add("Sin avisos.")
    for severity in ("error", "warning", "info"):
        group = [i for i in space.issues if i.severity == severity]
        if not group:
            continue
        add(f"### {SEVERITY_ES[severity]} ({len(group)})")
        add("")
        for i in group:
            loc = f" _(en {i.location[0]:.2f}, {i.location[1]:.2f} m)_" if i.location else ""
            msg = i.message.replace("\n", "<br>")
            add(f"- `{i.code}`: {msg}{loc}")
        add("")
    return "\n".join(lines).rstrip() + "\n"
