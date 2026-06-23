#!/usr/bin/env python3
"""
Prueba rápida del OCR sobre UNA sola acta, mostrando qué lee en cada casilla
con las dos estrategias. Úsalo para verificar que el backend funciona ANTES de
lanzar la comparación de 100 actas (que tarda).

Uso:
    python test_ocr_una_acta.py ../e14_pdfs/PRE/.../acta.pdf --backend paddleocr
"""
import sys, argparse
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import extractor as ex
import segmentacion as seg
import ocr_backends
import fitz

CASILLAS = (["TOTAL_E11","TOTAL_URNA","TOTAL_INCINERADOS"]
            + [f"cand_{i:02d}" for i in range(1,14)]
            + ["BLANCO","NULO","NO_MARCADO","SUMA_TOTAL"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--backend", default="paddleocr")
    a = ap.parse_args()

    print(f"Cargando backend '{a.backend}'...")
    backend = ocr_backends.crear_backend(a.backend)
    print("Backend cargado. Procesando acta...\n")

    res = ex.procesar_acta(a.pdf, guardar=False)
    doc = fitz.open(a.pdf)
    paginas = {}
    for p in range(min(3, len(doc))):
        img = ex.render_pagina(doc[p]); img = ex.corregir_inclinacion(img)
        paginas[p+1] = img

    print(f"{'CASILLA':18} {'TINTA':>6}  {'DÍGITOS':>10}  {'NÚMERO':>8}")
    print("-"*52)
    for c in res.casillas:
        if c.etiqueta not in CASILLAS:
            continue
        img = paginas.get(c.pagina)
        x,y,w,h = c.bbox
        crop = img[y:y+h, x:x+w]
        if not seg.tiene_contenido(crop):
            print(f"{c.etiqueta:18} {'vacía':>6}  {'-':>10}  {'0':>8}")
            continue
        # Estrategia dígitos
        digs = seg.segmentar_digitos(crop)
        por_digito = "".join(backend.leer_digito(d) or "?" for d in digs)
        # Estrategia número
        prep = seg.preparar_numero(crop)
        completo = backend.leer_numero(prep)
        print(f"{c.etiqueta:18} {c.tinta_pct:>5.1f}%  {por_digito:>10}  {completo:>8}")

if __name__ == "__main__":
    main()
