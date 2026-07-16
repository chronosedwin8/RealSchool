"""Casos de uso de resolución: ``generate`` (factible rápido) y ``optimize``.

Ambos abren el ``.schedule``, resuelven con el motor (config del proyecto) y
persisten el horario en el proyecto de forma atómica. ``generate`` busca una
primera solución factible (solo estructura); ``optimize`` aplica todas las reglas
blandas configuradas y permite elegir el backend.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, ClassVar

from ...core.problem import SchedulingProblem
from ...engine import EngineResult, MetricsEngine
from ..context import AppContext
from ..project import open_project, save_project
from ..runtime import (
    build_registry,
    engine_config_of,
    plugins_config_of,
    run_engine,
)
from ..solvers import solver_factory_for
from .base import Command, CommandResult

_METRICS = MetricsEngine()


def solution_summary(problem: SchedulingProblem, result: EngineResult) -> dict[str, Any]:
    """Resumen legible del horario obtenido (para stdout)."""
    assert result.solution is not None
    metrics = _METRICS.compute(problem, result.solution)
    return {
        "status": result.status.value if result.status else "?",
        "objective_value": result.solution.objective_value,
        "quality_score": round(metrics.quality_score, 2),
        "room_utilization_pct": round(metrics.room_utilization_pct, 2),
        "teacher_gaps": metrics.teacher_gaps,
        "hard_violations": metrics.hard_violations,
    }


class GenerateCommand(Command):
    """Genera una primera solución factible (solo estructura) y la guarda."""

    name: ClassVar[str] = "generate"

    def __init__(self, project_path: str, *, quick: bool = False, timeout: float | None = None):
        self._path = project_path
        self._quick = quick
        self._timeout = timeout

    def execute(self, ctx: AppContext) -> CommandResult:
        project = open_project(self._path)
        registry, boolean = build_registry(plugins_config_of(project), structural_only=True)
        solver_config = engine_config_of(project).to_solver_config()
        if self._timeout is not None:
            solver_config = replace(solver_config, max_time_in_seconds=self._timeout)
        elif self._quick:
            cap = min(solver_config.max_time_in_seconds or 60.0, 60.0)
            solver_config = replace(solver_config, max_time_in_seconds=cap)

        result = run_engine(
            project.problem,
            registry,
            solver_factory=ctx.solver_factory,
            solver_config=solver_config,
            boolean_starts=boolean,
            on_event=ctx.emit_progress,
        )
        save_project(self._path, replace(project, solution=result.solution))
        return CommandResult(
            payload=solution_summary(project.problem, result),
            messages=("horario generado y guardado",),
        )


class OptimizeCommand(Command):
    """Optimiza el horario con las reglas blandas configuradas y lo guarda."""

    name: ClassVar[str] = "optimize"

    def __init__(
        self,
        project_path: str,
        *,
        solver: str | None = None,
        seed: int | None = None,
        timeout: float | None = None,
    ):
        self._path = project_path
        self._solver = solver
        self._seed = seed
        self._timeout = timeout

    def execute(self, ctx: AppContext) -> CommandResult:
        project = open_project(self._path)
        plugins_cfg = plugins_config_of(project)
        engine_cfg = engine_config_of(project)
        solver_name = self._solver or engine_cfg.default_solver
        factory = solver_factory_for(solver_name)
        registry, boolean = build_registry(plugins_cfg, mip=solver_name != "ortools_cpsat")

        solver_config = engine_cfg.to_solver_config()
        if self._seed is not None:
            solver_config = replace(solver_config, random_seed=self._seed)
        if self._timeout is not None:
            solver_config = replace(solver_config, max_time_in_seconds=self._timeout)

        result = run_engine(
            project.problem,
            registry,
            solver_factory=factory,
            solver_config=solver_config,
            boolean_starts=boolean,
            on_event=ctx.emit_progress,
        )
        payload = solution_summary(project.problem, result)
        payload["solver"] = solver_name
        # persiste el horario + métricas + anexa al historial (metrics.json / history.json)
        run_record = {"timestamp": datetime.now(UTC).isoformat(timespec="seconds"), **payload}
        save_project(
            self._path,
            replace(
                project,
                solution=result.solution,
                metrics=payload,
                history=(*project.history, run_record),
            ),
        )
        return CommandResult(payload=payload, messages=(f"optimizado con {solver_name}",))
