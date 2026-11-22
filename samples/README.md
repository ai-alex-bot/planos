# Muestras

DXF de prueba y configs de mapeo YAML. Se generan con `pipeline/scripts/generate_samples.py`
(ver README principal). Se versionan para poder probar `planos inspect` / `planos convert` sin
regenerarlos.

| Archivo | Contenido |
|---|---|
| `depto_2d_limpio.dxf` | Departamento típico de Lima, 2 dormitorios (~65 m²), en metros, capas bien nombradas. |
| `depto_2d_desordenado.dxf` | Mismo departamento en centímetros, con huecos de milímetros, líneas duplicadas, capa mal nombrada, columnas con hatch, ventana sin bloque, mampara, vano libre, textos de área/NPT, cotas, mobiliario y marco con rótulo. |
| `planta_2_unidades.dxf` | Dos departamentos lado a lado (prueba de `multiple_units_detected` y `region`). |
