"""Agregado de salida: la solución del problema (D5).

Contiene las asignaciones, el valor de la función objetivo y el desglose de
penalizaciones (informe que en la Fase 9 producirá el ``SolutionInspector``).
Sus invariantes propias son estructurales; ``validate_against`` re-verifica la
solución contra un problema concreto de forma independiente del solver —
semilla del Validation Engine de la Fase 9 ("nunca confiar solo en el solver").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .assignment import Assignment
from .exceptions import InvalidAssignment, ReferentialIntegrityError, require
from .ids import TaskId

if TYPE_CHECKING:
    from .problem import SchedulingProblem


@dataclass(frozen=True, slots=True)
class Penalty:
    """Penalización aportada por una restricción blanda al objetivo."""

    source: str
    amount: int

    def __post_init__(self) -> None:
        require(
            bool(self.source.strip()),
            InvalidAssignment,
            "el origen de la penalización no puede ser vacío",
        )
        require(self.amount >= 0, InvalidAssignment, f"penalización negativa: {self.amount}")


@dataclass(frozen=True, slots=True)
class Solution:
    """Horario resuelto: asignaciones + valor objetivo + desglose de penalizaciones."""

    assignments: tuple[Assignment, ...]
    objective_value: int
    penalties: tuple[Penalty, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        task_ids = [a.task_id for a in self.assignments]
        require(
            len(task_ids) == len(set(task_ids)),
            InvalidAssignment,
            "una tarea tiene más de una asignación en la solución",
        )
        require(
            self.objective_value >= 0,
            InvalidAssignment,
            f"objetivo negativo: {self.objective_value}",
        )

    def assignment_for(self, task_id: TaskId) -> Assignment | None:
        for assignment in self.assignments:
            if assignment.task_id == task_id:
                return assignment
        return None

    def validate_against(self, problem: SchedulingProblem) -> None:
        """Re-verifica la solución contra el problema (independiente del solver).

        Comprueba cobertura exacta de tareas, inicios dentro del dominio válido
        y existencia de los recursos asignados. Lanza un error del dominio ante
        la primera violación.
        """
        problem_task_ids = {t.id for t in problem.tasks}
        solution_task_ids = {a.task_id for a in self.assignments}
        require(
            solution_task_ids == problem_task_ids,
            ReferentialIntegrityError,
            f"cobertura de tareas incorrecta: faltan {problem_task_ids - solution_task_ids}, "
            f"sobran {solution_task_ids - problem_task_ids}",
        )
        resource_ids = {r.id for r in problem.resources}
        for assignment in self.assignments:
            task = problem.task_by_id(assignment.task_id)
            valid = problem.valid_starts_for(task)
            require(
                assignment.start in valid,
                InvalidAssignment,
                f"inicio {assignment.start} inválido para la tarea {task.id}",
            )
            for rid in assignment.resource_ids:
                require(
                    rid in resource_ids,
                    ReferentialIntegrityError,
                    f"la tarea {task.id} usa un recurso inexistente: {rid}",
                )
