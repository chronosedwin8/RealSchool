# Telemetría y eventos de progreso

El motor mide cada corrida y puede emitir eventos en vivo. Ambos son **opcionales**
y no cambian el comportamiento por defecto.

## Telemetría por etapa

Cada `solve` produce una `Telemetry` con latencias y composición del modelo:

```python
result = engine.solve(problem, config)
t = result.telemetry
print(t.t_analyze_ms, t.t_compile_ms, t.t_solve_ms, t.t_total_ms)
print(t.num_variables, t.num_bool_vars, t.num_int_vars, t.num_intervals)
print(t.num_branches, t.num_conflicts, t.t_first_solution_ms)
```

Es la base del **framework de benchmarking** (`benchmarks/`): `run_scenario`
ejecuta N repeticiones y resume con media, mediana, P50/P95/P99 e IC95, y guarda un
`BenchmarkRecord` trazable (commit, hardware, config). Ver
[API — engine](../reference/engine.md).

## Eventos de progreso en vivo (`on_event`)

`engine.solve(..., on_event=callback)` recibe `ProgressEvent` en cada hito
(análisis, compilación, búsqueda, fin). Con `None` (por defecto) no hay coste.

```python
from scheduling_platform.pipeline.events import ProgressEvent

def on_event(ev: ProgressEvent) -> None:
    print(ev.event, ev.stage, ev.percentage)

engine.solve(problem, config, on_event=on_event)
```

## El stream JSONL para una GUI

La CLI enruta esos eventos con `--json-stream`: los emite por `stdout` como líneas
JSON, terminando con `{"event":"completed","result":...}`. Es lo que una interfaz
gráfica consume para pintar el progreso sin bloquearse:

```json
{"event": "solver_searching", "stage": "search", "percentage": 60, "variables": 20070}
{"event": "completed", "result": {"quality_score": 94.2}}
```

En modo normal (sin el flag), el progreso va a `stderr` como texto y `stdout`
recibe solo el resultado final (invariante *Zero-Leakage*).

## Interrupción segura

Un `Ctrl+C`/`SIGTERM` durante la búsqueda termina limpio (exit 130) sin corromper
el `.bjs` (la escritura es atómica y solo ocurre tras un solve exitoso). Detalle en
**ADR-027**.

Referencia: [API — engine](../reference/engine.md) ·
[application](../reference/application.md).
