# PLAN DE TRABAJO MAESTRO
# Scheduling Optimization Platform — Academic Module
**Versión:** 1.0 · **Fecha:** 2026-07-13 · **Fuente de verdad:** `Prompt3.md`

---

## 0. Análisis previo: de la idea original a la especificación vigente

### 0.1 Evolución de los documentos

| Documento | Rol | Estado |
|---|---|---|
| `contextobase.md` | Idea original: motor académico basado en OR-Tools, con la mejora clave de separar dominio ↔ solver (Constraint Translator / Solution Builder) | Contexto histórico |
| `Prompt2.md` | Formalización: DDD + Hexagonal, ACL del solver, mapeo matricial obligatorio | Superado |
| `Prompt3.md` | **Especificación vigente.** Generaliza el motor (Modelo Canónico: `Resource`, `Task`, `TimeSlot`), introduce el pipeline de compilación DSL → CIR → Optimizer Passes → Solver Compiler, SAL, Conflict Explanation Engine, ReOptimization y Simulation | **Prioritario** |

### 0.2 Qué cambió de Prompt2 a Prompt3 (y por qué importa)

1. **El motor deja de conocer "colegios".** El core solo conoce `Resource`, `Task`, `TimeSlot`, `Constraint`, `Assignment`. El módulo académico es un adaptador encima. Esto habilita futuros módulos (hospitales, fábricas, aerolíneas) sin tocar el núcleo.
2. **Se relaja el "Matrix Mapping" obligatorio.** Prompt2 forzaba `BoolVar` 3D `X[t,r,s]` y prohibía `AddElement`/`AddAllowedAssignments`; Prompt3 (§2.1.1) exige elegir la formulación más eficiente **justificándola** — decisión correcta, porque `IntervalVar` + `NoOverlap` suele dominar a matrices booleanas en scheduling.
3. **Aparece el CIR** (Constraint Intermediate Representation) con pases de optimización estilo LLVM: deduplicación, fusión, simplificación algebraica, detección de contradicciones, reordenamiento.
4. **Pipeline de optimización completo** (§3): validación → normalización → grafo de restricciones → compilación → solver → explicación de conflictos → solution builder + métricas.

### 0.3 Requisitos valiosos de documentos anteriores que Prompt3 no menciona explícitamente (se incorporan al plan como mejoras)

- **Estrategia de pruebas y benchmarks formal** ("no escribir código sin pruebas", `tests/`, `benchmarks/`) — contextobase la exigía; Prompt3 no tiene sección de testing. **Se reincorpora como pilar transversal (§3 de este plan).**
- **Validation Engine post-solución** ("nunca confiar únicamente en el solver") — validación independiente de la solución reconstruida. Se integra en la Fase 9.
- **Formatos de serialización concretos** (JSON, YAML, formato propio `.proschedule`) — se integran en la Fase 10.
- **Determinismo y telemetría** (`random_seed`, `num_search_workers`, `max_time_in_seconds`, `SolutionInspector`) — Prompt3 los menciona en la Fase 9; se les añaden pruebas de determinismo.
- **Stack fijado por Prompt2/contextobase:** Python 3.13+, typing estricto, sin persistencia en el core, SOLID/Clean Architecture/DDD.

---

## 1. Alcance global

Construir una **Plataforma de Optimización de Calendarización** con:

- **Core genérico** independiente de dominio, framework y solver.
- **Pipeline de compilación de restricciones** DSL → CIR → Optimizer Passes → Solver Compiler.
- **Solver Abstraction Layer (SAL):** OR-Tools CP-SAT como primera implementación, reemplazable.
- **Módulo Académico** como primer adaptador de dominio (multi-institución, multi-sede, multi-jornada).
- **SDK de plugins:** el núcleo jamás se modifica para agregar reglas.
- **Escalabilidad objetivo:** 500 docentes, 300 aulas, 1500 grupos, 10 edificios, miles de restricciones.

**Arquitectura de capas (regla de dependencias — solo hacia abajo, nunca hacia arriba):**

```
Academic Module (Teacher, Room, Subject…)          ← dominio específico, no conoce al solver
        │  Adapter (Academic → Canónico)
        ▼
Canonical Model (Resource, Task, TimeSlot,
                 Constraint, Assignment)           ← el core no conoce "colegios"
        │  Plugins → DSL
        ▼
CIR + Optimizer Passes                             ← álgebra pura, no conoce CP-SAT
        │  Solver Compiler
        ▼
Solver Abstraction Layer (ISolver)                 ← ORToolsSolver | (futuro) GurobiSolver
        │
        ▼
Solution Builder → Validation → Metrics → Schedule
```

---

## 2. Fases de desarrollo

> Orden estricto de Prompt3 §7. Se añade una **Fase 0** (mejora propuesta): sin fundaciones de ingeniería no puede cumplirse "cada módulo con tests" ni typing estricto verificable. Cada fase termina con sus pruebas en verde y sus ADRs escritos antes de pasar a la siguiente (guardrail §6 de Prompt3).

### FASE 0 — Fundaciones de ingeniería *(mejora propuesta, ~pre-requisito)*
- **Entregables:** estructura de paquetes (`src/` layout), `pyproject.toml` (uv o poetry), `ruff` (lint+format), `mypy --strict`, `pytest` + `hypothesis` + `pytest-benchmark`, CI local (script `check`), `docs/adr/` con plantilla ADR y los ADR-000x iniciales (¿por qué Python?, ¿por qué CP-SAT?, ¿por qué CIR?).
- **Pruebas de rigor:** pipeline de calidad ejecuta en limpio; smoke test de import de `ortools` en Python 3.13.
- **Criterio de salida:** `check` (lint + types + tests) pasa en verde en un repositorio git inicializado.

### FASE 1 — Arquitectura del Core y Modelo Canónico  ✅ COMPLETADA (2026-07-13)

> Entregado: 10 módulos en `core/` (ids, time_grid, requirement, resource, task, constraint, assignment, problem, solution, exceptions); 53 tests (unitarios + property-based + aislamiento dinámico sin ortools); cobertura 99%; ADR-004/005. Pipeline `check.py` en verde.

- **Entregables:** entidades canónicas `Resource`, `Task`, `TimeSlot`, `Constraint`, `Assignment` como objetos inmutables puros; value objects temporales (rejilla de slots discreta); interfaces del core; documento de arquitectura + ADRs (granularidad del slot, identidad de entidades, inmutabilidad).
- **Decisión clave a justificar:** representación del tiempo (rejilla discreta uniforme vs. intervalos continuos). Recomendación: rejilla discreta de slots — CP-SAT trabaja con enteros y los marcos horarios escolares son discretos por naturaleza.
- **Pruebas de rigor:** unitarias de invariantes (un `TimeSlot` no puede tener fin ≤ inicio; `Task` exige duración > 0); property-based (Hypothesis) sobre operaciones de la rejilla temporal (unión/intersección/contención de rangos).
- **Criterio de salida:** el core importa sin `ortools` instalado (prueba automática de aislamiento de dependencias).

### FASE 2 — Academic Module y Adaptador al Modelo Canónico  ✅ COMPLETADA (2026-07-13)

> Entregado: entidades académicas (TimeFrame, Room, Teacher+disponibilidad, StudentGroup, Subject, TeachingAssignment), agregado AcademicProblem, y `AcademicToCanonicalAdapter` con traducción por tags (docente/grupo fijos, aula elegible) + reconstrucción inversa a AcademicSchedule. 74 tests (round-trip, property-based, aislamiento core+academic sin ortools); cobertura 99%; ADR-006. Pipeline `check.py` en verde.

- **Entregables:** entidades académicas (Infraestructura: Institución, Sede, Campus, Edificio, Piso, Aula, Laboratorio, Capacidad, Equipamiento · Temporal: Calendario, Período, Año Lectivo, Jornada, Marco Horario, Bloque, Receso, Almuerzo · Académico: Docente, Disponibilidad, Materia, Carga, Asignación, Curso, Grupo, Nivel, Sección, Estudiante · Operacional: Horario, Clase, Evento, Restricción, Preferencia, Conflicto, Resultado); `AcademicToCanonicalAdapter` con mapeo bidireccional de IDs.
- **Pruebas de rigor:** round-trip del adaptador (académico → canónico → académico preserva la información); property-based sobre generadores aleatorios de instituciones válidas; test de que el módulo académico no importa nada del solver.
- **Criterio de salida:** una institución de juguete ("mini-colegio": 3 docentes, 2 grupos, 4 materias) se traduce a modelo canónico verificable a mano.

### FASE 3 — Solver Abstraction Layer (SAL) y Constraint DSL  ✅ COMPLETADA (2026-07-13)

> Entregado: SAL (`ISolver` con handles opacos, `SolverConfig`, `Literal`, `FakeSolver`), DSL (`Var`/`LinearExpr`/`Relation` con operadores, `LinearConstraint`/`AllDifferent`/`BoolOr`/`Implication`, `Objective`, `DslModel`) y `DslToSolverCompiler` (seam del Solver Compiler). 101 tests (álgebra DSL, bajada a FakeSolver, contrato ISolver reutilizable); cobertura dsl+sal 98%; ADR-007. Pipeline `check.py` en verde.

- **Entregables:** interfaz `ISolver` (`add_constraint()`, `add_objective()`, `solve()`, `get_assignment()`); DSL declarativo de restricciones (expresiones algebraicas componibles: `all_different`, `no_overlap`, `implies`, `sum(...) <= k`, cardinalidad, consecutividad); `FakeSolver` de pruebas que registra llamadas.
- **Pruebas de rigor:** el DSL construye árboles de expresión correctos (unitarias); contrato de `ISolver` verificado contra `FakeSolver`; ninguna clase fuera del SAL importa `ortools` (test de arquitectura con `grep`/import-linter automatizado).
- **Criterio de salida:** una restricción de juguete expresada en DSL llega al `FakeSolver` sin que el core toque `model.Add(...)`.

### FASE 4 — CIR y Optimizer Passes  ✅ COMPLETADA (2026-07-13)

> Entregado: CIR canónico (`CirLinear`/`AllDifferent`/`BoolOr`/`Implication`/`CirModel`), `lower(DSL->CIR)`, `CirToSolverCompiler`, evaluador de referencia (`satisfies`), serialización textual, y 6 optimizer passes (`SimplifyLinearByGcd`, `Deduplicate`, `FuseComparableLinear`, `RemoveTrivial`, `DetectContradictions`, `Reorder`) con `PassManager`. 121 tests: **preservación semántica por enumeración exhaustiva**, differential testing, snapshots, contradicciones sembradas; cobertura cir 97%; ADR-008. Pipeline `check.py` en verde.

- **Entregables:** representación intermedia (nodos algebraicos tipados, normalizados); pases: eliminación de redundantes, fusión de equivalentes, simplificación algebraica, detección de contradicciones estructurales, reordenamiento para propagación; `PassManager` configurable; serialización del CIR a texto (debugging y snapshot tests).
- **Pruebas de rigor (las más críticas del proyecto):**
  - **Property-based de preservación semántica:** para instancias pequeñas generadas por Hypothesis, el espacio de soluciones antes y después de cada pase es idéntico (verificado por enumeración exhaustiva en instancias ≤ N variables).
  - **Differential testing:** resolver con pases ON vs OFF debe dar la misma factibilidad y el mismo valor óptimo.
  - Snapshot tests del CIR serializado para casos canónicos.
- **Criterio de salida:** todo pase demuestra preservación semántica; contradicciones sembradas a propósito son detectadas antes del solver.

### FASE 5 — Optimization Pipeline (Graph Builder y Conflict Explanation)  ✅ COMPLETADA (2026-07-13)

> Entregado: `ConstraintGraphBuilder` (4 chequeos de infactibilidad por condición necesaria: tag sin proveedor, dominio temporal vacío, sobre-suscripción de recurso unario, demanda>oferta global), `ConflictExplanationEngine` (traduce hallazgos y `StructuralContradictionError` a `ConflictReport` renderizable), `OptimizationPipeline` (orquestador con DI del solver: analizar→CIR+pases→compilar→solve). 133 tests: catálogo de instancias infactibles con explicación accionable, pipeline e2e con FakeSolver; cobertura pipeline 100%; ADR-009. Pipeline `check.py` en verde.

- **Entregables:** orquestador del pipeline (validación pre-solver → normalización/escalado de pesos → `ConstraintGraphBuilder` → compilación → solve → explicación/solución); detección de inviabilidades estructurales sobre el grafo (ej. demanda de horas > oferta disponible, aforo insuficiente, bipartitos sin matching posible — regla de Hall en casos simples); `ConflictExplanationEngine` que ante `INFEASIBLE` produce explicación legible ("Profesor Juan tiene 37h bloqueadas y debe impartir 42h; faltan 5h").
- **Pruebas de rigor:** batería de **instancias inviables diseñadas** (una por categoría de conflicto) donde se verifica que (a) el grafo detecta las estructurales sin invocar solver, y (b) la explicación menciona las entidades correctas; pruebas del escalador de pesos (ningún criterio blando puede dominar numéricamente a otro por error de escala).
- **Criterio de salida:** 100% de las instancias inviables del catálogo producen explicación accionable, nunca un "INFEASIBLE" mudo.

### FASE 6 — Sistema de Plugins (SDK)  ✅ COMPLETADA (2026-07-13)

> Entregado: `SchedulingModelContext` (vocabulario simbólico de variables `start`/`assign` + restricciones estructurales base), `SchedulingPlugin`/`Contribution` (plugins puros que solo emiten DSL), `PluginRegistry` (registro, activación dinámica, `build_model`, `discover_plugins`), y catálogo de ejemplo (`TeacherLunchPlugin`, `ForbiddenStartsPlugin`). 146 tests: arnés de contrato de plugin, activación/desactivación cambia el modelo, discovery, plugin de tercero sin tocar el núcleo, y `TeacherLunchPlugin` end-to-end por el pipeline con FakeSolver; cobertura plugins 98%; ADR-010. Pipeline `check.py` en verde.

- **Entregables:** interfaz de plugin (declara restricciones vía DSL, nunca ejecuta código sobre variables del solver); descubrimiento/registro automático; activación/desactivación dinámica por configuración; catálogo inicial organizado (`teacher/`, `student/`, `room/`, `subject/`, `institution/`); documentación del SDK con plugin de ejemplo.
- **Pruebas de rigor:** test de contrato que todo plugin debe pasar (arnés reutilizable del SDK); prueba de que activar/desactivar un plugin cambia el CIR resultante y nada más; prueba de que un plugin de terceros (carpeta externa) se registra sin modificar el núcleo.
- **Criterio de salida:** `TeacherLunchPlugin` de ejemplo funciona end-to-end sin que el core lo conozca por nombre.

### FASE 7 — Modelo matemático CP-SAT  ✅ COMPLETADA (2026-07-13)

> Entregado: `ORToolsSolver` (implementa `ISolver` sobre CP-SAT; único módulo que importa `ortools`, no reexportado en `sal/__init__`), estrategia de variables booleana `start`/`assign` justificada (ADR-011), `ResourceNoOverlapPlugin` (no-solape por linealización de ocupación), y `SolverConfig` con `random_seed`/`num_search_workers`/`max_time_in_seconds`. 157 tests: contrato ISolver sobre solver real, **oráculo con óptimo calculado a mano**, **determinismo** con semilla fija, **metamórficas** (permutar entrada ⇒ mismo óptimo); cobertura sal+catalog 98%; ADR-011. Pipeline `check.py` en verde. Deuda: reformulación por intervalos para escala (Fase 11).

- **Entregables:** `ORToolsSolver` (implementación del SAL); estrategia de variables documentada y justificada por tipo de restricción — previsiblemente: `OptionalIntervalVar` + `NoOverlap` para exclusión mutua de recursos, `BoolVar` de asignación para compatibilidades, `Cumulative` para capacidades, enteros solo para holguras/contadores; documento "Modelo Matemático" con la justificación exigida por §2.1.1; todas las variables instanciadas antes de `Solve()` (sin lógica condicional dinámica).
- **Pruebas de rigor:** instancias mínimas con **óptimo conocido calculado a mano** (oráculos); metamórficas (permutar el orden de entrada de entidades no cambia el valor óptimo); pruebas de determinismo con `random_seed` fijo; micro-benchmarks comparando formulaciones alternativas cuando se use `AddElement`/`AddAllowedAssignments` (justificación por análisis de rendimiento, §2.5).
- **Criterio de salida:** el mini-colegio de la Fase 2 obtiene horario óptimo verificado a mano.

### FASE 8 — Rule Engine y Scoring Engine (compilación a CIR)  ✅ COMPLETADA (2026-07-14)

> Entregado: `PenaltyTerm` + `ScoringEngine` (objetivo unificado `min Σ peso·holgura`, `normalize_weights`), atributos numéricos genéricos en `Resource`/`Task` (saldan la deuda de ADR-006), ocupación compartida en el contexto, reglas **duras** (`MaxDailyLoadPlugin`, `MaxConsecutivePlugin`, `RoomCapacityPlugin`, más `ResourceNoOverlap`/`ForbiddenStarts`) y **blandas** (`PreferEarlySlotsPlugin`, `AvoidSlotsPlugin`). 178 tests: cada regla con caso positivo/negativo/frontera resuelto con OR-Tools real, trade-off de pesos verificado, y las blandas nunca vuelven infactible el horario; cobertura plugins 96%; ADR-012. Pipeline `check.py` en verde.

- **Entregables:** restricciones **duras** del catálogo académico (no-solape docente/grupo/aula, intensidad horaria exacta, disponibilidades, almuerzo docente con duración configurable, bloques dobles/triples consecutivos, máximos diarios/consecutivos/semanales, compatibilidades docente-materia/materia-aula, capacidad, sin huecos de estudiantes dentro del marco, festivos/eventos/bloqueos); restricciones **blandas** vía variables de holgura penalizadas (preferencias mañana/tarde, evitar primeras/últimas horas, huecos docentes, balanceo de carga, distribución semanal, minimizar desplazamientos/cambios de aula-edificio, utilización de aulas); función objetivo unificada con pesos configurables y normalizados.
- **Pruebas de rigor:** una suite por regla con caso positivo (se satisface), negativo (instancia que la fuerza a fallar → INFEASIBLE o penalización) y de frontera; pruebas de trade-off del scoring (subir el peso de un criterio cambia la solución en la dirección esperada); property-based sobre las duras estructurales (ninguna solución emitida viola jamás no-solape).
- **Criterio de salida:** cada regla del catálogo tiene sus tres pruebas y ADR de formulación matemática.

### FASE 9 — Motor, Optimizador y Telemetría  ✅ COMPLETADA (2026-07-14)

> Entregado: `SchedulingEngine` (API pública con solver inyectado como factory — la capa `engine` no importa ortools), `SolutionBuilder` (variables → `Solution` canónica → horario académico), `SolutionInspector` (Informe de Penalizaciones con invariante *suma = objetivo*), **`ValidationEngine`** (re-verifica el horario con código independiente del solver) y `Telemetry` (latencia por etapa + tamaño del modelo antes/después de los pases). 193 tests: end-to-end académico→horario, invariante del informe, y detección del 100% de violaciones sembradas en soluciones corrompidas; cobertura engine+pipeline 99%; ADR-013.

- **Entregables:** API pública del motor (`SchedulingEngine.solve(problem, config) -> Result`); configuración del solver expuesta (`num_search_workers`, `max_time_in_seconds`, `random_seed`); `SolutionInspector` (extrae holguras vía `solver.Assignment()` y genera el Informe de Penalizaciones); `SolutionBuilder` (variables → horario académico); **Validation Engine post-solución** (mejora recuperada: re-verifica toda solución con código independiente del solver); logging estructurado y eventos de progreso.
- **Pruebas de rigor:** integración end-to-end (académico → solución validada); el Validation Engine ejecutado sobre soluciones **corrompidas a propósito** detecta el 100% de las violaciones sembradas; reproducibilidad total con semilla fija; el Informe de Penalizaciones cuadra exactamente con el valor de la función objetivo.
- **Criterio de salida:** demo completa del mini-colegio y de un colegio mediano (30 docentes, 15 grupos) con informe de calidad.

### FASE 10 — Metrics Engine, ReOptimization Engine y Serialización  ✅ COMPLETADA (2026-07-14)

> Entregado: `MetricsEngine` (uso de aulas, huecos intercalados, balance de carga, violaciones duras, `quality_score` 0-100 + comparador), `ReOptimizationEngine` (congelar = un plugin más, `FrozenSchedulePlugin`), `SimulationEngine` (what-if sandbox sin estado) y serialización en tres capas (`codec` ↔ JSON/YAML/`.proschedule` versionado con gzip). 210 tests: KPIs verificados a mano, **invariante de congelado** (lo congelado no se mueve), round-trip property-based, y un `.proschedule` reproduce el mismo horario en ejecución limpia; cobertura engine+serialization 98%; ADR-014.

- **Entregables:** KPIs (uso de aulas %, huecos docentes/estudiantes, balance de carga, cambios de edificio, score global) y comparador de dos horarios; **ReOptimization:** congelar asignaciones (variables fijadas vía hints/igualdades) y reoptimizar solo el subconjunto en conflicto; **Simulation (sandbox):** escenarios what-if con comparación de métricas contra línea base; serialización import/export JSON, YAML y formato propio `.proschedule` (contenedor versionado con schema).
- **Pruebas de rigor:** round-trip de serialización (exportar → importar → modelo idéntico) property-based; compatibilidad de versiones del schema; reoptimización con 90% congelado no altera lo congelado (invariante duro) y mejora o mantiene el score del resto; métricas verificadas contra cálculo manual en instancias pequeñas.
- **Criterio de salida:** un `.proschedule` reproduce el mismo horario en una ejecución limpia.

### FASE 11 — Benchmarks de escala y endurecimiento *(cierre, mejora propuesta)*
- **Entregables:** suite de datasets sintéticos parametrizables (S / M / L / XL hasta el objetivo 500-300-1500); presupuestos de rendimiento (tiempo de compilación del CIR, memoria, tiempo a primera solución factible, gap a los N minutos); perfilado y optimización de cuellos de botella; documentación final de la API pública.
- **Pruebas de rigor:** benchmarks reproducibles con `pytest-benchmark` y registro histórico; prueba de estrés XL con límite de tiempo (debe emitir la mejor solución factible encontrada, nunca colgarse); prueba de memoria acotada en construcción del modelo.
- **Criterio de salida:** el objetivo de escalabilidad de Prompt3 §4 se cumple o queda documentado el gap con plan de acción.

---

## 3. Estrategia transversal de pruebas ("pruebas de rigor")

| Nivel | Herramienta | Qué garantiza |
|---|---|---|
| Estático | `mypy --strict`, `ruff` | Typing estricto (requisito de stack), estilo uniforme |
| Arquitectura | import-linter / test de imports | El dominio jamás importa `ortools`; capas solo dependen hacia abajo |
| Unitario | `pytest` | Invariantes de entidades, DSL, pases del CIR, reglas |
| Property-based | `hypothesis` | Preservación semántica de pases, round-trips (adaptador, serialización), invariantes duros |
| Differential | arnés propio | Pases ON vs OFF ⇒ misma factibilidad y óptimo |
| Oráculos | instancias con óptimo manual | El modelo matemático es correcto, no solo "corre" |
| Metamórfico | arnés propio | Permutaciones de entrada no cambian el óptimo; determinismo por semilla |
| Post-solución | Validation Engine | Nunca confiar solo en el solver: toda solución se re-verifica |
| Inviabilidad | catálogo de instancias inviables | Conflict Explanation siempre produce explicación accionable |
| Rendimiento | `pytest-benchmark` + datasets S–XL | Presupuestos de tiempo/memoria; regresiones detectadas |

**Regla operativa:** ninguna fase se cierra sin (1) sus pruebas en verde, (2) cobertura ≥ 90% en el módulo de la fase, (3) sus ADRs escritos, (4) el checkpoint de contexto actualizado.

## 4. Mejoras y optimizaciones propuestas sobre Prompt3 (resumen)

1. **Fase 0 de fundaciones** — sin ella, "typing estricto" y "no código sin pruebas" no son verificables.
2. **Reincorporar el Validation Engine post-solución** (estaba en contextobase, ausente en Prompt3).
3. **Reincorporar estrategia formal de testing/benchmarks** como pilar transversal con técnicas específicas para software de optimización (property-based, differential, metamórfico, oráculos).
4. **Concretar la serialización** (JSON/YAML/`.proschedule` versionado con schema).
5. **CIR serializable a texto** — habilita snapshot tests, debugging y auditoría de los optimizer passes.
6. **Fase 11 de benchmarks de escala** para validar explícitamente el objetivo 500/300/1500.
7. **ADRs como archivos versionados** en `docs/adr/` (además del bloque `[[ADR]]` por turno), tal como recomendaba contextobase.

## 5. Mecánica de trabajo (guardrails de Prompt3 §6)

- Una fase por vez; prohibido generar múltiples módulos de golpe.
- Arquitectura justificada **antes** del código (por qué, ventajas, desventajas, impacto en rendimiento/mantenibilidad/escalabilidad).
- Cada turno de trabajo termina con `[[ADR]]`, `[[Context Checkpoint]]` (YAML) y `[[Pausa para Validación]]`.
- No se avanza de fase sin aprobación explícita del usuario.
