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
- Carga `public/models/demo.glb` o un GLB arrastrado.
- Modos: órbita, planta (cámara ortográfica cenital), caminata a 1.60 m (WASD + pointer lock en
  escritorio; joystick virtual + arrastre en celular; colisión simple con muros).
- Iluminación con `<Environment files=...>` usando un HDRI **local** en `viewer/public/` (sin CDN: las
  casetas de venta pueden tener mala conexión).
- Clic en un piso: nombre del ambiente y área útil. Para la unidad: área declarada si existe; si no,
  la calculada.

## Muestras (`samples/`)

Generadas por `pipeline/scripts/generate_samples.py`: departamento limpio, variante desordenada y
planta con 2 unidades.
