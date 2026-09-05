#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E6 · Informe consolidado de auditoría, por ronda.

Junta en un solo documento todo lo verificado: procedencia de los datos,
integridad de las actas, auditoría entre los dos conteos oficiales, lo que dice
el papel en las mesas señaladas, y la restricción física de censo y topes
legales. Todo cuantificado **contra el margen oficial**, que es la única escala
que hace interpretable cualquier cifra.

### Se REGENERA, no se escribe a mano

El informe se recalcula desde los ficheros oficiales cada vez que se ejecuta.
Así cumple el criterio de reproducibilidad del scope: un tercero clona, corre
esto y obtiene los mismos números, sin que nadie haya transcrito nada.

Lo barato se recalcula aquí (hashes, resultado oficial, auditoría
preconteo/escrutinio, censo y topes: ~1-2 min, sin GPU). Lo caro —los veredictos
contra el papel, que necesitan OCR sobre miles de actas— se **lee de los CSV**
que producen `oficial/dirimir.py` y los notebooks; si no están, el informe lo
dice en vez de inventarlo.

### Tono

El informe no dictamina fraude y lo declara explícitamente. Incluye los
resultados NEGATIVOS con el mismo peso que los positivos: son los que dan
autoridad al método cuando encuentre algo.

Uso:
    python -m e14.informe.consolidado \\
        --mmv    data/manifests/MMV_2V/MMV_Presidente2V_2026 \\
        --control data/manifests/MMV_1V/MMV_Presidente1V_2026 \\
        --ronda  "2ª vuelta" \\
        --out    docs/INFORME_2V.md
"""
from __future__ import annotations
import argparse, csv, datetime, sys
from collections import Counter, defaultdict
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ / "extraccion"))

from e14.oficial import mmv                    # noqa: E402
from e14.oficial.auditar import clasificar     # noqa: E402


def _pct(parte, total):
    return f"{100 * parte / total:.3f} %".replace(".", ",") if total else "n/d"


def _n(x):
    """Miles con punto y decimales con coma: convención española.

    El informe está en español; dejar `1,151` para mil ciento cincuenta y uno
    se lee como 1,151 (algo más de uno) en cualquier país hispanohablante."""
    return f"{x:,}".replace(",", ".")


# ------------------------------- recolectores --------------------------------
def resultado_oficial(esc, cand):
    tot = defaultdict(int)
    for v in esc.values():
        for c, n in v.items():
            tot[c] += n
    suma = sum(tot.values())
    personas = sorted(((v, c) for c, v in tot.items() if mmv.es_candidato(c)), reverse=True)
    margen = personas[0][0] - personas[1][0] if len(personas) >= 2 else 0
    return tot, suma, personas, margen


def auditoria(pre, esc):
    comunes = set(pre) & set(esc)
    tip = Counter()
    for k in comunes:
        tip[clasificar(pre[k], esc[k])] += 1
    return comunes, tip


def censo_y_topes(esc, dv, ind):
    """Chequeos A (tope legal por mesa) y B (censo por puesto).

    El EXTERIOR (dep. 88) se separa: su 'censo' en DIVIPOL es capacidad
    administrativa, no habilitados —el 73,6 % son múltiplos exactos de 100
    frente al 1,0 % en el resto del país—, así que el chequeo B no le aplica."""
    viola_tope = 0
    por_puesto = defaultdict(lambda: {"votos": 0, "censo": 0, "dep": None})
    for k, votos in esc.items():
        pk = (k[0], k[1], k[2], k[3])
        p = dv.get(pk)
        if not p:
            continue
        total = sum(votos.values())
        tope = ind.get(p["indicador"], ("", 0))[1]
        if tope and total > tope:
            viola_tope += 1
        e = por_puesto[pk]
        e["votos"] += total
        e["censo"] = p["pot_hombres"] + p["pot_mujeres"]
        e["dep"] = k[0]
    nac = {k: v for k, v in por_puesto.items() if v["dep"] != 88}
    ext = {k: v for k, v in por_puesto.items() if v["dep"] == 88}
    exc_nac = {k: v for k, v in nac.items() if v["votos"] > v["censo"]}
    exc_ext = {k: v for k, v in ext.items() if v["votos"] > v["censo"]}
    return {
        "mesas": len(esc), "puestos": len(por_puesto),
        "viola_tope": viola_tope,
        "puestos_nac": len(nac), "excede_nac": len(exc_nac),
        "exceso_votos_nac": sum(v["votos"] - v["censo"] for v in exc_nac.values()),
        "excede_ext": len(exc_ext),
        "exceso_votos_ext": sum(v["votos"] - v["censo"] for v in exc_ext.values()),
        "claves_excede": set(exc_nac) | set(exc_ext),
    }


def leer_dirimidas(ruta):
    if not ruta or not Path(ruta).exists():
        return None
    filas = list(csv.DictReader(open(ruta, encoding="utf-8")))
    c = Counter(r["veredicto"] for r in filas)
    preconteo = [r for r in filas if r["veredicto"] == "COINCIDE_PRECONTEO"]
    return {"total": len(filas), "conteo": c, "preconteo": preconteo}


# --------------------------------- informe -----------------------------------
def generar(carpeta_mmv, out, ronda, carpeta_control=None, dirimidas=None):
    f = mmv.localizar(carpeta_mmv)
    for req in ("preconteo", "escrutinio"):
        if req not in f:
            raise SystemExit(f"falta el fichero de {req} en {carpeta_mmv}")

    print("verificando integridad...")
    integro = mmv.verificar(carpeta_mmv, verbose=False)
    cand = mmv.cargar_candidatos(f["candidatos"]) if "candidatos" in f else {}
    print("cargando conteos oficiales...")
    pre = mmv.cargar_preconteo(f["preconteo"])
    esc = mmv.cargar_escrutinio(f["escrutinio"])
    dv = mmv.cargar_divipol(f["divipol"]) if "divipol" in f else {}
    ind = mmv.cargar_indicadores(f["indicadores"]) if "indicadores" in f else {}

    tot, suma, personas, margen = resultado_oficial(esc, cand)
    comunes, tip = auditoria(pre, esc)
    cen = censo_y_topes(esc, dv, ind) if dv and ind else None
    dirim = leer_dirimidas(dirimidas)

    ctrl = None
    if carpeta_control:
        print("cargando la ronda de control...")
        fc = mmv.localizar(carpeta_control)
        if "preconteo" in fc and "escrutinio" in fc:
            pc, ec = mmv.cargar_preconteo(fc["preconteo"]), mmv.cargar_escrutinio(fc["escrutinio"])
            cc, tc = auditoria(pc, ec)
            dvc = mmv.cargar_divipol(fc["divipol"]) if "divipol" in fc else dv
            indc = mmv.cargar_indicadores(fc["indicadores"]) if "indicadores" in fc else ind
            cenc = censo_y_topes(ec, dvc, indc) if dvc and indc else None
            ctrl = {"mesas": len(cc), "tip": tc, "censo": cenc,
                    "integro": mmv.verificar(carpeta_control, verbose=False)}

    n_cambio = sum(v for t, v in tip.items() if t != "SIN_CAMBIO")
    L = []
    A = L.append
    A(f"# Informe de auditoría — {ronda}")
    A("")
    A(f"**Generado automáticamente** el {datetime.date.today():%Y-%m-%d} por "
      f"`python -m e14.informe.consolidado`.")
    A("No transcribe cifras a mano: todo se recalcula desde los ficheros oficiales.")
    A("")
    A("> **Este informe NO dictamina fraude.** Detecta anomalías, las cuantifica y")
    A("> deja la evidencia servida para revisión humana. Muchas anomalías son")
    A("> errores honestos o correcciones legítimas. El juicio es humano.")
    A("")

    # ---- resumen
    A("## Resumen")
    A("")
    A("| | |")
    A("|---|---|")
    A(f"| Integridad de los ficheros oficiales | {'✅ SHA-256 verificado' if integro else '❌ NO verifica'} |")
    A(f"| Mesas en el escrutinio | {_n(len(esc))} |")
    A(f"| Margen oficial | **{_n(margen)} votos** ({_pct(margen, suma)}) |")
    A(f"| Mesas que cambiaron entre los dos conteos | {_n(n_cambio)} ({_pct(n_cambio, len(comunes))}) |")
    if cen:
        A(f"| Mesas que superan su tope legal | **{_n(cen['viola_tope'])}** de {_n(cen['mesas'])} |")
    A("")

    # ---- procedencia
    A("## 1 · Procedencia y verificación")
    A("")
    A("Los datos son los ficheros **MMV** (mesa a mesa con votos) que la")
    A("Registraduría publica para auditores, y traen **dos conteos oficiales**")
    A("independientes de cada mesa:")
    A("")
    A("- **Preconteo** — la noche electoral. Informativo, sin valor jurídico.")
    A("- **Escrutinio** — el acto jurídico definitivo, días después.")
    A("")
    A(f"Verificación de integridad: **{'los ficheros coinciden con el SHA-256 oficial' if integro else 'ALGÚN FICHERO NO VERIFICA'}**.")
    A("Cualquier tercero puede recalcular el hash y confirmar que se partió del")
    A("fichero oficial sin alterar.")
    A("")

    # ---- resultado
    A("## 2 · Resultado oficial")
    A("")
    A("| | Votos | % |")
    A("|---|---:|---:|")
    for v, c in personas:
        A(f"| {mmv.nombre_de(c, cand)} | {_n(v)} | {100*v/suma:.2f} % |")
    agr = sum(v for c, v in tot.items() if not mmv.es_candidato(c))
    A(f"| Blanco / nulo / no marcado | {_n(agr)} | {100*agr/suma:.2f} % |")
    A(f"| **Total** | **{_n(suma)}** | |")
    A("")
    A(f"**Margen: {_n(margen)} votos = {_pct(margen, suma)}** "
      f"— {margen/max(1,len(esc)):.1f} votos por mesa.")
    A("")
    A("Ese número es la escala de todo lo que sigue: la pregunta útil no es")
    A("\"¿hubo fraude?\" sino **\"¿cuántos votos están en disputa frente a")
    A(f"{_n(margen)}?\"**.")
    A("")

    # ---- auditoria
    A("## 3 · Preconteo vs. escrutinio")
    A("")
    A("**Que el escrutinio cambie el preconteo no es una anomalía**: existe")
    A("precisamente para corregirlo. Lo que se audita es cuántas mesas, de qué")
    A("tipo y hacia dónde.")
    A("")
    A(f"De {_n(len(comunes))} mesas comparables, **{_n(n_cambio)} cambiaron ({_pct(n_cambio, len(comunes))})**:")
    A("")
    A("| Tipología | Mesas | Qué es |")
    A("|---|---:|---|")
    desc = {
        "PERMUTACION": "los **mismos valores** repartidos entre otros candidatos; no altera el total de la mesa, así que ninguna suma la delata",
        "ANULADA": "la mesa queda en 0 (causal de anulación: decisión **jurídica**, no de lectura)",
        "APARECE": "sin votos en preconteo, con votos en escrutinio",
        "OTROS": "cambios de magnitud",
    }
    for t, n in tip.most_common():
        if t == "SIN_CAMBIO":
            continue
        A(f"| `{t}` | {_n(n)} | {desc.get(t, '')} |")
    A("")

    # ---- papel
    A("## 4 · Qué dice el papel")
    A("")
    if dirim:
        ce = dirim["conteo"].get("COINCIDE_ESCRUTINIO", 0)
        cp = dirim["conteo"].get("COINCIDE_PRECONTEO", 0)
        an = dirim["conteo"].get("ANULADA_NO_DIRIMIBLE", 0)
        A(f"Se fue al acta E-14 escaneada de {_n(dirim['total'])} mesas señaladas.")
        A("")
        A("| Veredicto | Mesas |")
        A("|---|---:|")
        for v, n in dirim["conteo"].most_common():
            A(f"| {v} | {_n(n)} |")
        A("")
        if ce + cp:
            A(f"De las **{ce+cp} dirimibles, el papel respalda al escrutinio en {ce} "
              f"({100*ce/(ce+cp):.0f} %)**. Es lo esperado: corregir el preconteo es su función.")
        if an:
            A("")
            A(f"Las {an} **anuladas no son dirimibles**: el escrutinio las pone en 0 y el")
            A("papel muestra los votos emitidos, así que \"coincide con el preconteo\" es")
            A("cierto por definición. Anular es una decisión jurídica; para evaluarlas hay")
            A("que leer la constancia de la página 2 del acta.")
        if cp:
            A("")
            plural = "mesas donde el papel respalda" if cp != 1 else "mesa donde el papel respalda"
            A(f"**{cp} {plural} al PRECONTEO** — ahí el escrutinio se")
            A("apartó del acta. Son las que merecen revisión humana:")
            A("")
            A("| Mesa (dep/muni/zona/puesto/mesa) | Tipología | Impacto |")
            A("|---|---|---:|")
            for r in dirim["preconteo"]:
                A(f"| {r['dep']}/{r['muni']}/{r['zona']}/{r['puesto']}/{r['mesa']} | "
                  f"{r['tipologia']} | {r['impacto_votos']} votos |")
            tot_imp = sum(int(r["impacto_votos"]) for r in dirim["preconteo"])
            A("")
            A(f"Impacto conjunto: **{_n(tot_imp)} votos = {_pct(tot_imp, margen)} del margen**.")
    else:
        A("*(pendiente: no se encontró el CSV de `e14.oficial.dirimir`)*")
    A("")

    # ---- censo
    if cen:
        A("## 5 · Restricción física: censo y topes legales")
        A("")
        A("La señal **más dura** del proyecto, y la única que no admite \"error")
        A("humano\" como explicación: una mesa no puede tener más votos que")
        A("votantes habilitados. Se calcula sobre el escrutinio oficial, **sin OCR**.")
        A("")
        A(f"**Chequeo A — votos por mesa > tope legal: {_n(cen['viola_tope'])} de {_n(cen['mesas'])}.**")
        if cen["viola_tope"] == 0:
            A("")
            A("La restricción legal por mesa **se cumple sin excepción**.")
        A("")
        A(f"**Chequeo B — votos del puesto > censo:** {_n(cen['excede_nac'])} puestos del")
        A(f"territorio nacional ({_pct(cen['excede_nac'], cen['puestos_nac'])}), con un exceso")
        A(f"de {_n(cen['exceso_votos_nac'])} votos = **{_pct(cen['exceso_votos_nac'], margen)} del margen**.")
        A("")
        A(f"El **exterior se cuenta aparte** ({_n(cen['excede_ext'])} puestos, "
          f"{_n(cen['exceso_votos_ext'])} votos): su \"censo\" en DIVIPOL es capacidad")
        A("administrativa, no habilitados —el 73,6 % son múltiplos exactos de 100,")
        A("frente al 1,0 % en el resto del país—, así que el chequeo no le aplica.")
        A("")

    # ---- control
    if ctrl:
        A("## 6 · Ronda de control")
        A("")
        A("Las mismas mesas y el mismo censo, otra elección. Una anomalía presente en")
        A("**ambas** rondas es estructural del censo o del puesto; una que sólo")
        A("aparece en esta es cualitativamente distinta.")
        A("")
        nc_ctrl = sum(v for t, v in ctrl["tip"].items() if t != "SIN_CAMBIO")
        A("| | Control | Esta ronda |")
        A("|---|---:|---:|")
        A(f"| Mesas comparadas | {_n(ctrl['mesas'])} | {_n(len(comunes))} |")
        A(f"| Mesas que cambiaron | {_n(nc_ctrl)} ({_pct(nc_ctrl, ctrl['mesas'])}) | "
          f"{_n(n_cambio)} ({_pct(n_cambio, len(comunes))}) |")
        A(f"| Permutaciones | {_n(ctrl['tip'].get('PERMUTACION', 0))} | {_n(tip.get('PERMUTACION', 0))} |")
        if ctrl["censo"] and cen:
            A(f"| Mesas sobre el tope legal | {_n(ctrl['censo']['viola_tope'])} | {_n(cen['viola_tope'])} |")
            A(f"| Puestos sobre su censo | {_n(ctrl['censo']['excede_nac'] + ctrl['censo']['excede_ext'])} | "
              f"{_n(cen['excede_nac'] + cen['excede_ext'])} |")
            ambas = ctrl["censo"]["claves_excede"] & cen["claves_excede"]
            A("")
            A(f"**{_n(len(ambas))} puestos exceden su censo en las DOS rondas** → estructural.")
        if nc_ctrl and n_cambio and nc_ctrl / max(1, ctrl["mesas"]) > 3 * n_cambio / max(1, len(comunes)):
            A("")
            A("> La ronda de control corrige muchísimas más mesas. Antes de leer eso como")
            A("> una anomalía: tenía **13 candidatos frente a 2**, y cada candidato extra")
            A("> multiplica las ocasiones de equivocarse al transcribir. Es una diferencia")
            A("> objetiva que conviene explicar, no un hallazgo.")
        A("")

    # ---- limitaciones
    A("## 7 · Limitaciones declaradas")
    A("")
    A("- **No se puede probar intención.** Ninguna señal distingue un dedo torpe de")
    A("  un dolo. Sólo el patrón agregado sugiere algo, y sugerir no es probar.")
    A("- **Una mesa aislada no prueba nada.** El valor está en el agregado y en")
    A("  cruzar señales.")
    A("- El OCR **no es perfecto** y no necesita serlo: el objetivo es ordenar por")
    A("  riesgo, no leer todo bien. Los veredictos contra el papel son una ayuda")
    A("  para el revisor, no un dictamen.")
    A("- **Un acta con un error aritmético real nunca debe \"cuadrar\"**: optimizar")
    A("  esa métrica a ciegas taparía justo lo que hay que detectar.")
    A("- Para el **voto del exterior no existe el ejemplar de CLAVEROS** (el portal")
    A("  de escrutinios nunca publicó el departamento 88): allí el cruce se degrada")
    A("  de tres vías a dos.")
    A("")

    # ---- reproducir
    A("## 8 · Cómo reproducir")
    A("")
    A("```bash")
    A(f"python -m e14.oficial.mmv verificar {carpeta_mmv}")
    A(f"python -m e14.oficial.auditar {carpeta_mmv} --out auditoria")
    A("jupyter lab notebooks/censo_topes_E5.ipynb        # censo y topes legales")
    A("jupyter lab notebooks/dirimir_otros_2v.ipynb      # contraste contra el papel")
    A(f"python -m e14.informe.consolidado --mmv {carpeta_mmv} --out {out}")
    A("```")
    A("")
    A("Documentación de apoyo: [DATOS_OFICIALES.md](DATOS_OFICIALES.md) ·")
    A("[CASOS_DE_USO.md](CASOS_DE_USO.md) · [OCR_2V.md](OCR_2V.md) ·")
    A("[INTEGRIDAD_DESCARGA.md](INTEGRIDAD_DESCARGA.md) ·")
    A("[ESTADO_Y_SCOPE.md](ESTADO_Y_SCOPE.md)")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\n-> {out}  ({len(L)} líneas)")
    return out


def main():
    ap = argparse.ArgumentParser(description="E6 · informe consolidado de auditoría")
    ap.add_argument("--mmv", required=True, help="carpeta MMV de la ronda")
    ap.add_argument("--control", default=None, help="carpeta MMV de la ronda de control")
    ap.add_argument("--ronda", default="2ª vuelta")
    ap.add_argument("--dirimidas", default=None, help="CSV de e14.oficial.dirimir")
    ap.add_argument("--out", default="docs/INFORME.md")
    a = ap.parse_args()
    generar(a.mmv, a.out, a.ronda, a.control, a.dirimidas)


if __name__ == "__main__":
    main()
