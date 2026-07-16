# Decisiones de arquitectura (ADR)

Cada decisión relevante está registrada como un **ADR** (Architecture Decision
Record): contexto, decisión y consecuencias. Son la fuente de verdad del *por qué*
del diseño. Aquí están ordenados por fase.

## Fundamentos (Fase 0–1)

- [ADR-000 — Fuente de verdad](../adr/ADR-000-fuente-de-verdad.md)
- [ADR-001 — Python y toolchain](../adr/ADR-001-python-y-toolchain.md)
- [ADR-002 — OR-Tools CP-SAT](../adr/ADR-002-or-tools-cp-sat.md)
- [ADR-003 — Estrategia de pruebas](../adr/ADR-003-estrategia-de-pruebas.md)
- [ADR-004 — Tiempo discreto por segmentos](../adr/ADR-004-tiempo-discreto-segmentos.md)
- [ADR-005 — Constraint seam](../adr/ADR-005-constraint-seam.md)
- [ADR-006 — Adaptador y alcance académico](../adr/ADR-006-adaptador-y-alcance-academico.md)
- [ADR-007 — SAL y DSL](../adr/ADR-007-sal-y-dsl.md)
- [ADR-008 — CIR y Optimizer Passes](../adr/ADR-008-cir-y-optimizer-passes.md)
- [ADR-009 — Pipeline y explicación de conflictos](../adr/ADR-009-pipeline-y-conflict-explanation.md)
- [ADR-010 — SDK de plugins](../adr/ADR-010-sdk-de-plugins.md)
- [ADR-011 — Modelo CP-SAT](../adr/ADR-011-modelo-cp-sat.md)
- [ADR-012 — Rule Engine y Scoring Engine](../adr/ADR-012-rule-engine-y-scoring-engine.md)
- [ADR-013 — Motor de validación y telemetría](../adr/ADR-013-motor-validacion-y-telemetria.md)
- [ADR-014 — Métricas, reoptimización, simulación, serialización](../adr/ADR-014-metrics-reoptimizacion-simulacion-serializacion.md)
- [ADR-015 — Formulación por intervalos y escala](../adr/ADR-015-formulacion-por-intervalos-y-escala.md)
- [ADR-016 — Dataset DS-04 Untis real](../adr/ADR-016-dataset-ds04-untis-real.md)
- [ADR-017 — Warm start](../adr/ADR-017-warm-start.md)
- [ADR-018 — Objetivo de calidad: estabilidad de aula](../adr/ADR-018-objetivo-de-calidad-estabilidad-de-aula.md)

## Optimización del motor (Fase 1, O1–O10)

- [ADR-019 — Catálogo canónico de restricciones](../adr/ADR-019-catalogo-canonico-de-restricciones.md)
- [ADR-020 — Scoring Engine con Tiers](../adr/ADR-020-scoring-engine-tiers.md)
- [ADR-021 — Benchmarking estadístico y registro](../adr/ADR-021-benchmarking-estadistico-y-registro.md)
- [ADR-022 — Multi-solver MILP vía SAL](../adr/ADR-022-multi-solver-milp-via-sal.md)
- [ADR-023 — Optimización dirigida por evidencia](../adr/ADR-023-optimizacion-dirigida-por-evidencia.md)

## Headless Engine (Fase 2, H1–H12)

- [ADR-024 — Capa de aplicación y Command Dispatcher](../adr/ADR-024-capa-de-aplicacion-y-command-dispatcher.md)
- [ADR-025 — Formato de proyecto (.schedule)](../adr/ADR-025-formato-schedule.md)
- [ADR-026 — CLI Typer schedule-engine](../adr/ADR-026-cli-typer-schedule-engine.md)
- [ADR-027 — json-stream y señales](../adr/ADR-027-json-stream-y-senales.md)

## Persistencia y distribución (Fase 3, B1–B7)

- [ADR-028 — Formato .bjs](../adr/ADR-028-formato-bjs.md)
- [ADR-029 — Distribución como binario nativo](../adr/ADR-029-distribucion-binario-nativo.md)
