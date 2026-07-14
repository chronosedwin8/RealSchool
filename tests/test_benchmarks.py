"""Benchmarks de escala y presupuestos de rendimiento (Fase 11).

Pruebas de rigor:
- Los datasets sintéticos son **factibles por construcción** y se rechazan los
  parámetros imposibles.
- El **modo compacto** (sin booleanas de inicio) reduce drásticamente el modelo,
  y una regla que las necesite falla de forma explícita, no silenciosa.
- El motor respeta el **límite de tiempo**: nunca se cuelga.

La medición a escala real (500 docentes / 300 aulas / 1500 grupos) se ejecuta
con ``scripts/benchmark.py xl``; aquí se usan instancias pequeñas para que la
suite siga siendo rápida.
"""

from __future__ import annotations

import pytest

from scheduling_platform.benchmarks import (
    PRESETS,
    BenchmarkRunner,
    DatasetSpec,
    InfeasibleDataset,
    build_academic,
)
from scheduling_platform.plugins import SchedulingModelContext, registry_with
from scheduling_platform.plugins.catalog.preferences import PreferEarlySlotsPlugin
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.plugins.context import BooleanStartsDisabled
from scheduling_platform.sal import SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver

_TINY = DatasetSpec(
    name="tiny",
    teachers=10,
    rooms=8,
    groups=8,
    subjects=5,
    days=5,
    periods_per_day=6,
    load_factor=0.5,
)
_CONFIG = SolverConfig(max_time_in_seconds=20.0, num_search_workers=4, random_seed=1)


# --- Dataset Provider ---


def test_todos_los_presets_son_factibles_por_construccion() -> None:
    for spec in PRESETS.values():
        spec.validate()  # no lanza


def test_dataset_imposible_se_rechaza() -> None:
    # 100 grupos con una sola aula no caben en la semana
    imposible = DatasetSpec(name="imposible", teachers=50, rooms=1, groups=100, subjects=5)
    with pytest.raises(InfeasibleDataset):
        imposible.validate()


def test_el_preset_xl_alcanza_la_escala_objetivo() -> None:
    xl = PRESETS["xl"]
    assert xl.teachers == 500
    assert xl.rooms == 300
    assert xl.groups == 1500
    xl.validate()


def test_dataset_academico_se_construye() -> None:
    academic = build_academic(_TINY)
    assert len(academic.teachers) == 10
    assert len(academic.assignments) == _TINY.total_classes


# --- Runner y presupuestos ---


def test_runner_produce_un_horario_valido() -> None:
    run = BenchmarkRunner(solver_factory=ORToolsSolver).run(_TINY, _CONFIG)
    assert run.solved
    assert run.hard_violations == 0
    assert run.tasks == _TINY.total_classes
    assert run.num_variables > 0
    assert run.t_total_ms > 0
    assert "tiny" in run.render()
    assert run.to_dict()["dataset"] == "tiny"


def test_el_modo_compacto_reduce_drasticamente_el_modelo() -> None:
    compacto = BenchmarkRunner(solver_factory=ORToolsSolver, boolean_starts=False).run(
        _TINY, _CONFIG
    )
    booleano = BenchmarkRunner(solver_factory=ORToolsSolver, boolean_starts=True).run(
        _TINY, _CONFIG
    )
    # las booleanas de inicio son 'tareas x períodos': dominan el modelo
    assert compacto.num_variables < booleano.num_variables / 2
    # y ambos producen un horario válido
    assert compacto.solved and booleano.solved


def test_el_estres_respeta_el_limite_de_tiempo() -> None:
    # Con un límite muy corto el motor debe devolver el control, no colgarse.
    apretado = SolverConfig(max_time_in_seconds=2.0, num_search_workers=2, random_seed=1)
    run = BenchmarkRunner(solver_factory=ORToolsSolver).run(_TINY, apretado)
    assert run.status in {s.value for s in SolverStatus}
    assert run.t_solve_ms < 10_000  # muy por debajo de colgarse


# --- El modo compacto falla de forma explícita, no silenciosa ---


def test_una_regla_que_necesita_las_booleanas_falla_claramente() -> None:
    academic = build_academic(_TINY)
    from scheduling_platform.academic import AcademicToCanonicalAdapter

    problem = AcademicToCanonicalAdapter().translate(academic).problem
    context = SchedulingModelContext.build(problem, boolean_starts=False)

    registry = registry_with([IntervalNoOverlapPlugin(), PreferEarlySlotsPlugin(weight=1)])
    with pytest.raises(BooleanStartsDisabled):
        registry.build_model(context)


def test_las_reglas_por_periodo_funcionan_con_booleanas_activas() -> None:
    academic = build_academic(_TINY)
    from scheduling_platform.academic import AcademicToCanonicalAdapter

    problem = AcademicToCanonicalAdapter().translate(academic).problem
    context = SchedulingModelContext.build(problem, boolean_starts=True)

    registry = registry_with([IntervalNoOverlapPlugin(), PreferEarlySlotsPlugin(weight=1)])
    model = registry.build_model(context)
    assert model.objective is not None
