# Detección de muros, vanos y ambientes

Idea central: construir una **máscara de muros** en planta (un `MultiPolygon` de shapely) y derivar de
ella los muros, los ambientes y la geometría 3D. Así no dependemos de que el dibujo esté
perfectamente cerrado, y todo lo que no se puede resolver se reporta como issue con ubicación.

## 0. Unidades y recorte

1. Si el YAML define `units`, manda. Si no, se lee `$INSUNITS`.
2. Si `$INSUNITS` es 0/ausente (o da un tamaño absurdo, p. ej. un depto de 1 km), se infiere a partir de la extensión de **las entidades de muros
   mapeadas** (no de todo el dibujo, para no confundirse con marcos, rótulos o XREFs): lado mayor
   ~5–50 → m, ~500–5000 → cm, ~5000–50000 → mm. Issue `units_assumed`.
3. Si el YAML define `region` (en unidades del dibujo), se descarta todo lo que caiga fuera.
4. XREF no resuelto → issue `xref_unresolved` (error).

## 1. Recolección

- Capas `walls`: LINE, LWPOLYLINE/POLYLINE, ARC (discretizado), HATCH (contornos) e INSERT
  (explotados recursivamente con su transformación).
- Capas `structure` (columnas, placas): polilíneas cerradas y hatches, que entran a la máscara con
  `source = "structure"`.
- Capas `railings` (barandas y parapetos dibujados con líneas): se emparejan como muros y, si es una
  sola línea, se les da `geometry.railing_thickness`. Son **muros bajos** (`source = "railing"`,
  altura `heights.railing`): cierran ambientes (un balcón volado) sin nada encima. Un muro de altura
  completa nunca se prolonga dentro de una baranda.
- Entidades no soportadas → `entity_unsupported`.

## 2. Limpieza

1. Descartar segmentos de longitud ~0.
2. Snap de extremos a clusters dentro de `snap`.
3. Fusionar segmentos colineales superpuestos (`duplicate_removed`).
4. Extender extremos sueltos hasta el segmento más cercano si están a menos de `gap_close`
   (`gap_closed`).

## 3. Polígonos de muro

1. **Polilíneas cerradas / hatches** → polígono directo (`make_valid`).
2. **Pares de líneas paralelas**: ángulo ≤ `angle_deg`, separación entre `wall_thickness_min` y
   `wall_thickness_max`, superposición longitudinal > 0. El tramo superpuesto da un rectángulo con eje y
   espesor. No requiere tapas en los extremos. Si una línea admite varios pares, gana el más cercano.
3. **Respaldo**: `unary_union` + `polygonize` sobre los segmentos sin par; se aceptan las caras
   delgadas (desaparecen con `buffer(-wall_thickness_max/2)`). Lo que sobra → `unpaired_wall_line`.
4. **Tramos colineales** del mismo muro (mismo eje y espesor) separados menos que `gap_opening_min`
   se unen en un solo muro (p. ej. un muro exterior partido por los encuentros en T).
5. **Encuentros**: emparejar caras deja sin cubrir el cuadrado de cada esquina en L y el núcleo de las
   T/X, y un cierre morfológico **no** rellena una esquina convexa. Por eso cada extremo de muro que
   llega a otro muro no paralelo se prolonga hasta la cara opuesta de ese muro (solo se alarga).
6. Unión + cierre morfológico (`buffer(+r).buffer(-r)`, `r < gap_opening_min/2`) para muescas
   pequeñas sin tapar vanos reales.
7. **Clusters** (`geometry/clusters.py`, también en `planos inspect`): componentes conexas de muros y
   estructura con tolerancia `cluster_gap` (0.50 m). Los bloques de puertas/ventanas y las líneas de
   ventana actúan de **puente** sobre sus huecos. Un grupo cuyo bbox cae ≥ 80 % dentro del bbox de otro
   mayor (columna aislada, muro cortado por un vano sin bloque) se fusiona con él. Grupos < 2 m se
   consideran sueltos. Si quedan 2+ grupos → `multiple_units_detected` con el bbox de cada uno, listo
   para copiar en `region`. Limitación: dos unidades que comparten muro medianero se ven como una sola;
   en ese caso hay que usar `region` a mano.

## 4. Vanos

Todo vano, con bloque o inferido, se rellena con un rectángulo `opening_fill` (ancho × espesor del
muro) para cerrar la máscara antes de buscar ambientes. El relleno se alarga unos milímetros a cada
lado para **solapar** con el muro: si solo lo toca, el error de punto flotante deja grietas de ancho
cero que conectan todos los ambientes en uno.

### 4.1 Con bloque

- INSERT en capas `doors`/`windows`, o con nombre de bloque que calce `blocks.*`.
- `blocks.glass_doors` (`MAMP*`) → `kind = "glass_door"` (sill 0.00, head 2.10).
- `blocks.railings` (`BARANDA*`, `PARAPETO*`) → `kind = "railing"`: parapeto de `heights.railing`
  y nada encima. El nombre manda sobre la capa (una baranda en la capa VENTANAS sigue siendo baranda).
- Se asocia al hueco paralelo (±10°) con el que se superpone su extensión proyectada; el ancho y
  el centro salen del hueco real (`wall_gap`).
- Si no hay hueco (muro dibujado continuo bajo el bloque), va al muro paralelo más cercano y el
  ancho es la extensión del bloque proyectada sobre el eje del muro (`block_extent`).
- Sin muro compatible → `opening_without_wall`.

### 4.0 Cómo se encuentran los huecos

Desde cada **extremo libre** de muro (uno que no fue prolongado a un encuentro y no toca otro muro)
se lanza un rayo por el eje del muro. Si choca con la máscara (otro muro o una columna) a una
distancia entre `gap_opening_min` (0.40) y `gap_opening_max` (4.00), eso es un hueco. Cubre tanto el
muro interrumpido (dos extremos colineales) como la puerta junto a una esquina o una columna. El
mismo hueco visto desde ambos lados se cuenta una vez.

### 4.2 Sin bloque (huecos inferidos)

Si no se cierran, los ambientes "se escapan" al exterior. Son los huecos de 4.0 que no quedaron
asociados a ningún bloque:

| Situación | Resultado |
|---|---|
| Hay líneas de capa `windows` dentro del hueco | `window` |
| Borde exterior y un ambiente exterior al lado (`is_outdoor`: terraza, balcón…) | `railing` |
| Otro hueco en el borde exterior de la unidad | `window` (alturas por defecto) |
| Hueco interior | `passage` (vano libre, head = `door_head`) |

Esta clasificación se hace **después** de detectar los ambientes (hace falta saber si el ambiente
vecino es exterior); por eso `opening_inferred` se emite en ese momento.

`width_source = "inferred_gap"` y issue `opening_inferred` (warning) con la ubicación.

"Borde exterior": el hueco toca el anillo exterior de la máscara cerrada (la máscara + todos los
`opening_fill`).

## 5. Ambientes

1. Ambientes = huecos interiores (holes) de la máscara cerrada (muros + todos los `opening_fill`),
   cortados además por las líneas de `room_separators`. Huecos menores a `min_void_area` (0.05 m²) son
   artefactos y se descartan.
2. Textos: los de capas `room_labels`; si el plano no tiene ninguna, todos los que no estén en capas
   `ignore`. MTEXT se lee con `plain_text()` (sin códigos de formato).
3. Clasificación (`geometry/texts.py`):
   - **área**: `12.50 m2`, `12,50 M²`, `A=12.50`, `ÁREA: 12.50` → `Room.declared_area_m2`;
   - **otros** (se ignoran): `NPT +0.15`, `N.P.T. ±0.00`, números sueltos, `1.20x2.10`, `h=2.10`,
     `P1`, `ESCALA 1/50`;
   - **nombre**: el resto.
4. Nombres en dos líneas ("DORM." sobre "PRINCIPAL") se unen si están apilados (separación vertical ≤
   2 alturas de texto).
5. Si alguno de los nombres pertenece al vocabulario usual (`DORM.`, `S.H.`, `SS.HH.`, `BAÑO`, `COC.`,
   `COCINA`, `LAV.`, `LAVANDERÍA`, `HALL`, `ESTAR`, `SALA`, `COMEDOR`, `TERRAZA`, …), las notas que no lo
   son ("PISO PORCELANATO") no cuentan como segundo nombre.
6. Slug: sin tildes, minúsculas, puntuación → `_`; los repetidos llevan sufijo en todas sus apariciones
   (`s_h_1`, `s_h_2`). Ambientes sin nombre: `ambiente` (+ sufijo).
7. `is_outdoor = true` si el nombre calza `TERRAZA|BALC[OÓ]N|PATIO|JARD[IÍ]N` (área libre y regla de
   barandas). `has_ceiling` (solo 3D) es por defecto lo contrario, y el YAML puede forzarlo por nombre
   o slug: `rooms: {"TERRAZA": {has_ceiling: true}}` para una terraza bajo la losa de arriba.
8. Issues: `room_without_name`, `room_multiple_labels` (sugiere `room_separators`), `room_area_mismatch`,
   `suspicious_area` (`min_room_area` / `max_room_area`).
9. `Wall.adjacent_room_ids`: se toma una franja de 5 cm a cada lado del muro y gana el ambiente que más
   la cubre (lado izquierdo/derecho mirando de `start` a `end`; `None` = exterior).

## 6. Áreas de la unidad

- `covered_area_m2` / `open_area_m2`: suma del área útil por `is_outdoor`.
- `gross_area_m2` ("área techada (calculada)"): contorno exterior de la máscara cerrada, menos los
  ambientes sin techar y menos los muros que solo bordean ambientes sin techar (parapetos, muros
  laterales de la terraza). Los muros entre un ambiente techado y uno sin techar cuentan completos.
- Si hay `declared` en el YAML y la diferencia supera `area_mismatch_pct` → `area_mismatch`.

## 7. Geometría 3D (`model3d/build.py`, JSON → GLB)

- Se parte de `space.json` (no del DXF). Las huellas de todos los muros (incluidos los
  `opening_fill`) se cortan en **piezas disjuntas**, una por muro (primero los muros reales, al final
  los rellenos): no hay caras superpuestas ni z-fighting en los encuentros.
- Cada pieza se extruye a `floor_to_ceiling` con manifold3d y se le restan las cajas de los vanos
  (`ancho × (espesor + 2·opening_cut_margin) × (sill..head)`): queda el dintel sobre puertas/pasos y
  alféizar + dintel en ventanas. Los cortadores sobresalen 1 mm a lo largo para evitar caras coplanares.
- Un piso por ambiente: `floor_<slug>` (UV en metros, para texturas en la Fase 2). Techo
  `ceiling_<slug>` (mirando hacia abajo) en los ambientes con `has_ceiling` (`geometry.ceiling`, por
  defecto sí), con `hidden_by_default`: el visor solo lo muestra en modo Caminar.
- Cada pieza se extruye a la altura de su muro (las barandas a `heights.railing`). El cortador de un
  vano tipo `railing` sube más allá del techo: queda el parapeto y nada encima.
- Nodos vacíos `opening_<tipo>_NN` en la base del vano, rotados con su muro.
- Materiales placeholder: `wall`, `column`, `floor`, `floor_exterior`, `ceiling`.
- glTF Y arriba: plano (x, y) y altura h → (x, h, −y). El modelo se **recentra** en el origen (glTF usa
  float32 y los planos reales pueden venir en coordenadas grandes); el desplazamiento queda en
  `origin_offset_m`.
- **Extras** (escritos con pygltflib después de exportar; three.js los expone en `userData`):
  - piso: `type, room_id, name, slug, net_area_m2, declared_area_m2, is_outdoor, has_ceiling,
    label_position`;
  - techo: `type, room_id, slug, hidden_by_default`;
  - muro: `type, wall_id, source, thickness, height, adjacent_room_ids`;
  - vano: `type, opening_id, kind, width, sill_height, head_height, wall_id, is_exterior`;
  - escena: `gross_area_m2, covered_area_m2, open_area_m2, declared, display_area_m2,
    display_area_kind` ("declarada" si existe el dato oficial, si no "calculada"), `floor_to_ceiling`.
- Validación en tests: el volumen de muros es igual a área × altura − Σ vanos (±0.2 %).
