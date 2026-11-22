# Contexto del proyecto

Startup peruana que vende a inmobiliarias una herramienta para mejorar la venta de departamentos en planos (preventa). La inmobiliaria entrega los planos de sus tipologías y nosotros generamos una experiencia 3D web donde cada comprador puede recorrer y decorar su futuro departamento con un link personalizado. El vendedor recibe datos de uso para saber quién está más interesado.

## Roadmap del MVP
- Fase 1: pipeline DXF → JSON del espacio → GLB + visor web simple  ← ACTUAL
- Fase 2: editor de decoración (catálogo de muebles GLB, estilos, acabados) + config por comprador
- Fase 3: links por comprador + backend (FastAPI + Postgres/Supabase) + tracking de eventos + panel del vendedor
- Fase 4: foto realista con IA (render + mapas de profundidad/normales → modelo de imagen con ControlNet)

## Stack
- Pipeline: Python 3.11+, uv, ezdxf, shapely, trimesh (+ manifold3d para booleanos), pydantic, typer, pytest
- Web: Vite + React + TypeScript + React Three Fiber + drei, pnpm

## Convenciones
- Código, nombres y commits en inglés; README y docs en español.
- Unidades internas siempre en metros. glTF con eje Y hacia arriba.
- Nada de valores mágicos: alturas, espesores y tolerancias van en config.
- Commits pequeños por paso; tests para cada parte del pipeline.
- Prioridad: robustez con planos reales desordenados antes que features.