# Casos de uso, tipologías y propuesta de valor

Qué se puede sostener con estos datos, con qué fuerza, y qué no.

## El marco: por qué el 100 % de OCR es la métrica equivocada

Un clasificador perfecto sobre 122.019 actas manuscritas es una utopía. Pero
además **es la métrica equivocada**: el proyecto no necesita *leer* bien todas
las actas, necesita **ordenarlas por riesgo** para que una persona revise las
pocas que importan.

Bajo ese marco el OCR imperfecto deja de ser un bloqueo. Una lectura que el
censo declara imposible se detecta igual, aunque no sepamos el valor correcto.

Dos consecuencias prácticas:

- **No todos los errores pesan igual.** Un dígito mal leído en unidades vale
  ±9 votos; en centenas, ±900. Combinado con la confianza del modelo por
  posición, da una **incertidumbre expresada en votos** y una cola de revisión
  ordenada por impacto real, no por "cuán mal leyó".
- **Una casilla de 3 posiciones con 4 dígitos es imposible por construcción.**
  Con 343,7 habilitados por mesa de media (máximo nacional 1.191), cualquier
  valor ≥ 1000 es un error estructural, no una lectura discutible.

### El número que enmarca todo

**Margen de 2ª vuelta: 251.854 votos (0,96 %) — 2,1 votos por mesa.**

La pregunta útil no es "¿hubo fraude?" sino **"¿cuántos votos están en disputa
por anomalías, frente a 251.854?"**.

## Tipologías de anomalía, por fuerza probatoria

Ordenadas por lo difícil que es dar una explicación inocente:

| # | Tipología | Cómo se detecta | Fuerza | Estado |
|---|---|---|---|---|
| 1 | **Imposibilidad física** — votos > habilitados o > tope legal de la mesa | Censo (Anexo 4) + INDICADORES | **La más dura**: no la explica un error de digitación | Datos listos, falta correr |
| 2 | **Divergencia entre ejemplares** — 3 copias del acta, arbitradas por el escrutinio oficial | `comparacion/triangular.py` | Fuerte, con la salvedad de abajo | ✅ Operativo |
| 3 | **Divergencia papel ↔ oficial** — acta vs preconteo/escrutinio | `oficial/dirimir.py` | **Señal de oro**: ataca el tramo entre el papel y el resultado publicado | ✅ Operativo |
| 4 | **Inconsistencia interna** — la aritmética no cuadra | `chequeo_aritmetico` | Media: común por error honesto, valiosa en agregado | ✅ Operativo |
| 5 | **Anomalía estructural** — 4 dígitos en casilla de 3, espacios sin anular | `posiciones.py` | Media-alta, y **no necesita leer bien los números** | Parcial |
| 6 | **Patrón agregado** — Benford, redondeos, mesas gemelas, saltos entre vueltas | pendiente | Débil aislada, fuerte en volumen | ⬜ |

### ⚠️ El voto mayoritario 2-vs-1 no vale en este corpus

Parece natural que si dos ejemplares coinciden y uno difiere, el discrepante sea
el sospechoso. **Es falso aquí**: el voto mayoritario supone errores
independientes, y DELEGADOS y TRANSMISIÓN son **ambos binarizados de 1 bit**,
comparten modo de fallo y se equivocan igual.

Medido en las mesas de Turbo: los dos binarizados pierden el dígito de
**centenas** (121→21, 119→19) y forman una mayoría falsa; el escrutinio oficial
confirma que el discrepante —CLAVEROS— era el que acertaba.

Por eso el árbitro es el **escrutinio oficial**, que es independiente del papel.

### ⚠️ La confianza clasifica, no filtra

Una casilla retocada hace **dudar al modelo precisamente por estar alterada**.
Descartar las lecturas de baja confianza elimina justo los casos que se buscan.
Se ordena por confianza y se revisa empezando por las altas, pero no se tira nada.

Caso trabajado en detalle: [CASO_TURBO.md](CASO_TURBO.md).

## La prueba más robusta: direccionalidad

Los errores de OCR son **simétricos por construcción** — al modelo le da igual
un candidato que otro. Los errores humanos honestos (fatiga, letra) también
deberían serlo. Por tanto:

> Si las anomalías favorecen sistemáticamente a un candidato, esa asimetría
> **no la explican ni el OCR ni el cansancio**.

Es medible sin OCR perfecto (sólo requiere que sus errores sean simétricos,
cosa verificable), y es el tipo de evidencia que resiste el contrainterrogatorio:
no dice "esta mesa es fraudulenta", dice "la distribución no es aleatoria, y
aquí está el test".

Implementado en `oficial/auditar.py`. **Cuidado con la hipótesis nula**: depende
del mecanismo de cada tipología, y equivocarla fabrica falsos positivos — ver
[DATOS_OFICIALES.md](DATOS_OFICIALES.md), donde están documentados los tres
errores que costó afinarlo.

### El grupo de control: la 1ª vuelta

Las mismas mesas, los mismos jurados, distinto resultado. Una mesa con
anomalías en **ambas** vueltas es un puesto con mala letra o mal escáner; una
que sólo se descuadra en la 2ª es cualitativamente distinta.

## Propuesta de valor, en tres niveles

**El producto no es un detector de fraude. Es un sistema de triaje auditable**
que convierte 122.019 actas en una lista corta, priorizada y justificada, para
que una persona decida.

1. **Verificación de integridad institucional** — que los datos oficiales cuadren
   consigo mismos y con el papel. Publicable aunque no haya ni un hallazgo, y es
   lo que da credibilidad al resto.
2. **Medición de calidad del proceso** — tasa base de error por departamento,
   tipología y magnitud. Valor público **independiente de que haya fraude o no**,
   y hace el proyecto defendible: no parte de asumir la conclusión.
3. **Cola de casos para revisión humana** — con evidencia adjunta: recorte del
   papel + los tres números + la tipología + el impacto en votos.

### Demostración de que el embudo funciona

Ya corrido end-to-end sobre 2ª vuelta:

**122.017 mesas → 1.151 cambios → 43 señaladas → 27 dirimibles → 1 caso**
que merece ojo humano (mesa `31/067/0/01/11`, 60 votos de impacto).

Y el resultado agregado fue **negativo**: la direccionalidad es compatible con
error de transcripción, y en 26 de 27 el escrutinio corrigió correctamente al
preconteo. **Ese resultado negativo es lo más valioso producido hasta ahora**:
un método que sólo confirma sospechas no vale nada; uno que dice "aquí hay una
anomalía, la medí, y parece error humano" es el que tendrá autoridad cuando
encuentre algo real.

## Orden de trabajo recomendado

1. **Arreglar las aspas del OCR** — cuello de botella medido: el 16,3 % de las
   casillas ([OCR_2V.md](OCR_2V.md)). Desbloquea 2, 3 y 4.
2. **Cerrar el cruce con el censo** (tipología 1) — la señal más dura, datos
   listos, funciona incluso con OCR imperfecto.
3. **Score de riesgo con peso posicional** — barato, y produce el entregable de
   triaje.
4. **Direccionalidad** sobre todas las tipologías.
5. **Patrón agregado** (Benford y compañía) — lo último, es lo más débil.

## Lo que hay que resistir

Dos tentaciones que arruinarían el trabajo:

- **Publicar mesas individuales como "fraude".** Una mesa aislada nunca prueba
  intención, y un solo falso positivo mediático quema la credibilidad de todo lo
  demás.
- **Optimizar el % de cuadre a ciegas.** Un acta con error aritmético real
  *nunca* debe cuadrar: si subís el cuadre "arreglando" esos casos, estás
  tapando justo la señal que buscás.

## Límites honestos

- **Intención, nunca.** Ninguna de las seis tipologías distingue dedo torpe de
  dolo. Sólo el patrón agregado sugiere algo, y sugerir no es probar.
- **El techo del OCR no es 100 %**, y no debe serlo.
- **Que el escrutinio corrija al preconteo es su función**, no una irregularidad.
- **Para el voto del exterior (dep. 88) no hay CLAVEROS**
  ([INTEGRIDAD_DESCARGA.md](INTEGRIDAD_DESCARGA.md)): ahí el cruce se degrada de
  3 vías a 2 y hay que declararlo.
- El sistema **marca, cuantifica y documenta. El juicio es humano.**
