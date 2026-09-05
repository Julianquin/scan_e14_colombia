# El caso Turbo (Antioquia 01/280, zona 3, puesto 01)

Análisis de las mesas que circularon públicamente como "alteraciones en los
formularios E-14". Es el caso de referencia del proyecto: lo que se aprenda aquí
define cómo se detectan los demás.

## Lo que muestra la denuncia

Compara el ejemplar de **DELEGADOS** con el de **CLAVEROS** de la misma mesa:

| Mesa | Casilla | CLAVEROS | DELEGADOS (denuncia) |
|---|---|---|---|
| 003 | Cepeda | `138` | mancha + `38` |
| 003 | Espriella | `✱93` | `793` |
| 006 | Cepeda | `121` | mancha + `21` |
| 006 | Espriella | `101` | `201` |
| 015 | Cepeda | `119` | mancha + `19` |
| 015 | Espriella | `✱42` | `142` |

El patrón denunciado es coherente y siempre en el mismo sentido: **Cepeda pierde
el dígito de centenas y Espriella lo gana**.

## Qué dicen los tres ejemplares

La denuncia compara **dos** ejemplares. Hay un tercero, y es decisivo.

| Mesa | Casilla | CLAVEROS | DELEGADOS | TRANSMISIÓN | **Escrutinio oficial** |
|---|---|---|---|---|---|
| 003 | Cepeda | 138 | 38 | 38 | **138** |
| 003 | Espriella | 93 | 793 | 893 | **93** |
| 006 | Cepeda | 121 | 21 | 21 | **121** |
| 006 | Espriella | 101 | 201 | 201 | **101** |
| 015 | Cepeda | 119 | 19 | 19 | **119** |
| 015 | Espriella | 42 | 142 | 142 | **42** |

**DELEGADOS y TRANSMISIÓN se comportan igual.** Son dos papeles físicos distintos,
escaneados por procesos distintos: si un ejemplar hubiera sido alterado, el otro
no mostraría lo mismo.

## La explicación técnica

CLAVEROS es **JPEG a color, 300 dpi**. DELEGADOS y TRANSMISIÓN son **PNG
binarizados a 1 bit** y menor resolución (ver [FORENSE_COLOR.md](FORENSE_COLOR.md)).

Inspeccionando los recortes:

- Donde CLAVEROS muestra un **`1` limpio con un óvalo tenue detrás** —traspaso del
  reverso del papel, presente en todo el corpus—, la binarización funde ambos en
  una **mancha negra sólida**.
- Donde CLAVEROS muestra un **aspa (✱)** de anulación, la binarización la engorda
  hasta convertirla en una mancha que el OCR lee como un dígito.
- En la mesa 002 el escaneo de DELEGADOS está **especialmente sobre-binarizado**:
  convierte en manchas incluso dígitos que TRANSMISIÓN conserva legibles.

Es decir: la diferencia visible entre ejemplares es **del proceso de escaneo**, no
del papel.

## Lo que sí se puede afirmar

1. **El escrutinio oficial registró los valores de CLAVEROS** —los legibles— en las
   seis casillas. El resultado oficial **no recogió** los valores que aparecen
   alterados en el escaneo binarizado.
2. El patrón se repite idéntico en los dos ejemplares binarizados, lo que es
   incompatible con la alteración de un único papel.
3. La suma de las tres mesas es de unos **900 votos** sobre un margen de 251.854
   (0,36 %), y aun así no llegaron al conteo oficial.

## Lo que NO se puede afirmar

- **Que no exista alteración física en el papel.** Determinarlo exige peritaje
  documentológico sobre el original, no un escaneo. Este análisis sólo puede
  decir que *la evidencia disponible se explica por el escaneo*.
- Que la denuncia no tenga otros elementos fuera de estas imágenes.

## Por qué esto importa metodológicamente

Es el ejemplo perfecto de por qué **el voto mayoritario 2-vs-1 no vale en este
corpus**: DELEGADOS y TRANSMISIÓN comparten modo de fallo, forman "mayoría" y
señalarían a CLAVEROS —el único que acertaba— como el sospechoso. Por eso el
árbitro es el escrutinio oficial (ver [CASOS_DE_USO.md](CASOS_DE_USO.md)).

## Un bug que estuvo a punto de arruinar el análisis

Los primeros intentos comparaban **mesas equivocadas**. El nombre de los ficheros
de CLAVEROS es `E14_PRE_dep_muni_ZONA_tok_puesto_MESA_id.pdf`, y la **zona también
va en 3 dígitos**: buscar la mesa 003 con `*_003_*.pdf` en la zona 003 devuelve
**todas** las mesas, y `sorted()[0]` entrega la 001.

Corregido en `comparacion/triangular.py` y `oficial/dirimir.py` (`_acta_claveros`,
que parsea el nombre y compara la clave completa). Cualquier resultado anterior al
2026-09-05 que localizara actas por glob hay que rehacerlo.

## Qué buscar de verdad

El perfil de una divergencia que sí merece revisión:

- **UN solo ejemplar** se aparta (no los dos binarizados a la vez).
- Leída con **confianza ALTA**.
- El **escrutinio oficial** coincide con los otros dos.

Ninguna de las mesas de Turbo cumple ese perfil. Para buscarlas a escala:
[`notebooks/triangular_ejemplares.ipynb`](../notebooks/triangular_ejemplares.ipynb).
