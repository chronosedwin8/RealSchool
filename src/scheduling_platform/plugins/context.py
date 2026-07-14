"""Contexto del modelo que ven los plugins.

Define el vocabulario simbólico de variables de decisión del problema de
calendarización y las restricciones estructurales base. Los plugins leen este
contexto y emiten restricciones DSL sobre estas variables; nunca tocan el
solver. El esquema es solver-agnóstico (keys de texto): la Fase 7 mapeará cada
key a una variable CP-SAT concreta.

Variables de decisión:
- ``tstart#t{task}`` (entera): período en que arranca la tarea. Su dominio son
  exactamente los inicios válidos.
- ``assign#t{task}#r{resource}`` (booleana): la tarea ``task`` usa ``resource``.
- ``start#t{task}#s{slot}`` (booleana, **opcional**): la tarea inicia en ese
  período. Es una codificación redundante con ``tstart``, pero necesaria para
  las reglas que razonan período a período (preferencias, almuerzo, carga
  diaria). En instituciones grandes multiplica el tamaño del modelo, así que
  puede desactivarse (``boolean_starts=False``) cuando ninguna regla activa la
  necesita: el motor pasa entonces a un modelo puramente de intervalos.

Restricciones estructurales (semántica de las variables, no reglas de negocio):
- Cada tarea inicia exactamente una vez (solo si hay booleanas ``start``).
- Cada requerimiento de recurso se satisface con la cantidad pedida.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..core.problem import SchedulingProblem
from ..core.task import Task
from ..dsl.domain import BoolDomain, EnumDomain, IntDomain
from ..dsl.expressions import LinearExpr, Var
from ..dsl.logic import DslConstraint, LinearConstraint


class BooleanStartsDisabled(RuntimeError):
    """Una regla pidió las booleanas ``start`` en un modelo compacto."""


def _linear_sum(variables: Iterable[Var]) -> LinearExpr:
    """Suma de variables con coeficiente 1, normalizada en una sola pasada."""
    return LinearExpr.from_terms((variable, 1) for variable in variables)


@dataclass(frozen=True, slots=True)
class SchedulingModelContext:
    """Vocabulario de variables y estructura del modelo, expuesto a los plugins."""

    problem: SchedulingProblem
    valid_starts_by_task: Mapping[int, tuple[int, ...]]
    eligible_by_task: Mapping[int, Mapping[str, tuple[int, ...]]]
    tasks_by_resource: Mapping[int, tuple[Task, ...]]
    boolean_starts: bool = True

    @classmethod
    def build(
        cls, problem: SchedulingProblem, *, boolean_starts: bool = True
    ) -> SchedulingModelContext:
        providers: dict[str, list[int]] = defaultdict(list)
        for resource in problem.resources:
            for tag in resource.tags:
                providers[tag].append(int(resource.id))

        valid_starts: dict[int, tuple[int, ...]] = {}
        eligible: dict[int, dict[str, tuple[int, ...]]] = {}
        # Índice inverso recurso -> tareas elegibles. Sin él, cada regla tendría
        # que cruzar todas las tareas contra todos los recursos (O(T x R)), lo
        # que domina el tiempo de construcción en instituciones grandes.
        by_resource: dict[int, list[Task]] = defaultdict(list)

        for task in problem.tasks:
            tid = int(task.id)
            valid_starts[tid] = tuple(sorted(int(s) for s in problem.valid_starts_for(task)))
            per_tag: dict[str, tuple[int, ...]] = {}
            elegibles: set[int] = set()
            for req in task.requirements:
                rids = tuple(sorted(providers.get(req.tag, [])))
                per_tag[req.tag] = rids
                elegibles.update(rids)
            eligible[tid] = per_tag
            for rid in elegibles:
                by_resource[rid].append(task)

        return cls(
            problem,
            valid_starts,
            eligible,
            {rid: tuple(tasks) for rid, tasks in by_resource.items()},
            boolean_starts,
        )

    def tasks_for_resource(self, resource_id: int) -> tuple[Task, ...]:
        """Tareas que pueden usar ese recurso (índice precalculado)."""
        return self.tasks_by_resource.get(resource_id, ())

    # --- vocabulario de variables ---

    def start_var(self, task_id: int, slot: int) -> Var:
        if not self.boolean_starts:
            raise BooleanStartsDisabled(
                "este modelo se construyó sin las booleanas 'start' (modo compacto); "
                "una regla las está pidiendo. Reconstruye el contexto con "
                "boolean_starts=True o usa reglas basadas en 'tstart'."
            )
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
            keys.add(self.task_start_var(tid).key)
            if self.boolean_starts:
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
            if self.boolean_starts:
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

    def task_start_var(self, task_id: int) -> Var:
        """Entera: el período en que arranca la tarea.

        Su dominio son *exactamente* los inicios válidos (puede tener huecos),
        así que por sí sola ya restringe la tarea a horarios legales. Es el
        inicio que consumen los intervalos.
        """
        starts = self.valid_starts(task_id)
        if not starts:
            return Var(f"tstart#t{task_id}", IntDomain(0, 0))
        return Var(f"tstart#t{task_id}", EnumDomain(tuple(starts)))

    def start_channeling(self, task_id: int) -> DslConstraint:
        """Enlaza las booleanas ``start`` con la entera ``tstart``.

        ``sum(s * start[t,s]) == tstart[t]``. Como exactamente un ``start`` vale
        1, la suma es justo el período elegido.
        """
        pairs = [(self.start_var(task_id, slot), slot) for slot in self.valid_starts(task_id)]
        pairs.append((self.task_start_var(task_id), -1))
        return LinearConstraint(LinearExpr.from_terms(pairs).eq(0))

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
