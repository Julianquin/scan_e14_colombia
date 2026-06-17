# Cómo probar la Fase 0 con tus PDFs reales

Scripts:
- `extractor.py`      → motor de extracción
- `probar_muestra.py` → revisión visual sobre una muestra

## Qué extrae ahora (21 elementos por acta)
1. Las **3 casillas de NIVELACIÓN** de la pág. 1: TOTAL_E11, TOTAL_URNA,
   TOTAL_INCINERADOS  ← el TOTAL_E11 es la referencia del chequeo aritmético
2. Las **13 casillas de VOTACIÓN** de los candidatos (pág. 1 y 2)
3. Los **4 agregados** de la pág. 2: VOTOS EN BLANCO, VOTOS NULOS,
   VOTOS NO MARCADOS y SUMA TOTAL  ← necesarios para el chequeo aritmético
4. El **recuadro de CONSTANCIAS** de la pág. 3 (notas manuscritas de los jurados)

## Instalación (una vez)
```bash
pip install pymupdf opencv-python-headless numpy
```

## Probar
```bash
# Muestra variada: una acta por departamento (recomendado)
python probar_muestra.py e14_pdfs --por-carpeta --salida revision

# O N actas al azar
python probar_muestra.py e14_pdfs --n 20 --salida revision

# Extraer una sola acta a recortes
python extractor.py ruta/al/acta.pdf --crops salida_crops
```

## Colores en el overlay de revisión
- **VERDE**   = casilla de candidato con voto
- **ROJO**    = casilla vacía
- **MAGENTA** = agregado (blanco/nulo/no marcado/suma) con valor
- **AZUL**    = recuadro de constancias con texto

En consola: tabla con CAND (debe ser 13) y CONST (debe ser 1).
ESTADO "OK" = 13 candidatos + 1 constancia.

## Cómo se mide si una casilla tiene número
La heurística de "tinta" ahora elimina las líneas de borde de la celda antes
de medir, así que un recuadro vacío da 0.0% aunque el recorte incluya parte
del marco. Esto lo hace fiable a escala.

## Pendiente para fases siguientes
- Fase 1: OCR de cada recorte → número, y chequeo aritmético
  (suma candidatos + blanco + nulo + no marcado == SUMA_TOTAL == total E-11).
- El recuadro de constancias se leerá para distinguir correcciones legítimas
  de posibles manipulaciones.

## Cuando termines de revisar
Comparte cuántas salieron OK vs REVISAR y 2-3 overlays de casos que fallen.

## ACTUALIZACIÓN — Enfoque híbrido (contornos + plantilla relativa)
El formato E-14 es pre-impreso e idéntico en todo el país, así que las casillas
caen siempre en las mismas posiciones RELATIVAS (fracciones de la página).

El extractor ahora combina dos métodos:
1. Detección por contornos (precisa cuando las líneas están nítidas)
2. Plantilla relativa de respaldo (cuando el escaneo es malo / líneas borrosas)

Para cada candidato y agregado: si la detección por contornos da una caja
cercana a la posición esperada, la usa; si no, cae a la plantilla. Así SIEMPRE
se obtienen las casillas, incluso en actas que antes fallaban.

Esto resuelve los casos del resumen de prueba que daban:
  - "No se segmentó el bloque de agregados en pág. 2"
  - "No se detectaron casillas; el formato puede diferir"

El campo "aviso" indica cuándo se usó la plantilla como respaldo, para que
puedas revisar esos casos con más atención si quieres.
