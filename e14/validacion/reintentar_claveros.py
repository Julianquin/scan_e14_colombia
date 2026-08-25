#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reintento DIRIGIDO de los PDF de CLAVEROS que `e14.validacion.integridad_pdfs`
marcó como CORRUPTOS (truncados, sin %%EOF). NO reintenta faltantes: el
propio `claveros_mesas.csv` ya confirmó cobertura completa (0 faltantes);
lo único roto son estos truncados puntuales.

A diferencia de `descargar_claveros.py pdfs`, este script SIEMPRE
re-descarga cada ruta que se le pasa. El comando original decide "ya existe"
mirando solo tamaño + primeros 5 bytes (`_es_pdf_valido`), así que un
truncado con cabecera válida se lo salta sin arreglarlo, y además no tiene
--overwrite.

No toca el departamento 88 (CONSULADOS/exterior): ese hueco es del origen
(el index.json de escrutinios nunca publicó esos puestos) y no aparece en
corruptos.csv, así que no hay nada que este script pueda hacer con él.

Uso:
    python -m e14.validacion.reintentar_claveros \
        --corruptos data/segunda_vuelta/_integridad/reporte_integridad_2v.corruptos.csv

Después, volvé a correr integridad_pdfs para confirmar que corruptos/con
problema en [claveros] bajó a 0 (o para ver cuáles siguen fallando en el
origen, no en la copia local).
"""
from __future__ import annotations
import argparse, csv, os, random, time
from pathlib import Path

import requests

BASE_URL = "https://escrutinios2vueltapresidente2026.registraduria.gov.co"
RAIZ_MARCA = "e14_pdfs_claveros/"     # todo lo que sigue a esto es la ruta relativa que también usa la URL


def leer_objetivos(corruptos_csv: str) -> list[tuple[str, Path]]:
    """(ruta_relativa_para_la_url, ruta_local) por cada fila ejemplar=claveros."""
    objetivos = []
    with open(corruptos_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("ejemplar") != "claveros":
                continue
            path = r["path"]
            i = path.find(RAIZ_MARCA)
            if i < 0:
                print(f"  (ruta sin '{RAIZ_MARCA}', se omite: {path})")
                continue
            rel = path[i + len(RAIZ_MARCA):]          # docs/E14/dep/muni/zona/puesto/archivo.pdf
            objetivos.append((rel, Path(path)))
    return objetivos


def descargar_uno(session, base_url, rel, local, retries, timeout, min_bytes):
    url = base_url.rstrip("/") + "/" + rel.lstrip("/")
    ultimo_error = ""
    for intento in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code != 200:
                ultimo_error = f"http_{r.status_code}"
            elif not r.content[:5].startswith(b"%PDF"):
                ultimo_error = "no_es_pdf"
            elif len(r.content) < min_bytes:
                ultimo_error = f"muy_chico:{len(r.content)}"
            elif b"%%EOF" not in r.content[-2048:]:
                ultimo_error = "sigue_sin_eof"          # el origen mismo lo sirve truncado
            else:
                local.parent.mkdir(parents=True, exist_ok=True)
                tmp = local.with_suffix(local.suffix + f".part{os.getpid()}")
                tmp.write_bytes(r.content)
                os.replace(tmp, local)
                return "ok", ""
        except Exception as exc:
            ultimo_error = repr(exc)
        if intento < retries:
            time.sleep(min(30.0, 1.5 * (2 ** (intento - 1))) + random.uniform(0, 1.0))
    return "error", ultimo_error


def main():
    ap = argparse.ArgumentParser(description="Reintenta los PDF de CLAVEROS marcados como corruptos (truncados) por integridad_pdfs")
    ap.add_argument("--corruptos", required=True, help="*.corruptos.csv de integridad_pdfs")
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--min-bytes", type=int, default=800)
    ap.add_argument("--user-agent", default="Mozilla/5.0 (compatible; E14ClaverosReintento/1.0)")
    a = ap.parse_args()

    objetivos = leer_objetivos(a.corruptos)
    print(f"[claveros] {len(objetivos):,} PDF a reintentar")
    if not objetivos:
        return

    session = requests.Session()
    session.headers.update({"User-Agent": a.user_agent, "Accept": "*/*",
                             "Referer": a.base_url.rstrip("/") + "/", "Cache-Control": "no-cache"})

    ok = err = 0
    for i, (rel, local) in enumerate(objetivos, 1):
        estado, motivo = descargar_uno(session, a.base_url, rel, local, a.retries, a.timeout, a.min_bytes)
        if estado == "ok":
            ok += 1
        else:
            err += 1
            print(f"  [{i}/{len(objetivos)}] SIGUE FALLANDO {local}  ->  {motivo}")
        print(f"{i}/{len(objetivos)} | ok={ok} error={err}")

    print(f"\nHecho. ok={ok} error={err}.")
    if err:
        print("Los que sigan en error puede que el origen mismo los tenga truncados -> no recuperable reintentando.")


if __name__ == "__main__":
    main()
