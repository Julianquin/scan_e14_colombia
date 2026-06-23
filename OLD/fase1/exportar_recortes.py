#!/usr/bin/env python3
"""
Fase 1 (local) — Exporta los recortes de las casillas CON número para enviarlos
al notebook de GPU (Kaggle/Colab) donde correrá el OCR.

Solo exporta casillas con tinta (las vacías = 0, no necesitan OCR). Cada recorte
se guarda como PNG con un nombre que codifica su procedencia, y se genera un
índice CSV que el notebook usará para saber a qué mesa/casilla pertenece cada
imagen.

Estructura de nombre de cada PNG:
    {dep}-{muni}-{zona}-{puesto}-{mesa}__{etiqueta}.png

Uso:
    # A partir de la carpeta de PDFs (procesa y exporta de una vez)
    python exportar_recortes.py ../e14_pdfs --salida recortes_ocr --limite 1000

    # Solo casillas concretas (por defecto todas las numéricas)
    python exportar_recortes.py ../e14_pdfs --salida recortes_ocr
"""
from __future__ import annotations
import sys, csv, argparse, os
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import extractor as ex
import segmentacion as seg
import posiciones
import cv2
import fitz
from comunes import CASILLAS_NUMERICAS, parsear_ruta


def procesar_uno(args) -> list:
    """Procesa un acta y devuelve filas de índice de los recortes guardados."""
    pdf_path, salida = args
    salida = Path(salida)
    ubic = parsear_ruta(pdf_path)
    clave = f"{ubic['ejemplar']}-{ubic['dep']}-{ubic['muni']}-{ubic['zona']}-{ubic['puesto']}-{ubic['mesa']}"
# → DELEGADOS-03-004-002-04-007__cand_10.png
    filas = []
    try:
        res = ex.procesar_acta(pdf_path, guardar=False)
        doc = fitz.open(pdf_path)
        paginas = {}
        for p in range(min(3, len(doc))):
            img = ex.render_pagina(doc[p]); img = ex.corregir_inclinacion(img)
            paginas[p+1] = img

        for c in res.casillas:
            if c.etiqueta not in CASILLAS_NUMERICAS:
                continue
            img = paginas.get(c.pagina)
            if img is None:
                continue
            x, y, w, h = c.bbox
            crop = img[y:y+h, x:x+w]

            if not seg.tiene_contenido(crop):
                # Casilla VACÍA: se registra igualmente (vacío = 0), pero no se
                # exporta PNG porque no hay nada que leer con OCR. Dejar
                # constancia evita que el chequeo aritmético "no sepa" que existe.
                filas.append({**ubic, "etiqueta": c.etiqueta,
                              "archivo": "", "tinta": c.tinta_pct,
                              "n_posiciones": 0, "tipos_posicion": "",
                              "n_digitos": 0, "banderas": "casilla_vacia;espacio_sin_anular"})
                continue

            # Casilla con contenido: quitar SOLO barras de borde (no filtrar
            # contenido) y registrar el estado de cada posición.
            reg = posiciones.registrar_casilla(crop)
            crop_limpio = reg.crop_limpio
            nombre = f"{clave}__{c.etiqueta}.png"
            cv2.imwrite(str(salida / nombre), crop_limpio)
            tipos = "|".join(p.tipo for p in reg.posiciones)
            filas.append({**ubic, "etiqueta": c.etiqueta,
                          "archivo": nombre, "tinta": c.tinta_pct,
                          "n_posiciones": reg.n_posiciones,
                          "tipos_posicion": tipos,
                          "n_digitos": reg.n_digitos,
                          "banderas": ";".join(reg.banderas)})
    except Exception as e:
        filas.append({**ubic, "etiqueta": "ERROR", "archivo": "",
                      "tinta": "", "error": str(e)[:80]})
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carpeta")
    ap.add_argument("--salida", default="recortes_ocr")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    a = ap.parse_args()

    salida = Path(a.salida); salida.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(str(p) for p in Path(a.carpeta).rglob("*.pdf"))
    if a.limite:
        pdfs = pdfs[:a.limite]
    print(f"Exportando recortes de {len(pdfs):,} actas con {a.workers} procesos...")

    indice = salida / "indice_recortes.csv"
    nuevo = not indice.exists()
    f = open(indice, "a", newline="", encoding="utf-8")
    campos = ["ejemplar","dep","muni","zona","puesto","mesa","etiqueta","archivo","tinta",
          "n_posiciones","tipos_posicion","n_digitos","banderas","error"]
    w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
    if nuevo:
        w.writeheader()

    total_recortes = 0
    hechas = 0
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = [pool.submit(procesar_uno, (p, str(salida))) for p in pdfs]
        for fut in as_completed(futs):
            for fila in fut.result():
                w.writerow(fila)
                if fila.get("archivo"):
                    total_recortes += 1
            hechas += 1
            if hechas % 200 == 0:
                f.flush()
                print(f"  {hechas:,}/{len(pdfs):,} actas | {total_recortes:,} recortes")
    f.close()
    print(f"\nListo: {total_recortes:,} recortes en {salida}")
    print(f"Índice: {indice}")
    print(f"\nAhora comprime la carpeta y súbela como dataset a Kaggle:")
    print(f"  zip -r recortes_ocr.zip {salida}")
    print(f"Luego usa el notebook ocr_trocr_kaggle.ipynb para leer los números.")


if __name__ == "__main__":
    main()
