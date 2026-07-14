# ADR-008: CIR y Optimizer Passes

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
Prompt3 §2.3 exige un flujo de compilación multicapa (DSL -> CIR -> Optimizer
Passes -> Solver Compiler) que permita simplificar, deduplicar y analizar las
restricciones antes de instanciar el solver, y detectar infactibilidades
estructurales lo antes posible.

## Decisiones adoptadas

### 1. CIR canónico referenciado por `key`
Los nodos (`CirLinear`, `CirAllDifferent`, `CirBoolOr`, `CirImplication`)
referencian variables por su `key` (str); los dominios viven en `CirModel`.
Términos ordenados y sin ceros hacen que restricciones estructuralmente
idénticas sean *iguales* (hashables), habilitando dedup y análisis triviales.

### 2. Dependencias acíclicas
`cir` importa `dsl` (lowering) y `sal` (Solver Compiler). El compilador directo
DSL->solver de la Fase 3 se conserva intacto; el camino canónico de producción
pasa ahora por el CIR (`lower -> PassManager -> CirToSolverCompiler`).

### 3. Conjunto de pases y su corrección
`SimplifyLinearByGcd` (división por mcd con floor/ceil según integralidad),
`DeduplicateConstraints`, `FuseComparableLinear` (cota más estricta; EQ
incompatible -> restricción falsa canónica), `RemoveTrivialConstraints`,
`DetectContradictions` (constantes imposibles, EQ sin solución entera, valores
fuera de dominio, igualdades en conflicto) y `ReorderForPropagation`.
`PassManager` es configurable (`without(...)`).

### 4. Verificación por preservación semántica exhaustiva
Cada pase se valida generando modelos CIR diminutos (variables de dominio
pequeño) y comparando el **espacio completo de soluciones** (enumeración por
fuerza bruta) antes y después. El pipeline completo o preserva ese espacio o
lanza `StructuralContradictionError`, en cuyo caso el espacio original debe ser
vacío. Se añade *differential testing* (pases ON vs OFF).

## Consecuencias técnicas
- **Corrección demostrada**, no solo "ejecuta": los pases quedan auditados
  matemáticamente sobre instancias pequeñas.
- **Infactibilidad temprana:** las contradicciones estructurales se detectan
  antes del solver; la Fase 5 las convertirá en explicaciones legibles.
- **Serialización textual del CIR** habilita snapshot tests y depuración.
- **Alcance:** el CIR cubre el subconjunto lineal/booleano/all-different;
  `NoOverlap`/`Cumulative` se añadirán en la Fase 7 con su modelado CP-SAT.
