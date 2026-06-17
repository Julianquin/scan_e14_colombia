#!/usr/bin/env python3
"""
Fase 1 — Comparar estrategias de lectura: dígito-a-dígito vs número completo.

Sobre un conjunto de actas, lee cada casilla con las dos estrategias usando el
backend de OCR indicado, y reporta cuál acierta más. Para medir precisión hace
falta la "verdad" (los números reales); hay dos modos:

  A) MODO ETIQUETADO: le pasas un CSV con la verdad por casilla y mide aciertos.
  B) MODO COHERENCIA: sin verdad, usa el chequeo aritmético como proxy — una
     estrategia que produce más actas que CUADRAN aritméticamente es mejor.

Uso:
    # Modo coherencia sobre 100 actas (no necesita etiquetas)
    python comparar_ocr.py e14_pdfs --backend paddleocr --n 100

    # Modo etiquetado (si tienes verdad_casillas.csv)
    python comparar_ocr.py e14_pdfs --backend trocr --verdad verdad_casillas.csv
"""
from __future__ import annotations
import sys, csv, time, random, argparse
from pathlib import Path

# Importar el extractor (Fase 0) y los módulos de Fase 1
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import extractor as ex
import segmentacion as seg
import chequeo_aritmetico as chk
import ocr_backends
from comunes import CASILLAS_NUMERICAS


def leer_acta(pdf_path, backend, estrategia):
    """
    Procesa un acta con la Fase 0 y lee sus casillas numéricas con la estrategia
    indicada ('digitos' o 'numero'). Devuelve dict {etiqueta: int}.
    """
    res = ex.procesar_acta(pdf_path, guardar=False)
    # Necesitamos los recortes; reprocesamos en memoria por página
    import fitz, cv2, numpy as np
    doc = fitz.open(pdf_path)
    paginas = {}
    for p in range(min(3, len(doc))):
        img = ex.render_pagina(doc[p]); img = ex.corregir_inclinacion(img)
        paginas[p+1] = img

    numeros = {}
    for c in res.casillas:
        if c.etiqueta not in CASILLAS_NUMERICAS:
            continue
        img = paginas.get(c.pagina)
        if img is None:
            continue
        x, y, w, h = c.bbox
        crop = img[y:y+h, x:x+w]
        if not seg.tiene_contenido(crop):
            numeros[c.etiqueta] = 0      # casilla vacía = 0
            continue
        if estrategia == "numero":
            prep = seg.preparar_numero(crop)
            txt = backend.leer_numero(prep)
            numeros[c.etiqueta] = int(txt) if txt else 0
        else:  # digitos
            digs = seg.segmentar_digitos(crop)
            cifras = "".join(backend.leer_digito(d) or "" for d in digs)
            numeros[c.etiqueta] = int(cifras) if cifras else 0
    return numeros


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carpeta")
    ap.add_argument("--backend", default="paddleocr", help="paddleocr | trocr")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--verdad", default="", help="CSV con la verdad por casilla (modo etiquetado)")
    ap.add_argument("--salida", default="comparacion_ocr.csv")
    a = ap.parse_args()

    print(f"Cargando backend '{a.backend}' (puede tardar la primera vez)...")
    backend = ocr_backends.crear_backend(a.backend)

    pdfs = sorted(str(p) for p in Path(a.carpeta).rglob("*.pdf"))
    random.seed(42)
    pdfs = random.sample(pdfs, min(a.n, len(pdfs)))
    print(f"Comparando sobre {len(pdfs)} actas...\n")

    # Modo coherencia: contar cuántas cuadran con cada estrategia
    cuadran = {"digitos": 0, "numero": 0}
    tiempos = {"digitos": 0.0, "numero": 0.0}
    filas = []
    for pdf in pdfs:
        fila = {"pdf": pdf}
        for estrategia in ("digitos", "numero"):
            t0 = time.time()
            try:
                nums = leer_acta(pdf, backend, estrategia)
                r = chk.chequear(nums)
                cuadra = (r.cuadra_suma is True and r.cuadra_e11 is True)
                if cuadra:
                    cuadran[estrategia] += 1
                fila[f"{estrategia}_cuadra"] = int(bool(cuadra))
                fila[f"{estrategia}_suma"] = r.suma_calculada
                fila[f"{estrategia}_total"] = r.suma_total_leida
            except Exception as e:
                fila[f"{estrategia}_cuadra"] = ""
                fila[f"{estrategia}_error"] = str(e)[:60]
            tiempos[estrategia] += time.time() - t0
        filas.append(fila)

    print("="*60)
    print("RESULTADO (modo coherencia aritmética):")
    print(f"  Actas que CUADRAN leyendo dígito-a-dígito: {cuadran['digitos']}/{len(pdfs)}")
    print(f"  Actas que CUADRAN leyendo número completo: {cuadran['numero']}/{len(pdfs)}")
    print(f"\n  Tiempo dígito-a-dígito: {tiempos['digitos']:.1f}s")
    print(f"  Tiempo número completo: {tiempos['numero']:.1f}s")
    mejor = "dígito-a-dígito" if cuadran["digitos"] >= cuadran["numero"] else "número completo"
    print(f"\n  → Estrategia con más actas coherentes: {mejor}")
    print("="*60)

    with open(a.salida, "w", newline="", encoding="utf-8") as f:
        if filas:
            w = csv.DictWriter(f, fieldnames=sorted({k for fila in filas for k in fila}),
                               extrasaction="ignore")
            w.writeheader(); w.writerows(filas)
    print(f"\nDetalle por acta → {a.salida}")
    print("\nNota: 'cuadra' usa el chequeo aritmético como proxy de acierto.")
    print("Para precisión exacta, usa --verdad con un CSV etiquetado a mano.")


if __name__ == "__main__":
    main()
