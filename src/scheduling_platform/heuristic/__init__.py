"""Generador heurístico de horarios (fases 1 y 2 del esquema de Untis).

Fase 1: colocación por dificultad; fase 2: intercambios con recocido simulado
sobre el número de evaluación exacto de `untis_model.evaluation`, calculado de
forma incremental. Solo depende de `untis_model`: el pulido CP-SAT (fase 3) lo
orquesta `bridge` con el horario que devuelve `optimize`.

Uso::

    from scheduling_platform.heuristic import Strategy, optimize

    resultado = optimize(proyecto, strategy=Strategy.A, time_limit=30)
    resultado.timetable, resultado.evaluation.total, resultado.unplaced
"""

from .incremental import State
from .model import Model, build_model
from .strategies import (
    DEFAULT_TIME,
    HeuristicResult,
    Progress,
    Strategy,
    optimize,
    repair_change_penalty,
)

__all__ = [
    "DEFAULT_TIME",
    "HeuristicResult",
    "Model",
    "Progress",
    "State",
    "Strategy",
    "build_model",
    "optimize",
    "repair_change_penalty",
]
