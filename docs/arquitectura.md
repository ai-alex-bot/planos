# Arquitectura – Fase 1

```
DXF ──► planos.dxf.reader ──► geometry (cleanup → walls → openings → rooms) ──► space.json
                                                                                   │
                                                          planos.model3d.build ◄───┘
                                                                   │
                                                               model.glb ──► viewer (R3F)
                                                          planos.report ──► report.md
```

## Pipeline (`pipeline/`)

| Módulo | Responsabilidad |
|---|---|
| `cli.py` | Comandos `inspect` y `convert` (typer). `convert` sale con código ≠ 0 si hay issues `error`. |
| `config.py` | Modelos pydantic del YAML, valores por defecto y heurísticas de capas. |
| `schema.py` | Modelos de `space.json` (ver [esquema-space.md](esquema-space.md)). |
| `issues.py` | Colector de issues con código, severidad, mensaje y ubicación. |
| `dxf/reader.py` | Carga DXF, unidades, recorte por `region`, iteración de entidades con explosión de bloques. |
| `dxf/inspect.py` | Resumen de capas, bloques, textos, unidades y clusters. |
| `geometry/*` | Limpieza, muros, vanos, ambientes (ver [deteccion-muros.md](deteccion-muros.md)). |
| `model3d/build.py` | Extrusión, booleanos y exportación GLB con extras por nodo. |
| `report.py` | `report.md`: resumen, áreas por ambiente, issues. |

## Visor (`viewer/`)

- Vite + React + TypeScript + React Three Fiber + drei.
- Carga `public/models/demo.glb`, `?model=otro.glb` (desde `public/models/`), un GLB arrastrado o uno
  elegido con **Abrir GLB** (en el celular no hay arrastrar y soltar). `?modo=planta|caminar` abre en
  ese modo.
- Iluminación con un HDRI **local** (`public/hdri/lebombo_1k.hdr`, CC0 de Poly Haven): sin CDN, las
  casetas de venta pueden tener mala conexión.
- Modos (botones abajo o teclas 1/2/3):
  - **Órbita**: cámara en perspectiva encuadrada al modelo (considera el FOV horizontal en
    vertical); clic/toque en un piso → nombre y área útil.
  - **Planta**: cámara ortográfica cenital con el norte del plano arriba, solo paneo y zoom, etiquetas
    con nombre y área de cada ambiente (`label_position` de los extras). Plano de corte horizontal
    global (`renderer.clippingPlanes`) a 1.20 m (`src/config.ts`, `?corte=`): los muros cortados se
    rellenan con una copia oscura que solo dibuja caras interiores (los muros del GLB son sólidos
    cerrados, verificado en tests); ventanas y mamparas se dibujan como una línea desde los nodos
    `opening_*`. El raycaster de three.js ignora el corte, así que los clics descartan intersecciones
    por encima de él; las copias oscuras, las etiquetas y las líneas no reciben clics. Sin sombras.
  - **Caminata**: ojos a 1.60 m, empieza en el ambiente techado más grande mirando al centro.
    WASD/flechas (Shift corre) en escritorio; **joystick** en pantallas táctiles; arrastrar para
    mirar. Colisión con rayos a 0.30/1.00/1.50 m: los alféizares detienen, las puertas no. Muestra
    "Estás en …" con el ambiente bajo los pies. Muestra los techos (`ceiling_*`, ocultos en los otros
    modos), que no proyectan sombra ni participan en clics, colisiones o detección del ambiente.
- Área de la unidad: la declarada si existe; si no, la calculada (de los extras de la escena).
- Pruebas: `pnpm test` (vitest: lectura de extras, movimiento) y `pnpm smoke` (Playwright con el Edge
  instalado: clic/toque en pisos, los 3 modos, joystick, colisiones, sin errores de consola).

## Muestras (`samples/`)

Generadas por `pipeline/scripts/generate_samples.py`: departamento limpio, variante desordenada y
planta con 2 unidades.
