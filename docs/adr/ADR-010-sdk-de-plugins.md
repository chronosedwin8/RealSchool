# ADR-010: SDK de Plugins

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
Prompt3 §5: el núcleo jamás debe modificarse para agregar reglas; los plugins
generan definiciones DSL que entran en el pipeline de compilación y no ejecutan
código sobre variables del solver. Falta un vocabulario de variables de
decisión que los plugins puedan referenciar antes de existir el modelo CP-SAT.

## Decisiones adoptadas

### 1. Vocabulario simbólico de variables en un contexto
`SchedulingModelContext` define las variables de decisión como `Var` del DSL con
keys estables y solver-agnósticas:
- `start#t{task}#s{slot}` (bool): la tarea inicia en ese slot.
- `assign#t{task}#r{resource}` (bool): la tarea usa ese recurso.
La Fase 7 mapeará cada key a una variable CP-SAT concreta; el DSL/CIR ya operan
sobre estas keys sin conocer el solver.

### 2. Restricciones estructurales en el contexto, no como "reglas"
El contexto aporta la *semántica* de las variables (cada tarea inicia una vez;
cada requerimiento se satisface con su cantidad). No son reglas de negocio, por
lo que viven en el contexto y no en un plugin. El no-solape de recursos, que sí
requiere variables de ocupación, se añadirá en la Fase 8.

### 3. Plugins puros que solo emiten DSL
`SchedulingPlugin.contribute(context) -> Contribution` devuelve restricciones
DSL y términos de penalización; jamás toca el solver. Un arnés de contrato
(`assert_plugin_contract`) exige determinismo, DSL puro y que solo se
referencien variables del contexto.

### 4. Registro con activación dinámica y descubrimiento
`PluginRegistry` registra explícitamente o por `discover_plugins(package)`
(escaneo de módulos), activa/desactiva por nombre y ensambla el `DslModel`
(estructurales + contribuciones activas). Un plugin de tercero se integra con
`register(...)` sin modificar el núcleo.

## Consecuencias técnicas
- **Núcleo cerrado a modificación, abierto a extensión:** nuevas reglas son
  plugins; el pipeline las trata de forma opaca (nunca las nombra).
- **Verificado end-to-end:** `TeacherLunchPlugin` atraviesa el pipeline hasta el
  `FakeSolver` sin que el core lo conozca por nombre.
- **Deuda acotada:** el ejemplo de almuerzo es una versión global (prohíbe
  ocupar el slot); la granular por docente llega en la Fase 8 con variables de
  ocupación. El catálogo completo de reglas también es Fase 8.
