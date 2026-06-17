# Hoja de ruta — Auditoría técnica de actas E-14 (Presidencia Colombia 2026)

## 1. Objetivo general

Construir un sistema **reproducible y auditable**, ejecutable en un equipo local
(CPU, 16 núcleos) con apoyo de GPU gratuita (Kaggle), que procese los 122.016
E-14 publicados por la Registraduría para:

1. Extraer y leer su contenido (casillas de votos, nivelación, constancias).
2. Detectar, cuantificar y documentar inconsistencias y vulnerabilidades
   correspondientes a las categorías de denuncia documentadas públicamente.
3. Producir evidencia trazable, mesa a mesa, para revisión humana.

**Lo que NO es**: no es una plataforma en tiempo real (las elecciones ya
ocurrieron; esto es auditoría post-hoc) y no emite veredictos de fraude. El
sistema marca, cuantifica y documenta; el juicio es humano.

## 2. Restricciones de capacidad (decisiones de diseño derivadas)

| Restricción | Decisión |
|---|---|
| Sin presupuesto cloud (Google Vision ≈ 500-600 USD) | OCR local/gratuito: TrOCR-handwritten en Kaggle GPU |
| CPU local sin GPU | Fase 0 (extracción) en CPU local; solo el OCR va a Kaggle |
| Kaggle: 30 h/semana GPU, datasets 100 GB persistentes | Flujo por lotes: exportar recortes → dataset → notebook → CSV |
| PDFs = escaneos **binarizados B/N** (~200 DPI) | La presión del trazo y el color de tinta NO sobreviven; el forense morfológico se limita a grosor, densidad y geometría |
| Fuente pública = ejemplar de TRANSMISIÓN (visor Registraduría) | El cruce entre ejemplares depende de conseguir otros juegos; el pipeline se diseña ejemplar-agnóstico |

## 3. Mapeo: categorías de denuncia → fases del sistema

| # | Denuncia documentada | Fase que la ataca | Estado |
|---|---|---|---|
| 1 | **Errores aritméticos** (suma de candidatos+blanco+nulos+no marcados ≠ SUMA_TOTAL ≠ TOTAL E-11) | Fase 1 · chequeo aritmético | Código listo; pendiente corrida real |
| 2 | **Espacios en blanco no anulados** (sin guion/asterisco → vulnerables a inflado posterior) | Fase 1 · registro de posiciones → bandera `espacio_sin_anular` | ✅ Implementado |
| 3 | **Alteración morfológica** (tachones, enmendaduras, 1→10, 4→9) | Fase 3 · forense morfológico comparativo | Pendiente |
| 4 | **Divergencia entre ejemplares** (Transmisión vs Delegados vs Claveros) | Fase 2 · cruce con datos oficiales + pipeline ejemplar-agnóstico | Pendiente |
| 5 | **Diseño/usabilidad → error por fatiga** (jornadas >12 h, cuadrículas pequeñas) | Fase 4 · análisis estadístico (direccionalidad del error) | Pendiente |

## 4. Fases

### Fase 0 — Extracción de casillas · ✅ CERRADA (validada con actas reales)

Extrae 21 elementos por acta: 3 de nivelación (TOTAL_E11, TOTAL_URNA,
TOTAL_INCINERADOS), 13 candidatos, 4 agregados (BLANCO, NULO, NO_MARCADO,
SUMA_TOTAL) y CONSTANCIAS. CSV de 62 columnas + banderas de anomalía
(ALTA/MEDIA/INFO).

Calidad del recorte (requisito de todas las fases siguientes):
- Cada fila se ancla a las **líneas horizontales reales** de la tabla y la X al
  separador vertical real (`celdas+lineas`; respaldo: plantilla de fracciones).
- El límite derecho es el **borde derecho real de la tabla** (`_borde_derecho_bloque`
  + afinado por fila contra inclinación): la barra del borde ya no entra al recorte.
- `ajustar_recorte_interior` excluye líneas residuales sin tocar dígitos
  (calibrado con caso real: el '1' de '107' se conserva).
- Métrica `borde_residual` para trazabilidad de calidad.

Validación: 2 actas reales (Leticia=126, Medellín=107), 29/29 recortes finales
sin barras, dígitos íntegros. Local, CPU, ~2 actas/s por proceso (reanudable).

### Fase 1 — Lectura y validación aritmética · EN CURSO

Ataca las denuncias **#1** y **#2**.

- **Registro de posiciones** (`posiciones.py`): cada casilla registra el estado
  de sus posiciones (`digito`/`punto`/`guion`/`vacio`) clasificando por
  RELLENO del trazo (dígito=trazo 0.18-0.35; punto=mancha sólida >0.5).
  Banderas: `espacio_sin_anular` (denuncia #2), `mas_de_3_posiciones` (casos
  tipo --47), `posicion_ambigua`, `contiene_guion`, `casilla_vacia`.
  Las 20 casillas numéricas se registran SIEMPRE (las vacías = 0, sin PNG).
- **OCR manuscrito**: TrOCR-handwritten en Kaggle GPU. Flujo:
  `exportar_recortes.py` (local) → zip → dataset Kaggle →
  `ocr_trocr_kaggle.ipynb` (GPU T4, lotes de 32) → `numeros_leidos.csv` →
  `combinar_resultados.py` (local). PaddleOCR descartado (2 bugs en CPU + ~43 GB RAM).
- **Chequeo aritmético** (`chequeo_aritmetico.py`): suma(candidatos)+B+N+NM ==
  SUMA_TOTAL == TOTAL_E11. Alertas ALTA/MEDIA/NINGUNA/INCOMPLETO. El chequeo
  valida de paso al OCR: si cuadra, la lectura gana confianza.

**Siguiente paso inmediato**: corrida de ~500 actas en Kaggle para medir la
tasa real de lectura de TrOCR y decidir si basta o si conviene afinar
(preprocesado o CNN de dígitos como alternativa).

### Fase 2 — Cruce con resultados oficiales y entre ejemplares

Ataca la denuncia **#4**.

- **2a (factible ya)**: descargar los resultados numéricos oficiales por mesa
  (divulgación del preconteo y/o E-24 del escrutinio) y cruzarlos contra la
  lectura OCR del papel. Discrepancia papel-vs-dato-oficial = señal de oro.
- **2b (pipeline ejemplar-agnóstico)**: el extractor procesa cualquier juego de
  E-14 con el mismo formato. *Comprobado en la práctica*: el acta de validación
  de Medellín es un ejemplar **DELEGADOS** y se procesó idéntico al de
  transmisión. Si se consigue otro juego (MOE, partidos), se corre el MISMO
  pipeline sobre ambos y se comparan mesa a mesa: la divergencia entre
  ejemplares queda cuantificada automáticamente.

### Fase 3 — Forense morfológico (tachones/enmendaduras)

Ataca la denuncia **#3**, con el límite honesto de la fuente: en escaneos
binarizados B/N no sobreviven la presión ni la tinta. Lo que SÍ es medible:

- **Densidad de tinta** del dígito (sobreescrito ≈ 2x lo normal).
- **Grosor de trazo bimodal** en una casilla = dos escrituras.
- **Geometría**: dígito que invade posiciones vecinas o desborda la celda.
- **Señal comparativa (la clave)**: cada dígito contra la distribución de
  grosor/densidad del MISMO acta (mismo jurado, misma pluma). Lo anómalo es lo
  que difiere de su propio contexto, no de un estándar global.
- **Clasificador ligero**: CNN pequeño entrenado en Kaggle con etiquetado débil
  (candidatas = no cuadra la aritmética + el dígito leído difiere del esperado;
  etiquetar a mano unos cientos). Se aplica SOLO a actas ya marcadas, como
  evidencia de apoyo — nunca como disparador.

### Fase 4 — Análisis estadístico

Ataca las denuncias **#4** y **#5**. Local, pandas/sklearn.

- **Direccionalidad del error** (la prueba central): el error honesto por
  fatiga es simétrico entre candidatos; la manipulación es direccional. Test:
  en las mesas que no cuadran, ¿la diferencia favorece sistemáticamente a
  alguien o se reparte al azar?
- **Outliers de participación**: mesas ~100%, variaciones extremas vs. el
  histórico del puesto.
- **Clustering** de mesas/puestos por patrón de anomalías: ¿las inconsistencias
  se concentran geográficamente o son aleatorias?
- **Mapa de `espacio_sin_anular` por puesto**: dónde la cadena de custodia fue
  más vulnerable (denuncia #2 agregada territorialmente).

### Fase 5 — Tablero de revisión y trazabilidad

- **Tablero Streamlit local**: mesas ordenadas por alerta; por mesa: recortes,
  números leídos, estado de posiciones, chequeos, constancias.
- **Trazabilidad ("MLOps casero", suficiente y auditable)**: hash SHA-256 del
  PDF de origen (ya está en el nombre de cada archivo), scripts y CSVs
  versionados en git, semillas fijas, versión de modelo y fecha en cada salida.
  Cualquier tercero puede reproducir el resultado end-to-end desde los PDFs.

## 5. Principios rectores

1. El sistema **no dictamina fraude**: detecta, cuantifica y documenta.
2. **Registrar fielmente** (incluida la anomalía) > "corregir" automáticamente.
3. La **aritmética es la señal más fiable**; lo visual es evidencia de apoyo.
4. **Nunca mutilar un dígito**: un borde residual es ruido tolerable que la
   Fase 1 limpia; un dígito dañado es información perdida.
5. Toda afirmación debe ser **reproducible** desde los PDFs originales.
6. Validar cada cambio con **actas reales e imágenes**, nunca solo con métricas
   (varias métricas dieron falsos positivos contando dígitos como barras).

## 6. Registro de decisiones técnicas (resumen)

- Método de agregados/nivelación: `celdas+lineas` (líneas reales); el método
  "anclaje a cand_13" se eliminó por desfasar media fila (4/500 actas).
- Límite derecho: borde real de la tabla, tomando la PRIMERA línea (hay actas
  con doble línea derecha) y afinando por fila (inclinación residual).
- `ajustar_recorte_interior`: sin dilatación (inflaba dígitos), banda 10%,
  umbral 0.88, la línea debe tocar el extremo (<4%).
- Barras fragmentadas (Fase 1): columna estrecha, lateral, cuyos fragmentos
  tocan banda superior e inferior y cubren >45% del recorrido con huecos.
- PaddleOCR descartado en CPU (bug oneDNN + RAM); TrOCR-handwritten en Kaggle.
- Clasificación de posiciones por relleno del trazo, no por altura absoluta.
