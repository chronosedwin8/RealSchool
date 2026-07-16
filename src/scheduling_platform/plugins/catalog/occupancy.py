"""Ocupación agregada por recurso y período (compartida por las reglas de calidad).

Varias reglas blandas (huecos, continuidad, balance, jornada) razonan sobre si un
recurso está **ocupado** en un período dado. Este módulo produce una única
variable booleana ``busy#r{rid}#k{slot}`` por (recurso, período) y sus enlaces,
de modo que todas las reglas compartan la misma variable: como las keys y los
enlaces coinciden, el pase de deduplicación del CIR los colapsa y no se paga dos
veces.

``busy`` es el OR (linealizado) de las ocupaciones de cada tarea candidata sobre
ese recurso y período:

    busy >= occ_tarea      (se fuerza a 1 si alguna tarea ocupa)
    busy <= sum(occ_tarea) (no puede valer 1 si ninguna ocupa)

Requiere el modo con booleanas de inicio (``boolean_starts=True``): la ocupación
período-a-período no existe en el modelo puramente de intervalos.
"""

from __future__ import annotations

from ...dsl.domain import BoolDomain
from ...dsl.expressions import LinearExpr, Var
from ...dsl.logic import DslConstraint, LinearConstraint
from ..context import SchedulingModelContext


def busy_var(
    context: SchedulingModelContext, resource_id: int, slot: int
) -> tuple[Var, list[DslConstraint]]:
    """Variable booleana "el recurso está ocupado en ese período" y sus enlaces."""
    busy = Var(f"busy#r{resource_id}#k{slot}", BoolDomain())
    links: list[DslConstraint] = []
    occ_vars: list[Var] = []
    for task in context.tasks_for_resource(resource_id):
        if not context.covering_starts(task, slot):
            continue
        occ, occ_links = context.occupancy(task, resource_id, slot)
        links.extend(occ_links)
        occ_vars.append(occ)

    if not occ_vars:
        links.append(LinearConstraint(busy.eq(0)))
        return busy, links

    for occ in occ_vars:
        links.append(LinearConstraint((busy - occ) >= 0))
    links.append(LinearConstraint((busy - LinearExpr.from_terms((v, 1) for v in occ_vars)) <= 0))
    return busy, links


def day_slots(context: SchedulingModelContext) -> list[tuple[int, int]]:
    """(inicio, fin_exclusivo) de cada día operativo (segmento de la rejilla)."""
    return [(int(seg.start), int(seg.end)) for seg in context.problem.grid.segments]
