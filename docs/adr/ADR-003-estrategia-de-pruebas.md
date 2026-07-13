# ADR-003: Estrategia de pruebas multicapa para software de optimización

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
Un solver puede "correr" y devolver resultados incorrectos en silencio (modelo
mal formulado, pase de optimización que altera la semántica, pesos mal
escalados). Los tests unitarios clásicos no bastan para detectar eso.

## Alternativas evaluadas
1. **Solo tests unitarios + integración** — insuficiente: no detectan errores
   de formulación matemática.
2. **Suite multicapa específica de optimización** — mayor inversión inicial en
   arneses de prueba, garantía real de corrección.

## Decisión adoptada
Opción 2, con estas capas obligatorias (detalle en `PLAN_DE_TRABAJO.md` §3):
- Estático: `mypy --strict` + `ruff`.
- Arquitectura: prueba automática de que solo `sal` importa `ortools`.
- Unitarias (`pytest`) y property-based (`hypothesis`) por módulo.
- Differential testing: optimizer passes ON vs OFF ⇒ misma factibilidad y óptimo.
- Oráculos: instancias pequeñas con óptimo calculado a mano.
- Metamórficas: permutar la entrada no cambia el óptimo; determinismo por semilla.
- Validación post-solución independiente del solver.
- Rendimiento: `pytest-benchmark` con presupuestos por tamaño de instancia.

Ninguna fase se cierra sin `scripts/check.py` en verde y cobertura ≥ 90% en el
módulo de la fase.

## Consecuencias técnicas
La Fase 4 (CIR) concentra el mayor esfuerzo de arneses (enumeración exhaustiva
de espacios de solución en instancias pequeñas). A cambio, los pases de
optimización quedan matemáticamente auditados y las regresiones se detectan de
inmediato.
