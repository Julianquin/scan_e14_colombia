# CLAVEROS conserva el color — la restricción del ROADMAP era falsa

**Hallazgo del 2026-08-24.** El ROADMAP asumía que *todos* los E-14 publicados
son escaneos binarizados B/N y concluía que "la presión del trazo y el color de
tinta NO sobreviven". Eso es cierto para DELEGADOS y TRANSMISIÓN, y **falso para
CLAVEROS**.

## La medición

| Ejemplar | Imagen embebida | Formato | Espacio de color | Bits |
|---|---|---|---|---|
| DELEGADOS | 860×2606 | PNG | gris | **1 bit (binarizado)** |
| TRANSMISIÓN | 868×2608 | PNG | gris | **1 bit (binarizado)** |
| **CLAVEROS** | **1260×3897** | JPEG | **RGB** | **8 bits/canal** |

CLAVEROS tiene **2,1× más píxeles** y color real, no un B/N guardado como RGB:
sobre un acta de muestra se midieron **249 niveles de gris distintos** y
saturación con p99=126 (max 255).

Comprobar en cualquier acta:

```python
import fitz
d = fitz.open(pdf)
info = d.extract_image(d[0].get_images(full=True)[0][0])
print(info["width"], info["height"], info["ext"], info["colorspace"], info["bpc"])
```

## Por qué importa: la enmendadura es visible

Caso de TURBO (ANTIOQUIA 01 / 280, zona 3, puesto 01, mesa 2) — uno de los ya
reportados. En el ejemplar a color, bajo los dígitos `113` escritos con
bolígrafo negro grueso se ve un **trazo fantasma** más tenue: escritura previa
sobre la que se volvió a escribir.

Dos poblaciones de tinta claramente separadas en el mismo recorte:

| Población | Intensidad | Área | BGR medio | Saturación |
|---|---|---|---|---|
| Tinta negra densa (bolígrafo) | 0–90 | 5,0 % | (54, 49, 49) | 54 |
| **Trazo fantasma** | 160–205 | **5,6 %** | (202, 193, 187) | 20 |
| Papel | 205–255 | 87,8 % | — | — |

El trazo fantasma ocupa **más área que la tinta que lo tapa**. En el binarizado
de DELEGADOS/TRANSMISIÓN de esa misma mesa no queda ni rastro: la imagen tiene
literalmente 2 niveles y todo trazo colapsa a negro sólido.

## El bug que esto destapa

El pipeline de Fase 0 binariza con **umbral fijo 128**:

```python
_, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)
```

(`e14/extraccion/extractor.py` líneas 119, 154, 348, 450, 854 … y la
clasificación por relleno de `e14/extraccion/posiciones.py`.)

El trazo fantasma vive en **160–205**, es decir **por encima de 128** → el
umbral lo clasifica como papel y lo descarta. Aplicado a CLAVEROS, el pipeline
actual **convierte el ejemplar a color en un equivalente del binarizado y tira
justo la señal que hace único a CLAVEROS**.

Esto no es un fallo de la Fase 0 —fue calibrada para escaneos de 1 bit, donde
es correcto— sino un supuesto que deja de valer al cambiar de ejemplar.

## ⚠️ Resultado NEGATIVO: el trazo fantasma NO es enmendadura

**Probado y descartado el 2026-08-25.** La conclusión de la sección anterior
—que el trazo fantasma bajo los dígitos de Turbo indicaba sobreescritura— **es
incorrecta**. No repetir este intento sin leer esto.

Se construyó un detector de bimodalidad de tinta (tinta densa vs. trazo
intermedio fuera del halo de antialiasing, filtrando líneas de cuadrícula por
alargamiento) y se calibró contra las 4 mesas de Turbo frente a 40 mesas
aleatorias de control (344 casillas):

| | ratio fantasma/tinta |
|---|---|
| Control p50 | 0,09 |
| Control p90 | 0,43 |
| Control p99 | 1,30 |
| Control máx | 1,97 |
| **Turbo (casos "conocidos")** | **0,3 – 1,4** |

**Turbo cae dentro del rango del control.** La métrica no separa nada.

La causa: el óvalo tenue bajo los dígitos aparece **también en mesas control
tomadas al azar** (verificado visualmente), sobre todo bajo los "1". Es un
artefacto generalizado del escaneo a color —traspaso del reverso o de la copia
calcante a través del papel— y no una marca de sobreescritura. El escaneo
binarizado no lo mostraba simplemente porque el umbral lo tiraba, no porque no
estuviera.

### Dos corolarios que sí son sólidos

1. **Los tres ejemplares son papeles físicos DISTINTOS**, no el mismo papel
   escaneado tres veces: la escritura difiere en grosor y forma entre ellos.
   Esto **descarta comparar ejemplares píxel a píxel** tras alinearlos — la
   hipótesis que se iba a probar en la Capa 2.
2. **La binarización de DELEGADOS/TRANSMISIÓN fabrica falsos positivos**: donde
   el color muestra un "1" con bleed-through detrás, el umbral funde ambos en
   una **mancha negra sólida** (visto en Turbo mesa 015, casilla CANDIDATO_01,
   en delegados y transmisión a la vez). Quien compare esos dos ejemplares por
   imagen verá "divergencias" que son artefactos del escaneo.

### Y una advertencia sobre el ground truth

Las 4 mesas de Turbo (01/280, zona 3, puesto 01, mesas 002/003/006/015) están
registradas como "casos de enmendadura reportados", pero **no hay evidencia en
los datos de que lo sean**: la aritmética cuadra razonablemente y las
diferencias visibles entre ejemplares se explican por los artefactos de
binarización de arriba. Antes de usarlas como positivos para calibrar o
entrenar cualquier cosa, hay que confirmar de dónde salió ese reporte y sobre
qué ejemplar/vuelta.

**No hay hoy ni un solo positivo de enmendadura verificado.** Ese es el
bloqueo real del proyecto, no la arquitectura del modelo.

## ⚠️ Segundo resultado NEGATIVO: el color tampoco mejora el OCR

Descartada la vía forense, quedaba la hipótesis razonable de que el color al
menos ayudaría a **leer** mejor los dígitos. **También es falsa.**

Experimento controlado (`e14/ocr/clasificador_color.py --gris`): misma
arquitectura, misma resolución 48x48, mismas etiquetas; la única variable es si
el modelo ve color o el gris replicado a 3 canales. Métrica = % de actas que
CUADRAN al releer 1.500 actas **no vistas** (no la accuracy por dígito, que
está sesgada por el autoetiquetado):

| Entrada | % de cuadre |
|---|---|
| RGB (color) | 42,7 % |
| **Gris** | **46,9 %** |

El color **empeora ~4 puntos**: aporta variabilidad irrelevante (tono del
papel, iluminación, tinte del JPEG) sobre la que el modelo sobreajusta.

### Lo que sí funcionó

Comparación limpia sobre el **mismo tramo** de 1.500 actas no vistas
(12.000–13.500 — hay que comparar siempre en el mismo tramo: distintos
departamentos tienen distinta calidad de escaneo y el mismo modelo saca 46,9 %
en un tramo y 36,3 % en otro):

| Modelo | % de cuadre |
|---|---|
| `digitnet.pt` 1ra vuelta (binario 28x28) | 17,5 % |
| Gris 48x48, ronda 1 (1.045 actas) | 36,3 % |
| **Gris 48x48, ronda 2 bootstrap (4.880 actas)** | **38,3 %** |

**2,2× sobre la base.** La ganancia viene de reentrenar sobre CLAVEROS y de la
resolución (28x28 → 48x48 sin binarizar), no del color.

El bootstrapping (etiquetar con el mejor modelo, reentrenar, repetir) da
**rendimientos decrecientes**: +2 puntos con 4,7× más datos. El cuello de
botella ya no son los datos de entrenamiento.

**Y el techo no es 100 %:** un acta con un error aritmético real —la denuncia
#1 que el proyecto persigue— *nunca* debe cuadrar. Parte del % restante es
señal, no fallo del OCR. Confundir ambas cosas llevaría a "arreglar" el modelo
hasta que tape justo lo que hay que detectar.

## Consecuencias para el diseño

1. **CLAVEROS es el ejemplar forense**, no solo uno más para el cruce. Es
   además el que firma la comisión escrutadora, así que es el jurídicamente
   más relevante.
2. El forense de enmendaduras debe leer **el JPEG original a color**, sin pasar
   por la binarización de Fase 0. La Fase 0 sigue sirviendo para *localizar* la
   casilla (geometría); lo que no debe hacerse es leer los píxeles ya
   binarizados.
3. El recorte que alimente al detector debe guardarse en **RGB 8 bits**, no en
   el `28×28` binario del dataset de dígitos actual.
4. Para el **voto del exterior (dep. 88) no hay CLAVEROS**
   (ver [INTEGRIDAD_DESCARGA.md](INTEGRIDAD_DESCARGA.md)): ahí el forense de
   color no es posible y solo queda el cruce binarizado a 2 vías. Hay que
   declararlo como limitación.
