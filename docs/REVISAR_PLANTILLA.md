# Localización de los agregados — celdas + líneas reales (anclaje eliminado)

Los agregados (BLANCO/NULO/NO_MARCADO/SUMA_TOTAL) se localizan con una sola
estrategia robusta y un respaldo simple:

## Estrategia única: "celdas+lineas"
`localizar_bloque_agregados` encuentra:
- Las 5 líneas horizontales REALES del bloque (con reintento a umbral más laxo
  si la rejilla es tenue; busca 5 líneas con separaciones regulares en una
  franja amplia 0.68-0.95h, así tolera bloques desplazados).
- La línea vertical que separa etiquetas de votos (fija la X).
Cada fila se recorta de línea a línea → inmune al desfase.

## Respaldo: "plantilla" (fracciones fijas)
Solo si no se localizan las 5 líneas. Aproxima la posición SIN el desfase de
media fila que producía el viejo anclaje al candidato 13.

## El método "anclaje" fue ELIMINADO
En las pruebas, el anclaje al candidato 13 era el ÚNICO que producía el desfase
de media fila. Se eliminó por completo. En una prueba de 500 actas, 496 usaron
"celdas+lineas" y solo 4 caían al anclaje (con error). Ahora esas 4 usan
"plantilla" (sin desfase) o, idealmente, se diagnostican para que logren
"celdas+lineas".

## Diagnosticar las que no logran celdas+lineas
Las actas que caen al respaldo "plantilla" son las que no pudieron usar la
estrategia buena. Para entender POR QUÉ falla cada una:
```bash
python diagnosticar_agregados.py e14_pdfs/PRE/ruta/acta1.pdf e14_pdfs/PRE/ruta/acta2.pdf
```
Para cada acta muestra:
- Cuántas líneas horizontales detecta (con dos umbrales).
- Si encuentra las 5 líneas regulares y sus separaciones.
- El separador vertical detectado.
- El ORIGEN final (`celdas+lineas` o `plantilla`).

Si una acta sigue cayendo al respaldo, el diagnóstico indica la causa:
- No detecta suficientes líneas (rejilla muy tenue) → bajar más el umbral.
- Las separaciones no son regulares (filas de altura muy distinta) → ajustar rango.
- El bloque está fuera de la franja 0.68-0.95 → ampliar franja.

## Revisar
```bash
python revisar_plantilla.py resultados/casillas_e14.csv --n 500 --salida rev
python revisar_plantilla.py --pdfs acta1.pdf acta2.pdf --salida rev
```
