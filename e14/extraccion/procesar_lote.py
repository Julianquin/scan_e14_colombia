#!/usr/bin/env python3
"""
Procesador masivo de actas E-14 — Fase 0 a escala.

Recorre recursivamente la carpeta de PDFs (e14_pdfs), ejecuta el extractor
sobre cada acta usando todos los núcleos de CPU, y vuelca los metadatos de
las casillas a un CSV consolidado. Reanudable: si se interrumpe, al relanzar
omite las actas ya procesadas.

NO guarda los recortes PNG por defecto (serían ~2M de archivos). Solo guarda
metadatos: por cada acta, los 18 valores de tinta y los bbox, más el código
de ubicación deducido de la ruta del archivo.

Uso:
    python procesar_lote.py e14_pdfs --salida resultados
    python procesar_lote.py e14_pdfs --salida resultados --workers 8
    python procesar_lote.py e14_pdfs --salida resultados --limite 1000   # prueba
"""

from __future__ import annotations
import os, sys, csv, json, time, argparse, signal
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extractor as ex
from comunes import CAND, CASILLAS_NUMERICAS, parsear_ruta

# Orden fijo de las 21 columnas de voto (20 numéricas + CONSTANCIAS).
COLUMNAS_VOTO = CASILLAS_NUMERICAS + ["CONSTANCIAS"]


def calcular_banderas(tinta: dict) -> dict:
    """
    Calcula banderas de consistencia a partir del patrón de casillas con/sin
    número (sin OCR). NINGUNA bandera significa "fraude": son señales de que
    el acta merece revisión humana. La interpretación llega con el OCR y el
    cruce con el E-11 y las constancias.

    `tinta` es el dict {etiqueta: tinta_pct}.
    """
    def tiene(et, umbral=1.0):
        v = tinta.get(et)
        return (v is not None) and (v > umbral)

    n_cand_con_voto = sum(1 for c in CAND if tiene(c))
    suma_llena   = tiene("SUMA_TOTAL")
    blanco       = tiene("BLANCO")
    nulo         = tiene("NULO")
    no_marcado   = tiene("NO_MARCADO")
    constancias  = tiene("CONSTANCIAS", umbral=0.3)
    algun_agregado = blanco or nulo or no_marcado
    e11_lleno    = tiene("TOTAL_E11")

    banderas = {
        # ALTA prioridad
        "suma_vacia_con_votos":  int((not suma_llena) and n_cand_con_voto > 0),
        "sin_ningun_voto":       int(n_cand_con_voto == 0 and not algun_agregado),
        "suma_con_todo_vacio":   int(suma_llena and n_cand_con_voto == 0 and not algun_agregado),
        # MEDIA prioridad
        "todos_candidatos_llenos": int(n_cand_con_voto == 13),
        "agregados_sin_suma":    int(algun_agregado and not suma_llena),
        "e11_vacio_con_votos":   int((not e11_lleno) and n_cand_con_voto > 0),
        # INFO (contexto)
        "tiene_constancias":     int(constancias),
        "n_cand_con_voto":       n_cand_con_voto,
    }

    # Nivel de prioridad de revisión (el más alto que aplique)
    if banderas["suma_vacia_con_votos"] or banderas["sin_ningun_voto"] or banderas["suma_con_todo_vacio"]:
        banderas["prioridad_revision"] = "ALTA"
    elif (banderas["todos_candidatos_llenos"] or banderas["agregados_sin_suma"]
          or banderas["e11_vacio_con_votos"]):
        banderas["prioridad_revision"] = "MEDIA"
    else:
        banderas["prioridad_revision"] = "OK"

    return banderas


def procesar_uno(pdf_path: str) -> dict:
    """
    Procesa un acta y devuelve un dict plano listo para CSV.
    Pensado para ejecutarse en un proceso worker independiente.
    """
    try:
        res = ex.procesar_acta(pdf_path, guardar=False)
        ubic = parsear_ruta(pdf_path)

        # Indexar tinta por etiqueta
        tinta = {c.etiqueta: c.tinta_pct for c in res.casillas}

        fila = {
            "pdf": pdf_path,
            **ubic,
            "ok": int(res.ok),
            "n_casillas": len(res.casillas),
            "uso_plantilla": int("plantilla" in res.aviso),
            "aviso": res.aviso,
        }
        # Añadir el % de tinta de cada una de las 18 casillas
        for col in COLUMNAS_VOTO:
            fila[f"tinta_{col}"] = tinta.get(col, "")
            # marca binaria: ¿tiene número escrito?
            v = tinta.get(col)
            if col == "CONSTANCIAS":
                fila[f"tiene_{col}"] = int(v > 0.3) if v is not None else ""
            else:
                fila[f"tiene_{col}"] = int(v > 1.0) if v is not None else ""

        # Banderas de consistencia (sin OCR)
        fila.update(calcular_banderas(tinta))
        return fila
    except Exception as e:
        ubic = parsear_ruta(pdf_path)
        return {"pdf": pdf_path, **ubic, "ok": 0, "n_casillas": 0,
                "uso_plantilla": "", "aviso": f"EXCEPCIÓN: {str(e)[:100]}"}


def cargar_procesados(csv_path: Path) -> set:
    """Lee el CSV existente y devuelve el conjunto de PDFs ya procesados."""
    hechos = set()
    if csv_path.exists():
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("pdf"):
                    hechos.add(row["pdf"])
    return hechos


def cabecera_csv() -> list:
    base = ["pdf", "dep", "muni", "zona", "puesto", "mesa", "archivo",
            "ok", "n_casillas", "uso_plantilla", "aviso"]
    for col in COLUMNAS_VOTO:
        base.append(f"tinta_{col}")
        base.append(f"tiene_{col}")
    # Banderas de consistencia
    base += ["n_cand_con_voto", "suma_vacia_con_votos", "sin_ningun_voto",
             "suma_con_todo_vacio", "todos_candidatos_llenos",
             "agregados_sin_suma", "e11_vacio_con_votos", "tiene_constancias",
             "prioridad_revision"]
    return base


def main():
    ap = argparse.ArgumentParser(description="Procesador masivo Fase 0 — actas E-14")
    ap.add_argument("carpeta", help="Carpeta raíz de PDFs (ej: e14_pdfs)")
    ap.add_argument("--salida", default="resultados", help="Carpeta de salida")
    ap.add_argument("--workers", type=int, default=os.cpu_count(),
                    help="Procesos en paralelo (def: todos los núcleos)")
    ap.add_argument("--limite", type=int, default=None,
                    help="Procesar solo N actas (para pruebas)")
    ap.add_argument("--flush-cada", type=int, default=200,
                    help="Guardar en disco cada N actas")
    a = ap.parse_args()

    carpeta = Path(a.carpeta)
    if not carpeta.is_dir():
        print(f"No existe la carpeta {carpeta}"); sys.exit(1)

    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    csv_path = salida / "casillas_e14.csv"

    print("Buscando PDFs...", flush=True)
    todos = sorted(str(p) for p in carpeta.rglob("*.pdf"))
    print(f"  {len(todos):,} PDFs encontrados", flush=True)

    # Reanudación: omitir los ya procesados
    hechos = cargar_procesados(csv_path)
    if hechos:
        print(f"  {len(hechos):,} ya procesados (se omiten)", flush=True)
    pendientes = [p for p in todos if p not in hechos]
    if a.limite:
        pendientes = pendientes[:a.limite]
    print(f"  {len(pendientes):,} pendientes en esta corrida", flush=True)
    if not pendientes:
        print("Nada que procesar."); return

    nuevo = not csv_path.exists()
    f_csv = open(csv_path, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_csv, fieldnames=cabecera_csv(), extrasaction="ignore")
    if nuevo:
        writer.writeheader()

    t0 = time.time()
    hechos_n = 0
    fallos_n = 0
    plantilla_n = 0
    conteo_banderas = {
        "ALTA": 0, "MEDIA": 0,
        "suma_vacia_con_votos": 0, "sin_ningun_voto": 0,
        "suma_con_todo_vacio": 0, "todos_candidatos_llenos": 0,
        "agregados_sin_suma": 0, "tiene_constancias": 0,
    }

    print(f"\nProcesando con {a.workers} procesos...\n", flush=True)
    try:
        with ProcessPoolExecutor(max_workers=a.workers) as ex_pool:
            futuros = {ex_pool.submit(procesar_uno, p): p for p in pendientes}
            for fut in as_completed(futuros):
                fila = fut.result()
                writer.writerow(fila)
                hechos_n += 1
                if not fila.get("ok"):
                    fallos_n += 1
                if fila.get("uso_plantilla") == 1:
                    plantilla_n += 1
                # Contar banderas
                pr = fila.get("prioridad_revision")
                if pr in ("ALTA", "MEDIA"):
                    conteo_banderas[pr] += 1
                for b in ("suma_vacia_con_votos", "sin_ningun_voto",
                          "suma_con_todo_vacio", "todos_candidatos_llenos",
                          "agregados_sin_suma", "tiene_constancias"):
                    if fila.get(b) == 1:
                        conteo_banderas[b] += 1

                if hechos_n % a.flush_cada == 0:
                    f_csv.flush()
                    dt = time.time() - t0
                    rate = hechos_n / dt
                    eta = (len(pendientes) - hechos_n) / rate if rate else 0
                    print(f"  {hechos_n:,}/{len(pendientes):,} | "
                          f"{rate:.1f} actas/s | "
                          f"fallos={fallos_n} plantilla={plantilla_n} | "
                          f"revision[A={conteo_banderas['ALTA']} "
                          f"M={conteo_banderas['MEDIA']}] | "
                          f"ETA {eta/60:.0f} min", flush=True)
    except KeyboardInterrupt:
        print("\n⚠ Interrumpido. El progreso está guardado; relanza para continuar.")
    finally:
        f_csv.close()

    dt = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Procesadas en esta corrida: {hechos_n:,}")
    print(f"  Fallos: {fallos_n}  |  Usaron plantilla: {plantilla_n}")
    print(f"  Tiempo: {dt/60:.1f} min  ({hechos_n/max(dt,1):.1f} actas/s)")
    print(f"\n  BANDERAS DE CONSISTENCIA (para revisión, NO son fraude):")
    print(f"    Prioridad ALTA:  {conteo_banderas['ALTA']:,}")
    print(f"    Prioridad MEDIA: {conteo_banderas['MEDIA']:,}")
    print(f"    · suma vacía con votos:    {conteo_banderas['suma_vacia_con_votos']:,}")
    print(f"    · sin ningún voto:         {conteo_banderas['sin_ningun_voto']:,}")
    print(f"    · suma con todo vacío:     {conteo_banderas['suma_con_todo_vacio']:,}")
    print(f"    · todos candidatos llenos: {conteo_banderas['todos_candidatos_llenos']:,}")
    print(f"    · agregados sin suma:      {conteo_banderas['agregados_sin_suma']:,}")
    print(f"    · con constancias escritas:{conteo_banderas['tiene_constancias']:,}")
    print(f"\n  CSV: {csv_path.resolve()}")
    print(f"{'='*60}")

    # Reporte resumen
    resumen = {
        "procesadas_corrida": hechos_n,
        "fallos": fallos_n,
        "usaron_plantilla": plantilla_n,
        "segundos": round(dt, 1),
        "banderas": conteo_banderas,
    }
    (salida / "_resumen_lote.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
