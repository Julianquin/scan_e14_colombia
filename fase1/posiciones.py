#!/usr/bin/env python3
"""
Fase 1 — Segmentación y registro del ESTADO de cada posición de una casilla.

Filosofía (acordada con el diseño del proyecto): NO interpretar ni "limpiar" el
contenido. Registrar fielmente qué hay en cada posición de la casilla, para que
el OCR lea y el chequeo aritmético + humano interpreten.

Cada casilla de voto del E-14 tiene varias posiciones (normalmente 3:
centena/decena/unidad; a veces 4 u otras, lo cual es en sí una anomalía a
registrar). Cada posición puede contener:
    - un dígito (0-9)
    - un punto (marca de relleno / posible cero o vacío)
    - un guion (vacío marcado)
    - nada (vacío en blanco)

Este módulo:
  1. Quita SOLO las barras de borde de celdas vecinas (no toca el contenido).
  2. Detecta los bloques de contenido (posiciones con algo escrito).
  3. Clasifica cada bloque por su forma (digito/punto/guion).
  4. Devuelve un registro estructurado por posición + banderas de inconsistencia.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import cv2
import numpy as np


@dataclass
class Posicion:
    x0: int
    x1: int
    tipo: str           # 'digito' | 'punto' | 'guion' | 'marca'
    alto_frac: float    # altura del contenido / altura de la casilla
    relleno: float      # qué tan lleno está su bounding box

    @property
    def es_digito(self) -> bool:
        return self.tipo == "digito"


@dataclass
class RegistroCasilla:
    n_posiciones: int
    posiciones: list                # lista de Posicion (de izq a der)
    n_digitos: int
    n_puntos: int
    n_guiones: int
    crop_limpio: np.ndarray = None  # casilla sin barras de borde
    banderas: list = field(default_factory=list)


def quitar_barras_borde(crop: np.ndarray, umbral: float = 0.7) -> np.ndarray:
    """
    Borra las barras de borde de la celda PROTEGIENDO la tinta de los dígitos
    (máscara de barras − tinta a conservar). Enfoque morfológico:

      2. Máscara de barras: líneas verticales muy largas (apertura con kernel
         vertical de ~0.9 de la altura). Una barra de borde cruza casi todo el
         alto; un dígito no, así que el kernel exigente no captura dígitos
         completos.
      3. Tinta a conservar: todo lo que NO es barra, dilatado para crear una
         zona de protección alrededor de los trazos (rescata partes de un dígito
         vertical que hubieran caído en la máscara de barras).
      4. Máscara final = barras − tinta protegida.
      5. Blanquear la máscara final.

    Esto borra la barra sin mutilar dígitos verticales (1, 4, 7, 9), que era el
    problema de los enfoques por columnas. Si algo sale mal, en el peor caso
    deja algo de borde (ruido tolerable), no daña el número.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop.copy()
    h, w = gray.shape
    if h < 8 or w < 8:
        return gray

    _, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)

    # Paso 2a: máscara de barras verticales largas CONTINUAS (casi toda la altura)
    k_vert = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(h * 0.9)))
    barras = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k_vert)

    # Paso 2b: barras FRAGMENTADAS de recorrido completo. Una barra rota por el
    # escaneo no sobrevive a la apertura, pero conserva su firma: sus fragmentos
    # recorren el recorte de extremo a extremo (tocan la banda superior Y la
    # inferior) y cubren la mayor parte del trayecto aunque con huecos. Un
    # dígito nunca cumple eso. Se exige además que el grupo sea estrecho y esté
    # pegado a un lateral del recorte (zona de borde, no de dígitos).
    col_cov = binary.sum(axis=0) / 255 / h            # cobertura por columna
    banda_v = max(2, int(h * 0.08))
    toca_arr = binary[:banda_v, :].sum(axis=0) > 0
    toca_aba = binary[-banda_v:, :].sum(axis=0) > 0
    frag = (col_cov > 0.45) & toca_arr & toca_aba
    frag_idx = np.where(frag)[0]
    if len(frag_idx):
        grupos = []
        ini = prev = frag_idx[0]
        for x in frag_idx[1:]:
            if x - prev > 3:
                grupos.append((ini, prev)); ini = x
            prev = x
        grupos.append((ini, prev))
        max_grosor = max(4, int(w * 0.025))
        for a, b in grupos:
            lateral = (b < w * 0.12) or (a > w * 0.88)
            if (b - a + 1) <= max_grosor and lateral:
                barras[:, a:b + 1] = np.maximum(barras[:, a:b + 1],
                                                binary[:, a:b + 1])

    if barras.sum() == 0:
        return gray  # no hay barras: recorte fiel

    # Paso 3: tinta a conservar (lo que no es barra) + zona de protección
    tinta_conservar = cv2.subtract(binary, barras)
    k_prot = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    tinta_protegida = cv2.dilate(tinta_conservar, k_prot)

    # Paso 4: máscara final = barras − tinta protegida
    mascara_final = cv2.subtract(barras, tinta_protegida)

    # Paso 5: blanquear solo la máscara final
    out = gray.copy()
    out[mascara_final > 0] = 255
    return out


def detectar_bloques(gray: np.ndarray, min_ancho_frac: float = 0.02,
                     hueco_min_frac: float = 0.03) -> list[tuple]:
    """
    Detecta los bloques de contenido (zonas con tinta separadas por huecos en
    blanco) recorriendo la proyección de tinta por columna. Cada bloque es una
    posición con algo escrito.
    """
    h, w = gray.shape
    _, b = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    proj = b.sum(axis=0) / 255
    tiene = proj > max(2, h * 0.02)

    bloques = []
    en = False
    ini = 0
    hueco_min = int(w * hueco_min_frac)
    for i, t in enumerate(tiene):
        if t and not en:
            ini = i; en = True
        elif not t and en:
            bloques.append([ini, i]); en = False
    if en:
        bloques.append([ini, len(tiene)])

    # Fusionar bloques separados por huecos muy pequeños (mismo dígito partido)
    fusionados = []
    for blo in bloques:
        if fusionados and blo[0] - fusionados[-1][1] < hueco_min:
            fusionados[-1][1] = blo[1]
        else:
            fusionados.append(blo)

    return [(a, b) for a, b in fusionados if (b - a) > w * min_ancho_frac]


def clasificar_bloque(gray: np.ndarray, x0: int, x1: int) -> Posicion:
    """Clasifica un bloque de contenido por su forma."""
    h, w = gray.shape
    sub = gray[:, x0:x1]
    _, b = cv2.threshold(sub, 100, 255, cv2.THRESH_BINARY_INV)
    ys, xs = np.where(b > 0)
    if len(ys) == 0:
        return Posicion(x0, x1, "vacio", 0.0, 0.0)
    alto = ys.max() - ys.min() + 1
    ancho = xs.max() - xs.min() + 1
    relleno = (b > 0).sum() / max(1, alto * ancho)
    alto_frac = alto / h

    # Reglas de forma. La señal más fiable para separar punto de dígito es el
    # RELLENO (qué fracción de su bounding box ocupa la tinta), no la altura
    # absoluta, que varía con el tamaño del recorte:
    #   - punto: mancha SÓLIDA, llena su bbox (relleno alto) y es baja
    #   - dígito: TRAZO, deja huecos (relleno bajo)
    #   - guion: muy bajo y claramente más ancho que alto
    if alto_frac < 0.18 and ancho > alto * 2.2:
        tipo = "guion"
    elif relleno > 0.5 and alto_frac < 0.30:
        tipo = "punto"
    elif relleno <= 0.45:
        tipo = "digito"          # trazo: dígito independientemente de su altura
    elif alto_frac >= 0.40:
        tipo = "digito"          # alto y algo relleno: dígito grueso
    else:
        tipo = "marca"           # ambiguo: dejar para revisión
    return Posicion(x0, x1, tipo, round(alto_frac, 2), round(relleno, 2))


def registrar_casilla(crop: np.ndarray, posiciones_esperadas: int = 3) -> RegistroCasilla:
    """
    Registra el estado de cada posición de una casilla, sin filtrar contenido.

    `posiciones_esperadas` es el formato típico (3). Si se detecta un número
    distinto, se marca como inconsistencia (p.ej. 4 posiciones como en '--47').
    """
    limpio = quitar_barras_borde(crop)
    bloques = detectar_bloques(limpio)
    posiciones = [clasificar_bloque(limpio, a, b) for a, b in bloques]

    n_dig = sum(1 for p in posiciones if p.tipo == "digito")
    n_pun = sum(1 for p in posiciones if p.tipo == "punto")
    n_gui = sum(1 for p in posiciones if p.tipo == "guion")

    banderas = []
    if len(bloques) == 0:
        banderas.append("casilla_vacia")
        banderas.append("espacio_sin_anular")   # vacía y sin guion/asterisco
    if len(bloques) > posiciones_esperadas:
        banderas.append(f"mas_de_{posiciones_esperadas}_posiciones")
    if any(p.tipo == "marca" for p in posiciones):
        banderas.append("posicion_ambigua")
    if n_gui > 0:
        banderas.append("contiene_guion")
    # Denuncia frecuente: la instrucción oficial exige anular con guiones o
    # asteriscos las casillas sin votos. Una casilla sin dígitos y sin guion
    # queda "abierta" — vulnerable a que se agreguen números después en la
    # cadena de custodia. Se registra como vulnerabilidad, no como fraude.
    if len(bloques) > 0 and n_dig == 0 and n_gui == 0:
        banderas.append("espacio_sin_anular")

    return RegistroCasilla(
        n_posiciones=len(bloques), posiciones=posiciones,
        n_digitos=n_dig, n_puntos=n_pun, n_guiones=n_gui,
        crop_limpio=limpio, banderas=banderas)


if __name__ == "__main__":
    import sys, fitz
    sys.path.insert(0, "..")
    import extractor as ex
    doc = fitz.open("../acta.pdf") if len(sys.argv) < 2 else fitz.open(sys.argv[1])
    res = ex.procesar_acta(sys.argv[1] if len(sys.argv) > 1 else "../acta.pdf", guardar=False)
    paginas = {}
    for p in range(min(3, len(doc))):
        img = ex.render_pagina(doc[p]); paginas[p+1] = ex.corregir_inclinacion(img)
    for c in res.casillas:
        if c.etiqueta in ("CONSTANCIAS",):
            continue
        img = paginas.get(c.pagina)
        if img is None:
            continue
        x, y, w, h = c.bbox
        reg = registrar_casilla(img[y:y+h, x:x+w])
        tipos = [p.tipo for p in reg.posiciones]
        print(f"{c.etiqueta:18s}: {reg.n_posiciones} pos {tipos} "
              f"{'⚠ '+','.join(reg.banderas) if reg.banderas else ''}")
