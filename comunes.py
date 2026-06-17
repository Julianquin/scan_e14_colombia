#!/usr/bin/env python3
"""
Constantes y utilidades compartidas de ScanE14.

Fuente ÚNICA de verdad para las etiquetas del formato E-14 y para un par de
helpers que antes estaban duplicados entre la raíz y `fase1/`.

Este módulo es PURO (solo librería estándar): no importa cv2, fitz ni numpy,
para que pueda usarse desde cualquier fase (incluida la lógica de validación
aritmética) sin arrastrar las dependencias de visión por computador.
"""

from __future__ import annotations

import re
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# ETIQUETAS DEL FORMATO E-14 PRESIDENCIAL 2026
# ─────────────────────────────────────────────────────────────────────────────

CANDIDATOS = list(range(1, 14))                       # 1..13
CAND = [f"cand_{i:02d}" for i in CANDIDATOS]          # ["cand_01", ..., "cand_13"]

# Bloque de nivelación de la mesa (página 1).
NIVELACION = ["TOTAL_E11", "TOTAL_URNA", "TOTAL_INCINERADOS"]

# Agregados (página 2): votos en blanco / nulos / no marcados / suma total.
AGREGADOS = ["BLANCO", "NULO", "NO_MARCADO", "SUMA_TOTAL"]

# Las 20 casillas que contienen un número (sin CONSTANCIAS, que es texto libre).
CASILLAS_NUMERICAS = NIVELACION + CAND + AGREGADOS


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def parsear_ruta(pdf_path) -> dict:
    """
    Extrae los códigos de ubicación de la ruta del PDF.

    Estructura esperada:
        .../PRE/{dep}/{muni}/{zona}/{puesto}/{mesa}/archivo.pdf

    Devuelve siempre las claves dep, muni, zona, puesto, mesa y archivo
    (vacías si la ruta no sigue el patrón).
    """
    p = Path(pdf_path)
    partes = p.parts
    datos = {"dep": "", "muni": "", "zona": "", "puesto": "", "mesa": "",
             "archivo": p.name}
    try:
        i = partes.index("PRE")
        datos["dep"]    = partes[i + 1]
        datos["muni"]   = partes[i + 2]
        datos["zona"]   = partes[i + 3]
        datos["puesto"] = partes[i + 4]
        datos["mesa"]   = partes[i + 5]
    except (ValueError, IndexError):
        pass
    return datos


def solo_digitos(texto: str) -> str:
    """Deja solo los dígitos 0-9 del texto reconocido por el OCR."""
    return re.sub(r"\D", "", texto or "")


if __name__ == "__main__":
    # Auto-comprobación rápida (no requiere dependencias externas).
    assert len(CAND) == 13
    assert len(CASILLAS_NUMERICAS) == 20
    assert parsear_ruta("x/PRE/05/001/00/01/001/acta.pdf")["dep"] == "05"
    assert parsear_ruta("ruta/rara/acta.pdf")["dep"] == ""
    assert solo_digitos("1o7") == "17"
    print("comunes.py OK")
    print("  CAND:", CAND)
    print("  CASILLAS_NUMERICAS:", CASILLAS_NUMERICAS)
