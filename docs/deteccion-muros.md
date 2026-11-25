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
| Hueco en el borde exterior de la unidad | `window` (alturas por defecto) |
| Hueco interior | `passage` (vano libre, head = `door_head`) |

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
7. `is_roofed = false` si el nombre calza `TERRAZA|BALC[OÓ]N|PATIO|JARD[IÍ]N`.
8. Issues: `room_without_name`, `room_multiple_labels` (sugiere `room_separators`), `room_area_mismatch`,
   `suspicious_area` (`min_room_area` / `max_room_area`).
9. `Wall.adjacent_room_ids`: se toma una franja de 5 cm a cada lado del muro y gana el ambiente que más
   la cubre (lado izquierdo/derecho mirando de `start` a `end`; `None` = exterior).

## 6. Áreas de la unidad

- `covered_area_m2` / `open_area_m2`: suma del área útil por `is_roofed`.
- `gross_area_m2` ("área techada (calculada)"): contorno exterior de la máscara cerrada, menos los
  ambientes sin techar y menos los muros que solo bordean ambientes sin techar (parapetos, muros
  laterales de la terraza). Los muros entre un ambiente techado y uno sin techar cuentan completos.
- Si hay `declared` en el YAML y la diferencia supera `area_mismatch_pct` → `area_mismatch`.

## 7. Geometría 3D

- Las mallas de muros se generan **a partir de la máscara unida** (no muro por muro) para evitar
  caras superpuestas y z-fighting en los encuentros. La máscara se parte en piezas por `Wall` sin
  superposición (cada pieza es la intersección de la máscara con la celda de su muro).
- Extrusión a `floor_to_ceiling`; cada vano resta (manifold3d) una caja
  `ancho × (espesor + margen) × (sill..head)`: deja dintel sobre puertas/pasos y alféizar + dintel en
  ventanas.
- Un piso por ambiente: `floor_<slug>`; extras glTF: `room_id`, `name`, `net_area_m2`, `is_roofed`.
- Nodos: `wall_001`, `floor_sala_comedor`, `opening_door_01` (vacío con posición). Escena con extras
  de la unidad (áreas declaradas/calculadas).
- Se verifica que trimesh escriba los extras por nodo; si no, se post-procesa con pygltflib. Un test
  relee los extras.
