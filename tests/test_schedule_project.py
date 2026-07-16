"""Proyecto tipado .bjs (B2): round-trip completo sin pérdida, metadatos, atomicidad."""

from __future__ import annotations

from pathlib import Path

import pytest

from scheduling_platform.application import (
    BjsProject,
    new_project,
    open_project,
    save_project,
)
from scheduling_platform.application.config import EngineConfig, PluginsConfig, PluginSetting
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
    constraints = PluginsConfig((PluginSetting(id="teacher_room_stability", tier=2, weight=100),))
    solver_config = EngineConfig(default_solver="highs", threads=4, random_seed=9)
    base = BjsProject.create(
        "Colegio Demo", problem, constraints=constraints, solver_config=solver_config
    )
    project = BjsProject(
        manifest=base.manifest,
        problem=problem,
        constraints=constraints,
        solver_config=solver_config,
        solution=_solution(),
        metrics={"quality_score": 96.5},
        history=({"solver": "ortools_cpsat", "quality_score": 96.5},),
    )
    path = tmp_path / "demo.bjs"
    save_project(path, project)

    reloaded = open_project(path)
    assert reloaded.manifest["project_name"] == "Colegio Demo"
    assert "uuid" in reloaded.manifest
    assert reloaded.manifest["engine_signature"]["engine_version"] == engine_version()
    assert problem_to_dict(reloaded.problem) == problem_to_dict(problem)
    assert reloaded.constraints.plugins[0].id == "teacher_room_stability"
    assert reloaded.solver_config.default_solver == "highs"
    assert reloaded.solver_config.threads == 4
    assert reloaded.solution is not None
    assert solution_to_dict(reloaded.solution) == solution_to_dict(_solution())
    assert reloaded.metrics == {"quality_score": 96.5}
    assert reloaded.history == ({"solver": "ortools_cpsat", "quality_score": 96.5},)


def test_new_project_persiste_con_firma(tmp_path: Path) -> None:
    path = tmp_path / "nuevo.bjs"
    project = new_project(path, "Nuevo", _problem())
    assert path.exists()
    sig = project.manifest["engine_signature"]
    assert sig["engine_version"] == engine_version()
    assert "git_commit" in sig
    reloaded = open_project(path)
    assert reloaded.manifest["uuid"] == project.manifest["uuid"]


def test_escritura_atomica_no_deja_temporales(tmp_path: Path) -> None:
    path = tmp_path / "x.bjs"
    save_project(path, BjsProject.create("X", _problem()))
    save_project(path, BjsProject.create("X2", _problem()))
    assert open_project(path).manifest["project_name"] == "X2"
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*tmp*")) == []


def test_abrir_inexistente_o_incompleto_falla(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="no existe"):
        open_project(tmp_path / "fantasma.bjs")


def test_solution_opcional(tmp_path: Path) -> None:
    path = tmp_path / "sin_sol.bjs"
    save_project(path, BjsProject.create("SinSol", _problem()))
    reloaded = open_project(path)
    assert reloaded.solution is None
    assert reloaded.metrics is None
    assert reloaded.history == ()
    assert isinstance(reloaded.constraints, PluginsConfig)
