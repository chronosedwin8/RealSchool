"""Serialización: JSON, YAML y el contenedor .proschedule (Fase 10).

Pruebas de rigor: round-trip property-based (exportar → importar → modelo
idéntico), compatibilidad de versiones del esquema, y la garantía central de que
un ``.proschedule`` **reproduce el mismo horario** en una ejecución limpia.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given

from scheduling_platform.academic import AcademicProblem, AcademicToCanonicalAdapter
from scheduling_platform.core import (
    Assignment,
    ConstraintId,
    HardConstraint,
    Penalty,
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    SoftConstraint,
    Solution,
    Task,
    TaskId,
    TimeGrid,
    TimeSlotIndex,
)
from scheduling_platform.engine import SchedulingEngine
from scheduling_platform.plugins import registry_with
from scheduling_platform.plugins.catalog.structural import ResourceNoOverlapPlugin
from scheduling_platform.sal import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver
from scheduling_platform.serialization import (
    ProSchedule,
    SerializationError,
    UnsupportedSchemaVersion,
    load_proschedule,
    problem_from_json,
    problem_from_yaml,
    problem_to_json,
    problem_to_yaml,
    save_proschedule,
    solution_from_json,
    solution_to_json,
)

from .academic_strategies import academic_problems

_CONFIG = SolverConfig(random_seed=1, num_search_workers=1)


def _problem() -> SchedulingProblem:
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([2, 2]),
        resources=(
            Resource(ResourceId(0), "Prof. Juan", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula 101", frozenset({"room"}), attributes=(("seats", 30),)),
        ),
        tasks=(
            Task(
                TaskId(0),
                "Mate",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
                allowed_starts=frozenset({TimeSlotIndex(0), TimeSlotIndex(1)}),
                attributes=(("size", 25),),
            ),
            Task(
                TaskId(1),
                "Física",
                2,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            ),
        ),
        constraints=(
            HardConstraint(ConstraintId(0), "no_overlap"),
            SoftConstraint(ConstraintId(1), "prefer_early", weight=5),
        ),
    )


# --- Round-trip ---


def test_roundtrip_json_preserva_el_problema() -> None:
    original = _problem()
    assert problem_from_json(problem_to_json(original)) == original


def test_roundtrip_yaml_preserva_el_problema() -> None:
    original = _problem()
    assert problem_from_yaml(problem_to_yaml(original)) == original


def test_roundtrip_json_preserva_la_solucion() -> None:
    original = Solution(
        assignments=(Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),),
        objective_value=7,
        penalties=(Penalty("prefer_early_slots", 7),),
    )
    assert solution_from_json(solution_to_json(original)) == original


@given(academic_problems())
def test_property_roundtrip_de_cualquier_problema_academico(academic: AcademicProblem) -> None:
    canonical = AcademicToCanonicalAdapter().translate(academic).problem
    assert problem_from_json(problem_to_json(canonical)) == canonical


# --- Contenedor .proschedule ---


def test_proschedule_reproduce_el_mismo_horario(tmp_path: Path) -> None:
    problem = _problem()
    engine = SchedulingEngine(
        registry=registry_with([ResourceNoOverlapPlugin()]), solver_factory=ORToolsSolver
    )
    original = engine.solve(problem, _CONFIG)
    assert original.solution is not None

    ruta = tmp_path / "colegio.proschedule"
    save_proschedule(
        ruta, ProSchedule(problem=problem, solution=original.solution, metadata={"autor": "test"})
    )

    # Ejecución limpia: se carga el proyecto y se vuelve a resolver.
    cargado = load_proschedule(ruta)
    assert cargado.problem == problem
    assert cargado.solution == original.solution
    assert cargado.metadata == {"autor": "test"}

    reejecutado = engine.solve(cargado.problem, _CONFIG)
    assert reejecutado.solution is not None
    assert reejecutado.solution.assignments == original.solution.assignments


def test_proschedule_sin_solucion(tmp_path: Path) -> None:
    ruta = tmp_path / "solo_problema.proschedule"
    save_proschedule(ruta, ProSchedule(problem=_problem()))
    cargado = load_proschedule(ruta)
    assert cargado.solution is None


def test_proschedule_rechaza_version_incompatible(tmp_path: Path) -> None:
    import gzip
    import json

    ruta = tmp_path / "futuro.proschedule"
    with gzip.open(ruta, "wb") as handle:
        handle.write(
            json.dumps(
                {"format": "proschedule", "version": 999, "problem": {}, "solution": None}
            ).encode()
        )
    with pytest.raises(UnsupportedSchemaVersion):
        load_proschedule(ruta)


def test_proschedule_rechaza_formato_ajeno(tmp_path: Path) -> None:
    import gzip
    import json

    ruta = tmp_path / "ajeno.proschedule"
    with gzip.open(ruta, "wb") as handle:
        handle.write(json.dumps({"format": "otra-cosa", "version": 1}).encode())
    with pytest.raises(SerializationError):
        load_proschedule(ruta)
