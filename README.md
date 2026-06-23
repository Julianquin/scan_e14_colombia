# ScanE14 — Auditoría técnica de actas E-14 (Presidencia Colombia 2026)

Sistema **reproducible y auditable** para descargar masivamente los formularios
E-14 (actas de mesa) publicados por la Registraduría, extraer su contenido, leer
los números y **detectar, cuantificar y documentar inconsistencias** para
revisión humana. Cubre **primera y segunda vuelta**.

> **Principio rector:** el sistema **NO dictamina fraude**. Detecta *anomalías* y
> reúne *evidencia* (recortes + números + chequeos + rastro de integridad), y
> deja el juicio a una persona. Muchas anomalías son errores honestos de
> diligenciamiento o correcciones legítimas. La fuerza del sistema está en el
> *agregado* y en *cruzar señales*, no en señalar una mesa aislada.

## Filosofía: una ronda no es una copia del código

El código es **agnóstico de ronda** y vive una sola vez en el paquete `e14/`. Las
distintas vueltas (y los dos ejemplares: DELEGADOS / TRANSMISIÓN / CLAVEROS) se
sirven **parametrizando** los comandos (`--base-url`, `--out`, `--codes`), no
copiando scripts. Cada ronda es solo un **directorio de datos** bajo `data/`.

## Estado del proyecto

| Área | Descripción | Estado |
|------|-------------|--------|
| Descarga | Bajar los PDFs del visor oficial (incremental, reanudable) | ✅ 1ª vuelta · 🟡 2ª en curso |
| Extracción (Fase 0) | Recortar de cada acta las 21 casillas | ✅ Cerrada y validada |
| OCR de dígitos (Fase 1) | Clasificador CNN por dígito + auto-entrenamiento + decodificador aritmético | 🟢 ~53% de cuadre (desde 7,6% de TrOCR) |
| **Comparación entre ejemplares** | DELEGADOS vs TRANSMISIÓN por mesa/candidato | 🟡 **Foco principal actual** |
| Enmendaduras intra-dígito | Detección de retoque en el recuadro de centenas | ⬜ Diseño |
| Monitor + integridad del manifiesto | Vigilancia del `allTransmissionCodes.json` con cadena a prueba de manipulación | ✅ Operativo |
| Reporte de auditoría | Consolidado por mesa (hash, cuadre, tasa base) | ✅ Operativo |
| Cruce con preconteo oficial (Fase 2) | Desviación por mesa frente al dato oficial | ⬜ Pendiente |

Arquitectura completa y decisiones técnicas en **[docs/ROADMAP.md](docs/ROADMAP.md)**.

## Estructura del repositorio

```
scan_e14_colombia/
├── README.md                 # este fichero (punto de entrada)
├── pyproject.toml            # (o requirements.txt + requirements-ocr.txt)
├── .gitignore                # data/, models/, *.pdf, *.pt, *.json.gz, __pycache__/ ...
│
├── e14/                      # PAQUETE: todo el código, reutilizable y agnóstico de ronda
│   ├── comunes.py            # constantes E-14, parsear_ruta, utilidades compartidas
│   ├── descarga/             # descargar_e14.py · monitor_codes.py
│   ├── extraccion/           # extractor · segmentacion · posiciones · procesar_lote   (Fase 0)
│   ├── ocr/                  # clasificador_digitos · etiquetador · chequeo_aritmetico
│   │                         #   combinar_resultados · ocr_backends · ocr_trocr_kaggle  (Fase 1)
│   ├── comparacion/          # comparar_ejemplares.py   ← foco actual (enmendaduras)
│   └── auditoria/            # reporte_auditoria.py
│
├── notebooks/                # monitor_codes.ipynb · ocr_trocr_kaggle.ipynb
├── docs/                     # ROADMAP · BANDERAS · SCRAPING · FLUJO_KAGGLE · POSICIONES ...
├── tests/                    # test_ocr_una_acta · diagnostico_* · probar_muestra · comparar_ocr
│
├── data/                     # NO versionado (ver .gitignore)
│   ├── manifests/            # allTransmissionCodes.json · departmentsTree.json  (una copia)
│   ├── primera_vuelta/       # e14_pdfs/ · recortes/ · dataset_digitos/ · resultados/
│   └── segunda_vuelta/       # e14_pdfs/ · codes_snapshots/ · resultados/
│
└── models/                   # digitnet.pt y demás pesos (NO versionado, o git-lfs)
```

## Instalación

```bash
pip install -r requirements.txt          # base (descarga, monitor, auditoría)
pip install -r requirements-ocr.txt      # extra OCR: torch + opencv (Fase 1)
```

> El extra de OCR (torch/opencv) es pesado y opcional: si solo usas el monitor o
> el reporte de auditoría, te basta la instalación base. Para Fase 1 conviene un
> entorno conda dedicado con un único NumPy (evita el choque NumPy 1.x/2.x).

## Flujos principales

**1. Descargar las actas de una ronda** (parametrizable por vuelta/ejemplar):

```bash
python -m e14.descarga.descargar_e14 \
    --codes data/manifests/allTransmissionCodes.json \
    --base-url https://e14segundavueltapresidente.registraduria.gov.co \
    --out data/segunda_vuelta/e14_pdfs
```

**2. Vigilar el manifiesto oficial** (crece/cambia según se cargan actas; deja
rastro de integridad):

```bash
python -m e14.descarga.monitor_codes --interval 300 --out data/segunda_vuelta/codes_snapshots
python -m e14.descarga.monitor_codes --verificar --out data/segunda_vuelta/codes_snapshots
```

**3. Leer los números** (Fase 0 → Fase 1):

```bash
python -m e14.extraccion.procesar_lote        # recorta casillas de cada PDF
python -m e14.ocr.clasificador_digitos entrenar  digitos.npz --ensemble 3
python -m e14.ocr.clasificador_digitos evaluar   numeros_leidos.csv recortes/
python -m e14.ocr.clasificador_digitos decodificar numeros_leidos.csv recortes/   # cierra por aritmética
```

**4. Consolidar el reporte de auditoría:**

```bash
python -m e14.auditoria.reporte_auditoria --out data/segunda_vuelta/codes_snapshots
```

## Las dos señales que persigue el sistema

1. **El acta fue sustituida** — el PDF de una mesa cambia de hash (monitor) o un
   ejemplar difiere del otro para el mismo candidato (`comparacion/`). El caso
   central de 2ª vuelta: un "1" de las centenas que se le quita a un candidato y
   se le suma al otro deja el total intacto, así que **la aritmética sola es
   ciega** — solo la comparación entre ejemplares lo revela.
2. **El acta no cuadra** — los números no satisfacen
   `suma(candidatos)+blanco+nulo+no_marcado == SUMA_TOTAL == TOTAL_E11` (OCR +
   `chequeo_aritmetico`).

Una mesa que dispara **ambas** señales —y además se desvía del preconteo
oficial— es cualitativamente distinta de un simple re-escaneo o un lapsus de
digitación. El sistema mide la **tasa base** de cada señal para que una alerta
aislada tenga contexto.

## Documentación

Índice en **[docs/](docs/)**. Para el diseño y el estado de cada fase, empieza
por **[docs/ROADMAP.md](docs/ROADMAP.md)**.
