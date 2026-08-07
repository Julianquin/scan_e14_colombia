#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_segmentacion_2v.py — QA a escala de la geometría de posiciones_2v.py antes
de quemar cómputo de OCR sobre las ~360k actas de 2da vuelta.

Dos modos:

  barrido   — recorre una muestra grande de cada ejemplar SIN rasterizar
              (solo lee metadata de la imagen incrustada: dimensiones,
              nº de páginas). Barato, sirve para detectar outliers de forma
              masiva: fotos en vez de escaneos, rotaciones, tamaños atípicos.

  muestra   — toma la intersección de mesas presentes en los 3 ejemplares,
              estratifica por departamento (proporcional al nº de mesas de
              cada uno) y genera montajes de QA visual (posiciones_2v.probar)
              para revisión humana, agrupados por departamento.

Uso:
    python qa_segmentacion_2v.py barrido --n 3000 --out barrido_2v.csv
    python qa_segmentacion_2v.py muestra --n 200 --out revision_muestra_2v
"""
from __future__ import annotations
import argparse, csv, random, statistics, sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "e14" / "extraccion"))
import posiciones_2v as P2V  # noqa: E402

EJEMPLARES = {
    "DELEGADOS": RAIZ / "data" / "segunda_vuelta" / "e14_pdfs_2v",
    "TRANSMISION": RAIZ / "data" / "segunda_vuelta" / "e14_pdfs_2v_t",
    "CLAVEROS": RAIZ / "data" / "segunda_vuelta" / "e14_pdfs_claveros",
}


def listar_pdfs(dir_ejemplar: Path):
    return [p for p in dir_ejemplar.rglob("*.pdf") if "_logs" not in p.parts]


# ---------------------------------------------------------------- barrido --

def _info_pagina1(pdf_path: Path):
    """Metadata barata de la página 1: dims de la imagen incrustada + nº páginas,
    sin rasterizar (extract_image copia los bytes del XObject, no decodifica)."""
    fitz = P2V._fitz()
    doc = fitz.open(pdf_path)
    n_paginas = doc.page_count
    page = doc[0]
    imgs = page.get_images(full=True)
    if not imgs:
        return {"n_paginas": n_paginas, "img_w": 0, "img_h": 0, "colorspace": -1,
                "rect_w": page.rect.width, "rect_h": page.rect.height, "n_imgs": 0,
                "aspecto_calc": 0.0}
    base = doc.extract_image(imgs[0][0])
    w, h = base["width"], base["height"]
    return {"n_paginas": n_paginas, "img_w": w, "img_h": h,
            "colorspace": base.get("colorspace"), "rect_w": page.rect.width,
            "rect_h": page.rect.height, "n_imgs": len(imgs),
            "aspecto_calc": (h / w) if w else 0.0}


def barrido(n_por_ejemplar: int, out_csv: str, seed: int):
    """outlier=1 usa el MISMO criterio que el filtro real de exportar()
    (P2V.es_formato_estandar, aspecto fijo +-tolerancia) — no una mediana
    local — para que este diagnóstico prediga exactamente qué va a caer en
    cola_revision.csv al exportar en serio."""
    rng = random.Random(seed)
    filas = []
    aspectos = defaultdict(list)

    for ejemplar, dir_e in EJEMPLARES.items():
        if not dir_e.exists():
            print(f"! {ejemplar}: no existe {dir_e}, se omite"); continue
        pdfs = listar_pdfs(dir_e)
        muestra = rng.sample(pdfs, min(n_por_ejemplar, len(pdfs)))
        print(f"{ejemplar}: muestreando {len(muestra)} de {len(pdfs)} PDFs...")
        for i, pdf in enumerate(muestra, 1):
            try:
                dep, muni, zona, puesto, mesa = P2V.parsear_clave(pdf)
                info = _info_pagina1(pdf)
                estandar = (info["img_w"] > 0 and
                            abs(info["aspecto_calc"] - P2V.ASPECTO_ESTANDAR) / P2V.ASPECTO_ESTANDAR
                            <= P2V.ASPECTO_TOLERANCIA)
                aspectos[ejemplar].append(info["aspecto_calc"])
                filas.append({"ejemplar": ejemplar, "dep": dep, "muni": muni, "zona": zona,
                              "puesto": puesto, "mesa": mesa, "ruta": str(pdf), **info,
                              "aspecto": round(info["aspecto_calc"], 4), "outlier": int(not estandar)})
            except Exception as exc:
                filas.append({"ejemplar": ejemplar, "dep": "", "muni": "", "zona": "",
                              "puesto": "", "mesa": "", "ruta": str(pdf), "n_paginas": -1,
                              "img_w": -1, "img_h": -1, "colorspace": -1, "rect_w": -1,
                              "rect_h": -1, "n_imgs": -1, "aspecto": -1, "outlier": -1,
                              "error": str(exc)})
            if i % 500 == 0:
                print(f"  {i}/{len(muestra)}")

    medianas = {e: (statistics.median(v) if v else 0.0) for e, v in aspectos.items()}

    cols = ["ejemplar", "dep", "muni", "zona", "puesto", "mesa", "n_paginas", "img_w",
            "img_h", "colorspace", "n_imgs", "aspecto", "outlier", "ruta", "error"]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            fila.setdefault("error", "")
            w.writerow(fila)

    print(f"\n--- Resumen barrido (criterio: aspecto {P2V.ASPECTO_ESTANDAR:.2f} "
          f"+-{P2V.ASPECTO_TOLERANCIA:.0%}, igual al filtro real de exportar) ---")
    for ejemplar in EJEMPLARES:
        sub = [f for f in filas if f["ejemplar"] == ejemplar]
        n_out = sum(1 for f in sub if f["outlier"] == 1)
        n_err = sum(1 for f in sub if f.get("error"))
        n_pag = sum(1 for f in sub if f.get("n_paginas") not in (2, -1))
        print(f"{ejemplar}: n={len(sub)}  aspecto_mediana={medianas.get(ejemplar, 0):.3f}  "
              f"outliers={n_out} ({100*n_out/len(sub) if sub else 0:.1f}%)  "
              f"errores_lectura={n_err}  paginas!=2={n_pag}")
    print(f"\nCSV -> {out_csv}  (revisa las filas outlier=1 y error!='' primero)")


# ---------------------------------------------------------------- muestra --

def _indexar(dir_ejemplar: Path):
    """clave (dep,muni,zona,puesto,mesa) normalizada -> Path del PDF."""
    idx = {}
    for pdf in listar_pdfs(dir_ejemplar):
        try:
            clave = tuple(x.lstrip("0") or "0" for x in P2V.parsear_clave(pdf))
        except ValueError:
            continue
        idx[clave] = pdf
    return idx


def muestra(n_total: int, out_dir: str, color_claveros: bool, seed: int):
    rng = random.Random(seed)
    print("Indexando los 3 ejemplares (recorrido único de cada árbol)...")
    indices = {e: _indexar(d) for e, d in EJEMPLARES.items() if d.exists()}
    for e, idx in indices.items():
        print(f"  {e}: {len(idx):,} mesas indexadas")

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

    salida = Path(out_dir); salida.mkdir(parents=True, exist_ok=True)
    manifest = (salida / "manifest_muestra.csv").open("w", newline="", encoding="utf-8")
    w = csv.writer(manifest)
    w.writerow(["dep", "muni", "zona", "puesto", "mesa", "ejemplar", "ruta_pdf", "ruta_montaje"])

    n_ok = n_err = 0
    for clave in seleccion:
        dep = clave[0]
        dep_dir = salida / f"dep_{dep}"
        dep_dir.mkdir(exist_ok=True)
        for ejemplar, idx in indices.items():
            pdf = idx[clave]
            nombre = f"{ejemplar}_{'_'.join(clave)}.png"
            destino = dep_dir / nombre
            usar_color = color_claveros and ejemplar == "CLAVEROS"
            try:
                P2V.probar(pdf, destino, color=usar_color)
                w.writerow([*clave, ejemplar, str(pdf), str(destino)])
                n_ok += 1
            except Exception as exc:
                w.writerow([*clave, ejemplar, str(pdf), f"ERROR: {exc}"])
                n_err += 1
    manifest.close()
    print(f"\nHecho. montajes ok={n_ok} err={n_err}. Revisar en {salida}/dep_*/ "
          f"y el manifiesto en {salida}/manifest_muestra.csv")


def main():
    ap = argparse.ArgumentParser(description="QA de segmentación 2V a escala")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("barrido")
    p.add_argument("--n", type=int, default=3000, help="muestra por ejemplar")
    p.add_argument("--out", default="barrido_2v.csv")
    p.add_argument("--seed", type=int, default=42)

    p = sub.add_parser("muestra")
    p.add_argument("--n", type=int, default=200, help="mesas totales (x3 ejemplares)")
    p.add_argument("--out", default="revision_muestra_2v")
    p.add_argument("--color-claveros", action="store_true",
                   help="genera el montaje de CLAVEROS en color (para revisar Fase 3)")
    p.add_argument("--seed", type=int, default=42)

    a = ap.parse_args()
    if a.cmd == "barrido":
        barrido(a.n, a.out, a.seed)
    elif a.cmd == "muestra":
        muestra(a.n, a.out, a.color_claveros, a.seed)


if __name__ == "__main__":
    main()
