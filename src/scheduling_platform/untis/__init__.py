"""Importador de exports reales de Untis (dataset DS-04, Colegio Alemán).

Lee el XML nativo de Untis, lo traduce al Modelo Canónico y reconstruye también
**el horario que Untis generó**, para poder compararlo con el nuestro usando la
misma vara de medir (Gap Analysis).
"""

from __future__ import annotations

from .adapter import (
    Coupling,
    UntisToCanonicalAdapter,
    UntisTranslation,
    untis_reference_solution,
)
from .parser import (
    UntisClass,
    UntisExport,
    UntisLesson,
    UntisRoom,
    UntisSubject,
    UntisTeacher,
    UntisTime,
    parse_untis,
)

__all__ = [
    "Coupling",
    "UntisClass",
    "UntisExport",
    "UntisLesson",
    "UntisRoom",
    "UntisSubject",
    "UntisTeacher",
    "UntisTime",
    "UntisToCanonicalAdapter",
    "UntisTranslation",
    "parse_untis",
    "untis_reference_solution",
]
