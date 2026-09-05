#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dirimir contra el PAPEL las mesas que señala `auditar.py`.

Cuando el preconteo y el escrutinio discrepan en una mesa, sólo el acta E-14
escaneada dice cuál de los dos coincide con lo que firmaron los jurados. Este
módulo va al papel y lo resuelve, dejando la evidencia servida para revisión
humana.

### Por qué NO se limita a "leer el acta y comparar"

Aunque el OCR acierta el 96,9 % de las casillas, leer a ciegas y comparar sigue
siendo más frágil que necesario: aquí el problema es más fácil, porque **no hay
que leer un número libre, hay que decidir entre DOS hipótesis conocidas**. Eso permite usar la
distribución de probabilidad completa del clasificador en vez del `argmax`:

    log L(preconteo)  = Σ log P(dígito que el preconteo predice en esa posición)
    log L(escrutinio) = Σ log P(dígito que el escrutinio predice en esa posición)

y quedarse con la diferencia. Un modelo que duda entre dos dígitos concretos
sigue siendo informativo si uno de ellos es el de una hipótesis y el otro no.
El resultado además viene con una medida natural de confianza (el margen entre
las dos log-verosimilitudes), no con un sí/no de credibilidad desconocida.

### Qué posiciones se comparan

Sólo las **discriminantes**: aquellas donde las dos hipótesis predicen dígitos
distintos. Las que coinciden no aportan nada a la decisión.

Con el modelo de **11 clases** (`digitnet_2v_relleno.pt`, el de por defecto) se
usan las tres posiciones. Con el viejo de 10 se descartaban las CENTENAS cuando
algún valor era < 100, porque ahí va el **aspa (✱)** de anulación y ese modelo la
leía como `7`: incluirla metía ruido justo en la posición de más peso. El modelo
nuevo la lee como RELLENO, así que la exclusión ya no hace falta y se recupera la
posición más discriminante (ver docs/OCR_2V.md).

### Veredicto conservador

Si el margen entre hipótesis no supera `--umbral`, el veredicto es
`REVISAR_A_MANO`, no un empate forzado. El objetivo es una cola corta y fiable
para un humano, no un dictamen automático.

Uso:
    python -m e14.oficial.dirimir \
        --auditoria data/segunda_vuelta/_oficial/auditoria_2v.mesas.csv \
        --mmv       data/manifests/MMV_2V/MMV_Presidente2V_2026 \
        --actas     data/segunda_vuelta/e14_pdfs_claveros \
        --modelo    models/digitnet_2v_relleno.pt \
        --tipologias PERMUTACION,ANULADA \
        --out       data/segunda_vuelta/_oficial/dirimidas_2v
"""
from __future__ import annotations
import argparse, csv, math, sys
from pathlib import Path

import numpy as np

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ / "extraccion"))

from e14.oficial import mmv                       # noqa: E402

# La casilla CANDIDATO_0N del acta corresponde al candidato de CÓDIGO N, que es
# el número impreso junto a su foto en el formulario — NO al N-ésimo por
# votación. En 2da vuelta el código 1 es Cepeda (Pacto Histórico, fila 1 del
# acta) y el 2 es De la Espriella, mientras que por votación el orden es el
# inverso. Mapear por votación invertía las dos hipótesis y habría dado todos
# los veredictos al revés.
CASILLA_DE_ORDEN = ["CANDIDATO_01", "CANDIDATO_02"]


# ------------------------------- verosimilitud -------------------------------
def clases_de_valor(valor: int, n_clases: int) -> list[int]:
    """Valor -> la clase que el modelo debería predecir en cada posición.

    Con 11 clases las posiciones sin dígito son RELLENO (el modelo sabe leer el
    aspa); con 10 se rellenan con ceros a la izquierda, que es lo único que el
    modelo viejo podía representar."""
    if n_clases > 10:
        from e14.ocr.dataset_oficial import etiquetas_de_valor, RELLENO
        et = etiquetas_de_valor(valor)
        return et if et is not None else [RELLENO] * 3
    return [int(c) for c in f"{valor:03d}"]


def posiciones_discriminantes(v1: int, v2: int, n_clases: int = 10) -> list[int]:
    """Índices (0=centenas,1=decenas,2=unidades) donde las dos hipótesis
    difieren y la lectura es informativa.

    Con el modelo de 10 clases había que **descartar las centenas** cuando algún
    valor era < 100: ahí va el aspa de anulación, que el modelo leía como `7`, y
    usar esa posición metía ruido sistemático justo donde más pesa.

    Con 11 clases esa exclusión sobra —el aspa es la clase RELLENO— y de hecho
    conviene quitarla: recupera la posición de mayor peso para discriminar."""
    c1, c2 = clases_de_valor(v1, n_clases), clases_de_valor(v2, n_clases)
    out = [i for i in range(3) if c1[i] != c2[i]]
    if n_clases <= 10:
        out = [i for i in out if not (i == 0 and (v1 < 100 or v2 < 100))]
    return out


def log_verosimilitud(probs: np.ndarray, valor: int, posiciones: list[int],
                      n_clases: int = 10) -> float:
    """log P(el papel muestre `valor`) según el clasificador, sobre `posiciones`.
    probs: (3, n_clases) para las tres posiciones de una casilla."""
    c = clases_de_valor(valor, n_clases)
    return sum(math.log(max(1e-12, probs[i][c[i]])) for i in posiciones)


# --------------------------------- proceso -----------------------------------
def dirimir(auditoria, carpeta_mmv, dir_actas, modelo, out, tipologias,
            umbral=2.0, limite=None, evidencia=True, dev="cuda", n_clases=None):
    import torch, cv2
    import posiciones_2v as P
    from e14.ocr.dataset_color import cajas_de_acta
    from e14.ocr.clasificador_color import cargar, a_gris

    tipos = {t.strip().upper() for t in tipologias.split(",") if t.strip()}
    filas = [r for r in csv.DictReader(open(auditoria, encoding="utf-8"))
             if not tipos or r["tipologia"].upper() in tipos]
    if limite:
        filas = filas[:limite]
    print(f"mesas a dirimir: {len(filas):,}  (tipologías: {sorted(tipos) or 'todas'})")

    f = mmv.localizar(carpeta_mmv)
    cand = mmv.cargar_candidatos(f["candidatos"]) if "candidatos" in f else {}
    pre = mmv.cargar_preconteo(f["preconteo"])
    esc = mmv.cargar_escrutinio(f["escrutinio"])

    tot = {}
    for v in esc.values():
        for c, n in v.items():
            tot[c] = tot.get(c, 0) + n
    # indexado por CÓDIGO de candidato (el número del acta), no por votación
    por_codigo = {c[1]: c for c, v in tot.items() if mmv.es_candidato(c) and v > 0}
    personas = [por_codigo.get(n + 1) for n in range(len(CASILLA_DE_ORDEN))]
    if any(p is None for p in personas):
        raise SystemExit(f"No encuentro los candidatos de código 1 y 2; "
                         f"códigos presentes: {sorted(por_codigo)}")
    print("mapeo casilla del acta -> candidato:")
    for nom, cod in zip(CASILLA_DE_ORDEN, personas):
        print(f"  {nom} = código {cod[1]} = {mmv.nombre_de(cod, cand)}")

    red, dev = cargar(modelo, dev, n_clases)
    n_clases = red.f[-1].out_features          # el que realmente tiene el modelo
    print(f"modelo: {Path(modelo).name}  ({n_clases} clases"
          + ("  con RELLENO -> se usan las centenas)" if n_clases > 10
             else "  sin RELLENO -> se descartan las centenas con aspa)"))
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    dir_ev = Path(f"{out}_evidencia");
    if evidencia:
        dir_ev.mkdir(parents=True, exist_ok=True)

    resultados, conteo = [], {}
    for i, r in enumerate(filas, 1):
        dep, muni, zona = int(r["dep"]), int(r["muni"]), int(r["zona"])
        puesto, mesa = r["puesto"], int(r["mesa"])
        k = (dep, muni, zona, puesto, mesa)

        # localizar el acta en el árbol de CLAVEROS.
        # OJO: no vale `*_{mesa:03d}_*.pdf` — la ZONA también va en 3 dígitos en
        # el nombre, así que en la zona 003 ese patrón matchea todas las mesas y
        # devuelve la primera. Hay que comparar la clave parseada.
        from e14.comparacion.triangular import _acta_claveros
        d = Path(dir_actas) / "docs" / "E14" / f"{dep:02d}" / f"{muni:03d}" / f"{int(zona):02d}" / puesto
        a = _acta_claveros(d, k)
        cands = [a] if a else []
        base = {"dep": dep, "muni": muni, "zona": zona, "puesto": puesto, "mesa": mesa,
                "tipologia": r["tipologia"], "impacto_votos": r["impacto_votos"]}
        if not cands:
            resultados.append({**base, "veredicto": "ACTA_NO_ENCONTRADA"})
            conteo["ACTA_NO_ENCONTRADA"] = conteo.get("ACTA_NO_ENCONTRADA", 0) + 1
            continue

        pdf = cands[0]
        try:
            cajas = cajas_de_acta(pdf)
            if len(cajas) != 9:
                raise ValueError("recorte incompleto")
            nombres, lote = [], []
            for nom in CASILLA_DE_ORDEN:
                for c in cajas[nom]:
                    nombres.append(nom); lote.append(c)
            x = torch.from_numpy(a_gris(np.stack(lote))).permute(0, 3, 1, 2).float().div(255).to(dev)
            with torch.no_grad():
                pr = torch.softmax(red(x), 1).cpu().numpy()
        except Exception as exc:
            resultados.append({**base, "veredicto": f"ERROR_LECTURA"})
            conteo["ERROR_LECTURA"] = conteo.get("ERROR_LECTURA", 0) + 1
            continue

        # candidato i-ésimo del acta <-> i-ésimo de `personas` (orden de votación)
        lp = le = 0.0
        n_pos = 0
        detalle = {}
        for idx, nom in enumerate(CASILLA_DE_ORDEN):
            if idx >= len(personas):
                break
            cod = personas[idx]
            vp, ve = pre[k].get(cod, 0), esc[k].get(cod, 0)
            probs = pr[3*idx:3*idx+3]
            pos = posiciones_discriminantes(vp, ve, n_clases)
            n_pos += len(pos)
            if pos:
                lp += log_verosimilitud(probs, vp, pos, n_clases)
                le += log_verosimilitud(probs, ve, pos, n_clases)
            detalle[f"pre_{nom}"] = vp
            detalle[f"esc_{nom}"] = ve
            if n_clases > 10:
                from e14.ocr.dataset_oficial import interpretar
                detalle[f"leido_{nom}"] = interpretar(probs.argmax(1))
            else:
                detalle[f"leido_{nom}"] = int("".join(str(d) for d in probs.argmax(1)))

        if r["tipologia"].upper() == "ANULADA":
            # En una mesa ANULADA el escrutinio pone 0/0 y el papel muestra los
            # votos que se emitieron: el papel "coincide con el preconteo" SIEMPRE,
            # por construcción, y compararlos no informa de nada. Anular es una
            # decisión JURÍDICA (causal de nulidad), no una corrección de lectura;
            # lo que habría que revisar es la constancia de la página 2 del acta,
            # no los números. Se registra el total emitido y se deja fuera del
            # recuento de aciertos.
            ver = "ANULADA_NO_DIRIMIBLE"
        elif n_pos == 0:
            ver = "SIN_POSICION_DISCRIMINANTE"
        else:
            margen = lp - le
            if abs(margen) < umbral:
                ver = "REVISAR_A_MANO"
            elif margen > 0:
                ver = "COINCIDE_PRECONTEO"
            else:
                ver = "COINCIDE_ESCRUTINIO"
        conteo[ver] = conteo.get(ver, 0) + 1
        resultados.append({**base, **detalle, "veredicto": ver,
                           "margen_log": round(lp - le, 2) if n_pos else "",
                           "posiciones_usadas": n_pos, "acta": str(pdf)})

        if evidencia:
            try:
                celdas = P.recortar_celdas(pdf, color=True)
                tiras = []
                for idx, nom in enumerate(CASILLA_DE_ORDEN):
                    c = cv2.resize(celdas[nom], (430, 95))
                    lab = np.full((95, 300, 3), 255, np.uint8)
                    cod = personas[idx] if idx < len(personas) else None
                    cv2.putText(lab, mmv.nombre_de(cod, cand)[:22] if cod else nom,
                                (3, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1)
                    cv2.putText(lab, f"preconteo: {detalle[f'pre_{nom}']}",
                                (3, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 0, 0), 1)
                    cv2.putText(lab, f"escrutinio: {detalle[f'esc_{nom}']}",
                                (3, 84), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 120, 0), 1)
                    tiras.append(np.hstack([lab, c]))
                enc = np.full((34, 730, 3), 255, np.uint8)
                cv2.putText(enc, f"{dep}/{muni}/{zona}/{puesto}/{mesa}  {r['tipologia']}  -> {ver}",
                            (4, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
                cv2.imwrite(str(dir_ev / f"{dep:02d}_{muni:03d}_{zona:02d}_{puesto}_{mesa:03d}.png"),
                            np.vstack([enc] + tiras))
            except Exception:
                pass

        if i % 10 == 0:
            print(f"  {i}/{len(filas)}")

    # ------------------------------ reporte ----------------------------------
    if resultados:
        cols = sorted({c for r in resultados for c in r}, key=lambda c: (c != "veredicto", c))
        with open(f"{out}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader(); w.writerows(resultados)

    print(f"\n=== VEREDICTOS ({len(resultados)} mesas) ===")
    for v, n in sorted(conteo.items(), key=lambda kv: -kv[1]):
        print(f"  {v:28s} {n:>4}")
    anul = [r for r in resultados if r.get("veredicto") == "ANULADA_NO_DIRIMIBLE"]
    if anul:
        votos = sum(int(r["impacto_votos"]) for r in anul)
        print(f"\n{len(anul)} mesas ANULADAS ({votos:,} votos emitidos) quedan fuera del")
        print("recuento: el escrutinio las pone en 0 y el papel muestra los votos, así que")
        print("'coincide con el preconteo' es cierto por definición. Anular es una decisión")
        print("jurídica — para revisarlas hay que leer la constancia (página 2 del acta).")

    ce = conteo.get("COINCIDE_ESCRUTINIO", 0); cp = conteo.get("COINCIDE_PRECONTEO", 0)
    if ce + cp:
        print(f"\nDe las {ce+cp} mesas DIRIMIBLES: el papel respalda al ESCRUTINIO en {ce} "
              f"({100*ce/(ce+cp):.0f}%) y al PRECONTEO en {cp} ({100*cp/(ce+cp):.0f}%).")
        print("Que el escrutinio gane es lo esperado: su función es corregir el preconteo.")
        if cp:
            print(f"\nLas {cp} donde el papel respalda al PRECONTEO son las que merecen")
            print("revisión humana — ahí el escrutinio se apartó del acta:")
            for r in resultados:
                if r.get("veredicto") == "COINCIDE_PRECONTEO":
                    print(f"  {r['dep']}/{r['muni']}/{r['zona']}/{r['puesto']}/{r['mesa']}  "
                          f"{r['tipologia']}  impacto={r['impacto_votos']} votos  "
                          f"margen={r.get('margen_log')}")
    print(f"\nCSV: {out}.csv" + (f"   |   evidencia: {dir_ev}/" if evidencia else ""))
    print("\nEl veredicto es una AYUDA, no un dictamen: el OCR se equivoca. Antes de")
    print("usar cualquier caso, mirar el PNG de evidencia y confirmarlo a ojo.")


def main():
    ap = argparse.ArgumentParser(description="Dirime contra el acta E-14 las mesas señaladas por auditar.py")
    ap.add_argument("--auditoria", required=True, help="*.mesas.csv de e14.oficial.auditar")
    ap.add_argument("--mmv", required=True, help="carpeta MMV de la ronda")
    ap.add_argument("--actas", required=True, help="árbol de PDFs de CLAVEROS")
    ap.add_argument("--modelo", default="models/digitnet_2v_relleno.pt",
                    help="por defecto el de 11 clases (con RELLENO), que lee las aspas")
    ap.add_argument("--n-clases", type=int, default=None,
                    help="por defecto se deduce del checkpoint")
    ap.add_argument("--tipologias", default="PERMUTACION,ANULADA")
    ap.add_argument("--out", required=True, help="prefijo de salida (CSV + carpeta de evidencia)")
    ap.add_argument("--umbral", type=float, default=2.0,
                    help="margen mínimo de log-verosimilitud para dictaminar (default 2.0 ~ 7x más probable)")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--sin-evidencia", dest="evidencia", action="store_false")
    ap.add_argument("--dev", default="cuda")
    a = ap.parse_args()
    dirimir(a.auditoria, a.mmv, a.actas, a.modelo, a.out, a.tipologias,
            a.umbral, a.limite, a.evidencia, a.dev, a.n_clases)


if __name__ == "__main__":
    main()
