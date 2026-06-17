# Banderas de consistencia (sin OCR)

El procesador ahora calcula, para cada acta, unas banderas basadas SOLO en el
patrón de casillas llenas/vacías (no necesita leer los números todavía).

## Banderas (NINGUNA significa fraude — son señales para revisión humana)

PRIORIDAD ALTA:
- `suma_vacia_con_votos`  → SUMA_TOTAL vacía pero hay votos de candidatos.
  (Ej.: el caso que detectaste; suele ser error de diligenciamiento, pero
   una casilla de total vacía también es donde podría alterarse sin notarse.)
- `sin_ningun_voto`       → ninguna casilla de candidato ni agregado con número.
- `suma_con_todo_vacio`   → hay total escrito pero ningún voto. ¿De dónde sale?

PRIORIDAD MEDIA:
- `todos_candidatos_llenos` → los 13 candidatos tienen número (inusual).
- `agregados_sin_suma`      → hay blanco/nulo/no marcado pero no suma.

INFO (contexto, no es anomalía):
- `tiene_constancias`     → el recuadro de constancias tiene texto. Clave para
  interpretar las demás banderas (una corrección documentada explica muchas).
- `n_cand_con_voto`       → cuántos candidatos recibieron votos.

Cada acta recibe `prioridad_revision` = ALTA / MEDIA / OK (la más alta que aplique).

## Nuevas columnas en el CSV
n_cand_con_voto, suma_vacia_con_votos, sin_ningun_voto, suma_con_todo_vacio,
todos_candidatos_llenos, agregados_sin_suma, tiene_constancias, prioridad_revision

## Listar anomalías tras la corrida
```bash
# Solo prioridad ALTA
python listar_anomalias.py resultados/casillas_e14.csv --salida anomalias.csv

# Incluir también MEDIA
python listar_anomalias.py resultados/casillas_e14.csv --salida anomalias.csv --incluir-media
```
Genera un CSV ordenado por prioridad, listo para revisión humana, con la
ubicación (dep/muni/zona/puesto/mesa) y la ruta del PDF de cada acta marcada.

## Importante
Estas banderas son un PRIMER FILTRO sin OCR. El veredicto real llega con la
Fase 1 (lectura de números + cruce: suma candidatos + blanco + nulo + no
marcado == SUMA_TOTAL == total E-11) y la lectura del recuadro de constancias.
