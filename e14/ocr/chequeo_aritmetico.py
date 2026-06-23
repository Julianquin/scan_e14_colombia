#!/usr/bin/env python3
"""
Fase 1 — Chequeo aritmético de un acta E-14.

Dada la lectura de los números (de OCR o manual), verifica las identidades que
DEBEN cumplirse en un acta correcta:

  (1) suma(candidatos 1..13) + BLANCO + NULO + NO_MARCADO == SUMA_TOTAL
  (2) SUMA_TOTAL == TOTAL_E11   (votos contabilizados == votantes según E-11)

La inconsistencia aritmética es la señal de fraude MÁS confiable, pero recuerda:
una inconsistencia puede ser fraude O un error de diligenciamiento (o de OCR).
Por eso esto MARCA para revisión, no dictamina. Las constancias y el cruce con
el preconteo (Fase 2) ayudan a interpretar.
"""
from __future__ import annotations
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comunes import CAND


@dataclass
class ResultadoChequeo:
    suma_candidatos: Optional[int] = None
    suma_calculada: Optional[int] = None      # candidatos + blanco + nulo + no_marcado
    suma_total_leida: Optional[int] = None
    total_e11: Optional[int] = None
    cuadra_suma: Optional[bool] = None        # (1)
    cuadra_e11: Optional[bool] = None         # (2)
    diferencia_suma: Optional[int] = None
    diferencia_e11: Optional[int] = None
    incompleto: bool = False                  # faltan números para chequear
    notas: list = field(default_factory=list)


def _val(numeros: dict, clave: str) -> Optional[int]:
    """Obtiene un número leído; None si no se leyó o no es entero."""
    v = numeros.get(clave)
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def chequear(numeros: dict) -> ResultadoChequeo:
    """
    `numeros` es un dict {etiqueta: valor_int} con las lecturas. Las casillas
    vacías deben venir como 0 (no como None) para distinguir "leído como vacío"
    de "no se pudo leer".
    """
    r = ResultadoChequeo()

    cand_vals = [_val(numeros, c) for c in CAND]
    blanco = _val(numeros, "BLANCO")
    nulo = _val(numeros, "NULO")
    no_marcado = _val(numeros, "NO_MARCADO")
    suma_total = _val(numeros, "SUMA_TOTAL")
    e11 = _val(numeros, "TOTAL_E11")

    r.suma_total_leida = suma_total
    r.total_e11 = e11

    # ¿Tenemos todo lo necesario para el chequeo (1)?
    componentes = cand_vals + [blanco, nulo, no_marcado]
    if any(v is None for v in componentes) or suma_total is None:
        r.incompleto = True
        r.notas.append("Faltan lecturas para el chequeo de suma")
    else:
        r.suma_candidatos = sum(cand_vals)
        r.suma_calculada = r.suma_candidatos + blanco + nulo + no_marcado
        r.diferencia_suma = r.suma_calculada - suma_total
        r.cuadra_suma = (r.diferencia_suma == 0)

    # Chequeo (2): SUMA_TOTAL == TOTAL_E11
    if suma_total is not None and e11 is not None:
        r.diferencia_e11 = suma_total - e11
        r.cuadra_e11 = (r.diferencia_e11 == 0)
    else:
        r.notas.append("Falta SUMA_TOTAL o TOTAL_E11 para el chequeo E-11")

    return r


def nivel_alerta(r: ResultadoChequeo) -> str:
    """
    Traduce el resultado a un nivel de alerta para priorizar revisión.
    NINGUNO no implica "acta limpia": implica "cuadra aritméticamente".
    """
    if r.incompleto:
        return "INCOMPLETO"
    # Ambos chequeos disponibles
    fallos = 0
    if r.cuadra_suma is False:
        fallos += 1
    if r.cuadra_e11 is False:
        fallos += 1
    if fallos == 2:
        return "ALTA"          # ni la suma interna ni el E-11 cuadran
    if fallos == 1:
        return "MEDIA"
    return "NINGUNA"


if __name__ == "__main__":
    # Demostración con el acta de ejemplo (mesa 026 Leticia)
    ejemplo = {
        "cand_01": 69, "cand_02": 0, "cand_03": 3, "cand_04": 42,
        "cand_05": 0, "cand_06": 0, "cand_07": 0, "cand_08": 0,
        "cand_09": 0, "cand_10": 0, "cand_11": 7, "cand_12": 3, "cand_13": 0,
        "BLANCO": 2, "NULO": 0, "NO_MARCADO": 0,
        "SUMA_TOTAL": 126, "TOTAL_E11": 126,
    }
    r = chequear(ejemplo)
    print("Chequeo del acta de ejemplo:")
    print(f"  Suma candidatos:        {r.suma_candidatos}")
    print(f"  Suma calculada:         {r.suma_calculada}")
    print(f"  SUMA_TOTAL leída:       {r.suma_total_leida}")
    print(f"  TOTAL_E11:              {r.total_e11}")
    print(f"  ¿Cuadra suma interna?   {r.cuadra_suma}  (dif {r.diferencia_suma})")
    print(f"  ¿Cuadra con E-11?       {r.cuadra_e11}  (dif {r.diferencia_e11})")
    print(f"  Nivel de alerta:        {nivel_alerta(r)}")
