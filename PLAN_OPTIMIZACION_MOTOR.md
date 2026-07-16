# PLAN DE OPTIMIZACIÓN DEL MOTOR (v2)
## Catálogo canónico de restricciones, Scoring por Tiers, benchmarking científico y optimización dirigida — antes de la interfaz desktop

**Fecha:** 2026-07-15 · **Repo:** `github.com/chronosedwin8/RealSchool` (base `c2773e8`, 244 tests verdes)
**Guardar en el repo como `PLAN_OPTIMIZACION_MOTOR.md` (Paso 0) para referencia posterior.**

---

## Contexto

El motor está funcionalmente completo (Fases 0–11 + importador Untis real + warm start que repara 4 años reales + primer objetivo de calidad que ya supera a Untis en estabilidad de aula, −19/−28%). Antes de la interfaz desktop, se endurece y optimiza el motor con las Actividades 2–12: catálogo formal de restricciones sobre el Modelo Canónico, Scoring Engine jerarquizado por Tiers, telemetría completa, benchmarking estadístico con registro automático, multi-solver, escalabilidad 20→500, dashboard, gate de regresiones y comparación ampliada con Untis.

**Decisiones ya acordadas con el usuario:**
- **Dashboard:** HTML estático autocontenido desde los JSON (cero infraestructura). PostgreSQL 18 queda **diferido** — el esquema del registro se diseña "PG-ready" (JSONB-compatible) para migrar sin cambios cuando haya multi-máquina.
- **Presupuesto:** suite dual — **RÁPIDA** (~15-20 min, gate de cada cambio) y **COMPLETA** (2-4 h, bajo demanda/nocturna).
- **Solvers (verificado en el entorno):** CBC, SCIP y HiGHS ya vienen en el OR-Tools instalado (`pywraplp`) — cero dependencias nuevas. **Gurobi no disponible** (sin licencia): detectado dinámicamente, funcionará sin código nuevo si aparece.

---

## LO QUE YA ESTÁ HECHO — excluido del plan (imperativo 1)

No se re-implementa nada de esto; el catálogo (O1) solo lo **referencia**:

| Pedido en las actividades | Ya existe como |
|---|---|
| HC-01/02/03 exclusividad persona/grupo/aula | `IntervalNoOverlapPlugin` (+ variante booleana `ResourceNoOverlapPlugin`) sobre recursos unarios |
| HC-04 capacidad volumétrica | `RoomCapacityPlugin` (size ≤ seats vía atributos) |
| HC-05 disponibilidad estricta | Estructural: `allowed_starts` (el adaptador intersecta disponibilidades) |
| HC-06 simultaneidad de clases combinadas | **Por construcción**: un acople (Kopplung) = UNA tarea canónica con N profesores/cursos/aulas — no necesita plugin |
| HC-07 equipamiento/especialidad de aula | Matching por tags (`roomtype#lab`, `equip#X`) del adaptador académico |
| SC-01 preferencia temporal | `PreferEarlySlotsPlugin` / `AvoidSlotsPlugin` |
| SC-03 evitar franjas extremas | `AvoidSlotsPlugin` parametrizado |
| SC-06 estabilidad geográfica (docente) | `TeacherRoomStabilityPlugin` (validado: −19/−28% vs Untis) |
| Telemetría por etapa (t_adaptation, t_cir, t_build, t_search) | `pipeline/telemetry.py` |
| RAM pico, JSON por corrida | `benchmarks/runner.py` (tracemalloc + `to_dict`) |
| Datasets sintéticos factibles S/M/L/XL | `benchmarks/datasets.py` (`DatasetSpec` + presets) |
| Conflictos duros / blandas violadas / score | `ValidationEngine` + `SolutionInspector` (invariante suma=objetivo) + `MetricsEngine` |
| Warm start + comparación Untis base | `sal.add_hint`, `warm_start_years.py`, `warm_start_quality.py`, importador `untis/` |
| Normalización básica de pesos | `plugins/scoring.py::normalize_weights` |

## MEJORAS ADOPTADAS sobre la propuesta (imperativo 2)

1. **Sin Docker**: host Windows sin Docker; el aislamiento se logra con corridas de calentamiento (descartadas), semilla fija, workers fijos y proceso en prioridad alta. Docker queda documentado como opcional futuro. *(Menos infraestructura, misma validez con IC95 + percentiles.)*
2. **Sin Pydantic**: el proyecto ya tiene un patrón de dataclasses congeladas + codec versionado (`serialization/`); el registro de benchmarks usa el mismo patrón. *(Cero dependencias redundantes, consistencia interna.)*
3. **CI dividido por naturaleza del check**: GitHub Actions ejecuta lo **determinista** (tests, `hard_violations == 0`, score/conflictos con semilla fija); los umbrales de **tiempo y RAM** se validan en el gate **local** — en runners compartidos un umbral de +5% de P50 daría falsos positivos constantes. *(La regla de la Actividad 8 se conserva, aplicada donde es fiable.)*
4. **Sin subtipos PERSON/LOCATION/GROUP en el core**: los tags existentes (`teacher`, `room`, `group`) ya son esa clasificación; el catálogo los mapea sin tocar el Modelo Canónico. *(Core intacto, misma semántica.)*
5. **Comparación del vector de holguras** en el gate (Actividad 11): además de los umbrales agregados, se compara el desglose de penalizaciones por etiqueta para detectar re-balanceos ocultos (un plugin nuevo que mejora huecos pero dispara cambios de aula → falla y exige recalibrar Tiers).
6. **Informe Markdown auto-generado** por benchmark (Actividad 12); PDF descartado (dependencia extra sin valor añadido; el MD es versionable y auditable).

---

## Paso 0 — Persistir el plan
Copiar este plan a `PLAN_OPTIMIZACION_MOTOR.md` en la raíz del repo y enlazarlo desde `PLAN_DE_TRABAJO.md`. Commit propio.

---

## FASE O1 — Catálogo canónico de restricciones + plugins faltantes *(Actividad 2)*

**Nuevo** `src/scheduling_platform/plugins/constraint_catalog.py`:
- `ConstraintDefinition(id, name, description, kind: HARD|SOFT|STRUCTURAL, tier, default_weight, plugin_factory | nota)` — peso ∞ representado como `kind=HARD` (sin peso).
- `CONSTRAINT_CATALOG` con **todas** las entradas HC-01..HC-07 y SC-01..SC-08 del metamodelo del usuario, cada una apuntando a su implementación existente (tabla de arriba) o al plugin nuevo.
- `registry_from_catalog(ids_activos, pesos_override, tiers_override)` → `PluginRegistry`.
- `scripts/catalog.py`: imprime el catálogo como tabla (documentación viva).

**Plugins NUEVOS** (los únicos que faltan; en `plugins/catalog/`):
- **SC-02 `TeacherGapsPlugin`** — huecos intermedios del día por docente. Hueco = tramo libre ≥ umbral (param., default 30 min: filtra recreos de 10-25 min en datos Untis). Requiere ocupación por período (`boolean_starts=True` o reificación sobre `tstart`); evaluar coste con telemetría y documentar el modo recomendado.
- **SC-04 `TaskContinuityPlugin`** — penaliza fragmentación: sesiones del mismo acople en el mismo día no adyacentes (reificación de adyacencia sobre `tstart` + indicador de día).
- **SC-05 `WeeklyBalancePlugin`** — indicador de día por sesión vía channeling lineal (`0 ≤ tstart − L·day ≤ L−1`, `day ∈ EnumDomain`) y penalización por pares del mismo acople en el mismo día (aproximación lineal de la varianza).
- **SC-07 `DailySpanPlugin`** (blanda) — penaliza `último − primero > umbral` por docente/día (variables min/max de día con reificación).
- **SC-08 `SoftMaxConsecutivePlugin`** (blanda) — versión penalizada del `MaxConsecutivePlugin` duro existente (misma maquinaria de ocupación, holgura en vez de prohibición).
- *(Opcional barato)* `GroupRoomStabilityPlugin` — clon del de docentes para grupos (SC-06 versión GROUP).

**Tests:** completitud del catálogo (todo plugin tiene entrada y viceversa), y cada plugin nuevo con caso positivo/negativo/frontera resuelto con OR-Tools (patrón de `tests/test_rule_engine.py`/`test_quality.py`) + contrato del SDK. **ADR-019.**

## FASE O2 — Scoring Engine v2: Tiers + normalización por máximo teórico *(Actividad 2.3.C)*

- `PenaltyTerm` gana `tier: int` (1=vital ×10⁴, 2=operativa ×10², 3=preferencial ×10⁰) y `theoretical_max: int | None`.
- `ScoringEngine.build_objective`: `min Σ_j E_j · Σ_k W_k · s̄_k`. **Nota de implementación entera** (CP-SAT no admite fracciones): la normalización `s_k/s_max` se implementa como `coef = round(W_k · E_j · SCALE / s_max)` con `SCALE=1000`, garantizando coeficiente ≥ 1 — documentar el error de redondeo aceptado.
- Cada plugin blando calcula su `theoretical_max` (p. ej. huecos: períodos/día − 1 por docente·día).
- El Informe de Penalizaciones (`SolutionInspector`) muestra el desglose por Tier y por regla; el invariante *suma = objetivo* se mantiene y se re-verifica.
- **Tests:** una violación Tier-1 pesa más que TODAS las Tier-3 posibles juntas (test de dominancia lexicográfica); estabilidad numérica con miles de términos; retro-compatibilidad (pesos sin tier = Tier 3). **ADR-020.**

## FASE O3 — Telemetría completa *(Actividad 3)*

- `pipeline/telemetry.py`: añadir `t_export_ms`; desglose **binarias / enteras / intervalos / continuas** (=0 en CP-SAT, el campo se registra igual) contado en `cir/compiler.py`; `threads` desde `SolverConfig`.
- `ISolver.get_stats() -> dict` (default `{}`): `ORToolsSolver` expone `NumBranches`, `NumConflicts`, `WallTime` del response de CP-SAT. Extensión mínima de la SAL.
- **Nuevo** `benchmarks/resource_monitor.py`: hilo de muestreo con **psutil** (única dependencia nueva) → RAM pico/promedio, CPU promedio/máx durante la resolución (tracemalloc se mantiene como métrica secundaria).
- `BenchmarkRun`: ratios tiempo/docente, /grupo, /clase, /variable + `t_export_ms` (medir `save_proschedule`).
- **Tests:** valores sanos del monitor; desglose de variables contra `FakeSolver` en modelo conocido.

## FASE O4 — Benchmarking estadístico + registro automático + trazabilidad *(Actividades 4, 5, 12)*

- **Nuevo** `benchmarks/stats.py`: protocolo = `warmup` corridas descartadas (2 rápida / 5 completa) + N medidas → media, mediana, desv. estándar, mín, máx, **P50/P95/P99**, **IC 95%** (t de Student). N escalonado: 20 (S/M), 10 (DS-04 real), 5 (L), 3 (XL); 30 en suite completa para S/M.
- **Nuevo** `benchmarks/record.py`: `BenchmarkRecord` (dataclass congelada + codec, patrón `serialization/`) con el esquema de la Actividad 5 **más** Actividad 12: `git_commit`, `pip_freeze` (ortools/psutil/pyyaml versions), hardware (CPU, núcleos, RAM GB, SO vía platform/psutil), config solver (backend, workers, seed, límite), dataset, timestamp ISO, agregados, corridas crudas, `observaciones`. Escrito **automáticamente** a `benchmarks/results/<ts>-<dataset>-<solver>.json` + **informe Markdown** gemelo auto-generado. Esquema PG-ready (documentado).
- **Nuevo** `scripts/bench.py` (CLI única): `bench quick` (S+M+DS-04, ~15-20 min) · `bench full` (todo + escalera + solvers) · `bench run <dataset> [--solver --reps]` · `bench compare <A> <B>`.
- **Tests:** estadísticas contra valores a mano; record completo; round-trip. **ADR-021** (protocolo de medición).

## FASE O5 — Multi-solver vía SAL *(Actividad 7)*

- **Nuevo** `sal/mip_solver.py`: `MipSolver(backend: CBC|SCIP|HIGHS|GUROBI)` implementando `ISolver` sobre `ortools.linear_solver.pywraplp` (segunda ubicación autorizada a importar ortools; actualizar `tests/test_architecture.py` a "solo `sal/`").
  - Sin intervalos nativos → los benchmarks MIP usan la **formulación booleana existente**; `new_interval`/`add_no_overlap` lanzan error explícito.
  - `add_hint` → `SetHint` donde exista; degradación con aviso. Gurobi por detección dinámica.
- **Tests:** contrato ISolver (parte lineal) + oráculos por backend + differential CP-SAT vs cada MIP (mismo óptimo en instancias pequeñas).
- `bench solvers <dataset>` sobre DS-01 y DS-04 → tiempo, calidad, RAM, score. **Entregable:** informe "qué solver por topología" (la evidencia, gane quien gane). **ADR-022.**

## FASE O6 — Escalabilidad y complejidad observada *(Actividad 9)*

- Escalera en `benchmarks/datasets.py`: 20, 40, 60, 80, 100, 150, 200, 250, 300, 400, 500 docentes (derivación proporcional del preset, factible por construcción).
- **Nuevo** `benchmarks/complexity.py`: regresión log-log de `t_total` **y de cada etapa** vs docentes/clases/variables → exponente observado, clasificación lineal/cuadrática/exponencial, y **qué etapa escala peor**. Gráfica NumBooleans vs tiempo.
- Mitigación si hay explosión (del doc del usuario): `AddDecisionStrategy` guiando la búsqueda + límites de seguridad — se expone en `SolverConfig` como estrategia opcional y se mide su efecto.
- `bench ladder`. **Criterio:** ninguna etapa propia (todo menos la búsqueda) peor que ~O(n·log n).

## FASE O7 — Dashboard HTML estático *(Actividad 6)*

- **Nuevo** `scripts/dashboard.py`: lee `benchmarks/results/*.json` → `benchmarks/dashboard.html` autocontenido (canvas inline, sin CDNs, tema claro/oscuro): líneas (tiempo/score por commit), barras (solvers), **boxplots** (dispersión entre repeticiones), histogramas, **heatmap** dataset×solver, tabla de corridas con commit y hardware. Publicable como artifact.
- **Tests:** genera HTML válido desde fixtures; tolera resultados parciales.

## FASE O8 — Gate de regresiones + CI *(Actividades 8 y 11)*

- **Nuevo** `scripts/regression_gate.py` (local): ejecuta `bench quick`, compara contra `benchmarks/baselines/<dataset>.json` y **falla** si: P50 `t_total` +5% · `ram_peak` +10% · `score` baja · conflictos suben · **el vector de holguras por etiqueta se re-balancea** (una regla empeora >50% aunque el total mejore). Informe de diferencias en `benchmarks/regression_report.md`. `--update-baseline "justificación"` deja la justificación registrada.
- **Nuevo** `.github/workflows/ci.yml`: en cada push/PR ejecuta `check.py` + los checks **deterministas** del gate (tests, `hard_violations == 0`, score/conflictos con semilla fija). Los umbrales de tiempo/RAM quedan en el gate local (runners compartidos = ruido).
- **Tests:** con fixtures detecta cada tipo de regresión y respeta umbrales.

## FASE O9 — Comparación con Untis ampliada *(Actividad 10)*

- `engine/metrics.py`: **distribución de huecos** (histograma y varianza por docente, umbral ≥30 min), huecos promedio/máx por docente; balance y utilización ya existen.
- `ORToolsSolver`: callback opcional para registrar **tiempo a primera solución factible** (métrica pedida) — se añade a `Telemetry`.
- **Nuevo** `scripts/gap_analysis.py`: consolida los 4 años reales — Untis vs motor (flujo dos-fases de `warm_start_quality.py`, + fase de huecos si SC-02 resulta tratable a tamaño real) en TODAS las métricas de la actividad → JSON + sección del dashboard + artifact.
- El "Adapter de exportación a Untis" del doc original queda **fuera de alcance** (ya importamos SUS datos reales y comparamos sobre la misma vara; exportar hacia Untis solo serviría para re-ejecutar Untis, que ya tenemos ejecutado en los 4 XML).

## FASE O10 — Optimización dirigida por evidencia *(cierre)*

- Perfilar (cProfile) las etapas señaladas por O6; corregir los 2-3 peores cuellos (candidatos: restricciones estructurales en `plugins/context.py`, dedup CIR en modelos gigantes, extracción de solución).
- Cada optimización: `bench quick` antes/después + gate verde + dashboard. **ADR-023** con tabla antes/después.

**Criterios de salida hacia la interfaz desktop:**
1. Gate local y CI operativos y en verde.
2. Escalera 20→500 documentada; ninguna etapa propia super-lineal sin justificar.
3. DS-04 real (reparar + pulir) < 2 min extremo a extremo.
4. Dashboard con ≥2 versiones comparadas.
5. Informe multi-solver + gap analysis Untis completos (todas las métricas de la Actividad 10).
6. Catálogo completo HC-01..HC-07 / SC-01..SC-08 con Tiers operativos.
7. ADRs 019–023 escritos.

---

## Orden y dependencias

```
Paso 0 → O1 (catálogo+plugins) → O2 (Tiers) → O3 (telemetría) → O4 (stats+registro)
       → O5 (multi-solver) y O6 (escalera)   [ambas necesitan O4]
       → O7 (dashboard)                       [necesita datos de O4–O6]
       → O8 (gate+CI)                         [necesita baselines de O4]
       → O9 (Untis ampliado)                  [necesita O1 (umbral huecos) + O3]
       → O10 (optimización)                   [necesita O6 (cuellos) + O8 (protección)]
```

Cada fase cierra como siempre: `scripts/check.py` verde, cobertura ≥90% en lo nuevo, ADR, commit + push.

## Verificación end-to-end

1. `python scripts/check.py` → 244 tests actuales + nuevos, verde.
2. `python scripts/catalog.py` → tabla HC-01..SC-08 completa con Tiers.
3. `python scripts/bench.py quick` → records JSON + informes MD con IC95 y percentiles.
4. `python scripts/bench.py solvers small` → CP-SAT vs CBC vs SCIP vs HiGHS.
5. `python scripts/bench.py ladder` (reducida 20→100 para verificar) → exponente observado.
6. `python scripts/dashboard.py` → dashboard.html con todas las gráficas.
7. `python scripts/regression_gate.py` → PASS; con regresión artificial (sleep) → FAIL.
8. `python scripts/gap_analysis.py` → informe 4 años con todas las métricas de la Actividad 10.
9. Test de dominancia de Tiers: una violación Tier-1 > todas las Tier-3 juntas.

## Dependencias nuevas
- `psutil` (CPU/RAM). Única adición — CBC/SCIP/HiGHS ya vienen en el OR-Tools instalado (verificado en este entorno).
