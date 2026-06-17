#!/usr/bin/env python3
"""
Genera un listado de actas a revisar a partir del CSV de procesar_lote.py.

Filtra las actas con banderas de consistencia (prioridad ALTA/MEDIA) y produce
un CSV ordenado por prioridad, listo para revisión humana. Esto es un adelanto
de la Fase 1 que NO usa OCR: solo el patrón de casillas llenas/vacías.

IMPORTANTE: una bandera NO significa fraude. Son señales de que el acta merece
mirada humana. Muchas serán errores de diligenciamiento (p.ej. suma sin llenar).

Uso:
    python listar_anomalias.py resultados/casillas_e14.csv --salida anomalias.csv
"""
import csv, argparse
from pathlib import Path
from collections import Counter

PRIORIDAD_ORDEN = {"ALTA": 0, "MEDIA": 1, "OK": 2}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="CSV de procesar_lote.py")
    ap.add_argument("--salida", default="anomalias.csv")
    ap.add_argument("--incluir-media", action="store_true",
                    help="Incluir también prioridad MEDIA (por defecto solo ALTA)")
    a = ap.parse_args()

    filas = []
    conteo = Counter()
    total = 0
    with open(a.csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            total += 1
            pr = row.get("prioridad_revision", "OK")
            conteo[pr] += 1
            if pr == "ALTA" or (a.incluir_media and pr == "MEDIA"):
                filas.append(row)

    # Ordenar por prioridad y luego por departamento/municipio
    filas.sort(key=lambda r: (PRIORIDAD_ORDEN.get(r.get("prioridad_revision"), 9),
                              r.get("dep",""), r.get("muni","")))

    cols = ["prioridad_revision","dep","muni","zona","puesto","mesa",
            "n_cand_con_voto","suma_vacia_con_votos","sin_ningun_voto",
            "suma_con_todo_vacio","todos_candidatos_llenos","agregados_sin_suma",
            "tiene_constancias","uso_plantilla","pdf"]
    with open(a.salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)

    print(f"Total actas en CSV:      {total:,}")
    print(f"  Prioridad ALTA:  {conteo['ALTA']:,}  ({100*conteo['ALTA']/max(total,1):.1f}%)")
    print(f"  Prioridad MEDIA: {conteo['MEDIA']:,}  ({100*conteo['MEDIA']/max(total,1):.1f}%)")
    print(f"  OK:              {conteo['OK']:,}")
    print(f"\nActas en el listado de revisión: {len(filas):,}")
    print(f"Guardado en: {Path(a.salida).resolve()}")
    print(f"\nRecuerda: una bandera NO es fraude. Es una señal para revisión humana.")
    print(f"Muchas serán errores de diligenciamiento (ej. suma sin llenar).")

if __name__ == "__main__":
    main()
