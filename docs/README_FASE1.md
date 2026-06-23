# Fase 1 — Lectura de números (OCR) + chequeo aritmético

Sobre los recortes que produce la Fase 0, lee el número manuscrito de cada
casilla y verifica que el acta cuadre aritméticamente. Ataca las denuncias
**#1** (errores aritméticos) y **#2** (espacios sin anular). Ver el diseño
completo en [../docs/ROADMAP.md](../docs/ROADMAP.md).

## Documentos de la fase
- **[FLUJO_KAGGLE.md](FLUJO_KAGGLE.md)** — pipeline de OCR en GPU (Kaggle): por
  qué Kaggle y los 4 pasos exportar → subir → correr → combinar.
- **[POSICIONES.md](POSICIONES.md)** — registro fiel del estado de cada posición
  de una casilla (dígito/punto/guion/vacío) y la bandera `espacio_sin_anular`.

## Módulos
- `exportar_recortes.py`   — exporta los recortes de casillas con número y un
                             `indice_recortes.csv` (entrada del OCR en Kaggle).
- `posiciones.py`          — registra posiciones por casilla (ver POSICIONES.md).
- `segmentacion.py`        — aísla dígitos / limpia el recorte (sin OCR).
- `ocr_backends.py`        — backends intercambiables: PaddleOCR y TrOCR (local).
- `ocr_trocr_kaggle.{py,ipynb}` — OCR TrOCR-handwritten en GPU (Kaggle).
- `chequeo_aritmetico.py`  — verifica suma(candidatos)+B+N+NM == SUMA_TOTAL ==
                             TOTAL_E11.
- `combinar_resultados.py` — combina los números leídos con el chequeo aritmético.
- `comparar_ocr.py`, `test_ocr_una_acta.py`, `diagnostico_nivelacion.py` —
                             herramientas de prueba/diagnóstico.

## Backend de OCR
El backend **en producción es TrOCR-handwritten en Kaggle GPU** (flujo por
lotes, ver FLUJO_KAGGLE.md). **PaddleOCR se evaluó y se descartó** en CPU (bug
oneDNN + ~43 GB de RAM). `ocr_backends.py` mantiene ambos por si se quiere
reproducir la comparación en local.

Instalación local (opcional, ver `../requirements-fase1.txt`):
```bash
pip install -r ../requirements-fase1.txt   # transformers torch pillow (TrOCR)
```

## Las dos estrategias de lectura (las comparamos)
1. **Dígito a dígito**: `segmentar_digitos()` aísla cada cifra y el OCR lee una
   sola cifra cada vez. Validado: detecta el nº correcto de dígitos en 9/9 casos
   de prueba (incluye casos con puntos pre-impresos).
2. **Número completo**: `preparar_numero()` limpia el recorte y el OCR lee el
   número entero de una vez.

### Comparar cuál lee mejor
```bash
cd fase1
# Modo coherencia (no necesita etiquetas): usa el chequeo aritmético como proxy.
# La estrategia con más actas que CUADRAN es la mejor lectora.
python comparar_ocr.py ../e14_pdfs --backend trocr --n 100
```
Genera `comparacion_ocr.csv` y un resumen: cuántas actas cuadran con cada
estrategia y el tiempo de cada una.

## Chequeo aritmético
La identidad que se verifica:
```
suma(cand_01..cand_13) + BLANCO + NULO + NO_MARCADO == SUMA_TOTAL == TOTAL_E11
```
- Casilla vacía = 0 (la segmentación lo detecta y no llama al OCR).
- Niveles de alerta: ALTA (no cuadran ni suma ni E-11), MEDIA (falla uno),
  NINGUNA (cuadra), INCOMPLETO (faltan lecturas).
- IMPORTANTE: una inconsistencia puede ser fraude, error de diligenciamiento
  O error de OCR. Marca para revisión; no dictamina.

## Validado hasta ahora (sandbox, sin OCR real)
- Segmentación: 9/9 casos con el nº correcto de dígitos.
- Chequeo aritmético: el acta de ejemplo (mesa 026 Leticia) cuadra
  perfectamente (124 candidatos + 2 blanco = 126 = SUMA_TOTAL = TOTAL_E11).

## Siguiente paso recomendado
Corrida de ~500 actas en Kaggle para medir la tasa real de lectura de TrOCR y
decidir si basta o si conviene afinar (preprocesado o un CNN de dígitos).
