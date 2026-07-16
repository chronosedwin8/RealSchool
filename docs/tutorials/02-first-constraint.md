# Tutorial 2 — Tu primera restricción

Vamos a escribir un plugin blando que prefiere las primeras horas del día, lo
probaremos y lo activaremos. (Concepto completo en
[Restricciones y Tiers](../architecture/scoring_tiers.md).)

## La idea

Un plugin lee el contexto del modelo y devuelve una `Contribution`. Para preferir
las primeras horas, penalizamos cada clase por lo tarde que empieza:

```{.python notest}
@dataclass(frozen=True, slots=True)
class PreferEarly(SchedulingPlugin):
    name = "prefer_early_demo"
    weight: int = 1

    def contribute(self, context):
        expr = LinearExpr.of(0)
        for task in context.problem.tasks:
            tid = int(task.id)
            for slot in context.valid_starts(tid):
                if slot:  # el período 0 no penaliza; cuanto más tarde, más coste
                    expr = expr + slot * context.start_var(tid, slot)
        if not expr.coeffs:
            return Contribution()
        return Contribution(
            penalties=(PenaltyTerm(expr, self.weight, "prefer_early_demo", tier=3),)
        )
```

- El `tier=3` lo marca como **preferencial** (la prioridad más baja).
- Como razona período a período, el contexto usa `boolean_starts=True`.
- Para activarlo, se registra junto al no-solape estructural:

```{.python notest}
registry = registry_with([IntervalNoOverlapPlugin(), PreferEarly(weight=5)])
```

## Todo junto (ejecutable)

Este bloque define el plugin, lo prueba sobre un problema mínimo y lo registra:

```python
from dataclasses import dataclass

from scheduling_platform.plugins import (
    SchedulingPlugin, Contribution, PenaltyTerm, SchedulingModelContext, registry_with,
)
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.dsl.expressions import LinearExpr
from scheduling_platform.core import (
    SchedulingProblem, TimeGrid, Resource, ResourceId, Task, TaskId, ResourceRequirement,
)


@dataclass(frozen=True, slots=True)
class PreferEarly(SchedulingPlugin):
    name = "prefer_early_demo"
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        expr = LinearExpr.of(0)
        for task in context.problem.tasks:
            tid = int(task.id)
            for slot in context.valid_starts(tid):
                if slot:
                    expr = expr + slot * context.start_var(tid, slot)
        if not expr.coeffs:
            return Contribution()
        return Contribution(
            penalties=(PenaltyTerm(expr, self.weight, "prefer_early_demo", tier=3),)
        )


problem = SchedulingProblem(
    grid=TimeGrid.from_segment_lengths([4]),
    resources=(
        Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
        Resource(ResourceId(1), "Aula", frozenset({"room"})),
    ),
    tasks=(
        Task(TaskId(0), "Mate", 1,
             (ResourceRequirement("teacher#0"), ResourceRequirement("room"))),
    ),
)

context = SchedulingModelContext.build(problem, boolean_starts=True)
contribution = PreferEarly(weight=5).contribute(context)
assert contribution.penalties[0].label == "prefer_early_demo"
assert contribution.penalties[0].tier == 3

registry = registry_with([IntervalNoOverlapPlugin(), PreferEarly(weight=5)])
assert "prefer_early_demo" in registry.names()
```

Todo plugin debe además cumplir el **contrato del SDK** (determinista, DSL puro):
`assert_plugin_contract(...)` (ver [Guía: restricciones](../sdk_guide/constraints.md)).

**Siguiente:** [tu primer importador](03-first-importer.md).
