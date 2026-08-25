#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reintento DIRIGIDO de los PDF que `e14.validacion.integridad_pdfs` marcó como
FALTANTES o CORRUPTOS, para DELEGADOS o TRANSMISIÓN (una corrida por
ejemplar). Reutiliza tal cual el motor de descarga de
`e14.descarga.descargar_e14_2vlta` (mismo `Record`, misma `download_one` con
sus reintentos/backoff, mismo manifest/errors jsonl) en vez de duplicarlo:
solo le da una lista curada de registros en lugar del `allTransmissionCodes.json`
completo.

No aplica a CLAVEROS: ese portal (escrutinios) no expone las actas por
id_transmission_code/URL directa como el visor, y el hueco del departamento
88 (CONSULADOS/exterior) ya se confirmó que es del ORIGEN (el index.json de
escrutinios nunca publicó esos puestos), no algo recuperable reintentando.

--overwrite es forzoso: la marca "ya existe" del descargador original solo
mira los primeros 5 bytes, así que un PDF truncado (sin %%EOF, el caso de
los CORRUPTOS) pasaría de largo si no se fuerza la re-descarga.

Uso (una corrida por ejemplar):
    python -m e14.validacion.reintentar_faltantes \
        --ejemplar delegados \
        --base-url https://e14segundavueltapresidente.registraduria.gov.co \
        --out data/segunda_vuelta/e14_pdfs_2v \
        --faltantes data/segunda_vuelta/_integridad/reporte_integridad_2v.faltantes.csv \
        --corruptos data/segunda_vuelta/_integridad/reporte_integridad_2v.corruptos.csv

    python -m e14.validacion.reintentar_faltantes \
        --ejemplar transmision \
        --base-url https://e14segundavueltapresidentet.registraduria.gov.co \
        --out data/segunda_vuelta/e14_pdfs_2v_t \
        --faltantes data/segunda_vuelta/_integridad/reporte_integridad_2v.faltantes.csv \
        --corruptos data/segunda_vuelta/_integridad/reporte_integridad_2v.corruptos.csv

Después de reintentar, vuelve a correr `integridad_pdfs` para confirmar qué
quedó resuelto y qué sigue fallando (probablemente porque la mesa fue
renumerada/retirada en el visor entre corridas -> ya no está bajo esa ruta).
"""
from __future__ import annotations
import argparse, csv
from pathlib import Path

from e14.comunes import parsear_ruta
from e14.descarga.descargar_e14_2vlta import Record, dedupe_records, run_download


def leer_objetivos(ejemplar: str, *csv_paths: str) -> list[Record]:
    """Junta faltantes.csv + corruptos.csv, filtra por ejemplar, parsea cada
    ruta con parsear_ruta (misma convención dep/muni/zona/puesto/mesa/archivo
    que usa el resto del proyecto) y arma los Record que espera el motor de
    descarga original."""
    rutas = set()
    for p in csv_paths:
        if not p or not Path(p).exists():
            continue
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("ejemplar") == ejemplar:
                    rutas.add(r["path"])

    records = []
    for ruta in sorted(rutas):
        d = parsear_ruta(ruta)
        if not d["dep"]:
            print(f"  (ruta sin patrón dep/muni/zona/puesto/mesa reconocible, se omite: {ruta})")
            continue
        records.append(Record(
            id_transmission_code="", number_table=d["mesa"], expected_name=d["archivo"],
            transmission_status="", corporation_code="001", department_code=d["dep"],
            municipality_code=d["muni"], zone_code=d["zona"], stand_code=d["puesto"], id_stand=""))
    return dedupe_records(records)


def main():
    ap = argparse.ArgumentParser(description="Reintenta descargar los PDF marcados como faltantes/corruptos por integridad_pdfs (solo DELEGADOS/TRANSMISIÓN)")
    ap.add_argument("--ejemplar", required=True, choices=["delegados", "transmision"])
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--out", required=True, help="misma carpeta que ya tiene los PDF de este ejemplar")
    ap.add_argument("--faltantes", default="", help="*.faltantes.csv de integridad_pdfs")
    ap.add_argument("--corruptos", default="", help="*.corruptos.csv de integridad_pdfs")
    ap.add_argument("--corporation-folder", default="PRE")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--queue-multiplier", type=int, default=4)
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--sleep-min", type=float, default=0.15)
    ap.add_argument("--sleep-max", type=float, default=0.50)
    ap.add_argument("--backoff-base", type=float, default=1.5)
    ap.add_argument("--max-backoff", type=float, default=60.0)
    ap.add_argument("--connect-timeout", type=float, default=15.0)
    ap.add_argument("--read-timeout", type=float, default=120.0)
    ap.add_argument("--chunk-size", type=int, default=128 * 1024)
    ap.add_argument("--min-bytes", type=int, default=800)
    ap.add_argument("--manifest", default="", help="jsonl de esta corrida (default: <out>/_logs/manifest_<stamp>.jsonl)")
    ap.add_argument("--errors", default="")
    ap.add_argument("--progress-every", type=int, default=20)
    ap.add_argument("--flush-every", type=int, default=5)
    ap.add_argument("--user-agent", default="Mozilla/5.0 (compatible; E14Reintento/1.0)")
    a = ap.parse_args()
    a.overwrite = True   # forzoso: ver nota sobre is_valid_pdf en el docstring

    records = leer_objetivos(a.ejemplar, a.faltantes, a.corruptos)
    print(f"[{a.ejemplar}] {len(records):,} PDF a reintentar")
    if not records:
        return

    run_download(a, records, {})


if __name__ == "__main__":
    main()
