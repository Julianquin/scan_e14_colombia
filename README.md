# ScanE14 — Auditoría técnica de actas E-14 (Presidencia Colombia 2026)

Sistema **reproducible y auditable** para procesar masivamente los 122.016
formularios E-14 (actas de mesa) publicados por la Registraduría, extraer su
contenido, leer los números y **detectar, cuantificar y documentar
inconsistencias** para revisión humana.

> **Principio rector:** el sistema **NO dictamina fraude**. Detecta *anomalías*
> y reúne *evidencia* (recortes + números + chequeos), y deja el juicio a una
> persona. Muchas anomalías son errores honestos de diligenciamiento o
> correcciones legítimas que los jurados documentan en el recuadro de
> constancias.

## Estado del proyecto

| Fase | Descripción | Estado |
|------|-------------|--------|
| Descarga | Bajar los 122.016 PDFs del visor oficial | ✅ Completada |
| **Fase 0** | Extraer de cada acta las casillas (nivelación + candidatos + agregados + constancias) | ✅ **Cerrada y validada con actas reales** |
| Fase 1 | OCR de los números (TrOCR en Kaggle) + chequeo aritmético | 🟡 En curso |
| Fase 2 | Cruce con resultados oficiales y entre ejemplares | ⬜ Pendiente |
| Fase 3 | Forense morfológico (tachones / enmendaduras) | ⬜ Pendiente |
| Fase 4 | Análisis estadístico (direccionalidad del error) | ⬜ Pendiente |
| Fase 5 | Tablero de revisión y trazabilidad | ⬜ Pendiente |

La arquitectura completa, el mapeo denuncia→fase y las decisiones técnicas están
en **[docs/ROADMAP.md](docs/ROADMAP.md)** (documento maestro).

## Estructura del repositorio

```
ScanE14/
├── descargar_e14.py        # scraper de PDFs (fase de descarga) — guía: docs/SCRAPING.md
├── extractor.py            # ★ FASE 0 — motor de extracción de casillas
├── comunes.py              # constantes E-14 y utilidades compartidas
├── procesar_lote.py        # procesamiento masivo multinúcleo (genera casillas_e14.csv)
├── probar_muestra.py       # prueba visual sobre una muestra (overlays)
├── revisar_plantilla.py    # revisar el recorte de agregados
├── diagnosticar_agregados.py  # diagnóstico del bloque de agregados
├── listar_anomalias.py     # genera el listado de actas a revisar
│
├── fase1/                  # FASE 1 — OCR + validación aritmética (ver fase1/README_FASE1.md)
│   ├── exportar_recortes.py   # prepara recortes para Kaggle
│   ├── ocr_trocr_kaggle.{py,ipynb}  # OCR TrOCR en GPU (Kaggle)
│   ├── combinar_resultados.py # integra OCR + chequeo aritmético
│   ├── chequeo_aritmetico.py  # valida suma(candidatos)+B+N+NM == SUMA_TOTAL == TOTAL_E11
│   ├── posiciones.py, segmentacion.py, ocr_backends.py
│   └── comparar_ocr.py, test_ocr_una_acta.py, diagnostico_nivelacion.py
│
├── docs/                   # documentación (ver docs/README.md como índice)
├── requirements.txt        # dependencias de Fase 0
└── requirements-fase1.txt  # dependencias de OCR (Fase 1)
```

Datos no versionados (ver `.gitignore`): `e14_pdfs/`, `recortes_ocr/`,
`resultados/`, PDFs, PNG y los JSON de entrada del scraper.

## Instalación (Fase 0)

```bash
pip install -r requirements.txt
```

## Flujo de trabajo (Fase 0)

```
PDFs (e14_pdfs/)
   │
   ├─[1] probar_muestra.py     → overlays visuales de una muestra
   ├─[2] revisar_plantilla.py  → confirmar el recorte de agregados
   ├─[3] procesar_lote.py      → genera resultados/casillas_e14.csv
   └─[4] listar_anomalias.py   → genera anomalias.csv (a revisar)
            │
            ▼
      entrada para la FASE 1 (OCR + chequeo aritmético)
```

Guías detalladas: **[docs/COMO_PROBAR.md](docs/COMO_PROBAR.md)** (probar) y
**[docs/PROCESAR_MASIVO.md](docs/PROCESAR_MASIVO.md)** (corrida completa).

## ¿Qué extrae la Fase 0?

De cada PDF (3 páginas, imagen escaneada) extrae **21 elementos**:

- **3 de NIVELACIÓN** (pág. 1): `TOTAL_E11`, `TOTAL_URNA`, `TOTAL_INCINERADOS`.
- **13 de VOTACIÓN** de los candidatos (págs. 1 y 2).
- **4 agregados** (pág. 2): `BLANCO`, `NULO`, `NO_MARCADO`, `SUMA_TOTAL`.
- **1 recuadro de CONSTANCIAS** (pág. 3).

Para cada elemento reporta si **tiene número escrito o está vacío** (vía un
porcentaje de "tinta" que ignora los bordes de la celda). Aún **no lee** el
número: eso es la Fase 1. El `TOTAL_E11` es la referencia contra la que la Fase 1
valida la `SUMA_TOTAL`.

## Salida: `resultados/casillas_e14.csv`

Una fila por acta, **62 columnas**: identificación (`pdf, dep, muni, zona,
puesto, mesa, archivo`), estado (`ok, n_casillas, uso_plantilla, aviso`), por
cada uno de los 21 elementos `tinta_<x>` y `tiene_<x>` (42 columnas), y 9 de
banderas de consistencia. Detalle de las banderas en
**[docs/BANDERAS.md](docs/BANDERAS.md)**.

## Documentación

Índice completo en **[docs/README.md](docs/README.md)**. Para entender el diseño
y el estado de cada fase, empieza por **[docs/ROADMAP.md](docs/ROADMAP.md)**.
