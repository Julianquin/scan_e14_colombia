#!/usr/bin/env python3
"""
Fase 0 — Extractor robusto de casillas de votación de actas E-14.

Toma un PDF E-14 (presidencial 2026, formato Delegados/Transmisión) y recorta
de forma fiable la casilla de VOTACIÓN de cada candidato y de los agregados
(blanco/nulo/no marcado), detectando la estructura en cada acta en lugar de
asumir coordenadas fijas. Deja los recortes listos para el OCR posterior.

No emite ningún juicio: solo localiza y recorta. La lectura de dígitos y la
detección de anomalías son fases posteriores.
"""

from __future__ import annotations
import io
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import cv2
import fitz  # PyMuPDF


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DEL FORMATO E-14 PRESIDENCIAL 2026
# ─────────────────────────────────────────────────────────────────────────────

DPI = 200                      # resolución de render
ZOOM = DPI / 72.0

# Geometría esperada de una caja de candidato (en px @200 DPI), como rangos
# tolerantes; se usan para clasificar contornos, no para posicionar.
CAJA_ALTO_MIN = 480
CAJA_ALTO_MAX = 700
CAJA_ANCHO_MIN_FRAC = 0.85     # respecto al ancho de página

# La columna VOTACIÓN ocupa el tramo derecho de cada caja de candidato.
VOTO_X_INI_FRAC = 0.66
VOTO_X_FIN_FRAC = 0.985

# Candidatos por página del acta presidencial 2026:
#   pág 1: candidatos 1..7
#   pág 2: candidatos 8..13  + (votos en blanco / nulos / no marcados / suma)
CANDIDATOS_PAG1 = list(range(1, 8))     # 1..7
CANDIDATOS_PAG2 = list(range(8, 14))    # 8..13
AGREGADOS = ["BLANCO", "NULO", "NO_MARCADO", "SUMA_TOTAL"]

# ─────────────────────────────────────────────────────────────────────────────
# PLANTILLA RELATIVA DEL FORMATO E-14 (fracciones de la página)
# El formato es pre-impreso e idéntico en todo el país, así que las casillas
# caen siempre en las mismas posiciones RELATIVAS. Se usan como respaldo cuando
# la detección por contornos falla (escaneo con manchas, líneas borrosas).
# ─────────────────────────────────────────────────────────────────────────────
PLANTILLA_CAND_PAG1 = [
    (0.364, 0.445), (0.450, 0.529), (0.535, 0.614), (0.620, 0.700),
    (0.705, 0.785), (0.790, 0.870), (0.875, 0.955),
]
PLANTILLA_CAND_PAG2 = [
    (0.251, 0.330), (0.335, 0.415), (0.421, 0.500),
    (0.506, 0.586), (0.592, 0.672), (0.677, 0.757),
]
PLANTILLA_AGREGADOS = [
    ("BLANCO", 0.768, 0.798), ("NULO", 0.798, 0.823),
    ("NO_MARCADO", 0.823, 0.847), ("SUMA_TOTAL", 0.847, 0.877),
]

# Bloque NIVELACIÓN DE LA MESA (página 1, encima de los candidatos): 3 filas.
# El TOTAL_E11 es el número contra el que se valida la SUMA_TOTAL en Fase 1.
NIVELACION = ["TOTAL_E11", "TOTAL_URNA", "TOTAL_INCINERADOS"]
PLANTILLA_NIVELACION = [
    ("TOTAL_E11",         0.243, 0.275),
    ("TOTAL_URNA",        0.275, 0.299),
    ("TOTAL_INCINERADOS", 0.299, 0.329),
]


@dataclass
class Casilla:
    """Una casilla de votación recortada y su metadato."""
    etiqueta: str            # "cand_01", "BLANCO", ...
    pagina: int
    bbox: tuple              # (x, y, w, h) en la imagen de la página
    tinta_pct: float         # % de píxeles oscuros (heurística de "tiene algo escrito")
    archivo_crop: str = ""   # ruta del PNG recortado (si se guarda)


@dataclass
class ResultadoExtraccion:
    pdf: str
    ok: bool
    paginas: int = 0
    casillas: list = field(default_factory=list)
    aviso: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# RENDER Y ALINEACIÓN
# ─────────────────────────────────────────────────────────────────────────────

def render_pagina(page: "fitz.Page") -> np.ndarray:
    """Renderiza una página de PDF a imagen BGR de OpenCV."""
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM))
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        return cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    if pix.n == 1:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def corregir_inclinacion(img: np.ndarray) -> np.ndarray:
    """
    Corrige pequeñas rotaciones del escaneo (deskew) usando la orientación
    dominante de las líneas largas del formato.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)
    # Detectar líneas con Hough; estimar ángulo mediano
    lines = cv2.HoughLinesP(binary, 1, np.pi/180, threshold=200,
                            minLineLength=img.shape[1]//3, maxLineGap=20)
    if lines is None:
        return img
    angulos = []
    for l in lines[:200]:
        x1, y1, x2, y2 = l[0]
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(ang) < 20:        # solo líneas casi horizontales
            angulos.append(ang)
    if not angulos:
        return img
    ang = float(np.median(angulos))
    if abs(ang) < 0.2:           # ya está derecho
        return img
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w/2, h/2), ang, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


# ─────────────────────────────────────────────────────────────────────────────
# DETECCIÓN DE CAJAS DE CANDIDATO
# ─────────────────────────────────────────────────────────────────────────────

def detectar_cajas_candidato(img: np.ndarray) -> list[tuple]:
    """
    Detecta las cajas redondeadas de candidato por contornos y las deduplica
    (cada caja tiene borde externo+interno). Devuelve lista de (x,y,w,h)
    ordenada de arriba a abajo.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cand = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw > w * CAJA_ANCHO_MIN_FRAC and CAJA_ALTO_MIN < ch < CAJA_ALTO_MAX:
            cand.append((x, y, cw, ch))

    # Deduplicar por proximidad vertical (mismo centro Y ⇒ misma caja)
    cand.sort(key=lambda b: b[1])
    dedup = []
    for box in cand:
        cy = box[1] + box[3] / 2
        if dedup:
            pcy = dedup[-1][1] + dedup[-1][3] / 2
            if abs(cy - pcy) < 120:        # misma caja física
                # quedarnos con la más grande (borde externo)
                if box[2] * box[3] > dedup[-1][2] * dedup[-1][3]:
                    dedup[-1] = box
                continue
        dedup.append(box)
    return dedup


# Márgenes internos para excluir los bordes de la caja al recortar (fracción)
MARGEN_V = 0.10    # recorta 10% arriba y abajo (línea separadora, borde)
MARGEN_DER = 0.04  # recorta 4% del borde derecho (línea vertical de la caja)


def recortar_voto(img: np.ndarray, caja: tuple) -> tuple[np.ndarray, tuple]:
    """
    Recorta la subregión de la columna VOTACIÓN dentro de una caja,
    excluyendo los bordes para quedarnos solo con la zona del número.
    """
    x, y, cw, ch = caja
    w = img.shape[1]
    x0 = int(w * VOTO_X_INI_FRAC)
    x1 = int(w * VOTO_X_FIN_FRAC) - int(w * MARGEN_DER)
    dv = int(ch * MARGEN_V)
    y0, y1 = y + dv, y + ch - dv
    crop = img[y0:y1, x0:x1]
    return crop, (x0, y0, x1 - x0, y1 - y0)


def tinta_pct(crop: np.ndarray) -> float:
    """
    Porcentaje de píxeles de escritura en una casilla.

    Antes de medir, elimina las líneas largas (bordes de la celda): una columna
    o fila que está oscura casi de extremo a extremo es un borde, no un número.
    Así el valor refleja solo el trazo manuscrito, sin importar si el recorte
    incluyó parte del marco de la casilla.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    h, w = gray.shape
    if h < 6 or w < 6:
        return 0.0
    oscuro = (gray < 100).astype(np.uint8)

    # Quitar columnas que son línea vertical (oscuras en >70% de su altura)
    col_frac = oscuro.sum(axis=0) / h
    oscuro[:, col_frac > 0.7] = 0
    # Quitar filas que son línea horizontal (oscuras en >70% de su ancho)
    row_frac = oscuro.sum(axis=1) / w
    oscuro[row_frac > 0.7, :] = 0

    # Medir sobre la zona central (margen 6%) para descartar restos de borde
    m = int(min(h, w) * 0.06)
    centro = oscuro[m:h-m, m:w-m] if h > 2*m and w > 2*m else oscuro
    return float(100.0 * centro.sum() / max(centro.size, 1))


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def cajas_desde_plantilla(img: np.ndarray, plantilla: list) -> list[tuple]:
    """
    Genera cajas de candidato a partir de la plantilla relativa (fracciones).
    Respaldo cuando la detección por contornos no da el número esperado.
    """
    h, w = img.shape[:2]
    cajas = []
    for (y_top, y_bot) in plantilla:
        y = int(y_top * h)
        ch = int((y_bot - y_top) * h)
        cajas.append((0, y, w, ch))
    return cajas


def fusionar_cajas(detectadas: list[tuple], plantilla_boxes: list[tuple],
                   img_h: int) -> list[tuple]:
    """
    Combina cajas detectadas por contorno con la plantilla. Para cada posición
    de la plantilla, busca una caja detectada cuyo centro esté cerca; si la
    encuentra, usa la detectada (más precisa); si no, usa la de plantilla.
    Garantiza que siempre haya una caja por candidato esperado.
    """
    resultado = []
    usados = [False] * len(detectadas)
    for pb in plantilla_boxes:
        pcy = pb[1] + pb[3] / 2
        mejor, mejor_d = None, img_h * 0.04   # tolerancia: 4% de la altura
        for i, db in enumerate(detectadas):
            if usados[i]:
                continue
            dcy = db[1] + db[3] / 2
            d = abs(dcy - pcy)
            if d < mejor_d:
                mejor, mejor_d, mejor_i = db, d, i
        if mejor is not None:
            resultado.append(mejor)
            usados[mejor_i] = True
        else:
            resultado.append(pb)       # respaldo por plantilla
    return resultado


def _detectar_lineas_h(binary: np.ndarray, w: int, y_ini: int, y_fin: int,
                       min_frac: float = 0.4) -> list[int]:
    """Detecta posiciones Y de líneas horizontales largas en una franja."""
    horiz = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (int(w * 0.3), 1)))
    proj = horiz.sum(axis=1)
    filas = [y for y in range(max(0, y_ini), min(len(proj), y_fin))
             if proj[y] > w * min_frac * 255]
    lineas = []
    if filas:
        ini = prev = filas[0]
        for y in filas[1:]:
            if y - prev > 25:
                lineas.append((ini + prev) // 2)
                ini = y
            prev = y
        lineas.append((ini + prev) // 2)
    return lineas


def _detectar_separador_vertical(binary: np.ndarray, w: int, h: int,
                                 y_ini: int, y_fin: int) -> Optional[int]:
    """
    Detecta la línea vertical que separa la columna de etiquetas de la de votos
    en el bloque de agregados. Es una vertical larga situada en la zona central-
    derecha (~0.55-0.72 del ancho).
    """
    franja = binary[y_ini:y_fin, :]
    fh = franja.shape[0]
    vert = cv2.morphologyEx(
        franja, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(fh * 0.5))))
    proj = vert.sum(axis=0)
    # Buscar columnas con vertical larga en la zona donde está el separador
    candidatos = [(x, proj[x]) for x in range(int(w * 0.55), int(w * 0.75))
                  if proj[x] > fh * 0.5 * 255]
    if not candidatos:
        return None
    # El separador suele ser la vertical más a la izquierda de esa zona
    return min(candidatos, key=lambda c: c[0])[0]


def detectar_celdas_agregados(img: np.ndarray) -> list[tuple]:
    """
    Detecta las 4 celdas de ETIQUETA del bloque de agregados.
    Mantiene compatibilidad: devuelve lista de (x, y, w, h).
    Implementado sobre la detección robusta por líneas.
    """
    info = localizar_bloque_agregados(img)
    if not info:
        return []
    lineas, x_sep = info["lineas"], info["x_separador"]
    celdas = []
    for i in range(4):
        y0, y1 = lineas[i], lineas[i + 1]
        celdas.append((0, y0, x_sep, y1 - y0))
    return celdas


def localizar_bloque_agregados(img: np.ndarray) -> Optional[dict]:
    """
    Localiza el bloque de agregados de forma robusta:
      - Encuentra las 5 líneas horizontales que delimitan sus 4 filas.
      - Encuentra la línea vertical que separa etiquetas de votos.

    Es tolerante a rejillas imperfectas porque trabaja con líneas (no exige
    contornos cerrados) y usa rangos relativos a la altura de la página.

    Devuelve {"lineas": [y0..y4], "x_separador": x} o None si no lo localiza.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)

    # El bloque está en la parte baja. Buscamos en una franja amplia para
    # tolerar que esté algo desplazado.
    y_ini, y_fin = int(h * 0.68), int(h * 0.95)
    lineas = _detectar_lineas_h(binary, w, y_ini, y_fin)

    # Necesitamos 4 filas de altura similar y consecutivas. Buscamos 5 líneas
    # con separaciones parecidas (las filas de agregados son regulares).
    grupo = _buscar_5_lineas_regulares(lineas, h)
    if grupo is None:
        # Reintento con umbral de línea más laxo (rejilla tenue)
        lineas = _detectar_lineas_h(binary, w, y_ini, y_fin, min_frac=0.25)
        grupo = _buscar_5_lineas_regulares(lineas, h)
    if grupo is None:
        return None

    x_sep = _detectar_separador_vertical(binary, w, h, grupo[0], grupo[-1])
    if x_sep is None:
        # Respaldo: usar la fracción típica de inicio de la columna de votos
        x_sep = int(w * VOTO_X_INI_FRAC)

    return {"lineas": grupo, "x_separador": x_sep}


def buscar_n_lineas_regulares(lineas: list[int], h: int, n_filas: int,
                              lo_f: float = 0.018, hi_f: float = 0.040) -> Optional[list[int]]:
    """
    De una lista de líneas horizontales, encuentra (n_filas + 1) líneas
    consecutivas con separaciones similares (las filas de un bloque-tabla del
    E-14 tienen altura parecida).

    lo_f / hi_f acotan la altura de fila esperada como fracción de la página.
    """
    n = n_filas + 1
    if len(lineas) < n:
        return None
    lineas = sorted(lineas)
    lo, hi = h * lo_f, h * hi_f
    mejor = None
    for i in range(len(lineas) - n_filas):
        ventana = lineas[i:i + n]
        gaps = [ventana[j + 1] - ventana[j] for j in range(n_filas)]
        if all(lo < g < hi for g in gaps):
            var = max(gaps) - min(gaps)
            if mejor is None or var < mejor[0]:
                mejor = (var, ventana)
    return mejor[1] if mejor else None


def _buscar_5_lineas_regulares(lineas: list[int], h: int) -> Optional[list[int]]:
    """Compatibilidad: busca 5 líneas (4 filas) para el bloque de agregados."""
    return buscar_n_lineas_regulares(lineas, h, 4)


def agregados_por_celdas(img: np.ndarray, cajas_detectadas: list[tuple]) -> tuple:
    """
    Localiza la columna de votos de los 4 agregados combinando dos referencias
    estables leídas de la propia acta:
      • X: la línea vertical que separa etiquetas de votos.
      • Y: las 5 líneas horizontales reales de la tabla (cada fila de línea a línea).

    Robusto al desfase: cada fila se ancla a sus propias líneas.
    Devuelve (lista de (etiqueta, bbox), origen).
    """
    h, w = img.shape[:2]
    info = localizar_bloque_agregados(img)
    if not info:
        return agregados_desde_plantilla(img, cajas_detectadas), "plantilla"

    lineas = info["lineas"]
    x_ini = info["x_separador"] + int(w * 0.006)   # tras el separador vertical
    # Límite derecho REAL: la línea vertical derecha de la tabla (ver nivelación)
    xb = _borde_derecho_bloque(img, lineas[0], lineas[-1],
                               info["x_separador"] + int(w * 0.02))
    if xb is not None and xb > x_ini + int(w * 0.10):
        x_fin = xb - int(w * 0.004)
    else:
        x_fin = int(w * VOTO_X_FIN_FRAC)

    res = []
    for i, (etiqueta, _, _) in enumerate(PLANTILLA_AGREGADOS):
        y0, y1 = lineas[i], lineas[i + 1]
        dv = int((y1 - y0) * 0.06)
        # x_fin afinado por fila (absorbe inclinación de la línea derecha)
        if xb is not None and xb > x_ini + int(w * 0.10):
            x_fin_fila = _afinar_borde_fila(img, y0, y1, xb) - int(w * 0.004)
        else:
            x_fin_fila = x_fin
        res.append((etiqueta, (x_ini, y0 + dv, x_fin_fila - x_ini, (y1 - y0) - 2 * dv)))
    return res, "celdas+lineas"


def localizar_bloque_nivelacion(img: np.ndarray) -> Optional[dict]:
    """
    Localiza el bloque NIVELACIÓN DE LA MESA (página 1), análogo a los agregados
    pero con 3 filas. Usa las líneas horizontales reales y el separador vertical.

    Devuelve {"lineas": [y0..y3], "x_separador": x} o None.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)

    # El bloque está en el tercio superior (bajo el encabezado, antes de candidatos)
    y_ini, y_fin = int(h * 0.20), int(h * 0.36)
    lineas = _detectar_lineas_h(binary, w, y_ini, y_fin)

    # 3 filas → 4 líneas. Las filas de nivelación son algo más variables en alto.
    grupo = buscar_n_lineas_regulares(lineas, h, 3, lo_f=0.020, hi_f=0.045)
    if grupo is None:
        lineas = _detectar_lineas_h(binary, w, y_ini, y_fin, min_frac=0.25)
        grupo = buscar_n_lineas_regulares(lineas, h, 3, lo_f=0.020, hi_f=0.045)
    if grupo is None:
        return None

    x_sep = _detectar_separador_vertical(binary, w, h, grupo[0], grupo[-1])
    if x_sep is None:
        x_sep = int(w * VOTO_X_INI_FRAC)
    return {"lineas": grupo, "x_separador": x_sep}


def _borde_derecho_bloque(img: np.ndarray, y_top: int, y_bot: int,
                          x_desde: int) -> Optional[int]:
    """
    Detecta la X donde empieza la línea vertical DERECHA de la tabla (el borde
    derecho del bloque de nivelación/agregados), buscando en la franja vertical
    completa del bloque [y_top, y_bot].

    Es inconfundible con un dígito: la línea impresa cruza TODAS las filas del
    bloque (col_frac ≈ 1.0 sobre 3-4 filas), mientras un dígito vive en una
    sola fila (col_frac ≤ ~0.33 sobre el bloque). Devuelve el inicio del grupo
    más a la derecha, o None si no hay línea clara.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    franja = (gray[y_top:y_bot, :] < 100).astype(np.uint8)
    if franja.size == 0:
        return None
    fh = franja.shape[0]
    franja = cv2.morphologyEx(franja, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5)))
    col_frac = franja.sum(axis=0) / fh
    w = gray.shape[1]
    candidatas = [x for x in range(max(0, x_desde), w) if col_frac[x] > 0.7]
    if not candidatas:
        return None
    # Tomar el PRIMER grupo (la línea más a la izquierda de la zona derecha):
    # es el borde de la celda de valores. Algunas actas tienen una segunda
    # línea exterior más a la derecha; quedarse con la última dejaría la
    # interior dentro del recorte.
    ini = candidatas[0]
    return ini


def _afinar_borde_fila(img: np.ndarray, y0: int, y1: int, xg: int,
                       ventana: int = 22) -> int:
    """
    Afinado POR FILA del borde derecho: busca la línea vertical en la ventana
    [xg−ventana, xg+ventana] dentro de la franja de la fila [y0,y1]. Absorbe la
    inclinación residual de la página (la línea global puede caer unos píxeles
    antes/después a la altura de cada fila). La línea impresa cruza ~100% de su
    fila; se exige >0.8. Devuelve el inicio local de la línea, o xg si no hay.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    fh = y1 - y0
    if fh < 6:
        return xg
    franja = (gray[y0:y1, max(0, xg - ventana):xg + ventana] < 100).astype(np.uint8)
    franja = cv2.morphologyEx(franja, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5)))
    col_frac = franja.sum(axis=0) / fh
    idx = [i for i in range(franja.shape[1]) if col_frac[i] > 0.8]
    if not idx:
        return xg
    ini = idx[0]
    return max(0, xg - ventana) + ini


def nivelacion_por_celdas(img: np.ndarray) -> tuple:
    """
    Localiza la columna de valores de las 3 filas de NIVELACIÓN, anclando cada
    fila a las líneas reales de la tabla y la X al separador vertical.
    Devuelve (lista de (etiqueta, bbox), origen).
    """
    h, w = img.shape[:2]
    info = localizar_bloque_nivelacion(img)
    if not info:
        return nivelacion_desde_plantilla(img), "plantilla"

    lineas = info["lineas"]
    x_ini = info["x_separador"] + int(w * 0.006)
    # Límite derecho REAL: la línea vertical derecha de la tabla. Así la barra
    # del borde queda FUERA del recorte desde el origen. Fallback: fracción fija.
    xb = _borde_derecho_bloque(img, lineas[0], lineas[-1],
                               info["x_separador"] + int(w * 0.02))
    if xb is not None and xb > x_ini + int(w * 0.10):
        x_fin = xb - int(w * 0.004)
    else:
        x_fin = int(w * VOTO_X_FIN_FRAC)
    res = []
    for i, (etiqueta, _, _) in enumerate(PLANTILLA_NIVELACION):
        y0, y1 = lineas[i], lineas[i + 1]
        dv = int((y1 - y0) * 0.06)
        # x_fin afinado por fila (absorbe inclinación de la línea derecha)
        if xb is not None and xb > x_ini + int(w * 0.10):
            x_fin_fila = _afinar_borde_fila(img, y0, y1, xb) - int(w * 0.004)
        else:
            x_fin_fila = x_fin
        res.append((etiqueta, (x_ini, y0 + dv, x_fin_fila - x_ini, (y1 - y0) - 2 * dv)))
    return res, "celdas+lineas"


def nivelacion_desde_plantilla(img: np.ndarray) -> list[tuple]:
    """Respaldo: bbox de las 3 casillas de nivelación por fracciones fijas."""
    h, w = img.shape[:2]
    x0 = int(w * VOTO_X_INI_FRAC) + int(w * 0.015)
    x1 = int(w * VOTO_X_FIN_FRAC) - int(w * MARGEN_DER)
    res = []
    for (etiqueta, y_top, y_bot) in PLANTILLA_NIVELACION:
        y = int(y_top * h)
        bh = int((y_bot - y_top) * h)
        dv = int(bh * 0.08)
        res.append((etiqueta, (x0, y + dv, x1 - x0, bh - 2 * dv)))
    return res


def agregados_desde_plantilla(img: np.ndarray,
                              cajas_candidato: list[tuple] = None) -> list[tuple]:
    """
    Respaldo de último recurso: genera los bbox de los 4 agregados usando las
    fracciones fijas de la plantilla (PLANTILLA_AGREGADOS).

    Solo se usa cuando `localizar_bloque_agregados` no logra encontrar las 5
    líneas reales del bloque (caso muy raro). Aproxima la posición sin el
    desfase de media fila que producía el viejo anclaje al candidato 13.
    """
    h, w = img.shape[:2]
    x0 = int(w * VOTO_X_INI_FRAC) + int(w * 0.015)
    x1 = int(w * VOTO_X_FIN_FRAC) - int(w * MARGEN_DER)
    res = []
    for (etiqueta, y_top, y_bot) in PLANTILLA_AGREGADOS:
        y = int(y_top * h)
        bh = int((y_bot - y_top) * h)
        dv = int(bh * 0.08)
        res.append((etiqueta, (x0, y + dv, x1 - x0, bh - 2 * dv)))
    return res


def ajustar_recorte_interior(img: np.ndarray, bbox: tuple,
                             banda_frac: float = 0.10,
                             altura_min: float = 0.88,
                             margen: int = 4) -> tuple:
    """
    Ajusta un bbox para que caiga DENTRO de la celda, excluyendo las líneas de
    borde del formulario. Corrección DE RAÍZ al problema de las barras en los
    recortes: se recorta el interior desde el principio.

    Criterios calibrados con casos reales (acta Medellín 003, donde un '1'
    manuscrito grande casi se confunde con línea):
      • SIN dilatación vertical: una línea de borde residual es CONTINUA
        (col_frac ≈ 0.95-1.0); un dígito grande llega a ~0.7-0.8. La dilatación
        inflaba los dígitos y causaba falsos positivos.
      • Banda estrecha (10%): las líneas residuales del bbox base están pegadas
        a los extremos; los dígitos empiezan más adentro (~15-20%).
      • Contacto con el extremo: el grupo-línea debe empezar a <4% del borde
        del recorte. Un dígito, aunque sea vertical, no toca el extremo.
    """
    x, y, w, h = bbox
    crop = img[y:y+h, x:x+w]
    if crop.size == 0 or w < 12 or h < 12:
        return bbox
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    osc = (gray < 100).astype(np.uint8)

    # Proyección SIN dilatación (línea de borde = columna continua casi total).
    # Cierre vertical mínimo (3px) solo para microcortes del propio escaneo.
    osc_c = cv2.morphologyEx(osc, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (1, 3)))
    col_frac = osc_c.sum(axis=0) / h

    banda = max(3, int(w * banda_frac))
    tope_contacto = max(2, int(w * 0.04))
    x0_new, x1_new = 0, w
    # banda izquierda: grupo-línea que empiece pegado al extremo izquierdo
    cx = 0
    while cx < banda:
        if col_frac[cx] > altura_min and cx <= tope_contacto:
            fin = cx
            while fin + 1 < banda and col_frac[fin + 1] > altura_min:
                fin += 1
            x0_new = fin + 1
            cx = fin + 1
        cx += 1
    # banda derecha: grupo-línea que termine pegado al extremo derecho
    cx = w - 1
    while cx >= w - banda:
        if col_frac[cx] > altura_min and cx >= w - 1 - tope_contacto:
            ini = cx
            while ini - 1 >= w - banda and col_frac[ini - 1] > altura_min:
                ini -= 1
            x1_new = ini
            cx = ini
        cx -= 1
    x0_new = min(x0_new + margen, w // 3)
    x1_new = max(x1_new - margen, 2 * w // 3)

    # Bordes horizontales (sup/inf): mismo criterio en vertical
    row_frac = osc_c.sum(axis=1) / w
    banda_v = max(3, int(h * banda_frac))
    tope_v = max(2, int(h * 0.04))
    y0_new, y1_new = 0, h
    cy = 0
    while cy < banda_v:
        if row_frac[cy] > altura_min and cy <= tope_v:
            fin = cy
            while fin + 1 < banda_v and row_frac[fin + 1] > altura_min:
                fin += 1
            y0_new = fin + 1
            cy = fin + 1
        cy += 1
    cy = h - 1
    while cy >= h - banda_v:
        if row_frac[cy] > altura_min and cy >= h - 1 - tope_v:
            ini = cy
            while ini - 1 >= h - banda_v and row_frac[ini - 1] > altura_min:
                ini -= 1
            y1_new = ini
            cy = ini
        cy -= 1
    y0_new = min(y0_new + margen, h // 3)
    y1_new = max(y1_new - margen, 2 * h // 3)

    return (x + x0_new, y + y0_new, x1_new - x0_new, y1_new - y0_new)


def borde_residual(img: np.ndarray, bbox: tuple) -> int:
    """
    Métrica de calidad del recorte: cuenta columnas-línea (>80% de la altura,
    tras reconectar) que quedan en el recorte. 0 = recorte limpio sin bordes.
    Sirve para marcar recortes que necesiten revisión, con trazabilidad.
    """
    x, y, w, h = bbox
    crop = img[y:y+h, x:x+w]
    if crop.size == 0 or w < 8 or h < 8:
        return 0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    osc = (gray < 100).astype(np.uint8)
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(8, h // 6)))
    col_frac = cv2.dilate(osc, vk).sum(axis=0) / h
    return int((col_frac > 0.8).sum())


def procesar_acta(pdf_path: str, salida_crops: Optional[str] = None,
                  guardar: bool = True) -> ResultadoExtraccion:
    """
    Procesa un acta E-14 completa y extrae las casillas de votación.
    Devuelve ResultadoExtraccion con la lista de casillas y sus recortes.
    """
    res = ResultadoExtraccion(pdf=str(pdf_path), ok=False)
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        res.aviso = f"No se pudo abrir el PDF: {e}"
        return res

    res.paginas = len(doc)
    out_dir = Path(salida_crops) if salida_crops else None
    if out_dir and guardar:
        out_dir.mkdir(parents=True, exist_ok=True)

    # Mapa de qué candidatos y plantilla usar por página
    mapa_pag = {0: CANDIDATOS_PAG1, 1: CANDIDATOS_PAG2}
    mapa_plantilla = {0: PLANTILLA_CAND_PAG1, 1: PLANTILLA_CAND_PAG2}

    for pidx in range(min(2, len(doc))):     # solo páginas 1 y 2 traen votos
        img = render_pagina(doc[pidx])
        img = corregir_inclinacion(img)
        h_img = img.shape[0]

        cajas = detectar_cajas_candidato(img)
        if pidx == 0:
            cajas = [c for c in cajas if c[1] > h_img * 0.30]
        cajas.sort(key=lambda b: b[1])

        etiquetas = mapa_pag.get(pidx, [])
        plantilla = mapa_plantilla.get(pidx, [])

        # HÍBRIDO: fusionar lo detectado con la plantilla relativa, de modo que
        # siempre haya una caja por candidato esperado (precisa si la detección
        # funcionó; de plantilla si falló).
        plantilla_boxes = cajas_desde_plantilla(img, plantilla)
        cajas_cand = fusionar_cajas(cajas, plantilla_boxes, h_img)

        usados_plantilla = 0
        for i, caja in enumerate(cajas_cand):
            etiqueta = f"cand_{etiquetas[i]:02d}"
            crop, bbox = recortar_voto(img, caja)
            # Ajustar el recorte al INTERIOR de la celda (sin líneas de borde)
            bbox = ajustar_recorte_interior(img, bbox)
            x_a, y_a, w_a, h_a = bbox
            crop = img[y_a:y_a+h_a, x_a:x_a+w_a]
            t = tinta_pct(crop)
            casilla = Casilla(etiqueta=etiqueta, pagina=pidx + 1,
                              bbox=tuple(int(v) for v in bbox), tinta_pct=round(t, 2))
            if out_dir and guardar:
                fname = out_dir / f"p{pidx+1}_{etiqueta}.png"
                cv2.imwrite(str(fname), crop)
                casilla.archivo_crop = str(fname)
            res.casillas.append(casilla)

        # ── Pág. 1: bloque NIVELACIÓN DE LA MESA (3 filas) ──────────────────
        if pidx == 0:
            niveles, origen_niv = nivelacion_por_celdas(img)
            for etiqueta, bbox in niveles:
                bbox = ajustar_recorte_interior(img, bbox)
                x, y, bw, bh = bbox
                crop = img[y:y+bh, x:x+bw]
                t = tinta_pct(crop)
                casilla = Casilla(etiqueta=etiqueta, pagina=1,
                                  bbox=tuple(int(v) for v in bbox),
                                  tinta_pct=round(t, 2))
                if out_dir and guardar:
                    fname = out_dir / f"p1_{etiqueta}.png"
                    cv2.imwrite(str(fname), crop)
                    casilla.archivo_crop = str(fname)
                res.casillas.append(casilla)
            if origen_niv != "celdas+lineas":
                res.aviso = (res.aviso + " | " if res.aviso else "") + \
                            f"nivelacion por respaldo ({origen_niv})"

        # ── Pág. 2: agregados — anclados a las líneas reales de la tabla ────
        if pidx == 1:
            # Estrategia única: localizar el bloque por sus líneas horizontales
            # reales y el separador vertical. Cada fila se ancla de línea a línea
            # → inmune al desfase. Si no se localiza el bloque, cae a la plantilla
            # relativa (que aproxima sin el desfase de media fila del viejo
            # anclaje, ya eliminado).
            aggs, origen_agg = agregados_por_celdas(img, cajas)
            for etiqueta, bbox in aggs:
                bbox = ajustar_recorte_interior(img, bbox)
                x, y, bw, bh = bbox
                crop = img[y:y+bh, x:x+bw]
                t = tinta_pct(crop)
                casilla = Casilla(etiqueta=etiqueta, pagina=2,
                                  bbox=tuple(int(v) for v in bbox),
                                  tinta_pct=round(t, 2))
                if out_dir and guardar:
                    fname = out_dir / f"p2_{etiqueta}.png"
                    cv2.imwrite(str(fname), crop)
                    casilla.archivo_crop = str(fname)
                res.casillas.append(casilla)
            if origen_agg != "celdas+lineas":
                res.aviso = (res.aviso + " | " if res.aviso else "") + \
                            f"agregados por respaldo ({origen_agg})"

    res.ok = len(res.casillas) > 0
    if not res.ok:
        res.aviso = "No se detectaron casillas; el formato puede diferir."

    # ── Página 3: recuadro de CONSTANCIAS DE LOS JURADOS ─────────────────────
    if len(doc) >= 3:
        img3 = render_pagina(doc[2])
        img3 = corregir_inclinacion(img3)
        h3, w3 = img3.shape[:2]
        bbox_c = detectar_constancias(img3)
        if bbox_c is None:
            # Respaldo: zona relativa típica del recuadro de constancias
            bbox_c = (0, int(h3 * 0.24), w3, int(h3 * 0.50))
        x, y, w, h = bbox_c
        crop = img3[y:y+h, x:x+w]
        t = texto_pct(crop)
        casilla = Casilla(etiqueta="CONSTANCIAS", pagina=3,
                          bbox=tuple(int(v) for v in bbox_c),
                          tinta_pct=round(t, 2))
        if out_dir and guardar:
            fname = out_dir / "p3_CONSTANCIAS.png"
            cv2.imwrite(str(fname), crop)
            casilla.archivo_crop = str(fname)
        res.casillas.append(casilla)

    return res


def detectar_agregados(img: np.ndarray, cajas_candidato: list[tuple]) -> list[tuple]:
    """
    Detecta el bloque de agregados al final de la pág. 2 (VOTOS EN BLANCO,
    NULOS, NO MARCADOS, SUMA TOTAL) y devuelve una lista de
    (etiqueta, bbox_voto) para la columna de votos de cada fila.

    Estrategia: el bloque está debajo del último candidato. Se localizan las
    líneas horizontales internas que separan las 4 filas y se recorta la
    columna de votos (tramo derecho) de cada una.
    """
    h, w = img.shape[:2]
    if not cajas_candidato:
        return []

    # Inicio del bloque: justo debajo de la última caja de candidato
    ultima = max(cajas_candidato, key=lambda b: b[1])
    y0 = ultima[1] + ultima[3] + 10
    y1 = int(h * 0.92)            # antes del pie de página
    if y1 - y0 < 200:
        return []

    bloque = img[y0:y1, :]
    gray = cv2.cvtColor(bloque, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)
    horiz = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (int(w * 0.5), 1)))
    proj = horiz.sum(axis=1)
    lineas = [y for y in range(len(proj)) if proj[y] > w * 0.4 * 255]

    # Agrupar líneas contiguas
    grupos = []
    if lineas:
        ini = prev = lineas[0]
        for y in lineas[1:]:
            if y - prev > 25:
                grupos.append((ini + prev) // 2)
                ini = y
            prev = y
        grupos.append((ini + prev) // 2)

    # Necesitamos al menos 5 líneas para delimitar 4 filas
    if len(grupos) < 5:
        return []

    x0 = int(w * VOTO_X_INI_FRAC) + int(w * 0.015)   # +margen izq: excluye borde de caja
    x1 = int(w * VOTO_X_FIN_FRAC) - int(w * MARGEN_DER)

    resultado = []
    for i in range(min(4, len(grupos) - 1)):
        fy0 = y0 + grupos[i]
        fy1 = y0 + grupos[i + 1]
        dv = int((fy1 - fy0) * 0.08)     # margen interno para excluir bordes
        bbox = (x0, fy0 + dv, x1 - x0, (fy1 - fy0) - 2 * dv)
        resultado.append((AGREGADOS[i], bbox))
    return resultado


def detectar_constancias(img: np.ndarray) -> Optional[tuple]:
    """
    Detecta el recuadro 'CONSTANCIAS DE LOS JURADOS DE VOTACIÓN' en la pág. 3.

    Lo localiza por su cabecera: una banda horizontal oscura (texto blanco
    sobre fondo negro) ancha, situada en el tercio superior de la página.
    Devuelve el bbox (x, y, w, h) del área de texto manuscrito (debajo de la
    cabecera, hasta antes del bloque de firmas), o None si no la encuentra.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Filas muy oscuras y anchas = cabeceras negras del formato
    oscuro = (gray < 80).sum(axis=1)
    bandas = []
    filas = [y for y in range(h) if oscuro[y] > w * 0.5]
    if filas:
        ini = prev = filas[0]
        for y in filas[1:]:
            if y - prev > 30:
                bandas.append((ini, prev))
                ini = y
            prev = y
        bandas.append((ini, prev))

    # La cabecera de constancias es una banda gruesa (>40px) en el tercio
    # superior de la página (la franja negra del título).
    cabecera = None
    for y0, y1 in bandas:
        alto = y1 - y0
        if alto > 40 and y0 < h * 0.35:
            cabecera = (y0, y1)
            break
    if cabecera is None:
        return None

    # El área de texto va desde el fin de la cabecera hasta el bloque de firmas.
    # Detectamos el inicio de las firmas buscando la siguiente banda oscura
    # ancha bastante más abajo; si no, usamos un límite proporcional.
    y_texto_ini = cabecera[1] + 5
    y_firmas = None
    for y0, y1 in bandas:
        if y0 > cabecera[1] + h * 0.45:   # firmas están bastante más abajo
            y_firmas = y0
            break
    y_texto_fin = y_firmas if y_firmas else int(h * 0.74)

    return (0, y_texto_ini, w, y_texto_fin - y_texto_ini)


def texto_pct(crop: np.ndarray) -> float:
    """% de píxeles oscuros (texto manuscrito) en una región, excluyendo bordes."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    h, w = gray.shape
    m = int(min(h, w) * 0.03)
    centro = gray[m:h-m, m:w-m] if h > 2*m and w > 2*m else gray
    return float(100.0 * (centro < 100).sum() / max(centro.size, 1))


def resultado_a_dict(res: ResultadoExtraccion) -> dict:
    d = asdict(res)
    return d


if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser(description="Fase 0 — Extractor de casillas E-14")
    ap.add_argument("pdf", help="Ruta al PDF del acta")
    ap.add_argument("--crops", default="crops_salida", help="Directorio de recortes")
    ap.add_argument("--json", default="", help="Guardar metadatos en JSON")
    a = ap.parse_args()

    res = procesar_acta(a.pdf, salida_crops=a.crops)
    print(f"PDF: {res.pdf}")
    print(f"Páginas: {res.paginas}  |  Casillas extraídas: {len(res.casillas)}")
    for c in res.casillas:
        marca = "●" if c.tinta_pct > 1.0 else "○"
        print(f"   {marca} {c.etiqueta:12s} pág{c.pagina} tinta={c.tinta_pct:5.2f}%  {c.archivo_crop}")
    if a.json:
        Path(a.json).write_text(json.dumps(resultado_a_dict(res), indent=2, ensure_ascii=False))
        print(f"\nMetadatos → {a.json}")
