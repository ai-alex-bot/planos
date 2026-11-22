# Planos → 3D (Fase 1)

Pipeline que convierte el plano DXF de una tipología de departamento en un modelo 3D (GLB) y un visor
web para recorrerlo. Ver [claude.md](claude.md) para el contexto y el roadmap.

> En construcción. Instalación y uso completos llegan al cerrar la Fase 1.

## Estructura

- `pipeline/` – paquete Python con la CLI `planos`.
- `viewer/` – visor web (Vite + React + React Three Fiber).
- `samples/` – DXF de prueba y configs de mapeo.
- `docs/` – [arquitectura](docs/arquitectura.md), [esquema de space.json](docs/esquema-space.md),
  [detección de muros](docs/deteccion-muros.md).

## Desarrollo rápido

```bash
cd pipeline
uv sync
uv run planos --version
uv run pytest
```
