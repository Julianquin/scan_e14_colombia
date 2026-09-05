#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Carga de los archivos oficiales MMV (mesa a mesa con votos) de la Registraduría.

Cada ronda publica DOS conteos oficiales independientes por mesa:

  - PRECONTEO  (`PRE*_MMV_9999_PRECONTEO.txt`): el de la noche electoral.
    Informativo, sin valor jurídico.
  - ESCRUTINIO (`_ficheros_MMV_4_MMV_9999_ESCRUTINIO.csv`): el acto jurídico
    definitivo, días después. Es el que decide.

Que difieran NO es una anomalía por sí mismo: el escrutinio existe justamente
para corregir el preconteo. Lo que se audita es *cuánto*, *cómo* y *hacia
dónde* difieren (ver `auditar.py`).

Además vienen los archivos básicos de auditores, de los que este módulo usa:
  - INDICADORES: el **tope legal de votantes por mesa** según el tipo de puesto
    (360 nacional, 500/800/1200 puesto censo, 700 exterior). Es el `--cap-mesa`
    que `validacion/limite_habilitados.py` pedía confirmar a mano.
  - DIVIPOL: nombres y tipo de puesto (para saber qué tope aplica a cada mesa).
  - CANDIDATOS / PARTIDOS: para nombrar los códigos.

Formato (de `Estructuras Basicas (1808).pdf`, incluido en el mismo zip):

  PRECONTEO — ancho fijo, 38 caracteres:
    dep(2) muni(3) zona(2) puesto(2) mesa(6) jal(2) comunicado(4)
    circunscripcion(1) partido(5) candidato(3) votos(8)

  ESCRUTINIO — separado por ';':
    fijo9999(4) dep(2) muni(3) zona(3) puesto(2) mesa(6) comuna(2)
    corporacion(3) circunscripcion(1) partido(4) candidato(3) votos(8)

OJO con dos diferencias entre ambos formatos, que hay que normalizar para
cruzarlos: la ZONA va en 2 dígitos en preconteo y 3 en escrutinio, y el
PARTIDO en 5 y 4 respectivamente. `clave_mesa` y `cargar_*` ya lo hacen.

Los códigos de candidato 996/997/998 (con partido 0) son los agregados
(blanco / nulo / no marcado), no personas.

Uso:
    python -m e14.oficial.mmv verificar data/manifests/MMV_2V/MMV_Presidente2V_2026
    python -m e14.oficial.mmv resumen   data/manifests/MMV_2V/MMV_Presidente2V_2026
"""
from __future__ import annotations
import argparse, hashlib, re
from collections import defaultdict
from pathlib import Path

# códigos de candidato que no son personas (partido 0)
AGREGADOS = {996: "BLANCO", 997: "NULO", 998: "NO_MARCADO"}


# --------------------------------- claves ------------------------------------
def clave_mesa(dep, muni, zona, puesto, mesa) -> tuple:
    """Clave normalizada y comparable entre preconteo, escrutinio y las actas.

    zona y mesa a int (los ficheros los rellenan con ceros a distinta anchura);
    el puesto se deja como texto porque la especificación lo declara
    ALFANUMÉRICO — hay puestos '0A' y similares que int() rompería."""
    return (int(dep), int(muni), int(zona), str(puesto).strip(), int(mesa))


# -------------------------------- localizar ----------------------------------
def localizar(carpeta) -> dict:
    """Encuentra los ficheros dentro de la carpeta de una ronda (los zips traen
    un nivel extra de anidamiento que varía entre 1ra y 2da vuelta)."""
    carpeta = Path(carpeta)
    out = {}
    for p in carpeta.rglob("*"):
        n = p.name.upper()
        if n.endswith(".TXT") and "PRECONTEO" in n and not n.startswith("HASH"):
            out["preconteo"] = p
        elif n.endswith(".CSV") and "ESCRUTINIO" in n:
            out["escrutinio"] = p
        elif n.startswith("HASH_") and "PRECONTEO" in n:
            out["hash_preconteo"] = p
        elif n.startswith("HASH_") and "ESCRUTINIO" in n:
            out["hash_escrutinio"] = p
        elif n.startswith("INDICADORES"):
            out["indicadores"] = p
        elif n.startswith("DIVIPOL"):
            out["divipol"] = p
        elif n.startswith("CANDIDATOS"):
            out["candidatos"] = p
        elif n.startswith("PARTIDOS"):
            out["partidos"] = p
    return out


# ------------------------------- integridad ----------------------------------
def _hashes_declarados(path) -> dict:
    """Los ficheros HASH_* vienen en UTF-16 con MD5/SHA1/SHA-256/SHA-512."""
    txt = Path(path).read_text(encoding="utf-16", errors="ignore")
    out = {}
    for linea in txt.splitlines():
        if ":" not in linea:
            continue
        k, v = linea.split(":", 1)
        out[k.strip()] = v.strip().replace(" ", "")
    return out


def verificar(carpeta, verbose=True) -> bool:
    """Comprueba los datos contra los hashes que publica la propia Registraduría.

    Esto es lo que hace el análisis *reproducible por un tercero*: cualquiera
    puede recalcular el SHA-256 y confirmar que partimos del fichero oficial
    sin alterar."""
    f = localizar(carpeta)
    todo_ok = True
    for dat, hsh in (("preconteo", "hash_preconteo"), ("escrutinio", "hash_escrutinio")):
        if dat not in f or hsh not in f:
            if verbose:
                print(f"  {dat:11s} FALTA el fichero o su HASH")
            todo_ok = False
            continue
        esperado = _hashes_declarados(f[hsh]).get("SHA-256", "").lower()
        real = hashlib.sha256(f[dat].read_bytes()).hexdigest()
        ok = (esperado == real)
        todo_ok &= ok
        if verbose:
            print(f"  {dat:11s} SHA-256 {'OK' if ok else 'NO COINCIDE'}   {f[dat].name}")
            if not ok:
                print(f"      declarado: {esperado}\n      real     : {real}")
    return todo_ok


# --------------------------------- carga -------------------------------------
def cargar_preconteo(path) -> dict:
    """{clave_mesa: {(partido, candidato): votos}} — ancho fijo de 38."""
    datos = defaultdict(dict)
    with open(path, encoding="latin-1") as fh:
        for linea in fh:
            linea = linea.rstrip("\r\n")
            if len(linea) < 38:
                continue
            k = clave_mesa(linea[0:2], linea[2:5], linea[5:7], linea[7:9], linea[9:15])
            datos[k][(int(linea[22:27]), int(linea[27:30]))] = int(linea[30:38])
    return dict(datos)


def cargar_escrutinio(path) -> dict:
    """{clave_mesa: {(partido, candidato): votos}} — separado por ';'."""
    datos = defaultdict(dict)
    with open(path, encoding="latin-1") as fh:
        for linea in fh:
            p = linea.rstrip("\r\n;").split(";")
            if len(p) < 12:
                continue
            k = clave_mesa(p[1], p[2], p[3], p[4], p[5])
            datos[k][(int(p[9]), int(p[10]))] = int(p[11])
    return dict(datos)


def cargar_indicadores(path) -> dict:
    """{codigo: (descripcion, potencial_max_por_mesa)} — el TOPE LEGAL."""
    out = {}
    for linea in Path(path).read_text(encoding="latin-1").splitlines():
        if len(linea) < 105:
            continue
        out[int(linea[0])] = (linea[1:101].strip(), int(linea[101:105]))
    return out


def cargar_divipol(path) -> dict:
    """{(dep,muni,zona,puesto): dict} con nombres, indicador de puesto y censo."""
    out = {}
    for linea in Path(path).read_text(encoding="latin-1").splitlines():
        if len(linea) < 60:
            continue
        try:
            dep, muni, zona, pue = linea[0:2], linea[2:5], linea[5:7], linea[7:9]
            out[(int(dep), int(muni), int(zona), pue.strip())] = {
                "departamento": linea[9:21].strip(),
                "municipio": linea[21:51].strip(),
                "puesto": linea[51:91].strip(),
                "indicador": int(linea[91:92]),
                "pot_hombres": int(linea[92:100] or 0),
                "pot_mujeres": int(linea[100:108] or 0),
                "mesas": int(linea[108:114] or 0),
            }
        except (ValueError, IndexError):
            continue
    return out


def cargar_candidatos(path) -> dict:
    """{(partido, candidato): 'NOMBRE APELLIDO'}."""
    out = {}
    for linea in Path(path).read_text(encoding="latin-1").splitlines():
        if len(linea) < 120:
            continue
        try:
            partido, cand = int(linea[11:16]), int(linea[16:19])
            nombre = linea[20:70].strip()
            apellido = linea[70:120].strip()
            out[(partido, cand)] = f"{nombre} {apellido}".strip()
        except ValueError:
            continue
    return out


def nombre_de(cod: tuple, candidatos: dict) -> str:
    """Nombre legible de un (partido, candidato), incluidos los agregados."""
    if cod[0] == 0 and cod[1] in AGREGADOS:
        return AGREGADOS[cod[1]]
    return candidatos.get(cod, f"{cod[0]}/{cod[1]}")


def mismos_votos(a: dict, b: dict, solo_candidatos: bool = True) -> bool:
    """¿Dos mesas tienen los mismos votos?

    Compara sobre la UNIÓN de códigos con default 0. Un fichero puede omitir la
    fila de un candidato con 0 votos y el otro incluirla: `a == b` los daría por
    distintos sin que cambie ni un voto. Ese error ya se coló dos veces (infló
    las mesas "cambiadas" de 1.151 a 1.532 en auditar.py, y marcó el 60 % de las
    mesas como "inestables" en dataset_oficial.py), así que vive aquí una sola
    vez."""
    codigos = set(a) | set(b)
    if solo_candidatos:
        codigos = {c for c in codigos if es_candidato(c)}
    return all(a.get(c, 0) == b.get(c, 0) for c in codigos)


def es_candidato(cod: tuple) -> bool:
    """True si es una persona (no BLANCO/NULO/NO_MARCADO)."""
    return not (cod[0] == 0 and cod[1] in AGREGADOS)


# --------------------------------- resumen -----------------------------------
def resumen(carpeta):
    f = localizar(carpeta)
    print(f"=== {Path(carpeta).name} ===")
    for k in ("preconteo", "escrutinio", "indicadores", "divipol", "candidatos"):
        print(f"  {k:12s} {'-> ' + f[k].name if k in f else 'NO ENCONTRADO'}")
    print("\nIntegridad (SHA-256 contra el hash oficial):")
    verificar(carpeta)

    if "indicadores" in f:
        print("\nTopes legales de votantes por mesa (INDICADORES):")
        for c, (desc, pot) in sorted(cargar_indicadores(f["indicadores"]).items()):
            print(f"  {c}  {desc:45s} {pot:>5}")

    cand = cargar_candidatos(f["candidatos"]) if "candidatos" in f else {}
    if "escrutinio" in f:
        esc = cargar_escrutinio(f["escrutinio"])
        tot = defaultdict(int)
        for votos in esc.values():
            for cod, v in votos.items():
                tot[cod] += v
        suma = sum(tot.values())
        print(f"\nESCRUTINIO — {len(esc):,} mesas, {suma:,} votos:")
        for cod, v in sorted(tot.items(), key=lambda kv: -kv[1]):
            print(f"  {nombre_de(cod, cand):32s} {v:>12,}  {100*v/max(1,suma):5.2f}%")
        personas = sorted(((v, c) for c, v in tot.items() if es_candidato(c)), reverse=True)
        if len(personas) >= 2:
            m = personas[0][0] - personas[1][0]
            print(f"\n  MARGEN: {m:,} votos = {100*m/max(1,suma):.2f}% "
                  f"({m/max(1,len(esc)):.1f} votos por mesa)")


def main():
    ap = argparse.ArgumentParser(description="Archivos oficiales MMV (preconteo y escrutinio)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("verificar"); p.add_argument("carpeta")
    p = sub.add_parser("resumen"); p.add_argument("carpeta")
    a = ap.parse_args()
    if a.cmd == "verificar":
        ok = verificar(a.carpeta)
        print("\nTodos los ficheros verifican." if ok else "\nHAY FICHEROS QUE NO VERIFICAN.")
    elif a.cmd == "resumen":
        resumen(a.carpeta)


if __name__ == "__main__":
    main()
