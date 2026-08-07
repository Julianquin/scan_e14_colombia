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
import segmentacion

# Columna de votación (x relativo) y, por casilla, (nombre, centro_y, alto) relativos.
# x1 bajó de 0.975 a 0.940: medido por densidad de píxeles oscuros sobre una
# mesa real, el borde derecho de la tabla cae en 0.945-0.953 del ancho de
# página (ligero sesgo de rotación entre filas), y 0.975 lo dejaba DENTRO del
# recorte pegado al borde derecho — visible como barra negra vertical en QA.
CELL_X = (0.720, 0.940)

# Margen de seguridad hacia adentro, en fracción del ancho/alto de cada celda.
# margen_top es mayor porque TOTAL_E11 y BLANCO (primera fila de cada grupo:
# nivelación / agregados) capturan la barra del encabezado de sección justo
# arriba de ellas — el resto de filas no tiene ese problema pero el recorte
# extra no les hace daño (es margen en blanco).
MARGEN_CELDA = 0.02
MARGEN_TOP = 0.16

# Aspecto (alto/ancho) esperado de un acta bien formada: escaneo autor-recortado
# a la franja angosta del formulario, ~3.0 en los tres ejemplares (medido sobre
# 9000 actas reales: medianas 3.01/3.00/3.09). Fuera de +-20% ya no es un
# escaneo normal — es una FOTO DE CELULAR (aspecto ~1.78, tipo 1080x1920) o un
# escaneo de hoja completa (A4/Carta/Legal, aspecto ~1.4-1.65) con la franja
# del acta desplazada dentro de la página. En ambos casos las coordenadas
# relativas de CELDAS_2V caen en cualquier cosa menos las casillas reales
# (verificado: sobre una foto real, las 9 casillas cayeron 100% en el fondo).
ASPECTO_ESTANDAR = 3.0
ASPECTO_TOLERANCIA = 0.20

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


def info_formato(pdf_path):
    """Metadata barata de la página 1 (dims de la imagen incrustada), SIN
    rasterizar: extract_image copia los bytes del XObject, no decodifica
    píxeles. Sirve para filtrar antes de gastar cómputo en recortar_celdas."""
    fitz = _fitz()
    doc = fitz.open(pdf_path)
    page = doc[0]
    imgs = page.get_images(full=True)
    if not imgs:
        return {"n_paginas": doc.page_count, "img_w": 0, "img_h": 0, "aspecto": 0.0}
    base = doc.extract_image(imgs[0][0])
    w, h = base["width"], base["height"]
    return {"n_paginas": doc.page_count, "img_w": w, "img_h": h,
            "aspecto": (h / w) if w else 0.0}


def es_formato_estandar(pdf_path, aspecto_esperado=ASPECTO_ESTANDAR, tolerancia=ASPECTO_TOLERANCIA):
    """True si el aspecto (alto/ancho) del acta cae dentro de +-tolerancia del
    esperado. False = fuera de rango (foto de celular, escaneo de hoja
    completa, etc.) — no aplicar CELDAS_2V a estas sin tratamiento especial."""
    info = info_formato(pdf_path)
    if not info["aspecto"]:
        return False, info
    desviacion = abs(info["aspecto"] - aspecto_esperado) / aspecto_esperado
    return desviacion <= tolerancia, info


def _dpi_nativo_de_pagina(doc, page, dpi_min=150, dpi_max=600):
    """DPI real de la imagen incrustada en página 1, a partir de su ancho en
    píxeles contra el ancho de página en puntos (72 pt/in). CLAVEROS es JPEG
    a ~300 DPI; DELEGADOS/TRANSMISION tienen un MediaBox 1:1 con los píxeles
    de origen (~72 DPI) — ver nota en render_pagina1."""
    imgs = page.get_images(full=True)
    if not imgs or page.rect.width <= 0:
        return dpi_min
    base = doc.extract_image(imgs[0][0])
    dpi = 72.0 * base["width"] / page.rect.width
    return max(dpi_min, min(dpi_max, dpi))


def dpi_nativo(pdf_path, dpi_min=150, dpi_max=600):
    """Como _dpi_nativo_de_pagina pero abriendo el PDF — usar solo para
    inspección puntual; render_pagina1 ya lo calcula sin reabrir el archivo."""
    fitz = _fitz()
    doc = fitz.open(pdf_path)
    return _dpi_nativo_de_pagina(doc, doc[0], dpi_min, dpi_max)


def render_pagina1(pdf_path, dpi=200, color=False):
    """Nunca renderiza por DEBAJO del DPI nativo real de la imagen incrustada
    (dpi_efectivo = max(dpi pedido, dpi nativo)). Sin esto, CLAVEROS (fuente
    ~300 DPI) se downsamplea a dpi=200 mientras que DELEGADOS/TRANSMISION
    (MediaBox inflado, ~72 DPI nativo) se upsamplean al mismo dpi=200 —
    incluso pidiendo el mismo dpi, CLAVEROS terminaba con ~7.6x MENOS píxeles
    por celda que DELEGADOS, y leía peor en el piloto OCR pese a ser la
    fuente de mejor calidad.
    """
    fitz = _fitz(); cv2 = _cv2()
    doc = fitz.open(pdf_path)
    page = doc[0]
    dpi_efectivo = max(dpi, _dpi_nativo_de_pagina(doc, page))
    pm = page.get_pixmap(dpi=int(round(dpi_efectivo)))
    img = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, pm.n)
    if color:
        return cv2.cvtColor(img[:, :, :3], cv2.COLOR_RGB2BGR) if pm.n >= 3 else cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(img[:, :, :3], cv2.COLOR_RGB2GRAY) if pm.n >= 3 else img[:, :, 0]


def recortar_celdas(pdf_path, dpi=200, color=False, margen=MARGEN_CELDA, margen_top=MARGEN_TOP):
    """Devuelve {etiqueta: imagen (ndarray)} con las 9 casillas de valor.

    color=True conserva BGR (necesario para morfología: densidad de tinta,
    color de pluma). Por defecto sigue en gris para no romper el flujo de OCR.

    margen: recorta hacia adentro esa fracción del ancho/alto de cada celda,
    como seguridad general. margen_top recorta más arriba (ver MARGEN_TOP).
    """
    img = render_pagina1(pdf_path, dpi, color)
    H, W = img.shape[:2]
    x0, x1 = int(CELL_X[0] * W), int(CELL_X[1] * W)
    mx = int((x1 - x0) * margen)
    x0, x1 = x0 + mx, x1 - mx
    out = {}
    for nombre, yc, h in CELDAS_2V:
        y0, y1 = int((yc - h / 2) * H), int((yc + h / 2) * H)
        mtop = int((y1 - y0) * margen_top)
        mbot = int((y1 - y0) * margen)
        y0, y1 = y0 + mtop, y1 - mbot
        out[nombre] = img[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]
    return out


_TOKENS = re.compile(r"E14_PRE_(\w+)_(\w+)_(\w+)_(\w+)_(\w+)_(\w+)_(\d+)", re.I)


def parsear_clave(pdf_path):
    """
    (dep, muni, zona, puesto, mesa) desde la ruta/nombre, soportando los dos árboles:
      - CLAVEROS: .../docs/E14/dd/mm/zz/pp/E14_PRE_dd_mm_zzz_tok4_pp_mesa_id.pdf
      - TRANS/DELEG: .../PRE/dd/mm/zz/pp/mesa/<hash>.pdf

    OJO CLAVEROS: el token 4 del nombre de archivo NO es el puesto (es otro
    campo del portal de escrutinios, p.ej. "07" en
    E14_PRE_44_001_099_07_08_001_6832.pdf). El puesto real es la carpeta
    contenedora (token 5 del nombre) — usar el token 4 colapsaba ~40% de las
    mesas de CLAVEROS a claves erróneas (puestos 08 y 09 de ese ejemplo caían
    en la misma clave), corrompiendo el cruce en comparar_ejemplares.py.
    """
    p = Path(pdf_path)
    m = _TOKENS.search(p.name)
    if m:  # claveros: dep/muni/zona/mesa del nombre; puesto de la carpeta
        dep, muni, zona, _tok4, tok5, mesa, _id = m.groups()
        partes = p.parts
        puesto = tok5
        if "E14" in partes:
            i = partes.index("E14")
            if len(partes) > i + 4:
                puesto = partes[i + 4]
        return dep, muni, zona, puesto, mesa
    partes = [x for x in p.parts]
    if "PRE" in partes:  # transmisión/delegados: 5 carpetas tras 'PRE'
        i = partes.index("PRE")
        sub = partes[i + 1:i + 6]
        if len(sub) == 5:
            return tuple(sub)
    raise ValueError(f"No pude extraer códigos de: {pdf_path}")


def limpiar_recorte(c):
    """binarizar_ink (quita el marco gris de CLAVEROS) + quitar_barras_borde
    (quita barras sólidas de borde en DELEGADOS/TRANSMISION) — en cadena
    porque atacan dos artefactos distintos, uno claro y uno oscuro."""
    return segmentacion.quitar_barras_borde(segmentacion.binarizar_ink(c))


def probar(pdf_path, salida, color=False, margen=MARGEN_CELDA, limpiar=True):
    cv2 = _cv2()
    celdas = recortar_celdas(pdf_path, color=color, margen=margen)
    if limpiar and not color:
        celdas = {k: limpiar_recorte(v) for k, v in celdas.items()}
    filas = []
    for nombre, _yc, _h in CELDAS_2V:
        c = celdas[nombre]
        c = cv2.resize(c, (360, 64))
        lab = np.full((64, 170, 3) if color else (64, 170), 255, np.uint8)
        cv2.putText(lab, nombre[:17], (2, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1)
        filas.append(np.hstack([lab, c]))
    cv2.imwrite(str(salida), np.vstack(filas))
    print(f"Montaje QA -> {salida}")


def exportar(dir_pdfs, ejemplar, salida, dpi=200, limite=None, color=False, margen=MARGEN_CELDA,
             incluir_atipicas=False, limpiar=True):
    """Exporta los recortes de un árbol de PDFs. Antes de recortar, filtra por
    aspecto (ver es_formato_estandar): las actas fuera de rango (fotos de
    celular, escaneos de hoja completa) NO se recortan con CELDAS_2V —eso
    produciría basura silenciosa (ruido leído como dígitos, aritmética que
    'no cuadra' por una falla de segmentación, no del acta)— sino que se
    registran en cola_revision.csv para tratamiento aparte.

    limpiar=True (default; ignorado si color=True): pasa cada recorte por
    segmentacion.quitar_barras_borde antes de guardarlo — borra las líneas
    rectas de borde que TrOCR confunde con un '1' (confirmado en el piloto:
    tanto en CLAVEROS como en TRANSMISION/DELEGADOS), sin recortar ni
    redimensionar, así que no corre el riesgo de preparar_numero (que en 2da
    vuelta borraba ceros manuscritos legítimos de BLANCO/NULO/NO_MARCADO —
    ver comentario en segmentacion.py). Verificado: no toca ceros reales.
    """
    cv2 = _cv2()
    dir_pdfs = Path(dir_pdfs); salida = Path(salida); salida.mkdir(parents=True, exist_ok=True)
    pdfs = [p for p in dir_pdfs.rglob("*.pdf") if "_logs" not in p.parts]
    if limite:
        pdfs = pdfs[:limite]
    idx = (salida / "indice_recortes.csv").open("w", newline="", encoding="utf-8")
    idx.write("ejemplar,dep,muni,zona,puesto,mesa,etiqueta,ruta\n")
    cola = (salida / "cola_revision.csv").open("w", newline="", encoding="utf-8")
    cola.write("ejemplar,dep,muni,zona,puesto,mesa,motivo,aspecto,img_w,img_h,ruta\n")
    n_ok = n_err = n_atipica = 0
    for i, pdf in enumerate(pdfs, 1):
        try:
            dep, muni, zona, puesto, mesa = parsear_clave(pdf)
            estandar, info = es_formato_estandar(pdf)
            if not estandar and not incluir_atipicas:
                motivo = "sin_imagen" if not info["aspecto"] else "aspecto_atipico"
                cola.write(f"{ejemplar},{dep},{muni},{zona},{puesto},{mesa},{motivo},"
                          f"{info['aspecto']:.4f},{info['img_w']},{info['img_h']},{pdf}\n")
                n_atipica += 1
                continue
            celdas = recortar_celdas(pdf, dpi, color=color, margen=margen)
            clave = f"{ejemplar}_{dep}_{muni}_{zona}_{puesto}_{mesa}"
            for nombre, c in celdas.items():
                if limpiar and not color:
                    c = limpiar_recorte(c)
                ruta = salida / f"{clave}__{nombre}.png"
                cv2.imwrite(str(ruta), c)
                idx.write(f"{ejemplar},{dep},{muni},{zona},{puesto},{mesa},{nombre},{ruta}\n")
            n_ok += 1
        except Exception as exc:
            n_err += 1
            print(f"  ! {pdf.name}: {exc}")
        if i % 200 == 0:
            print(f"{i}/{len(pdfs)} | ok={n_ok} atipicas={n_atipica} err={n_err}")
    idx.close(); cola.close()
    print(f"\nHecho. actas ok={n_ok}  atipicas(cola_revision.csv)={n_atipica}  err={n_err}.")
    print(f"Recortes + indice_recortes.csv en {salida}/")
    if n_atipica:
        print(f"{n_atipica} actas en {salida}/cola_revision.csv (fuera de aspecto "
              f"{ASPECTO_ESTANDAR:.2f}+-{ASPECTO_TOLERANCIA:.0%}) — NO se recortaron, revisar aparte.")


def main():
    ap = argparse.ArgumentParser(description="Casillas E-14 2da vuelta (geometría relativa)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probar"); p.add_argument("pdf"); p.add_argument("--salida", default="montaje_2v.png")
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--color", action="store_true", help="conserva color (para morfología, ej. CLAVEROS)")
    p.add_argument("--margen", type=float, default=MARGEN_CELDA,
                   help="recorte hacia adentro por celda, fracción 0-1 (evita las líneas reales de la tabla)")
    p.add_argument("--no-limpiar", dest="limpiar", action="store_false",
                   help="previsualiza el recorte CRUDO (sin quitar_barras_borde), para revisar "
                        "alineación geométrica tal cual sale de recortar_celdas (default: limpio, "
                        "tal como lo ve el OCR)")
    p = sub.add_parser("exportar"); p.add_argument("dir_pdfs"); p.add_argument("ejemplar")
    p.add_argument("--salida", default="recortes_2v"); p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--limite", type=int, default=None)
    p.add_argument("--color", action="store_true", help="conserva color (para morfología, ej. CLAVEROS)")
    p.add_argument("--margen", type=float, default=MARGEN_CELDA,
                   help="recorte hacia adentro por celda, fracción 0-1 (evita las líneas reales de la tabla)")
    p.add_argument("--incluir-atipicas", action="store_true",
                   help="fuerza el recorte también en actas de aspecto atípico (fotos, hoja completa); "
                        "por defecto se mandan a cola_revision.csv sin recortar")
    p.add_argument("--no-limpiar", dest="limpiar", action="store_false",
                   help="desactiva quitar_barras_borde (activado por defecto: borra líneas rectas de "
                        "borde que TrOCR confunde con '1', sin tocar dígitos reales)")
    a = ap.parse_args()
    if a.cmd == "probar":
        probar(a.pdf, a.salida, a.color, a.margen, a.limpiar)
    elif a.cmd == "exportar":
        exportar(a.dir_pdfs, a.ejemplar.upper(), a.salida, a.dpi, a.limite, a.color, a.margen,
                 a.incluir_atipicas, a.limpiar)


if __name__ == "__main__":
    main()