#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integridad de los PDF descargados — para cada ejemplar de una ronda
(DELEGADOS/TRANSMISIÓN vía el visor, CLAVEROS vía escrutinios) verifica:

  1. estructura: cada PDF empieza con %PDF- y cierra con %%EOF (detecta
     truncados/corruptos sin depender de pymupdf). El nombre de archivo del
     visor de transmisión PARECE un sha256 (64 hex) pero NO lo es -> se
     comprobó a mano (sha256sum real ≠ nombre) que es solo un ID opaco del
     storage de la Registraduría, así que no sirve para verificar contenido
     y no se usa como chequeo.
  2. cobertura: cruza el último manifiesto (jsonl/csv) contra los archivos en
     disco -> qué se planeó descargar pero no quedó (error de red, etc). Para
     DELEGADOS/TRANSMISIÓN la ruta absoluta grabada en el manifiesto es de
     OTRA máquina/usuario (julianquin) -> se reconstruye la ruta esperada a
     partir de los códigos (dep/muni/zona/puesto + expected_name), no del
     campo 'path'.
  3. comparación entre ejemplares: cuenta PDFs por departamento en cada
     ejemplar y señala huecos de un ejemplar frente a los otros. Así se
     confirma/cuantifica el caso conocido: CLAVEROS no tiene NADA del
     departamento 88 (CONSULADOS/exterior), y no es un fallo del
     descargador — el index.json de escrutinios nunca publicó puestos para
     ese departamento (0 de 22.876 claves), mientras el visor de
     transmisión sí trae 3.670/3.666 actas de dep=88.

NO requiere pymupdf/opencv: solo librería estándar, para poder correr rápido
sobre los ~360k PDFs (163 GB) sin el entorno pesado de Fase 1.

Uso:
    python -m e14.validacion.integridad_pdfs \
        --base data/segunda_vuelta \
        --ejemplar delegados=e14_pdfs_2v \
        --ejemplar transmision=e14_pdfs_2v_t \
        --ejemplar claveros=e14_pdfs_claveros \
        --out reporte_integridad_2v
"""
from __future__ import annotations
import argparse, csv, json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


# ------------------------------ chequeo por archivo --------------------------
def chequear_pdf(path_str: str):
    """Estructura mínima: cabecera %PDF- y cola %%EOF. Solo lee la cola en
    modo binario con seek desde el final -> no carga el archivo entero."""
    path = Path(path_str)
    problemas = []
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if not head.startswith(b"%PDF-"):
                problemas.append("sin_cabecera_pdf")
            f.seek(0, 2)
            tam = f.tell()
            f.seek(max(0, tam - 2048))
            cola = f.read()
        if b"%%EOF" not in cola:
            problemas.append("sin_eof")
    except Exception as exc:
        problemas.append(f"error_lectura:{exc!r}")
    return path_str, problemas


def _departamento(path: Path, raiz: Path) -> str:
    """Código de depto = primer directorio numérico de 2 dígitos bajo la raíz
    del ejemplar (PRE/dep/... en el visor, docs/E14/dep/... en claveros)."""
    rel = path.relative_to(raiz).parts
    for p in rel:
        if len(p) == 2 and p.isdigit():
            return p
    return "??"


# --------------------------------- escaneo ------------------------------------
def escanear_ejemplar(nombre: str, raiz: Path, workers: int):
    pdfs = [str(p) for p in raiz.rglob("*.pdf")]
    print(f"[{nombre}] {len(pdfs):,} PDF encontrados bajo {raiz} — chequeando estructura/hash...")

    corruptos = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for path_str, problemas in ex.map(chequear_pdf, pdfs, chunksize=200):
            if problemas:
                corruptos.append((path_str, ";".join(problemas)))

    conteo_dep = Counter(_departamento(Path(p), raiz) for p in pdfs)
    print(f"[{nombre}] corruptos/con problema: {len(corruptos):,}")
    return {"total": len(pdfs), "corruptos": corruptos, "por_departamento": conteo_dep}


# ------------------------------ cobertura (manifiesto) ------------------------
def _ultimo(dir_logs: Path, patron: str) -> Path | None:
    cands = sorted(dir_logs.glob(patron))
    return cands[-1] if cands else None


def cobertura_visor(raiz: Path):
    """DELEGADOS/TRANSMISIÓN: manifest_*.jsonl. El campo 'path' es una ruta
    absoluta grabada en OTRA máquina/usuario -> se reconstruye la ruta local
    esperada a partir de los códigos (dep/muni/zona/puesto + expected_name),
    que sí son estables entre máquinas."""
    man = _ultimo(raiz / "_logs", "manifest_*.jsonl")
    if not man:
        return None
    planeados = ok = 0
    faltantes = []
    with open(man, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            planeados += 1
            p = (raiz / "PRE" / d["department_code"] / d["municipality_code"] / d["zone_code"]
                 / d["stand_code"] / d["number_table"] / d["expected_name"])
            if p.exists():
                ok += 1
            else:
                faltantes.append((d.get("status", ""), d.get("id_transmission_code", ""),
                                   d.get("department_name", ""), d.get("municipality_name", ""), str(p)))
    return {"manifiesto": man.name, "planeados": planeados, "en_disco": ok,
            "faltantes": faltantes}


def cobertura_claveros(raiz: Path):
    """CLAVEROS: claveros_mesas.csv es ACUMULATIVO entre reorganizaciones de
    directorio -> trae filas viejas con 'ruta_local' relativa a una carpeta
    de salida abandonada (prefijo del nombre de la carpeta del ejemplar, sin
    'data/...'). Esas rutas nunca van a existir en el layout actual y no son
    un hueco real (el propio manifest de la corrida final ya las reporta
    'skip' = ya estaban) -> se descartan y solo se cruzan las filas con la
    ruta del layout actual (prefijo 'data/', relativa a la raíz del
    proyecto), dedupe por ruta quedándonos con el ÚLTIMO estado visto."""
    csvp = raiz / "claveros_mesas.csv"
    if not csvp.exists():
        return None
    ultimo_estado, descartadas = {}, 0
    with open(csvp, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rel = r["ruta_local"].replace("\\", "/")
            if not rel.startswith("data/"):     # ruta relativa al cwd del proceso que corrió la descarga
                descartadas += 1
                continue
            ultimo_estado[rel] = r["estado"]
    if descartadas:
        print(f"  [claveros] {descartadas:,} filas del CSV de layouts de carpeta abandonados (ignoradas)")
    planeados = len(ultimo_estado)
    faltantes = [(estado, "", "", "", p) for p, estado in ultimo_estado.items() if not Path(p).exists()]
    ok = planeados - len(faltantes)
    return {"manifiesto": "claveros_mesas.csv", "planeados": planeados, "en_disco": ok,
            "faltantes": faltantes}


# ------------------------------ comparación entre ejemplares ------------------
def comparar_departamentos(conteos: dict[str, Counter]):
    deps = sorted(set().union(*[set(c) for c in conteos.values()]))
    filas = []
    for d in deps:
        fila = {"dep": d, **{nom: conteos[nom].get(d, 0) for nom in conteos}}
        valores = list(fila[nom] for nom in conteos)
        if max(valores) > 0 and min(valores) == 0:
            fila["bandera"] = "HUECO_TOTAL"
        elif max(valores) and (min(valores) / max(valores)) < 0.5:
            fila["bandera"] = "DIVERGENCIA_FUERTE"
        else:
            fila["bandera"] = ""
        filas.append(fila)
    return filas


# ------------------------------------ main -------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Chequeo de integridad de los PDF E-14 descargados")
    ap.add_argument("--base", required=True, help="carpeta de la ronda, p.ej. data/segunda_vuelta")
    ap.add_argument("--ejemplar", action="append", required=True, metavar="NOMBRE=SUBCARPETA",
                     help="repetible: delegados=e14_pdfs_2v, transmision=e14_pdfs_2v_t, claveros=e14_pdfs_claveros")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="reporte_integridad")
    a = ap.parse_args()

    base = Path(a.base)
    ejemplares = dict(kv.split("=", 1) for kv in a.ejemplar)

    resultados, conteos = {}, {}
    for nombre, sub in ejemplares.items():
        raiz = base / sub
        res = escanear_ejemplar(nombre, raiz, a.workers)
        if nombre == "claveros":
            res["cobertura"] = cobertura_claveros(raiz)
        else:
            res["cobertura"] = cobertura_visor(raiz)
        resultados[nombre] = res
        conteos[nombre] = res["por_departamento"]

    # --- reportes ---
    out = Path(a.out)
    with open(out.with_suffix(".corruptos.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["ejemplar", "path", "problema"])
        for nombre, res in resultados.items():
            for path_str, problema in res["corruptos"]:
                w.writerow([nombre, path_str, problema])

    with open(out.with_suffix(".faltantes.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["ejemplar", "status_manifiesto", "id_transmission", "depto", "municipio", "path"])
        for nombre, res in resultados.items():
            cob = res.get("cobertura")
            if not cob:
                continue
            for status, idt, dep, muni, p in cob["faltantes"]:
                w.writerow([nombre, status, idt, dep, muni, p])

    filas_dep = comparar_departamentos(conteos)
    with open(out.with_suffix(".departamentos.csv"), "w", newline="", encoding="utf-8") as f:
        cols = ["dep"] + list(ejemplares) + ["bandera"]
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(filas_dep)

    # --- resumen en pantalla ---
    print("\n=== RESUMEN INTEGRIDAD ===")
    for nombre, res in resultados.items():
        cob = res.get("cobertura")
        print(f"\n[{nombre}]  total en disco: {res['total']:,}  |  corruptos/con problema: {len(res['corruptos']):,}")
        if cob:
            print(f"  manifiesto {cob['manifiesto']}: planeados={cob['planeados']:,}  en_disco={cob['en_disco']:,}  "
                  f"faltantes={len(cob['faltantes']):,}")

    huecos = [f for f in filas_dep if f["bandera"]]
    if huecos:
        print(f"\n=== DEPARTAMENTOS CON DIVERGENCIA ENTRE EJEMPLARES ({len(huecos)}) ===")
        for f in huecos:
            resto = "  ".join(f"{nom}={f[nom]:,}" for nom in ejemplares)
            print(f"  dep={f['dep']}  {resto}  <- {f['bandera']}")
    else:
        print("\nSin divergencias de cobertura por departamento entre ejemplares.")

    print(f"\nCSV: {out}.corruptos.csv | {out}.faltantes.csv | {out}.departamentos.csv")


if __name__ == "__main__":
    main()
