# ADR-031: Fachada `EngineService` como frontera única GUI↔motor

**Fecha:** 2026-07-17 · **Estado:** Aceptado

## Contexto
La Fase 6 construye una app de escritorio (PySide6) que compite con Untis. La
regla de oro del proyecto es que **toda la lógica vive en el motor**: la UI es
solo presentación y **nunca** debe contener reglas de negocio (nada de
`if profesor.horas > 30:` en un widget). Para garantizarlo por construcción hace
falta una frontera única, testeable sin ningún toolkit gráfico.

## Decisión

### 1. Una Fachada en proceso, no un servidor
`application/service.py` expone `EngineService`: abrir/guardar (`BjsProject`),
consultar (tablas, horario, dashboard), `validate`, `optimize` y edición básica.
La GUI la consume **en proceso** (llamada de método con callbacks nativos): cero
HTTP, cero serialización, cero servidor. Reutiliza íntegramente las Fases 1-4
(`runtime.run_engine`/`build_registry`/`analyze_feasibility`, `MetricsEngine`,
`check_consistency`, `solver_factory_for`).

### 2. Modelos de vista planos (`view_models.py`), sin Qt
Dataclasses inmutables (`EntityTables`, `TimetableView`, `DashboardStats`,
`ValidationReport`, `SolveOutcome`) que el motor **reconstruye desde el problema
canónico** del `.bjs`: clasifica recursos por *tag* (`teacher`/`group`/`room`),
deriva las materias del nombre de las tareas y ubica cada clase en su
`(día, período)` vía `TimeGrid.segment_of`. No se necesita la capa académica: el
`.bjs` es canónico y basta. La UI solo pinta estas estructuras.

### 3. Los fallos no escapan como excepciones
`optimize` **captura** `InfeasibleError`/`SolveTimeoutError`/`ConfigError` y
devuelve un `SolveOutcome` estructurado (`solved` + `status` + `message` +
`metrics`). La GUI nunca ve un *traceback*.

### 4. Cancelación cooperativa opt-in
`SolverConfig.should_stop` es un seam opcional (análogo a `on_event`): el
`ORToolsSolver` lo consulta en su callback de solución y hace `stop_search()`.
La app activa un `CancelToken` (bandera *thread-safe*) desde el botón *Detener*
sin acoplar la capa de aplicación a ningún solver ni toolkit.

## Consecuencias
- **Positivas:** frontera única y verificable; la lógica no puede filtrarse a la
  UI (los modelos de vista son de solo lectura); todo se prueba sin Qt (9 tests
  nuevos, 402 en total); reutilización máxima del motor existente.
- **Negativas:** la Fachada crece por módulo (esta es la rebanada mínima del MVP;
  reportes, import/export y CRUD completo llegan después).
- En español, coherente con el resto del repositorio.
