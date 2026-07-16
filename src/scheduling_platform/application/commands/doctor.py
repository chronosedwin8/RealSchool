"""Caso de uso ``doctor``: diagnóstico del entorno de ejecución.

Reporta versión de Python, hardware, paquetes clave y qué solvers (backends de
cálculo) están disponibles nativamente. Reutiliza la captura de contexto de la
Fase 1 (``Provenance``) y la resolución de solvers de la Capa de Aplicación.
"""

from __future__ import annotations

from typing import ClassVar

from ...benchmarks import Provenance
from ..context import AppContext
from ..solvers import SOLVER_NAMES, solver_factory_for
from .base import Command, CommandResult


def _available_solvers() -> dict[str, bool]:
    available: dict[str, bool] = {}
    for name in SOLVER_NAMES:
        try:
            solver_factory_for(name)()  # instanciar detecta si el backend existe
            available[name] = True
        except Exception:  # diagnóstico: cualquier fallo = backend no disponible
            available[name] = False
    return available


class DoctorCommand(Command):
    """Verifica el entorno: Python, hardware, paquetes y solvers disponibles."""

    name: ClassVar[str] = "doctor"

    def execute(self, ctx: AppContext) -> CommandResult:
        prov = Provenance.capture()
        solvers = _available_solvers()
        payload = {
            "python": prov.python_version,
            "os": prov.os,
            "cpu": prov.cpu,
            "cpu_cores": prov.cpu_cores,
            "ram_gb": prov.ram_total_gb,
            "packages": dict(prov.packages),
            "solvers": solvers,
        }
        messages = [
            f"Python {prov.python_version} · {prov.cpu_cores} hilos · {prov.ram_total_gb} GB"
        ]
        messages += [
            f"solver {name}: {'disponible' if ok else 'NO disponible'}"
            for name, ok in solvers.items()
        ]
        return CommandResult(payload=payload, messages=tuple(messages))
