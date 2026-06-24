#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comparar_ejemplares.py — compara los NÚMEROS leídos de una misma mesa entre sus
ejemplares (CLAVEROS / DELEGADOS / TRANSMISIÓN). Dos ejemplares son copias de la
misma acta: deberían reportar lo mismo. Cuando difieren, una fue alterada... o el
OCR/jurado se equivocó. El comparador DETECTA y DOCUMENTA; no dictamina.

Detecta dos cosas:
  1. DISCREPANCIA por casilla: un mismo campo (candidato, blanco, total...) con
     valor distinto entre ejemplares.
  2. TRASLADO (doble fraude): dentro de una mesa, entre dos ejemplares, los votos
     de candidatos cambian pero su SUMA se mantiene -> se movieron votos de un
     candidato a otro. Invisible al chequeo aritmético (el total no cambia).
     El caso clásico: -100 a un candidato y +100 a otro (el "1" de las centenas).

ENTRADA: un CSV largo por ejemplar con columnas
    dep,muni,zona,puesto,mesa,etiqueta,valor[,conf]
(es la salida natural del clasificador por ejemplar). 'etiqueta' = CANDIDATO_01,
CANDIDATO_02, BLANCO, NULO, NO_MARCADO, SUMA_TOTAL, TOTAL_E11, ...

Uso:
    python comparar_ejemplares.py \
        --fuente CLAVEROS=claveros_numeros.csv \
        --fuente DELEGADOS=delegados_numeros.csv \
        --fuente TRANSMISION=transmision_numeros.csv \
        [--prefijo-candidato CANDIDATO] [--min-conf 0.0] [--salida comparacion_ejemplares]
"""
from __future__ import annotations
import argparse, csv
from collections import defaultdict
from itertools import combinations
from pathlib import Path


def _norm(x):
    s = str(x).strip()
    return str(int(s)) if s.isdigit() else s


def clave_mesa(r):
    return (_norm(r["dep"]), _norm(r["muni"]), _norm(r["zona"]), _norm(r["puesto"]), _norm(r["mesa"]))


def cargar_fuente(path, ejemplar):
    """CSV largo -> dict[(mesa)][etiqueta] = (valor:int, conf:float|None)."""
    out = defaultdict(dict)
    rd = csv.DictReader(open(path, encoding="utf-8-sig"))
    cols = {c.lower(): c for c in (rd.fieldnames or [])}
    cval = next((cols[c] for c in ("valor", "numero", "lectura", "valor_final") if c in cols), None)
    cet = cols.get("etiqueta")
    ccf = cols.get("conf") or cols.get("confianza")
    for r in rd:
        try:
            v = int(str(r[cval]).strip())
        except (ValueError, TypeError, KeyError):
            continue
        conf = None
        if ccf:
            try:
                conf = float(r[ccf])
            except (ValueError, TypeError):
                conf = None
        out[clave_mesa(r)][str(r[cet]).strip().upper()] = (v, conf)
    return out


def comparar(fuentes, prefijo_cand, min_conf, salida):
    # índice global: mesa -> etiqueta -> ejemplar -> (valor, conf)
    idx = defaultdict(lambda: defaultdict(dict))
    ejemplares = list(fuentes)
    for ej, data in fuentes.items():
        for mesa, celdas in data.items():
            for et, (v, c) in celdas.items():
                idx[mesa][et][ej] = (v, c)

    discrepancias, traslados = [], []
    mesas_con_disc, mesas_con_tras = set(), set()

    for mesa, celdas in idx.items():
        # --- pares de ejemplares presentes en la mesa ---
        presentes = set()
        for et, porej in celdas.items():
            presentes.update(porej)
        for ea, eb in combinations(sorted(presentes), 2):
            # discrepancias por casilla
            deltas_cand = {}
            for et, porej in celdas.items():
                if ea in porej and eb in porej:
                    (va, ca), (vb, cb) = porej[ea], porej[eb]
                    if va != vb:
                        if min_conf and ca is not None and cb is not None and (ca < min_conf or cb < min_conf):
                            continue   # descarta lecturas poco fiables si hay confianza
                        dif = vb - va
                        discrepancias.append({
                            "dep": mesa[0], "muni": mesa[1], "zona": mesa[2], "puesto": mesa[3], "mesa": mesa[4],
                            "etiqueta": et, "ej_a": ea, "valor_a": va, "ej_b": eb, "valor_b": vb,
                            "dif": dif, "abs_dif": abs(dif),
                            "multiplo_100": int(abs(dif) % 100 == 0 and dif != 0),
                            "conf_a": ca if ca is not None else "", "conf_b": cb if cb is not None else ""})
                        mesas_con_disc.add(mesa)
                        if et.upper().startswith(prefijo_cand):
                            deltas_cand[et] = dif
            # --- traslado: suma de deltas de candidatos == 0 pero hay movimiento ---
            if deltas_cand and sum(deltas_cand.values()) == 0 and any(d != 0 for d in deltas_cand.values()):
                ganan = {k: d for k, d in deltas_cand.items() if d > 0}
                pierden = {k: d for k, d in deltas_cand.items() if d < 0}
                monto = sum(d for d in deltas_cand.values() if d > 0)
                traslados.append({
                    "dep": mesa[0], "muni": mesa[1], "zona": mesa[2], "puesto": mesa[3], "mesa": mesa[4],
                    "ej_a": ea, "ej_b": eb, "monto": monto,
                    "ganan": ";".join(f"{k}(+{d})" for k, d in ganan.items()),
                    "pierden": ";".join(f"{k}({d})" for k, d in pierden.items()),
                    "multiplo_100": int(monto % 100 == 0)})
                mesas_con_tras.add(mesa)

    # --- escribir salidas ---
    discrepancias.sort(key=lambda r: (-r["multiplo_100"], -r["abs_dif"]))
    traslados.sort(key=lambda r: (-r["multiplo_100"], -r["monto"]))
    dpath = Path(salida + "_discrepancias.csv")
    with dpath.open("w", newline="", encoding="utf-8") as f:
        cols = ["dep", "muni", "zona", "puesto", "mesa", "etiqueta", "ej_a", "valor_a",
                "ej_b", "valor_b", "dif", "abs_dif", "multiplo_100", "conf_a", "conf_b"]
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(discrepancias)
    tpath = Path(salida + "_traslados.csv")
    with tpath.open("w", newline="", encoding="utf-8") as f:
        cols = ["dep", "muni", "zona", "puesto", "mesa", "ej_a", "ej_b", "monto",
                "ganan", "pierden", "multiplo_100"]
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(traslados)

    total_mesas = len(idx)
    print(f"=== COMPARACIÓN ENTRE EJEMPLARES ===")
    print(f"Ejemplares: {', '.join(ejemplares)}")
    print(f"Mesas comparables: {total_mesas:,}")
    print(f"  con DISCREPANCIA en alguna casilla: {len(mesas_con_disc):,} "
          f"({100*len(mesas_con_disc)/max(1,total_mesas):.2f}%)")
    print(f"  con TRASLADO (total preservado):    {len(mesas_con_tras):,} "
          f"({100*len(mesas_con_tras)/max(1,total_mesas):.2f}%)  <- señal fuerte")
    tras100 = sum(1 for t in traslados if t["multiplo_100"])
    print(f"     de ellos, traslados de múltiplo de 100: {tras100:,}")
    print(f"\nDetalle: {dpath}  y  {tpath}")
    print("\nNota: una discrepancia puede ser error de OCR, lapsus de digitación del")
    print("jurado, o alteración. Prioriza: traslado con total preservado, múltiplos de")
    print("100, y (si hay confianza) lecturas fiables en ambos ejemplares.")


def main():
    ap = argparse.ArgumentParser(description="Compara números leídos entre ejemplares de la misma mesa")
    ap.add_argument("--fuente", action="append", required=True, metavar="EJEMPLAR=ruta.csv",
                    help="repetir por ejemplar, p.ej. --fuente CLAVEROS=claveros.csv")
    ap.add_argument("--prefijo-candidato", default="CANDIDATO")
    ap.add_argument("--min-conf", type=float, default=0.0, help="si los CSV traen 'conf', ignora discrepancias por debajo")
    ap.add_argument("--salida", default="comparacion_ejemplares")
    a = ap.parse_args()

    fuentes = {}
    for f in a.fuente:
        if "=" not in f:
            raise SystemExit(f"--fuente debe ser EJEMPLAR=ruta.csv (recibí: {f})")
        nombre, ruta = f.split("=", 1)
        fuentes[nombre.strip().upper()] = cargar_fuente(ruta, nombre.strip().upper())
        print(f"Cargado {nombre.strip().upper()}: {len(fuentes[nombre.strip().upper()]):,} mesas")
    if len(fuentes) < 2:
        raise SystemExit("Hacen falta al menos 2 ejemplares para comparar.")
    print()
    comparar(fuentes, a.prefijo_candidato.upper(), a.min_conf, a.salida)


if __name__ == "__main__":
    main()