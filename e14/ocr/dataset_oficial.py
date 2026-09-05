#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dataset de dígitos etiquetado con el ESCRUTINIO OFICIAL como verdad.

Resuelve el cuello de botella documentado en `docs/OCR_2V.md`: el clasificador
no tiene clase para el **aspa (✱)** de anulación y la lee como `7` con
confianza alta, en el 16,3 % de las casillas. Medido contra el escrutinio
oficial, el acierto exacto por casilla es del **83 %**, y casi todo el 17 %
restante es ese mismo error (`794`→94, `744`→44, `788`→88).

### Por qué esto sustituye al autoetiquetado por aritmética

`dataset_color.py` etiqueta con las actas cuya aritmética cuadra, o sea
justamente donde el modelo **ya acertaba**: es ciego a su propio error
sistemático, y por eso el bootstrapping se agotó (+2 puntos con 4,7x más datos).

Aquí las etiquetas vienen de **fuera del modelo**: los archivos oficiales MMV,
verificados por SHA-256. Eso rompe la circularidad, y de paso cubre justo las
casillas donde están las aspas (BLANCO / NULO / NO_MARCADO).

### La clase RELLENO

En vez de distinguir `aspa` / `guion` / `cero de relleno` —que exigiría
etiquetado manual y además **no hace falta**— se usa una sola clase para
"esta posición no aporta dígito":

    valor  94 -> ["RELLENO", "9", "4"]      (el papel muestra ✱94, o 094)
    valor 106 -> ["1", "0", "6"]            (el 0 del medio SÍ es significativo)
    valor   7 -> ["RELLENO", "RELLENO", "7"]

Al leer: se descartan los RELLENO de la izquierda y se concatena el resto.
Un aspa y un cero de relleno significan lo mismo para el valor, así que
distinguirlos no aporta nada y sí costaría etiquetas.

**Se excluye el valor 0**: se escribe indistintamente `✱✱✱`, `000` o `✱✱0`, y
no hay forma de saber cuál sin mirar. Meterlo introduciría ruido.

### Qué casillas se pueden etiquetar

El escrutinio da 5 de las 9 casillas del acta. SUMA_TOTAL se deriva sumándolas.
TOTAL_E11 / TOTAL_URNA / TOTAL_INCINERADOS no están y se quedan fuera.

Uso:
    python -m e14.ocr.dataset_oficial construir \\
        --actas data/segunda_vuelta/e14_pdfs_claveros \\
        --mmv   data/manifests/MMV_2V/MMV_Presidente2V_2026 \\
        --salida data/segunda_vuelta/digitos_oficial.npz --limite 15000
"""
from __future__ import annotations
import argparse, sys
from collections import Counter
from pathlib import Path

import numpy as np
import cv2

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ / "extraccion"))

import posiciones_2v as P                     # noqa: E402
from e14.oficial import mmv                   # noqa: E402
from e14.ocr.dataset_color import cajas_de_acta   # noqa: E402

RELLENO = 10
VOCAB = [str(d) for d in range(10)] + ["RELLENO"]

# casilla del acta -> código oficial. CANDIDATO_0N es el candidato de CÓDIGO N
# (el número impreso junto a su foto), no el N-ésimo por votación.
MAPA_CASILLA = {
    "CANDIDATO_01": ("codigo", 1),
    "CANDIDATO_02": ("codigo", 2),
    "BLANCO":       ("fijo", (0, 996)),
    "NULO":         ("fijo", (0, 997)),
    "NO_MARCADO":   ("fijo", (0, 998)),
    "SUMA_TOTAL":   ("derivado", None),      # suma de las cinco anteriores
}


def etiquetas_de_valor(valor: int) -> list[int] | None:
    """Valor entero -> 3 etiquetas por posición. None si no es etiquetable."""
    if valor <= 0 or valor > 999:
        return None                 # 0 es ambiguo (✱✱✱ / 000); >999 no cabe
    s = str(valor)
    return [RELLENO] * (3 - len(s)) + [int(c) for c in s]


def interpretar(clases) -> int:
    """Inverso: 3 clases -> valor. Descarta RELLENO y concatena el resto."""
    digs = [c for c in clases if c != RELLENO]
    return int("".join(str(d) for d in digs)) if digs else 0


def construir(dir_actas, carpeta_mmv, salida, limite=None, desde=0,
              solo_estables=True, gris=True):
    """`gris=True` (por defecto) guarda las cajas en 1 canal en vez de 3.

    El color está descartado por medición (empeora ~4 puntos, ver
    docs/FORENSE_COLOR.md), así que guardar 3 canales idénticos sólo gasta
    memoria. Con 1 canal el corpus COMPLETO (118.337 actas, ~1,68 M cajas) ocupa
    3,9 GB en vez de 11,6 GB — y sin la copia que hacía `a_gris()`, que llevaba
    el pico a 23,2 GB sobre una máquina de 23 GB."""
    f = mmv.localizar(carpeta_mmv)
    esc = mmv.cargar_escrutinio(f["escrutinio"])
    pre = mmv.cargar_preconteo(f["preconteo"]) if solo_estables else {}
    tot = Counter()
    for v in esc.values():
        for c, n in v.items():
            tot[c] += n
    por_codigo = {c[1]: c for c, v in tot.items() if mmv.es_candidato(c) and v > 0}

    pdfs = [p for p in Path(dir_actas).rglob("*.pdf") if "_logs" not in p.parts]
    pdfs = pdfs[desde: desde + limite if limite else None]
    print(f"actas a procesar: {len(pdfs):,}")
    if solo_estables:
        print("  (sólo mesas donde PRECONTEO y ESCRUTINIO coinciden: son las de")
        print("   valor oficial menos discutible)")

    # Acumular en BLOQUES en vez de una sola lista gigante.
    #
    # Una lista de arrays de 48x48 cuesta ~4.752 bytes por caja (2.304 del array
    # + overhead del objeto numpy), más del doble que el array compacto. Con el
    # corpus completo (1,68 M cajas) el pico era ~11,9 GB —lista y `np.stack`
    # vivos a la vez— sobre una máquina con ~12 GB libres. Compactando cada
    # BLOQUE el pico baja a ~4 GB y deja de depender del tamaño del corpus.
    BLOQUE = 50_000
    bloques_X, buf_X = [], []
    y, meta = [], []
    n_ok = n_sin_oficial = n_err = n_inestable = 0

    def _cerrar_bloque():
        if buf_X:
            bloques_X.append(np.stack(buf_X).astype(np.uint8))
            buf_X.clear()
    for i, pdf in enumerate(pdfs, 1):
        try:
            dep, muni, zona, puesto, mesa = P.parsear_clave(pdf)
            k = mmv.clave_mesa(dep, muni, zona, puesto, mesa)
            if k not in esc:
                n_sin_oficial += 1
                continue
            if solo_estables and (k not in pre or
                                  not mmv.mismos_votos(pre[k], esc[k], solo_candidatos=False)):
                n_inestable += 1
                continue
            estandar, _ = P.es_formato_estandar(pdf)
            if not estandar:
                n_err += 1
                continue
            cajas = cajas_de_acta(pdf)
            if len(cajas) != 9:
                n_err += 1
                continue

            valores = {}
            for casilla, (tipo, dato) in MAPA_CASILLA.items():
                if tipo == "codigo":
                    cod = por_codigo.get(dato)
                    valores[casilla] = esc[k].get(cod, 0) if cod else None
                elif tipo == "fijo":
                    valores[casilla] = esc[k].get(dato, 0)
            valores["SUMA_TOTAL"] = sum(v for c, v in valores.items()
                                        if c != "SUMA_TOTAL" and v is not None)

            usadas = 0
            for casilla, valor in valores.items():
                if valor is None or casilla not in cajas:
                    continue
                et = etiquetas_de_valor(valor)
                if et is None:
                    continue
                for pos, caja in enumerate(cajas[casilla]):
                    buf_X.append(cv2.cvtColor(caja, cv2.COLOR_BGR2GRAY)[..., None]
                                 if gris else caja)
                    y.append(et[pos])
                    meta.append(f"{'_'.join(map(str, k))}|{casilla}|{pos}")
                    if len(buf_X) >= BLOQUE:
                        _cerrar_bloque()
                usadas += 1
            if usadas:
                n_ok += 1
        except Exception:
            n_err += 1
        if i % 500 == 0:
            print(f"  {i}/{len(pdfs)} | actas usadas={n_ok} inestables={n_inestable} "
                  f"sin_oficial={n_sin_oficial} err={n_err}")

    _cerrar_bloque()
    if not bloques_X:
        print("Sin datos.")
        return
    X = np.concatenate(bloques_X) if len(bloques_X) > 1 else bloques_X[0]
    bloques_X.clear()
    y = np.array(y, np.int64)
    np.savez_compressed(salida, X=X, y=y, meta=np.array(meta))
    c = np.bincount(y, minlength=11)
    print(f"\nactas usadas: {n_ok:,}  (inestables {n_inestable:,}, "
          f"sin oficial {n_sin_oficial:,}, errores {n_err:,})")
    print(f"cajas etiquetadas: {len(y):,}   shape={X.shape}"
          f"   ({X.nbytes/1e9:.2f} GB en RAM)")
    print("distribución por clase:")
    for i, n in enumerate(c):
        if n:
            print(f"  {VOCAB[i]:>8s}: {n:>8,}  {'#' * int(50 * n / max(c))}")
    print(f"-> {salida}")


def main():
    ap = argparse.ArgumentParser(description="Dataset etiquetado con el escrutinio oficial")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("construir")
    p.add_argument("--actas", required=True)
    p.add_argument("--mmv", required=True)
    p.add_argument("--salida", default="digitos_oficial.npz")
    p.add_argument("--limite", type=int, default=None)
    p.add_argument("--desde", type=int, default=0)
    p.add_argument("--incluir-inestables", dest="solo_estables", action="store_false",
                   help="incluir también mesas donde preconteo y escrutinio difieren")
    p.add_argument("--color", dest="gris", action="store_false",
                   help="guardar en RGB (3x más memoria; el color NO mejora, ver docs)")
    a = ap.parse_args()
    if a.cmd == "construir":
        construir(a.actas, a.mmv, a.salida, a.limite, a.desde, a.solo_estables, a.gris)


if __name__ == "__main__":
    main()
