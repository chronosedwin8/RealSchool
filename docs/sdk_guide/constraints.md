# Crear restricciones (HARD y SOFT)

Una restricción es un **plugin**: un objeto que lee el contexto del modelo y
devuelve una `Contribution` con restricciones duras (DSL) y/o penalizaciones
blandas (`PenaltyTerm`). Nunca toca el solver.

## La interfaz

```python
from scheduling_platform.plugins import (
    SchedulingPlugin, Contribution, PenaltyTerm, SchedulingModelContext,
)

class SchedulingPlugin(ABC):
    name: ClassVar[str]
    def contribute(self, context: SchedulingModelContext) -> Contribution: ...
```

- **`context`** expone el vocabulario de variables: `assign_var(task, resource)`,
  `start_var(task, slot)`, `task_start_var(task)`, `occupancy(...)`, los inicios
  válidos y el índice recurso→tareas.
- **`Contribution(constraints=..., penalties=...)`** es lo que devuelves.

## Una regla DURA

Emite `DslConstraint` (p. ej. `LinearConstraint`). El solver **debe** cumplirla.

```python
from scheduling_platform.dsl.logic import LinearConstraint
from scheduling_platform.dsl.expressions import LinearExpr

class MaxTwoRoomsPlugin(SchedulingPlugin):
    name = "max_two_rooms"
    def contribute(self, context):
        constraints = []
        # ejemplo: a lo sumo 2 aulas activas por algún criterio...
        # constraints.append(LinearConstraint(expr <= 2))
        return Contribution(constraints=tuple(constraints))
```

## Una regla BLANDA (con holgura y Tier)

Devuelve un `PenaltyTerm(expr, weight, label, tier=..., theoretical_max=...)`. El
`ScoringEngine` minimiza la suma ponderada. El **Tier** decide su prioridad
lexicográfica (ver [Restricciones y Tiers](../architecture/scoring_tiers.md)).

```python
class PreferEarlyPlugin(SchedulingPlugin):
    name = "prefer_early"
    weight: int = 1
    def contribute(self, context):
        expr = LinearExpr.of(0)
        for task in context.problem.tasks:
            tid = int(task.id)
            for slot in context.valid_starts(tid):
                offset = slot  # cuanto más tarde, más penalización
                if offset:
                    expr = expr + offset * context.start_var(tid, slot)
        if not expr.coeffs:
            return Contribution()
        return Contribution(
            penalties=(PenaltyTerm(expr, self.weight, "prefer_early", tier=3),)
        )
```

!!! warning "Variables por período"
    Si tu regla razona período a período (huecos, continuidad, carga diaria),
    necesita las booleanas de inicio: usa `boolean_starts=True` al construir el
    contexto/motor. Las reglas basadas solo en `assign` (p. ej. estabilidad de
    aula) funcionan en el modo compacto.

## Registrar el plugin

```python
from scheduling_platform.plugins import registry_with
registry = registry_with([PreferEarlyPlugin(weight=5)])
```

Desde configuración (`plugins.yaml` / `.bjs`), si tu plugin está en el
**catálogo canónico** (`constraint_catalog.py`), se activa por su `id` con
`registry_from_catalog([...], weight_overrides=..., ...)`.

## Probarlo (contrato del SDK)

Todo plugin debe cumplir el contrato: determinista, DSL puro, sin tocar el solver.

```python
from tests.plugin_contract import assert_plugin_contract
context = SchedulingModelContext.build(problem, boolean_starts=True)
assert_plugin_contract(PreferEarlyPlugin(weight=2), context)
```

Y una prueba de comportamiento con OR-Tools real: monta un problema mínimo donde
la regla deba activarse y verifica el `objective_value` (patrón en
`tests/test_daily_quality.py`).

## Depurarlo

- El **Informe de Penalizaciones** (`Solution.penalties`) desglosa cuánto aportó
  cada `label`; la suma coincide con el objetivo.
- Si el modelo sale `INFEASIBLE`, tu regla dura entra en conflicto: el
  `ConflictReport` lo explica.
- Referencia completa: [API — plugins](../reference/plugins.md).
