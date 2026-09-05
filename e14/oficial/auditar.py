#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auditoría PRECONTEO vs ESCRUTINIO — los dos conteos oficiales, mesa a mesa.

Por qué este chequeo vale la pena: **no depende del OCR**. Cruza dos ficheros
oficiales verificados por hash, así que produce resultados firmes hoy, sin
esperar a que mejore la lectura del papel. El OCR entra después, para dirimir
quién tiene razón en las mesas que este análisis señala.

### Lo que este análisis NO dice

Que el escrutinio cambie el preconteo **no es una anomalía**: el escrutinio es
el acto jurídico que existe precisamente para corregir el conteo informal de la
noche electoral. Encontrar diferencias es lo normal y lo esperado.

Lo que sí se puede auditar es *cuántas*, *de qué tipo* y **hacia dónde**:

  - ANULADA      la mesa queda en 0 en el escrutinio (causal de anulación).
  - PERMUTACION  el escrutinio tiene los MISMOS valores que el preconteo pero
                 repartidos entre otros candidatos. Con dos candidatos es el
                 intercambio clásico de columnas al transcribir. Es la
                 tipología más nítida: no cambia el total de la mesa, así que
                 ninguna suma la delata — sólo la comparación la revela.
  - APARECE      la mesa no tenía votos en preconteo y sí en escrutinio.
  - OTROS        el resto de cambios de magnitud.

### La pregunta que decide: direccionalidad

Un error humano de transcripción no tiene preferencia política: debería
repartirse por igual entre candidatos. Por eso, para cada tipología se corre un
**test binomial de dos colas** sobre a quién favorece. Un p alto significa
"compatible con error"; un p bajo, una asimetría que el error honesto no
explica. Esto es un test, no una acusación, y por eso resiste el escrutinio
crítico.

Uso:
    python -m e14.oficial.auditar data/manifests/MMV_2V/MMV_Presidente2V_2026 \
        --out data/segunda_vuelta/_oficial/auditoria_2v

    # comparar la tasa base entre rondas (la 1ra vuelta es el grupo de control)
    python -m e14.oficial.auditar data/manifests/MMV_1V/MMV_Presidente1V_2026 \
        --out data/primer_vuelta/_oficial/auditoria_1v
"""
from __future__ import annotations
import argparse, csv
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

from e14.oficial import mmv


# ------------------------------- clasificación -------------------------------
def clasificar(pre: dict, esc: dict) -> str:
    """Tipología del cambio de UNA mesa. Sólo mira candidatos-persona: mover
    votos entre BLANCO/NULO/NO_MARCADO no altera el resultado entre personas.

    Compara sobre la UNIÓN de códigos con default 0: un fichero puede omitir
    la fila de un candidato con 0 votos y el otro incluirla, y comparar los
    dicts tal cual marcaría un cambio inexistente (pasó: inflaba el recuento
    de mesas cambiadas de 1.151 a 1.532)."""
    codigos = {k for k in (*pre, *esc) if mmv.es_candidato(k)}
    cp = {k: pre.get(k, 0) for k in codigos}
    ce = {k: esc.get(k, 0) for k in codigos}
    if mmv.mismos_votos(pre, esc):
        return "SIN_CAMBIO"
    tot_p, tot_e = sum(cp.values()), sum(ce.values())
    if tot_e == 0 and tot_p > 0:
        return "ANULADA"
    if tot_p == 0 and tot_e > 0:
        return "APARECE"
    if sorted(cp.values()) == sorted(ce.values()):
        return "PERMUTACION"
    return "OTROS"


def _binomial_dos_colas(k: int, n: int, p0: float = 0.5) -> float:
    """Test binomial exacto de dos colas: P(resultado tan o más extremo que k
    de n) bajo H0 = probabilidad p0. Sin scipy; la suma exacta es barata aquí.

    p0 NO es 0,5 salvo con exactamente dos candidatos. Con 13 (1ra vuelta) la
    hipótesis nula correcta es que los errores caen sobre cada candidato en
    proporción a su votación —un candidato grande tiene más votos que perder o
    ganar por error—, así que p0 es su cuota de votos. Usar 0,5 con 13
    candidatos declaraba "asimetría significativa" siempre, porque ninguno
    llega al 50 %: era un falso positivo garantizado."""
    if n == 0:
        return 1.0
    def pmf(i):
        return comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i))
    obs = pmf(k)
    # dos colas exacto (método de Sterne): sumar toda masa no más probable que la observada
    return min(1.0, sum(pmf(i) for i in range(n + 1) if pmf(i) <= obs * (1 + 1e-9)))


# --------------------------------- auditoría ---------------------------------
def auditar(carpeta, out, top=25):
    f = mmv.localizar(carpeta)
    for req in ("preconteo", "escrutinio"):
        if req not in f:
            raise SystemExit(f"No encuentro el fichero de {req} en {carpeta}")

    print("Integridad (SHA-256 contra el hash oficial de la Registraduría):")
    integro = mmv.verificar(carpeta)
    if not integro:
        print("  ATENCIÓN: algún fichero no verifica; el análisis NO es reproducible.")

    cand = mmv.cargar_candidatos(f["candidatos"]) if "candidatos" in f else {}
    print("\nCargando...")
    pre = mmv.cargar_preconteo(f["preconteo"])
    esc = mmv.cargar_escrutinio(f["escrutinio"])
    comunes = sorted(set(pre) & set(esc))
    print(f"  mesas preconteo={len(pre):,}  escrutinio={len(esc):,}  en ambos={len(comunes):,}")
    solo_p, solo_e = set(pre) - set(esc), set(esc) - set(pre)
    if solo_p or solo_e:
        print(f"  sólo en preconteo: {len(solo_p):,}   sólo en escrutinio: {len(solo_e):,}")

    # códigos de candidato-persona presentes, ordenados por votación
    tot_esc = defaultdict(int)
    for v in esc.values():
        for c, n in v.items():
            tot_esc[c] += n
    # se excluyen los candidatos RETIRADOS (0 votos): no pueden salir favorecidos
    # nunca, así que inflarían el test de direccionalidad con ceros estructurales.
    personas = [c for c, v in sorted(tot_esc.items(), key=lambda kv: -kv[1])
                if mmv.es_candidato(c) and v > 0]
    retirados = [c for c, v in tot_esc.items() if mmv.es_candidato(c) and v == 0]
    if retirados:
        print(f"  candidatos con 0 votos (retirados), excluidos del test: "
              f"{', '.join(mmv.nombre_de(c, cand) for c in retirados)}")

    tip = Counter()
    delta = defaultdict(int)                     # efecto total por candidato
    delta_por_tip = defaultdict(lambda: defaultdict(int))
    favorece = defaultdict(Counter)              # tipología -> candidato favorecido
    filas = []

    for k in comunes:
        t = clasificar(pre[k], esc[k])
        tip[t] += 1
        if t == "SIN_CAMBIO":
            continue
        d = {c: esc[k].get(c, 0) - pre[k].get(c, 0) for c in personas}
        for c, v in d.items():
            delta[c] += v
            delta_por_tip[t][c] += v
        ganador = max(d.items(), key=lambda kv: kv[1])
        if ganador[1] > 0:
            favorece[t][ganador[0]] += 1
        filas.append({
            "dep": k[0], "muni": k[1], "zona": k[2], "puesto": k[3], "mesa": k[4],
            "tipologia": t,
            **{f"pre_{mmv.nombre_de(c, cand)[:18]}": pre[k].get(c, 0) for c in personas},
            **{f"esc_{mmv.nombre_de(c, cand)[:18]}": esc[k].get(c, 0) for c in personas},
            "impacto_votos": sum(abs(v) for v in d.values()),
        })

    # ------------------------------ reportes ---------------------------------
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    if filas:
        cols = list(filas[0].keys())
        with open(f"{out}.mesas.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(sorted(filas, key=lambda r: -r["impacto_votos"]))

    n_cambio = sum(v for t, v in tip.items() if t != "SIN_CAMBIO")
    print(f"\n=== CAMBIOS ENTRE PRECONTEO Y ESCRUTINIO ===")
    print(f"mesas comparadas: {len(comunes):,}")
    print(f"mesas que cambiaron: {n_cambio:,}  ({100*n_cambio/max(1,len(comunes)):.2f}%)")
    print(f"\n{'tipología':14s} {'mesas':>8s}  efecto por candidato")
    for t, n in tip.most_common():
        if t == "SIN_CAMBIO":
            continue
        ef = "  ".join(f"{mmv.nombre_de(c, cand)[:16]}:{delta_por_tip[t][c]:+,}" for c in personas[:3])
        print(f"{t:14s} {n:>8,}  {ef}")

    # H0 de "cuántas veces debería salir favorecido cada candidato".
    # Depende del MECANISMO de la tipología, no es una sola para todas:
    #   PERMUTACION -> los valores se barajan entre candidatos, así que cada uno
    #     tiene la misma probabilidad de quedarse con el mayor: H0 UNIFORME (1/k).
    #   el resto -> son errores de magnitud sobre los votos existentes, y quien
    #     más votos tiene más tiene en juego: H0 PROPORCIONAL a su votación.
    # Usar la proporcional en PERMUTACION marcaba como "asimetría" a todos los
    # candidatos pequeños, que es un artefacto del mecanismo, no una señal.
    tot_personas = sum(tot_esc[c] for c in personas) or 1
    cuota_prop = {c: tot_esc[c] / tot_personas for c in personas}
    cuota_unif = {c: 1.0 / len(personas) for c in personas}

    print(f"\n=== DIRECCIONALIDAD (¿los cambios son simétricos?) ===")
    print(f"Test binomial exacto por candidato, Bonferroni sobre {len(personas)} comparaciones.")
    print("La hipótesis nula depende del mecanismo de cada tipología (ver código).")
    print("LIMITACIÓN: la H0 uniforme de PERMUTACION supone que los valores se barajan")
    print("entre TODOS los candidatos. Si en la práctica se intercambian sobre todo")
    print("entre casillas contiguas del formulario, los vecinos saldrán sobre-representados")
    print("sin que eso implique nada. Con 2 candidatos (2da vuelta) no aplica.")
    alpha = 0.05 / max(1, len(personas))
    for t in ("PERMUTACION", "ANULADA", "OTROS", "APARECE"):
        c = favorece.get(t)
        if not c or sum(c.values()) < 2:
            continue
        n = sum(c.values())
        cuota = cuota_unif if t == "PERMUTACION" else cuota_prop
        h0 = "uniforme (los valores se barajan)" if t == "PERMUTACION" else "proporcional a la votación"
        print(f"\n  {t}  (n={n})   H0: {h0}")
        filas_dir = []
        for cod in personas:
            k = c.get(cod, 0)
            if k == 0 and cuota[cod] * n < 1:
                continue
            p = _binomial_dos_colas(k, n, cuota[cod])
            filas_dir.append((p, cod, k, cuota[cod] * n))
        for p, cod, k, esperado in sorted(filas_dir):
            marca = "  <- ASIMETRÍA" if p < alpha else ""
            print(f"    {mmv.nombre_de(cod, cand)[:26]:26s} favorecido {k:>5} veces "
                  f"(esperado {esperado:6.1f})  p={p:.4f}{marca}")
        if not any(p < alpha for p, *_ in filas_dir):
            print("    -> todo compatible con error de transcripción")

    if len(personas) >= 2:
        v1, v2 = tot_esc[personas[0]], tot_esc[personas[1]]
        margen = v1 - v2
        efecto = delta[personas[0]] - delta[personas[1]]
        print(f"\n=== IMPACTO SOBRE EL RESULTADO ===")
        print(f"margen oficial ({mmv.nombre_de(personas[0], cand)[:20]} sobre "
              f"{mmv.nombre_de(personas[1], cand)[:20]}): {margen:,} votos")
        print(f"efecto NETO de todos los cambios sobre ese margen: {efecto:+,} votos "
              f"({100*abs(efecto)/max(1,abs(margen)):.3f}% del margen)")
        print(f"votos movidos en total (suma de |cambios|): "
              f"{sum(r['impacto_votos'] for r in filas):,}")

    if filas:
        print(f"\n=== TOP {top} MESAS POR IMPACTO ===")
        for r in sorted(filas, key=lambda x: -x["impacto_votos"])[:top]:
            loc = f"{r['dep']}/{r['muni']}/{r['zona']}/{r['puesto']}/{r['mesa']}"
            print(f"  {loc:24s} {r['tipologia']:12s} {r['impacto_votos']:>5} votos")
        print(f"\nDetalle completo: {out}.mesas.csv")

    print("\nRecordatorio: que el escrutinio corrija al preconteo es su función.")
    print("Estas mesas son CANDIDATAS A REVISIÓN, no hallazgos de fraude. Para saber")
    print("cuál de los dos conteos acierta hay que ir al acta E-14 escaneada.")


def main():
    ap = argparse.ArgumentParser(description="Auditoría preconteo vs escrutinio (datos oficiales MMV)")
    ap.add_argument("carpeta", help="carpeta de la ronda, p.ej. data/manifests/MMV_2V/MMV_Presidente2V_2026")
    ap.add_argument("--out", default="auditoria_oficial")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    auditar(a.carpeta, a.out, a.top)


if __name__ == "__main__":
    main()
