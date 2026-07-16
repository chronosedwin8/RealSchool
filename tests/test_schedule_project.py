"""Formato de proyecto .schedule: round-trip atómico sin pérdida (H2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scheduling_platform.application import (
    ConfigError,
    ScheduleProject,
    new_project,
    open_project,
    save_project,
)
from scheduling_platform.application.project import engine_version
from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.core.assignment import Assignment
from scheduling_platform.core.ids import TimeSlotIndex
from scheduling_platform.core.solution import Solution
from scheduling_platform.serialization.codec import problem_to_dict, solution_to_dict


def _problem() -> SchedulingProblem:
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


def _solution() -> Solution:
    return Solution(
        assignments=(Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),),
        objective_value=7,
    )


def test_round_trip_completo(tmp_path: Path) -> None:
    problem = _problem()
    project = ScheduleProject.create(
        "Colegio Demo", problem, config={"engine": {"default_solver": "ortools_cpsat"}}
    )
    project = ScheduleProject(
        metadata=project.metadata,
        problem=problem,
        config=project.config,
        solution=_solution(),
        benchmarks=({"t_total_ms": 123.0},),
    )
    path = tmp_path / "demo.schedule"
    save_project(path, project)

    reloaded = open_project(path)
    assert reloaded.metadata["name"] == "Colegio Demo"
    assert "uuid" in reloaded.metadata
    assert reloaded.config == {"engine": {"default_solver": "ortools_cpsat"}}
    assert problem_to_dict(reloaded.problem) == problem_to_dict(problem)
    assert reloaded.solution is not None
    assert solution_to_dict(reloaded.solution) == solution_to_dict(_solution())
    assert reloaded.benchmarks == ({"t_total_ms": 123.0},)


def test_new_project_persiste_con_metadatos(tmp_path: Path) -> None:
    path = tmp_path / "nuevo.schedule"
    project = new_project(path, "Nuevo", _problem())
    assert path.exists()
    assert project.metadata["engine_version"] == engine_version()
    reloaded = open_project(path)
    assert reloaded.metadata["uuid"] == project.metadata["uuid"]


def test_escritura_atomica_no_deja_temporales(tmp_path: Path) -> None:
    path = tmp_path / "x.schedule"
    save_project(path, ScheduleProject.create("X", _problem()))
    # sobrescribir no corrompe ni deja .tmp colgando
    save_project(path, ScheduleProject.create("X2", _problem()))
    assert open_project(path).metadata["name"] == "X2"
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*tmp*")) == []


def test_abrir_inexistente_falla_claro(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no existe"):
        open_project(tmp_path / "fantasma.schedule")


def test_abrir_archivo_no_zip_falla_claro(tmp_path: Path) -> None:
    bad = tmp_path / "corrupto.schedule"
    bad.write_text("esto no es un zip", encoding="utf-8")
    with pytest.raises(ConfigError, match="válido"):
        open_project(bad)


def test_solution_opcional(tmp_path: Path) -> None:
    path = tmp_path / "sin_sol.schedule"
    save_project(path, ScheduleProject.create("SinSol", _problem()))
    assert open_project(path).solution is None
