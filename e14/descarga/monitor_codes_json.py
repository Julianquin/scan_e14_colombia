#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor forense del allTransmissionCodes.json (2da vuelta).

Descarga el JSON cada N minutos y, en cada descarga:
  1. Calcula su SHA-256 y lo encadena en _cadena.jsonl (registro a prueba de
     manipulación: cada eslabón = sha256(eslabón_anterior + sha_contenido + ts),
     así no se puede alterar el pasado sin romper la cadena).
  2. Guarda un snapshot comprimido (.json.gz) con marca de tiempo.
  3. Compara con la descarga anterior por ACTA y registra:
        - añadidas      (normal según se cargan resultados)
        - ELIMINADAS    (sospechoso: una mesa no debería desaparecer)
        - hash cambiado (le sustituyeron el PDF a una mesa: corrección o manipulación)
        - estado cambiado
     Si hay eliminadas, hash cambiado, o el conteo BAJA -> alerta + detalle en _alertas/.

Uso:
    python monitor_codes_json.py                 # cada 10 min (por defecto)
    python monitor_codes_json.py --interval 300  # cada 5 min
    python monitor_codes_json.py --once          # una sola vez (prueba)
    python monitor_codes_json.py --solo-cambios  # guarda .gz solo si cambió (la cadena registra TODO igual)
"""
from __future__ import annotations
import argparse, gzip, hashlib, json, os, time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple
import requests

URL = ("https://e14segundavueltapresidente.registraduria.gov.co"
       "/assets/temis/divipol_json/allTransmissionCodes.json")


# ------------------------------- parsing ------------------------------------
def _walk(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            for nd in nodes:
                if isinstance(nd, dict) and "expectedName" in nd:
                    yield nd
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for it in value:
            yield from _walk(it)


def indexar(data: Any) -> Dict[str, Tuple[str, str]]:
    """clave_acta -> (expectedName, estado). Clave = idTransmissionCode o la ubicación."""
    idx: Dict[str, Tuple[str, str]] = {}
    for nd in _walk(data.get("data", data) if isinstance(data, dict) else data):
        en = str(nd.get("expectedName", "")).strip()
        if not en:
            continue
        idt = str(nd.get("idTransmissionCode", "")).strip()
        clave = idt or "|".join(str(nd.get(k, "")).strip() for k in
                                ("idDepartmentCode", "municipalityCode", "idZoneCode",
                                 "standCode", "numberStand"))
        idx[clave] = (en, str(nd.get("idTransmissionCodeStatus", "")).strip())
    return idx


def diferencias(prev: Dict[str, Tuple[str, str]], now: Dict[str, Tuple[str, str]]):
    pa, na = set(prev), set(now)
    comun = pa & na
    return (na - pa,                                              # añadidas
            pa - na,                                              # eliminadas
            {k for k in comun if prev[k][0] != now[k][0]},        # hash cambiado
            {k for k in comun if prev[k][1] != now[k][1]})        # estado cambiado


# ------------------------------- red ----------------------------------------
def fetch(url, timeout, retries, backoff, ua, referer) -> bytes:
    headers = {"User-Agent": ua, "Accept": "application/json,*/*;q=0.8",
               "Accept-Language": "es-CO,es;q=0.9,en;q=0.8", "Referer": referer,
               "Cache-Control": "no-cache", "Pragma": "no-cache"}
    last = ""
    for intento in range(1, retries + 1):
        try:
            u = f"{url}?t={int(time.time() * 1000)}"               # esquiva cache CDN
            r = requests.get(u, headers=headers, timeout=timeout)
            if r.status_code == 200:
                json.loads(r.content)                             # valida que es JSON
                return r.content
            last = f"http_{r.status_code}"
        except Exception as exc:
            last = repr(exc)
        if intento < retries:
            time.sleep(min(60.0, backoff * (2 ** (intento - 1))))
    raise RuntimeError(last or "fetch_failed")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------- estado -------------------------------------
def cargar_estado(out: Path):
    """Recupera índice y último eslabón de la cadena para continuar tras un reinicio."""
    estado = {"sha": None, "eslabon": "GENESIS", "idx": {}, "n": 0}
    cadena = out / "_cadena.jsonl"
    if cadena.exists():
        ult = None
        for line in cadena.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ult = json.loads(line)
        if ult:
            estado["sha"] = ult.get("sha_contenido")
            estado["eslabon"] = ult.get("eslabon", "GENESIS")
            snap = out / ult.get("snapshot", "")
            if ult.get("snapshot") and snap.exists():
                try:
                    data = json.loads(gzip.decompress(snap.read_bytes()))
                    estado["idx"] = indexar(data); estado["n"] = len(estado["idx"])
                except Exception:
                    pass
    return estado


def registrar_log(out: Path, fila: dict):
    log = out / "_monitor_log.csv"
    nuevo = not log.exists()
    cols = ["timestamp", "sha_contenido", "n_actas", "anadidas", "eliminadas",
            "hash_cambiado", "estado_cambiado", "alerta", "snapshot"]
    with log.open("a", encoding="utf-8") as f:
        if nuevo:
            f.write(",".join(cols) + "\n")
        f.write(",".join(str(fila.get(c, "")) for c in cols) + "\n")


# ------------------------------- ciclo --------------------------------------
def procesar(out: Path, raw: bytes, estado: dict, solo_cambios: bool) -> dict:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sha = sha256_bytes(raw)
    idx = indexar(json.loads(raw)); n = len(idx)
    anadidas, eliminadas, hash_camb, estado_camb = diferencias(estado["idx"], idx)
    bajada = n < estado["n"]
    alerta = bool(eliminadas) or bool(hash_camb) or bajada

    # eslabón de la cadena (cubre TODA descarga, cambie o no el contenido)
    eslabon = sha256_bytes((estado["eslabon"] + sha + ts).encode())

    # snapshot
    nombre = ""
    if not solo_cambios or sha != estado["sha"]:
        nombre = f"allTransmissionCodes_{stamp}.json.gz"
        tmp = out / (nombre + ".part")
        tmp.write_bytes(gzip.compress(raw)); os.replace(tmp, out / nombre)
        (out / "latest.json").write_bytes(raw)

    # cadena
    with (out / "_cadena.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "sha_contenido": sha, "eslabon": eslabon,
                            "eslabon_anterior": estado["eslabon"], "n_actas": n,
                            "snapshot": nombre}, ensure_ascii=False) + "\n")

    # alerta con detalle
    if alerta:
        (out / "_alertas").mkdir(exist_ok=True)
        det = {"ts": ts, "n_actas": n, "n_anterior": estado["n"],
               "eliminadas": {k: estado["idx"][k] for k in eliminadas},
               "hash_cambiado": {k: {"antes": estado["idx"][k], "ahora": idx[k]} for k in hash_camb}}
        (out / "_alertas" / f"alerta_{stamp}.json").write_text(
            json.dumps(det, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{ts}] *** ALERTA ***  actas={n:,} (antes {estado['n']:,})  "
              f"eliminadas={len(eliminadas)}  hash_cambiado={len(hash_camb)}"
              f"{'  CONTEO BAJÓ' if bajada else ''}  -> _alertas/alerta_{stamp}.json")
    elif sha != estado["sha"]:
        print(f"[{ts}] cambio  actas={n:,}  (+{len(anadidas)} nuevas, "
              f"{len(estado_camb)} cambian estado)  -> {nombre}")
    else:
        print(f"[{ts}] sin cambios  actas={n:,}")

    registrar_log(out, {"timestamp": ts, "sha_contenido": sha[:12], "n_actas": n,
                        "anadidas": len(anadidas), "eliminadas": len(eliminadas),
                        "hash_cambiado": len(hash_camb), "estado_cambiado": len(estado_camb),
                        "alerta": int(alerta), "snapshot": nombre})
    return {"sha": sha, "eslabon": eslabon, "idx": idx, "n": n}


def ciclo(args, estado: dict) -> dict:
    out = Path(args.out)
    try:
        raw = fetch(args.url, (args.connect_timeout, args.read_timeout),
                    args.retries, args.backoff, args.user_agent, args.referer)
    except Exception as exc:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] ERROR de descarga: {exc}")
        registrar_log(out, {"timestamp": ts, "sha_contenido": "", "n_actas": estado["n"],
                            "alerta": "", "snapshot": "ERROR:" + str(exc)[:40]})
        return estado
    return procesar(out, raw, estado, args.solo_cambios)


# ----------------------------- auditoría ------------------------------------
def _leer_snapshot(path: Path) -> bytes:
    b = path.read_bytes()
    return gzip.decompress(b) if path.name.endswith(".gz") else b


def _resolver(out: Path, ref: str) -> Path:
    if Path(ref).exists():
        return Path(ref)
    if (out / ref).exists():
        return out / ref
    if ref == "latest":
        return out / "latest.json"
    cand = sorted(out.glob(f"*{ref}*.json.gz")) or sorted(out.glob(f"*{ref}*.json"))
    if cand:
        return cand[0]
    raise FileNotFoundError(f"No encuentro snapshot para '{ref}'")


def verificar(out: Path):
    cadena = out / "_cadena.jsonl"
    if not cadena.exists():
        print(f"No hay _cadena.jsonl en {out}"); return
    entradas = [json.loads(l) for l in cadena.read_text(encoding="utf-8").splitlines() if l.strip()]
    prev, roto = "GENESIS", False
    for i, e in enumerate(entradas, 1):
        if e.get("eslabon_anterior") != prev:
            print(f"  [{i}] ROTO: enlace con el anterior no coincide (ts={e['ts']})"); roto = True
        if sha256_bytes((prev + e["sha_contenido"] + e["ts"]).encode()) != e.get("eslabon"):
            print(f"  [{i}] ROTO: eslabón recomputado no coincide (ts={e['ts']})"); roto = True
        snap = e.get("snapshot")
        if snap and (out / snap).exists():
            if sha256_bytes(_leer_snapshot(out / snap)) != e["sha_contenido"]:
                print(f"  [{i}] ROTO: el fichero {snap} fue ALTERADO (su hash no es el de la cadena)"); roto = True
        prev = e.get("eslabon", prev)
    if roto:
        print(f"\n*** CADENA COMPROMETIDA en {len(entradas)} eslabones. ***")
    else:
        print(f"Cadena íntegra: {len(entradas)} eslabones verificados desde GENESIS, sin alteraciones.")
        if entradas:
            print(f"  {entradas[0]['ts']}  ->  {entradas[-1]['ts']}")
            print(f"  actas: {entradas[0]['n_actas']:,}  ->  {entradas[-1]['n_actas']:,}")


def comparar(out: Path, ref_a: str, ref_b: str):
    pa, pb = _resolver(out, ref_a), _resolver(out, ref_b)
    da = indexar(json.loads(_leer_snapshot(pa)))
    db = indexar(json.loads(_leer_snapshot(pb)))
    anadidas, eliminadas, hash_camb, estado_camb = diferencias(da, db)
    print(f"A = {pa.name}  ({len(da):,} actas)")
    print(f"B = {pb.name}  ({len(db):,} actas)\n")
    print(f"  añadidas en B:    {len(anadidas):,}")
    print(f"  ELIMINADAS en B:  {len(eliminadas):,}{'   <- SOSPECHOSO' if eliminadas else ''}")
    print(f"  hash cambiado:    {len(hash_camb):,}{'   <- PDF sustituido' if hash_camb else ''}")
    print(f"  estado cambiado:  {len(estado_camb):,}")
    for k in sorted(eliminadas):
        print(f"    [eliminada] {k}  era {da[k]}")
    for k in sorted(hash_camb):
        print(f"    [hash] {k}  antes={da[k][0]}  ahora={db[k][0]}")

    sal = out / f"comparacion_{pa.stem}__{pb.stem}.csv".replace(".json", "")
    with sal.open("w", encoding="utf-8", newline="") as f:
        f.write("tipo,clave,antes,ahora\n")
        for k in sorted(eliminadas):
            f.write(f"eliminada,{k},{da[k]},\n")
        for k in sorted(hash_camb):
            f.write(f"hash_cambiado,{k},{da[k][0]},{db[k][0]}\n")
        for k in sorted(estado_camb):
            f.write(f"estado_cambiado,{k},{da[k][1]},{db[k][1]}\n")
        for k in sorted(anadidas):
            f.write(f"anadida,{k},,{db[k][0]}\n")
    print(f"\nDetalle volcado en: {sal.name}")


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Monitor forense del allTransmissionCodes.json (2da vuelta)")
    ap.add_argument("--url", default=URL)
    ap.add_argument("--out", default="codes_snapshots")
    ap.add_argument("--interval", type=int, default=600, help="segundos entre descargas (def 600 = 10 min)")
    ap.add_argument("--once", action="store_true", help="una sola descarga y salir")
    ap.add_argument("--solo-cambios", action="store_true",
                    help="guarda el .gz solo cuando cambia (la cadena registra TODA descarga igual)")
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--backoff", type=float, default=2.0)
    ap.add_argument("--connect-timeout", type=float, default=15.0)
    ap.add_argument("--read-timeout", type=float, default=180.0)
    ap.add_argument("--user-agent", default="Mozilla/5.0 (compatible; E14CodesMonitor/1.0)")
    ap.add_argument("--referer", default="https://e14segundavueltapresidente.registraduria.gov.co/")
    ap.add_argument("--verificar", action="store_true", help="verifica la cadena de integridad y sale")
    ap.add_argument("--comparar", nargs=2, metavar=("A", "B"),
                    help="compara dos snapshots (ruta, nombre, 'latest' o un trozo de fecha) y sale")
    a = ap.parse_args()

    out = Path(a.out)
    if a.verificar:
        verificar(out); return
    if a.comparar:
        comparar(out, a.comparar[0], a.comparar[1]); return
    out.mkdir(parents=True, exist_ok=True)
    estado = cargar_estado(out)
    if estado["n"]:
        print(f"Estado previo: {estado['n']:,} actas en el último snapshot.")
    print(f"Monitorizando cada {a.interval}s -> {out}/  (Ctrl-C para parar)")
    try:
        while True:
            estado = ciclo(a, estado)
            if a.once:
                break
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print("\nDetenido por el usuario.")


if __name__ == "__main__":
    main()
