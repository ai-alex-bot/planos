# Esquema de `space.json` (v1.0)

`space.json` es la representación intermedia entre el DXF y el GLB. Se valida con pydantic
(`pipeline/src/planos/schema.py`). Reglas generales:

- Todas las longitudes en **metros**, áreas en **m²**.
- Coordenadas 2D en el plano XY del DXF (ya escaladas a metros). El paso a glTF (Y arriba) ocurre
  solo al exportar el GLB: `(x, y)` del plano → `(x, z = -y)` en glTF, altura → `y`.
- Identificadores en inglés y `snake_case`; mensajes de issues en español (van al `report.md`).

## Terminología de áreas (Perú)

| Término | Campo | Significado |
|---|---|---|
| Área útil | `Room.net_area_m2` | Área interior de un ambiente, medida a cara interna de muros. |
| Área techada (calculada) | `Metadata.gross_area_m2` | Huella de los ambientes techados **incluyendo muros**. |
| Área techada de ambientes | `Metadata.covered_area_m2` | Suma de `net_area_m2` de ambientes con `is_roofed = true`. |
| Área libre | `Metadata.open_area_m2` | Suma de `net_area_m2` de ambientes **sin techar** (terraza, balcón, patio, jardín). |
| Área declarada | `Metadata.declared` | Dato oficial de la inmobiliaria (YAML). Si existe, el visor muestra esta y nunca la calculada. |

> Ojo: en Perú "área libre" significa área **sin techar**; nunca se usa para el área interior.

## Modelos

```python
Point2 = tuple[float, float]

class Polygon2(BaseModel):
    exterior: list[Point2]                 # anillo exterior, antihorario, sin repetir el primer punto
    holes: list[list[Point2]] = []

class BBox2(BaseModel):
    min: Point2
    max: Point2

class DeclaredAreas(BaseModel):            # viene del YAML (declared:)
    area_techada_m2: float | None = None
    area_libre_m2: float | None = None

class Metadata(BaseModel):
    source_file: str
    source_sha256: str
    dxf_version: str
    source_units: Literal["m", "cm", "mm", "in", "ft", "unknown"]
    units_origin: Literal["insunits", "config", "heuristic"]
    scale_to_m: float
    region: BBox2 | None                   # recorte aplicado (en metros), si hubo
    pipeline_version: str
    generated_at: datetime
    config: ResolvedConfig                 # alturas/tolerancias efectivamente usadas
    gross_area_m2: float                   # "área techada (calculada)", incluye muros
    covered_area_m2: float                 # suma área útil de ambientes techados
    open_area_m2: float                    # suma área útil de ambientes sin techar
    declared: DeclaredAreas | None

class Wall(BaseModel):
    id: str                                # "wall_001"
    start: Point2                          # eje del muro
    end: Point2
    thickness: float
    height: float
    footprint: Polygon2                    # polígono real en planta
    source: Literal["line_pair", "closed_polyline", "hatch", "polygonized", "structure", "opening_fill"]
    adjacent_room_ids: tuple[str | None, str | None]   # (lado izquierdo, lado derecho) mirando start→end
    source_handles: list[str]              # handles DXF para trazabilidad

class Opening(BaseModel):
    id: str                                # "opening_door_01", "opening_window_01", ...
    kind: Literal["door", "window", "glass_door", "passage"]
    wall_id: str | None                    # None → issue opening_without_wall
    center: Point2
    width: float
    sill_height: float                     # door/glass_door/passage 0.00; window 1.00
    head_height: float                     # 2.10 (door_head / window_head)
    rotation_deg: float
    block_name: str | None
    width_source: Literal["wall_gap", "block_extent", "inferred_gap"]
    is_exterior: bool                      # hueco en el borde exterior de la unidad
    source_handle: str | None

class Room(BaseModel):
    id: str                                # "room_01"
    name: str | None                       # texto original normalizado: "SALA-COMEDOR", "S.H."
    slug: str                              # único, sin tildes ni puntuación: "sala_comedor", "s_h_1"
    polygon: Polygon2
    net_area_m2: float                     # "área útil"
    declared_area_m2: float | None         # texto de área encontrado dentro ("12.50 m2", "A=12.50")
    is_roofed: bool                        # false si name ~ TERRAZA|BALC[OÓ]N|PATIO|JARD[IÍ]N
    label_point: Point2
    label_handle: str | None

class Issue(BaseModel):
    code: IssueCode
    severity: Literal["info", "warning", "error"]
    message: str                           # español
    location: Point2 | None = None
    bbox: BBox2 | None = None
    handles: list[str] = []

class Space(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    units: Literal["m"] = "m"
    metadata: Metadata
    walls: list[Wall]
    openings: list[Opening]
    rooms: list[Room]
    issues: list[Issue]
```

## Códigos de issue

| Código | Severidad | Cuándo |
|---|---|---|
| `units_assumed` | warning | `$INSUNITS` ausente/0 y no hay `units` en el YAML; se infirió por extensión de los muros. |
| `layer_unmapped` | info | Capa con entidades que no cae en ninguna categoría ni en `ignore`. |
| `entity_unsupported` | warning | Entidad en capa de muros que no se sabe procesar (SPLINE, etc.). |
| `xref_unresolved` | **error** | Hay XREF no resuelto (falta geometría). |
| `multiple_units_detected` | warning | Clusters de muros desconectados; se listan con su bbox. Usar `region`. |
| `region_empty` | **error** | `region` no contiene geometría de muros. |
| `no_walls` | **error** | No se encontró ninguna entidad en capas de muros. |
| `duplicate_removed` | info | Segmentos duplicados/superpuestos fusionados. |
| `gap_closed` | info | Extremos unidos dentro de `gap_close`. |
| `unpaired_wall_line` | warning | Línea de muro que no se pudo emparejar ni cerrar. |
| `open_wall_end` | warning | Extremo de muro suelto que no se pudo resolver. |
| `opening_without_wall` | warning | Bloque de vano sin muro compatible cerca. |
| `opening_inferred` | warning | Hueco sin bloque convertido en `window`/`passage`/`glass_door`. |
| `room_without_name` | warning | Ambiente sin texto de nombre dentro. |
| `room_multiple_labels` | warning | Ambiente con 2+ nombres (p. ej. cocina abierta). Sugerir `room_separators`. |
| `room_area_mismatch` | warning | Área de texto en el ambiente vs. `net_area_m2` difiere más que `area_mismatch_pct`. |
| `suspicious_area` | warning | `net_area_m2 < min_room_area` o `> max_room_area`. |
| `area_mismatch` | warning | Área techada/libre declarada vs. calculada difiere más que `area_mismatch_pct`. |

`planos convert` termina con exit code ≠ 0 si existe algún issue con severidad `error`.

## YAML de mapeo

Todos los campos son opcionales. Si una categoría de `layers` se define, **reemplaza** la
heurística por defecto de esa categoría.

```yaml
units: auto                  # auto | m | cm | mm
region: null                 # [xmin, ymin, xmax, ymax] en unidades del DIBUJO
layers:
  walls: [MUROS, A-WALL]
  structure: [COLUMNAS, PLACAS]
  doors: [PUERTAS]
  windows: [VENTANAS]
  room_labels: [TEXTOS, AMBIENTES]
  room_separators: []        # líneas virtuales que separan ambientes sin muro
  ignore: [COTAS, EJES, MOBILIARIO, MARCO, ROTULO]
blocks:                      # respaldo por nombre de bloque (glob, sin distinguir mayúsculas)
  doors: ["PUERTA*", "P-*"]
  windows: ["VENT*", "V-*"]
  glass_doors: ["MAMP*"]
declared:
  area_techada_m2: 62.40
  area_libre_m2: 4.10
heights:
  floor_to_ceiling: 2.40
  door_head: 2.10
  window_sill: 1.00
  window_head: 2.10
tolerances:
  snap: 0.01
  gap_close: 0.03
  angle_deg: 1.0
  wall_thickness_min: 0.07
  wall_thickness_max: 0.40
  min_wall_length: 0.10       # traslapes menores no son muro (p. ej. jambas)
  gap_opening_min: 0.40
  gap_opening_max: 4.00
  cluster_gap: 0.50          # distancia máx. entre muros de una misma unidad
  arc_flatten: 0.01          # error máx. al discretizar arcos
  min_void_area: 0.05         # huecos cerrados menores son artefactos
  min_room_area: 1.5
  max_room_area: 60.0
  area_mismatch_pct: 5.0
geometry:
  ceiling: false
```

### Heurísticas por defecto de capas (regex, sin distinguir mayúsculas)

| Categoría | Patrones |
|---|---|
| walls | `MURO(S)?`, `WALL(S)?`, `A-WALL.*`, `TABIQUE(S)?`, `ALBA[ÑN]ILERIA` |
| structure | `COLUMNA(S)?`, `PLACA(S)?`, `ESTRUCTURA`, `CONCRETO`, `S-COL.*` |
| doors | `PUERTA(S)?`, `DOOR(S)?`, `A-DOOR.*` |
| windows | `VENTANA(S)?`, `WINDOW(S)?`, `A-GLAZ.*`, `MAMPARA(S)?` |
| room_labels | `TEXTO(S)?`, `AMBIENTE(S)?`, `A-AREA-IDEN.*`, `NOMBRES?` |
| ignore | `COTA(S)?`, `DIM.*`, `EJE(S)?`, `MOBILIARIO`, `MUEBLE(S)?`, `MARCO`, `ROTULO`, `R[OÓ]TULO`, `DEFPOINTS` |
