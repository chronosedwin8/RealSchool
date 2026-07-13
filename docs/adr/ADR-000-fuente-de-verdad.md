# ADR-000: Prompt3.md como fuente de verdad de la especificación

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
Existen cuatro documentos con especificaciones parcialmente divergentes:
`promptInicial.md`, `contextobase.md`, `Prompt2.md` y `Prompt3.md`.

## Alternativas evaluadas
1. **Fusionar todos los documentos** — riesgo de contradicciones (ej. Prompt2 obliga
   matrices booleanas 3D; Prompt3 lo deja a criterio justificado).
2. **Seguir solo Prompt3** — se perderían requisitos valiosos ausentes en él
   (testing formal, validación post-solución, formatos de serialización).
3. **Prompt3 como base + rescate selectivo documentado** — lo mejor de ambos.

## Decisión adoptada
Opción 3. Prompt3 manda; de los documentos previos se rescatan únicamente: la
estrategia formal de pruebas y benchmarks, el Validation Engine post-solución y
los formatos de serialización (JSON/YAML/`.proschedule`). Todo quedó registrado
en `PLAN_DE_TRABAJO.md`.

## Consecuencias técnicas
Especificación única y sin ambigüedad. Los prompts anteriores quedan como
contexto histórico y no deben citarse como requisito.
