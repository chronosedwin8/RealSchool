"""Validation Engine: nunca confiar únicamente en el solver.

Re-verifica una solución ya construida contra el problema, con código
completamente independiente del modelo matemático: no mira variables ni
restricciones del solver, solo el horario resultante. Si el modelo tuviera un
error de formulación, este motor lo delataría.

Comprueba:
1. **Integridad estructural**: cobertura exacta de tareas, inicios válidos y
   recursos existentes (delegado en ``Solution.validate_against``).
2. **Requerimientos satisfechos**: cada tarea usa exactamente la cantidad de
   recursos pedida por cada uno de sus requerimientos (por tag).
3. **Capacidad de los recursos**: ningún recurso aloja más tareas simultáneas
   que su capacidad (no-solape para los unarios).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..core.exceptions import DomainError
from ..core.ids import ResourceId
from ..core.problem import SchedulingProblem
from ..core.solution import Solution


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Una violación detectada en la solución ya construida."""

    kind: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Resultado de la re-verificación independiente."""

    valid: bool
    issues: tuple[ValidationIssue, ...] = ()

    def render(self) -> str:
        if self.valid:
            return "La solución supera todas las validaciones independientes."
        lines = ["La solución viola restricciones (el solver no es de fiar por sí solo):"]
        lines.extend(f"- [{issue.kind}] {issue.message}" for issue in self.issues)
        return "\n".join(lines)


class ValidationEngine:
    """Verifica una solución contra el problema, sin usar el solver."""

    def validate(self, problem: SchedulingProblem, solution: Solution) -> ValidationReport:
        issues: list[ValidationIssue] = []
        self._check_structure(problem, solution, issues)
        if not issues:
            # Las comprobaciones siguientes asumen una solución bien formada.
            self._check_requirements(problem, solution, issues)
            self._check_capacity(problem, solution, issues)
        return ValidationReport(valid=not issues, issues=tuple(issues))

    @staticmethod
    def _check_structure(
        problem: SchedulingProblem, solution: Solution, issues: list[ValidationIssue]
    ) -> None:
        try:
            solution.validate_against(problem)
        except DomainError as error:
            issues.append(ValidationIssue("structure", str(error)))

    @staticmethod
    def _check_requirements(
        problem: SchedulingProblem, solution: Solution, issues: list[ValidationIssue]
    ) -> None:
        for assignment in solution.assignments:
            task = problem.task_by_id(assignment.task_id)
            resources = [problem.resource_by_id(rid) for rid in assignment.resource_ids]
            for requirement in task.requirements:
                provided = sum(1 for r in resources if requirement.tag in r.tags)
                if provided != requirement.quantity:
                    issues.append(
                        ValidationIssue(
                            "unsatisfied_requirement",
                            f"La tarea '{task.name}' requiere {requirement.quantity} recurso(s) "
                            f"con '{requirement.tag}' pero la solución le asigna {provided}.",
                        )
                    )

    @staticmethod
    def _check_capacity(
        problem: SchedulingProblem, solution: Solution, issues: list[ValidationIssue]
    ) -> None:
        # ocupación real: (recurso, slot) -> tareas que lo usan simultáneamente
        occupancy: dict[tuple[int, int], list[str]] = defaultdict(list)
        for assignment in solution.assignments:
            task = problem.task_by_id(assignment.task_id)
            for resource_id in assignment.resource_ids:
                for offset in range(task.duration):
                    slot = int(assignment.start) + offset
                    occupancy[(int(resource_id), slot)].append(task.name)

        for (raw_rid, slot), tasks in sorted(occupancy.items()):
            resource = problem.resource_by_id(ResourceId(raw_rid))
            if len(tasks) > resource.capacity:
                issues.append(
                    ValidationIssue(
                        "capacity_exceeded",
                        f"El recurso '{resource.name}' aloja {len(tasks)} tareas a la vez en el "
                        f"período {slot} (capacidad {resource.capacity}): {', '.join(tasks)}.",
                    )
                )
