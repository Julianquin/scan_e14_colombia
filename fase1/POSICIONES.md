# Registro del estado de cada posición de una casilla

## Cambio de filosofía (importante)
Antes intentábamos "limpiar" la casilla para leer un número, y eso PERDÍA
información: puntos, guiones y vacíos se borraban. Ahora NO filtramos contenido.
Registramos fielmente qué hay en cada posición y dejamos que el OCR lea y el
chequeo aritmético + humano interpreten.

## Qué hace `posiciones.py`
Para cada casilla (módulo `registrar_casilla`):
1. `quitar_barras_borde`: elimina SOLO las barras verticales de celdas vecinas
   (columnas oscuras casi en toda la altura). No toca el contenido interno.
2. `detectar_bloques`: encuentra las posiciones con contenido (zonas de tinta
   separadas por huecos). Fusiona huecos minúsculos (dígito partido).
3. `clasificar_bloque`: clasifica cada posición por su FORMA:
   - **dígito**: trazo, deja huecos en su bounding box (relleno bajo ≤0.45)
   - **punto**: mancha sólida que llena su bbox (relleno >0.5, baja)
   - **guion**: muy bajo y más ancho que alto
   - **marca**: ambiguo, se deja para revisión

La señal clave es el RELLENO (tinta/área del bbox), no la altura absoluta, que
varía con el tamaño del recorte.

## Qué se registra (en indice_recortes.csv)
- `n_posiciones`: cuántas posiciones con contenido se detectaron
- `tipos_posicion`: p.ej. `punto|digito|digito` o `digito|digito|digito`
- `n_digitos`: cuántas posiciones son dígitos (lo que leerá el OCR)
- `banderas`: inconsistencias detectadas, p.ej.:
  - `mas_de_3_posiciones`: caso como `--47` (4 posiciones) → ANOMALÍA a revisar
  - `posicion_ambigua`: alguna posición no clasificada con seguridad
  - `contiene_guion`: hay un guion (vacío marcado)
  - `casilla_vacia`: sin contenido

## Por qué esto importa
- Un punto puede significar cero, vacío, o relleno: no lo decidimos aquí.
- Casos como `--47` (4 posiciones, dos guiones) son anomalías reales que el
  sistema DEBE registrar, no "corregir".
- El recorte exportado conserva TODO el contenido (solo sin barras de borde),
  así el OCR ve la casilla íntegra y nada se pierde.

## Validado
Sobre el acta de ejemplo: clasifica correctamente las 3 posiciones de cada
casilla (126→digito|digito|digito; 69→punto|digito|digito; casillas con punto
de relleno→punto|punto|digito), y marca las vacías.

## Registro completo de las 21 casillas (incluida nivelación y vacías)
`exportar_recortes.py` registra SIEMPRE las 20 casillas numéricas de cada acta
(3 nivelación: TOTAL_E11, TOTAL_URNA, TOTAL_INCINERADOS + 13 candidatos + 4
agregados), aunque estén vacías:
- Casilla CON contenido: se exporta su PNG (sin barras de borde) + estado de
  posiciones en el índice.
- Casilla VACÍA: NO se exporta PNG (no hay nada que leer con OCR), pero SÍ se
  registra en el índice con bandera `casilla_vacia` (= 0). Así el chequeo
  aritmético sabe que la casilla existe y vale 0, en vez de ignorarla.

Esto corrige una ausencia previa: TOTAL_INCINERADOS (a menudo vacía) no se
registraba, y el bloque de nivelación quedaba incompleto. El TOTAL_E11 es
esencial para el chequeo (SUMA_TOTAL debe coincidir con él).

## Decisión: recorte fiel (sin borrado de bordes)
Tras varias iteraciones, el borrado automático de barras de borde resultó
frágil: cada ajuste arreglaba un caso y rompía otro (el peor: dañar dígitos
verticales como 1/4/7). Se decidió VOLVER A LO SIMPLE:

- `quitar_barras_borde` ahora devuelve el recorte fiel SIN tocar el contenido.
- El recorte exportado conserva todo, incluso si tiene algo de borde.

Razones:
1. Un borde de más es ruido tolerable; un dígito mutilado es info perdida.
2. El chequeo aritmético es la red de seguridad: si un borde hace leer mal al
   OCR, la suma no cuadra y el acta sale marcada para revisión (no se pierde).
3. Con resultados reales del OCR sabremos SI el borde molesta y cómo quitarlo
   sin dañar dígitos. Quizá TrOCR lo ignora y no hay que hacer nada.

El registro de posiciones (digito/punto/guion + banderas) se mantiene: es útil
y no daña el recorte.

## Actualización: máscara protectora de tinta (borrado seguro de barras)
Se implementó la versión ligera de la estrategia recomendada (máscara protectora
de tinta), que SÍ borra barras sin dañar dígitos:

1. **Máscara de barras**: apertura morfológica con kernel vertical de ~0.9 de la
   altura → solo captura líneas casi tan altas como el recorte (las barras de
   borde). Un dígito no es tan alto, así que no entra entero.
2. **Tinta a conservar**: todo lo que NO es barra, DILATADO (kernel 7x7) para
   crear una zona de protección alrededor de los trazos.
3. **Máscara final = barras − tinta protegida**: si un trazo de dígito vertical
   coincidió con la máscara de barras, su entorno protegido lo rescata.
4. **Blanqueo** de la máscara final.

Validado visualmente: en cand_01 (69), cand_11 (7) y SUMA_TOTAL (126), se borra
SOLO la barra de borde; los dígitos verticales (1, 7, 9) quedan intactos. Si
algo falla, en el peor caso deja algo de borde (ruido tolerable), nunca mutila
el número. NO incluye la alineación con plantilla (paso 1 de la recomendación),
que es costosa y en parte ya la cubre el deskew de la Fase 0.
