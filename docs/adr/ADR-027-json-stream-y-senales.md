# ADR-027: Progreso en vivo (`--json-stream`) e interrupción segura

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
Una GUI futura invocará el binario de forma asíncrona y necesita (1) pintar
progreso sin bloquearse y (2) poder cancelar una resolución pesada sin corromper
el proyecto. Es el objetivo declarado de "GUI-ready" de la Fase 2 (H12).

## Decisión

### 1. Seam de eventos en el Core, opt-in (impacto cero por defecto)
`pipeline/events.py` define `ProgressEvent` y `ProgressCallback`. `pipeline.run`
y `engine.solve` aceptan un `on_event: ProgressCallback | None = None`; con `None`
el comportamiento es **idéntico** al histórico (verificado por test). El pipeline
emite hitos de etapa (`analysis_started`, `compilation_started`,
`solver_searching`, `search_finished`) con porcentaje. No se tocó la interfaz de
la SAL.

### 2. Enrutado del progreso según el modo (contrato de streams intacto)
`AppContext.emit_progress` decide el canal:
- **`--json-stream`**: los eventos van por `stdout` como **JSONL** (son el canal
  de datos en vivo para la GUI); el dispatcher cierra con un evento
  `{"event":"completed","result":…}`. `stdout` contiene **solo** JSONL.
- **modo normal**: el progreso va a `stderr` como texto; `stdout` recibe solo el
  payload final (Zero-Leakage preservado).

### 3. Interrupción segura (SIGINT/SIGTERM)
El dispatcher intercepta `KeyboardInterrupt` y devuelve **exit 130** (convención
POSIX), sin escribir nada en `stdout`. La CLI mapea `SIGTERM` a `KeyboardInterrupt`
para que ambas señales converjan. Como la escritura del `.schedule` es **atómica**
(ADR-025) y solo ocurre tras un solve exitoso, un Ctrl+C durante la búsqueda deja
el proyecto original intacto.

## Consecuencias
- **Positivas:** el binario es GUI-ready — stream de progreso estable y
  cancelación limpia, verificados por test y en el binario real. El Core sigue
  agnóstico: el seam es opcional y no cambia nada cuando no se usa.
- **Alcance:** los eventos son de **etapa** (no gap intra-búsqueda en vivo);
  emitir mejoras de gap durante la búsqueda de CP-SAT requeriría extender la
  interfaz de la SAL con un callback de solución y queda como endurecimiento
  futuro. El `first_solution_ms` ya se captura en la telemetría (O9).
