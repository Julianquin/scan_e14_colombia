# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).

## [1.0.0] — 2026-06-16

Primera versión estable. **Fase 0 cerrada y validada con actas reales**; Fase 1
(OCR + chequeo aritmético) en curso. Fases 2–5 diseñadas en `docs/ROADMAP.md`.

### Añadido
- **Fase 0 — extracción** (`extractor.py`): recorta de cada PDF E-14 los 21
  elementos (3 nivelación + 13 candidatos + 4 agregados + constancias) con
  enfoque híbrido (contornos + plantilla de respaldo), deskew, anclaje a líneas
  reales (`celdas+lineas`) y límite derecho real de la tabla.
- **Procesamiento masivo** (`procesar_lote.py`): CSV de 62 columnas con banderas
  de consistencia (ALTA/MEDIA/INFO), paralelo y reanudable.
- **Descarga** (`descargar_e14.py`): scraper robusto de los 122.016 PDFs.
- **Fase 1 (en curso)**: registro de posiciones (`posiciones.py`), segmentación
  (`segmentacion.py`), backends de OCR (`ocr_backends.py`), flujo de TrOCR en
  Kaggle y chequeo aritmético (`chequeo_aritmetico.py`).

### Cambiado (esta organización de la v1)
- `README.md` raíz reescrito como portada; `docs/README.md` convertido en índice.
- Cifras corregidas en la documentación: **21 elementos** por acta y **62
  columnas** de CSV (antes aparecían 18 y 47/55 según el documento).
- Documentación de agregados unificada en `docs/REVISAR_PLANTILLA.md`.
- `docs/SCRAPING.md` reescrito como guía (ya no incrusta el código del script).
- `requirements.txt` ahora incluye `requests`; nuevo `requirements-fase1.txt`.

### Factorizado
- Nuevo módulo `comunes.py` (constantes E-14, `parsear_ruta`, `solo_digitos`)
  como fuente única de verdad. Eliminada la duplicación de estas definiciones en
  `procesar_lote.py`, `fase1/exportar_recortes.py`, `fase1/comparar_ocr.py`,
  `fase1/chequeo_aritmetico.py` y `fase1/ocr_backends.py`.

### Decisiones técnicas
Registradas en `docs/ROADMAP.md` §6 (método `celdas+lineas`, eliminación del
anclaje, borde derecho real, PaddleOCR descartado en CPU, etc.).
