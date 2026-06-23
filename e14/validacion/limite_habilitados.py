#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Límite de habilitados — cruza el censo electoral (Anexo 4 de la Registraduría,
habilitados por PUESTO) con los votantes leídos de las actas E-14.

Restricción dura: los votantes de un puesto no pueden superar sus cédulas
habilitadas. Si los superan, es una anomalía objetiva (más votos que votantes
inscritos). Como la participación nunca es del 100%, una violación es una señal
fuerte y de muy baja tasa de falsos positivos.

IMPORTANTE: el Anexo 4 está a nivel de PUESTO (da 'total' habilitados y nº de
'mesas'), NO por mesa. El tope por mesa no es uniforme (hay puestos especiales),
así que el chequeo exacto se hace agregando los votos de las mesas de cada puesto
y comparándolo con el total del puesto. El chequeo por mesa es opcional y requiere
un tope (--cap-mesa) que debes confirmar.

NO dictamina fraude: cuantifica y documenta. Una participación imposible (>100%)
es señal dura; una muy alta (p.ej. >95%) es señal blanda para revisar.

Uso:
    # 1) Limpiar el Excel a un CSV reutilizable (data/manifests/)
    python limite_habilitados.py preparar Copia_de_Anexo_4.xlsx --salida habilitados_puesto.csv

    # 2) Validar contra los votantes leídos (TOTAL_E11 por mesa)
    python limite_habilitados.py validar --habilitados habilitados_puesto.csv \
           --votos numeros_leidos.csv [--ejemplar TRANSMISION] [--umbral-alto 0.95] [--cap-mesa 600]
"""
from __future__ import annotations
import argparse, csv
from collections import defaultdict
from pathlib import Path


def _norm(x):
    """Normaliza códigos para el cruce: '01' -> '1' (robusto a ceros a la izquierda)."""
    s = str(x).strip()
    return str(int(s)) if s.isdigit() else s


def clave_puesto(dep, muni, zona, puesto):
    return (_norm(dep), _norm(muni), _norm(zona), _norm(puesto))


# ------------------------------ habilitados ---------------------------------
def cargar_habilitados_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    filas = list(ws.iter_rows(values_only=True))
    # localizar cabecera (la fila con 'dd','mm','zz','pp')
    hi = next(i for i, r in enumerate(filas)
              if r and str(r[0]).strip() == "dd" and "pp" in [str(c).strip() for c in r if c])
    reg = {}
    for r in filas[hi + 1:]:
        if not r or r[0] is None or r[3] is None:      # salta total nacional y vacías
            continue
        dd, mm, zz, pp = r[0], r[1], r[2], r[3]
        if not str(dd).strip().isdigit():
            continue
        reg[clave_puesto(dd, mm, zz, pp)] = {
            "dep": _norm(dd), "muni": _norm(mm), "zona": _norm(zz), "puesto": _norm(pp),
            "departamento": r[4], "municipio": r[5], "nombre_puesto": r[6],
            "mujeres": r[7], "hombres": r[8], "total": int(r[9]), "mesas": int(r[10]),
            "direccion": r[12] if len(r) > 12 else ""}
    return reg


def cargar_habilitados_csv(path):
    reg = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        reg[clave_puesto(r["dep"], r["muni"], r["zona"], r["puesto"])] = {
            **r, "total": int(r["total"]), "mesas": int(r["mesas"])}
    return reg


def cargar_habilitados(path):
    return cargar_habilitados_xlsx(path) if str(path).lower().endswith((".xlsx", ".xlsm")) \
        else cargar_habilitados_csv(path)


# --------------------------------- votos ------------------------------------
def cargar_votos(path, campo="TOTAL_E11", ejemplar=None):
    """
    Lee numeros_leidos.csv (formato largo: una fila por casilla con 'etiqueta' y
    valor). Devuelve votantes por mesa: {(dep,muni,zona,puesto,mesa): valor}.
    """
    f = open(path, encoding="utf-8-sig")
    rd = csv.DictReader(f)
    cols = {c.lower(): c for c in (rd.fieldnames or [])}
    col_val = next((cols[c] for c in ("numero", "valor", "lectura", "texto", "valor_final") if c in cols), None)
    col_et = cols.get("etiqueta")
    por_mesa = {}
    for r in rd:
        if col_et and r[col_et].strip().upper() != campo:
            continue
        if ejemplar and str(r.get("ejemplar", "")).strip().upper() != ejemplar.upper():
            continue
        try:
            v = int(str(r[col_val]).strip())
        except (ValueError, TypeError):
            continue
        k = (_norm(r["dep"]), _norm(r["muni"]), _norm(r["zona"]), _norm(r["puesto"]), _norm(r["mesa"]))
        por_mesa[k] = v
    return por_mesa


# ------------------------------- validación ---------------------------------
def validar(habil, votos_mesa, umbral_alto, cap_mesa, salida):
    # agrega votos por puesto
    por_puesto = defaultdict(lambda: {"votos": 0, "n_mesas": 0})
    for (d, m, z, p, _mesa), v in votos_mesa.items():
        kp = (d, m, z, p)
        por_puesto[kp]["votos"] += v
        por_puesto[kp]["n_mesas"] += 1

    filas_p, excede, alto, sin_censo = [], 0, 0, 0
    for kp, agg in por_puesto.items():
        h = habil.get(kp)
        if not h:
            sin_censo += 1
            filas_p.append({"dep": kp[0], "muni": kp[1], "zona": kp[2], "puesto": kp[3],
                            "habilitados": "", "votos": agg["votos"], "ratio": "",
                            "mesas_censo": "", "mesas_leidas": agg["n_mesas"], "bandera": "SIN_CENSO"})
            continue
        ratio = agg["votos"] / h["total"] if h["total"] else 0
        bandera = "EXCEDE" if agg["votos"] > h["total"] else ("ALTO" if ratio >= umbral_alto else "")
        if bandera == "EXCEDE":
            excede += 1
        elif bandera == "ALTO":
            alto += 1
        filas_p.append({"dep": kp[0], "muni": kp[1], "zona": kp[2], "puesto": kp[3],
                        "habilitados": h["total"], "votos": agg["votos"], "ratio": round(ratio, 4),
                        "mesas_censo": h["mesas"], "mesas_leidas": agg["n_mesas"], "bandera": bandera})

    filas_p.sort(key=lambda r: (r["bandera"] != "EXCEDE", r["bandera"] != "ALTO",
                                -(r["ratio"] or 0) if isinstance(r["ratio"], float) else 0))
    pp = Path(salida + "_puesto.csv")
    with pp.open("w", newline="", encoding="utf-8") as f:
        cols = ["dep", "muni", "zona", "puesto", "habilitados", "votos", "ratio",
                "mesas_censo", "mesas_leidas", "bandera"]
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(filas_p)

    # chequeo por mesa (opcional, requiere tope)
    mp_n = 0
    if cap_mesa:
        pm = Path(salida + "_mesa.csv")
        with pm.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["dep", "muni", "zona", "puesto", "mesa", "votantes", "cap", "bandera"])
            for (d, m, z, p, mesa), v in sorted(votos_mesa.items()):
                if v > cap_mesa:
                    mp_n += 1
                    w.writerow([d, m, z, p, mesa, v, cap_mesa, "SUPERA_CAP"])

    print(f"=== LÍMITE DE HABILITADOS ===")
    print(f"Puestos con votos leídos: {len(por_puesto):,}")
    print(f"  EXCEDE habilitados (>100%):  {excede:,}   <- anomalía dura")
    print(f"  participación ALTA (≥{umbral_alto:.0%}): {alto:,}   <- revisar")
    print(f"  sin censo cruzable:          {sin_censo:,}")
    if cap_mesa:
        print(f"Mesas que superan cap={cap_mesa}: {mp_n:,}")
    print(f"\nReporte por puesto: {pp}" + (f"  | por mesa: {salida}_mesa.csv" if cap_mesa else ""))


# --------------------------------- preparar ---------------------------------
def preparar(xlsx, salida):
    reg = cargar_habilitados_xlsx(xlsx)
    cols = ["dep", "muni", "zona", "puesto", "departamento", "municipio",
            "nombre_puesto", "mujeres", "hombres", "total", "mesas", "direccion"]
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for v in reg.values():
            w.writerow(v)
    tot = sum(v["total"] for v in reg.values())
    mesas = sum(v["mesas"] for v in reg.values())
    maxavg = max(v["total"] / v["mesas"] for v in reg.values() if v["mesas"])
    print(f"Puestos: {len(reg):,}  |  habilitados: {tot:,}  |  mesas: {mesas:,}")
    print(f"Promedio por mesa: {tot/mesas:.1f}  |  máx promedio/mesa observado: {maxavg:.0f}")
    print(f"(sugerencia: un --cap-mesa razonable va por encima de ~{int(maxavg)+50})")
    print(f"CSV listo: {salida}")


def main():
    ap = argparse.ArgumentParser(description="Cruce censo (Anexo 4) vs votantes E-14")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preparar"); p.add_argument("xlsx")
    p.add_argument("--salida", default="habilitados_puesto.csv")
    p = sub.add_parser("validar")
    p.add_argument("--habilitados", required=True); p.add_argument("--votos", required=True)
    p.add_argument("--campo", default="TOTAL_E11"); p.add_argument("--ejemplar", default=None)
    p.add_argument("--umbral-alto", type=float, default=0.95)
    p.add_argument("--cap-mesa", type=int, default=None)
    p.add_argument("--salida", default="limite_habilitados")
    a = ap.parse_args()

    if a.cmd == "preparar":
        preparar(a.xlsx, a.salida)
    elif a.cmd == "validar":
        habil = cargar_habilitados(a.habilitados)
        votos = cargar_votos(a.votos, a.campo, a.ejemplar)
        print(f"Cargados {len(habil):,} puestos del censo y {len(votos):,} mesas con votos.\n")
        validar(habil, votos, a.umbral_alto, a.cap_mesa, a.salida)


if __name__ == "__main__":
    main()