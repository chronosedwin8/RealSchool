"""Validación en dos fases del .bjs (B3): estructural + referencial + consistencia."""

from __future__ import annotations

from pathlib import Path

import pytest

from scheduling_platform.application import BjsProject, ConfigError, open_project, save_project
from scheduling_platform.application.bjs_validation import check_consistency, check_structure
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
from scheduling_platform.serialization.bjs import extract, pack_dir, read


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


# --- Fase estructural ---


def test_estructura_valida_pasa() -> None:
    check_structure(
        {
            "calendar.json": {"grid": {"segments": []}},
            "resources.json": {"resources": []},
            "tasks.json": {"tasks": []},
        }
    )


def test_falta_archivo_obligatorio() -> None:
    with pytest.raises(ConfigError, match="tasks"):
        check_structure({"calendar.json": {"grid": {}}, "resources.json": {"resources": []}})


def test_campo_de_tipo_incorrecto() -> None:
    with pytest.raises(ConfigError, match="resources"):
        check_structure(
            {
                "calendar.json": {"grid": {}},
                "resources.json": {"resources": "no-es-lista"},
                "tasks.json": {"tasks": []},
            }
        )


def test_estructura_corrupta_en_bjs_real_falla_al_abrir(tmp_path: Path) -> None:
    # extraer, corromper tasks.json (quitar el campo), re-empaquetar, abrir -> error claro
    path = tmp_path / "p.bjs"
    save_project(path, BjsProject.create("t", _problem()))
    src = tmp_path / "src"
    extract(path, src)
    (src / "tasks.json").write_text('{"otro": 1}', encoding="utf-8")
    roto = tmp_path / "roto.bjs"
    pack_dir(src, roto)
    # el contenedor sigue íntegro (checksums recomputados), pero la estructura falla
    assert read(roto)  # el ZIP se lee
    with pytest.raises(ConfigError, match="tasks"):
        open_project(roto)


# --- Fase referencial / consistencia ---


def test_consistencia_ok_sin_avisos() -> None:
    project = BjsProject.create("t", _problem())
    assert check_consistency(project) == ()


def test_solucion_con_tarea_inexistente_falla() -> None:
    project = BjsProject(
        manifest={},
        problem=_problem(),
        solution=Solution(
            assignments=(Assignment(TaskId(99), TimeSlotIndex(0), (ResourceId(0),)),),
            objective_value=0,
        ),
    )
    with pytest.raises(ConfigError, match="tarea inexistente"):
        check_consistency(project)


def test_solucion_con_recurso_inexistente_falla() -> None:
    project = BjsProject(
        manifest={},
        problem=_problem(),
        solution=Solution(
            assignments=(Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(77),)),),
            objective_value=0,
        ),
    )
    with pytest.raises(ConfigError, match="recurso inexistente"):
        check_consistency(project)


def test_aviso_de_recurso_sin_uso() -> None:
    # un docente cuyo tag no lo requiere ninguna tarea -> aviso blando
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(
            Resource(ResourceId(0), "Prof A", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Prof B ocioso", frozenset({"teacher", "teacher#9"})),
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
    warnings = check_consistency(BjsProject(manifest={}, problem=problem))
    assert any("teacher#9" in w for w in warnings)
