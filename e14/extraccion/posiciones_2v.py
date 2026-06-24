#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
posiciones_2v.py — geometría de las casillas del acta E-14 de SEGUNDA VUELTA.

La 2da vuelta tiene solo 9 casillas de valor (3 nivelación + 2 candidatos + 4
agregados), todas en la columna derecha (votación). Las coordenadas son
RELATIVAS (fracciones de la página), así que sirven para los tres ejemplares
pese a que se escanean a tamaños muy distintos (CLAVEROS ~840px de ancho,
TRANSMISIÓN/DELEGADOS ~2400px). Calibrado y validado sobre la mesa
01/001/01/01/001 en los tres ejemplares.

Solo se procesa la PÁGINA 1 (la 2 son constancias/firmas).

Uso:
    # QA visual: recorta las 9 casillas de un acta a un montaje
    python posiciones_2v.py probar acta.pdf --salida montaje.png

    # Exporta los recortes de un árbol de PDFs (un ejemplar) para el clasificador
    python posiciones_2v.py exportar data/segunda_vuelta/e14_pdfs_claveros CLAVEROS \
           --salida recortes_claveros
"""
from __future__ import annotations
import argparse, csv, re
from pathlib import Path
import numpy as np

# Columna de votación (x relativo) y, por casilla, (nombre, centro_y, alto) relativos
CELL_X = (0.720, 0.975)
CELDAS_2V = [
    ("TOTAL_E11",         0.263, 0.032),
    ("TOTAL_URNA",        0.295, 0.032),
    ("TOTAL_INCINERADOS", 0.327, 0.032),
    ("CANDIDATO_01",      0.460, 0.050),
    ("CANDIDATO_02",      0.615, 0.050),
    ("BLANCO",            0.726, 0.032),
    ("NULO",              0.758, 0.032),
    ("NO_MARCADO",        0.789, 0.032),
    ("SUMA_TOTAL",        0.820, 0.032),
]


def _fitz():
    import fitz  # PyMuPDF
    return fitz


def _cv2():
    import cv2
    return cv2


def render_pagina1(pdf_path, dpi=200):
    fitz = _fitz(); cv2 = _cv2()
    doc = fitz.open(pdf_path)
    pm = doc[0].get_pixmap(dpi=dpi)
    img = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, pm.n)
    return cv2.cvtColor(img[:, :, :3], cv2.COLOR_RGB2GRAY) if pm.n >= 3 else img[:, :, 0]


def recortar_celdas(pdf_path, dpi=200):
    """Devuelve {etiqueta: imagen_gris (ndarray)} con las 9 casillas de valor."""
    img = render_pagina1(pdf_path, dpi)
    H, W = img.shape
    x0, x1 = int(CELL_X[0] * W), int(CELL_X[1] * W)
    out = {}
    for nombre, yc, h in CELDAS_2V:
        y0, y1 = int((yc - h / 2) * H), int((yc + h / 2) * H)
        out[nombre] = img[max(0, y0):min(H, y1), x0:x1]
    return out


_TOKENS = re.compile(r"E14_PRE_(\d+)_(\d+)_(\d+)_(\d+)_(\d+)_(\d+)_(\d+)", re.I)


def parsear_clave(pdf_path):
    """
    (dep, muni, zona, puesto, mesa) desde la ruta/nombre, soportando los dos árboles:
      - CLAVEROS: .../docs/E14/dd/mm/zz/pp/E14_PRE_dd_mm_zzz_pp_ss_mmm_id.pdf
      - TRANS/DELEG: .../PRE/dd/mm/zz/pp/mesa/<hash>.pdf
    """
    p = Path(pdf_path)
    m = _TOKENS.search(p.name)
    if m:  # claveros: del nombre de fichero
        dep, muni, zona, puesto, _sub, mesa, _id = m.groups()
        return dep, muni, zona, puesto, mesa
    partes = [x for x in p.parts]
    if "PRE" in partes:  # transmisión/delegados: 5 carpetas tras 'PRE'
        i = partes.index("PRE")
        sub = partes[i + 1:i + 6]
        if len(sub) == 5:
            return tuple(sub)
    raise ValueError(f"No pude extraer códigos de: {pdf_path}")


def probar(pdf_path, salida):
    cv2 = _cv2()
    celdas = recortar_celdas(pdf_path)
    filas = []
    for nombre, _yc, _h in CELDAS_2V:
        c = celdas[nombre]
        c = cv2.resize(c, (360, 64))
        lab = np.full((64, 170), 255, np.uint8)
        cv2.putText(lab, nombre[:17], (2, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1)
        filas.append(np.hstack([lab, c]))
    cv2.imwrite(str(salida), np.vstack(filas))
    print(f"Montaje QA -> {salida}")


def exportar(dir_pdfs, ejemplar, salida, dpi=200, limite=None):
    cv2 = _cv2()
    dir_pdfs = Path(dir_pdfs); salida = Path(salida); salida.mkdir(parents=True, exist_ok=True)
    pdfs = [p for p in dir_pdfs.rglob("*.pdf") if "_logs" not in p.parts]
    if limite:
        pdfs = pdfs[:limite]
    idx = (salida / "indice_recortes.csv").open("w", newline="", encoding="utf-8")
    idx.write("ejemplar,dep,muni,zona,puesto,mesa,etiqueta,ruta\n")
    n_ok = n_err = 0
    for i, pdf in enumerate(pdfs, 1):
        try:
            dep, muni, zona, puesto, mesa = parsear_clave(pdf)
            celdas = recortar_celdas(pdf, dpi)
            clave = f"{ejemplar}_{dep}_{muni}_{zona}_{puesto}_{mesa}"
            for nombre, c in celdas.items():
                ruta = salida / f"{clave}__{nombre}.png"
                cv2.imwrite(str(ruta), c)
                idx.write(f"{ejemplar},{dep},{muni},{zona},{puesto},{mesa},{nombre},{ruta}\n")
            n_ok += 1
        except Exception as exc:
            n_err += 1
            print(f"  ! {pdf.name}: {exc}")
        if i % 200 == 0:
            print(f"{i}/{len(pdfs)} | ok={n_ok} err={n_err}")
    idx.close()
    print(f"\nHecho. actas ok={n_ok} err={n_err}. Recortes + indice_recortes.csv en {salida}/")


def main():
    ap = argparse.ArgumentParser(description="Casillas E-14 2da vuelta (geometría relativa)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probar"); p.add_argument("pdf"); p.add_argument("--salida", default="montaje_2v.png")
    p.add_argument("--dpi", type=int, default=200)
    p = sub.add_parser("exportar"); p.add_argument("dir_pdfs"); p.add_argument("ejemplar")
    p.add_argument("--salida", default="recortes_2v"); p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--limite", type=int, default=None)
    a = ap.parse_args()
    if a.cmd == "probar":
        probar(a.pdf, a.salida)
    elif a.cmd == "exportar":
        exportar(a.dir_pdfs, a.ejemplar.upper(), a.salida, a.dpi, a.limite)


if __name__ == "__main__":
    main()