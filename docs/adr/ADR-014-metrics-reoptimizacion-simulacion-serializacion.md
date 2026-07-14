# ADR-014: Metrics, ReOptimization, Simulation y Serialización

**Fecha:** 2026-07-14 · **Estado:** Aceptado

## Contexto
Prompt3 §5 exige capacidad de reoptimización parcial (congelar y recalcular solo
lo necesario) y un modo sandbox de simulación; `contextobase.md` pedía un Metrics
Engine para comparar horarios objetivamente y serialización JSON/YAML/formato
propio.

## Decisiones adoptadas

### 1. Congelar es *otra regla dura*, no un segundo motor
La reoptimización no necesita un motor paralelo: `FrozenSchedulePlugin` fija las
variables `start`/`assign` de las clases congeladas y entra por el **mismo**
pipeline. `ReOptimizationEngine` solo compone plugins y delega en
`SchedulingEngine`. Consecuencia: cero código de scheduling duplicado, y el
invariante "lo congelado no se mueve" es verificable directamente.

### 2. Métricas calculadas desde el horario, no desde el solver
`MetricsEngine` reconstruye la ocupación a partir de la `Solution`, igual que el
Validation Engine. KPIs: uso de aulas, huecos *intercalados* (los del principio y
final del día no cuentan — no son un problema real), balance de carga docente,
violaciones duras y un `quality_score` 0-100 con pesos configurables. Una
violación dura hunde el score a 0: un horario inválido no es "casi bueno".

### 3. Simulación como comparación de dos problemas, sin estado
`SimulationEngine.compare(baseline, scenario)` resuelve ambos y compara KPIs. No
muta nada: un escenario "what-if" es simplemente otro problema canónico. Cuando
la línea base es infactible y el escenario no, se reporta explícitamente (no hay
KPIs que comparar, pero la respuesta —"contratar ese docente lo vuelve
factible"— es la que importa).

### 4. Serialización en tres capas
`codec.py` es la única capa que conoce la *forma* de los datos (entidades ↔
diccionarios). JSON, YAML y `.proschedule` solo eligen cómo escribir esos
diccionarios; cambiar de formato de fichero no toca la traducción de entidades.
El `.proschedule` es JSON comprimido con gzip, **versionado**: rechaza formatos
ajenos y versiones de esquema incompatibles en vez de fallar de forma opaca.

## Consecuencias técnicas
- **Reproducibilidad garantizada:** un `.proschedule` recargado en una ejecución
  limpia produce el mismo horario (verificado en pruebas).
- **Round-trip property-based:** cualquier problema académico generado
  aleatoriamente sobrevive a exportar → importar sin perder información.
- **Deuda:** el `quality_score` combina criterios con pesos arbitrarios pero
  configurables y documentados; conviene calibrarlos con datos reales durante los
  benchmarks (Fase 11).
