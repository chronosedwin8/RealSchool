"""Scoring Engine v2: Tiers y normalización por máximo teórico (O2, ADR-020)."""

from __future__ import annotations

from collections.abc import Sequence

from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.core.ids import TimeSlotIndex
from scheduling_platform.dsl.domain import BoolDomain
from scheduling_platform.dsl.expressions import LinearExpr, Var
from scheduling_platform.engine import SchedulingEngine
from scheduling_platform.pipeline import OptimizationPipeline
from scheduling_platform.plugins import (
    PenaltyTerm,
    PluginRegistry,
    SchedulingModelContext,
    SchedulingPlugin,
    ScoringEngine,
    registry_from_catalog,
)
from scheduling_platform.plugins.catalog.preferences import AvoidSlotsPlugin, PreferEarlySlotsPlugin
from scheduling_platform.plugins.catalog.structural import ResourceNoOverlapPlugin
from scheduling_platform.sal import SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver

_CONFIG = SolverConfig(random_seed=1, num_search_workers=1)
_A = Var("a", BoolDomain())


def _term(weight: int, label: str, *, tier: int = 3, tmax: int | None = None) -> PenaltyTerm:
    return PenaltyTerm(
        LinearExpr.of(_A), weight=weight, label=label, tier=tier, theoretical_max=tmax
    )


# --- Coeficiente efectivo ---


def test_retrocompatibilidad_tier3_sin_maximo_es_el_peso() -> None:
    assert ScoringEngine().effective_coefficient(_term(5, "x")) == 5


def test_multiplicadores_por_tier() -> None:
    eng = ScoringEngine()
    assert eng.effective_coefficient(_term(1, "x", tier=1)) == 10_000
    assert eng.effective_coefficient(_term(1, "x", tier=2)) == 100
    assert eng.effective_coefficient(_term(1, "x", tier=3)) == 1


def test_normalizacion_por_maximo_teorico() -> None:
    # round(E2=100 * W=2 * SCALE=1000 / smax=4) = 50000
    assert ScoringEngine().effective_coefficient(_term(2, "x", tier=2, tmax=4)) == 50_000


def test_tier_by_label_tiene_prioridad_sobre_el_del_termino() -> None:
    eng = ScoringEngine(tier_by_label={"x": 1})
    assert eng.effective_coefficient(_term(3, "x", tier=3)) == 30_000


def test_dominancia_lexicografica_de_coeficientes() -> None:
    # Una violación Tier-1 pesa más que TODAS las Tier-3 posibles juntas.
    eng = ScoringEngine()
    coef_vital = eng.effective_coefficient(_term(1, "vital", tier=1))
    # 100 criterios preferenciales de peso 1, cada uno violado hasta 50 veces
    peor_preferencial = sum(
        eng.effective_coefficient(_term(1, f"p{i}", tier=3)) * 50 for i in range(100)
    )
    assert coef_vital > peor_preferencial


def test_objetivo_por_defecto_conserva_los_pesos_crudos() -> None:
    # Retrocompatibilidad: sin tiers ni máximos, coef == weight (comportamiento histórico).
    objective = ScoringEngine().build_objective([_term(3, "a"), _term(5, "b")])
    assert objective is not None
    assert {v.key: c for v, c in objective.expr.coeffs} == {"a": 8}  # ambos sobre 'a'


# --- Catálogo: tiers operativos ---


def test_registry_from_catalog_construye_scoring_con_tiers() -> None:
    registry = registry_from_catalog(["SC-02", "SC-06", "SC-01"])
    tiers = registry.scoring.tier_by_label
    assert tiers["teacher_gaps"] == 1  # SC-02 vital
    assert tiers["teacher_room_stability"] == 2  # SC-06 operativa
    assert tiers["prefer_early_slots"] == 3  # SC-01 preferencial


# --- Extremo a extremo: los tiers cambian la decisión ---


def _one_class(slots: int = 4, allowed: set[int] | None = None) -> SchedulingProblem:
    starts = frozenset(TimeSlotIndex(s) for s in allowed) if allowed is not None else None
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([slots]),
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
                allowed_starts=starts,
            ),
        ),
    )


def _chosen_slot(
    problem: SchedulingProblem, plugins: Sequence[SchedulingPlugin], scoring: ScoringEngine
) -> int:
    context = SchedulingModelContext.build(problem)
    registry = PluginRegistry(scoring=scoring)
    registry.register(ResourceNoOverlapPlugin())
    for plugin in plugins:
        registry.register(plugin)
    solver = ORToolsSolver()
    result = OptimizationPipeline().run(problem, registry.build_model(context), solver, _CONFIG)
    assert result.status is SolverStatus.OPTIMAL
    var_map = result.var_map
    assert var_map is not None
    for slot in context.valid_starts(0):
        if solver.value(var_map[context.start_var(0, slot).key]) == 1:
            return slot
    raise AssertionError("ninguna variable de inicio quedó activa")


def test_un_tier_alto_domina_a_uno_bajo_mas_pesado() -> None:
    problem = _one_class()
    plugins = [
        PreferEarlySlotsPlugin(weight=100),  # empuja fuerte al período 0 (Tier 3)
        AvoidSlotsPlugin(slots=frozenset({0}), weight=1),  # repele el 0 (Tier 1)
    ]
    # Sin tiers, el peso 100 gana: se elige el período 0.
    assert _chosen_slot(problem, plugins, ScoringEngine()) == 0
    # Con 'avoid_slots' en Tier 1, evitar el 0 domina pese al peso menor.
    tiered = ScoringEngine(tier_by_label={"avoid_slots": 1})
    assert _chosen_slot(problem, plugins, tiered) != 0


def test_invariante_suma_penalizaciones_igual_objetivo_con_tiers() -> None:
    # Con el horario forzado al período 0, la penalización se dispara; el informe
    # debe sumar exactamente el valor del objetivo (mismo coeficiente efectivo).
    problem = _one_class(allowed={0})
    scoring = ScoringEngine(tier_by_label={"avoid_slots": 2})
    registry = PluginRegistry(scoring=scoring)
    registry.register(ResourceNoOverlapPlugin())
    registry.register(AvoidSlotsPlugin(slots=frozenset({0}), weight=3))
    result = SchedulingEngine(registry=registry, solver_factory=ORToolsSolver).solve(
        problem, _CONFIG
    )
    assert result.solved
    assert result.solution is not None
    total = sum(p.amount for p in result.solution.penalties)
    assert total == result.solution.objective_value
    assert result.solution.objective_value == 300  # E2=100 * weight 3 * 1 violación
