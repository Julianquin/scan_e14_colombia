# Integridad de la descarga — qué falta y por qué

Registro de los huecos **del origen** (la Registraduría) frente a los huecos
**nuestros** (descarga incompleta). La distinción importa: lo nuestro se
arregla reintentando; lo del origen no, y es en sí mismo un hallazgo de
auditoría que hay que documentar en vez de "arreglar".

Verificado con `python -m e14.validacion.integridad_pdfs` (chequeo de
estructura PDF + cobertura contra manifiesto + cobertura comparada por
departamento entre los tres ejemplares).

## Estado a 2026-08-24 — segunda vuelta

| Ejemplar | PDFs en disco | Corruptos | Faltantes vs. manifiesto |
|---|---|---|---|
| DELEGADOS (`e14_pdfs_2v`) | 122.019 | 0 | 0 |
| TRANSMISIÓN (`e14_pdfs_2v_t`) | 122.019 | 0 | 0 |
| CLAVEROS (`e14_pdfs_claveros`) | 118.337 | **16** | 0 |

DELEGADOS y TRANSMISIÓN quedaron **completos e íntegros** tras un reintento
dirigido (`e14.validacion.reintentar_faltantes`) de 39 y 59 archivos
respectivamente — todos eran timeouts de red de la corrida de julio, es
decir huecos NUESTROS, ya cerrados.

## Hueco del origen 1 — CLAVEROS no tiene el exterior (dep. 88)

**3.670 mesas de CONSULADOS (departamento 88) existen en DELEGADOS y en
TRANSMISIÓN, y CERO en CLAVEROS.**

No es un fallo de nuestro descargador: el `index.json` del portal de
escrutinios —la fuente de la que sale todo CLAVEROS— **no publica ni un solo
puesto** del departamento 88 (0 de 22.876 claves). La Registraduría nunca
indexó ahí las actas de escrutinio del voto en el exterior, y no da
explicación pública de por qué.

**Consecuencia para la auditoría:** para el voto del exterior el cruce entre
ejemplares se degrada de 3 vías a 2 (DELEGADOS vs. TRANSMISIÓN). El
ejemplar de CLAVEROS —el que firma la comisión escrutadora— no es
verificable ahí. Cualquier conclusión sobre dep. 88 debe declarar esta
limitación.

## Hueco del origen 2 — 16 actas de CLAVEROS servidas truncadas

16 PDFs se descargaron con cabecera `%PDF` válida pero **sin marca de cierre
`%%EOF`**: están truncados. El reintento dirigido
(`e14.validacion.reintentar_claveros`) no los recupera — a 2026-08-24 el
dominio `escrutinios2vueltapresidente2026.registraduria.gov.co` **ya no
responde** (timeout de conexión al sitio entero, no solo a esos archivos;
el visor de transmisión sí responde con normalidad desde la misma red).
El portal de escrutinios parece haber sido dado de baja tras el escrutinio.

**13 de los 16 son de Bucaramanga**, lo que sugiere un problema de lote en
el origen y no corrupción aleatoria en tránsito.

| Departamento | Municipio | Zona | Puesto | Mesa | Archivo |
|---|---|---|---|---|---|
| VALLE | JAMUNDÍ | 02 | ESCUELA ANGEL MARIA CAMACHO | 9 | `docs/E14/31/064/02/05/E14_PRE_31_064_002_00_05_009_6760.pdf` |
| ANTIOQUIA | ENVIGADO | 09 | URB. MULTIFAMILIAR SEÑORIAL | 14 | `docs/E14/01/121/09/02/E14_PRE_01_121_009_00_02_014_5183.pdf` |
| CUNDINAMARCA | TOCANCIPÁ | 01 | INST EDU DEPTAL TÉCNICO COMERCIAL | 6 | `docs/E14/15/292/01/03/E14_PRE_15_292_001_00_03_006_5831.pdf` |
| SANTANDER | BUCARAMANGA | 05 | COL FRANCISCO DE PAULA S/DER SEDE B | 2 | `docs/E14/27/001/05/04/E14_PRE_27_001_005_04_04_002_6428.pdf` |
| SANTANDER | BUCARAMANGA | 14 | ESC NORMAL SUPERIOR SEDE A | 9 | `docs/E14/27/001/14/01/E14_PRE_27_001_014_13_01_009_6441.pdf` |
| SANTANDER | BUCARAMANGA | 08 | UNIDADES TECNOLÓGICAS DE SANT | 24 | `docs/E14/27/001/08/03/E14_PRE_27_001_008_07_03_024_6432.pdf` |
| SANTANDER | BUCARAMANGA | 07 | GIMNASIO SUPERIOR EMPRESARIAL | 9 | `docs/E14/27/001/07/05/E14_PRE_27_001_007_06_05_009_6430.pdf` |
| SANTANDER | BUCARAMANGA | 07 | INST SAN JOSÉ DE LA SALLE | 12 | `docs/E14/27/001/07/02/E14_PRE_27_001_007_06_02_012_6430.pdf` |
| SANTANDER | BUCARAMANGA | 18 | INST CALDAS | 12 | `docs/E14/27/001/18/01/E14_PRE_27_001_018_16_01_012_6445.pdf` |
| SANTANDER | BUCARAMANGA | 18 | INST CALDAS | 13 | `docs/E14/27/001/18/01/E14_PRE_27_001_018_16_01_013_6445.pdf` |
| SANTANDER | BUCARAMANGA | 18 | INST CALDAS | 20 | `docs/E14/27/001/18/01/E14_PRE_27_001_018_16_01_020_6445.pdf` |
| SANTANDER | BUCARAMANGA | 01 | COLEGIO FE Y ALEGRÍA LOS COLORADOS | 3 | `docs/E14/27/001/01/04/E14_PRE_27_001_001_01_04_003_6420.pdf` |
| SANTANDER | BUCARAMANGA | 11 | JARDÍN INFANTIL CASITA DE CHOC | 5 | `docs/E14/27/001/11/03/E14_PRE_27_001_011_10_03_005_6436.pdf` |
| SANTANDER | BUCARAMANGA | 19 | I.E. JOSÉ CELESTINO MUTIS | 22 | `docs/E14/27/001/19/01/E14_PRE_27_001_019_17_01_022_6446.pdf` |
| SANTANDER | BUCARAMANGA | 02 | I.E. LA JUVENTUD SEDE A | 1 | `docs/E14/27/001/02/05/E14_PRE_27_001_002_02_05_001_6420.pdf` |
| SANTANDER | BUCARAMANGA | 12 | COL ADVENTISTA LIBERTAD | 14 | `docs/E14/27/001/12/01/E14_PRE_27_001_012_11_01_014_6437.pdf` |

(prefijo de todas: `https://escrutinios2vueltapresidente2026.registraduria.gov.co/`)

El número de mesa viene embebido en el propio nombre de archivo oficial
(penúltimo grupo de 3 dígitos); está cruzado y confirmado contra
`claveros_mesas.csv`.

## Cómo re-verificar

```bash
python -m e14.validacion.integridad_pdfs \
    --base data/segunda_vuelta \
    --ejemplar delegados=e14_pdfs_2v \
    --ejemplar transmision=e14_pdfs_2v_t \
    --ejemplar claveros=e14_pdfs_claveros \
    --workers 12 \
    --out data/segunda_vuelta/_integridad/reporte_integridad_2v
```

Escribe tres CSV en `data/segunda_vuelta/_integridad/`: `.corruptos.csv`,
`.faltantes.csv` y `.departamentos.csv` (cobertura comparada entre
ejemplares, con bandera `HUECO_TOTAL` / `DIVERGENCIA_FUERTE`).

**Nota sobre el nombre de archivo del visor:** parece un `sha256` (64 hex)
pero **no lo es** — se comprobó que el `sha256sum` real del contenido no
coincide con el nombre. Es un id opaco del storage, así que no sirve para
verificar integridad de contenido; por eso el chequeo se hace por estructura
(`%PDF` + `%%EOF`) y no por hash.
