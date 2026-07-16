# ADR-019: Catálogo canónico de restricciones y reglas de estructura diaria

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
La Actividad 2 pide clasificar formalmente cada restricción (ID, nombre,
descripción, peso, tipo) sobre el Modelo Canónico (Resource/Task/TimeSlot), y
completar las reglas blandas que faltaban (huecos, continuidad, balance, jornada,
consecutivas blandas). El motor ya tenía los plugins duros y la estabilidad de
aula (ADR-018), pero sin un registro único ni las reglas de estructura diaria.

## Decisión

### 1. `constraint_catalog.py` — fuente única de verdad
Cada restricción es una `ConstraintDefinition` inmutable con `id`, `name`,
`description`, `kind` (HARD/SOFT/STRUCTURAL), `tier` y `plugin_name`. El catálogo
mapea **21 restricciones** (13 duras, 8 blandas) a su plugin implementador, o a
`None` cuando se satisface *por construcción* (HC-05 disponibilidad en el dominio
de `tstart`; HC-06 acoples como una única Task; HC-07 matching por tags). Un test
verifica **cobertura bidireccional**: todo plugin del repo tiene entrada y
viceversa. `registry_from_catalog(ids)` arma el `PluginRegistry` deduplicando por
plugin (HC-01/02/03 comparten `interval_no_overlap`).

### 2. Reglas de estructura diaria (SC-02/04/05/07/08)
Cinco plugins nuevos, todos sobre una ocupación booleana compartida
(`busy#r{rid}#k{slot}`, módulo `occupancy.py`) que el pase de deduplicación del
CIR colapsa entre reglas:

- **SC-02 huecos** — indicadores monótonos `before`/`after` por período; un hueco
  es un período libre con clase antes y después (`gap ≥ before + after − busy − 1`).
- **SC-04 continuidad** — penaliza cada arranque de bloque (`blk ≥ busy − busy_prev`).
- **SC-05 balance** — minimiza la carga del día más cargado (`peak ≥ carga_día`).
- **SC-07 jornada** — penaliza la longitud del tramo ocupado (`span` inclusivo).
- **SC-08 consecutivas blanda** — holgura sobre el máximo de la versión dura.

Todas **requieren `boolean_starts=True`** (la ocupación período-a-período no
existe en el modelo puro de intervalos), lo que queda documentado.

## Consecuencias
- **Positivas:** Actividad 2 cerrada con clasificación auditable y documentación
  viva (`scripts/catalog.py`). Las reglas comparten la misma maquinaria de
  ocupación, sin duplicar coste. Cada regla probada con caso mínimo y caso
  forzado con OR-Tools real.
- **Negativas:** las reglas diarias exigen el modo booleano (modelo más grande);
  medir su coste a escala real es trabajo de O3 (telemetría) y O9 (huecos vs Untis).
- El Scoring por Tiers declarado en el catálogo se hace operativo en O2 (ADR-020).
