"""CLI Typer ``schedule-engine`` (H5): parseo, dispatch y exit codes."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from scheduling_platform.application import ScheduleProject, save_project
from scheduling_platform.cli.main import app
from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)

runner = CliRunner()


def _problem() -> SchedulingProblem:
    # dos clases del mismo docente: activan el no-solape (modelo realista)
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula", frozenset({"room"})),
        ),
        tasks=tuple(
            Task(
                TaskId(i),
                f"Clase {i}",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            )
            for i in range(2)
        ),
    )


def test_doctor_reporta_solvers() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "solvers" in result.stdout
    assert "ortools_cpsat" in result.stdout


def test_convert_origen_inexistente_exit_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["convert", str(tmp_path / "no.xml"), str(tmp_path / "o.schedule")])
    assert result.exit_code == 1


def test_validate_proyecto_factible(tmp_path: Path) -> None:
    path = tmp_path / "p.schedule"
    save_project(path, ScheduleProject.create("t", _problem()))
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0
    assert "feasible" in result.stdout


def test_generate_desde_cli(tmp_path: Path) -> None:
    path = tmp_path / "p.schedule"
    save_project(path, ScheduleProject.create("t", _problem()))
    result = runner.invoke(app, ["generate", str(path), "--quick"])
    assert result.exit_code == 0
    assert "quality_score" in result.stdout


def test_ayuda_lista_los_comandos() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("convert", "generate", "optimize", "validate", "explain", "doctor"):
        assert cmd in result.stdout
