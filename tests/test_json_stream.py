"""H12: eventos de progreso (--json-stream) y salida segura ante interrupción."""

from __future__ import annotations

import io
import json
from pathlib import Path

from scheduling_platform.application import (
    BjsProject,
    Command,
    CommandDispatcher,
    CommandResult,
    GenerateCommand,
    save_project,
)
from scheduling_platform.application.context import AppContext
from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.engine import SchedulingEngine
from scheduling_platform.pipeline.events import ProgressEvent
from scheduling_platform.plugins import registry_with
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.sal import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver


def _problem() -> SchedulingProblem:
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula", frozenset({"room"})),
        ),
        tasks=tuple(
            Task(
                TaskId(i),
                f"C{i}",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            )
            for i in range(2)
        ),
    )


# --- El seam on_event es opt-in y no cambia el comportamiento por defecto ---


def test_on_event_recibe_eventos_de_etapa() -> None:
    eventos: list[ProgressEvent] = []
    engine = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin()]),
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )
    result = engine.solve(_problem(), SolverConfig(random_seed=1), on_event=eventos.append)
    assert result.solved
    nombres = [e.event for e in eventos]
    assert "analysis_started" in nombres
    assert "solver_searching" in nombres
    assert "search_finished" in nombres
    assert eventos[-1].percentage == 100


def test_sin_on_event_sigue_funcionando() -> None:
    engine = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin()]),
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )
    assert engine.solve(_problem(), SolverConfig(random_seed=1)).solved  # on_event=None por defecto


# --- Enrutado del progreso según el modo ---


def _ctx(out: io.StringIO, err: io.StringIO, *, json_stream: bool) -> AppContext:
    from scheduling_platform.application.log import AppLogger

    return AppContext(
        out=out,
        err=err,
        logger=AppLogger(err),
        solver_factory=ORToolsSolver,
        json_stream=json_stream,
    )


def test_emit_progress_stream_va_a_stdout_jsonl() -> None:
    out, err = io.StringIO(), io.StringIO()
    _ctx(out, err, json_stream=True).emit_progress(
        ProgressEvent("solver_searching", "search", 60, {"gap": 0.1})
    )
    assert out.getvalue().strip() == json.dumps(
        {"event": "solver_searching", "stage": "search", "percentage": 60, "gap": 0.1}
    )
    assert err.getvalue() == ""  # nada por stderr en modo stream


def test_emit_progress_normal_va_a_stderr() -> None:
    out, err = io.StringIO(), io.StringIO()
    _ctx(out, err, json_stream=False).emit_progress(ProgressEvent("solver_searching", "search", 60))
    assert out.getvalue() == ""  # stdout limpio en modo normal (Zero-Leakage)
    assert "solver_searching" in err.getvalue()


# --- Dispatcher en modo stream ---


def test_dispatch_stream_emite_jsonl_y_evento_final(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    save_project(path, BjsProject.create("t", _problem()))
    out, err = io.StringIO(), io.StringIO()
    code = CommandDispatcher().dispatch(
        GenerateCommand(str(path), quick=True), out=out, err=err, json_stream=True
    )
    assert code == 0
    lines = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert all("event" in line for line in lines)  # stdout: SOLO JSONL
    assert lines[-1]["event"] == "completed"  # el último trae el resultado
    assert "quality_score" in lines[-1]["result"]


# --- Interrupción segura (SIGINT) ---


class _InterruptingCommand(Command):
    name = "boom"

    def execute(self, ctx: AppContext) -> CommandResult:
        raise KeyboardInterrupt


def test_interrupcion_sale_limpia_sin_stdout() -> None:
    out, err = io.StringIO(), io.StringIO()
    code = CommandDispatcher().dispatch(_InterruptingCommand(), out=out, err=err)
    assert code == 130  # convención POSIX para SIGINT
    assert out.getvalue() == ""  # nada por stdout
    assert "interrump" in err.getvalue().lower()
