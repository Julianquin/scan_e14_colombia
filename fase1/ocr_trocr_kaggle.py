# ============================================================================
# OCR de dígitos manuscritos E-14 con TrOCR-handwritten — Notebook Kaggle (GPU)
# ============================================================================
# Lee los recortes exportados por exportar_recortes.py y produce un CSV con el
# número leído de cada casilla. Pensado para correr en Kaggle con GPU activada.
#
# CÓMO USAR EN KAGGLE:
#   1. Sube recortes_ocr.zip como Dataset (Add Data → Upload).
#   2. Crea un Notebook, activa GPU (Settings → Accelerator → GPU T4).
#   3. Pega este código (cada bloque '# %% celda' puede ir en una celda).
#   4. Ajusta RECORTES_DIR a la ruta donde Kaggle montó tu dataset
#      (algo como /kaggle/input/recortes-ocr/recortes_ocr).
#   5. Run All. Genera /kaggle/working/numeros_leidos.csv → descárgalo.
# ============================================================================

# %% celda 1 — Instalar dependencias (Kaggle suele traer torch; falta a veces transformers)
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                "transformers", "pillow"], check=False)

# %% celda 2 — Imports y configuración
import os, csv, time, re
from pathlib import Path
import torch
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

# AJUSTA esta ruta a donde Kaggle montó tu dataset:
RECORTES_DIR = Path("/kaggle/input/recortes-ocr/recortes_ocr")
SALIDA = Path("/kaggle/working/numeros_leidos.csv")
MODELO = "microsoft/trocr-base-handwritten"   # o trocr-large-handwritten (+lento +preciso)
BATCH = 32

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Dispositivo: {device}")
assert device == "cuda", "Activa la GPU en Settings → Accelerator → GPU"

# %% celda 3 — Cargar modelo
print("Cargando TrOCR-handwritten...")
processor = TrOCRProcessor.from_pretrained(MODELO)
model = VisionEncoderDecoderModel.from_pretrained(MODELO).to(device).eval()
print("Modelo cargado.")

def solo_digitos(texto):
    return re.sub(r"\D", "", texto or "")

# %% celda 4 — Leer todos los recortes en lotes
indice = RECORTES_DIR / "indice_recortes.csv"
filas = []
with open(indice, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r.get("archivo"):
            filas.append(r)
print(f"Recortes a leer: {len(filas):,}")

def leer_lote(imgs):
    pv = processor(images=imgs, return_tensors="pt").pixel_values.to(device)
    with torch.no_grad():
        ids = model.generate(pv, max_new_tokens=8)
    return processor.batch_decode(ids, skip_special_tokens=True)

resultados = []
t0 = time.time()
buffer_imgs, buffer_meta = [], []

def flush():
    if not buffer_imgs:
        return
    textos = leer_lote(buffer_imgs)
    for meta, txt in zip(buffer_meta, textos):
        meta["numero"] = solo_digitos(txt)
        meta["texto_crudo"] = txt
        resultados.append(meta)
    buffer_imgs.clear(); buffer_meta.clear()

for i, r in enumerate(filas):
    ruta = RECORTES_DIR / r["archivo"]
    try:
        img = Image.open(ruta).convert("RGB")
    except Exception:
        continue
    buffer_imgs.append(img)
    buffer_meta.append(dict(r))
    if len(buffer_imgs) >= BATCH:
        flush()
        if (i+1) % (BATCH*20) == 0:
            rate = (i+1)/(time.time()-t0)
            print(f"  {i+1:,}/{len(filas):,} | {rate:.0f} recortes/s | "
                  f"ETA {(len(filas)-i-1)/rate/60:.0f} min")
flush()
print(f"\nLeídos {len(resultados):,} recortes en {(time.time()-t0)/60:.1f} min")

# %% celda 5 — Guardar CSV
campos = ["dep","muni","zona","puesto","mesa","etiqueta","numero","texto_crudo","archivo","tinta"]
with open(SALIDA, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
    w.writeheader(); w.writerows(resultados)
print(f"Guardado: {SALIDA}")
print("Descárgalo desde el panel Output del notebook y pásalo a la Fase 1 local.")
