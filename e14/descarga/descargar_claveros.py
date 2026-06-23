#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga de actas CLAVEROS (escrutinio) — 2da vuelta. FASE A + inspector.

El portal de escrutinios usa DOS niveles:
  1) index.json  -> mapea rutas a ficheros JSON intermedios (uno por puesto).
  2) cada JSON por-puesto lista sus mesas y la referencia al PDF (incluido el
     número final tipo '3085' que NO es deducible).

Este script:
  - `indices`     : baja los JSON intermedios desde index.json (incremental).
  - `inspeccionar`: vuelca la estructura de un JSON ya bajado para fijar cómo se
                    construye la URL del PDF (paso previo a la fase B = bajar PDFs).

Uso:
    python descargar_claveros.py indices index.json --out claveros_idx
    python descargar_claveros.py indices index.json --out claveros_idx --tipos consolidado
    python descargar_claveros.py inspeccionar claveros_idx/.../actas_documentos_xxx.json
"""
from __future__ import annotations
import argparse, json, os, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import requests

BASE = "https://escrutinios2vueltapresidente2026.registraduria.gov.co/"


def clasificar(clave: str) -> str:
    if "actas-documentos" in clave and clave.rstrip("/").endswith("mesas"):
        return "documentos"
    if "actas-publicadas/consolidado" in clave:
        return "consolidado"
    if "avance-actas" in clave:
        return "avance"
    return "otro"


def fetch(url, timeout, retries, backoff, ua):
    headers = {"User-Agent": ua, "Accept": "application/json,*/*;q=0.8",
               "Referer": BASE, "Cache-Control": "no-cache"}
    last = ""
    for intento in range(1, retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.content
            last = f"http_{r.status_code}"
        except Exception as exc:
            last = repr(exc)
        if intento < retries:
            time.sleep(min(30.0, backoff * (2 ** (intento - 1))))
    raise RuntimeError(last or "fetch_failed")


def es_json_valido(path: Path, min_bytes: int) -> bool:
    try:
        if path.stat().st_size < min_bytes:
            return False
        json.loads(path.read_bytes())
        return True
    except Exception:
        return False


def indices(index_json, out, tipos, base, retries, backoff, timeout, ua, min_bytes, limite):
    idx = json.load(open(index_json, encoding="utf-8"))
    out = Path(out); (out / "_logs").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    man = (out / "_logs" / f"manifest_{stamp}.jsonl").open("w", encoding="utf-8")

    objetivo = [(k, v) for k, v in idx.items() if clasificar(k) in tipos]
    if limite:
        objetivo = objetivo[:limite]
    total = len(objetivo)
    print(f"Tipos: {sorted(tipos)}  ->  {total:,} ficheros a bajar  (de {len(idx):,} en el index)")

    ok = skip = err = 0
    t0 = time.time()
    for i, (clave, fichero) in enumerate(objetivo, 1):
        url = base + clave + fichero
        destino = out / clave / fichero
        destino.parent.mkdir(parents=True, exist_ok=True)
        estado = ""
        if es_json_valido(destino, min_bytes):
            skip += 1; estado = "skip"
        else:
            try:
                raw = fetch(url, (timeout, timeout * 3), retries, backoff, ua)
                json.loads(raw)                      # valida
                tmp = destino.with_suffix(destino.suffix + f".part{os.getpid()}")
                tmp.write_bytes(raw); os.replace(tmp, destino)
                ok += 1; estado = "ok"
            except Exception as exc:
                err += 1; estado = f"error:{exc}"[:80]
        man.write(json.dumps({"clave": clave, "fichero": fichero, "estado": estado}, ensure_ascii=False) + "\n")
        if i % 200 == 0 or i == total:
            rps = i / max(1e-9, time.time() - t0)
            print(f"{i}/{total} | ok={ok} skip={skip} err={err} | {rps:.1f}/s")
    man.close()
    print(f"\nHecho. ok={ok} skip={skip} err={err}.  Índices en {out}/")
    print("Siguiente paso: 'inspeccionar' uno para fijar el patrón del PDF (fase B).")


def _strings_pdf(value, acc, limite=20):
    if len(acc) >= limite:
        return
    if isinstance(value, str):
        if ".pdf" in value.lower() or "E14" in value:
            acc.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _strings_pdf(v, acc, limite)
    elif isinstance(value, list):
        for v in value:
            _strings_pdf(v, acc, limite)


def inspeccionar(archivo):
    d = json.loads(Path(archivo).read_bytes())
    print(f"=== {archivo} ===")
    print("tipo raíz:", type(d).__name__)
    if isinstance(d, dict):
        print("claves raíz:", list(d.keys())[:30])
        for k in list(d.keys())[:6]:
            v = d[k]
            t = type(v).__name__
            extra = f"len={len(v)}" if isinstance(v, (list, dict)) else repr(v)[:120]
            print(f"  [{k}] {t}  {extra}")
            if isinstance(v, list) and v:
                print(f"      primer elem: {json.dumps(v[0], ensure_ascii=False)[:400]}")
    elif isinstance(d, list):
        print("len:", len(d))
        if d:
            print("primer elem:", json.dumps(d[0], ensure_ascii=False)[:600])
    acc = []
    _strings_pdf(d, acc)
    print("\nCadenas con '.pdf' o 'E14' encontradas (muestra):")
    for s in acc:
        print("  ", s)
    if not acc:
        print("  (ninguna directa — pega aquí la salida y vemos los campos para armar la URL)")


def _es_pdf_valido(path: Path, min_bytes: int) -> bool:
    try:
        if path.stat().st_size < min_bytes:
            return False
        with open(path, "rb") as f:
            return f.read(5).startswith(b"%PDF")
    except Exception:
        return False


def _plan_pdf(rec, base, out: Path):
    """De un registro de mesa -> (url, ruta_local, codigos). None si no hay PDF."""
    na = str(rec.get("nombre_archivo", "")).strip()
    if not na:
        return None
    url = base.rstrip("/") + "/" + na.lstrip("/")
    local = out / na.lstrip("/")
    partes = na.lstrip("/").split("/")            # docs/E14/dep/muni/zona/puesto/fichero
    dep, muni, zona, puesto = (partes[2], partes[3], partes[4], partes[5]) if len(partes) >= 7 else ("", "", "", "")
    mesa = str(rec.get("numero", "")).strip()
    return url, local, {"dep": dep, "muni": muni, "zona": zona, "puesto": puesto, "mesa": mesa}


_tls = threading.local()


def _sesion(ua):
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": ua, "Accept": "*/*", "Referer": BASE,
                          "Cache-Control": "no-cache"})
        _tls.s = s
    return s


def _fetch_sess(url, timeout, retries, backoff, ua):
    s = _sesion(ua); last = ""
    for i in range(1, retries + 1):
        try:
            r = s.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.content
            last = f"http_{r.status_code}"
        except Exception as exc:
            last = repr(exc)
        if i < retries:
            time.sleep(min(20.0, backoff * (2 ** (i - 1))))
    raise RuntimeError(last or "fetch_failed")


def _bajar_pdf(task, timeout, retries, backoff, ua, min_bytes):
    url, local = task[0], task[1]
    if _es_pdf_valido(local, min_bytes):
        return task, "skip"
    try:
        raw = _fetch_sess(url, (timeout, timeout * 3), retries, backoff, ua)
        if not raw[:5].startswith(b"%PDF"):
            raise RuntimeError("no_pdf")
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_suffix(local.suffix + f".part{os.getpid()}_{threading.get_ident()}")
        tmp.write_bytes(raw); os.replace(tmp, local)
        return task, "ok"
    except Exception as exc:
        return task, f"error:{exc}"[:80]


def pdfs(indices_dir, out, base, retries, backoff, timeout, ua, solo_digitalizadas,
         min_bytes, limite, workers):
    indices_dir = Path(indices_dir); out = Path(out)
    (out / "_logs").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1) construir la lista de tareas recorriendo los JSON por-puesto
    jsons = sorted(indices_dir.rglob("actas_documentos_*mesas_*.json"))
    print(f"JSON por-puesto: {len(jsons):,}  ->  construyendo lista de PDFs...")
    tareas, omit = [], 0
    for jp in jsons:
        try:
            registros = json.loads(jp.read_bytes())
        except Exception:
            continue
        for rec in registros:
            if solo_digitalizadas and rec.get("digitalizado") != 1:
                omit += 1; continue
            plan = _plan_pdf(rec, base, out)
            if not plan:
                omit += 1; continue
            url, local, cod = plan
            tareas.append((url, local, cod, str(rec.get("nombre_archivo", "")).strip(),
                           rec.get("digitalizado", ""), rec.get("escrutado", "")))
    if limite:
        tareas = tareas[:limite]
    print(f"PDFs a procesar: {len(tareas):,}  (omitidas sin pdf/no digitalizadas: {omit:,})  | workers={workers}")

    # 2) descargar en paralelo; el hilo principal escribe manifest + csv
    man = (out / "_logs" / f"pdf_manifest_{stamp}.jsonl").open("w", encoding="utf-8")
    csv_path = out / "claveros_mesas.csv"
    nuevo = not csv_path.exists()
    csvf = csv_path.open("a", encoding="utf-8", newline="")
    if nuevo:
        csvf.write("dep,muni,zona,puesto,mesa,nombre_archivo,ruta_local,digitalizado,escrutado,estado\n")

    ok = skip = err = 0
    t0 = time.time(); n = len(tareas)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_bajar_pdf, t, timeout, retries, backoff, ua, min_bytes) for t in tareas]
        for i, fut in enumerate(as_completed(futs), 1):
            task, estado = fut.result()
            url, local, cod, na, dig, esc = task
            if estado == "ok": ok += 1
            elif estado == "skip": skip += 1
            else: err += 1
            man.write(json.dumps({"url": url, "estado": estado}, ensure_ascii=False) + "\n")
            csvf.write(f"{cod['dep']},{cod['muni']},{cod['zona']},{cod['puesto']},{cod['mesa']},"
                       f"{na},{local},{dig},{esc},{estado}\n")
            if i % 500 == 0 or i == n:
                rps = i / max(1e-9, time.time() - t0)
                eta = (n - i) / max(1e-9, rps)
                print(f"{i}/{n} | ok={ok} skip={skip} err={err} | {rps:.1f}/s | ETA {eta/60:.0f} min")
    man.close(); csvf.close()
    print(f"\nHecho. ok={ok} skip={skip} err={err}.")
    print(f"PDFs en {out}/docs/E14/...   |   índice de mesas: {csv_path}")
    if err:
        print("Hubo errores (429/403/timeout): relanza el mismo comando; es reanudable y solo reintentará lo que falte.")


def main():
    ap = argparse.ArgumentParser(description="Descarga CLAVEROS (escrutinio) 2da vuelta")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("indices"); p.add_argument("index_json")
    p.add_argument("--out", default="claveros_idx")
    p.add_argument("--tipos", default="documentos,consolidado",
                   help="coma-separado: documentos,consolidado,avance,otro")
    p.add_argument("--base", default=BASE)
    p.add_argument("--retries", type=int, default=4); p.add_argument("--backoff", type=float, default=1.5)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--min-bytes", type=int, default=2)
    p.add_argument("--limite", type=int, default=None, help="solo los primeros N (prueba)")
    p.add_argument("--user-agent", default="Mozilla/5.0 (compatible; E14ClaverosDL/1.0)")

    p = sub.add_parser("inspeccionar"); p.add_argument("archivo")

    p = sub.add_parser("pdfs"); p.add_argument("--indices", default="claveros_idx")
    p.add_argument("--out", default="e14_pdfs_claveros"); p.add_argument("--base", default=BASE)
    p.add_argument("--retries", type=int, default=4); p.add_argument("--backoff", type=float, default=1.5)
    p.add_argument("--timeout", type=float, default=30.0); p.add_argument("--min-bytes", type=int, default=800)
    p.add_argument("--incluir-no-digitalizadas", action="store_true",
                   help="intenta bajar también las marcadas digitalizado!=1 (por defecto se omiten)")
    p.add_argument("--limite", type=int, default=None)
    p.add_argument("--workers", type=int, default=16, help="descargas en paralelo (16-24 recomendado)")
    p.add_argument("--user-agent", default="Mozilla/5.0 (compatible; E14ClaverosDL/1.0)")

    a = ap.parse_args()
    if a.cmd == "indices":
        indices(a.index_json, a.out, set(t.strip() for t in a.tipos.split(",")),
                a.base, a.retries, a.backoff, a.timeout, a.user_agent, a.min_bytes, a.limite)
    elif a.cmd == "inspeccionar":
        inspeccionar(a.archivo)
    elif a.cmd == "pdfs":
        pdfs(a.indices, a.out, a.base, a.retries, a.backoff, a.timeout, a.user_agent,
             not a.incluir_no_digitalizadas, a.min_bytes, a.limite, a.workers)


if __name__ == "__main__":
    main()