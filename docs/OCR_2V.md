# OCR de 2ª vuelta — estado, resultados y el cuello de botella

Estado del clasificador de dígitos sobre CLAVEROS (2ª vuelta), a 2026-08-25.
Para el experimento de color (y por qué NO se usa color) ver
[FORENSE_COLOR.md](FORENSE_COLOR.md).

## Resultados medidos

Todo sobre el **mismo tramo** de 1.500 actas no vistas (12.000–13.500).
Comparar siempre en el mismo tramo: distintos departamentos tienen distinta
calidad de escaneo, y el mismo modelo saca 46,9 % en un tramo y 36,3 % en otro.

| Modelo | % de actas que cuadran |
|---|---|
| `digitnet.pt` (1ª vuelta, binario 28×28) | 17,5 % |
| gris 48×48, ronda 1 (1.045 actas) | 36,3 % |
| **`digitnet_2v_gris.pt`, ronda 2 (4.880 actas)** | **38,3 %** |

2,2× sobre la base. La ganancia vino de reentrenar sobre CLAVEROS y de subir la
resolución (28×28 binario → 48×48 en gris sin binarizar), **no del color**.

## ⚠️ El cuello de botella: las aspas de anulación

En el E-14 las casillas anuladas se marcan con un **aspa (✱)**. Regla oficial:
todo-aspas = 0; un número a la derecha del aspa es ese número (`✱84` = 84).

**El clasificador tiene 10 clases (0–9) y ninguna para el aspa.** Forzado a
elegir un dígito, elige **`7`** de forma sistemática —el aspa tiene trazos
diagonales— y encima **con confianza de 0,92–0,98**. Una casilla `✱✱✱` que vale
0 se lee `777`.

Medido sobre 2.700 casillas (300 actas): **441 = 16,3 %** se leen con 2 o más
dígitos `7` de alta confianza. La distribución no deja dudas:

| Casilla | casos | |
|---|---|---|
| NULO | 102 | ← suelen ir anuladas |
| BLANCO | 100 | ← suelen ir anuladas |
| NO_MARCADO | 98 | ← suelen ir anuladas |
| TOTAL_INCINERADOS | 97 | ← suelen ir anuladas |
| CANDIDATO_02 | 27 | |
| CANDIDATO_01 | 7 | |
| SUMA_TOTAL | 6 | |
| TOTAL_URNA | 2 | ← siempre llevan número real |
| TOTAL_E11 | 2 | ← siempre llevan número real |

Las cuatro casillas que suelen ir anuladas concentran el **90 %** de los casos;
las dos que siempre llevan número real casi no aparecen.

### Por qué no se arregla con más datos

El autoetiquetado (`dataset_color.py`) **solo conserva las actas que cuadran**,
es decir justamente aquellas donde el modelo ya leía bien el aspa. Los casos
donde falla **nunca entran al dataset**.

**El autoetiquetado por aritmética es ciego a su propio error sistemático.**

Eso explica los rendimientos decrecientes del bootstrapping: +2 puntos con 4,7×
más datos. Más rondas no van a arreglarlo, porque el error se auto-excluye del
conjunto de entrenamiento en cada ronda.

## ⚠️ Agujero del chequeo aritmético: el acta todo-ceros

**Encontrado el 2026-08-25 al entrenar con clases extra.**

Un acta leída como **todos ceros** satisface la aritmética de forma trivial:
`0 + 0 + 0 == 0 == 0`. El chequeo dice **"cuadra"**.

Consecuencias, ambas reales y observadas:

1. **La métrica de cuadre se puede falsear.** Un modelo colapsado que predice
   siempre la misma clase sacó **100 % de cuadre** siendo completamente inútil
   (`val_acc` = 0,0000). Sin el filtro, ese 100 % parecería un éxito histórico.
2. **El autoetiquetado se auto-envenenaría.** Esas actas entrarían al dataset
   con 27 etiquetas `0` falsas, reforzando el colapso en la ronda siguiente.

**Arreglado** en `dataset_color.py` (`construir`) y en la función `medir_cuadre`
del notebook de entrenamiento: si `TOTAL_E11 == 0` y `SUMA_TOTAL == 0` el acta se
descarta como degenerada y se reporta aparte. Una mesa sin votantes en el E-11 no
existe.

Verificado que **no afecta a lo ya medido**: el `digitnet_2v_gris.pt` produce
**0 actas degeneradas** sobre el tramo de 1.500, y su 38,3 % se mantiene idéntico
con el filtro puesto.

Queda pendiente decidir si el mismo guard debe vivir dentro de
`chequeo_aritmetico.chequear()` —que hoy devuelve `cuadra_suma=True` para el
caso todo-ceros— o seguir siendo responsabilidad de quien lo llama.

## El arreglo con más retorno

**Añadir clases al clasificador**: `aspa`, `guion` y `vacío`, además de los 10
dígitos. Es lo que estaba pedido desde el principio ("detectar dígitos,
asteriscos, equis o guiones") y resulta ser el cuello de botella principal, no
un extra.

Notas para hacerlo:

- Las etiquetas **no** pueden salir del autoetiquetado por aritmética, por lo
  de arriba. Hace falta etiquetar a mano una muestra —cientos, no miles— de
  casillas de NULO / BLANCO / NO_MARCADO / TOTAL_INCINERADOS, que es donde se
  concentran.
- `posiciones.py` ya clasifica por relleno de trazo en `digito`/`punto`/
  `guion`/`vacio` con heurísticas. Sirve para **preseleccionar** candidatos a
  etiquetar (aprendizaje activo), no como verdad.
- Con clases explícitas, la lectura deja de ser "3 dígitos" y pasa a ser
  "3 símbolos + regla de interpretación" (`✱84` → 84, `✱✱✱` → 0).
- **Cuidado con los pesos de clase**: una clase recién creada con 0-2 ejemplos
  recibe un peso enorme (`n_total/n_clase`), el loss se va a ~69 y el
  entrenamiento colapsa. Hay que acotarlos (clip) y poner a 0 los de las clases
  sin ejemplos.

### Probado end-to-end, pero faltan etiquetas

El flujo de 13 clases está validado con **32 aspas + 2 guiones** etiquetadas a
mano. Resultado: **32,0 % de cuadre frente a ~34 % del modelo de 10 clases** —
es decir, *ligeramente peor*. Esperable: 32 ejemplos no alcanzan para aprender
una clase nueva frente a 58.902 ceros, y añadir clases mal cubiertas sólo mete
ruido. El mecanismo funciona; hacen falta **cientos** de etiquetas para que la
aguja se mueva.

Y ojo al reunir candidatos: filtrar por "el modelo lee 7 con confianza > 0,9"
trae **una mezcla**, no sólo aspas — en una muestra de 60 revisada a ojo había
~32 aspas, ~24 sietes legítimos y 2 guiones. Hay que etiquetar mirando, no
asumir que todo candidato es aspa.

## Reproducir

Todo esto es explorable en
[`notebooks/banco_pruebas_2v.ipynb`](../notebooks/banco_pruebas_2v.ipynb) —
sección 5.2 para el diagnóstico de las aspas.

```bash
# dataset autoetiquetado por aritmética
python -m e14.ocr.dataset_color construir data/segunda_vuelta/e14_pdfs_claveros \
    --salida datos_r1.npz --limite 6000 --dev cuda

# entrenar (SIEMPRE --gris)
python -m e14.ocr.clasificador_color entrenar datos_r1.npz \
    --modelo models/digitnet_2v_gris.pt --epochs 40 --gris

# medir el cuadre sobre un tramo NO usado en entrenamiento
python -m e14.ocr.clasificador_color evaluar data/segunda_vuelta/e14_pdfs_claveros \
    --modelo models/digitnet_2v_gris.pt --desde 12000 --limite 1500 --gris
```
