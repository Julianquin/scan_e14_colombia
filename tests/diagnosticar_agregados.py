#!/usr/bin/env python3
"""
Diagnóstico del bloque de agregados sobre PDFs concretos.

Muestra qué detecta localizar_bloque_agregados (las 5 líneas y el separador
vertical) y por qué, si falla, cae al respaldo. Útil para entender los casos
que el listado marca con ORIGEN=anclaje/plantilla.

Uso:
    python diagnosticar_agregados.py acta1.pdf acta2.pdf ...
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import extractor as ex
import fitz, cv2, numpy as np


def diagnosticar(pdf_path):
    doc = fitz.open(pdf_path)
    if len(doc) < 2:
        print(f"  {pdf_path}: <2 páginas"); return
    img = ex.render_pagina(doc[1]); img = ex.corregir_inclinacion(img)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)

    print(f"\n{Path(pdf_path).name[:40]}  (página {w}x{h}px)")

    # Líneas horizontales detectadas en la franja de agregados
    y_ini, y_fin = int(h*0.68), int(h*0.95)
    lineas04 = ex._detectar_lineas_h(binary, w, y_ini, y_fin, 0.4)
    lineas025 = ex._detectar_lineas_h(binary, w, y_ini, y_fin, 0.25)
    print(f"  Líneas H (umbral 0.40): {len(lineas04)} → {[f'{y/h:.3f}' for y in lineas04]}")
    print(f"  Líneas H (umbral 0.25): {len(lineas025)} → {[f'{y/h:.3f}' for y in lineas025]}")

    grupo = ex._buscar_5_lineas_regulares(lineas04, h) or ex._buscar_5_lineas_regulares(lineas025, h)
    if grupo:
        gaps = [grupo[i+1]-grupo[i] for i in range(4)]
        print(f"  ✓ 5 líneas regulares: {[f'{y/h:.3f}' for y in grupo]}  gaps={gaps}")
        x_sep = ex._detectar_separador_vertical(binary, w, h, grupo[0], grupo[-1])
        print(f"  Separador vertical: {f'x={x_sep} ({x_sep/w:.3f})' if x_sep else 'NO detectado (usará 0.66)'}")
    else:
        print(f"  ✗ NO se encontraron 5 líneas regulares → caerá al respaldo")
        # Mostrar por qué: gaps de las líneas detectadas
        ls = sorted(lineas025)
        if len(ls) >= 2:
            gaps = [ls[i+1]-ls[i] for i in range(len(ls)-1)]
            print(f"    Separaciones entre líneas: {gaps}")
            print(f"    Rango esperado de fila: {int(h*0.018)}-{int(h*0.040)}px")

    info = ex.localizar_bloque_agregados(img)
    aggs, origen = ex.agregados_por_celdas(img, [])
    print(f"  → ORIGEN final: {origen}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python diagnosticar_agregados.py acta1.pdf [acta2.pdf ...]")
        sys.exit(1)
    for pdf in sys.argv[1:]:
        diagnosticar(pdf)
