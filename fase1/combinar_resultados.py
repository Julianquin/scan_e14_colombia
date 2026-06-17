#!/usr/bin/env python3
"""
Fase 1 (local) — Combina los números leídos en Kaggle con el chequeo aritmético.

Toma numeros_leidos.csv (salida del notebook TrOCR) y produce, por cada mesa,
los 21 valores + el resultado del chequeo aritmético + nivel de alerta.

Uso:
    python combinar_resultados.py numeros_leidos.csv --salida actas_verificadas.csv
"""
import sys, csv, argparse
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chequeo_aritmetico as chk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("numeros_csv", help="numeros_leidos.csv (de Kaggle)")
    ap.add_argument("--salida", default="actas_verificadas.csv")
    a = ap.parse_args()

    # Agrupar por mesa
    por_mesa = defaultdict(dict)
    ubic_mesa = {}
    with open(a.numeros_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            clave = (r["dep"], r["muni"], r["zona"], r["puesto"], r["mesa"])
            num = r.get("numero", "")
            por_mesa[clave][r["etiqueta"]] = int(num) if num.isdigit() else None
            ubic_mesa[clave] = r

    filas = []
    conteo = {"ALTA":0,"MEDIA":0,"NINGUNA":0,"INCOMPLETO":0}
    for clave, numeros in por_mesa.items():
        # Las casillas no leídas (vacías) se asumen 0
        completo = {}
        for et in chk.CAND + ["BLANCO","NULO","NO_MARCADO","SUMA_TOTAL","TOTAL_E11","TOTAL_URNA","TOTAL_INCINERADOS"]:
            completo[et] = numeros.get(et, 0) if numeros.get(et) is not None else 0
        r = chk.chequear(completo)
        alerta = chk.nivel_alerta(r)
        conteo[alerta] = conteo.get(alerta,0)+1
        dep,muni,zona,puesto,mesa = clave
        fila = {"dep":dep,"muni":muni,"zona":zona,"puesto":puesto,"mesa":mesa,
                "suma_candidatos":r.suma_candidatos,"suma_calculada":r.suma_calculada,
                "suma_total":r.suma_total_leida,"total_e11":r.total_e11,
                "cuadra_suma":r.cuadra_suma,"cuadra_e11":r.cuadra_e11,
                "dif_suma":r.diferencia_suma,"dif_e11":r.diferencia_e11,
                "alerta":alerta}
        for et in chk.CAND + ["BLANCO","NULO","NO_MARCADO","SUMA_TOTAL","TOTAL_E11","TOTAL_URNA","TOTAL_INCINERADOS"]:
            fila[et] = completo[et]
        filas.append(fila)

    # ordenar por alerta (ALTA primero)
    orden = {"ALTA":0,"MEDIA":1,"INCOMPLETO":2,"NINGUNA":3}
    filas.sort(key=lambda f: orden.get(f["alerta"],9))

    with open(a.salida,"w",newline="",encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()), extrasaction="ignore")
        w.writeheader(); w.writerows(filas)

    print(f"Actas verificadas: {len(filas):,}")
    for k in ["ALTA","MEDIA","NINGUNA","INCOMPLETO"]:
        print(f"   {k:11s}: {conteo.get(k,0):,}")
    print(f"\nGuardado: {a.salida}")
    print("Las de alerta ALTA/MEDIA son las que NO cuadran aritméticamente:")
    print("revisión humana con el recorte + constancias para decidir.")


if __name__ == "__main__":
    main()
