#!/usr/bin/env python3
"""
Fase 1 — Segmentación de dígitos dentro de una casilla de voto.

Cada casilla del E-14 tiene 3 posiciones (centenas/decenas/unidades), cada una
con un punto pre-impreso. Este módulo ofrece dos estrategias para preparar el
contenido de cara al OCR:

  1. segmentar_digitos(crop)  → aísla cada dígito como un recorte individual
                                (para leer dígito a dígito).
  2. preparar_numero(crop)    → limpia el recorte completo (para leer el número
                                entero de una vez).

La comparación entre ambas se hace en comparar_ocr.py.
"""
from __future__ import annotations
import cv2
import numpy as np


def _binarizar_sin_bordes(gray: np.ndarray) -> np.ndarray:
    """Binariza (texto=blanco) y elimina líneas de borde largas."""
    h, w = gray.shape
    _, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    # Eliminar columnas/filas que son líneas largas (bordes de la celda)
    col_frac = binary.sum(axis=0) / 255 / h
    binary[:, col_frac > 0.6] = 0
    row_frac = binary.sum(axis=1) / 255 / w
    binary[row_frac > 0.6, :] = 0
    return binary


def limpiar_para_ocr(crop: np.ndarray) -> np.ndarray:
    """
    Prepara un recorte para el OCR quedándose SOLO con los dígitos y recortando
    a su bounding box. Descarta el ruido de borde que confunde al OCR:

      - Barras de borde (de la celda actual o de las vecinas): componentes muy
        altos y estrechos que cruzan casi toda la altura del recorte.
      - Residuos / fragmentos: componentes de área mucho menor que la del dígito
        más grande (incluye trozos de barra rota y los puntos pre-impresos).

    Este enfoque por componentes es más robusto que cortar por columnas: no
    depende de umbrales de posición (que cada acta rompe distinto), sino de la
    forma y el tamaño de cada mancha de tinta. Un residuo a la izquierda que
    antes el OCR leía como '1' (p.ej. 104 → 1104) se elimina aquí.

    Si no se detecta ningún dígito claro, devuelve el recorte en gris tal cual.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop.copy()
    h, w = gray.shape
    if h < 6 or w < 6:
        return gray

    # Binarizar y quitar líneas horizontales largas (bordes sup/inf), que de lo
    # contrario unirían dígitos y barras en un solo componente.
    _, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    row_frac = binary.sum(axis=1) / 255 / w
    binary[row_frac > 0.6, :] = 0

    # Cerrar trazos rotos de un mismo dígito (sin fusionar dígitos vecinos)
    cerrado = cv2.morphologyEx(
        binary, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 11)))

    n, lab, stats, _ = cv2.connectedComponentsWithStats(cerrado, connectivity=8)
    if n <= 1:
        return gray

    comps = [{"x": stats[i][0], "y": stats[i][1], "w": stats[i][2],
              "h": stats[i][3], "area": stats[i][4]} for i in range(1, n)]

    # 1) Descartar primero las barras de borde (muy altas y estrechas), porque
    #    si no inflan la referencia de tamaño de los dígitos.
    def es_barra(c):
        ratio = c["h"] / max(1, c["w"])
        return ratio > 4.0 and c["h"] > h * 0.85
    sin_barras = [c for c in comps if not es_barra(c)]
    if not sin_barras:
        return gray

    # 2) Referencia de dígito: altura y área del mayor componente NO-barra.
    h_ref = max(c["h"] for c in sin_barras)
    area_ref = max(c["area"] for c in sin_barras)

    # 3) Un dígito tiene altura comparable a la de referencia Y es un TRAZO (no
    #    una mancha sólida). Un punto pre-impreso, aunque sea grueso, llena casi
    #    todo su bounding box (relleno alto); un dígito manuscrito deja huecos
    #    (relleno bajo). Esta es la señal que separa puntos gruesos de dígitos.
    digitos = []
    for c in sin_barras:
        relleno = c["area"] / max(1, c["w"] * c["h"])
        alto_ok = c["h"] >= h_ref * 0.5
        area_ok = c["area"] >= area_ref * 0.20
        es_mancha = relleno > 0.62        # punto pre-impreso: bbox casi lleno
        if alto_ok and area_ok and not es_mancha:
            digitos.append(c)

    if not digitos:
        return gray

    xs0 = min(c["x"] for c in digitos)
    ys0 = min(c["y"] for c in digitos)
    xs1 = max(c["x"] + c["w"] for c in digitos)
    ys1 = max(c["y"] + c["h"] for c in digitos)
    m = 10
    return gray[max(0, ys0 - m):min(h, ys1 + m),
                max(0, xs0 - m):min(w, xs1 + m)]


def binarizar_ink(crop: np.ndarray, umbral: int = 150) -> np.ndarray:
    """
    Blanco/negro puro por umbral de intensidad: la tinta manuscrita real es
    marcadamente oscura (perfil medido: ~0-100), mientras que el marco
    impreso de cada celda en CLAVEROS (fuente a color/JPEG, no bitonal como
    DELEGADOS/TRANSMISION) es gris claro (~180-220, casi el mismo tono que el
    fondo ~230-250) — un umbral entre esos dos rangos separa uno de otro.
    Esto es lo que TrOCR confunde con un dígito de más (típicamente un '1'
    fantasma antes del número real). No sirve para las barras de borde
    SÓLIDAS de DELEGADOS/TRANSMISION (son tan oscuras como la tinta real,
    ver quitar_barras_borde) — usar ambas en cadena: primero esta, después
    quitar_barras_borde.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    _, binaria = cv2.threshold(gray, umbral, 255, cv2.THRESH_BINARY)
    return binaria


def quitar_barras_borde(crop: np.ndarray, banda_borde: float = 0.15,
                        umbral: float = 0.85, halo: int = 2) -> np.ndarray:
    """
    Borra del recorte las líneas rectas de borde (de la celda o de una vecina)
    que TrOCR confunde con un '1' — SIN recortar ni redimensionar la imagen,
    a diferencia de limpiar_para_ocr, que además descarta manchas sólidas
    (relleno>0.62) para aislar dígitos y en 2da vuelta eso borraba ceros
    manuscritos legítimos de BLANCO/NULO/NO_MARCADO (óvalos sólidos pequeños).

    No usa componentes conectados: cuando la barra TOCA al dígito (caso común,
    p.ej. un '0' pegado al borde derecho) ambos se funden en un solo blob y un
    filtro por forma de componente ya no los distingue. En cambio, borra
    directamente filas/columnas dentro de la banda_borde (15% más cercano a
    cada lado) cuya densidad de tinta supera el umbral — una línea recta de
    borde es ~100% densa en TODA su fila/columna; un trazo de dígito, aunque
    pase cerca del borde, no lo es. `halo` expande cada columna/fila detectada
    ese nº de píxeles a cada lado: el núcleo de la línea es ~100% denso pero
    el antialiasing dejaba un borde gris parcial (<umbral) a los lados que
    sin esto sobrevivía como una línea fina visible. Todo lo demás queda
    intacto en su posición y tamaño original.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop.copy()
    h, w = gray.shape
    if h < 6 or w < 6:
        return gray
    out = gray.copy()
    _, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)

    col_frac = binary.sum(axis=0) / 255 / h
    row_frac = binary.sum(axis=1) / 255 / w
    banda_w = max(1, int(w * banda_borde))
    banda_h = max(1, int(h * banda_borde))

    col_mask = np.zeros(w, dtype=bool)
    cols = np.concatenate([np.arange(0, banda_w), np.arange(w - banda_w, w)])
    col_mask[cols] = col_frac[cols] > umbral
    if col_mask.any() and halo:
        col_mask = np.convolve(col_mask, np.ones(2 * halo + 1, dtype=bool), mode="same") > 0
    out[:, col_mask] = 255

    row_mask = np.zeros(h, dtype=bool)
    filas = np.concatenate([np.arange(0, banda_h), np.arange(h - banda_h, h)])
    row_mask[filas] = row_frac[filas] > umbral
    if row_mask.any() and halo:
        row_mask = np.convolve(row_mask, np.ones(2 * halo + 1, dtype=bool), mode="same") > 0
    out[row_mask, :] = 255

    return out


def segmentar_digitos(crop: np.ndarray, max_digitos: int = 3) -> list[np.ndarray]:
    """
    Aísla los dígitos manuscritos de una casilla por componentes conectados.

    Ignora los puntos pre-impresos (componentes pequeños) y los bordes. Devuelve
    una lista de recortes (uno por dígito), ordenados de izquierda a derecha.
    Si dos dígitos se tocan, pueden salir unidos (caso a vigilar en la comparación).
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    h, w = gray.shape
    binary = _binarizar_sin_bordes(gray)

    # Unir trazos rotos de un mismo dígito (dilatación leve vertical)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (3, 9)))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

    # Altura del componente más alto (excluyendo bordes ya quitados): referencia
    # del tamaño de un dígito real. Los puntos pre-impresos son mucho menores.
    alturas = [stats[i][3] for i in range(1, n)]
    h_max = max(alturas) if alturas else 0

    cajas = []
    for i in range(1, n):
        x, y, cw, ch, area = stats[i]
        # Un dígito real tiene altura comparable al mayor componente; un punto
        # pre-impreso es bastante más bajo (< 55% de la altura del dígito).
        es_digito = ch >= h_max * 0.55
        area_ok = area > (h * w) * 0.002
        no_borde = ch < h * 0.95
        if es_digito and area_ok and no_borde:
            cajas.append((x, y, cw, ch))

    cajas.sort(key=lambda b: b[0])
    # Quedarnos con los de la derecha si hay más de max_digitos (los números se
    # escriben alineados a la derecha; un blob espurio a la izquierda se descarta)
    if len(cajas) > max_digitos:
        cajas = cajas[-max_digitos:]

    recortes = []
    for (x, y, cw, ch) in cajas:
        # margen pequeño alrededor
        m = 6
        x0, y0 = max(0, x - m), max(0, y - m)
        x1, y1 = min(w, x + cw + m), min(h, y + ch + m)
        recortes.append(crop[y0:y1, x0:x1])
    return recortes


def preparar_numero(crop: np.ndarray) -> np.ndarray:
    """
    Prepara el recorte completo de la casilla para leer el número entero con OCR.

    Delega en `limpiar_para_ocr`, que se queda solo con los dígitos (descartando
    barras de borde y residuos) y recorta a su bounding box. Devuelve la imagen
    en escala de grises lista para el OCR.
    """
    return limpiar_para_ocr(crop)


def tiene_contenido(crop: np.ndarray, umbral_pct: float = 0.5) -> bool:
    """¿La casilla tiene algún dígito escrito? (reutiliza la lógica de tinta)."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    h, w = gray.shape
    if h < 6 or w < 6:
        return False
    binary = _binarizar_sin_bordes(gray)
    return (100.0 * binary.sum() / 255 / binary.size) > umbral_pct
