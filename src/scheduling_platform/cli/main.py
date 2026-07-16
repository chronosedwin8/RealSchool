"""Punto de entrada de la CLI ``schedule-engine`` (Typer).

Capa de entrada delgada: parsea argumentos, construye el ``Command`` adecuado y
lo entrega al ``CommandDispatcher``, que respeta el contrato de streams (datos por
``stdout``, logs por ``stderr``) y devuelve el exit code. La CLI **no** contiene
lógica de negocio: toda operación vive en la Capa de Aplicación.
"""

from __future__ import annotations

import contextlib
import signal
import sys
from types import FrameType

import typer

from ..application import (
    Command,
    CommandDispatcher,
    ConfigValidateCommand,
    ConvertCommand,
    DoctorCommand,
    ExplainCommand,
    GenerateCommand,
    OptimizeCommand,
    ValidateCommand,
)

app = typer.Typer(
    add_completion=True,
    no_args_is_help=True,
    help="Motor de calendarización headless. Datos por stdout, logs por stderr.",
)
config_app = typer.Typer(no_args_is_help=True, help="Gestión de configuración.")
app.add_typer(config_app, name="config")

_FORMAT = typer.Option("json", "--format", "-f", help="Formato de salida: json | yaml | markdown.")


def _raise_interrupt(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


@app.callback()
def _bootstrap() -> None:
    # SIGTERM se comporta como Ctrl+C: el dispatcher lo intercepta y sale limpio
    # (exit 130) sin corromper el proyecto (escritura atómica, H2).
    with contextlib.suppress(ValueError, OSError, AttributeError):
        signal.signal(signal.SIGTERM, _raise_interrupt)


def _run(command: Command, output_format: str, *, json_stream: bool = False) -> None:
    code = CommandDispatcher().dispatch(
        command,
        out=sys.stdout,
        err=sys.stderr,
        output_format=output_format,
        json_stream=json_stream,
    )
    raise typer.Exit(code)


@app.command()
def convert(
    source: str,
    dest: str,
    name: str | None = typer.Option(
        None, help="Nombre del proyecto (por defecto, el del archivo)."
    ),
    output_format: str = _FORMAT,
) -> None:
    """Importa un origen externo (Untis XML) a un proyecto .schedule."""
    _run(ConvertCommand(source, dest, name=name), output_format)


@app.command()
def generate(
    project: str,
    quick: bool = typer.Option(False, "--quick", help="Primera solución factible."),
    timeout: float | None = typer.Option(None, help="Límite de tiempo (s)."),
    json_stream: bool = typer.Option(
        False, "--json-stream", help="Progreso JSONL en vivo por stdout."
    ),
    output_format: str = _FORMAT,
) -> None:
    """Genera un horario factible y lo guarda en el proyecto."""
    _run(
        GenerateCommand(project, quick=quick, timeout=timeout),
        output_format,
        json_stream=json_stream,
    )


@app.command()
def optimize(
    project: str,
    solver: str | None = typer.Option(None, help="Backend: ortools_cpsat | cbc | scip | highs."),
    seed: int | None = typer.Option(None, help="Semilla del solver."),
    timeout: float | None = typer.Option(None, help="Límite de tiempo (s)."),
    json_stream: bool = typer.Option(
        False, "--json-stream", help="Progreso JSONL en vivo por stdout."
    ),
    output_format: str = _FORMAT,
) -> None:
    """Optimiza el horario con las reglas configuradas y lo guarda."""
    _run(
        OptimizeCommand(project, solver=solver, seed=seed, timeout=timeout),
        output_format,
        json_stream=json_stream,
    )


@app.command()
def validate(
    project: str,
    strict: bool = typer.Option(False, "--strict", help="Falla si hay violaciones duras."),
    output_format: str = _FORMAT,
) -> None:
    """Valida el proyecto: resumen si es factible, explicación si no."""
    _run(ValidateCommand(project, strict=strict), output_format)


@app.command()
def explain(project: str, output_format: str = _FORMAT) -> None:
    """Devuelve el mapa de conflictos estructurales (Explain Engine)."""
    _run(ExplainCommand(project), output_format)


@app.command()
def doctor(output_format: str = _FORMAT) -> None:
    """Diagnostica el entorno: Python, hardware y solvers disponibles."""
    _run(DoctorCommand(), output_format)


@config_app.command("validate")
def config_validate(
    engine: str | None = typer.Option(None, help="Ruta de engine.yaml."),
    plugins: str | None = typer.Option(None, help="Ruta de plugins.yaml."),
    output_format: str = _FORMAT,
) -> None:
    """Valida engine.yaml / plugins.yaml contra el catálogo."""
    _run(ConfigValidateCommand(engine, plugins), output_format)


if __name__ == "__main__":
    app()
