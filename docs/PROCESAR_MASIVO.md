# Procesamiento masivo — Fase 0 a escala (122.000 actas)

La Fase 0 está cerrada y validada con actas reales (ver `docs/ROADMAP.md`).
Ahora puedes procesar toda la carpeta con `procesar_lote.py`.

## Qué hace
- Recorre recursivamente `e14_pdfs/` buscando todos los PDFs.
- Procesa cada acta en paralelo usando TODOS los núcleos de tu CPU.
- Vuelca a un CSV consolidado: por cada acta, los 21 valores de tinta + un
  marcador binario "tiene número" + la ubicación (dep/muni/zona/puesto/mesa)
  deducida de la ruta del archivo.
- NO guarda los recortes PNG (serían ~2M de archivos). Solo metadatos.
- Es REANUDABLE: si lo interrumpes (Ctrl+C) o se corta, al relanzar el mismo
  comando continúa donde quedó.

## Uso
```bash
# Prueba con 500 actas primero (recomendado)
python procesar_lote.py e14_pdfs --salida resultados --limite 500

# Corrida completa (todos los núcleos)
python procesar_lote.py e14_pdfs --salida resultados

# Controlar número de procesos
python procesar_lote.py e14_pdfs --salida resultados --workers 8
```

## Salida
- `resultados/casillas_e14.csv`  → una fila por acta, 62 columnas
- `resultados/_resumen_lote.json` → estadísticas de la corrida

## Columnas del CSV (62)
- `pdf, dep, muni, zona, puesto, mesa, archivo` → identificación (7)
- `ok, n_casillas, uso_plantilla, aviso` → estado del procesamiento (4)
- `tinta_<x>` → % de tinta de cada uno de los 21 elementos (21)
- `tiene_<x>` → 1 si el elemento tiene número escrito, 0 si vacío (21)
- banderas de consistencia → `n_cand_con_voto, suma_vacia_con_votos,
  sin_ningun_voto, suma_con_todo_vacio, todos_candidatos_llenos,
  agregados_sin_suma, e11_vacio_con_votos, tiene_constancias,
  prioridad_revision` (9)

Los 21 elementos son: TOTAL_E11, TOTAL_URNA, TOTAL_INCINERADOS,
cand_01..cand_13, BLANCO, NULO, NO_MARCADO, SUMA_TOTAL y CONSTANCIAS.

## Estimación de tiempo
A ~0.3 actas/s por núcleo (incluye render a 200 DPI de 3 páginas).
Con 8 núcleos ≈ 2.4 actas/s → 122.000 actas ≈ 14 horas.
Con 16 núcleos ≈ 7 horas. Como es reanudable, puedes hacerlo por tramos.

## Importante: este CSV es la ENTRADA de la Fase 1
Por ahora el CSV dice qué casillas TIENEN número (tinta), pero todavía NO
el número en sí. Eso es la Fase 1 (OCR/HTR). El marcador "tiene_" ya permite
validaciones útiles: p.ej. si SUMA_TOTAL está vacía pero hay votos, o si una
mesa tiene patrones anómalos de casillas llenas.
