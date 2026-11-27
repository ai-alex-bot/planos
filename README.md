# Planos → 3D (Fase 1)

Convierte el plano DXF de una tipología de departamento en un modelo 3D (GLB) y lo muestra en un visor
web que funciona en el celular: vista en órbita, en planta y caminata en primera persona.

```
plano.dxf ──► planos convert ──► space.json + model.glb + report.md ──► visor web
```

Contexto del producto y roadmap: [claude.md](claude.md). Requerimientos y avance de la fase:
[docs/fase1-requerimientos.md](docs/fase1-requerimientos.md).

## Contenido

1. [Estructura del repo](#estructura-del-repo)
2. [Instalación](#instalación)
3. [Prueba rápida con el plano de ejemplo](#prueba-rápida-con-el-plano-de-ejemplo)
4. [De DWG a DXF (ODA File Converter)](#de-dwg-a-dxf-oda-file-converter)
5. [Procesar un plano nuevo](#procesar-un-plano-nuevo)
6. [El YAML de mapeo](#el-yaml-de-mapeo)
7. [Leer el reporte y resolver avisos](#leer-el-reporte-y-resolver-avisos)
8. [Visor web](#visor-web)
9. [Tests](#tests)
10. [Limitaciones conocidas](#limitaciones-conocidas)

## Estructura del repo

| Carpeta | Qué hay |
|---|---|
| `pipeline/` | Paquete Python con la CLI `planos` (DXF → `space.json` → GLB). |
| `viewer/` | Visor web: Vite + React + TypeScript + React Three Fiber. |
| `samples/` | DXF de prueba, sus YAML de mapeo y `expected.json` (verdad de terreno para los tests). |
| `docs/` | [Arquitectura](docs/arquitectura.md), [esquema de space.json](docs/esquema-space.md), [detección de muros, vanos y ambientes](docs/deteccion-muros.md). |

## Instalación

### Requisitos

- **uv** (gestor de Python): <https://docs.astral.sh/uv/getting-started/installation/>. No hace falta
  instalar Python aparte: uv descarga Python 3.12 la primera vez.
- **Node.js 20 o superior** y **pnpm**.

### pnpm

pnpm viene con Node a través de corepack:

```bash
corepack enable pnpm
```

En **Windows**, si Node está en `C:\Program Files` ese comando falla con `EPERM` (pide administrador).
Sin administrador, instala los accesos de pnpm en tu carpeta de usuario (ya está en el PATH):

```powershell
corepack enable --install-directory "$env:APPDATA\npm" pnpm
pnpm --version
```

### Dependencias

```bash
cd pipeline
uv sync              # crea pipeline/.venv con todo lo necesario

cd ../viewer
pnpm install
```

> Si tienes un entorno de conda/virtualenv activo, uv muestra un aviso sobre `VIRTUAL_ENV`: es
> inofensivo, uv usa igual `pipeline/.venv`.

## Prueba rápida con el plano de ejemplo

```bash
cd pipeline
uv run planos inspect ../samples/depto_2d_limpio.dxf
uv run planos convert ../samples/depto_2d_limpio.dxf -c ../samples/depto_2d_limpio.yaml -o out/demo

cd ../viewer
cp ../pipeline/out/demo/model.glb public/models/demo.glb   # el repo ya trae uno
pnpm dev
```

Abre la URL que muestra Vite (<http://localhost:5173>). Para verlo en el celular, conéctalo a la misma
red wifi y abre la dirección **Network** que imprime Vite (p. ej. `http://192.168.1.20:5173`). La
primera vez Windows puede pedir permiso en el firewall para Node: acéptalo en redes privadas.

Muestras incluidas (`samples/`):

| Archivo | Para qué sirve |
|---|---|
| `depto_2d_limpio.dxf` | Departamento de 2 dormitorios (~68 m² útiles) dibujado limpio, en metros. |
| `depto_2d_desordenado.dxf` | El mismo, en centímetros y con los problemas típicos de un plano real. |
| `planta_2_unidades.dxf` | Dos departamentos en el mismo dibujo (prueba de `region`). |

## De DWG a DXF (ODA File Converter)

El pipeline lee **DXF**. Si la inmobiliaria envía DWG, conviértelo con **ODA File Converter**
(gratuito, Windows/macOS/Linux): <https://www.opendesign.com/guestfiles/oda_file_converter>.

Con la interfaz:

1. *Input folder*: carpeta con los `.dwg`. *Output folder*: carpeta vacía de destino.
2. *Output version*: **ACAD2018**. *Output file type*: **DXF** (ASCII).
3. Marca *Audit each file* (repara errores menores del DWG) y pulsa **Start**.

Por línea de comandos (útil para lotes):

```bash
ODAFileConverter "C:\planos\dwg" "C:\planos\dxf" ACAD2018 DXF 0 1 "*.DWG"
#                 entrada         salida          versión  tipo recursivo auditar filtro
```

Antes de convertir, pide al arquitecto que haga **Bind** de las referencias externas (XREF). Un XREF
sin incrustar deja geometría fuera y `planos` lo reporta como error (`xref_unresolved`).

## Procesar un plano nuevo

```bash
cd pipeline
# 1. Ver qué trae el plano
uv run planos inspect C:/planos/dxf/tipologia_A.dxf

# 2. Escribir el YAML de mapeo (ver la sección siguiente) a partir de lo que mostró inspect

# 3. Convertir
uv run planos convert C:/planos/dxf/tipologia_A.dxf -c C:/planos/tipologia_A.yaml -o out/tipologia_A

# 4. Revisar out/tipologia_A/report.md; ajustar el YAML y repetir hasta que no queden errores
```

### `planos inspect`

Muestra todo lo necesario para armar el mapeo. Ejemplo con la muestra desordenada:

```
DXF AC1024 · $INSUNITS=0 · unidades: cm (origen: heuristic, ×0.01 → m)
                                   Capas
│ Capa       │ Categoría   │ Origen    │ Entidades │ Por tipo              │
│ COLUMNAS   │ structure   │ heuristic │         8 │ HATCH 8               │
│ COTAS      │ ignore      │ heuristic │         4 │ DIMENSION 3, MTEXT 1  │
│ MUROS      │ walls       │ heuristic │        75 │ LINE 75               │
│ PUERTAS    │ doors       │ heuristic │         8 │ INSERT 8              │
│ TAB-01     │ —           │ unmapped  │        62 │ LINE 62               │   ← ¡tabiques sin mapear!
│ TEXTOS     │ room_labels │ heuristic │        16 │ MTEXT 16              │
│ VENTANAS   │ windows     │ heuristic │         9 │ INSERT 6, LINE 3      │
                           Bloques usados (INSERT en el modelo)
│ Bloque │ Usos │ Capas    │ Vano       │ Tamaño local (unid. dibujo) │ Escalas X        │
│ MAMP-1 │    1 │ PUERTAS  │ glass_door │ 1 × 1                       │ 200              │
│ P1     │    7 │ PUERTAS  │ door       │ 1 × 1                       │ 70, 80, 90       │
                Grupos de muros (unidades)
│ # │ bbox (unid. dibujo) → usar en 'region' │ Tamaño (m) │
│ 1 │ [-12.5, -172.5, 1012.5, 712.5]         │      10.25 │
Avisos
  WARNING units_assumed: El DXF no declara unidades ($INSUNITS=0); ... se asume 'cm' (10.2 m).
  INFO layer_unmapped: La capa 'TAB-01' tiene 62 entidad(es) geométricas y no está mapeada ...
```

Qué mirar:

- **Unidades**: si dice `heuristic`, confírmalas en el YAML (`units`).
- **Capas con categoría `—`**: decide si son muros, columnas, textos… o algo a ignorar.
- **Bloques**: la columna *Vano* dice si cada bloque se tomará como puerta, ventana o mampara.
- **Grupos de muros**: si hay más de uno, el dibujo tiene varias unidades; usa `region`.
- Opciones: `--config mapeo.yaml` (ver cómo queda con tu mapeo), `--max-texts 0` (todos los textos),
  `--json` (salida para scripts).

### `planos convert`

Genera en la carpeta `-o`:

| Archivo | Contenido |
|---|---|
| `space.json` | Muros, vanos, ambientes, áreas, metadata y avisos ([esquema](docs/esquema-space.md)). |
| `model.glb` | Modelo 3D: `wall_001…`, `floor_<ambiente>`, `opening_door_01…`, con datos en los extras. |
| `report.md` | Resumen legible: áreas por ambiente, vanos y avisos con su ubicación. |

Código de salida: **0** sin errores (puede haber advertencias), **1** si hay algún aviso con severidad
`error` (los archivos se escriben igual para poder revisarlos), **2** si el archivo o el YAML no son
válidos.

## El YAML de mapeo

Un YAML por tipología (o por proyecto, si todas se dibujaron igual). **Todo es opcional**: un YAML
vacío usa las heurísticas y los valores por defecto. El mínimo útil suele ser `units` y las capas que
la heurística no reconoce.

### Paso a paso

1. **Unidades.** En Perú es común dibujar en metros o en centímetros. Si `inspect` dice `heuristic`, o
   el tamaño en metros no cuadra, fíjalas:
   ```yaml
   units: cm        # auto | m | cm | mm
   ```
2. **Muros.** Lista **todas** las capas con líneas de muro, incluidos tabiques y muros bajos. Al
   definir una categoría, la heurística de esa categoría deja de aplicarse: lista también las que sí
   se reconocían.
   ```yaml
   layers:
     walls: [MUROS, TAB-01]         # se aceptan comodines: "A-WALL*"
   ```
3. **Estructura.** Columnas y placas (polilíneas cerradas o hatch). Cierran esquinas y se modelan
   como muros:
   ```yaml
     structure: [COLUMNAS, PLACAS]
   ```
4. **Puertas y ventanas.** Capas donde están los bloques. Una ventana dibujada solo con líneas en la
   capa de ventanas también se detecta.
   ```yaml
     doors: [PUERTAS]
     windows: [VENTANAS, MAMPARAS]
   ```
   **Barandas y parapetos** (terrazas, balcones): si están dibujados con líneas en una capa propia,
   decláralos y se modelan como muros bajos de `heights.railing` (1.00 m) que cierran el ambiente
   (sirve para balcones volados). Con una sola línea se les da `geometry.railing_thickness`.
   ```yaml
     railings: [BARANDAS]
   ```
   Si la terraza no tiene nada dibujado en su lado abierto, el hueco se detecta solo y, como da a un
   ambiente exterior, se modela como baranda: parapeto y nada encima.
5. **Textos de ambientes.** Capas con los nombres ("SALA-COMEDOR", "DORM. 1", "S.H.") y, si las hay,
   las áreas ("12.50 m2", "A=12.50"). Los textos de NPT, cotas y notas se ignoran solos.
   ```yaml
     room_labels: [TEXTOS, AMBIENTES]
   ```
6. **Ignorar** capas que estorban (mobiliario, cotas, ejes, marco, rótulo). Muchas ya se ignoran por
   heurística.
   ```yaml
     ignore: [MOBILIARIO, COTAS, EJES, MARCO, ROTULO]
   ```
7. **Separadores de ambientes** (opcional). Si la cocina está abierta a la sala sin muro ni vano, el
   reporte dirá `room_multiple_labels`. Dibuja una línea en una capa nueva (p. ej. `LIMITE-AMBIENTE`)
   donde quieras separar y decláralo:
   ```yaml
     room_separators: [LIMITE-AMBIENTE]
   ```
8. **Bloques por nombre** (opcional). Solo si los bloques de vanos están en capas no mapeadas o
   quieres distinguir mamparas. Patrones con comodines, sin distinguir mayúsculas:
   ```yaml
   blocks:
     doors: ["PUERTA*", "P-*", "P[0-9]*"]
     windows: ["VENT*", "V-*", "V[0-9]*"]
     glass_doors: ["MAMP*"]          # mampara: alféizar 0.00, dintel 2.10
     railings: ["BARANDA*", "PARAPETO*"]   # baranda: parapeto de 1.00 m y nada encima
   ```
   El nombre del bloque manda sobre la capa: una `BARANDA-290` en la capa VENTANAS es baranda.
9. **Varias unidades en el mismo dibujo.** Copia de `inspect` el bbox del grupo que quieres (está en
   unidades del dibujo) y agrégale un margen:
   ```yaml
   region: [1200, -300, 2500, 900]   # xmin, ymin, xmax, ymax (unidades del DIBUJO)
   ```
10. **Áreas oficiales** de la inmobiliaria (recomendado). El visor muestra la declarada y nunca la
    calculada; el reporte avisa si difieren más del 5 %:
    ```yaml
    declared:
      area_techada_m2: 62.40
      area_libre_m2: 4.10          # terrazas, balcones, patios, jardines
    ```
    Los ambientes llamados TERRAZA, BALCÓN, PATIO o JARDÍN son **exteriores** (`is_outdoor`):
    cuentan como área libre y su borde abierto se modela como baranda.
11. **Techo de los ambientes exteriores.** Por defecto un ambiente exterior no tiene techo en el 3D.
    En Lima muchas terrazas quedan bajo la losa del piso de arriba: indícalo por nombre (o slug) y el
    comprador verá la losa encima (la baranda sigue igual y no hay nada entre ella y el techo):
    ```yaml
    rooms:
      "TERRAZA": {has_ceiling: true}
    ```
12. **Alturas y tolerancias** solo si el proyecto lo pide:
    ```yaml
    heights:
      floor_to_ceiling: 2.50       # default 2.40
      door_head: 2.10
      window_sill: 1.00
      window_head: 2.10
      railing: 1.00                # barandas y parapetos
    tolerances:
      wall_thickness_max: 0.45     # muros más gruesos que 0.40 m
      max_room_area: 80            # ambientes grandes que no son "sospechosos"
    geometry:
      ceiling: false               # no generar techos (por defecto sí; el visor los muestra al caminar)
    ```

Referencia completa de claves, valores por defecto y heurísticas de nombres de capa:
[docs/esquema-space.md](docs/esquema-space.md#yaml-de-mapeo). Ejemplos reales:
[samples/depto_2d_limpio.yaml](samples/depto_2d_limpio.yaml) y
[samples/depto_2d_desordenado.yaml](samples/depto_2d_desordenado.yaml).

Una clave mal escrita (p. ej. `murso:`) hace fallar la lectura del YAML con un mensaje claro, en vez de
ignorarse.

## Leer el reporte y resolver avisos

`report.md` empieza con el estado (✅ sin observaciones, ⚠️ advertencias, ❌ errores) y luego lista
áreas, ambientes, vanos y avisos con su ubicación en metros. Qué hacer con cada aviso:

| Aviso | Qué significa | Qué hacer |
|---|---|---|
| `xref_unresolved` (error) | El DXF referencia otro archivo que no está incrustado. | Pedir el plano con *Bind* de XREF. |
| `no_walls` / `region_empty` (error) | No hay muros en las capas mapeadas o dentro de `region`. | Revisar `layers.walls` y `region` con `inspect`. |
| `units_assumed` | Las unidades se adivinaron. | Fijar `units` en el YAML. |
| `layer_unmapped` | Una capa con geometría no está en ninguna categoría. | Agregarla a `walls`/`structure`/… o a `ignore`. |
| `multiple_units_detected` | Hay varios grupos de muros desconectados. | Elegir uno con `region` (el aviso trae los bbox). |
| `unpaired_wall_line` | Una línea de muro no tiene pareja paralela. | Muro más grueso que `wall_thickness_max`, línea suelta o capa equivocada. |
| `opening_inferred` | Un hueco sin bloque se tomó como baranda (borde de terraza/balcón), ventana (otro borde exterior o con líneas) o vano libre (interior). | Verificar el tipo; si es puerta, que el bloque esté en una capa de puertas. |
| `opening_without_wall` | Un bloque de puerta/ventana no está sobre ningún muro. | Bloque mal ubicado o muro en una capa no mapeada. |
| `room_without_name` | Ambiente sin texto de nombre adentro. | Mapear la capa de textos o pedir que se rotule. |
| `room_multiple_labels` | Dos nombres en un mismo ambiente. | Falta un muro/vano: usar `room_separators`. |
| `room_area_mismatch` | El área escrita en el plano no coincide con la medida. | Revisar el plano (a veces el texto es de otra versión). |
| `suspicious_area` | Ambiente menor a 1.5 m² o mayor a 60 m². | Suele indicar un muro faltante o un recinto que no es ambiente. |
| `area_mismatch` | El área declarada difiere más del 5 % de la calculada. | Confirmar el dato con la inmobiliaria o revisar el plano. |
| `duplicate_removed`, `gap_closed` (info) | Se limpiaron líneas duplicadas o huecos milimétricos. | Nada: es informativo. |

## Visor web

```bash
cd viewer
pnpm dev          # desarrollo, accesible desde el celular en la misma red
pnpm build        # genera viewer/dist: archivos estáticos para publicar en cualquier hosting
pnpm preview      # sirve el build localmente para probarlo
```

**Cargar un modelo**

- Por defecto carga `viewer/public/models/demo.glb`.
- `?model=tipologia_A.glb` carga `viewer/public/models/tipologia_A.glb` (copia ahí los GLB de cada
  tipología para una demo).
- Arrastrar un `.glb` sobre la ventana (escritorio) o usar el botón **Abrir GLB** (celular).
- `?modo=planta` o `?modo=caminar` abre directamente en ese modo; `?corte=1.4` cambia la altura del
  corte de la planta.

**Modos y controles** (botones abajo; en escritorio también teclas 1, 2, 3)

| Modo | Escritorio | Celular |
|---|---|---|
| **Órbita** | Arrastrar para girar, rueda para acercar, clic en un piso → ambiente y área útil. | Un dedo gira, pellizcar acerca, tocar un piso. |
| **Planta** | Plano cortado a 1.20 m: muros en negro, puertas y vanos como huecos, ventanas y mamparas con una línea azul, barandas como muro bajo; nombre y área de cada ambiente; clic en un ambiente. | Un dedo mueve, pellizcar acerca, tocar un ambiente. |
| **Caminar** | WASD o flechas (Shift corre), arrastrar para mirar. | Joystick abajo a la izquierda, arrastrar para mirar. |

Al caminar, los ojos están a 1.60 m, se ve el techo de los ambientes techados (solo en este modo),
los muros y alféizares detienen el paso (las puertas no) y arriba se muestra el ambiente actual.
La altura del corte de la planta se puede cambiar con `?corte=1.4` (entre 0.30 y 2.30 m).

El área de la unidad que se muestra es la **declarada** si el YAML la trae; si no, la calculada (y
lo dice).

La iluminación usa un HDRI incluido en el repo (`viewer/public/hdri/lebombo_1k.hdr`, CC0 de
[Poly Haven](https://polyhaven.com/a/lebombo)): el visor no depende de ningún CDN.

## Tests

```bash
cd pipeline && uv run pytest            # pipeline: lectura, muros, vanos, ambientes, GLB, equivalencias
cd viewer && pnpm test                  # visor: lectura de extras y movimiento
cd viewer && pnpm smoke                 # visor en un navegador real (requiere `pnpm dev` corriendo)
```

`pnpm smoke` usa el Edge instalado (`BROWSER_CHANNEL=chrome` para Chrome) vía Playwright, sin
descargar navegadores: prueba clic/toque en pisos, los tres modos, el joystick, las colisiones y que
no haya errores de consola, en escritorio y en un celular emulado.

Las muestras se regeneran con `uv run python scripts/generate_samples.py` (desde `pipeline/`); un
test avisa si `samples/expected.json` quedó desactualizado.

## Limitaciones conocidas

- **Dos unidades que comparten muro medianero** se detectan como una sola: usa `region` a mano.
- **Muros curvos**: los arcos se discretizan en tramos rectos que se emparejan; la huella queda
  facetada (en un muro de un cuarto de círculo de 3 m de radio, ~2.6 % menos de área que el arco
  ideal). Lo que no se logra emparejar queda reportado como `unpaired_wall_line`.
- **Un solo nivel** por archivo (dúplex: un DXF por piso).
- Fuera de alcance en esta fase: muebles, editor de decoración, render con IA, backend, conversión
  automática de DWG y planos en PDF o imagen.
