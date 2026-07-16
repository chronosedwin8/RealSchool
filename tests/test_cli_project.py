"""Subcomando ``project`` de la CLI (B4): info/validate/extract/pack."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from scheduling_platform.application import BjsProject, new_project, save_project
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


def _make(path: Path) -> None:
    save_project(path, BjsProject.create("Colegio Demo", _problem()))


def test_project_info(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    result = runner.invoke(app, ["project", "info", str(path)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["project_name"] == "Colegio Demo"
    assert payload["has_solution"] is False
    assert "engine_signature" in payload


def test_project_validate_ok(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    result = runner.invoke(app, ["project", "validate", str(path)])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["valid"] is True


def test_project_validate_bjs_inexistente_exit_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["project", "validate", str(tmp_path / "no.bjs")])
    assert result.exit_code == 1


def test_extract_editar_pack_validate_cierra_ciclo(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    out = tmp_path / "src"
    assert runner.invoke(app, ["project", "extract", str(path), "--out", str(out)]).exit_code == 0
    assert (out / "manifest.json").exists()
    assert (out / "tasks.json").exists()

    # editar un JSON extraído (renombrar el proyecto en el manifest)
    manifest_file = out / "manifest.json"
    doc = json.loads(manifest_file.read_text(encoding="utf-8"))
    doc["project_name"] = "Editado"
    manifest_file.write_text(json.dumps(doc), encoding="utf-8")

    nuevo = tmp_path / "nuevo.bjs"
    assert runner.invoke(app, ["project", "pack", str(out), "--out", str(nuevo)]).exit_code == 0
    info = runner.invoke(app, ["project", "info", str(nuevo)])
    assert info.exit_code == 0
    assert json.loads(info.stdout)["project_name"] == "Editado"


def test_pack_de_directorio_corrupto_exit_1(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    out = tmp_path / "src"
    runner.invoke(app, ["project", "extract", str(path), "--out", str(out)])
    # corromper la estructura: dejar tasks.json sin su campo
    (out / "tasks.json").write_text('{"nada": 1}', encoding="utf-8")
    nuevo = tmp_path / "roto.bjs"
    result = runner.invoke(app, ["project", "pack", str(out), "--out", str(nuevo)])
    assert result.exit_code == 1  # pack valida el resultado y detecta la estructura rota


def test_project_validate_strict_falla_con_avisos(tmp_path: Path) -> None:
    # un docente ocioso genera un aviso; con --strict, el aviso es error
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(
            Resource(ResourceId(0), "Prof A", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Prof ocioso", frozenset({"teacher", "teacher#9"})),
            Resource(ResourceId(2), "Aula", frozenset({"room"})),
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
    path = tmp_path / "avisos.bjs"
    new_project(path, "Avisos", problem)
    assert runner.invoke(app, ["project", "validate", str(path)]).exit_code == 0
    assert runner.invoke(app, ["project", "validate", str(path), "--strict"]).exit_code == 1
