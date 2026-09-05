# Informe de auditoría — Presidencia 2026 · 2ª vuelta

**Generado automáticamente** el 2026-09-05 por `python -m e14.informe.consolidado`.
No transcribe cifras a mano: todo se recalcula desde los ficheros oficiales.

> **Este informe NO dictamina fraude.** Detecta anomalías, las cuantifica y
> deja la evidencia servida para revisión humana. Muchas anomalías son
> errores honestos o correcciones legítimas. El juicio es humano.

## Resumen

| | |
|---|---|
| Integridad de los ficheros oficiales | ✅ SHA-256 verificado |
| Mesas en el escrutinio | 122.020 |
| Margen oficial | **251.854 votos** (0,956 %) |
| Mesas que cambiaron entre los dos conteos | 1.151 (0,943 %) |
| Mesas que superan su tope legal | **0** de 122.020 |

## 1 · Procedencia y verificación

Los datos son los ficheros **MMV** (mesa a mesa con votos) que la
Registraduría publica para auditores, y traen **dos conteos oficiales**
independientes de cada mesa:

- **Preconteo** — la noche electoral. Informativo, sin valor jurídico.
- **Escrutinio** — el acto jurídico definitivo, días después.

Verificación de integridad: **los ficheros coinciden con el SHA-256 oficial**.
Cualquier tercero puede recalcular el hash y confirmar que se partió del
fichero oficial sin alterar.

## 2 · Resultado oficial

| | Votos | % |
|---|---:|---:|
| ABELARDO DE LA ESPRIELLA | 12.960.166 | 49.19 % |
| IVÁN CEPEDA CASTRO | 12.708.312 | 48.24 % |
| Blanco / nulo / no marcado | 676.482 | 2.57 % |
| **Total** | **26.344.960** | |

**Margen: 251.854 votos = 0,956 %** — 2.1 votos por mesa.

Ese número es la escala de todo lo que sigue: la pregunta útil no es
"¿hubo fraude?" sino **"¿cuántos votos están en disputa frente a
251.854?"**.

## 3 · Preconteo vs. escrutinio

**Que el escrutinio cambie el preconteo no es una anomalía**: existe
precisamente para corregirlo. Lo que se audita es cuántas mesas, de qué
tipo y hacia dónde.

De 122.017 mesas comparables, **1.151 cambiaron (0,943 %)**:

| Tipología | Mesas | Qué es |
|---|---:|---|
| `OTROS` | 1.106 | cambios de magnitud |
| `PERMUTACION` | 28 | los **mismos valores** repartidos entre otros candidatos; no altera el total de la mesa, así que ninguna suma la delata |
| `ANULADA` | 15 | la mesa queda en 0 (causal de anulación: decisión **jurídica**, no de lectura) |
| `APARECE` | 2 | sin votos en preconteo, con votos en escrutinio |

## 4 · Qué dice el papel

Se fue al acta E-14 escaneada de 43 mesas señaladas.

| Veredicto | Mesas |
|---|---:|
| COINCIDE_ESCRUTINIO | 26 |
| ANULADA_NO_DIRIMIBLE | 15 |
| SIN_POSICION_DISCRIMINANTE | 1 |
| COINCIDE_PRECONTEO | 1 |

De las **27 dirimibles, el papel respalda al escrutinio en 26 (96 %)**. Es lo esperado: corregir el preconteo es su función.

Las 15 **anuladas no son dirimibles**: el escrutinio las pone en 0 y el
papel muestra los votos emitidos, así que "coincide con el preconteo" es
cierto por definición. Anular es una decisión jurídica; para evaluarlas hay
que leer la constancia de la página 2 del acta.

**1 mesa donde el papel respalda al PRECONTEO** — ahí el escrutinio se
apartó del acta. Son las que merecen revisión humana:

| Mesa (dep/muni/zona/puesto/mesa) | Tipología | Impacto |
|---|---|---:|
| 31/67/0/01/11 | PERMUTACION | 60 votos |

Impacto conjunto: **60 votos = 0,024 % del margen**.

## 5 · Restricción física: censo y topes legales

La señal **más dura** del proyecto, y la única que no admite "error
humano" como explicación: una mesa no puede tener más votos que
votantes habilitados. Se calcula sobre el escrutinio oficial, **sin OCR**.

**Chequeo A — votos por mesa > tope legal: 0 de 122.020.**

La restricción legal por mesa **se cumple sin excepción**.

**Chequeo B — votos del puesto > censo:** 44 puestos del
territorio nacional (0,326 %), con un exceso
de 134 votos = **0,053 % del margen**.

El **exterior se cuenta aparte** (13 puestos, 1.667 votos): su "censo" en DIVIPOL es capacidad
administrativa, no habilitados —el 73,6 % son múltiplos exactos de 100,
frente al 1,0 % en el resto del país—, así que el chequeo no le aplica.

## 6 · Ronda de control

Las mismas mesas y el mismo censo, otra elección. Una anomalía presente en
**ambas** rondas es estructural del censo o del puesto; una que sólo
aparece en esta es cualitativamente distinta.

| | Control | Esta ronda |
|---|---:|---:|
| Mesas comparadas | 122.020 | 122.017 |
| Mesas que cambiaron | 24.227 (19,855 %) | 1.151 (0,943 %) |
| Permutaciones | 157 | 28 |
| Mesas sobre el tope legal | 0 | 0 |
| Puestos sobre su censo | 33 | 57 |

**27 puestos exceden su censo en las DOS rondas** → estructural.

> La ronda de control corrige muchísimas más mesas. Antes de leer eso como
> una anomalía: tenía **13 candidatos frente a 2**, y cada candidato extra
> multiplica las ocasiones de equivocarse al transcribir. Es una diferencia
> objetiva que conviene explicar, no un hallazgo.

## 7 · Limitaciones declaradas

- **No se puede probar intención.** Ninguna señal distingue un dedo torpe de
  un dolo. Sólo el patrón agregado sugiere algo, y sugerir no es probar.
- **Una mesa aislada no prueba nada.** El valor está en el agregado y en
  cruzar señales.
- El OCR **no es perfecto** y no necesita serlo: el objetivo es ordenar por
  riesgo, no leer todo bien. Los veredictos contra el papel son una ayuda
  para el revisor, no un dictamen.
- **Un acta con un error aritmético real nunca debe "cuadrar"**: optimizar
  esa métrica a ciegas taparía justo lo que hay que detectar.
- Para el **voto del exterior no existe el ejemplar de CLAVEROS** (el portal
  de escrutinios nunca publicó el departamento 88): allí el cruce se degrada
  de tres vías a dos.

## 8 · Cómo reproducir

```bash
python -m e14.oficial.mmv verificar data/manifests/MMV_2V/MMV_Presidente2V_2026
python -m e14.oficial.auditar data/manifests/MMV_2V/MMV_Presidente2V_2026 --out auditoria
jupyter lab notebooks/censo_topes_E5.ipynb        # censo y topes legales
jupyter lab notebooks/dirimir_otros_2v.ipynb      # contraste contra el papel
python -m e14.informe.consolidado --mmv data/manifests/MMV_2V/MMV_Presidente2V_2026 --out docs/INFORME_2V.md
```

Documentación de apoyo: [DATOS_OFICIALES.md](DATOS_OFICIALES.md) ·
[CASOS_DE_USO.md](CASOS_DE_USO.md) · [OCR_2V.md](OCR_2V.md) ·
[INTEGRIDAD_DESCARGA.md](INTEGRIDAD_DESCARGA.md) ·
[ESTADO_Y_SCOPE.md](ESTADO_Y_SCOPE.md)
