# Documentación de ScanE14

Índice de la carpeta `docs/`. La portada del proyecto y el quickstart están en
el [README raíz](../README.md).

## Empieza aquí

- **[ROADMAP.md](ROADMAP.md)** — Documento maestro: objetivo, restricciones de
  capacidad, mapeo *denuncia documentada → fase*, las 6 fases en detalle,
  principios rectores y registro de decisiones técnicas.

## Guías de uso (Fase 0)

- **[COMO_PROBAR.md](COMO_PROBAR.md)** — Probar la extracción sobre una muestra
  de PDFs y leer los overlays de revisión.
- **[PROCESAR_MASIVO.md](PROCESAR_MASIVO.md)** — Corrida masiva (las 122.016
  actas): rendimiento, reanudación y estructura del CSV de salida.
- **[REVISAR_PLANTILLA.md](REVISAR_PLANTILLA.md)** — Localización del bloque de
  agregados (método `celdas+lineas`, respaldo por plantilla) y cómo
  diagnosticar actas problemáticas.
- **[BANDERAS.md](BANDERAS.md)** — Las banderas de consistencia (ALTA/MEDIA/INFO)
  y cómo listar las actas a revisar.
- **[SCRAPING.md](SCRAPING.md)** — Descarga masiva de los PDFs con
  `descargar_e14.py` (fase de descarga, ya completada).

## Fase 1 (OCR + validación)

La documentación de la Fase 1 vive junto a su código en
**[../fase1/README_FASE1.md](../fase1/README_FASE1.md)** (índice de la fase),
con **[../fase1/FLUJO_KAGGLE.md](../fase1/FLUJO_KAGGLE.md)** (pipeline de OCR en
GPU) y **[../fase1/POSICIONES.md](../fase1/POSICIONES.md)** (registro de
posiciones por casilla).
