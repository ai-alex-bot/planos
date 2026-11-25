# Fase 1 – Requerimientos y plan de trabajo

Registro del pedido original, los ajustes aprobados y el avance por commits. El detalle técnico vive en
[esquema-space.md](esquema-space.md), [deteccion-muros.md](deteccion-muros.md) y
[arquitectura.md](arquitectura.md).

## Pedido original

Pipeline que convierte el plano DXF de una tipología de departamento en un modelo 3D GLB, y un visor
web simple para recorrerlo.

### 1. Ingesta (DXF → JSON del espacio)
- Entrada: archivo DXF. La conversión DWG→DXF queda fuera; documentar en el README cómo hacerla con
  ODA File Converter.
- `planos inspect archivo.dxf`: capas con conteo de entidades por tipo, bloques usados, textos y
  unidades detectadas. Sirve para armar el mapeo.
- Mapeo de capas por proyecto en YAML (muros, puertas, ventanas, textos de ambientes), con heurísticas
  por defecto para nombres comunes (MURO, MUROS, WALL, A-WALL, PUERTA, VENTANA…). El YAML manda.
- Unidades: leer `$INSUNITS` y normalizar a metros, con opción de forzarlas en el YAML (en Perú es común
  dibujar en metros o centímetros).
- Muros: pares de líneas paralelas, polilíneas cerradas o hatches. Estrategia robusta (limpiar, unir
  extremos dentro de una tolerancia, polygonize) y reportar lo que no se pueda resolver.
- Vanos: bloques (INSERT). Posición, rotación, escala y ancho desde la extensión del bloque; asociar al
  muro más cercano. Alturas por defecto: puerta 2.10 m; ventana alféizar 1.00 m y dintel 2.10 m.
- Ambientes: polígonos interiores delimitados por muros, con nombre del TEXT/MTEXT que cae dentro y
  área en m².
- Salida: `space.json` validado con pydantic (unidades, muros, vanos, ambientes, metadata, warnings).

### 2. Generación 3D (JSON → GLB)
- Extruir muros a la altura piso-techo (default 2.40 m) y recortar vanos con booleanos.
- Un piso separado por ambiente. Techo desactivado por defecto.
- Nombres de nodos: `wall_001`, `floor_sala_comedor`, `opening_door_01`… Materiales placeholder
  distintos para muros y pisos.
- `planos convert archivo.dxf --config mapeo.yaml -o out/` → `space.json`, `model.glb`, `report.md`
  (resumen, áreas por ambiente y warnings).

### 3. Visor web
- Carga un GLB desde `/public` o arrastrando el archivo.
- Modos: órbita, planta (cenital) y caminata en primera persona a 1.60 m.
- Iluminación con environment de drei.
- Clic en un piso: nombre del ambiente y área.
- Debe funcionar bien en el celular.

### 4. Datos de prueba y tests
- DXF "limpio" de un departamento típico de Lima de 2 dormitorios (~65 m²) y variante "desordenada"
  (huecos de mm, líneas duplicadas, capa mal nombrada, dibujo en cm).
- Tests: áreas por ambiente con tolerancia, cantidad de vanos, el GLB se relee con trimesh, la variante
  desordenada da el mismo resultado (o warnings claros).

### Fuera de alcance
Muebles, editor de decoración, render con IA, backend, autenticación, conversión automática de DWG,
reconocimiento de planos en PDF o imagen.

### Criterios de terminado
- `uv run planos inspect` y `uv run planos convert` funcionan con los DXF de prueba.
- `pnpm dev` en `viewer/` muestra el modelo y se recorre en los 3 modos.
- Todos los tests pasan.
- README en español con instalación, uso y cómo armar el YAML de mapeo.

## Ajustes aprobados

1. **Terminología de áreas**: "área libre" en Perú = área sin techar. `Room.net_area_m2` ("área útil"),
   `Room.is_roofed` (false para TERRAZA/BALCÓN/PATIO/JARDÍN). Metadata: `gross_area_m2` ("área techada
   (calculada)"), `covered_area_m2`, `open_area_m2`. YAML `declared: {area_techada_m2, area_libre_m2}`;
   issue `area_mismatch` si difiere más que `area_mismatch_pct` (5 %). El visor muestra el área
   declarada si existe.
2. **Vanos sin bloque**: huecos colineales entre `gap_opening_min` (0.40) y `gap_opening_max` (4.00).
   Borde exterior → `window`; interior → `passage`; líneas de capa ventanas → `window`. Mamparas
   (`MAMP*`) → `glass_door`. `width_source: inferred_gap`, issue `opening_inferred`. Todo vano recibe
   `opening_fill`.
3. **Textos**: MTEXT con `plain_text()`. Clasificar en nombre / área / otros (cotas, NPT). Área →
   `Room.declared_area_m2` e issue `room_area_mismatch`. Abreviaturas de Lima. Slugs únicos sin tildes.
4. **Columnas y placas**: categoría `structure`; entran a la máscara.
5. **Varias unidades / rótulo / marco**: unidades inferidas solo con la extensión de muros; issue
   `multiple_units_detected`; YAML `region`; XREF no resuelto → `xref_unresolved` (error).
6. **Menores**: `Wall.adjacent_room_ids`; mallas desde la máscara unida (sin z-fighting); extras por
   nodo en el GLB (test que los relea); HDRI local en `viewer/public`; `max_room_area` en config; tests
   en cada paso; `convert` sale con código ≠ 0 si hay issues `error`; muestra desordenada con columnas
   hatch, ventana sin bloque, mampara a terraza, vano libre cocina-comedor, textos de área/NPT, COTAS,
   MOBILIARIO, marco y rótulo; tercera muestra `planta_2_unidades.dxf`.

## Avance por commits

| # | Paso | Estado |
|---|---|---|
| 1 | Esqueleto del repo, docs y esquema | ✅ |
| 2 | Generador de DXF de prueba + `expected.json` | ✅ |
| 3 | Config YAML, heurísticas de capas, issues | ✅ |
| 4 | Lector DXF: unidades, region, bloques, XREF | ✅ |
| 5 | Clusters de unidades + `planos inspect` | ✅ |
| 6 | Esquema pydantic + detección de muros (limpieza, pares, máscara) | ✅ |
| 7 | Vanos (bloques e inferidos) | ✅ |
| 8 | Ambientes, textos, áreas, `adjacent_room_ids` | ⏳ siguiente |
| 9 | `planos convert` → `space.json` + `report.md` | |
| 10 | Generación GLB (mallas desde máscara, booleanos, extras) | |
| 11 | Tests de equivalencia limpio vs desordenado | |
| 12 | Visor: base, carga de GLB, HDRI local | |
| 13 | Visor: modos órbita/planta/caminata y celular | |
| 14 | README completo | |
