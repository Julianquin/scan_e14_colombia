# Fase 1 — OCR con GPU gratuita en Kaggle (TrOCR-handwritten)

El OCR local en CPU resultó frágil y lento. La solución: separar el trabajo.
La extracción (Fase 0) corre en tu CPU; el OCR corre en la GPU gratuita de
Kaggle sobre los recortes ya extraídos.

## Por qué Kaggle
30 h/semana de GPU, sesiones de hasta 12 h, datasets persistentes de hasta
100 GB. Subes los recortes una vez y los reutilizas. Más estable que Colab para
trabajos largos por lotes.

## FLUJO COMPLETO

### 1. (LOCAL) Exportar los recortes de casillas con número
```bash
cd fase1
# Prueba con pocas primero
python exportar_recortes.py ../e14_pdfs --salida recortes_ocr --limite 1000
# Luego todas
python exportar_recortes.py ../e14_pdfs --salida recortes_ocr
```
Solo exporta casillas CON número (las vacías = 0, no necesitan OCR). Genera la
carpeta `recortes_ocr/` con los PNG + `indice_recortes.csv`.

### 2. (LOCAL) Comprimir y subir a Kaggle
```bash
zip -r recortes_ocr.zip recortes_ocr
```
En Kaggle: crea un Dataset (Datasets → New Dataset → Upload recortes_ocr.zip).

### 3. (KAGGLE) Correr el OCR en GPU
- Crea un Notebook nuevo, añade tu dataset (Add Data).
- Settings → Accelerator → **GPU T4**.
- Sube `ocr_trocr_kaggle.ipynb` (o pega `ocr_trocr_kaggle.py`).
- Ajusta `RECORTES_DIR` a la ruta donde Kaggle montó el dataset
  (mira en el panel derecho, algo como /kaggle/input/recortes-ocr/recortes_ocr).
- Run All. Genera `/kaggle/working/numeros_leidos.csv`.
- Descárgalo (panel Output).

Con GPU T4, TrOCR-handwritten lee del orden de decenas de recortes por segundo,
así que las 122k actas son cuestión de horas, no semanas.

### 4. (LOCAL) Combinar con el chequeo aritmético
```bash
python combinar_resultados.py numeros_leidos.csv --salida actas_verificadas.csv
```
Produce, por mesa: los 21 valores + chequeo (suma candidatos+blanco+nulo+
no_marcado == SUMA_TOTAL == TOTAL_E11) + nivel de alerta (ALTA/MEDIA/NINGUNA),
ordenado con las más sospechosas primero.

## Recordatorio
Una alerta NO significa fraude: puede ser fraude, error de diligenciamiento O
error de OCR. Marca para revisión humana con el recorte + las constancias.

## Nota sobre precisión de TrOCR
TrOCR-handwritten es bueno con manuscrito, pero no perfecto con dígitos sueltos.
Tras la primera corrida, revisa unas cuantas actas que "no cuadren" para ver si
es fraude/error real o fallo de lectura. Si la tasa de error de OCR es alta,
podemos afinar (preprocesado de recortes, o un CNN de dígitos como alternativa).

## Preprocesado de recortes (aislar los dígitos)
Los recortes exportados pasan por `limpiar_para_ocr()`, que se queda SOLO con
los dígitos y recorta a su bounding box. En vez de cortar por columnas (frágil),
clasifica cada componente conectado de tinta y descarta el ruido de borde:

- **Barras de borde** (de la celda o de las vecinas): componentes muy altos y
  estrechos (relación alto/ancho > 4) que cruzan casi toda la altura.
- **Residuos / fragmentos**: área mucho menor que la del dígito mayor.
- **Puntos pre-impresos** (incluso los gruesos): son manchas SÓLIDAS que llenan
  casi todo su bounding box (relleno > 0.62), mientras un dígito manuscrito es
  un trazo que deja huecos (relleno 0.18-0.35). Esta señal de "relleno" separa
  limpiamente puntos de dígitos.

Validado: 9/9 recortes reales quedan con exactamente el nº de dígitos correcto,
sin barras, sin puntos, sin residuos. Esto evita errores del OCR como leer
104 → 1104 por un residuo a la izquierda.

