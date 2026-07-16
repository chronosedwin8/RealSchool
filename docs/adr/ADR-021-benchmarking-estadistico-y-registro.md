# ADR-021: Benchmarking estadístico, registro automático y trazabilidad

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
Las Actividades 4, 5 y 12 piden ejecutar cada escenario N veces con estadística
(para eliminar el ruido del SO/hardware), registrar cada experimento
automáticamente en un JSON, y garantizar reproducibilidad (commit, hardware,
config). El proyecto no usa Docker ni PostgreSQL (decisión del plan), así que el
aislamiento se logra con calentamiento + semilla fija y el registro es en
ficheros.

## Decisión

### 1. `stats.py` — resumen estadístico
`summarize(values)` → media, mediana, desviación estándar, mínimo, máximo,
**P50/P95/P99** e **IC 95 %** con la **t de Student** (tabla de valores críticos
embebida, `1.96` para df > 30; sin dependencia de scipy). `summarize_runs` agrega
cada métrica numérica de las N corridas.

### 2. `suite.py` — protocolo de medición
`run_scenario` ejecuta `warmup` corridas descartadas + `reps` medidas sobre el
`BenchmarkRunner`, con repeticiones **escalonadas** por tamaño (20 small, 10
medium, 5 large, 3 xl). Semilla fija y workers fijos por defecto.

### 3. `record.py` — registro trazable y PG-ready
`BenchmarkRecord` (dataclass congelada) combina el esquema de la Actividad 5 con
la trazabilidad de la 12: `Provenance` captura commit y rama de Git, versiones de
paquetes (`importlib.metadata`), hardware (CPU, hilos, RAM vía `psutil`), SO y
Python. Se **persiste automáticamente** como JSON (estructura JSONB-compatible,
lista para migrar a PostgreSQL sin cambios) y como **informe Markdown gemelo**.
Nunca a mano.

### 4. `scripts/bench.py` — CLI única
`run <preset>`, `quick` (small+medium, gate), `full` (todos los presets) y
`compare <A> <B>` (diferencias porcentuales de las métricas clave). Sin Docker:
el aislamiento es calentamiento + semilla.

## Consecuencias
- **Positivas:** medición reproducible y auditable con una sola orden; los JSON
  alimentan el dashboard (O7) y el gate de regresiones (O8); esquema listo para
  PostgreSQL cuando haya multi-máquina.
- **Negativas / decisiones:** sin Pydantic (se usa el patrón de dataclasses del
  repo); sin Docker (aislamiento por protocolo, no por contenedor); DS-04 real se
  mide en el harness de comparación con Untis (O9), no en `bench` sintético.
- **Umbrales de tiempo/RAM:** su verificación vive en el gate local (O8), no en
  CI, porque en runners compartidos el ruido dispararía falsos positivos.
