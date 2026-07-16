"""Capa de Aplicación: dispatcher, contrato de streams y exit codes (H1)."""

from __future__ import annotations

import io
import json

from scheduling_platform.application import (
    AppContext,
    Command,
    CommandDispatcher,
    CommandResult,
    InfeasibleError,
)
from scheduling_platform.sal.ortools_solver import ORToolsSolver


class _EchoCommand(Command):
    name = "echo"

    def __init__(
        self,
        payload: object = None,
        raises: Exception | None = None,
        messages: tuple[str, ...] = (),
    ) -> None:
        self._payload = payload
        self._raises = raises
        self._messages = messages

    def execute(self, ctx: AppContext) -> CommandResult:
        if self._raises is not None:
            raise self._raises
        return CommandResult(payload=self._payload, messages=self._messages)


class _CapturesSolver(Command):
    name = "solver"

    def __init__(self) -> None:
        self.seen: object = None

    def execute(self, ctx: AppContext) -> CommandResult:
        self.seen = ctx.solver_factory
        return CommandResult()


def _run(command: Command, **kwargs: object) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = CommandDispatcher().dispatch(command, out=out, err=err, **kwargs)  # type: ignore[arg-type]
    return code, out.getvalue(), err.getvalue()


def test_payload_va_a_stdout_y_nada_de_ruido() -> None:
    code, out, err = _run(_EchoCommand(payload={"score": 94.2}, messages=("calculando...",)))
    assert code == 0
    assert json.loads(out) == {"score": 94.2}  # stdout: SOLO el dato estructurado
    assert "calculando" in err  # los mensajes humanos van a stderr
    assert "calculando" not in out  # invariante Zero-Leakage


def test_error_de_aplicacion_mapea_a_su_exit_code() -> None:
    code, out, err = _run(_EchoCommand(raises=InfeasibleError("sin solución")))
    assert code == 2  # InfeasibleError -> exit 2
    assert out == ""  # nada por stdout ante un fallo
    assert "sin solución" in err


def test_error_inesperado_es_exit_4() -> None:
    code, _out, err = _run(_EchoCommand(raises=RuntimeError("boom")))
    assert code == 4
    assert "boom" in err


def test_formato_yaml() -> None:
    code, out, _ = _run(_EchoCommand(payload={"a": 1}), output_format="yaml")
    assert code == 0
    assert "a: 1" in out


def test_formato_no_soportado_es_exit_1() -> None:
    code, out, err = _run(_EchoCommand(payload={"a": 1}), output_format="xml")
    assert code == 1
    assert out == ""
    assert "no soportado" in err


def test_inyeccion_de_dependencias_del_solver() -> None:
    command = _CapturesSolver()
    out, err = io.StringIO(), io.StringIO()
    CommandDispatcher(solver_factory=ORToolsSolver).dispatch(command, out=out, err=err)
    assert command.seen is ORToolsSolver


def test_sin_payload_no_escribe_stdout() -> None:
    code, out, err = _run(_EchoCommand(payload=None, messages=("hecho",)))
    assert code == 0
    assert out == ""
    assert "hecho" in err
