# ADR-005: `Constraint` como *seam* abstracto en el núcleo

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
Prompt3 §2.2 lista `Constraint` como entidad canónica, pero Prompt3 §2.3 exige
que el álgebra de restricciones se produzca vía DSL y se compile en el CIR
(`DSL -> CIR -> Optimizer Passes -> Solver`). ¿Qué es una `Constraint` en el
núcleo (Fase 1) frente a las fases de compilación (3-4)?

## Alternativas evaluadas
1. **El core contiene el álgebra de cada restricción** — colapsaría la razón de
   ser del pipeline DSL/CIR y acoplaría el núcleo a la mecánica de compilación.
2. **El core solo porta metadatos y delega la compilación** — `Constraint` es
   un contrato abstracto (id, nombre, clasificación dura/blanda + peso); su
   contenido algebraico lo generan las fases posteriores.

## Decisión adoptada
Opción 2, en `core/constraint.py`: ABC `Constraint` con `id`/`name` y propiedad
abstracta `kind`; subclases `HardConstraint` (satisfacción obligatoria) y
`SoftConstraint` (con `weight > 0`, penalizada en la función objetivo). El
método de compilación a DSL/CIR se añadirá como *seam* en la Fase 3, cuando el
DSL exista, sin tocar el núcleo. La jerarquía usa `frozen=True` sin `slots`
por ser polimórfica y de bajo volumen.

## Consecuencias técnicas
- **Separación de capas:** el núcleo no conoce CP-SAT ni el CIR.
- **Extensibilidad:** nuevas familias de restricciones se añaden como plugins
  (Fase 6) que declaran DSL; el core permanece intacto.
- **Coste:** una indirección adicional entre "declarar" y "compilar" una
  restricción, asumida a cambio de portabilidad de solver.
