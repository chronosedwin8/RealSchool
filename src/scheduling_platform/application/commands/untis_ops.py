"""Casos de uso Untis sin interfaz: `solve` y `evaluate` (interfaz headless).

`schedule-engine solve PROYECTO --strategy B` ejecuta una estrategia del
diálogo de Optimización y guarda el resultado; `schedule-engine evaluate`
devuelve el número de evaluación y su desglose. Sirven para scripts, para la
integración con MiUntisWeb y para pruebas (sección 9 del documento maestro).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from ..context import AppContext
from ..errors import ConfigError, InfeasibleError
from ..untis import OptimizeProgress, OptimizeRequest, UntisService, UntisSession
from .base import Command, CommandResult

STRATEGIES = ("A", "B", "D", "E", "repair")


def _evaluation_payload(
    svc: UntisService, session: UntisSession, timetable_id: str | None
) -> dict[str, object]:
    vista = svc.evaluation(session, timetable_id)
    if vista is None:
        raise ConfigError("el proyecto no tiene ningún horario que evaluar")
    return {
        "timetable": vista.timetable_id,
        "total": vista.total,
        "soft_points": vista.soft_points,
        "unplaced_periods": vista.unplaced_periods,
        "clashes": vista.clashes,
        "criteria": [
            {
                "criterion": c.criterion,
                "tab": c.tab,
                "slider": c.slider,
                "weight": c.weight,
                "violations": c.violations,
                "points": c.points,
            }
            for c in vista.criteria
            if c.violations
        ],
    }


class SolveCommand(Command):
    """Ejecuta una estrategia (A/B/D/E/Reparar) y guarda el proyecto `.rsp`."""

    name: ClassVar[str] = "solve"

    def __init__(
        self,
        project: str,
        *,
        strategy: str = "A",
        time_limit: float | None = None,
        seed: int = 0,
        out: str | None = None,
        optimize_teachers: bool = False,
        polish: bool = True,
    ) -> None:
        self._project = project
        self._strategy = strategy
        self._time_limit = time_limit
        self._seed = seed
        self._out = out
        self._optimize_teachers = optimize_teachers
        self._polish = polish

    def execute(self, ctx: AppContext) -> CommandResult:
        if self._strategy not in STRATEGIES:
            raise ConfigError(f"estrategia desconocida: {self._strategy!r} (usa {STRATEGIES})")
        origen = Path(self._project)
        if not origen.exists():
            raise ConfigError(f"no existe el proyecto: {origen}")
        destino = Path(self._out) if self._out else origen.with_suffix(".rsp")

        svc = UntisService()
        try:
            sesion = svc.open(origen)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"no se pudo abrir {origen.name}: {exc}") from exc

        ultimo = [-1.0]

        def progreso(evento: OptimizeProgress) -> None:
            if evento.elapsed - ultimo[0] >= 2.0:
                ultimo[0] = evento.elapsed
                ctx.logger.info(
                    f"[{evento.elapsed:6.1f} s] {evento.phase}: mejor {evento.best} "
                    f"(sin colocar {evento.unplaced})"
                )

        resultado = svc.optimize(
            sesion,
            OptimizeRequest(
                strategy=self._strategy,
                time_limit=self._time_limit,
                seed=self._seed,
                optimize_teachers=self._optimize_teachers,
                polish=self._polish,
            ),
            on_progress=progreso,
        )
        if not resultado.ok:
            raise InfeasibleError(resultado.message)
        guardado = svc.save(sesion, destino)
        payload = {
            "saved": str(guardado),
            "strategy": self._strategy,
            "status": resultado.status,
            "elapsed": round(resultado.elapsed, 2),
            "log": list(resultado.log),
            **_evaluation_payload(svc, sesion, resultado.timetable_id),
        }
        return CommandResult(payload=payload, messages=(resultado.message,))


class EvaluateCommand(Command):
    """Número de evaluación y desglose del horario activo (o del indicado)."""

    name: ClassVar[str] = "evaluate"

    def __init__(self, project: str, *, timetable: str | None = None) -> None:
        self._project = project
        self._timetable = timetable

    def execute(self, ctx: AppContext) -> CommandResult:
        origen = Path(self._project)
        if not origen.exists():
            raise ConfigError(f"no existe el proyecto: {origen}")
        svc = UntisService()
        try:
            sesion = svc.open(origen)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"no se pudo abrir {origen.name}: {exc}") from exc
        payload = _evaluation_payload(svc, sesion, self._timetable)
        return CommandResult(payload=payload, messages=(f"evaluación: {payload['total']}",))
