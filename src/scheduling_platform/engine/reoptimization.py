"""ReOptimization Engine: congelar el horario y reoptimizar solo un subconjunto.

En vez de recalcular todo el modelo, se congelan las clases que no se quieren
tocar (se fijan sus variables) y se deja libre únicamente el subconjunto en
conflicto. Se implementa reutilizando el pipeline completo: el congelado es un
plugin más (:class:`FrozenSchedulePlugin`), así que no hay un "segundo motor"
que mantener.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..core.ids import TaskId
from ..core.problem import SchedulingProblem
from ..core.solution import Solution
from ..plugins.base import SchedulingPlugin
from ..plugins.catalog.reoptimization import FrozenClass, FrozenSchedulePlugin
from ..plugins.registry import registry_with
from ..sal.interface import SolverConfig
from .engine import EngineResult, SchedulingEngine, SolverFactory


def freeze_all_except(solution: Solution, unfrozen: Iterable[TaskId]) -> tuple[FrozenClass, ...]:
    """Congela todas las clases de la solución salvo las indicadas."""
    libres = {int(tid) for tid in unfrozen}
    return tuple(
        FrozenClass(
            task_id=int(a.task_id),
            start=int(a.start),
            resource_ids=tuple(int(r) for r in a.resource_ids),
        )
        for a in solution.assignments
        if int(a.task_id) not in libres
    )


@dataclass(frozen=True, slots=True)
class ReOptimizationEngine:
    """Reoptimiza un subconjunto del horario manteniendo el resto intacto."""

    plugins: Sequence[SchedulingPlugin]
    solver_factory: SolverFactory
    metadata: dict[str, str] = field(default_factory=dict)

    def reoptimize(
        self,
        problem: SchedulingProblem,
        baseline: Solution,
        unfrozen: Iterable[TaskId],
        config: SolverConfig | None = None,
    ) -> EngineResult:
        """Vuelve a resolver dejando libres solo las tareas de ``unfrozen``."""
        frozen = freeze_all_except(baseline, unfrozen)
        registry = registry_with([*self.plugins, FrozenSchedulePlugin(frozen=frozen)])
        engine = SchedulingEngine(registry=registry, solver_factory=self.solver_factory)
        return engine.solve(problem, config)
