"""Contexto del modelo que ven los plugins.

Define el vocabulario simbólico de variables de decisión del problema de
calendarización y las restricciones estructurales base. Los plugins leen este
contexto y emiten restricciones DSL sobre estas variables; nunca tocan el
solver. El esquema es solver-agnóstico (keys de texto): la Fase 7 mapeará cada
key a una variable CP-SAT concreta.

Variables de decisión:
- ``start#t{task}#s{slot}`` (booleana): la tarea ``task`` inicia en ``slot``.
- ``assign#t{task}#r{resource}`` (booleana): la tarea ``task`` usa ``resource``.

Restricciones estructurales (semántica de las variables, no reglas de negocio):
- Cada tarea inicia exactamente una vez.
- Cada requerimiento de recurso se satisface con la cantidad pedida.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..core.problem import SchedulingProblem
from ..core.task import Task
from ..dsl.domain import BoolDomain
from ..dsl.expressions import LinearExpr, Var
from ..dsl.logic import DslConstraint, LinearConstraint


def _linear_sum(variables: Iterable[Var]) -> LinearExpr:
    acc = LinearExpr.of(0)
    for variable in variables:
        acc = acc + variable
    return acc


@dataclass(frozen=True, slots=True)
class SchedulingModelContext:
    """Vocabulario de variables y estructura del modelo, expuesto a los plugins."""

    problem: SchedulingProblem
    valid_starts_by_task: Mapping[int, tuple[int, ...]]
    eligible_by_task: Mapping[int, Mapping[str, tuple[int, ...]]]

    @classmethod
    def build(cls, problem: SchedulingProblem) -> SchedulingModelContext:
        providers: dict[str, list[int]] = defaultdict(list)
        for resource in problem.resources:
            for tag in resource.tags:
                providers[tag].append(int(resource.id))

        valid_starts: dict[int, tuple[int, ...]] = {}
        eligible: dict[int, dict[str, tuple[int, ...]]] = {}
        for task in problem.tasks:
            tid = int(task.id)
            valid_starts[tid] = tuple(sorted(int(s) for s in problem.valid_starts_for(task)))
            eligible[tid] = {
                req.tag: tuple(sorted(providers.get(req.tag, []))) for req in task.requirements
            }
        return cls(problem, valid_starts, eligible)

    # --- vocabulario de variables ---

    def start_var(self, task_id: int, slot: int) -> Var:
        return Var(f"start#t{task_id}#s{slot}", BoolDomain())

    def assign_var(self, task_id: int, resource_id: int) -> Var:
        return Var(f"assign#t{task_id}#r{resource_id}", BoolDomain())

    def valid_starts(self, task_id: int) -> tuple[int, ...]:
        return self.valid_starts_by_task[task_id]

    def eligible_resources(self, task_id: int, tag: str) -> tuple[int, ...]:
        return self.eligible_by_task[task_id].get(tag, ())

    def all_variable_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        for task in self.problem.tasks:
            tid = int(task.id)
            for slot in self.valid_starts(tid):
                keys.add(self.start_var(tid, slot).key)
            for req in task.requirements:
                for rid in self.eligible_resources(tid, req.tag):
                    keys.add(self.assign_var(tid, rid).key)
        return frozenset(keys)

    # --- restricciones estructurales base ---

    def structural_constraints(self) -> tuple[DslConstraint, ...]:
        constraints: list[DslConstraint] = []
        for task in self.problem.tasks:
            tid = int(task.id)
            starts = self.valid_starts(tid)
            start_sum = _linear_sum(self.start_var(tid, s) for s in starts)
            constraints.append(LinearConstraint(start_sum.eq(1)))
            for req in task.requirements:
                assign_sum = _linear_sum(
                    self.assign_var(tid, rid) for rid in self.eligible_resources(tid, req.tag)
                )
                constraints.append(LinearConstraint(assign_sum.eq(req.quantity)))
        return tuple(constraints)

    def slots_covered(self, start: int, duration: int) -> Sequence[int]:
        return range(start, start + duration)

    # --- ocupación (compartida por las reglas de la Fase 8) ---

    def covering_starts(self, task: Task, slot: int) -> tuple[int, ...]:
        """Inicios válidos de ``task`` cuya duración cubriría ``slot``."""
        tid = int(task.id)
        return tuple(s for s in self.valid_starts(tid) if s <= slot < s + task.duration)

    def occupies_var(self, task_id: int, resource_id: int, slot: int) -> Var:
        """Booleana: la tarea ocupa ese recurso en ese slot."""
        return Var(f"occ#t{task_id}#r{resource_id}#k{slot}", BoolDomain())

    def occupancy(
        self, task: Task, resource_id: int, slot: int
    ) -> tuple[Var, tuple[DslConstraint, ...]]:
        """Variable de ocupación y sus restricciones de enlace.

        ``occ = assign AND cover`` linealizado (ambos son 0/1), donde ``cover``
        es la suma de los ``start`` que cubrirían el slot. Varias reglas pueden
        pedir la misma ocupación: las keys coinciden y los enlaces duplicados son
        inocuos (el pase de deduplicación del CIR los colapsa).
        """
        tid = int(task.id)
        occ = self.occupies_var(tid, resource_id, slot)
        covering = self.covering_starts(task, slot)
        if not covering:
            return occ, (LinearConstraint(occ.eq(0)),)
        cover = _linear_sum(self.start_var(tid, s) for s in covering)
        assign = self.assign_var(tid, resource_id)
        return occ, (
            LinearConstraint((occ - assign) <= 0),
            LinearConstraint((occ - cover) <= 0),
            LinearConstraint((occ - assign - cover) >= -1),
        )
