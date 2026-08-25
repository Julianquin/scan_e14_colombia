#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clasificador de dígitos 48x48 para 2da vuelta (CLAVEROS) — GPU.

Contra el `clasificador_digitos.py` de 1ra vuelta, cambian tres cosas:
  1. Entrada **48x48 en escala de grises** (no binarizada) en vez de binaria
     28x28. CLAVEROS conserva 249 niveles de gris; binarizarlo con umbral fijo
     tira esa información (ver docs/FORENSE_COLOR.md).
  2. CNN de 3 bloques (32/64/128) con BatchNorm, en vez de 2 bloques.
  3. Augmentación fotométrica además de geométrica: la iluminación del escáner
     varía entre actas y el modelo no debe agarrarse de eso.

### ⚠️ El COLOR no ayuda — medido, no supuesto

El módulo nació para explotar el color RGB de CLAVEROS. **El experimento dijo
que no sirve.** Entrenando lo mismo con y sin color (misma arquitectura, misma
resolución, mismas etiquetas; `--gris` replica el gris a 3 canales para que la
ÚNICA variable sea la cromática), sobre 1.500 actas no vistas:

| Entrada | % de actas que CUADRAN |
|---|---|
| RGB (color) | 42,7 % |
| **Gris** | **46,9 %** |

El color **empeora** ~4 puntos: añade variabilidad irrelevante (tono del papel,
iluminación, tinte del JPEG) sobre la que el modelo sobreajusta. La ganancia
real vino de reentrenar sobre CLAVEROS y de subir la resolución, no del color.

**Usar `--gris` siempre.** El camino RGB se conserva solo para poder repetir la
comparación; el modelo de producción (`models/digitnet_2v_gris.pt`) es gris.

**Split por MESA, nunca por caja.** Los 27 dígitos de un acta comparten
escáner, bolígrafo y persona: si caen a ambos lados del split, la validación
mide memorización y sale optimista.

### La métrica que importa no es la accuracy por dígito

Las etiquetas salen de autoetiquetado por aritmética (`dataset_color.py`), o
sea de las actas que el modelo de 1ra vuelta ya leía bien — un conjunto
sesgado hacia lo fácil. Una accuracy alta ahí no prueba nada por sí sola.

Lo que sí mide progreso real es el **% de actas que CUADRAN** al releer con el
modelo nuevo actas NO vistas en entrenamiento: es la métrica de negocio del
proyecto (el "53% de cuadre" del README) y no depende de las etiquetas.
Por eso `evaluar` re-lee actas crudas y corre el chequeo aritmético.

Uso:
    python -m e14.ocr.clasificador_color entrenar piloto.npz --modelo digitnet_color.pt
    python -m e14.ocr.clasificador_color evaluar data/segunda_vuelta/e14_pdfs_claveros \
        --modelo digitnet_color.pt --desde 6000 --limite 1500
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ / "extraccion"))


def _torch():
    import torch
    import torch.nn as nn
    return torch, nn


# --------------------------------- modelo ------------------------------------
def construir_red_color(n_clases=10):
    torch, nn = _torch()

    class DigitNetColor(nn.Module):
        def __init__(self, n=n_clases):
            super().__init__()
            def bloque(ent, sal):
                return nn.Sequential(
                    nn.Conv2d(ent, sal, 3, padding=1), nn.BatchNorm2d(sal), nn.ReLU(),
                    nn.Conv2d(sal, sal, 3, padding=1), nn.BatchNorm2d(sal), nn.ReLU(),
                    nn.MaxPool2d(2))
            self.c = nn.Sequential(bloque(3, 32), bloque(32, 64), bloque(64, 128))
            self.f = nn.Sequential(
                nn.AdaptiveAvgPool2d(1), nn.Flatten(),
                nn.Dropout(0.3), nn.Linear(128, n))

        def forward(self, x):
            return self.f(self.c(x))

    return DigitNetColor()


# ------------------------------ augmentación ----------------------------------
def _augmenta_lote(x):
    """Geométrica suave + fotométrica. x: (B,3,H,W) float en [0,1]."""
    torch, _ = _torch()
    B = x.shape[0]
    # fotométrica: brillo y contraste por muestra
    brillo = (torch.rand(B, 1, 1, 1, device=x.device) - 0.5) * 0.30
    contraste = 1.0 + (torch.rand(B, 1, 1, 1, device=x.device) - 0.5) * 0.40
    x = ((x - 0.5) * contraste + 0.5 + brillo).clamp(0, 1)
    # geométrica: rotación/traslación/escala pequeñas vía grid_sample
    ang = (torch.rand(B, device=x.device) - 0.5) * (2 * 8 * np.pi / 180)   # +-8 grados
    esc = 1.0 + (torch.rand(B, device=x.device) - 0.5) * 0.20
    tx = (torch.rand(B, device=x.device) - 0.5) * 0.16
    ty = (torch.rand(B, device=x.device) - 0.5) * 0.16
    cos, sin = torch.cos(ang) / esc, torch.sin(ang) / esc
    theta = torch.zeros(B, 2, 3, device=x.device)
    theta[:, 0, 0], theta[:, 0, 1], theta[:, 0, 2] = cos, -sin, tx
    theta[:, 1, 0], theta[:, 1, 1], theta[:, 1, 2] = sin, cos, ty
    grid = torch.nn.functional.affine_grid(theta, x.shape, align_corners=False)
    return torch.nn.functional.grid_sample(x, grid, padding_mode="border", align_corners=False)


# -------------------------------- entrenamiento -------------------------------
def a_gris(X):
    """Control experimental: quita el COLOR conservando todo lo demás
    (resolución, arquitectura, etiquetas). Devuelve el gris replicado a 3
    canales, así el modelo es idéntico y la ÚNICA variable que cambia es la
    información cromática. Sin esto, la mejora del clasificador de color se
    confunde con la de reentrenar sobre CLAVEROS y a más resolución."""
    import cv2
    g = np.stack([cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in X])
    return np.repeat(g[..., None], 3, axis=3)


def _split_por_mesa(meta, frac_val=0.2, semilla=0):
    """meta[i] = 'CLAVE|casilla|pos' -> agrupa por CLAVE (la mesa)."""
    mesas = np.array([m.split("|")[0] for m in meta])
    unicas = np.unique(mesas)
    rng = np.random.default_rng(semilla)
    rng.shuffle(unicas)
    n_val = max(1, int(len(unicas) * frac_val))
    val = set(unicas[:n_val].tolist())
    es_val = np.array([m in val for m in mesas])
    return ~es_val, es_val


def entrenar(npz, modelo_out="digitnet_color.pt", epochs=40, batch=256, dev=None, gris=False):
    torch, nn = _torch()
    dev = dev or ("cuda" if torch.cuda.is_available() else "cpu")
    d = np.load(npz, allow_pickle=True)
    X, y, meta = d["X"], d["y"], d["meta"]
    if gris:
        X = a_gris(X)
        print("MODO CONTROL: sin color (gris replicado a 3 canales)")
    tr, va = _split_por_mesa(meta)
    n_mesas = len(np.unique([m.split("|")[0] for m in meta]))
    print(f"cajas={len(y):,}  mesas={n_mesas:,}  train={tr.sum():,}  val={va.sum():,}  dev={dev}")
    print(f"distribución de dígitos: {np.bincount(y, minlength=10).tolist()}")

    # (N,H,W,3) uint8 -> (N,3,H,W) float
    Xt = torch.from_numpy(X).permute(0, 3, 1, 2).float().div(255)
    yt = torch.from_numpy(y).long()
    Xtr, ytr = Xt[tr].to(dev), yt[tr].to(dev)
    Xva, yva = Xt[va].to(dev), yt[va].to(dev)

    cuenta = np.bincount(y[tr], minlength=10).astype(np.float32)
    pesos = torch.from_numpy((cuenta.sum() / np.maximum(cuenta, 1))).float()
    pesos = (pesos / pesos.mean()).to(dev)

    red = construir_red_color().to(dev)
    opt = torch.optim.AdamW(red.parameters(), lr=2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=2e-3, total_steps=epochs * max(1, len(Xtr) // batch + 1))
    lossf = nn.CrossEntropyLoss(weight=pesos, label_smoothing=0.05)

    mejor, mejor_sd = 0.0, None
    for ep in range(1, epochs + 1):
        red.train()
        perm = torch.randperm(len(Xtr), device=dev)
        for i in range(0, len(perm), batch):
            idx = perm[i:i + batch]
            xb = _augmenta_lote(Xtr[idx])
            opt.zero_grad()
            loss = lossf(red(xb), ytr[idx])
            loss.backward()
            opt.step()
            sched.step()
        red.eval()
        with torch.no_grad():
            acc = (red(Xva).argmax(1) == yva).float().mean().item()
        if acc > mejor:
            mejor, mejor_sd = acc, {k: v.clone() for k, v in red.state_dict().items()}
        if ep % 5 == 0 or ep == 1:
            print(f"  ep{ep:3d}  val_acc(por dígito) = {acc:.4f}   (mejor {mejor:.4f})")

    torch.save(mejor_sd, modelo_out)
    print(f"\nMejor val_acc por dígito: {mejor:.4f}  -> {modelo_out}")
    print("OJO: esta accuracy está sobre etiquetas autogeneradas (sesgadas a lo fácil).")
    print("La métrica que decide es el % de CUADRE en 'evaluar' sobre actas no vistas.")


# --------------------------------- evaluación ---------------------------------
def cargar(modelo_pt, dev=None):
    torch, _ = _torch()
    dev = dev or ("cuda" if torch.cuda.is_available() else "cpu")
    red = construir_red_color()
    red.load_state_dict(torch.load(modelo_pt, map_location=dev, weights_only=False))
    return red.eval().to(dev), dev


def evaluar(dir_pdfs, modelo_pt, desde=0, limite=None, dev=None, gris=False):
    """Re-lee actas CRUDAS con el modelo de color y mide el % que CUADRA.
    `desde` permite saltar las actas usadas para construir el dataset."""
    torch, _ = _torch()
    import posiciones_2v as P
    from e14.comunes import CAND_2V
    from e14.ocr.chequeo_aritmetico import chequear
    from e14.ocr.dataset_color import cajas_de_acta

    red, dev = cargar(modelo_pt, dev)
    pdfs = [p for p in Path(dir_pdfs).rglob("*.pdf") if "_logs" not in p.parts]
    pdfs = pdfs[desde: desde + limite if limite else None]
    print(f"actas a evaluar: {len(pdfs):,}  (desde={desde}, dev={dev})")

    n_cuadra = n_no = n_err = 0
    for i, pdf in enumerate(pdfs, 1):
        try:
            estandar, _ = P.es_formato_estandar(pdf)
            if not estandar:
                n_err += 1
                continue
            cajas = cajas_de_acta(pdf)
            if len(cajas) != 9:
                n_err += 1
                continue
            nombres, lote = [], []
            for nombre, tres in cajas.items():
                for c in tres:
                    nombres.append(nombre)
                    lote.append(c)
            arr = np.stack(lote)
            if gris:
                arr = a_gris(arr)
            x = torch.from_numpy(arr).permute(0, 3, 1, 2).float().div(255).to(dev)
            with torch.no_grad():
                dig = red(x).argmax(1).cpu().numpy()
            valores = {nombres[j]: int("".join(str(d) for d in dig[j:j + 3]))
                       for j in range(0, len(nombres), 3)}
            r = chequear(valores, cand=CAND_2V)
            if r.cuadra_suma and r.cuadra_e11:
                n_cuadra += 1
            else:
                n_no += 1
        except Exception:
            n_err += 1
        if i % 200 == 0:
            print(f"  {i}/{len(pdfs)} | cuadra={n_cuadra} ({100*n_cuadra/max(1,i):.1f}%)")

    total = n_cuadra + n_no
    print(f"\n=== CUADRE sobre actas NO vistas ===")
    print(f"  actas evaluadas: {total:,}  (errores/atípicas: {n_err:,})")
    print(f"  CUADRAN: {n_cuadra:,}  = {100*n_cuadra/max(1,total):.1f}%")


def main():
    ap = argparse.ArgumentParser(description="Clasificador de dígitos en COLOR (CLAVEROS 2da vuelta)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("entrenar")
    p.add_argument("npz")
    p.add_argument("--modelo", default="digitnet_color.pt")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--batch", type=int, default=256)
    p.add_argument("--dev", default=None)
    p.add_argument("--gris", action="store_true",
                   help="control: entrena SIN color (mismo tamaño y arquitectura)")
    p = sub.add_parser("evaluar")
    p.add_argument("dir_pdfs")
    p.add_argument("--modelo", default="digitnet_color.pt")
    p.add_argument("--desde", type=int, default=0)
    p.add_argument("--limite", type=int, default=None)
    p.add_argument("--dev", default=None)
    p.add_argument("--gris", action="store_true",
                   help="control: evalúa SIN color (usar con un modelo entrenado con --gris)")
    a = ap.parse_args()
    if a.cmd == "entrenar":
        entrenar(a.npz, a.modelo, a.epochs, a.batch, a.dev, a.gris)
    elif a.cmd == "evaluar":
        evaluar(a.dir_pdfs, a.modelo, a.desde, a.limite, a.dev, a.gris)


if __name__ == "__main__":
    main()
