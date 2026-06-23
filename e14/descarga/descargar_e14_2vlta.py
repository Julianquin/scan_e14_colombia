#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Descarga masiva de PDFs E-14 desde los JSON locales allTransmissionCodes.json
y departmentsTree.json.

Uso de prueba:
    python descargar_e14.py --codes allTransmissionCodes.json --tree departmentsTree.json --out e14_pdfs --limit 20

Corrida completa:
    python descargar_e14.py --codes allTransmissionCodes.json --tree departmentsTree.json --out e14_pdfs --workers 4
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import requests


DEFAULT_BASE_URL = "https://e14segundavueltapresidentet.registraduria.gov.co" # "https://divulgacione14presidentet.registraduria.gov.co"
DEFAULT_CORPORATION_FOLDER = "PRE"

RETRIABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
_THREAD_LOCAL = threading.local()


@dataclass(frozen=True)
class Record:
    id_transmission_code: str
    number_table: str
    expected_name: str
    transmission_status: str
    corporation_code: str
    department_code: str
    municipality_code: str
    zone_code: str
    stand_code: str
    id_stand: str


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def zfill_value(value: Any, width: int) -> str:
    text = "" if value is None else str(value).strip()
    return text.zfill(width)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def walk_nodes(value: Any) -> Iterable[Dict[str, Any]]:
    """
    Recorre estructuras tipo GraphQL y produce solo nodos con expectedName.
    Esto permite leer status3, status11 u otros buckets similares.
    """
    if isinstance(value, dict):
        nodes = value.get("nodes")

        if isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, dict) and "expectedName" in node:
                    yield node

        for child in value.values():
            yield from walk_nodes(child)

    elif isinstance(value, list):
        for item in value:
            yield from walk_nodes(item)


def node_to_record(node: Dict[str, Any]) -> Optional[Record]:
    expected_name = str(node.get("expectedName", "")).strip()

    if not expected_name:
        return None

    if not expected_name.lower().endswith(".pdf"):
        expected_name += ".pdf"

    return Record(
        id_transmission_code=str(node.get("idTransmissionCode", "")).strip(),
        number_table=zfill_value(node.get("numberStand"), 3),
        expected_name=expected_name,
        transmission_status=str(node.get("idTransmissionCodeStatus", "")).strip(),
        corporation_code=zfill_value(node.get("idCorporationCode", "001"), 3),
        department_code=zfill_value(node.get("idDepartmentCode"), 2),
        municipality_code=zfill_value(node.get("municipalityCode"), 3),
        zone_code=zfill_value(node.get("idZoneCode"), 3),
        stand_code=zfill_value(node.get("standCode"), 2),
        id_stand=str(node.get("idStand", "")).strip(),
    )


def load_records(codes_path: Path) -> List[Record]:
    raw = load_json(codes_path)

    records: List[Record] = []

    for node in walk_nodes(raw.get("data", raw)):
        record = node_to_record(node)

        if record is not None:
            records.append(record)

    return dedupe_records(records)


def dedupe_records(records: Iterable[Record]) -> List[Record]:
    seen = set()
    out: List[Record] = []

    for rec in records:
        if rec.id_transmission_code:
            key: Any = ("id", rec.id_transmission_code)
        else:
            key = (
                "loc",
                rec.corporation_code,
                rec.department_code,
                rec.municipality_code,
                rec.zone_code,
                rec.stand_code,
                rec.number_table,
                rec.expected_name,
            )

        if key in seen:
            continue

        seen.add(key)
        out.append(rec)

    return out


def load_tree_lookup(
    tree_path: Optional[Path],
) -> Dict[Tuple[str, str, str, str], Dict[str, Any]]:
    """
    Crea un diccionario para enriquecer el manifiesto con nombres legibles.

    Clave:
        departamento, municipio, zona, puesto
    """
    if not tree_path:
        return {}

    if not tree_path.exists():
        raise FileNotFoundError(f"No existe departmentsTree: {tree_path}")

    raw = load_json(tree_path)

    edges = (
        raw.get("data", {})
        .get("departmentsTree", {})
        .get("edges", [])
    )

    lookup: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

    for edge in edges:
        dep_node = edge.get("node", {}) if isinstance(edge, dict) else {}

        dep_code = zfill_value(dep_node.get("idDepartmentCode"), 2)
        dep_name = dep_node.get("departmentName", "")

        for mun_node in dep_node.get("municipalities", []) or []:
            mun_code = zfill_value(mun_node.get("municipalityCode"), 3)
            mun_name = mun_node.get("municipalityName", "")

            for zone_node in mun_node.get("zones", []) or []:
                zone_code = zfill_value(zone_node.get("idZoneCode"), 3)
                zone_name = zone_node.get("zoneName", "")

                for stand_node in zone_node.get("stands", []) or []:
                    stand_code = zfill_value(stand_node.get("standCode"), 2)

                    lookup[(dep_code, mun_code, zone_code, stand_code)] = {
                        "department_name": dep_name,
                        "municipality_name": mun_name,
                        "zone_name": zone_name,
                        "stand_name": stand_node.get("standName", ""),
                        "count_table_in_stand": stand_node.get("countTable"),
                    }

    return lookup


def get_session(args: argparse.Namespace) -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)

    if session is None:
        session = requests.Session()

        session.headers.update({
            "User-Agent": args.user_agent,
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
            "Referer": args.base_url.rstrip("/") + "/",
            "Connection": "keep-alive",
        })

        _THREAD_LOCAL.session = session

    return session


def corporation_folder(args: argparse.Namespace, rec: Record) -> str:
    """
    Para presidente en este portal el directorio es PRE.
    Se deja parametrizable por si necesitas cambiarlo.
    """
    return args.corporation_folder or DEFAULT_CORPORATION_FOLDER


def build_pdf_url(args: argparse.Namespace, rec: Record) -> str:
    base = args.base_url.rstrip("/")
    folder = corporation_folder(args, rec)
    name = quote(rec.expected_name, safe="")

    return (
        f"{base}/assets/temis/pdf/"
        f"{rec.department_code}/{rec.municipality_code}/{rec.zone_code}/"
        f"{rec.stand_code}/{rec.number_table}/{folder}/{name}"
        f"?uuid={uuid.uuid4()}"
    )


def local_pdf_path(args: argparse.Namespace, rec: Record) -> Path:
    folder = corporation_folder(args, rec)

    return (
        Path(args.out)
        / folder
        / rec.department_code
        / rec.municipality_code
        / rec.zone_code
        / rec.stand_code
        / rec.number_table
        / rec.expected_name
    )


def is_valid_pdf(path: Path, min_bytes: int) -> bool:
    try:
        if not path.exists() or path.stat().st_size < min_bytes:
            return False

        with path.open("rb") as fh:
            return fh.read(5).startswith(b"%PDF")

    except OSError:
        return False


def enriched_names(
    rec: Record,
    tree_lookup: Dict[Tuple[str, str, str, str], Dict[str, Any]],
) -> Dict[str, Any]:
    return tree_lookup.get(
        (
            rec.department_code,
            rec.municipality_code,
            rec.zone_code,
            rec.stand_code,
        ),
        {},
    )


def make_result(
    status: str,
    reason: str,
    rec: Record,
    url: str,
    path: Path,
    tree_lookup: Dict[Tuple[str, str, str, str], Dict[str, Any]],
    **extra: Any,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "timestamp_utc": now_utc(),
        "status": status,
        "reason": reason,
        "url": url,
        "path": str(path),
        **asdict(rec),
        **enriched_names(rec, tree_lookup),
    }

    result.update(extra)

    return result


def safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def sleep_backoff(args: argparse.Namespace, attempt: int) -> None:
    seconds = min(args.max_backoff, args.backoff_base * (2 ** (attempt - 1)))
    seconds += random.uniform(0, 1.0)
    time.sleep(seconds)


def download_one(
    args: argparse.Namespace,
    rec: Record,
    tree_lookup: Dict[Tuple[str, str, str, str], Dict[str, Any]],
) -> Dict[str, Any]:
    path = local_pdf_path(args, rec)
    url = build_pdf_url(args, rec)

    if not args.overwrite and is_valid_pdf(path, args.min_bytes):
        return make_result(
            "skip",
            "already_exists",
            rec,
            url,
            path,
            tree_lookup,
            bytes=path.stat().st_size,
        )

    session = get_session(args)
    path.parent.mkdir(parents=True, exist_ok=True)

    last_error = ""

    for attempt in range(1, args.retries + 1):
        if args.sleep_max > 0:
            time.sleep(random.uniform(args.sleep_min, args.sleep_max))

        url = build_pdf_url(args, rec)

        tmp_path = path.with_name(
            f"{path.name}.part.{os.getpid()}.{threading.get_ident()}.{attempt}"
        )

        try:
            with session.get(
                url,
                stream=True,
                timeout=(args.connect_timeout, args.read_timeout),
            ) as response:
                http_status = response.status_code
                content_type = response.headers.get("Content-Type", "")

                if http_status != 200:
                    last_error = f"http_{http_status}"

                    if http_status in RETRIABLE_HTTP_STATUS and attempt < args.retries:
                        sleep_backoff(args, attempt)
                        continue

                    return make_result(
                        "error",
                        last_error,
                        rec,
                        url,
                        path,
                        tree_lookup,
                        attempt=attempt,
                        http_status=http_status,
                        content_type=content_type,
                    )

                sha256 = hashlib.sha256()
                total_bytes = 0
                first_bytes = b""

                with tmp_path.open("wb") as fh:
                    for chunk in response.iter_content(chunk_size=args.chunk_size):
                        if not chunk:
                            continue

                        if len(first_bytes) < 5:
                            first_bytes += chunk[: 5 - len(first_bytes)]

                        total_bytes += len(chunk)
                        sha256.update(chunk)
                        fh.write(chunk)

                if not first_bytes.startswith(b"%PDF"):
                    last_error = (
                        f"not_pdf content_type={content_type!r} "
                        f"first_bytes={first_bytes[:20].hex()}"
                    )

                    safe_unlink(tmp_path)

                    if attempt < args.retries:
                        sleep_backoff(args, attempt)
                        continue

                    return make_result(
                        "error",
                        last_error,
                        rec,
                        url,
                        path,
                        tree_lookup,
                        attempt=attempt,
                        http_status=http_status,
                        content_type=content_type,
                        bytes=total_bytes,
                    )

                if total_bytes < args.min_bytes:
                    last_error = f"too_small bytes={total_bytes}"

                    safe_unlink(tmp_path)

                    if attempt < args.retries:
                        sleep_backoff(args, attempt)
                        continue

                    return make_result(
                        "error",
                        last_error,
                        rec,
                        url,
                        path,
                        tree_lookup,
                        attempt=attempt,
                        http_status=http_status,
                        content_type=content_type,
                        bytes=total_bytes,
                    )

                os.replace(tmp_path, path)

                return make_result(
                    "ok",
                    "downloaded",
                    rec,
                    url,
                    path,
                    tree_lookup,
                    attempt=attempt,
                    http_status=http_status,
                    content_type=content_type,
                    bytes=total_bytes,
                    sha256=sha256.hexdigest(),
                )

        except Exception as exc:
            last_error = repr(exc)
            safe_unlink(tmp_path)

            if attempt < args.retries:
                sleep_backoff(args, attempt)
                continue

    return make_result(
        "error",
        last_error or "unknown_error",
        rec,
        url,
        path,
        tree_lookup,
        attempt=args.retries,
    )


def parse_csv_filter(value: str, width: Optional[int] = None) -> set[str]:
    values = set()

    for item in (value or "").split(","):
        item = item.strip()

        if not item:
            continue

        values.add(item.zfill(width) if width else item)

    return values


def filter_records(records: List[Record], args: argparse.Namespace) -> List[Record]:
    departments = parse_csv_filter(args.departments, 2)
    statuses = parse_csv_filter(args.statuses, None)

    if departments:
        records = [r for r in records if r.department_code in departments]

    if statuses:
        records = [r for r in records if r.transmission_status in statuses]

    if args.limit and args.limit > 0:
        records = records[: args.limit]

    return records


def write_urls_csv(
    args: argparse.Namespace,
    records: List[Record],
    tree_lookup: Dict[Tuple[str, str, str, str], Dict[str, Any]],
) -> None:
    import csv

    path = Path(args.urls_csv)

    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "url",
        "local_path",
        "id_transmission_code",
        "transmission_status",
        "corporation_code",
        "department_code",
        "department_name",
        "municipality_code",
        "municipality_name",
        "zone_code",
        "zone_name",
        "stand_code",
        "stand_name",
        "number_table",
        "expected_name",
    ]

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        for rec in records:
            names = enriched_names(rec, tree_lookup)

            row = {
                "url": build_pdf_url(args, rec),
                "local_path": str(local_pdf_path(args, rec)),
                **asdict(rec),
                **names,
            }

            writer.writerow({key: row.get(key, "") for key in fieldnames})


def run_download(
    args: argparse.Namespace,
    records: List[Record],
    tree_lookup: Dict[Tuple[str, str, str, str], Dict[str, Any]],
) -> None:
    total = len(records)
    out_dir = Path(args.out)
    log_dir = out_dir / "_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())

    manifest_path = (
        Path(args.manifest)
        if args.manifest
        else log_dir / f"manifest_{stamp}.jsonl"
    )

    errors_path = (
        Path(args.errors)
        if args.errors
        else log_dir / f"errors_{stamp}.jsonl"
    )

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    errors_path.parent.mkdir(parents=True, exist_ok=True)

    counts: Dict[str, int] = {}
    started = time.time()
    submitted = 0
    completed = 0

    iterator = iter(records)

    def submit_next(executor: ThreadPoolExecutor, futures: set) -> bool:
        nonlocal submitted

        try:
            rec = next(iterator)
        except StopIteration:
            return False

        futures.add(executor.submit(download_one, args, rec, tree_lookup))
        submitted += 1

        return True

    print(f"Registros a procesar: {total}")
    print(f"Manifiesto: {manifest_path}")
    print(f"Errores:    {errors_path}")

    with manifest_path.open("a", encoding="utf-8") as manifest_fh, errors_path.open("a", encoding="utf-8") as errors_fh:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = set()

            prefill = min(
                total,
                max(args.workers * args.queue_multiplier, args.workers),
            )

            for _ in range(prefill):
                submit_next(executor, futures)

            while futures:
                done, futures = wait(futures, return_when=FIRST_COMPLETED)

                for future in done:
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {
                            "timestamp_utc": now_utc(),
                            "status": "error",
                            "reason": f"worker_crash {exc!r}",
                        }

                    completed += 1

                    status = result.get("status", "unknown")
                    counts[status] = counts.get(status, 0) + 1

                    line = json.dumps(result, ensure_ascii=False)

                    manifest_fh.write(line + "\n")

                    if status == "error":
                        errors_fh.write(line + "\n")

                    if completed % args.flush_every == 0:
                        manifest_fh.flush()
                        errors_fh.flush()

                    if (
                        completed == total
                        or completed % args.progress_every == 0
                        or status == "error"
                    ):
                        elapsed = max(time.time() - started, 0.001)
                        rate = completed / elapsed

                        print(
                            f"{completed}/{total} | "
                            f"ok={counts.get('ok', 0)} "
                            f"skip={counts.get('skip', 0)} "
                            f"error={counts.get('error', 0)} | "
                            f"{rate:.2f} registros/s",
                            flush=True,
                        )

                    submit_next(executor, futures)

    print("Terminado.")
    print(json.dumps(counts, ensure_ascii=False, indent=2))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Descarga PDFs E-14 usando allTransmissionCodes.json y departmentsTree.json locales."
    )

    parser.add_argument(
        "--codes",
        required=True,
        help="Ruta a allTransmissionCodes.json",
    )

    parser.add_argument(
        "--tree",
        default="",
        help="Ruta a departmentsTree.json. Opcional, pero recomendado.",
    )

    parser.add_argument(
        "--out",
        default="e14_pdfs",
        help="Carpeta de salida",
    )

    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Host base del portal",
    )

    parser.add_argument(
        "--corporation-folder",
        default=DEFAULT_CORPORATION_FOLDER,
        help="Directorio de corporación en la URL. Para presidente: PRE",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Descargas paralelas. Recomendado: 3 a 6.",
    )

    parser.add_argument(
        "--queue-multiplier",
        type=int,
        default=4,
        help="Futuros en cola por worker.",
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=5,
        help="Reintentos por PDF.",
    )

    parser.add_argument(
        "--sleep-min",
        type=float,
        default=0.15,
        help="Pausa mínima antes de cada solicitud.",
    )

    parser.add_argument(
        "--sleep-max",
        type=float,
        default=0.50,
        help="Pausa máxima antes de cada solicitud.",
    )

    parser.add_argument(
        "--backoff-base",
        type=float,
        default=1.5,
        help="Base del backoff exponencial.",
    )

    parser.add_argument(
        "--max-backoff",
        type=float,
        default=60.0,
        help="Backoff máximo en segundos.",
    )

    parser.add_argument("--connect-timeout", type=float, default=15.0)
    parser.add_argument("--read-timeout", type=float, default=120.0)
    parser.add_argument("--chunk-size", type=int, default=128 * 1024)

    parser.add_argument(
        "--min-bytes",
        type=int,
        default=800,
        help="Tamaño mínimo aceptado para un PDF.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Redescarga aunque el PDF ya exista.",
    )

    parser.add_argument(
        "--departments",
        default="",
        help="Filtro opcional: 01,05,60. Vacío = todos.",
    )

    parser.add_argument(
        "--statuses",
        default="",
        help="Filtro opcional: 11,3. Vacío = todos.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limita la cantidad de registros. 0 = sin límite.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No descarga; imprime algunas URLs.",
    )

    parser.add_argument(
        "--urls-csv",
        default="",
        help="Escribe un CSV con URLs calculadas.",
    )

    parser.add_argument(
        "--only-urls",
        action="store_true",
        help="Solo genera --urls-csv y termina.",
    )

    parser.add_argument(
        "--manifest",
        default="",
        help="Ruta personalizada para manifest JSONL.",
    )

    parser.add_argument(
        "--errors",
        default="",
        help="Ruta personalizada para errores JSONL.",
    )

    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--flush-every", type=int, default=25)

    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (compatible; E14Downloader/1.0)",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.workers < 1:
        print("--workers debe ser >= 1", file=sys.stderr)
        return 2

    if args.sleep_max < args.sleep_min:
        print("--sleep-max no puede ser menor que --sleep-min", file=sys.stderr)
        return 2

    codes_path = Path(args.codes)
    tree_path = Path(args.tree) if args.tree else None

    print(f"Leyendo: {codes_path}")
    records = load_records(codes_path)

    print(f"Registros en JSON, sin duplicados: {len(records)}")

    tree_lookup = load_tree_lookup(tree_path)

    if tree_lookup:
        print(f"Puestos en departmentsTree: {len(tree_lookup)}")

    records = filter_records(records, args)

    print(f"Registros después de filtros: {len(records)}")

    if not records:
        print("No hay registros para procesar.")
        return 0

    if args.urls_csv:
        write_urls_csv(args, records, tree_lookup)
        print(f"CSV de URLs escrito en: {args.urls_csv}")

    if args.dry_run:
        n = min(len(records), args.limit if args.limit and args.limit > 0 else 10)

        for rec in records[:n]:
            print(build_pdf_url(args, rec))

        return 0

    if args.only_urls:
        if not args.urls_csv:
            print("Usa --urls-csv ruta.csv junto con --only-urls", file=sys.stderr)
            return 2

        return 0

    run_download(args, records, tree_lookup)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())