#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reporte de auditoría — consolida la serie de snapshots del monitor en un informe
por mesa, defendible y no acusatorio.

Reconstruye, recorriendo TODOS los snapshots en orden:
  - cuándo apareció cada mesa por primera vez,
  - cada cambio de hash del PDF (antes/después, timestamp, estado en ese momento),
  - cambios de estado (y retrocesos),
  - eliminaciones.
Añade el veredicto de integridad de la cadena y la TASA BASE (qué % de mesas
cambia de hash en condiciones normales), para que una alerta aislada tenga contexto.

Opcionalmente cruza el cuadre aritmético (CSV de `decodificar`) por mesa.

Salidas: reporte_auditoria.csv (una fila por mesa con eventos) y reporte_auditoria.md.

NO pronuncia fraude. Un cambio de hash puede ser un re-escaneo legítimo; lo
relevante son los cambios TARDÍOS (mucho después de aparecer) o POSTERIORES a
consolidación, las eliminaciones y los retrocesos de estado.

Uso:
    python reporte_auditoria.py --out codes_snapshots
    python reporte_auditoria.py --out codes_snapshots --decodificadas actas_decodificadas.csv --umbral-tardio 6
"""
from __future__ import annotations
import argparse, csv, json
from datetime import datetime
from pathlib import Path
import monitor_codes_json as M


def _ts(nombre: str) -> datetime:
    # allTransmissionCodes_YYYYmmdd_HHMMSS.json.gz
    s = nombre.replace("allTransmissionCodes_", "").split(".")[0]
    return datetime.strptime(s, "%Y%m%d_%H%M%S")


def extraer(data):
    """clave -> {name, status, dep, muni, zona, puesto, mesa}."""
    out = {}
    raiz = data.get("data", data) if isinstance(data, dict) else data
    for nd in M._walk(raiz):
        en = str(nd.get("expectedName", "")).strip()
        if not en:
            continue
        loc = tuple(str(nd.get(k, "")).strip() for k in
                    ("idDepartmentCode", "municipalityCode", "idZoneCode", "standCode", "numberStand"))
        idt = str(nd.get("idTransmissionCode", "")).strip()
        clave = idt or "|".join(loc)
        out[clave] = {"name": en, "status": str(nd.get("idTransmissionCodeStatus", "")).strip(),
                      "dep": loc[0], "muni": loc[1], "zona": loc[2], "puesto": loc[3], "mesa": loc[4]}
    return out


def verificar_cadena(out: Path):
    cad = out / "_cadena.jsonl"
    if not cad.exists():
        return None
    ent = [json.loads(l) for l in cad.read_text(encoding="utf-8").splitlines() if l.strip()]
    prev, ok = "GENESIS", True
    for e in ent:
        if e.get("eslabon_anterior") != prev:
            ok = False
        if M.sha256_bytes((prev + e["sha_contenido"] + e["ts"]).encode()) != e.get("eslabon"):
            ok = False
        snap = e.get("snapshot")
        if snap and (out / snap).exists():
            if M.sha256_bytes(M._leer_snapshot(out / snap)) != e["sha_contenido"]:
                ok = False
        prev = e.get("eslabon", prev)
    return {"ok": ok, "n": len(ent),
            "desde": ent[0]["ts"] if ent else "", "hasta": ent[-1]["ts"] if ent else ""}


def construir_historia(snaps):
    historia = {}
    prev = None
    for snap in snaps:
        ts = _ts(snap.name)
        cur = extraer(json.loads(M._leer_snapshot(snap)))
        if prev is None:
            for k, m in cur.items():
                historia[k] = _nuevo(m, ts)
        else:
            sp, sc = set(prev), set(cur)
            for k in sc - sp:
                historia[k] = _nuevo(cur[k], ts)
            for k in sp - sc:
                if k in historia:
                    historia[k]["eliminada_ts"] = ts.strftime("%Y-%m-%d %H:%M:%S")
            for k in sc & sp:
                h = historia[k]
                if prev[k]["name"] != cur[k]["name"]:
                    h["hash_changes"].append((ts, prev[k]["name"], cur[k]["name"], cur[k]["status"]))
                if prev[k]["status"] != cur[k]["status"]:
                    h["status_changes"].append((ts, prev[k]["status"], cur[k]["status"]))
                h["name"], h["status"] = cur[k]["name"], cur[k]["status"]
                for c in ("dep", "muni", "zona", "puesto", "mesa"):
                    h[c] = cur[k][c]
        prev = cur
    return historia


def _nuevo(m, ts):
    return {"dep": m["dep"], "muni": m["muni"], "zona": m["zona"], "puesto": m["puesto"], "mesa": m["mesa"],
            "first_seen": ts, "name": m["name"], "status": m["status"],
            "hash_changes": [], "status_changes": [], "eliminada_ts": ""}


def cargar_cuadre(path):
    if not path or not Path(path).exists():
        return {}
    d = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        k = (r.get("dep", ""), r.get("muni", ""), r.get("zona", ""), r.get("puesto", ""), r.get("mesa", ""))
        d[k] = r.get("estado", "")
    return d


def main():
    ap = argparse.ArgumentParser(description="Reporte de auditoría de actas E-14")
    ap.add_argument("--out", default="codes_snapshots", help="carpeta de snapshots")
    ap.add_argument("--salida", default="reporte_auditoria")
    ap.add_argument("--decodificadas", default=None, help="CSV de 'decodificar' (cuadre por mesa)")
    ap.add_argument("--umbral-tardio", type=float, default=6.0,
                    help="horas tras aparecer a partir de las cuales un cambio de hash es 'tardío'")
    a = ap.parse_args()
    out = Path(a.out)

    snaps = sorted(out.glob("allTransmissionCodes_*.json.gz"))
    if len(snaps) < 2:
        print("Hacen falta al menos 2 snapshots."); return
    print(f"Procesando {len(snaps)} snapshots ({_ts(snaps[0].name)} -> {_ts(snaps[-1].name)})...")

    integridad = verificar_cadena(out)
    historia = construir_historia(snaps)
    cuadre = cargar_cuadre(a.decodificadas)

    total = len(historia)
    con_hash, tardios, eliminadas, retrocesos, filas = 0, 0, 0, 0, []
    for k, h in historia.items():
        if not h["hash_changes"] and not h["eliminada_ts"]:
            continue
        nch = len(h["hash_changes"])
        tardio = any((ts - h["first_seen"]).total_seconds() / 3600.0 >= a.umbral_tardio
                     for ts, *_ in h["hash_changes"])
        # retroceso de estado: el estado numérico baja
        retro = any(sb.isdigit() and sa.isdigit() and int(sa) < int(sb)
                    for _, sb, sa in h["status_changes"])
        if nch:
            con_hash += 1
        if tardio:
            tardios += 1
        if h["eliminada_ts"]:
            eliminadas += 1
        if retro:
            retrocesos += 1
        kc = (h["dep"], h["muni"], h["zona"], h["puesto"], h["mesa"])
        filas.append({
            "dep": h["dep"], "muni": h["muni"], "zona": h["zona"], "puesto": h["puesto"], "mesa": h["mesa"],
            "first_seen": h["first_seen"].strftime("%Y-%m-%d %H:%M:%S"),
            "n_cambios_hash": nch,
            "cambio_tardio": int(tardio),
            "fechas_cambio_hash": ";".join(ts.strftime("%H:%M:%S") for ts, *_ in h["hash_changes"]),
            "hash_inicial": h["hash_changes"][0][1][:16] if nch else "",
            "hash_actual": h["name"][:16],
            "estado_actual": h["status"],
            "retroceso_estado": int(retro),
            "eliminada_ts": h["eliminada_ts"],
            "cuadre_aritmetico": cuadre.get(kc, ""),
        })

    # ordena: lo más auditable arriba (eliminadas, tardíos, más cambios)
    filas.sort(key=lambda r: (r["eliminada_ts"] == "", -r["cambio_tardio"], -r["retroceso_estado"],
                              -r["n_cambios_hash"]))

    csv_path = Path(a.salida + ".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        cols = ["dep", "muni", "zona", "puesto", "mesa", "first_seen", "n_cambios_hash",
                "cambio_tardio", "fechas_cambio_hash", "hash_inicial", "hash_actual",
                "estado_actual", "retroceso_estado", "eliminada_ts", "cuadre_aritmetico"]
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(filas)

    pct = (100 * con_hash / total) if total else 0
    md = Path(a.salida + ".md")
    with md.open("w", encoding="utf-8") as f:
        f.write(f"# Reporte de auditoría E-14 (2da vuelta)\n\n")
        f.write(f"_Generado: {datetime.now():%Y-%m-%d %H:%M:%S}_\n\n")
        f.write("## Integridad del registro\n\n")
        if integridad:
            estado = "ÍNTEGRA ✔" if integridad["ok"] else "**COMPROMETIDA ✗**"
            f.write(f"Cadena de {integridad['n']} eslabones: {estado}  \n")
            f.write(f"Ventana: {integridad['desde']} → {integridad['hasta']}\n\n")
        else:
            f.write("No se encontró `_cadena.jsonl` (no se pudo verificar integridad).\n\n")
        f.write("## Universo y tasa base\n\n")
        f.write(f"- Mesas observadas: **{total:,}**\n")
        f.write(f"- Mesas con cambio de hash: **{con_hash:,}** ({pct:.2f}%)\n")
        f.write(f"- De ellas, con cambio **tardío** (≥{a.umbral_tardio:g} h tras aparecer): **{tardios:,}**\n")
        f.write(f"- Mesas **eliminadas**: **{eliminadas:,}**\n")
        f.write(f"- Mesas con **retroceso de estado**: **{retrocesos:,}**\n\n")
        f.write("## Lectura\n\n")
        f.write("Un cambio de hash por sí solo **no es prueba de fraude**: un re-escaneo o una "
                "corrección de digitación lo producen. La tasa base de arriba es la referencia; "
                "lo que merece revisión es lo que se aparta de ella: cambios **tardíos** o "
                "**posteriores a consolidación**, **eliminaciones** y **retrocesos de estado**. "
                "El cruce con el cuadre aritmético y con el preconteo oficial (Fase 2) refuerza o "
                "descarta cada caso. Detalle por mesa en `" + csv_path.name + "`.\n")

    print(f"\nIntegridad: {'ÍNTEGRA' if (integridad and integridad['ok']) else 'REVISAR'}")
    print(f"Mesas observadas: {total:,}")
    print(f"  con cambio de hash: {con_hash:,} ({pct:.2f}%)  | tardíos: {tardios:,}  | "
          f"eliminadas: {eliminadas:,}  | retrocesos estado: {retrocesos:,}")
    print(f"\nReporte: {csv_path}  y  {md}")


if __name__ == "__main__":
    main()
