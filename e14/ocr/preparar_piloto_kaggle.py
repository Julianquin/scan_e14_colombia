#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preparar_piloto_kaggle.py — arma el paquete del piloto OCR de ~500 actas en
Kaggle (2da vuelta): selecciona mesas estratificadas por departamento,
presentes en los 3 ejemplares (DELEGADOS/TRANSMISION/CLAVEROS ya filtrados
por posiciones_2v.py exportar, sin las atípicas de cola_revision.csv), copia
sus recortes a una carpeta plana y genera un índice con nombres de archivo
RELATIVOS — ocr_trocr_kaggle.py espera RECORTES_DIR / archivo, y las rutas
locales absolutas del indice_recortes.csv original no existen una vez subido
el zip a Kaggle.

Uso:
    python preparar_piloto_kaggle.py --n 500 --salida data/segunda_vuelta/piloto_kaggle_2v
    cd data/segunda_vuelta && zip -rq piloto_kaggle_2v.zip piloto_kaggle_2v
    # sube piloto_kaggle_2v.zip como Dataset en Kaggle
"""
from __future__ import annotations
import argparse, csv, random, shutil
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
EJEMPLARES = {
    "DELEGADOS": RAIZ / "data" / "segunda_vuelta" / "recortes_delegados",
    "TRANSMISION": RAIZ / "data" / "segunda_vuelta" / "recortes_transmision",
    "CLAVEROS": RAIZ / "data" / "segunda_vuelta" / "recortes_claveros",
}


def _leer_indice(dir_recortes: Path):
    """clave (dep,muni,zona,puesto,mesa) -> lista de filas del indice_recortes.csv."""
    por_mesa = defaultdict(list)
    with open(dir_recortes / "indice_recortes.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            clave = (r["dep"], r["muni"], r["zona"], r["puesto"], r["mesa"])
            por_mesa[clave].append(r)
    return por_mesa


def preparar(n_total: int, salida: str, seed: int):
    rng = random.Random(seed)
    print("Leyendo los 3 indice_recortes.csv...")
    indices = {e: _leer_indice(d) for e, d in EJEMPLARES.items() if (d / "indice_recortes.csv").exists()}
    for e, idx in indices.items():
        print(f"  {e}: {len(idx):,} mesas con recortes")

    comunes = set.intersection(*(set(idx) for idx in indices.values()))
    print(f"Mesas presentes en los {len(indices)} ejemplares: {len(comunes):,}")

    por_dep = defaultdict(list)
    for clave in comunes:
        por_dep[clave[0]].append(clave)

    total = len(comunes)
    seleccion = []
    for dep, claves in por_dep.items():
        cuota = max(1, round(n_total * len(claves) / total))
        seleccion.extend(rng.sample(claves, min(cuota, len(claves))))
    if len(seleccion) > n_total:
        seleccion = rng.sample(seleccion, n_total)
    print(f"Mesas seleccionadas (estratificado por depto): {len(seleccion)}")

    salida = Path(salida); salida.mkdir(parents=True, exist_ok=True)
    idx_out = (salida / "indice_recortes.csv").open("w", newline="", encoding="utf-8")
    w = csv.writer(idx_out)
    w.writerow(["ejemplar", "dep", "muni", "zona", "puesto", "mesa", "etiqueta", "archivo"])

    n_copiados = 0
    for clave in seleccion:
        for ejemplar, idx in indices.items():
            for r in idx[clave]:
                origen = RAIZ / r["ruta"]
                nombre = origen.name
                shutil.copy2(origen, salida / nombre)
                w.writerow([ejemplar, *clave, r["etiqueta"], nombre])
                n_copiados += 1
    idx_out.close()
    print(f"\nHecho. {len(seleccion)} mesas x {len(indices)} ejemplares x 9 casillas = "
          f"{n_copiados} recortes copiados en {salida}/")
    print(f"\nSiguiente paso:")
    print(f"  cd {salida.parent}")
    print(f"  zip -rq {salida.name}.zip {salida.name}")
    print(f"  # sube {salida.name}.zip como Dataset en Kaggle (Datasets -> New Dataset -> Upload)")


def main():
    ap = argparse.ArgumentParser(description="Prepara el paquete del piloto OCR (Kaggle) para 2da vuelta")
    ap.add_argument("--n", type=int, default=500, help="mesas totales (comunes a los 3 ejemplares)")
    ap.add_argument("--salida", default="data/segunda_vuelta/piloto_kaggle_2v")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    preparar(a.n, a.salida, a.seed)


if __name__ == "__main__":
    main()
