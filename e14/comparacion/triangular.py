#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X2 · Triangulación de los TRES ejemplares del acta, contra el papel.

Cada mesa se levanta por triplicado: DELEGADOS, TRANSMISIÓN y CLAVEROS. Si los
tres ejemplares deberían decir lo mismo y uno dice otra cosa, ese ejemplar
divergente es el candidato a revisión — **sin necesidad de saber cuál acierta**.

Es la señal que la aritmética NO puede ver: mover un voto de un candidato a otro
deja el total intacto, así que ninguna suma lo delata. Sólo comparar ejemplares
lo revela.

### Por qué esto es fiable ahora y antes no

El clasificador se entrenó **sólo con CLAVEROS** (JPEG color a 300 dpi), mientras
DELEGADOS y TRANSMISIÓN son PNG **binarizados de 1 bit** a ~860 px. Había motivo
para temer que leyera mal los dos que nunca vio. Medido sobre 60 mesas presentes
en los tres árboles, contra el escrutinio oficial:

| Ejemplar | Acierto por casilla |
|---|---|
| CLAVEROS | 98,0 % |
| DELEGADOS | 97,3 % |
| TRANSMISIÓN | 95,3 % |

Generaliza. (`validar_ocr()` reproduce esta medición.)

### ⚠️ El voto mayoritario 2-vs-1 NO es fiable aquí

Parece natural que si dos ejemplares coinciden y uno difiere, el discrepante sea
el sospechoso. **Es falso en este corpus**, porque el voto mayoritario supone que
los errores son independientes y aquí no lo son:

DELEGADOS y TRANSMISIÓN son **ambos binarizados de 1 bit**, comparten el mismo
modo de fallo y se equivocan igual. CLAVEROS es JPEG a color. Medido en Turbo:

| Mesa | CLAVEROS | DELEGADOS | TRANSMISIÓN | Oficial |
|---|---|---|---|---|
| 6 | **121** | 21 | 21 | **121** |
| 15 | **119** | 19 | 19 | **119** |

Los dos binarizados pierden el dígito de **centenas** y forman una "mayoría"
falsa; el oficial confirma que el discrepante (CLAVEROS) era el que acertaba.

Por eso el árbitro no es la mayoría: es el **escrutinio oficial**, que es
independiente del papel y está verificado por SHA-256. La columna
`coincide_oficial` dice qué ejemplares concuerdan con él, y `sospechoso` marca
al que se aparta.

### La confianza CLASIFICA, no descarta

Primera versión de este módulo descartaba toda divergencia cuya lectura no
superase un umbral de confianza. **Era un error**: una casilla retocada,
sobreescrita o emborronada hace **dudar al modelo precisamente por estar
alterada**, así que filtrar por confianza alta elimina justo los casos que se
buscan. En las 4 mesas de Turbo descartaba las 24 casillas, incluida una
divergencia real.

Ahora la confianza **ordena** en vez de filtrar:

  - `ALTA`  (≥ 0,90) — el modelo está seguro; una divergencia aquí es sólida.
  - `MEDIA` (0,70–0,90)
  - `BAJA`  (< 0,70) — puede ser ruido del OCR **o** una casilla difícil de leer
    porque está alterada. Hay que mirarla, no tirarla.

Con el OCR al ~97 % por casilla habrá errores de lectura entre las divergencias:
por eso el nivel va en el CSV y la revisión humana empieza por las de `ALTA`.

Uso:
    python -m e14.comparacion.triangular \\
        --claveros    data/segunda_vuelta/e14_pdfs_claveros \\
        --delegados   data/segunda_vuelta/e14_pdfs_2v \\
        --transmision data/segunda_vuelta/e14_pdfs_2v_t \\
        --mmv         data/manifests/MMV_2V/MMV_Presidente2V_2026 \\
        --modelo      models/digitnet_2v_relleno.pt \\
        --limite 2000 --out data/segunda_vuelta/_triangulacion/tri_2v
"""
from __future__ import annotations
import argparse, csv, sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ / "extraccion"))

from e14.oficial import mmv                                   # noqa: E402
from e14.ocr.dataset_oficial import interpretar, MAPA_CASILLA  # noqa: E402

EJEMPLARES = ("CLAVEROS", "DELEGADOS", "TRANSMISION")
CASILLAS_CAND = ("CANDIDATO_01", "CANDIDATO_02")


# -------------------------------- localizar ----------------------------------
def _acta_claveros(carpeta: Path, k) -> Path | None:
    """Localiza el acta de CLAVEROS de la mesa k dentro de su carpeta.

    NO se puede usar un glob tipo `*_{mesa:03d}_*.pdf`: el nombre es
    `E14_PRE_dep_muni_ZONA_tok_puesto_MESA_id.pdf` y la **zona también va en 3
    dígitos**, así que en la zona 003 ese patrón matchea TODAS las mesas y
    `sorted()[0]` devuelve la 001. Ese error hizo comparar mesas equivocadas en
    Turbo. Se resuelve parseando cada nombre y comparando la clave completa."""
    import posiciones_2v as P
    if not carpeta.is_dir():
        return None
    for p in sorted(carpeta.glob("*.pdf")):
        try:
            if mmv.clave_mesa(*P.parsear_clave(p)) == k:
                return p
        except Exception:
            continue
    return None


def rutas_de_mesa(k, dirs) -> dict:
    """{ejemplar: pdf} para la mesa k, sólo con los ejemplares que existan."""
    dep, muni, zona, puesto, mesa = k
    out = {}
    d = Path(dirs["CLAVEROS"]) / "docs" / "E14" / f"{dep:02d}" / f"{muni:03d}" / f"{zona:02d}" / puesto
    a = _acta_claveros(d, k)
    if a:
        out["CLAVEROS"] = a
    for nom in ("DELEGADOS", "TRANSMISION"):
        if nom not in dirs:
            continue
        d = (Path(dirs[nom]) / "PRE" / f"{dep:02d}" / f"{muni:03d}" /
             f"{zona:03d}" / puesto / f"{mesa:03d}")
        g = sorted(d.glob("*.pdf")) if d.is_dir() else []
        if g:
            out[nom] = g[0]
    return out


# --------------------------------- lectura -----------------------------------
def leer_acta(pdf, red, dev, casillas=None):
    """{casilla: (valor, confianza_minima)}. None si el acta no se puede recortar."""
    import torch
    from e14.ocr.dataset_color import cajas_de_acta
    from e14.ocr.clasificador_color import a_gris
    cajas = cajas_de_acta(pdf)
    if len(cajas) != 9:
        return None
    noms = [c for c in (casillas or MAPA_CASILLA) if c in cajas]
    if not noms:
        return None
    plano = np.stack([c for x in noms for c in cajas[x]])
    xb = torch.from_numpy(a_gris(plano)).permute(0, 3, 1, 2).float().div(255).to(dev)
    with torch.no_grad():
        pr = torch.softmax(red(xb), 1).cpu().numpy()
    cls, conf = pr.argmax(1), pr.max(1)
    return {noms[i]: (interpretar(cls[3*i:3*i+3]), float(conf[3*i:3*i+3].min()))
            for i in range(len(noms))}


# -------------------------------- validación ---------------------------------
def validar_ocr(dirs, esc, por_cod, red, dev, n=60):
    """Acierto por casilla de CADA ejemplar contra el escrutinio oficial.

    Sin esto no se puede interpretar una divergencia: si un ejemplar se lee peor
    que los otros, aportará divergencias falsas en proporción a su error."""
    res = {e: [0, 0] for e in EJEMPLARES}
    pdfs = [p for p in Path(dirs["CLAVEROS"]).rglob("*.pdf") if "_logs" not in p.parts][:n]
    import posiciones_2v as P
    for pdf in pdfs:
        try:
            k = mmv.clave_mesa(*P.parsear_clave(pdf))
            if k not in esc:
                continue
            rutas = rutas_de_mesa(k, dirs)
            if len(rutas) < 3:
                continue
            of = valores_oficiales(esc[k], por_cod)
            for nom, rp in rutas.items():
                lec = leer_acta(rp, red, dev)
                if not lec:
                    continue
                for cas, v in of.items():
                    if v and cas in lec:
                        res[nom][1] += 1
                        res[nom][0] += (lec[cas][0] == v)
        except Exception:
            pass
    return {e: (ok / t if t else 0.0, t) for e, (ok, t) in res.items()}


def valores_oficiales(votos_mesa, por_cod) -> dict:
    o = {}
    for cas, (tipo, dato) in MAPA_CASILLA.items():
        if tipo == "codigo":
            cod = por_cod.get(dato)
            o[cas] = votos_mesa.get(cod, 0) if cod else 0
        elif tipo == "fijo":
            o[cas] = votos_mesa.get(dato, 0)
    o["SUMA_TOTAL"] = sum(v for c, v in o.items() if c != "SUMA_TOTAL")
    return o


# ------------------------------- triangulación --------------------------------
def triangular(claveros, delegados, transmision, carpeta_mmv, modelo, out,
               limite=None, desde=0, conf_min=0.90, solo_candidatos=True,
               dev="cuda", validar=True, mesas=None):
    from e14.ocr.clasificador_color import cargar
    import posiciones_2v as P

    dirs = {"CLAVEROS": claveros}
    if delegados:
        dirs["DELEGADOS"] = delegados
    if transmision:
        dirs["TRANSMISION"] = transmision

    f = mmv.localizar(carpeta_mmv)
    esc = mmv.cargar_escrutinio(f["escrutinio"])
    cand = mmv.cargar_candidatos(f["candidatos"]) if "candidatos" in f else {}
    tot = defaultdict(int)
    for v in esc.values():
        for c, n in v.items():
            tot[c] += n
    por_cod = {c[1]: c for c, v in tot.items() if mmv.es_candidato(c) and v > 0}

    red, dev = cargar(modelo, dev)
    n_clases = red.f[-1].out_features
    print(f"modelo: {Path(modelo).name} ({n_clases} clases)   confianza mínima: {conf_min}")

    if validar:
        print("\nvalidando el OCR en los tres ejemplares (contra el escrutinio oficial)...")
        v = validar_ocr(dirs, esc, por_cod, red, dev)
        for e, (acc, n) in v.items():
            print(f"  {e:12s} {acc:.1%}  ({n:,} casillas)")
        print("  -> una divergencia sólo es informativa si los ejemplares se leen")
        print("     con calidad parecida; si no, el peor aporta falsos positivos.")

    casillas = CASILLAS_CAND if solo_candidatos else None
    if mesas:
        claves = [mmv.clave_mesa(*m.split("/")) for m in mesas]
    else:
        pdfs = [p for p in Path(claveros).rglob("*.pdf") if "_logs" not in p.parts]
        pdfs = pdfs[desde: desde + limite if limite else None]
        claves = []
        for p in pdfs:
            try:
                claves.append(mmv.clave_mesa(*P.parsear_clave(p)))
            except Exception:
                pass

    print(f"\nmesas a triangular: {len(claves):,}")
    filas, conteo = [], Counter()
    for i, k in enumerate(claves, 1):
        rutas = rutas_de_mesa(k, dirs)
        if len(rutas) < 2:
            conteo["MENOS_DE_2_EJEMPLARES"] += 1
            continue
        lect = {}
        for nom, rp in rutas.items():
            try:
                l = leer_acta(rp, red, dev, casillas)
                if l:
                    lect[nom] = l
            except Exception:
                pass
        if len(lect) < 2:
            conteo["ERROR_LECTURA"] += 1
            continue

        of = valores_oficiales(esc[k], por_cod) if k in esc else {}
        for cas in (casillas or MAPA_CASILLA):
            vals = {e: l[cas] for e, l in lect.items() if cas in l}
            if len(vals) < 2:
                continue
            cmin = min(c for _, c in vals.values())
            nivel = "ALTA" if cmin >= conf_min else ("MEDIA" if cmin >= 0.70 else "BAJA")
            distintos = {v for v, _ in vals.values()}
            if len(distintos) == 1:
                conteo[f"COINCIDEN_{nivel}"] += 1
                continue
            # El árbitro es el escrutinio OFICIAL, no la mayoría de los papeles
            # (ver la nota sobre el voto 2-vs-1 en el docstring).
            cnt = Counter(v for v, _ in vals.values())
            may, n_may = cnt.most_common(1)[0]
            vof = of.get(cas)
            con_oficial = [e for e, (v, _) in vals.items() if vof is not None and v == vof]
            sospechoso = ([e for e, (v, _) in vals.items() if vof is not None and v != vof]
                          if con_oficial else [])
            if vof is None:
                tipo = "SIN_OFICIAL"
            elif not con_oficial:
                # ningún ejemplar coincide con el oficial -> casi seguro fallo de OCR
                tipo = "NINGUNO_COINCIDE_OFICIAL"
            elif len(sospechoso) == 1:
                tipo = "UN_EJEMPLAR_SE_APARTA"
            else:
                tipo = "VARIOS_SE_APARTAN"
            conteo[f"{tipo}_{nivel}"] += 1
            fila = {"dep": k[0], "muni": k[1], "zona": k[2], "puesto": k[3], "mesa": k[4],
                    "casilla": cas, "tipo": tipo,
                    "oficial": vof if vof is not None else "",
                    "coincide_oficial": "|".join(con_oficial),
                    "sospechoso": "|".join(sospechoso),
                    "mayoria_papeles": may if n_may >= 2 else "",
                    "confianza": nivel, "conf_min": round(cmin, 3)}
            for e in EJEMPLARES:
                fila[e] = vals[e][0] if e in vals else ""
            filas.append(fila)
        if i % 200 == 0:
            print(f"  {i}/{len(claves)}  divergencias={len(filas)}")

    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    if filas:
        # las de confianza ALTA primero: por ahí empieza la revisión humana
        orden = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
        filas.sort(key=lambda r: (orden[r["confianza"]], -r["conf_min"]))
        cols = list(filas[0].keys())
        with open(f"{out}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader(); w.writerows(filas)

    print(f"\n=== RESULTADO ===")
    for t, n in conteo.most_common():
        print(f"  {t:24s} {n:,}")
    coin = sum(v for t, v in conteo.items() if t.startswith("COINCIDEN_"))
    div = sum(v for t, v in conteo.items()
              if t.split("_")[0] in ("UN", "VARIOS", "NINGUNO", "SIN")
              and not t.startswith("SIN_OFICIAL_"))
    div += sum(v for t, v in conteo.items() if t.startswith("SIN_OFICIAL_"))
    comp = coin + div
    if comp:
        print(f"\ncasillas comparadas: {comp:,}")
        print(f"  coinciden los ejemplares : {coin:,} ({100*coin/comp:.2f} %)")
        print(f"  DIVERGEN                 : {div:,} ({100*div/comp:.2f} %)")
        print("\n  divergencias, arbitradas por el ESCRUTINIO OFICIAL:")
        etiq = {"UN_EJEMPLAR_SE_APARTA": "un ejemplar se aparta del oficial  <- LO INTERESANTE",
                "VARIOS_SE_APARTAN": "varios se apartan del oficial",
                "NINGUNO_COINCIDE_OFICIAL": "ninguno coincide  <- casi seguro fallo de OCR",
                "SIN_OFICIAL": "sin dato oficial para arbitrar"}
        for base, txt in etiq.items():
            for niv in ("ALTA", "MEDIA", "BAJA"):
                n = conteo.get(f"{base}_{niv}", 0)
                if n:
                    print(f"    {txt:52s} {niv:6s} {n:,}")
    if filas:
        print(f"\nCSV: {out}.csv")
    print("\nLo que merece revisión humana son las de `UN_EJEMPLAR_SE_APARTA` con")
    print("confianza ALTA: un ejemplar dice algo distinto del oficial y de los otros")
    print("dos, y el modelo lo leyó seguro. Aun así NO es fraude: puede ser un error")
    print("del jurado al copiar el acta. Hay que mirar el papel.")
    return filas


def main():
    ap = argparse.ArgumentParser(description="X2 · triangulación de los tres ejemplares")
    ap.add_argument("--claveros", required=True)
    ap.add_argument("--delegados", default=None)
    ap.add_argument("--transmision", default=None)
    ap.add_argument("--mmv", required=True)
    ap.add_argument("--modelo", default="models/digitnet_2v_relleno.pt")
    ap.add_argument("--out", default="triangulacion")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--desde", type=int, default=0)
    ap.add_argument("--conf-min", type=float, default=0.90,
                    help="umbral para etiquetar una divergencia como ALTA (no descarta nada)")
    ap.add_argument("--todas-las-casillas", dest="solo_candidatos", action="store_false",
                    help="comparar las 6 casillas, no sólo los dos candidatos")
    ap.add_argument("--sin-validar", dest="validar", action="store_false")
    ap.add_argument("--mesa", action="append", dest="mesas",
                    help="repetible: dep/muni/zona/puesto/mesa (p.ej. 01/280/03/01/002)")
    ap.add_argument("--dev", default="cuda")
    a = ap.parse_args()
    triangular(a.claveros, a.delegados, a.transmision, a.mmv, a.modelo, a.out,
               a.limite, a.desde, a.conf_min, a.solo_candidatos, a.dev, a.validar, a.mesas)


if __name__ == "__main__":
    main()
