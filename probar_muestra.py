#!/usr/bin/env python3
"""
Herramienta de prueba visual de la Fase 0 sobre una muestra de actas.

Para cada PDF de la muestra genera:
  • Una imagen "overlay" mostrando QUÉ detectó el extractor (cajas + casillas
    marcadas como con-voto/vacío), para inspección humana rápida.
  • Una tira con los recortes de las casillas que tienen voto.

Uso:
    # Tomar 20 PDFs al azar de la carpeta e14_pdfs
    python probar_muestra.py e14_pdfs --n 20 --salida revision

    # Probar PDFs concretos
    python probar_muestra.py ruta/a/acta1.pdf ruta/a/acta2.pdf --salida revision

    # Tomar muestra variada (un PDF por cada departamento)
    python probar_muestra.py e14_pdfs --por-carpeta --salida revision
"""

from __future__ import annotations
import sys, random, argparse
from pathlib import Path

import cv2
import numpy as np
import fitz

# Importar el extractor del mismo directorio
sys.path.insert(0, str(Path(__file__).resolve().parent))
import extractor as ex


def recolectar_pdfs(rutas: list[str], n: int, por_carpeta: bool) -> list[Path]:
    """Recolecta una lista de PDFs a partir de archivos o carpetas dadas."""
    pdfs: list[Path] = []
    carpetas = []
    for r in rutas:
        p = Path(r)
        if p.is_file() and p.suffix.lower() == ".pdf":
            pdfs.append(p)
        elif p.is_dir():
            carpetas.append(p)

    for carpeta in carpetas:
        todos = sorted(carpeta.rglob("*.pdf"))
        if not todos:
            continue
        if por_carpeta:
            # Un PDF por cada subcarpeta de primer nivel (p.ej. cada departamento)
            vistos = {}
            for f in todos:
                # clave = primera subcarpeta bajo la carpeta base
                try:
                    rel = f.relative_to(carpeta)
                    clave = rel.parts[0] if len(rel.parts) > 1 else "."
                except ValueError:
                    clave = "."
                if clave not in vistos:
                    vistos[clave] = f
            pdfs.extend(vistos.values())
        else:
            # Muestra aleatoria reproducible
            random.seed(42)
            pdfs.extend(random.sample(todos, min(n, len(todos))))

    # Si pasaron archivos sueltos + carpeta, respetar n como tope global solo
    # cuando venía de carpeta aleatoria
    return pdfs


def overlay_deteccion(pdf_path: Path, salida_dir: Path) -> dict:
    """
    Genera una imagen mostrando lo que el extractor detectó sobre el acta.
    Devuelve un resumen para el reporte.
    """
    doc = fitz.open(pdf_path)
    res = ex.procesar_acta(str(pdf_path), guardar=False)

    # Indexar casillas por página
    por_pagina: dict[int, list] = {}
    for c in res.casillas:
        por_pagina.setdefault(c.pagina, []).append(c)

    paneles = []
    for pidx in range(min(3, len(doc))):
        img = ex.render_pagina(doc[pidx])
        img = ex.corregir_inclinacion(img)
        vis = img.copy()

        for c in por_pagina.get(pidx + 1, []):
            x, y, w, h = c.bbox
            if c.etiqueta == "CONSTANCIAS":
                tiene = c.tinta_pct > 0.3
                color = (200, 120, 0) if tiene else (0, 0, 220)  # azul / rojo
                cv2.rectangle(vis, (x, y), (x + w, y + h), color, 5)
                cv2.putText(vis, f"CONSTANCIAS {'con texto' if tiene else 'vacio'}",
                            (x + 20, y + 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
            elif c.etiqueta in ("BLANCO", "NULO", "NO_MARCADO", "SUMA_TOTAL"):
                tiene = c.tinta_pct > 1.0
                color = (180, 0, 180) if tiene else (0, 0, 220)  # magenta / rojo
                cv2.rectangle(vis, (x, y), (x + w, y + h), color, 4)
                cv2.putText(vis, f"{c.etiqueta} {c.tinta_pct:.1f}%",
                            (x + 8, y + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            elif c.etiqueta in ("TOTAL_E11", "TOTAL_URNA", "TOTAL_INCINERADOS"):
                tiene = c.tinta_pct > 1.0
                color = (200, 130, 0) if tiene else (0, 0, 220)  # naranja / rojo
                cv2.rectangle(vis, (x, y), (x + w, y + h), color, 4)
                cv2.putText(vis, f"{c.etiqueta} {c.tinta_pct:.1f}%",
                            (x + 8, y + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            else:
                tiene_voto = c.tinta_pct > 1.0
                color = (0, 160, 0) if tiene_voto else (0, 0, 220)  # verde / rojo
                cv2.rectangle(vis, (x, y), (x + w, y + h), color, 4)
                etiqueta = f"{c.etiqueta} {'VOTO' if tiene_voto else 'vacio'} {c.tinta_pct:.1f}%"
                cv2.putText(vis, etiqueta, (x + 8, y + 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

        escala = 900 / vis.shape[0]
        vis = cv2.resize(vis, (int(vis.shape[1] * escala), 900))
        paneles.append(vis)

    if paneles:
        # Igualar alturas y concatenar páginas lado a lado
        comp = cv2.hconcat(paneles)
        nombre = pdf_path.stem[:24]
        out = salida_dir / f"overlay_{nombre}.png"
        cv2.imwrite(str(out), comp)

    n_cand = sum(1 for c in res.casillas if c.etiqueta.startswith("cand_"))
    n_const = sum(1 for c in res.casillas if c.etiqueta == "CONSTANCIAS")
    n_voto = sum(1 for c in res.casillas
                 if c.etiqueta.startswith("cand_") and c.tinta_pct > 1.0)
    return {
        "pdf": str(pdf_path),
        "ok": res.ok,
        "casillas": len(res.casillas),
        "candidatos": n_cand,
        "constancias": n_const,
        "con_voto": n_voto,
        "aviso": res.aviso,
    }


def main():
    ap = argparse.ArgumentParser(description="Prueba visual de la Fase 0 sobre una muestra")
    ap.add_argument("rutas", nargs="+", help="PDFs o carpeta (p.ej. e14_pdfs)")
    ap.add_argument("--n", type=int, default=15, help="Tamaño de muestra aleatoria")
    ap.add_argument("--por-carpeta", action="store_true",
                    help="Un PDF por subcarpeta (muestra variada por departamento)")
    ap.add_argument("--salida", default="revision_fase0", help="Carpeta de salida")
    a = ap.parse_args()

    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)

    pdfs = recolectar_pdfs(a.rutas, a.n, a.por_carpeta)
    if not pdfs:
        print("No se encontraron PDFs. Revisa la ruta.")
        sys.exit(1)

    print(f"Probando {len(pdfs)} actas. Las imágenes de revisión van a: {salida.resolve()}\n")
    print(f"{'ESTADO':8s} {'CAND':5s} {'CONST':6s} {'C/VOTO':7s}  ARCHIVO")
    print("-" * 72)

    resumen = []
    for p in pdfs:
        try:
            r = overlay_deteccion(p, salida)
        except Exception as e:
            r = {"pdf": str(p), "ok": False, "casillas": 0, "candidatos": 0,
                 "constancias": 0, "con_voto": 0, "aviso": f"EXCEPCIÓN: {e}"}
        resumen.append(r)
        # OK = 13 candidatos detectados + 1 recuadro de constancias
        ok = r.get("candidatos") == 13 and r.get("constancias") == 1
        estado = "OK" if ok else "REVISAR"
        nombre = Path(r["pdf"]).name[:36]
        print(f"{estado:8s} {r.get('candidatos',0):>4d} {r.get('constancias',0):>5d} "
              f"{r.get('con_voto',0):>6d}   {nombre}"
              + (f"  ⚠ {r['aviso']}" if r["aviso"] else ""))

    n_ok = sum(1 for r in resumen
               if r.get("candidatos") == 13 and r.get("constancias") == 1)
    n_rev = len(resumen) - n_ok
    print("-" * 72)
    print(f"Total: {len(resumen)}  |  OK (13 cand + constancias): {n_ok}  |  A revisar: {n_rev}")
    print(f"\nAbre las imágenes 'overlay_*.png' en {salida} para verificar visualmente.")
    print("Verde = casilla con voto   |   Rojo = vacía   |   Azul = constancias con texto")

    import json
    (salida / "_resumen.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
