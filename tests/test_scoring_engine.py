"""Scoring Engine: restricciones blandas y función objetivo unificada (Fase 8).

Se verifica que las preferencias no imponen nada (el horario sigue siendo
factible), que sí cambian la solución elegida en la dirección esperada, y que
subir el peso de un criterio lo hace prevalecer sobre otro (trade-off).
"""

from __future__ import annotations

import pytest

from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.dsl.domain import BoolDomain
from scheduling_platform.dsl.expressions import LinearExpr, Var
from scheduling_platform.pipeline import OptimizationPipeline
from scheduling_platform.plugins import (
    PenaltyTerm,
    SchedulingModelContext,
    ScoringEngine,
    normalize_weights,
    registry_with,
)
from scheduling_platform.plugins.catalog.preferences import (
    AvoidSlotsPlugin,
    PreferEarlySlotsPlugin,
)
from scheduling_platform.plugins.catalog.structural import ResourceNoOverlapPlugin
from scheduling_platform.sal import SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver

from .plugin_contract import assert_plugin_contract

_CONFIG = SolverConfig(random_seed=1, num_search_workers=1)


def _one_class_problem() -> SchedulingProblem:
    """Una sola clase en un día de 4 períodos: el solver elige libremente."""
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula", frozenset({"room"})),
        ),
        tasks=(
            Task(
                TaskId(0),
                "Mate",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            ),
        ),
    )


def _chosen_slot(problem: SchedulingProblem, plugins: list[object]) -> int:
    context = SchedulingModelContext.build(problem)
    registry = registry_with([ResourceNoOverlapPlugin(), *plugins])  # type: ignore[list-item]
    model = registry.build_model(context)
    solver = ORToolsSolver()
    result = OptimizationPipeline().run(problem, model, solver, _CONFIG)
    assert result.status is SolverStatus.OPTIMAL
    var_map = result.var_map
    assert var_map is not None
    for slot in context.valid_starts(0):
        if solver.value(var_map[context.start_var(0, slot).key]) == 1:
            return slot
    raise AssertionError("ninguna variable de inicio quedó activa")


# --- ScoringEngine (unidad) ---


def test_sin_penalizaciones_no_hay_objetivo() -> None:
    assert ScoringEngine().build_objective([]) is None


def test_objetivo_pondera_cada_penalizacion() -> None:
    x = Var("x", BoolDomain())
    y = Var("y", BoolDomain())
    objective = ScoringEngine().build_objective(
        [
            PenaltyTerm(LinearExpr.of(x), weight=3, label="a"),
            PenaltyTerm(LinearExpr.of(y), weight=5, label="b"),
        ]
    )
    assert objective is not None
    assert {var.key: coef for var, coef in objective.expr.coeffs} == {"x": 3, "y": 5}


def test_peso_no_positivo_es_rechazado() -> None:
    with pytest.raises(ValueError):
        PenaltyTerm(LinearExpr.of(0), weight=0, label="a")


def test_normalize_weights_preserva_proporciones() -> None:
    normalizados = normalize_weights({"a": 1, "b": 3}, scale=100)
    assert normalizados == {"a": 25, "b": 75}


def test_normalize_weights_garantiza_minimo_uno() -> None:
    # un criterio diminuto frente a uno enorme no debe anularse
    normalizados = normalize_weights({"pequeno": 1, "enorme": 10_000}, scale=100)
    assert normalizados["pequeno"] >= 1


def test_weights_by_label_acumula() -> None:
    x = Var("x", BoolDomain())
    penalties = [
        PenaltyTerm(LinearExpr.of(x), weight=2, label="huecos"),
        PenaltyTerm(LinearExpr.of(x), weight=3, label="huecos"),
    ]
    assert ScoringEngine().weights_by_label(penalties) == {"huecos": 5}


# --- Preferencias end-to-end con OR-Tools ---


def test_prefer_early_elige_el_primer_periodo() -> None:
    assert _chosen_slot(_one_class_problem(), [PreferEarlySlotsPlugin(weight=1)]) == 0


def test_avoid_slots_evita_el_periodo_penalizado() -> None:
    # se penaliza el período 0: el solver debe elegir otro
    elegido = _chosen_slot(_one_class_problem(), [AvoidSlotsPlugin(slots=frozenset({0}), weight=1)])
    assert elegido != 0


def test_trade_off_el_peso_mayor_prevalece() -> None:
    problem = _one_class_problem()
    # PreferEarly empuja al período 0; AvoidSlots({0}) lo repele.
    # Con AvoidSlots más pesado, gana evitar el 0.
    elegido = _chosen_slot(
        problem,
        [PreferEarlySlotsPlugin(weight=1), AvoidSlotsPlugin(slots=frozenset({0}), weight=10)],
    )
    assert elegido == 1  # el más temprano de los no penalizados

    # Invirtiendo los pesos, gana la preferencia por la primera hora.
    elegido = _chosen_slot(
        problem,
        [PreferEarlySlotsPlugin(weight=10), AvoidSlotsPlugin(slots=frozenset({0}), weight=1)],
    )
    assert elegido == 0


def test_las_preferencias_no_hacen_infactible_el_horario() -> None:
    # Penalizar TODOS los períodos no impide encontrar solución: son blandas.
    problem = _one_class_problem()
    elegido = _chosen_slot(problem, [AvoidSlotsPlugin(slots=frozenset({0, 1, 2, 3}), weight=5)])
    assert elegido in (0, 1, 2, 3)


def test_reglas_blandas_cumplen_el_contrato_de_plugin() -> None:
    context = SchedulingModelContext.build(_one_class_problem())
    for plugin in (
        PreferEarlySlotsPlugin(weight=2),
        AvoidSlotsPlugin(slots=frozenset({3}), weight=2),
    ):
        assert_plugin_contract(plugin, context)
