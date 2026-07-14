"""Constraint Graph Builder: detección de infactibilidad estructural pre-solver.

Analiza el :class:`SchedulingProblem` canónico y detecta, mediante *condiciones
necesarias*, situaciones sin solución antes de invocar al solver. Toda
condición comprobada es necesaria: si se viola, el problema es demostrablemente
infactible (no hay falsos positivos). Los cuatro chequeos:

1. **Tag sin proveedor:** una tarea requiere un tag que ningún recurso ofrece.
2. **Dominio temporal vacío:** una tarea no tiene ningún inicio válido.
3. **Sobre-suscripción de recurso unario:** un recurso fijo (único proveedor,
   capacidad 1) debe ocupar más períodos de los que sus tareas pueden ocupar
   (p. ej. "Prof. Juan debe impartir 42 períodos pero dispone de 37").
4. **Demanda > oferta global:** para un tag compartido, la demanda total de
   tiempo supera la oferta (proveedores x horizonte).
"""

from __future__ import annotations

from collections import defaultdict

from ..core.problem import SchedulingProblem
from ..core.resource import Resource
from ..core.task import Task
from .issues import StructuralIssue


class ConstraintGraphBuilder:
    """Construye el grafo de recursos/tareas y detecta infactibilidades graves."""

    def analyze(self, problem: SchedulingProblem) -> tuple[StructuralIssue, ...]:
        providers = self._providers_by_tag(problem)
        demand = self._demand_by_tag(problem)
        issues: list[StructuralIssue] = []
        self._check_unsatisfiable_tags(problem, providers, issues)
        self._check_empty_time_domains(problem, issues)
        self._check_capacity(problem, providers, demand, issues)
        return tuple(issues)

    @staticmethod
    def _providers_by_tag(problem: SchedulingProblem) -> dict[str, list[Resource]]:
        providers: dict[str, list[Resource]] = defaultdict(list)
        for resource in problem.resources:
            for tag in resource.tags:
                providers[tag].append(resource)
        return providers

    @staticmethod
    def _demand_by_tag(problem: SchedulingProblem) -> dict[str, list[tuple[Task, int]]]:
        demand: dict[str, list[tuple[Task, int]]] = defaultdict(list)
        for task in problem.tasks:
            for requirement in task.requirements:
                demand[requirement.tag].append((task, requirement.quantity))
        return demand

    def _check_unsatisfiable_tags(
        self,
        problem: SchedulingProblem,
        providers: dict[str, list[Resource]],
        issues: list[StructuralIssue],
    ) -> None:
        missing: set[str] = set()
        for task in problem.tasks:
            for requirement in task.requirements:
                if requirement.tag not in providers:
                    missing.add(requirement.tag)
        for tag in sorted(missing):
            issues.append(
                StructuralIssue(
                    kind="unsatisfiable_requirement",
                    message=f"Ningún recurso provee '{tag}', requerido por al menos una tarea.",
                    entities=(tag,),
                )
            )

    def _check_empty_time_domains(
        self, problem: SchedulingProblem, issues: list[StructuralIssue]
    ) -> None:
        for task in problem.tasks:
            if not problem.valid_starts_for(task):
                issues.append(
                    StructuralIssue(
                        kind="empty_time_domain",
                        message=(
                            f"La tarea '{task.name}' no tiene ningún horario válido "
                            "(disponibilidad demasiado restringida)."
                        ),
                        entities=(task.name,),
                    )
                )

    def _check_capacity(
        self,
        problem: SchedulingProblem,
        providers: dict[str, list[Resource]],
        demand: dict[str, list[tuple[Task, int]]],
        issues: list[StructuralIssue],
    ) -> None:
        horizon = problem.horizon
        for tag, requiring in sorted(demand.items()):
            provs = providers.get(tag)
            if not provs:
                continue  # ya reportado como tag sin proveedor
            total_demand = sum(quantity * task.duration for task, quantity in requiring)
            if len(provs) == 1 and provs[0].capacity == 1:
                supply = self._occupiable_slot_count(problem, [t for t, _ in requiring])
                if total_demand > supply:
                    resource = provs[0]
                    issues.append(
                        StructuralIssue(
                            kind="resource_oversubscription",
                            message=(
                                f"El recurso '{resource.name}' debe ocupar {total_demand} "
                                f"períodos pero solo dispone de {supply}. "
                                f"Faltan {total_demand - supply}."
                            ),
                            entities=(resource.name,),
                        )
                    )
            else:
                supply = sum(p.capacity for p in provs) * horizon
                if total_demand > supply:
                    issues.append(
                        StructuralIssue(
                            kind="global_capacity",
                            message=(
                                f"La demanda de '{tag}' ({total_demand} períodos) supera la "
                                f"oferta total ({supply}: {len(provs)} recursos x {horizon})."
                            ),
                            entities=(tag,),
                        )
                    )

    @staticmethod
    def _occupiable_slot_count(problem: SchedulingProblem, tasks: list[Task]) -> int:
        slots: set[int] = set()
        for task in tasks:
            for start in problem.valid_starts_for(task):
                for offset in range(task.duration):
                    slots.add(start + offset)
        return len(slots)
