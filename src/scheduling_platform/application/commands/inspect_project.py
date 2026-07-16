"""Casos de uso de inspección: ``validate`` y ``explain``.

``validate`` resume el proyecto si es factible (aforo, huecos, score) y falla con
la explicación si es inviable. ``explain`` siempre devuelve el mapa de conflictos
estructurales (vacío si es factible), útil para que una GUI lo pinte.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ...engine import MetricsEngine
from ..context import AppContext
from ..errors import InfeasibleError
from ..project import open_project
from ..runtime import analyze_feasibility
from .base import Command, CommandResult

_METRICS = MetricsEngine()


class ValidateCommand(Command):
    """Valida el proyecto: resumen si es factible, explicación si no."""

    name: ClassVar[str] = "validate"

    def __init__(self, project_path: str, *, strict: bool = False) -> None:
        self._path = project_path
        self._strict = strict

    def execute(self, ctx: AppContext) -> CommandResult:
        project = open_project(self._path)
        report = analyze_feasibility(project.problem)
        if not report.feasible:
            raise InfeasibleError(report.render())

        payload: dict[str, Any] = {"feasible": True, "has_solution": project.solution is not None}
        messages = ["el proyecto es estructuralmente factible"]
        if project.solution is not None:
            metrics = _METRICS.compute(project.problem, project.solution)
            payload["metrics"] = {
                "room_utilization_pct": round(metrics.room_utilization_pct, 2),
                "teacher_gaps": metrics.teacher_gaps,
                "teacher_load_balance_pct": round(metrics.teacher_load_balance_pct, 2),
                "quality_score": round(metrics.quality_score, 2),
                "hard_violations": metrics.hard_violations,
            }
            if self._strict and metrics.hard_violations > 0:
                raise InfeasibleError(
                    f"validación estricta: {metrics.hard_violations} violaciones duras"
                )
        return CommandResult(payload=payload, messages=tuple(messages))


class ExplainCommand(Command):
    """Devuelve el mapa de conflictos estructurales (Explain Engine)."""

    name: ClassVar[str] = "explain"

    def __init__(self, project_path: str) -> None:
        self._path = project_path

    def execute(self, ctx: AppContext) -> CommandResult:
        project = open_project(self._path)
        report = analyze_feasibility(project.problem)
        if report.feasible:
            return CommandResult(
                payload={"feasible": True, "issues": []},
                messages=("sin conflictos estructurales",),
            )
        issues = [
            {"kind": issue.kind, "message": issue.message, "entities": list(issue.entities)}
            for issue in report.issues
        ]
        return CommandResult(
            exit_code=InfeasibleError.exit_code,
            payload={"feasible": False, "issues": issues},
            messages=("horario INFEASIBLE; ver el detalle de conflictos",),
        )
