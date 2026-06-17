#!/usr/bin/env python3
"""
Revisión visual del bloque de agregados (pág. 2).

Genera overlays mostrando dónde caen los recuadros de los 4 agregados con la
lógica de anclaje al candidato 13. Útil para confirmar que el recorte cae bien
incluso en actas con el bloque desplazado.

Uso:
    # Desde el CSV (las que usaron anclaje/plantilla)
    python revisar_plantilla.py resultados/casillas_e14.csv --n 25 --salida rev

    # Sobre PDFs concretos (para revisar un caso puntual)
    python revisar_plantilla.py --pdfs ruta/acta1.pdf ruta/acta2.pdf --salida rev
"""
from __future__ import annotations
import sys, csv, random, argparse
from pathlib import Path
import cv2, fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extractor as ex


def overlay_agregados(pdf_path: str, salida: Path) -> dict:
    doc = fitz.open(pdf_path)
    if len(doc) < 2:
        return {"pdf": pdf_path, "ok": False, "motivo": "menos de 2 páginas"}
    img = ex.render_pagina(doc[1]); img = ex.corregir_inclinacion(img)
    h, w = img.shape[:2]

    cajas = ex.detectar_cajas_candidato(img); cajas.sort(key=lambda b: b[1])
    aggs, origen = ex.agregados_por_celdas(img, cajas)

    y0 = int(h * 0.70); zona = img[y0:int(h*0.93), :].copy()
    info = {"origen": origen}
    for etiqueta, (x, y, bw, bh) in aggs:
        ry = y - y0
        crop = img[y:y+bh, x:x+bw]
        t = ex.tinta_pct(crop)
        info[etiqueta] = round(t, 1)
        color = (0,160,0) if t > 1.0 else (0,0,220)
        cv2.rectangle(zona, (x, ry), (x+bw, ry+bh), color, 4)
        cv2.putText(zona, f"{etiqueta} {t:.1f}%", (x+8, ry+30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    zona = cv2.resize(zona, (1000, int(1000*zona.shape[0]/zona.shape[1])))
    nombre = Path(pdf_path).stem[:20]
    cv2.imwrite(str(salida / f"agg_{nombre}.png"), zona)
    return {"pdf": pdf_path, "ok": True, **info}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", help="CSV de procesar_lote.py")
    ap.add_argument("--pdfs", nargs="*", default=[], help="PDFs concretos a revisar")
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--salida", default="rev_plantilla")
    ap.add_argument("--base", default="")
    a = ap.parse_args()

    salida = Path(a.salida); salida.mkdir(parents=True, exist_ok=True)

    pdfs = list(a.pdfs)
    if a.csv and not pdfs:
        con_plantilla = []
        with open(a.csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                # las que NO usaron líneas (anclaje o plantilla) o tienen aviso
                if row.get("uso_plantilla") == "1" or "anclaje" in row.get("aviso","") \
                   or "plantilla" in row.get("aviso",""):
                    con_plantilla.append(row["pdf"])
        print(f"Actas con anclaje/plantilla: {len(con_plantilla):,}")
        random.seed(42)
        pdfs = random.sample(con_plantilla, min(a.n, len(con_plantilla))) if con_plantilla else []

    if not pdfs:
        print("Nada que revisar."); return

    print(f"Generando overlays de {len(pdfs)} actas en {salida.resolve()}\n")
    print(f"{'ORIGEN':10} {'BLANCO':>7} {'NULO':>6} {'NO_M':>6} {'SUMA':>6}   ARCHIVO")
    print("-"*72)
    sospechosas = []
    for pdf in pdfs:
        ruta = (a.base + pdf) if a.base else pdf
        if not Path(ruta).exists():
            print(f"  (no encontrado) {ruta}"); continue
        r = overlay_agregados(ruta, salida)
        if not r.get("ok"):
            print(f"  ⚠ {r.get('motivo')}"); continue
        s = r.get("SUMA_TOTAL",0)
        alerta = " ⚠SUMA vacía" if s < 1.0 else ""
        if alerta: sospechosas.append(pdf)
        print(f"  {r['origen']:10} {r.get('BLANCO',0):>6.1f} {r.get('NULO',0):>6.1f} "
              f"{r.get('NO_MARCADO',0):>6.1f} {s:>6.1f}   {Path(pdf).name[:24]}{alerta}")
    print("-"*72)
    print(f"\nRevisa 'agg_*.png' en {salida}. Verde=número, Rojo=vacía.")
    print("Comprueba que cada recuadro cae sobre su fila correcta.")
    if sospechosas:
        print(f"\n⚠ {len(sospechosas)} con SUMA vacía (pueden ser reales o mal recorte).")


if __name__ == "__main__":
    main()
