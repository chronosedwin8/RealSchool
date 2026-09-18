"""Ponderación (Wichtung): los deslizadores 0-5 que gobiernan el objetivo.

Sustituye a los pesos por plugin de `engine.yaml`. El usuario nunca ve un id
`HC-07` ni `SC-04`: ve las mismas nueve pestañas que Untis. La escala a peso real
es no lineal porque Untis advierte de que el salto de 4 a 5 es enorme.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Final

#: Deslizador 0-5 → peso del objetivo. Calibrable en la pestaña Análisis.
SLIDER_WEIGHTS: Final[tuple[int, ...]] = (0, 1, 3, 10, 30, 300)

SLIDER_MIN: Final = 0
SLIDER_MAX: Final = 5

#: Un período sin colocar domina cualquier violación blanda, como en Untis.
UNPLACED_PENALTY: Final = 100_000
#: Un choque duro (o un deseo -3/+3 roto) pesa como un período sin colocar.
CLASH_PENALTY: Final = UNPLACED_PENALTY


def slider_to_weight(slider: int) -> int:
    """Traduce un deslizador 0-5 al peso que usa el objetivo."""
    if not SLIDER_MIN <= slider <= SLIDER_MAX:
        raise ValueError(f"Deslizador fuera de 0-5: {slider}")
    return SLIDER_WEIGHTS[slider]


class WeightingTab(StrEnum):
    """Las nueve pestañas del diálogo de ponderación."""

    TEACHERS_1 = "teachers_1"
    TEACHERS_2 = "teachers_2"
    CLASSES = "classes"
    SUBJECTS = "subjects"
    MAIN_SUBJECTS = "main_subjects"
    ROOMS = "rooms"
    PERIOD_DISTRIBUTION = "period_distribution"
    TIME_REQUESTS = "time_requests"
    ANALYSIS = "analysis"


@dataclass(frozen=True, slots=True)
class Weighting:
    """Los deslizadores 0-5, agrupados por pestaña.

    Los valores por defecto replican una instalación de Untis recién creada:
    ni todo a 0 (el motor no optimizaría nada) ni todo a 5 (Untis advierte de
    que como mucho cuatro criterios deberían estar en 4, y el 5 de uno en uno).
    """

    # --- Profesores 1 ---------------------------------------------------- #
    teacher_gaps: int = 4
    teacher_gaps_per_day_max: int = 3
    teacher_gaps_per_week_max: int = 2
    teacher_periods_per_day: int = 3
    teacher_days_per_week_max: int = 3
    teacher_single_period_half_day: int = 2

    # --- Profesores 2 ---------------------------------------------------- #
    teacher_consecutive_max: int = 3
    teacher_lunch_break: int = 3
    teacher_isolated_afternoon: int = 2
    teacher_load_balance: int = 2
    teacher_optimization: int = 2

    # --- Clases ----------------------------------------------------------- #
    class_gaps: int = 5
    class_periods_per_day: int = 4
    class_lunch_break: int = 3
    class_afternoon_periods: int = 2
    class_single_periods: int = 2

    # --- Materias ---------------------------------------------------------- #
    subject_double_periods: int = 4
    subject_blocks: int = 4
    subject_not_same_day: int = 3
    subject_not_consecutive_days: int = 1
    subject_sequence: int = 2
    subject_required_room: int = 4

    # --- Materias principales --------------------------------------------- #
    main_subject_per_day_max: int = 3
    main_subject_not_consecutive: int = 2
    main_subject_morning: int = 3
    subject_group_not_consecutive: int = 1

    # --- Aulas -------------------------------------------------------------- #
    room_optimization: int = 3
    room_capacity: int = 3
    room_alternative_chain: int = 2

    # --- Distribución de períodos ----------------------------------------- #
    distribution_same_day: int = 3
    distribution_uniform_week: int = 3
    distribution_same_period_consecutive_days: int = 1
    distribution_first_last_period: int = 2

    # --- Deseos de tiempo -------------------------------------------------- #
    time_request_teacher: int = 4
    time_request_class: int = 4
    time_request_room: int = 2
    time_request_subject: int = 2
    time_request_unspecified: int = 3

    def __post_init__(self) -> None:
        for f in fields(self):
            valor = getattr(self, f.name)
            if not SLIDER_MIN <= valor <= SLIDER_MAX:
                raise ValueError(f"Ponderación {f.name!r} fuera de 0-5: {valor}")

    def weight(self, criterion: str) -> int:
        """Peso efectivo del criterio `criterion`."""
        if not hasattr(self, criterion):
            raise KeyError(f"Criterio de ponderación desconocido: {criterion!r}")
        valor: int = getattr(self, criterion)
        return slider_to_weight(valor)

    def as_dict(self) -> dict[str, int]:
        """Todos los deslizadores como diccionario `criterio → 0-5`."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def criteria(cls) -> tuple[str, ...]:
        """Nombres de todos los criterios ponderables."""
        return tuple(f.name for f in fields(cls))

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> Weighting:
        """Reconstruye una ponderación ignorando criterios desconocidos."""
        validos = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in validos})


#: Pestaña a la que pertenece cada criterio, para pintar el diálogo y el Análisis.
TAB_OF_CRITERION: Final[dict[str, WeightingTab]] = {
    "teacher_gaps": WeightingTab.TEACHERS_1,
    "teacher_gaps_per_day_max": WeightingTab.TEACHERS_1,
    "teacher_gaps_per_week_max": WeightingTab.TEACHERS_1,
    "teacher_periods_per_day": WeightingTab.TEACHERS_1,
    "teacher_days_per_week_max": WeightingTab.TEACHERS_1,
    "teacher_single_period_half_day": WeightingTab.TEACHERS_1,
    "teacher_consecutive_max": WeightingTab.TEACHERS_2,
    "teacher_lunch_break": WeightingTab.TEACHERS_2,
    "teacher_isolated_afternoon": WeightingTab.TEACHERS_2,
    "teacher_load_balance": WeightingTab.TEACHERS_2,
    "teacher_optimization": WeightingTab.TEACHERS_2,
    "class_gaps": WeightingTab.CLASSES,
    "class_periods_per_day": WeightingTab.CLASSES,
    "class_lunch_break": WeightingTab.CLASSES,
    "class_afternoon_periods": WeightingTab.CLASSES,
    "class_single_periods": WeightingTab.CLASSES,
    "subject_double_periods": WeightingTab.SUBJECTS,
    "subject_blocks": WeightingTab.SUBJECTS,
    "subject_not_same_day": WeightingTab.SUBJECTS,
    "subject_not_consecutive_days": WeightingTab.SUBJECTS,
    "subject_sequence": WeightingTab.SUBJECTS,
    "subject_required_room": WeightingTab.SUBJECTS,
    "main_subject_per_day_max": WeightingTab.MAIN_SUBJECTS,
    "main_subject_not_consecutive": WeightingTab.MAIN_SUBJECTS,
    "main_subject_morning": WeightingTab.MAIN_SUBJECTS,
    "subject_group_not_consecutive": WeightingTab.MAIN_SUBJECTS,
    "room_optimization": WeightingTab.ROOMS,
    "room_capacity": WeightingTab.ROOMS,
    "room_alternative_chain": WeightingTab.ROOMS,
    "distribution_same_day": WeightingTab.PERIOD_DISTRIBUTION,
    "distribution_uniform_week": WeightingTab.PERIOD_DISTRIBUTION,
    "distribution_same_period_consecutive_days": WeightingTab.PERIOD_DISTRIBUTION,
    "distribution_first_last_period": WeightingTab.PERIOD_DISTRIBUTION,
    "time_request_teacher": WeightingTab.TIME_REQUESTS,
    "time_request_class": WeightingTab.TIME_REQUESTS,
    "time_request_room": WeightingTab.TIME_REQUESTS,
    "time_request_subject": WeightingTab.TIME_REQUESTS,
    "time_request_unspecified": WeightingTab.TIME_REQUESTS,
}
