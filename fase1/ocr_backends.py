#!/usr/bin/env python3
"""
Fase 1 — Backends de OCR intercambiables para leer dígitos manuscritos.

Define una interfaz común y dos implementaciones locales gratuitas:
  - PaddleBackend  (PaddleOCR)
  - TrOCRBackend   (microsoft/trocr-*-handwritten, vía transformers)

Cada backend implementa:
  leer_numero(img_bgr) -> str     # lee el número completo de un recorte
  leer_digito(img_bgr) -> str     # lee un único dígito de un recorte

Así el resto del código no depende del motor concreto. Para añadir otro backend
(p.ej. un CNN propio o una API en la nube), basta con implementar la interfaz.

INSTALACIÓN (en tu máquina, según el backend que uses):
  PaddleOCR:  pip install paddlepaddle paddleocr
  TrOCR:      pip install transformers torch pillow
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comunes import solo_digitos as _solo_digitos


class OCRBackend:
    """Interfaz común. No usar directamente."""
    nombre = "base"

    def leer_numero(self, img_bgr: np.ndarray) -> str:
        raise NotImplementedError

    def leer_digito(self, img_bgr: np.ndarray) -> str:
        # por defecto, reutiliza leer_numero y toma el primer dígito
        d = _solo_digitos(self.leer_numero(img_bgr))
        return d[:1]


# ─────────────────────────────────────────────────────────────────────────────
# PaddleOCR
# ─────────────────────────────────────────────────────────────────────────────
class PaddleBackend(OCRBackend):
    nombre = "paddleocr"

    def __init__(self, lang: str = "en"):
        from paddleocr import PaddleOCR
        # PaddleOCR 3.x (PP-OCRv5): la API usa .predict() y se desactivan los
        # módulos auxiliares (orientación, unwarp) que no aportan en recortes ya
        # alineados de dígitos.
        try:
            self.ocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang=lang,
            )
            self._api = "v3"
        except TypeError:
            # Fallback para PaddleOCR 2.x (API antigua)
            self.ocr = PaddleOCR(use_angle_cls=False, lang=lang, show_log=False)
            self._api = "v2"

    def _run(self, img_bgr: np.ndarray) -> str:
        if self._api == "v3":
            resultado = self.ocr.predict(img_bgr)
            # En 3.x, predict() devuelve una lista de objetos Result con
            # 'rec_texts' (lista de textos) y 'rec_polys'/'rec_boxes'.
            textos = []
            for res in resultado:
                d = res if isinstance(res, dict) else getattr(res, "json", {}).get("res", res)
                rec_texts = None
                rec_boxes = None
                # Acceso tolerante a distintas formas del resultado
                try:
                    rec_texts = d["rec_texts"]
                    rec_boxes = d.get("rec_boxes") or d.get("rec_polys")
                except (TypeError, KeyError):
                    rec_texts = getattr(res, "rec_texts", None)
                    rec_boxes = getattr(res, "rec_boxes", None)
                if not rec_texts:
                    continue
                if rec_boxes is not None and len(rec_boxes) == len(rec_texts):
                    pares = []
                    for t, b in zip(rec_texts, rec_boxes):
                        arr = np.array(b).reshape(-1, 2)
                        pares.append((float(arr[:, 0].min()), t))
                    pares.sort(key=lambda p: p[0])
                    textos.extend(t for _, t in pares)
                else:
                    textos.extend(rec_texts)
            return "".join(textos)
        else:
            resultado = self.ocr.ocr(img_bgr, cls=False)
            if not resultado or not resultado[0]:
                return ""
            items = []
            for linea in resultado[0]:
                box, (texto, conf) = linea
                x = min(p[0] for p in box)
                items.append((x, texto))
            items.sort(key=lambda t: t[0])
            return "".join(t for _, t in items)

    def leer_numero(self, img_bgr: np.ndarray) -> str:
        return _solo_digitos(self._run(img_bgr))

    def leer_digito(self, img_bgr: np.ndarray) -> str:
        return _solo_digitos(self._run(img_bgr))[:1]


# ─────────────────────────────────────────────────────────────────────────────
# TrOCR (Microsoft, transformer para manuscrito)
# ─────────────────────────────────────────────────────────────────────────────
class TrOCRBackend(OCRBackend):
    nombre = "trocr"

    def __init__(self, modelo: str = "microsoft/trocr-base-handwritten"):
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        import torch
        self.torch = torch
        self.processor = TrOCRProcessor.from_pretrained(modelo)
        self.model = VisionEncoderDecoderModel.from_pretrained(modelo)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)
        self.model.eval()

    def _run(self, img_bgr: np.ndarray) -> str:
        from PIL import Image
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        pixel_values = self.processor(images=pil, return_tensors="pt").pixel_values
        pixel_values = pixel_values.to(self.device)
        with self.torch.no_grad():
            ids = self.model.generate(pixel_values, max_new_tokens=8)
        texto = self.processor.batch_decode(ids, skip_special_tokens=True)[0]
        return texto

    def leer_numero(self, img_bgr: np.ndarray) -> str:
        return _solo_digitos(self._run(img_bgr))

    def leer_digito(self, img_bgr: np.ndarray) -> str:
        return _solo_digitos(self._run(img_bgr))[:1]


def crear_backend(nombre: str) -> OCRBackend:
    """Factory: crea el backend por nombre ('paddleocr' o 'trocr')."""
    nombre = nombre.lower()
    if nombre in ("paddle", "paddleocr"):
        return PaddleBackend()
    if nombre in ("trocr",):
        return TrOCRBackend()
    raise ValueError(f"Backend desconocido: {nombre}. Usa 'paddleocr' o 'trocr'.")
