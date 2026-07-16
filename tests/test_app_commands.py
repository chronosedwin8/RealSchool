"""Casos de uso núcleo sobre el dispatcher: generate/optimize/validate/explain/convert."""

from __future__ import annotations

import io
import json
from pathlib import Path

from scheduling_platform.application import (
    ConvertCommand,
    ExplainCommand,
    GenerateCommand,
    OptimizeCommand,
    ScheduleProject,
    ValidateCommand,
    open_project,
    save_project,
)
from scheduling_platform.application.dispatcher import CommandDispatcher
from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)


def _feasible() -> SchedulingProblem:
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula 1", frozenset({"room"})),
            Resource(ResourceId(2), "Aula 2", frozenset({"room"})),
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


def _infeasible() -> SchedulingProblem:
    # una clase exige un recurso 'lab' que ningún recurso provee -> infactible pre-solver
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),),
        tasks=(
            Task(
                TaskId(0),
                "Quimica",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("lab")),
            ),
        ),
    )


def _make(path: Path, problem: SchedulingProblem, config: dict[str, object] | None = None) -> None:
    save_project(path, ScheduleProject.create("Demo", problem, config=config or {}))


def _run(command: object, **kw: object) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = CommandDispatcher().dispatch(command, out=out, err=err, **kw)  # type: ignore[arg-type]
    return code, out.getvalue(), err.getvalue()


# --- generate / optimize ---


def test_generate_produce_y_guarda_horario(tmp_path: Path) -> None:
    path = tmp_path / "p.schedule"
    _make(path, _feasible())
    code, out, _ = _run(GenerateCommand(str(path), quick=True))
    assert code == 0
    assert json.loads(out)["hard_violations"] == 0
    assert open_project(path).solution is not None  # persistido


def test_optimize_con_cpsat(tmp_path: Path) -> None:
    path = tmp_path / "p.schedule"
    _make(
        path,
        _feasible(),
        config={
            "engine": {"default_solver": "ortools_cpsat", "max_time_seconds": 10},
            "plugins": [{"id": "teacher_room_stability", "enabled": True, "weight": 1}],
        },
    )
    code, out, err = _run(OptimizeCommand(str(path)))
    assert code == 0
    payload = json.loads(out)
    assert payload["solver"] == "ortools_cpsat"
    assert "quality_score" in payload
    assert "optimizado" in err
    assert open_project(path).solution is not None


def test_generate_infactible_es_exit_2(tmp_path: Path) -> None:
    path = tmp_path / "bad.schedule"
    _make(path, _infeasible())
    code, out, err = _run(GenerateCommand(str(path)))
    assert code == 2
    assert out == ""  # nada por stdout ante fallo (excepción)
    assert "lab" in err or "unsatisf" in err.lower() or "requisito" in err.lower()


# --- validate / explain ---


def test_validate_factible_sin_solucion(tmp_path: Path) -> None:
    path = tmp_path / "p.schedule"
    _make(path, _feasible())
    code, out, _ = _run(ValidateCommand(str(path)))
    assert code == 0
    payload = json.loads(out)
    assert payload["feasible"] is True
    assert payload["has_solution"] is False


def test_validate_con_solucion_incluye_metricas(tmp_path: Path) -> None:
    path = tmp_path / "p.schedule"
    _make(path, _feasible())
    _run(GenerateCommand(str(path)))  # genera y guarda una solución
    code, out, _ = _run(ValidateCommand(str(path)))
    assert code == 0
    assert "metrics" in json.loads(out)


def test_validate_infactible_es_exit_2(tmp_path: Path) -> None:
    path = tmp_path / "bad.schedule"
    _make(path, _infeasible())
    code, out, err = _run(ValidateCommand(str(path)))
    assert code == 2
    assert out == ""
    assert err  # explicación en stderr


def test_explain_factible_sin_conflictos(tmp_path: Path) -> None:
    path = tmp_path / "p.schedule"
    _make(path, _feasible())
    code, out, _ = _run(ExplainCommand(str(path)))
    assert code == 0
    assert json.loads(out) == {"feasible": True, "issues": []}


def test_explain_infactible_devuelve_mapa(tmp_path: Path) -> None:
    path = tmp_path / "bad.schedule"
    _make(path, _infeasible())
    code, out, _ = _run(ExplainCommand(str(path)))
    assert code == 2  # infactible
    payload = json.loads(out)  # pero SÍ hay salida estructurada (para la GUI)
    assert payload["feasible"] is False
    assert len(payload["issues"]) >= 1
    assert "kind" in payload["issues"][0]


# --- convert (errores; el happy-path se prueba con datos reales aparte) ---


def test_convert_origen_inexistente_es_exit_1(tmp_path: Path) -> None:
    code, _out, err = _run(ConvertCommand(str(tmp_path / "no.xml"), str(tmp_path / "o.schedule")))
    assert code == 1
    assert "no existe" in err


def test_convert_formato_no_soportado_es_exit_1(tmp_path: Path) -> None:
    src = tmp_path / "x.csv"
    src.write_text("a,b,c", encoding="utf-8")
    code, _out, err = _run(ConvertCommand(str(src), str(tmp_path / "o.schedule")))
    assert code == 1
    assert "no soportado" in err
