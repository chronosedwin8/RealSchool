"""Puente `untis_model` -> motor canónico (ADR-034).

Es la **única** capa de producto autorizada a importar el motor congelado
(`core`, `engine`, `plugins`, ...), lo que verifica `tests/test_boundaries.py`.
Traduce el proyecto Untis a un `SchedulingProblem`, reconstruye horarios en
vocabulario Untis y compila la ponderación a términos de objetivo.
"""

from .clock import Clock
from .rebuild import Rebuilt, solution_to_timetable, timetable_to_solution
from .translate import (
    ResourceKind,
    SessionRef,
    Translation,
    UntisTranslator,
    is_duty,
    translate,
)

__all__ = [
    "Clock",
    "Rebuilt",
    "ResourceKind",
    "SessionRef",
    "Translation",
    "UntisTranslator",
    "is_duty",
    "solution_to_timetable",
    "timetable_to_solution",
    "translate",
]
