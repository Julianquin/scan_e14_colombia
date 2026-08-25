#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dataset de dígitos EN COLOR para 2da vuelta (CLAVEROS).

Por qué existe: CLAVEROS es JPEG RGB 8 bits a ~300 dpi (1260x3897), mientras
DELEGADOS/TRANSMISION son PNG **binarizados de 1 bit** a ~860 px de ancho —
2,1x menos píxeles y sin niveles de gris (ver docs/FORENSE_COLOR.md). El
pipeline de Fase 1 binariza todo con umbral fijo, lo que iguala CLAVEROS por
abajo y desperdicia su ventaja. Este módulo saca las cajas de dígito
**sin binarizar**, conservando los niveles de gris.

OJO: guarda las cajas en RGB, pero **el color medido NO ayuda** (empeora ~4
puntos de cuadre frente a la escala de grises — ver la tabla en
`clasificador_color.py`). Se guardan en RGB solo para poder repetir esa
comparación; entrenar y leer siempre con `--gris`.

Geometría: cada casilla de valor tiene 3 sub-casillas. Medido sobre 25 actas
reales (perfil de oscuridad por columna), los dígitos caen centrados en
x = 0.15 / 0.50 / 0.85 del ancho de la casilla -> **partir en tercios** es
correcto; las líneas divisorias de CLAVEROS son demasiado tenues para
detectarlas de forma fiable, y no hace falta.

Autoetiquetado: no hay etiquetas humanas de 2da vuelta. Se arranca leyendo con
el `digitnet.pt` de 1ra vuelta (que es un clasificador POR DÍGITO 0-9, así que
sirve entre vueltas) sobre la versión binarizada, y se conservan como etiquetas
solo las actas cuya aritmética CUADRA — si las 9 casillas leídas satisfacen
suma(candidatos)+B+N+NM == SUMA_TOTAL == TOTAL_E11, es muy improbable que el
OCR haya acertado la ecuación equivocándose en los dígitos. Es el mismo truco
de `clasificador_digitos.exportar_dataset`, aplicado a 2da vuelta y en color.

Uso:
    # piloto: 800 actas -> npz con cajas RGB + etiquetas por aritmética
    python -m e14.ocr.dataset_color construir \
        data/segunda_vuelta/e14_pdfs_claveros \
        --salida data/segunda_vuelta/digitos_color_piloto.npz --limite 800
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import cv2

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ / "extraccion"))

import posiciones_2v as P                     # noqa: E402
from e14.comunes import CAND_2V               # noqa: E402
from e14.ocr.chequeo_aritmetico import chequear  # noqa: E402

TAM = 48            # lado de la caja RGB que consume la CNN
TAM_BIN = 28        # lo que espera digitnet.pt (1ra vuelta)


# ------------------------------- segmentación --------------------------------
def cajas_de_casilla(bgr: np.ndarray, tam: int = TAM) -> list[np.ndarray]:
    """Parte una casilla de valor en sus 3 sub-casillas (tercios) y las
    reescala a tam x tam SIN recortar al bbox de tinta: la posición del dígito
    dentro de su sub-casilla es informativa, y un bbox por umbral se rompe con
    el traspaso del reverso (bleed-through) que CLAVEROS sí muestra."""
    h, w = bgr.shape[:2]
    if h < 4 or w < 12:
        return []
    bordes = [0, w // 3, 2 * w // 3, w]
    return [cv2.resize(bgr[:, bordes[i]:bordes[i + 1]], (tam, tam),
                       interpolation=cv2.INTER_AREA) for i in range(3)]


def _normaliza_bin(caja_bgr: np.ndarray) -> np.ndarray:
    """Versión binaria 28x28 estilo MNIST (bbox de tinta cuadrado y centrado),
    que es lo que espera el digitnet.pt de 1ra vuelta."""
    g = cv2.cvtColor(caja_bgr, cv2.COLOR_BGR2GRAY)
    bw = (g < 150).astype(np.uint8) * 255      # ver segmentacion.binarizar_ink
    ys, xs = np.where(bw > 0)
    if len(xs) < 8:
        return np.zeros((TAM_BIN, TAM_BIN), np.uint8)
    rec = bw[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    s = max(rec.shape)
    cuad = np.zeros((s, s), np.uint8)
    oy, ox = (s - rec.shape[0]) // 2, (s - rec.shape[1]) // 2
    cuad[oy:oy + rec.shape[0], ox:ox + rec.shape[1]] = rec
    d = cv2.resize(cuad, (20, 20), interpolation=cv2.INTER_AREA)
    out = np.zeros((TAM_BIN, TAM_BIN), np.uint8)
    out[4:24, 4:24] = d
    return out


def cajas_de_acta(pdf, tam: int = TAM):
    """{casilla: [3 cajas RGB]} para las 9 casillas de valor de 2da vuelta."""
    celdas = P.recortar_celdas(pdf, color=True)
    out = {}
    for nombre, bgr in celdas.items():
        cajas = cajas_de_casilla(bgr, tam)
        if len(cajas) == 3:
            out[nombre] = cajas
    return out


# --------------------------------- lectura -----------------------------------
def cargar_digitnet(ruta="models/digitnet.pt", dev="cpu"):
    import torch
    from e14.ocr.clasificador_digitos import construir_red
    sds = torch.load(ruta, map_location=dev, weights_only=False)
    if not isinstance(sds, list):
        sds = [sds]
    redes = []
    for sd in sds:
        r = construir_red()
        r.load_state_dict(sd)
        r.eval().to(dev)
        redes.append(r)
    return redes


def leer_acta(cajas: dict, redes, dev="cpu") -> dict:
    """Lee las 9 casillas con el ensemble binario. Devuelve {casilla: int}."""
    import torch
    nombres, lote = [], []
    for nombre, tres in cajas.items():
        for c in tres:
            nombres.append(nombre)
            lote.append(_normaliza_bin(c))
    if not lote:
        return {}
    x = torch.from_numpy(np.stack(lote)).float().div(255).unsqueeze(1).to(dev)
    with torch.no_grad():
        p = sum(torch.softmax(r(x), 1) for r in redes) / len(redes)
    dig = p.argmax(1).cpu().numpy()
    valores = {}
    for i in range(0, len(nombres), 3):
        nom = nombres[i]
        valores[nom] = int("".join(str(d) for d in dig[i:i + 3]))
    return valores


def leer_acta_48(cajas: dict, red, dev, gris=False) -> dict:
    """Lee con un modelo de `clasificador_color` (entrada 48x48, 3 canales).
    Es el lector del BOOTSTRAPPING: cada ronda usa el mejor modelo disponible
    para etiquetar más actas que la anterior."""
    import torch
    from e14.ocr.clasificador_color import a_gris
    nombres, lote = [], []
    for nombre, tres in cajas.items():
        for c in tres:
            nombres.append(nombre)
            lote.append(c)
    if not lote:
        return {}
    arr = np.stack(lote)
    if gris:
        arr = a_gris(arr)
    x = torch.from_numpy(arr).permute(0, 3, 1, 2).float().div(255).to(dev)
    with torch.no_grad():
        dig = red(x).argmax(1).cpu().numpy()
    return {nombres[i]: int("".join(str(d) for d in dig[i:i + 3]))
            for i in range(0, len(nombres), 3)}


# -------------------------------- construcción --------------------------------
def construir(dir_pdfs, salida, limite=None, modelo="models/digitnet.pt", dev="cpu",
              modelo_48=None, gris=False, desde=0):
    """`modelo_48`: si se pasa, etiqueta con un modelo de clasificador_color en
    vez del digitnet binario de 1ra vuelta (ronda 2+ del bootstrapping)."""
    dir_pdfs = Path(dir_pdfs)
    pdfs = [p for p in dir_pdfs.rglob("*.pdf") if "_logs" not in p.parts]
    pdfs = pdfs[desde: desde + limite if limite else None]
    print(f"actas a procesar: {len(pdfs):,}   (dispositivo de lectura: {dev})")

    if modelo_48:
        from e14.ocr.clasificador_color import cargar
        red48, dev = cargar(modelo_48, dev)
        print(f"etiquetando con modelo 48x48: {modelo_48}" + ("  [gris]" if gris else "  [color]"))
        redes = None
    else:
        red48 = None
        redes = cargar_digitnet(modelo, dev)
    X, y, meta = [], [], []
    n_cuadra = n_no = n_err = n_degenerada = 0

    for i, pdf in enumerate(pdfs, 1):
        try:
            estandar, _ = P.es_formato_estandar(pdf)
            if not estandar:
                n_err += 1
                continue
            cajas = cajas_de_acta(pdf)
            if len(cajas) != 9:
                n_err += 1
                continue
            valores = (leer_acta_48(cajas, red48, dev, gris) if red48 is not None
                       else leer_acta(cajas, redes, dev))
            # Un acta leída como TODO CEROS satisface la aritmética de forma
            # trivial (0+0+0 == 0 == 0) y entraría al dataset con 27 etiquetas
            # '0' falsas. Una mesa sin votantes en el E-11 no existe. Sin este
            # filtro, un modelo colapsado se auto-envenena el entrenamiento.
            if valores.get("TOTAL_E11", 0) == 0 and valores.get("SUMA_TOTAL", 0) == 0:
                n_degenerada += 1
                continue
            r = chequear(valores, cand=CAND_2V)
            # se exigen AMBAS ecuaciones: que la suma cuadre y que además
            # coincida con TOTAL_E11. Con una sola es mucho más fácil que
            # cuadre por casualidad con dígitos mal leídos.
            if not (r.cuadra_suma and r.cuadra_e11):
                n_no += 1
                continue
            n_cuadra += 1
            clave = "_".join(P.parsear_clave(pdf))
            for nombre, tres in cajas.items():
                v = f"{valores[nombre]:03d}"
                for pos, caja in enumerate(tres):
                    X.append(caja)
                    y.append(int(v[pos]))
                    meta.append(f"{clave}|{nombre}|{pos}")
        except Exception:
            n_err += 1
        if i % 100 == 0:
            print(f"  {i}/{len(pdfs)} | cuadra={n_cuadra} no_cuadra={n_no} "
                  f"degenerada={n_degenerada} err={n_err}")

    if not X:
        print("Sin actas que cuadren: no hay etiquetas que guardar.")
        return
    X = np.stack(X).astype(np.uint8)
    y = np.array(y, np.int64)
    np.savez_compressed(salida, X=X, y=y, meta=np.array(meta))
    print(f"\nActas que CUADRAN: {n_cuadra:,} / {len(pdfs):,} "
          f"({100*n_cuadra/max(1,len(pdfs)):.1f}%)  | no cuadran={n_no:,} err={n_err:,}")
    if n_degenerada:
        print(f"Descartadas por leerse TODO CEROS: {n_degenerada:,}  "
              f"<- si son muchas, el modelo lector está colapsado")
    print(f"Cajas etiquetadas: {len(y):,}  shape={X.shape}")
    print(f"Distribución de dígitos: {np.bincount(y, minlength=10).tolist()}")
    print(f"-> {salida}")


def main():
    ap = argparse.ArgumentParser(description="Dataset de dígitos EN COLOR (CLAVEROS, 2da vuelta)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("construir")
    p.add_argument("dir_pdfs")
    p.add_argument("--salida", default="digitos_color.npz")
    p.add_argument("--limite", type=int, default=None)
    p.add_argument("--modelo", default="models/digitnet.pt")
    p.add_argument("--dev", default="cpu", help="cpu o cuda")
    p.add_argument("--modelo-48", default=None,
                   help="modelo de clasificador_color para etiquetar (bootstrapping ronda 2+)")
    p.add_argument("--gris", action="store_true", help="usar con un --modelo-48 entrenado en gris")
    p.add_argument("--desde", type=int, default=0, help="saltar las primeras N actas")
    a = ap.parse_args()
    if a.cmd == "construir":
        construir(a.dir_pdfs, a.salida, a.limite, a.modelo, a.dev, a.modelo_48, a.gris, a.desde)


if __name__ == "__main__":
    main()
