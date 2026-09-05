# Datos oficiales MMV — preconteo y escrutinio mesa a mesa

Los archivos **MMV** (mesa a mesa con votos) que publica la Registraduría para
auditores. Cubren **ambas vueltas** y traen los **dos conteos oficiales** de cada
mesa, además del censo y los topes legales.

Es la pieza que faltaba para la Fase 2 del [ROADMAP](ROADMAP.md): permite
auditar sin depender del OCR.

## Qué hay dentro

`data/manifests/MMV_Presidente{1V,2V}_2026.zip` →

| Fichero | Contenido |
|---|---|
| `PRE*_MMV_9999_PRECONTEO.txt` | Votos por mesa del **preconteo** (noche electoral, informativo) |
| `_ficheros_MMV_4_MMV_9999_ESCRUTINIO.csv` | Votos por mesa del **escrutinio** (acto jurídico definitivo) |
| `HASH_*.txt` | MD5 / SHA-1 / SHA-256 / SHA-512 oficiales (UTF-16) |
| `Estructuras Basicas (1808).pdf` | Especificación de todos los formatos |
| `ArchivosBasicos…zip` | DIVIPOL, CANDIDATOS, PARTIDOS, **INDICADORES** |

**Los cuatro ficheros de datos verifican contra su SHA-256 oficial.** Eso es lo
que hace el análisis reproducible por un tercero: cualquiera puede recalcular el
hash y confirmar que se partió del fichero oficial sin alterar.

```bash
python -m e14.oficial.mmv verificar data/manifests/MMV_2V/MMV_Presidente2V_2026
python -m e14.oficial.mmv resumen   data/manifests/MMV_2V/MMV_Presidente2V_2026
```

### El tope legal por mesa (INDICADORES)

`validacion/limite_habilitados.py` pedía confirmar a mano un `--cap-mesa`.
Ya no hace falta: el fichero INDICADORES lo declara por tipo de puesto.

| Código | Tipo de puesto | Máx. votantes/mesa |
|---|---|---|
| 1 | Mesas Nacional | **360** |
| 3 | Mesas Exterior 700 | 700 |
| 4 | Puesto Censo 500 | 500 |
| 5 | Puesto Censo 800 | 800 |
| 8 | Puesto Censo 1200 | 1200 |
| 9 | Exterior lunes a sábado | 9999 |

DIVIPOL dice qué indicador tiene cada puesto. Con eso, **votos > tope legal** es
una imposibilidad objetiva, no una lectura discutible.

### Formatos (resumen de la especificación)

**PRECONTEO** — ancho fijo, 38 caracteres:
`dep(2) muni(3) zona(2) puesto(2) mesa(6) jal(2) comunicado(4) circ(1) partido(5) candidato(3) votos(8)`

**ESCRUTINIO** — separado por `;`:
`9999(4) dep(2) muni(3) zona(3) puesto(2) mesa(6) comuna(2) corporacion(3) circ(1) partido(4) candidato(3) votos(8)`

⚠️ Dos campos cambian de anchura entre formatos y hay que normalizar para
cruzarlos: **zona** (2 vs 3 dígitos) y **partido** (5 vs 4). `mmv.clave_mesa` ya
lo hace. El **puesto** es alfanumérico en la especificación — no convertirlo a
entero.

Los códigos de candidato **996 / 997 / 998** (con partido 0) son
BLANCO / NULO / NO_MARCADO, no personas.

## Resultado oficial de 2ª vuelta

| | Votos | % |
|---|---|---|
| ABELARDO DE LA ESPRIELLA | 12.960.166 | 49,19 % |
| IVÁN CEPEDA CASTRO | 12.708.312 | 48,24 % |
| Blanco / nulo / no marcado | 676.482 | 2,57 % |
| **Total** | **26.344.960** | |

**Margen: 251.854 votos = 0,96 % — 2,1 votos por mesa.**

Ese número es el marco de todo el proyecto: con un margen así, la pregunta útil
no es "¿hubo fraude?" sino **"¿cuántos votos están en disputa por anomalías,
frente a 251.854?"**.

(1ª vuelta, para comparar: margen 662.222 = 2,76 %, 5,4 votos por mesa.)

## Caso de uso 1 — auditoría preconteo ↔ escrutinio

```bash
python -m e14.oficial.auditar data/manifests/MMV_2V/MMV_Presidente2V_2026 \
    --out data/segunda_vuelta/_oficial/auditoria_2v
```

**No depende del OCR.** Cruza dos ficheros oficiales verificados por hash, así
que da resultados firmes hoy. El OCR entra después, para dirimir cuál de los dos
conteos acierta en las mesas señaladas.

### Advertencia imprescindible

**Que el escrutinio cambie el preconteo NO es una anomalía.** El escrutinio es
el acto jurídico que existe precisamente para corregir el conteo informal de la
noche electoral. Encontrar diferencias es lo normal. Lo que se audita es
*cuántas*, *de qué tipo* y **hacia dónde**.

### Tipologías

| | Qué es |
|---|---|
| `ANULADA` | La mesa queda en 0 en el escrutinio (causal de anulación) |
| `PERMUTACION` | Los **mismos valores** repartidos entre otros candidatos. Con 2 candidatos, el intercambio de columnas al transcribir. **No cambia el total de la mesa, así que ninguna suma la delata: sólo la comparación la revela** |
| `APARECE` | Sin votos en preconteo, con votos en escrutinio |
| `OTROS` | Resto de cambios de magnitud |

### Resultados

**2ª vuelta — 1.151 mesas cambiaron (0,94 %)**

| Tipología | Mesas | Efecto en el margen |
|---|---|---|
| OTROS | 1.106 | +602 |
| **PERMUTACION** | **28** | +406 |
| ANULADA | 15 | −209 |
| APARECE | 2 | −116 |

- Efecto **neto** sobre el margen: **+683 votos (0,271 % del margen)**.
- Votos movidos en total: 19.943.
- **Direccionalidad: todo compatible con error de transcripción.** En
  PERMUTACION, 18 favorecen a Espriella y 10 a Cepeda (p = 0,186).

**Verificado contra el papel:** en 2 de las 28 permutaciones se fue al acta E-14
escaneada. En ambas **el preconteo tenía el error y el escrutinio lo corrigió**
(mesas `16/1/1/42/15` y `23/67/1/06/9`). El sistema funcionó.

**1ª vuelta (grupo de control) — 24.227 mesas cambiaron (19,85 %)**

**Veintiún veces más correcciones que en 2ª vuelta.** Merece explicación antes de
sacar conclusiones: 13 candidatos en vez de 2 dan muchas más oportunidades de
error de transcripción, y el preconteo de 1ª vuelta pudo procesarse en
condiciones distintas. Es una diferencia objetiva y llamativa, no un hallazgo.

## El test de direccionalidad

Un error humano no tiene preferencia política: debería repartirse según lo que
el mecanismo predice. Se corre un **test binomial exacto por candidato**, con
corrección de Bonferroni.

**La hipótesis nula depende del mecanismo de cada tipología** — esto costó dos
correcciones y conviene no repetirlas:

- `PERMUTACION` → **uniforme (1/k)**: los valores se barajan, así que cada
  candidato tiene la misma probabilidad de quedarse con el mayor.
- El resto → **proporcional a la votación**: son errores de magnitud sobre los
  votos existentes, y quien más votos tiene, más tiene en juego.

Errores cometidos y corregidos (documentados para que no se repitan):

1. Usar **p = 0,5** con 13 candidatos declaraba "asimetría significativa"
   siempre, porque ningún candidato llega al 50 %. Falso positivo garantizado.
2. Usar la H0 **proporcional en PERMUTACION** marcaba a todos los candidatos
   pequeños: recibir el valor de un candidato grande los "favorece" muchísimo en
   términos relativos. Artefacto del mecanismo, no señal.
3. No excluir a los **candidatos retirados** (0 votos) metía ceros estructurales
   en el test: nunca pueden salir favorecidos.

### Limitación conocida

La H0 uniforme de `PERMUTACION` supone que los valores se barajan entre **todos**
los candidatos. Si en la práctica se intercambian sobre todo entre **casillas
contiguas del formulario**, los vecinos saldrán sobre-representados sin que eso
signifique nada. Con 2 candidatos (2ª vuelta) la limitación no aplica.

Con esa salvedad, en 1ª vuelta sólo Cepeda queda marcado tras Bonferroni
(26 permutaciones a favor frente a 14,3 esperadas, p = 0,0031, α = 0,0045):
marginal, y a verificar contra el papel antes de darle cualquier peso.

## Qué NO se puede concluir

- **Intención, nunca.** Una permutación no distingue dedo torpe de dolo.
- **Una mesa aislada no prueba nada.** El valor está en el agregado.
- **Que el escrutinio corrija al preconteo es su función**, no una irregularidad.
- Estas mesas son **candidatas a revisión humana**, no hallazgos de fraude.

## Caso de uso 2 — dirimir contra el papel

```bash
python -m e14.oficial.dirimir \
    --auditoria data/segunda_vuelta/_oficial/auditoria_2v.mesas.csv \
    --mmv       data/manifests/MMV_2V/MMV_Presidente2V_2026 \
    --actas     data/segunda_vuelta/e14_pdfs_claveros \
    --modelo    models/digitnet_2v_gris.pt \
    --tipologias PERMUTACION,ANULADA \
    --out       data/segunda_vuelta/_oficial/dirimidas_2v
```

Cuando preconteo y escrutinio discrepan, sólo el acta dice cuál coincide con lo
que firmaron los jurados.

### No lee el acta "a ciegas"

El OCR ronda el 38 % de cuadre, así que leer y comparar sería frágil. Pero aquí
no hay que leer un número libre: hay que **decidir entre dos hipótesis
conocidas**. Eso permite usar la distribución completa del clasificador en vez
del `argmax` — se compara `log L(preconteo)` contra `log L(escrutinio)` sobre
las posiciones **discriminantes**, y el margen entre ambas es la confianza.
Si el margen no supera `--umbral`, el veredicto es `REVISAR_A_MANO`.

Se descarta la posición de **centenas** cuando algún valor es < 100: ahí va el
aspa de anulación, que el clasificador lee como `7` (ver [OCR_2V.md](OCR_2V.md)).

⚠️ **Las mesas ANULADAS no son dirimibles.** El escrutinio las pone en 0 y el
papel muestra los votos emitidos, así que "coincide con el preconteo" es cierto
*por definición* y no informa de nada. Anular es una decisión **jurídica**, no
una corrección de lectura: para revisarlas hay que leer la constancia de la
página 2 del acta. Se reportan aparte.

⚠️ **La casilla `CANDIDATO_0N` del acta es el candidato de CÓDIGO N**, el número
impreso junto a su foto — no el N-ésimo por votación. En 2ª vuelta el código 1
es Cepeda y el 2 De la Espriella, mientras que por votación el orden es el
inverso: mapear por votación invierte las hipótesis y da todos los veredictos al
revés.

### Resultado — 2ª vuelta

De las 43 mesas señaladas (`PERMUTACION` + `ANULADA`):

| Veredicto | Mesas |
|---|---|
| COINCIDE_ESCRUTINIO | 26 |
| ANULADA_NO_DIRIMIBLE | 15 (3.073 votos emitidos) |
| **COINCIDE_PRECONTEO** | **1** |
| SIN_POSICION_DISCRIMINANTE | 1 |

**De las 27 dirimibles, el papel respalda al escrutinio en 26 (96 %).** Es lo
esperado: corregir el preconteo es su función.

### El caso que sí merece revisión

**Mesa `31/067/0/01/11`** (VALLE, zona 0, puesto 01, mesa 11) — `PERMUTACION`,
margen de log-verosimilitud 11,15 (muy confiado), **verificado a ojo sobre el
recorte**:

| | Cepeda | De la Espriella |
|---|---|---|
| Preconteo | 125 | 95 |
| Escrutinio | 95 | 125 |
| **Acta (papel)** | **125** | **✱95** |

Aquí **el escrutinio se apartó del acta**, al revés que en los otros 26 casos:
30 votos pasaron de Cepeda a Espriella, 60 de impacto en el margen.

**Proporción honesta: 60 votos sobre un margen de 251.854 (0,024 %).** No altera
nada del resultado. Su valor es metodológico: el pipeline redujo 122.017 mesas a
un caso concreto, con la evidencia en papel adjunta, listo para que una persona
lo revise. Eso es exactamente el producto — triaje auditable, no veredictos.

## E5 · Censo y topes legales — RESULTADO (2026-09-04)

Corrido sobre las 122.020 mesas y 14.438 puestos de 2ª vuelta, con la 1ª como
control. **No depende del OCR**: todo sale del escrutinio oficial.

### Chequeo A — votos por mesa > tope legal: **0 de 122.020**

La restricción legal por mesa (360 nacional / 500 / 800 / 1200 censo / 700
exterior) **se cumple sin excepción**. Máximo observado: 767 votos, en un puesto
cuyo tope es 9999.

### Chequeo B — votos del puesto > censo: 57 puestos (0,39 %)

Pero al desglosarlos, ninguno resiste como hallazgo:

| Tipo | Puestos | Exceso (votos) | Interpretación |
|---|---|---|---|
| **Consulados** | 13 | **1.667 (93 %)** | ⚠️ **falso positivo de la métrica** — ver abajo |
| Rural diminuto (censo ≤ 30) | 16 | 53 | censo de 3–30 personas; ±5 votos da % absurdos |
| Cárceles / reclusión | 6 | 18 | población reclusa cambia entre censo y elección |
| Resto | 22 | 63 | excesos de **1 a 6 votos**, Pacífico (Chocó, Tumaco, Guapi) |

**Total 1.801 votos = 0,715 % del margen.** Quitando los consulados: **134 votos
= 0,05 %**.

### ⚠️ El censo del exterior no es un censo

Medido: el **73,6 %** de los puestos de consulados tiene censo múltiplo exacto de
100 (600, 800, 1500, 2400, 3000), frente al **1,0 %** en el resto del país. Es
**capacidad administrativa** (mesas × cupo), no personas inscritas. Aplicarles el
chequeo B genera falsos positivos sistemáticos, así que el notebook los separa y
**no los cuenta**.

### El control de 1ª vuelta es concluyente

| | 1ª vuelta | 2ª vuelta |
|---|---|---|
| Mesas que superan el tope legal | 0 | 0 |
| Puestos con votos > censo | 33 | 57 |
| **Puestos que exceden en AMBAS** | **27** | |

De los 30 que exceden sólo en 2ª vuelta, **8 son consulados** y aportan 617 de los
667 votos (92 %). Los 22 restantes suman ~50 votos, con excesos de 1 a 6.

### Veredicto

**E5 sale limpio.** No hay evidencia de imposibilidad física atribuible a esta
elección. Lo que aparece se explica por censo desactualizado en zonas de alta
movilidad (Pacífico), población reclusa, puestos rurales diminutos y una métrica
que no aplica al exterior — y **27 de 57 casos están en ambas vueltas**, o sea que
son estructurales del censo, no de la 2ª vuelta.

Esto es **publicable como verificación**: *"se comprobó la restricción física
sobre 122.020 mesas y 14.438 puestos, con dos fuentes de censo independientes que
coinciden al 100 %, y se cumple"*.

## Siguiente paso

- **Dirimir las 1.106 mesas `OTROS`** — ya desbloqueado: el OCR pasó de 69,2 % a
  **96,9 %** de acierto por casilla al añadir la clase RELLENO, y `dirimir.py`
  vuelve a usar la posición de centenas. Notebook listo:
  [`notebooks/dirimir_otros_2v.ipynb`](../notebooks/dirimir_otros_2v.ipynb).
- Leer las **constancias (página 2)** de las 15 mesas anuladas: es donde consta
  la causal, y es lo único que permite evaluarlas.
- Correr el mismo flujo sobre 1ª vuelta (157 permutaciones).
