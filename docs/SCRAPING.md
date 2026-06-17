# Descarga masiva de PDFs E-14 (`descargar_e14.py`)

El script **`descargar_e14.py`** (en la raíz del repo) descarga los PDFs E-14
directamente del portal de la Registraduría a partir de dos archivos JSON
locales que describen el universo de actas:

- `allTransmissionCodes.json` — índice de las 122.016 actas.
- `departmentsTree.json` — nombres legibles de departamento/municipio/zona/puesto
  (opcional pero recomendado: enriquece el manifiesto).

> Esta fase ya está **completada**. Esta guía documenta cómo reproducirla.
> Los dos JSON son datos de entrada externos y **no se versionan** (ver
> `.gitignore`); consíguelos aparte antes de ejecutar.

El PDF de cada mesa se construye con el patrón:

```text
/assets/temis/pdf/{departamento}/{municipio}/{zona}/{puesto}/{mesa}/PRE/{expectedName}?uuid={uuid}
```

y se guarda en `e14_pdfs/PRE/{dep}/{muni}/{zona}/{puesto}/{mesa}/{expectedName}`.

## Instalación

```bash
pip install requests
```

## Uso

```bash
# 1) Prueba con 20 PDFs primero
python descargar_e14.py \
  --codes allTransmissionCodes.json \
  --tree departmentsTree.json \
  --out e14_pdfs --limit 20 --workers 3

# 2) Corrida completa
python descargar_e14.py \
  --codes allTransmissionCodes.json \
  --tree departmentsTree.json \
  --out e14_pdfs --workers 4

# Solo un departamento (p. ej. 60)
python descargar_e14.py --codes allTransmissionCodes.json \
  --tree departmentsTree.json --out e14_pdfs --departments 60 --workers 4

# Generar un CSV con todas las URLs SIN descargar
python descargar_e14.py --codes allTransmissionCodes.json \
  --tree departmentsTree.json --out e14_pdfs \
  --urls-csv urls_e14.csv --only-urls
```

El script es robusto: reintentos con backoff exponencial, validación de que el
contenido sea un PDF real (`%PDF` + tamaño mínimo), descarga paralela con
`ThreadPoolExecutor`, y escritura de `manifest_*.jsonl` / `errors_*.jsonl` en
`e14_pdfs/_logs/`. Volver a lanzarlo **omite** los PDFs ya descargados válidos.

## Notas

- **Normalización de códigos**: departamento a 2 dígitos, municipio 3, zona 3,
  puesto 2, mesa 3. Una zona `"00"` termina como `/000/`.
- **Estados**: por defecto descarga todos los nodos con `expectedName` (incluye
  `status3`, `status11`, etc.). Para limitar a un estado: `--statuses 11`.
- **Otro ejemplar/host**: cambia solo el host con `--base-url <url>` (p. ej. el
  portal de transmisión). El pipeline es ejemplar-agnóstico.
- **Throttling**: empieza con `--workers 3` o `4`. Si ves muchos `429`/`503`,
  baja workers y sube pausas: `--sleep-min 0.5 --sleep-max 1.5`.

Para todas las opciones: `python descargar_e14.py --help`.
