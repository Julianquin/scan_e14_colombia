# Informe de estado y definición de scope

**Fecha:** 2026-08-26 · Elecciones presidenciales Colombia 2026, 1ª y 2ª vuelta.

---

## 1. Resumen ejecutivo

El proyecto tiene **la materia prima completa y verificada** y **dos flujos de
análisis operativos end-to-end**. El cuello de botella conocido —el OCR— tiene el
arreglo construido pero **sin validar**.

| | |
|---|---|
| Actas descargadas | **362.375** (2ª vuelta, 3 ejemplares) + 244.006 (1ª vuelta) |
| Integridad | ✅ verificada; 0 corruptos en delegados/transmisión, 16 en claveros |
| Datos oficiales | ✅ preconteo y escrutinio de ambas vueltas, **SHA-256 verificado** |
| Auditoría oficial | ✅ operativa, con resultados |
| OCR | ✅ **96,9 % por casilla** (desde 69,2 %); arreglo validado |
| Hallazgos | 1 mesa donde el escrutinio se apartó del acta (60 votos) |

**El resultado agregado hasta hoy es negativo**: las anomalías encontradas son
compatibles con error humano de transcripción. Eso es un hallazgo, no un fracaso
— y es lo que dará autoridad al método si algún día encuentra algo.

---

## 2. Scope: qué es y qué no es

### 2.1 Qué es

> Un **sistema de triaje auditable** que reduce ~122.000 actas por vuelta a una
> lista corta, priorizada y con evidencia adjunta, para que una persona la revise.

Las tres propiedades que lo definen:

1. **Reproducible por terceros.** Todo parte de ficheros oficiales verificables
   por hash. Cualquiera puede recalcular y llegar al mismo sitio.
2. **Conservador.** Ante la duda, `REVISAR_A_MANO`. Nunca un veredicto automático.
3. **Cuantificado contra el margen.** Toda anomalía se expresa en votos y se
   compara con los **251.854** de diferencia oficial (0,96 %; 2,1 votos por mesa).

### 2.2 Qué NO es — límites duros

| No es | Por qué |
|---|---|
| **Un detector de fraude** | Ninguna señal disponible distingue dedo torpe de dolo. El sistema marca y cuantifica; **el juicio es humano**. |
| **Un sistema en tiempo real** | Las elecciones ya ocurrieron. Es auditoría post-hoc. |
| **Un OCR perfecto** | El 100 % es utópico *y* la métrica equivocada: no hace falta leer bien todo, hace falta ordenar por riesgo. |
| **Una fuente de verdad alternativa** | No recuenta la elección. Compara fuentes existentes entre sí. |
| **Un servicio web / API** | El entregable son informes y CSV reproducibles, no infraestructura. |

### 2.3 Dentro del scope (comprometido)

| # | Entregable | Estado |
|---|---|---|
| E1 | Descarga íntegra y verificable de las actas | ✅ hecho |
| E2 | Informe de integridad: qué falta y de quién es la culpa | ✅ hecho |
| E3 | Auditoría preconteo ↔ escrutinio, con tipologías y direccionalidad | ✅ hecho |
| E4 | Dirimir contra el papel las mesas señaladas, con evidencia visual | ✅ hecho |
| E5 | Cruce con censo y topes legales (imposibilidad física) | ✅ **hecho** — sale limpio |
| E6 | Informe consolidado por vuelta, reproducible | ✅ **hecho** — [INFORME_2V.md](INFORME_2V.md), se regenera |

### 2.4 Extensión (si el OCR llega)

| # | | Depende de |
|---|---|---|
| X1 | Dirimir las 1.106 mesas `OTROS` | ✅ desbloqueado |
| X2 | Triangulación de los 3 ejemplares (árbitro: escrutinio oficial) | ✅ **módulo operativo** — `comparacion/triangular.py` |
| X3 | Score de riesgo con peso posicional (±9 vs ±900 votos) | ✅ desbloqueado |

### 2.5 Explícitamente FUERA de scope

- **Forense de enmendaduras intra-dígito.** Probado y **descartado con datos**:
  el "trazo fantasma" es traspaso del reverso del papel, aparece igual en mesas
  control y no separa nada ([FORENSE_COLOR.md](FORENSE_COLOR.md)).
- **Comparación píxel a píxel entre ejemplares.** Descartada: son papeles físicos
  distintos.
- **Análisis de patrón agregado** (Benford, mesas gemelas). Señal débil y alto
  riesgo de sobreinterpretación. No antes de cerrar E1–E6.
- **Recuperar el voto del exterior en CLAVEROS.** Imposible: el portal de
  escrutinios nunca publicó el departamento 88 (3.670 mesas). Se declara como
  limitación, no se intenta arreglar.
- **1ª vuelta como objeto de análisis propio.** Se usa sólo como **grupo de
  control**.

---

## 3. Estado por componente

### 3.1 Operativo y validado

| Componente | Evidencia |
|---|---|
| `descarga/` | 362.375 actas de 2ª vuelta; reintentos dirigidos cerrados |
| `validacion/integridad_pdfs.py` | delegados y transmisión **completos, 0 corruptos**; claveros 16 truncados (del origen) |
| `oficial/mmv.py` | 4 ficheros oficiales, **SHA-256 coincide** en las dos vueltas |
| `oficial/auditar.py` | 2ª v: 1.151 mesas cambiaron (0,94 %); efecto neto +683 votos (0,271 % del margen) |
| `oficial/dirimir.py` | 43 mesas → 27 dirimibles → **26 respaldan al escrutinio, 1 al preconteo** |
| `extraccion/posiciones_2v.py` | geometría validada; recorta las 9 casillas en los 3 ejemplares |
| E5 · censo y topes (`censo_topes_E5.ipynb`) | **0 de 122.020 mesas** superan el tope legal; los 57 puestos que exceden el censo tienen explicación institucional y 27 se repiten en 1ª vuelta |
| `informe/consolidado.py` | genera [INFORME_2V.md](INFORME_2V.md) recalculando desde los ficheros oficiales en 7 s; no hay cifras transcritas a mano |
| `ocr/` + `dataset_oficial.py` | **96,9 % de acierto por casilla** contra el escrutinio oficial (desde 69,2 %); errores de aspa 339 → 19 |

### 3.2 Parcial

**Comparación entre ejemplares (`comparacion/triangular.py`)** — operativa. El OCR
generaliza a los tres ejemplares (CLAVEROS 98,0 % · DELEGADOS 97,3 % ·
TRANSMISIÓN 95,3 %). Dos salvedades documentadas: el voto mayoritario 2-vs-1 **no
vale** (los dos binarizados comparten modo de fallo y forman mayorías falsas, así
que el árbitro es el escrutinio oficial), y la confianza **clasifica en vez de
filtrar** (una casilla alterada hace dudar al modelo, y filtrarla eliminaría lo
que se busca). Falta correrlo a escala: `notebooks/triangular_ejemplares.ipynb`.

---

## 4. Medido vs. supuesto

Distinción importante para no construir sobre arena.

**Medido con datos:**

- Margen oficial 251.854 votos; integridad de los 4 ficheros; 1.151 mesas
  cambiadas; 28 permutaciones no direccionales (p = 0,186); 83 % de acierto por
  casilla; el color **empeora** el OCR (42,7 % vs 46,9 %); el bootstrapping por
  aritmética se agota (+2 puntos con 4,7× más datos).

**Supuesto, aún sin verificar:**

- Que el 19,85 % de cambios en 1ª vuelta se explica por tener 13 candidatos.
- Que las 15 mesas anuladas lo fueron por causal legítima *(hay que leer las
  constancias de la página 2)*.
- Que los `OTROS` (1.106 mesas) son mayoritariamente correcciones legítimas.

---

## 5. Qué significa "producción" aquí

No hay servidores. **Producción = el análisis se puede publicar y un tercero lo
reproduce.** Criterios de aceptación:

| # | Criterio | Estado |
|---|---|---|
| P1 | Todo entregable arranca de ficheros con hash verificado | ✅ |
| P2 | Un tercero clona, instala y reproduce los números | 🔴 sin pins ni packaging |
| P3 | El pipeline corre sobre el **universo completo**, no tramos | 🔴 sólo tramos |
| P4 | Cada mesa señalada lleva evidencia visual adjunta | ✅ |
| P5 | Cada cifra publicada tiene su intervalo o test | 🟡 sólo direccionalidad |
| P6 | Limitaciones declaradas en el propio entregable | ✅ documentadas |
| P7 | Tests automáticos de las funciones críticas | 🔴 no hay |

---

## 6. Brechas para producción, priorizadas

### Bloqueantes

**B1 · ~~Validar el arreglo del OCR~~** — ✅ **hecho (2026-09-04)**: 96,9 % de
acierto por casilla. X1–X3 quedan desbloqueados.

**B2 · ~~Correr E5 (censo + topes legales)~~** — ✅ **hecho (2026-09-04)**:
0 de 122.020 mesas superan su tope legal; los 57 puestos que exceden el censo se
explican por consulados (métrica no aplicable), cárceles, rural diminuto y censo
desactualizado, y 27 de ellos exceden también en 1ª vuelta. Detalle en
[DATOS_OFICIALES.md](DATOS_OFICIALES.md). Notebook:
[`notebooks/censo_topes_E5.ipynb`](../notebooks/censo_topes_E5.ipynb).
Verificado de antemano: el escrutinio cruza con DIVIPOL en el **100 %** de las
122.020 mesas, y las dos fuentes de censo (DIVIPOL y el Anexo 4 del derecho de
petición) **coinciden al 100 %** en los 13.742 puestos comunes. *(minutos)*

**B3 · Correr el pipeline sobre el universo completo** — hoy todo está medido en
tramos de 300–1.500 actas. Un resultado publicable necesita las 118.337.
*(varias horas de GPU, en notebook)*

**B4 · Reproducibilidad (P2)** — `pyproject.toml`, versiones pinneadas, y un
`README` que lleve de cero a los números publicados. *(1 día)*

### Importantes, no bloqueantes

**B5 · Tests automáticos** de lo crítico: `mismos_votos` (el bug que apareció
tres veces), `clave_mesa`, los parsers de formato fijo, `interpretar`,
`posiciones_discriminantes`. Los `tests/` actuales son scripts de diagnóstico,
no tests.

**B6 · ~~Informe consolidado (E6)~~** — ✅ **hecho (2026-09-05)**:
`e14/informe/consolidado.py` lo regenera desde los ficheros oficiales.

**B7 · Constancias de las 15 anuladas** — requiere procesar la **página 2** de
las actas, que hoy el pipeline ignora por completo.

---

## 6.bis Incidente resuelto: la máquina se colgaba al entrenar

**Síntoma:** reinicio del equipo al cerrar la época 1, dos veces seguidas.

**Causa (medida, no supuesta):** `clasificador_color.entrenar()` subía el
dataset completo a la VRAM (**5,79 GB** con 209.544 cajas) y además evaluaba las
**41.908 imágenes de validación en un solo forward** — sólo la primera
convolución (32 canales de 48×48) pedía ~12 GB de activaciones, y hay seis antes
del pooling. Sobre 24 GB de tarjeta, el driver se colgaba.

**Arreglado:** los datos se quedan en RAM en uint8 y a la GPU va sólo el lote de
turno; la validación va por lotes de 512. VRAM pico por debajo de 1 GB, y ya no
escala con el tamaño del dataset.

**Diagnósticos que NO eran la causa** (se comprobaron): faltaba `torch.no_grad()`
—ya estaba, y evita el grafo pero no las activaciones del forward—; acumular
tensores con historial en listas —no se hace—; `num_workers` del `DataLoader`
—no se usa `DataLoader`.

**Lección de proceso:** este arreglo ya se había hecho en
`notebooks/entrenamiento_2v.ipynb` pero **no se llevó al módulo**, y después se
escribió un notebook que llamaba al módulo sin arreglar. Cuando un fix nace en un
notebook, hay que portarlo al módulo en el mismo momento.

## 6.ter Bug crítico de localización de actas (2026-09-05)

Buscar el acta de CLAVEROS con un glob `*_{mesa:03d}_*.pdf` es **incorrecto**: el
nombre lleva la ZONA también en 3 dígitos, así que en la zona 003 ese patrón
matchea todas las mesas y `sorted()[0]` devuelve la 001. Afectaba a
`comparacion/triangular.py` y `oficial/dirimir.py`, y produjo un análisis de
Turbo sobre **mesas equivocadas**.

Corregido con `_acta_claveros()`, que parsea el nombre y compara la clave
completa. **Cualquier resultado anterior a esa fecha que localizara actas por
glob debe rehacerse.**

## 7. Riesgos

| Riesgo | Mitigación |
|---|---|
| **Sobreinterpretar una mesa aislada.** Un falso positivo mediático quema el proyecto entero | Nunca publicar mesas sueltas; siempre agregado + tasa base |
| **Optimizar el cuadre a ciegas.** Un acta con error aritmético real nunca debe cuadrar: "arreglarlo" tapa la señal | Métrica primaria = acierto contra verdad oficial, no cuadre |
| **Hipótesis nula mal especificada.** Ya fabricó falsos positivos tres veces | H0 documentada por tipología; revisar antes de publicar cualquier test |
| **Circularidad en el autoetiquetado.** Ya agotó el bootstrapping | Etiquetas desde el escrutinio oficial, externo al modelo |
| **208 GB de datos no versionados** | Los hashes oficiales permiten re-descargar y verificar |
| **Carga de GPU que cuelga la máquina** | Entrenar siempre por lotes; el notebook imprime la VRAM pico y avisa si se dispara |

---

## 8. Camino recomendado

1. ~~**B1** — OCR~~ ✅ · ~~**B2** — E5 censo y topes~~ ✅ · ~~**B6** — informe~~ ✅
2. **X1** — dirimir las 1.106 mesas `OTROS` (notebook listo, sólo falta correrlo).
3. **B4 + B5** — reproducibilidad (`pyproject.toml`, pins) y tests automáticos.
   Es lo único que separa el proyecto de ser reproducible por un tercero.
4. **B3** — pipeline sobre el universo completo con el mejor modelo.
5. **B7** — constancias (página 2) de las 15 mesas anuladas.
6. Sólo entonces: X2 (triangulación de ejemplares) y X3 (score posicional).

**5 de 6 entregables del scope están cerrados.** Lo que más valor añade ahora no
es más análisis, sino **B4+B5**: sin pins ni tests, un tercero no puede reproducir
los números, y ese era el criterio de "producción".
