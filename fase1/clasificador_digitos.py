#!/usr/bin/env python3
"""
Fase 1 (alternativa a TrOCR) — Clasificador de dígitos sobre casillas E-14.

Cada casilla es un campo fijo de 3 dígitos. Segmentamos en 3 cajitas y
clasificamos cada una con una CNN pequeña, en vez de leer la línea con TrOCR
(que alucina dígitos/letras sobre manuscrito en rejilla).

Geometría medida sobre crops reales (consistente por tipo de celda):
    CAND  (cand_01..13):     centros x ~ [0.31, 0.57, 0.82]
    AGREG (BLANCO/NULO/...): centros x ~ [0.19, 0.50, 0.79]

Clases: 0-9. Las aspas (✱) cuentan como 0 segun la regla del E-14
(todo-aspas = 0; un numero a la derecha del aspa = ese numero, p.ej. ✱84 = 84),
asi que el aspa cae de forma natural en la clase 0 al autoetiquetar por valor.

FLUJO (subcomandos):
  1) exportar   numeros_leidos.csv  recortes_dir
        -> segmenta, autoetiqueta las casillas de actas que CUADRAN
           (etiquetas gratis y fiables) y deja sugerencia TrOCR en el resto.
  2) empaquetar dataset/etiquetas.csv  dataset/cajas
        -> junta las cajitas etiquetadas en un solo digitos.npz (sube esto).
  3) entrenar   digitos.npz
        -> CNN pequeña; split por MESA; precision de validacion por digito.
  4) evaluar    numeros_leidos.csv  recortes_dir  --modelo digitnet.pt
        -> relee el piloto con la CNN, re-corre el chequeo aritmetico y
           compara el % que CUADRA contra TrOCR (16,5% en actas completas).

cv2+numpy para 1-2 (corre en local). torch para 3-4 (local CPU o Kaggle).
"""
from __future__ import annotations
import sys, csv, argparse, math
from pathlib import Path
from collections import defaultdict
import numpy as np
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CENTROS = {"CAND": [0.31, 0.57, 0.82], "AGREG": [0.19, 0.50, 0.79]}
ANCHO_VENTANA = 0.26
AGREG = ["BLANCO", "NULO", "NO_MARCADO", "SUMA_TOTAL", "TOTAL_E11", "TOTAL_URNA", "TOTAL_INCINERADOS"]


# ----------------------------- SEGMENTACION ---------------------------------
def _tipo_de(etiqueta: str) -> str:
    return "CAND" if etiqueta.startswith("cand") else "AGREG"


def _normaliza_caja(bw: np.ndarray) -> np.ndarray:
    """Recorta a bbox de tinta (ink=255), cuadra y reescala a 28x28 (MNIST)."""
    ys, xs = np.where(bw > 0)
    if len(xs) < 8:
        return np.zeros((28, 28), np.uint8)
    rec = bw[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    s = max(rec.shape)
    cuad = np.zeros((s, s), np.uint8)
    oy, ox = (s - rec.shape[0]) // 2, (s - rec.shape[1]) // 2
    cuad[oy:oy + rec.shape[0], ox:ox + rec.shape[1]] = rec
    d = cv2.resize(cuad, (20, 20), interpolation=cv2.INTER_AREA)
    out = np.zeros((28, 28), np.uint8)
    out[4:24, 4:24] = d
    return out


def _blobs_columna(bw, w):
    col = (bw > 0).sum(axis=0)
    activo = col > (0.01 * bw.shape[0])
    runs, ini = [], None
    for x, a in enumerate(activo):
        if a and ini is None:
            ini = x
        elif not a and ini is not None:
            runs.append([ini, x]); ini = None
    if ini is not None:
        runs.append([ini, len(activo)])
    fus = []
    for r in runs:
        if fus and r[0] - fus[-1][1] < 0.03 * w:
            fus[-1][1] = r[1]
        else:
            fus.append(r)
    return fus


def segmentar(crop_path: str, etiqueta: str) -> list[np.ndarray]:
    """3 cajitas 28x28 (ink=255). 3 blobs -> usa blobs; si no -> ventanas fijas."""
    img = cv2.imread(crop_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return [np.zeros((28, 28), np.uint8)] * 3
    h, w = img.shape
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    fus = _blobs_columna(bw, w)
    if len(fus) == 3:
        ventanas = [(a, b) for a, b in fus]
    else:
        ventanas = [(int((c - ANCHO_VENTANA / 2) * w), int((c + ANCHO_VENTANA / 2) * w))
                    for c in CENTROS[_tipo_de(etiqueta)]]
    cajas = []
    for x0, x1 in ventanas:
        x0, x1 = max(0, x0 - 4), min(w, x1 + 4)
        cajas.append(_normaliza_caja(bw[:, x0:x1]))
    return cajas


# --------------------------- ARITMETICA / CONFIANZA -------------------------
def _sniff(path):
    cab = open(path, encoding="utf-8-sig").readline()
    return ";" if cab.count(";") > cab.count(",") else ","


def _clave(r):
    return (r["ejemplar"], r["dep"], r["muni"], r["zona"], r["puesto"], r["mesa"])


def _nivel(numeros: dict) -> str:
    """numeros[et] = int | None (None = casilla con tinta no leida). Ausente = 0."""
    import chequeo_aritmetico as chk
    completo = {}
    for et in chk.CAND + AGREG:
        completo[et] = numeros[et] if et in numeros else 0
    return chk.nivel_alerta(chk.chequear(completo))


def cargar_por_mesa(numeros_csv):
    por_mesa = defaultdict(dict)        # mesa -> {etiqueta: int|None}
    trocr = {}                          # (mesa..et) -> str leido
    for r in csv.DictReader(open(numeros_csv, encoding="utf-8-sig"), delimiter=_sniff(numeros_csv)):
        n = r["numero"].strip()
        por_mesa[_clave(r)][r["etiqueta"]] = int(n) if n.isdigit() else None
        trocr[_clave(r) + (r["etiqueta"],)] = n
    return por_mesa, trocr


def mesas_que_cuadran(numeros_csv):
    por_mesa, _ = cargar_por_mesa(numeros_csv)
    return {m for m, nums in por_mesa.items() if _nivel(nums) == "NINGUNA"}


# ------------------------------ EXPORTAR ------------------------------------
def exportar_dataset(numeros_csv, recortes_dir, salida_dir):
    salida = Path(salida_dir); (salida / "cajas").mkdir(parents=True, exist_ok=True)
    confianza = mesas_que_cuadran(numeros_csv)
    por_mesa, trocr = cargar_por_mesa(numeros_csv)
    print(f"Actas que cuadran (autoetiqueta de confianza): {len(confianza)}")

    filas, n = [], 0
    for r in csv.DictReader(open(numeros_csv, encoding="utf-8-sig"), delimiter=_sniff(numeros_csv)):
        if not r.get("archivo"):
            continue
        crop = Path(recortes_dir) / r["archivo"]
        if not crop.exists():
            continue
        mesa = _clave(r); et = r["etiqueta"]
        cajas = segmentar(str(crop), et)

        autoet = None
        val = por_mesa[mesa].get(et)
        if mesa in confianza and isinstance(val, int) and 0 <= val <= 999:
            autoet = str(val).zfill(3)
        sug = trocr.get(mesa + (et,), "")
        sug = sug.zfill(3) if sug.isdigit() and len(sug) <= 3 else ""

        for pos, caja in enumerate(cajas):
            nombre = f"{r['archivo'][:-4]}__pos{pos}.png"
            cv2.imwrite(str(salida / "cajas" / nombre), 255 - caja)   # negro sobre blanco (humano)
            filas.append({"caja": nombre, "etiqueta_celda": et, "pos": pos,
                          "etiqueta_digito": autoet[pos] if autoet else "",
                          "sugerencia": sug[pos] if sug else "",
                          "confianza": int(mesa in confianza)})
            n += 1

    with open(salida / "etiquetas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["caja", "etiqueta_celda", "pos",
                                          "etiqueta_digito", "sugerencia", "confianza"])
        w.writeheader(); w.writerows(filas)
    auto = sum(1 for x in filas if x["etiqueta_digito"] != "")
    print(f"Exportadas {n} cajitas en {salida/'cajas'}")
    print(f"Plantilla: {salida/'etiquetas.csv'}  ({auto} autoetiquetadas, {n-auto} por etiquetar a mano)")


# ------------------------------ EMPAQUETAR ----------------------------------
def empaquetar_npz(etiquetas_csv, cajas_dir, salida_npz):
    X, y, nombres = [], [], []
    for r in csv.DictReader(open(etiquetas_csv, encoding="utf-8-sig"), delimiter=_sniff(etiquetas_csv)):
        d = r["etiqueta_digito"].strip()
        if d not in [str(i) for i in range(10)]:     # solo etiquetadas 0-9
            continue
        img = cv2.imread(str(Path(cajas_dir) / r["caja"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        X.append(255 - img)                          # volver a ink=255 (como segmentar)
        y.append(int(d)); nombres.append(r["caja"])
    X = np.stack(X).astype(np.uint8); y = np.array(y, np.int64)
    np.savez_compressed(salida_npz, X=X, y=y, nombres=np.array(nombres))
    print(f"Guardado {salida_npz}: {len(y)} digitos etiquetados")
    vals, cnt = np.unique(y, return_counts=True)
    print("  distribucion por clase:", dict(zip(vals.tolist(), cnt.tolist())))


# ------------------------------ TORCH: CNN ----------------------------------
def _torch():
    import torch, torch.nn as nn
    return torch, nn


def construir_red():
    torch, nn = _torch()

    class DigitNet(nn.Module):
        def __init__(self, n=10):
            super().__init__()
            self.c = nn.Sequential(                       # CNN estilo paper (BN + 32/64)
                nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2))
            self.f = nn.Sequential(nn.Flatten(), nn.Linear(64 * 7 * 7, 128),
                                   nn.ReLU(), nn.Dropout(0.3), nn.Linear(128, n))

        def forward(self, x):
            return self.f(self.c(x))
    return DigitNet()


def _augmenta(img):
    """Aug ligera con cv2: desplazamiento, rotacion y escala pequeños (ink=255)."""
    a = (np.random.rand() - 0.5) * 20          # +-10 grados
    s = 1 + (np.random.rand() - 0.5) * 0.2     # +-10% escala
    tx, ty = (np.random.rand(2) - 0.5) * 4     # +-2 px
    M = cv2.getRotationMatrix2D((14, 14), a, s); M[:, 2] += [tx, ty]
    return cv2.warpAffine(img, M, (28, 28), flags=cv2.INTER_LINEAR, borderValue=0)


def _entrenar_uno(Xtr, ytr, Xva, yva, pesos, epochs, batch, aug, seed, dev):
    torch, nn = _torch()
    torch.manual_seed(seed); np.random.seed(seed)
    net = construir_red().to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    lossf = nn.CrossEntropyLoss(weight=pesos.to(dev))
    Xva_t = torch.tensor(Xva[:, None].astype("float32") / 255.).to(dev)
    yva_t = torch.tensor(yva).to(dev)
    idx = np.arange(len(ytr))
    for ep in range(epochs):
        net.train(); np.random.shuffle(idx)
        for i in range(0, len(idx), batch):
            b = idx[i:i + batch]; xb = Xtr[b].copy()
            if aug:
                xb = np.stack([_augmenta(im) for im in xb])
            xb = torch.tensor(xb[:, None].astype("float32") / 255.).to(dev)
            yb = torch.tensor(ytr[b]).to(dev)
            opt.zero_grad(); lossf(net(xb), yb).backward(); opt.step()
    net.eval()
    with torch.no_grad():
        acc = (net(Xva_t).argmax(1) == yva_t).float().mean().item()
    return net.state_dict(), acc


def entrenar(npz, modelo_out="digitnet.pt", epochs=30, batch=64, aug=True, ensemble=1):
    """Entrena 1 CNN, o 'ensemble' CNNs (distinta semilla) con voto suave."""
    torch, nn = _torch()
    d = np.load(npz, allow_pickle=True)
    X, y, nombres = d["X"], d["y"], d["nombres"]

    # split por MESA (evita fuga: dígitos de la misma acta no caen en train y val)
    mesas = np.array([n.split("__")[0] for n in nombres])
    uniq = np.unique(mesas); np.random.seed(0); np.random.shuffle(uniq)
    val_m = set(uniq[: max(1, len(uniq) // 5)])
    es_val = np.array([m in val_m for m in mesas])
    Xtr, ytr, Xva, yva = X[~es_val], y[~es_val], X[es_val], y[es_val]
    print(f"Train: {len(ytr)} dígitos / Val: {len(yva)} dígitos  (val = {len(val_m)} actas)")

    cnt = np.bincount(ytr, minlength=10).astype(np.float32)     # muchos 0 por las cabeceras
    pesos = torch.tensor(cnt.sum() / (10 * np.maximum(cnt, 1)), dtype=torch.float32)
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    sds = []
    for k in range(ensemble):
        sd, acc = _entrenar_uno(Xtr, ytr, Xva, yva, pesos, epochs, batch, aug, seed=k, dev=dev)
        sds.append(sd)
        print(f"  modelo {k+1}/{ensemble}  val_acc(por dígito) = {acc:.3f}")

    if ensemble > 1:                                            # voto suave en val
        nets = []
        for sd in sds:
            m_ = construir_red(); m_.load_state_dict(sd); m_.eval(); nets.append(m_)
        Xva_t = torch.tensor(Xva[:, None].astype("float32") / 255.)
        with torch.no_grad():
            p = sum(m_(Xva_t).softmax(1) for m_ in nets) / len(nets)
        print(f"  ENSEMBLE({ensemble}) val_acc(por dígito) = {(p.argmax(1).numpy() == yva).mean():.3f}")

    torch.save(sds if ensemble > 1 else sds[0], modelo_out)
    print(f"Modelo guardado: {modelo_out}")


def cargar_modelo(modelo_pt):
    """Devuelve SIEMPRE una lista de redes (1 o varias, según el ensemble)."""
    torch, _ = _torch()
    data = torch.load(modelo_pt, map_location="cpu")
    sds = data if isinstance(data, list) else [data]
    nets = []
    for sd in sds:
        m_ = construir_red(); m_.load_state_dict(sd); m_.eval(); nets.append(m_)
    return nets


def leer_celda(cajas, modelos):
    """Voto suave: promedia el softmax sobre las redes (una o varias)."""
    torch, _ = _torch()
    if not isinstance(modelos, list):
        modelos = [modelos]
    x = torch.tensor(np.stack(cajas)[:, None].astype("float32") / 255.)
    with torch.no_grad():
        p = sum(m_(x).softmax(1) for m_ in modelos) / len(modelos)
    conf, idx = p.max(1)
    return "".join(str(i) for i in idx.tolist()), conf.tolist()


# ------------------------------ EVALUAR -------------------------------------
def evaluar_cuadre(numeros_csv, recortes_dir, modelo_pt):
    import chequeo_aritmetico as chk
    modelo = cargar_modelo(modelo_pt)
    confianza = mesas_que_cuadran(numeros_csv)

    leido = defaultdict(dict)
    for r in csv.DictReader(open(numeros_csv, encoding="utf-8-sig"), delimiter=_sniff(numeros_csv)):
        if not r.get("archivo"):
            continue
        crop = Path(recortes_dir) / r["archivo"]
        if not crop.exists():
            continue
        cajas = segmentar(str(crop), r["etiqueta"])
        txt, _ = leer_celda(cajas, modelo)
        leido[_clave(r)][r["etiqueta"]] = int(txt)

    conteo = defaultdict(int); nuevas = 0
    for mesa, nums in leido.items():
        completo = {et: nums.get(et, 0) for et in chk.CAND + AGREG}
        niv = chk.nivel_alerta(chk.chequear(completo))
        conteo[niv] += 1
        if niv == "NINGUNA" and mesa not in confianza:
            nuevas += 1

    tot = len(leido)
    print(f"\n=== CLASIFICADOR sobre {tot} actas ===")
    for k in ["NINGUNA", "MEDIA", "ALTA"]:
        print(f"  {k:9s}: {conteo[k]:>4}  ({100*conteo[k]/tot:.1f}%)")
    print(f"\nBaseline TrOCR: {len(confianza)} cuadran ({100*len(confianza)/tot:.1f}%)")
    print(f"Actas que cuadran AHORA y no con TrOCR (ganancia real): {nuevas}")
    print(f"Total cuadran clasificador: {conteo['NINGUNA']} "
          f"({100*conteo['NINGUNA']/tot:.1f}%)  vs  {len(confianza)} TrOCR")


# ---------------------- DECODIFICACION ARITMETICA ---------------------------
IDENTIDAD = None   # se rellena con chk.CAND + agregados de identidad


def leer_celda_topk(cajas, modelos, k=2):
    """Top-k dígitos por posición: lista de 3 posiciones, cada una [(d, prob), ...]."""
    torch, _ = _torch()
    if not isinstance(modelos, list):
        modelos = [modelos]
    x = torch.tensor(np.stack(cajas)[:, None].astype("float32") / 255.)
    with torch.no_grad():
        p = (sum(m(x).softmax(1) for m in modelos) / len(modelos)).numpy()
    tops = []
    for pos in range(len(cajas)):
        orden = p[pos].argsort()[::-1][:k]
        tops.append([(int(d), float(p[pos][d])) for d in orden])
    return tops


def _candidatos_valor(tops, max_cost=2.5):
    """Valores posibles de una casilla (top-1 + swaps de 1 posición a top-2) con coste."""
    base = "".join(str(tops[i][0][0]) for i in range(3))
    cands = {int(base): 0.0}
    for i in range(3):
        if len(tops[i]) > 1:
            (d1, p1), (d2, p2) = tops[i][0], tops[i][1]
            cost = math.log(max(p1, 1e-9) / max(p2, 1e-9))
            if cost <= max_cost:
                s = list(base); s[i] = str(d2)
                v = int("".join(s))
                cands[v] = min(cands.get(v, 9e9), cost)
    return cands


def decodificar_acta(cands_por_celda):
    """
    cands_por_celda: {etiqueta: {valor: coste}} para las celdas de identidad.
    Busca la asignación de menor coste que CUADRA cambiando como mucho 2 casillas.
    Devuelve (asignacion, estado, coste, casillas_cambiadas).
    """
    import chequeo_aritmetico as chk
    base = {et: next(v for v, c in cc.items() if c == 0) for et, cc in cands_por_celda.items()}

    def cuadra(asig):
        completo = {et: asig.get(et, 0) for et in chk.CAND + AGREG}
        return chk.nivel_alerta(chk.chequear(completo)) == "NINGUNA"

    if cuadra(base):
        return base, "directo", 0.0, []

    flex = {et: cc for et, cc in cands_por_celda.items() if len(cc) > 1}
    soluciones = []

    for et, cc in flex.items():                          # 1 cambio
        for v, co in cc.items():
            if co == 0:
                continue
            asig = dict(base); asig[et] = v
            if cuadra(asig):
                soluciones.append((co, 1, asig, [et]))

    if not soluciones:                                   # 2 cambios (acotado a las más dudosas)
        fl = sorted(flex.items(), key=lambda kv: min(c for c in kv[1].values() if c > 0))[:8]
        for a in range(len(fl)):
            for b in range(a + 1, len(fl)):
                eta, ca = fl[a]; etb, cb = fl[b]
                for va, coa in ca.items():
                    if coa == 0:
                        continue
                    for vb, cob in cb.items():
                        if cob == 0:
                            continue
                        asig = dict(base); asig[eta] = va; asig[etb] = vb
                        if cuadra(asig):
                            soluciones.append((coa + cob, 2, asig, [eta, etb]))

    if not soluciones:
        return base, "no_cuadra", 0.0, []
    soluciones.sort(key=lambda s: s[0])
    coste, ncamb, asig, cambiadas = soluciones[0]
    estado = "corregido_minimo" if (ncamb == 1 and coste < 0.7) else "corregido_forzado"
    return asig, estado, coste, cambiadas


def decodificar(numeros_csv, recortes_dir, modelo_pt, salida="actas_decodificadas.csv"):
    import chequeo_aritmetico as chk
    modelos = cargar_modelo(modelo_pt)
    IDENT = chk.CAND + ["BLANCO", "NULO", "NO_MARCADO", "SUMA_TOTAL", "TOTAL_E11"]

    cands = defaultdict(dict)     # mesa -> {etiqueta: {valor: coste}}
    for r in csv.DictReader(open(numeros_csv, encoding="utf-8-sig"), delimiter=_sniff(numeros_csv)):
        if not r.get("archivo") or r["etiqueta"] not in IDENT:
            continue
        crop = Path(recortes_dir) / r["archivo"]
        if not crop.exists():
            continue
        tops = leer_celda_topk(segmentar(str(crop), r["etiqueta"]), modelos, k=2)
        cands[_clave(r)][r["etiqueta"]] = _candidatos_valor(tops)

    conteo = defaultdict(int); filas = []
    for mesa, cc in cands.items():
        asig, estado, coste, cambiadas = decodificar_acta(cc)
        conteo[estado] += 1
        filas.append({"ejemplar": mesa[0], "dep": mesa[1], "muni": mesa[2], "zona": mesa[3],
                      "puesto": mesa[4], "mesa": mesa[5], "estado": estado,
                      "n_cambios": len(cambiadas), "coste": round(coste, 3),
                      "casillas_corregidas": ";".join(cambiadas)})
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys())); w.writeheader(); w.writerows(filas)

    tot = len(cands)
    directo = conteo["directo"]
    mini = conteo["corregido_minimo"]; forz = conteo["corregido_forzado"]
    no = conteo["no_cuadra"]
    print(f"=== DECODIFICACION ARITMETICA sobre {tot} actas ===")
    print(f"  cuadran directo:          {directo:>4}  ({100*directo/tot:.1f}%)")
    print(f"  recuperadas (1 dígito):   {mini:>4}  ({100*mini/tot:.1f}%)  <- corrección mínima, fiable")
    print(f"  recuperadas (forzado):    {forz:>4}  ({100*forz/tot:.1f}%)  <- revisar: 2 cambios o top-2 flojo")
    print(f"  NO cuadran:               {no:>4}  ({100*no/tot:.1f}%)  <- candidatas a irregularidad real")
    print(f"\n  Cuadre total tras decodificar: {directo+mini+forz} ({100*(directo+mini+forz)/tot:.1f}%)")
    print(f"  Cuadre fiable (directo+mínimo): {directo+mini} ({100*(directo+mini)/tot:.1f}%)")
    print(f"\nDetalle por acta: {salida}")


# --------------------------- PSEUDOETIQUETAR --------------------------------
def pseudoetiquetar(numeros_csv, recortes_dir, etiquetas_csv, cajas_dir,
                    modelo_pt, umbral=0.995):
    """
    Reduce el etiquetado manual. Con el modelo actual:
      - relee cada acta; las que CUADRAN aritméticamente -> sus dígitos quedan
        VALIDADOS (etiqueta gratis y fiable, no es solo confianza del modelo).
      - del resto, cada cajita con confianza >= umbral -> pseudo-etiqueta.
      - lo que queda sin etiquetar (lo dudoso) va a por_revisar.csv ordenado de
        menos a más confianza, para el etiquetador manual.
    Conserva 'auto' (arranque) y 'manual' (tu etiquetado); refresca validado/
    pseudo en cada pasada, así puedes iterar sin fijar errores.
    """
    import chequeo_aritmetico as chk
    modelo = cargar_modelo(modelo_pt)

    celdas, por_mesa = [], defaultdict(dict)
    for r in csv.DictReader(open(numeros_csv, encoding="utf-8-sig"), delimiter=_sniff(numeros_csv)):
        if not r.get("archivo"):
            continue
        crop = Path(recortes_dir) / r["archivo"]
        if not crop.exists():
            continue
        txt, confs = leer_celda(segmentar(str(crop), r["etiqueta"]), modelo)
        celdas.append((_clave(r), r["archivo"], txt, confs))
        por_mesa[_clave(r)][r["etiqueta"]] = int(txt)

    cuadran = {m for m, nums in por_mesa.items()
               if chk.nivel_alerta(chk.chequear({et: nums.get(et, 0) for et in chk.CAND + AGREG})) == "NINGUNA"}

    pseudo, minconf = {}, {}
    for mesa, archivo, txt, confs in celdas:
        for pos in range(3):
            caja = f"{archivo[:-4]}__pos{pos}.png"
            minconf[caja] = confs[pos]
            if mesa in cuadran:
                pseudo[caja] = (txt[pos], "validado")
            elif confs[pos] >= umbral:
                pseudo[caja] = (txt[pos], "pseudo")

    rows = list(csv.DictReader(open(etiquetas_csv, encoding="utf-8-sig"), delimiter=_sniff(etiquetas_csv)))
    campos = list(rows[0].keys())
    if "fuente" not in campos:
        campos.append("fuente")
    for r in rows:
        if "fuente" not in r:                        # primera pasada
            r["fuente"] = "auto" if (r.get("confianza") == "1" and r["etiqueta_digito"]) else ""
        if r["fuente"] in ("auto", "manual"):        # intocables
            continue
        if r["caja"] in pseudo:
            r["etiqueta_digito"], r["fuente"] = pseudo[r["caja"]]
        else:
            r["etiqueta_digito"], r["fuente"] = "", ""

    with open(etiquetas_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos); w.writeheader(); w.writerows(rows)

    revisar = [r for r in rows if not r["etiqueta_digito"]]
    revisar.sort(key=lambda r: minconf.get(r["caja"], 0.0))
    por_rev = str(Path(etiquetas_csv).parent / "por_revisar.csv")
    with open(por_rev, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos); w.writeheader(); w.writerows(revisar)

    n = len(rows)
    val = sum(1 for r in rows if r["fuente"] == "validado")
    ps = sum(1 for r in rows if r["fuente"] == "pseudo")
    au = sum(1 for r in rows if r["fuente"] == "auto")
    ma = sum(1 for r in rows if r["fuente"] == "manual")
    print(f"Actas que cuadran con el modelo: {len(cuadran)}")
    print(f"Etiquetas: auto={au}  validado={val}  pseudo={ps}  manual={ma}")
    print(f"  -> a mano quedan {len(revisar)} de {n}  ({100*len(revisar)/n:.1f}%)")
    print(f"  Lista priorizada (más dudosas primero): {por_rev}")


# --------------------------------- CLI --------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Clasificador de digitos E-14")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("exportar"); p.add_argument("numeros_csv"); p.add_argument("recortes_dir")
    p.add_argument("--salida", default="dataset_digitos")

    p = sub.add_parser("empaquetar"); p.add_argument("etiquetas_csv"); p.add_argument("cajas_dir")
    p.add_argument("--salida", default="digitos.npz")

    p = sub.add_parser("entrenar"); p.add_argument("npz")
    p.add_argument("--modelo", default="digitnet.pt"); p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--sin-aug", action="store_true"); p.add_argument("--ensemble", type=int, default=1)

    p = sub.add_parser("evaluar"); p.add_argument("numeros_csv"); p.add_argument("recortes_dir")
    p.add_argument("--modelo", default="digitnet.pt")

    p = sub.add_parser("pseudoetiquetar"); p.add_argument("numeros_csv"); p.add_argument("recortes_dir")
    p.add_argument("etiquetas_csv"); p.add_argument("cajas_dir")
    p.add_argument("--modelo", default="digitnet.pt"); p.add_argument("--umbral", type=float, default=0.995)

    p = sub.add_parser("decodificar"); p.add_argument("numeros_csv"); p.add_argument("recortes_dir")
    p.add_argument("--modelo", default="digitnet.pt"); p.add_argument("--salida", default="actas_decodificadas.csv")

    a = ap.parse_args()
    if a.cmd == "exportar":
        exportar_dataset(a.numeros_csv, a.recortes_dir, a.salida)
    elif a.cmd == "empaquetar":
        empaquetar_npz(a.etiquetas_csv, a.cajas_dir, a.salida)
    elif a.cmd == "entrenar":
        entrenar(a.npz, a.modelo, a.epochs, aug=not a.sin_aug, ensemble=a.ensemble)
    elif a.cmd == "evaluar":
        evaluar_cuadre(a.numeros_csv, a.recortes_dir, a.modelo)
    elif a.cmd == "pseudoetiquetar":
        pseudoetiquetar(a.numeros_csv, a.recortes_dir, a.etiquetas_csv, a.cajas_dir, a.modelo, a.umbral)
    elif a.cmd == "decodificar":
        decodificar(a.numeros_csv, a.recortes_dir, a.modelo, a.salida)


if __name__ == "__main__":
    main()