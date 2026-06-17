#!/usr/bin/env python3
"""
Diagnóstico rápido: ¿tu extractor.py captura el bloque de nivelación?

Uso:
    python diagnostico_nivelacion.py ../e14_pdfs/PRE/.../un_acta.pdf
    (o sin argumento, usa la primera acta que encuentre en ../e14_pdfs)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import extractor as ex

# 1) ¿El código tiene la función de nivelación?
tiene_funcion = hasattr(ex, "nivelacion_por_celdas")
print(f"1. extractor.py tiene nivelacion_por_celdas(): "
      f"{'SÍ' if tiene_funcion else 'NO  ← tu extractor es una versión ANTIGUA'}")

if not tiene_funcion:
    print("\n→ Tu extractor.py no incluye la captura de nivelación.")
    print("  Reemplázalo por el extractor.py del ZIP más reciente y reintenta.")
    sys.exit(0)

# 2) ¿Devuelve las 3 casillas de nivelación en un acta real?
if len(sys.argv) > 1:
    pdf = sys.argv[1]
else:
    pdfs = list(Path("../e14_pdfs").rglob("*.pdf"))
    if not pdfs:
        print("\nNo encontré PDFs en ../e14_pdfs; pásame una ruta como argumento.")
        sys.exit(0)
    pdf = str(pdfs[0])

print(f"\n2. Probando sobre: {pdf}")
res = ex.procesar_acta(pdf, guardar=False)
nivel = [c for c in res.casillas if c.etiqueta in ("TOTAL_E11","TOTAL_URNA","TOTAL_INCINERADOS")]
print(f"   Casillas de nivelación devueltas: {len(nivel)} (esperado 3)")
for c in nivel:
    print(f"     {c.etiqueta:18s} tinta={c.tinta_pct:.1f}%  bbox={c.bbox}")
if res.aviso:
    print(f"   Aviso del extractor: {res.aviso}")
if len(nivel) < 3:
    print("\n→ El extractor tiene la función pero NO detecta el bloque en esta acta.")
    print("  Comparte este PDF para ajustar la detección de nivelación.")
else:
    print("\n→ Nivelación OK. Si no aparece en recortes_ocr, reexporta los recortes.")
