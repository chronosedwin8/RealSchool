"""Arnés de contrato reutilizable para plugins del SDK (Fase 6).

Toda implementación de ``SchedulingPlugin`` debe cumplirlo: ser determinista,
devolver DSL puro y referenciar solo variables del contexto (nunca tocar el
solver).
"""

from __future__ import annotations

from scheduling_platform.dsl.logic import DslConstraint
from scheduling_platform.plugins import PenaltyTerm, SchedulingModelContext, SchedulingPlugin


def assert_plugin_contract(plugin: SchedulingPlugin, context: SchedulingModelContext) -> None:
    assert isinstance(plugin.name, str) and plugin.name

    first = plugin.contribute(context)
    second = plugin.contribute(context)
    assert first == second, "contribute debe ser determinista"

    for constraint in first.constraints:
        assert isinstance(constraint, DslConstraint)
    for penalty in first.penalties:
        assert isinstance(penalty, PenaltyTerm)
        assert penalty.weight > 0, "toda penalización debe tener peso positivo"

    # Un plugin solo puede referenciar variables del contexto o variables
    # auxiliares propias con un prefijo reconocible (ocupación, ocupación de aula).
    aux_prefixes = ("occ#", "uses#")
    known = context.all_variable_keys()
    for constraint in first.constraints:
        for variable in constraint.variables():
            assert variable.key in known or variable.key.startswith(aux_prefixes), (
                f"variable ajena al contexto: {variable.key}"
            )
