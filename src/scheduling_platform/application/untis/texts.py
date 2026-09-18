"""Textos de la ventana Ponderación: etiqueta es/de y ayuda de cada deslizador.

Redacción propia y genérica (el documento maestro prohíbe copiar textos de
Untis). La ayuda explica qué cuenta el evaluador de referencia como violación.
"""

from __future__ import annotations

from typing import Final

#: Pestaña -> (español, alemán).
TAB_LABELS: Final[dict[str, tuple[str, str]]] = {
    "teachers_1": ("Profesores 1", "Lehrer 1"),
    "teachers_2": ("Profesores 2", "Lehrer 2"),
    "classes": ("Clases", "Klassen"),
    "subjects": ("Materias", "Fächer"),
    "main_subjects": ("Materias principales", "Hauptfächer"),
    "rooms": ("Aulas", "Räume"),
    "period_distribution": ("Distribución de períodos", "Stundenverteilung"),
    "time_requests": ("Deseos de tiempo", "Zeitwünsche"),
    "analysis": ("Análisis", "Analyse"),
}

#: Criterio -> (etiqueta es, etiqueta de, ayuda es).
CRITERION_TEXTS: Final[dict[str, tuple[str, str, str]]] = {
    "teacher_gaps": (
        "Evitar huecos de profesores",
        "Hohlstunden der Lehrer vermeiden",
        "Cada período libre de un profesor entre dos clases del mismo día.",
    ),
    "teacher_gaps_per_day_max": (
        "Huecos por día (mín-máx)",
        "Hohlstunden pro Tag (min-max)",
        "Días en que los huecos del profesor salen del rango de su ficha.",
    ),
    "teacher_gaps_per_week_max": (
        "Huecos por semana (mín-máx)",
        "Hohlstunden pro Woche (min-max)",
        "Huecos semanales fuera del rango de la ficha del profesor.",
    ),
    "teacher_periods_per_day": (
        "Períodos por día (mín-máx)",
        "Stunden pro Tag (min-max)",
        "Períodos por encima o por debajo del rango diario del profesor.",
    ),
    "teacher_days_per_week_max": (
        "Días por semana (máx)",
        "Tage pro Woche (max)",
        "Días trabajados por encima del máximo del profesor.",
    ),
    "teacher_single_period_half_day": (
        "Un solo período en media jornada",
        "Einzelstunde im Halbtag",
        "Mañanas o tardes en las que el profesor viene para un único período.",
    ),
    "teacher_consecutive_max": (
        "Períodos seguidos (máx)",
        "Stunden hintereinander (max)",
        "Períodos seguidos por encima del máximo de la ficha del profesor.",
    ),
    "teacher_lunch_break": (
        "Almuerzo de profesores",
        "Mittagspause der Lehrer",
        "Días de mañana y tarde sin períodos libres en la franja del almuerzo.",
    ),
    "teacher_isolated_afternoon": (
        "Tarde con un solo período",
        "Nachmittag mit einer Stunde",
        "Tardes en las que el profesor tiene una única clase.",
    ),
    "teacher_load_balance": (
        "Carga diaria equilibrada",
        "Gleichmäßige Tagesbelastung",
        "Diferencia entre el día más cargado y el menos cargado del profesor.",
    ),
    "teacher_optimization": (
        "Optimización de profesores",
        "Lehreroptimierung",
        "Sesiones con líneas sin profesor asignado.",
    ),
    "class_gaps": (
        "Evitar huecos de clases",
        "Hohlstunden der Klassen vermeiden",
        "Cada período libre de una clase entre dos lecciones del mismo día.",
    ),
    "class_periods_per_day": (
        "Períodos por día de la clase (mín-máx)",
        "Stunden pro Tag der Klasse (min-max)",
        "Períodos fuera del rango diario de la ficha de la clase.",
    ),
    "class_lunch_break": (
        "Almuerzo de clases",
        "Mittagspause der Klassen",
        "Días de mañana y tarde sin descanso en la franja del almuerzo.",
    ),
    "class_afternoon_periods": (
        "Clases por la tarde",
        "Nachmittagsunterricht",
        "Tardes con clase, por clase y día.",
    ),
    "class_single_periods": (
        "Un solo período en media jornada (clase)",
        "Einzelstunde im Halbtag (Klasse)",
        "Mañanas o tardes de una clase con un único período.",
    ),
    "subject_double_periods": (
        "Períodos dobles",
        "Doppelstunden",
        "Dobles por debajo o por encima del rango pedido en la lección.",
    ),
    "subject_blocks": (
        "Bloques",
        "Blöcke",
        "Bloques de 3 o más períodos pedidos que no se consiguen.",
    ),
    "subject_not_same_day": (
        "No dos veces el mismo día",
        "Nicht zweimal am selben Tag",
        "Veces que una lección marcada aparece en tramos separados el mismo día.",
    ),
    "subject_not_consecutive_days": (
        "No en días seguidos",
        "Nicht an aufeinanderfolgenden Tagen",
        "Pares de días seguidos en los que aparece una lección marcada.",
    ),
    "subject_sequence": (
        "Secuencia de materias",
        "Fächerfolge",
        "Días en que una lección va antes que la materia que debe precederla.",
    ),
    "subject_required_room": (
        "Aula obligatoria de la materia",
        "Pflichtraum des Fachs",
        "Sesiones fuera del aula que exige su materia.",
    ),
    "main_subject_per_day_max": (
        "Materias principales por día (máx)",
        "Hauptfächer pro Tag (max)",
        "Períodos de materias principales por encima del máximo diario de la clase.",
    ),
    "main_subject_not_consecutive": (
        "Materias principales no seguidas",
        "Hauptfächer nicht hintereinander",
        "Dos materias principales distintas seguidas en una clase.",
    ),
    "main_subject_morning": (
        "Materias principales por la mañana",
        "Hauptfächer am Vormittag",
        "Sesiones de materias principales que caen por la tarde.",
    ),
    "subject_group_not_consecutive": (
        "Grupo de materias no seguido",
        "Fächergruppe nicht hintereinander",
        "Dos materias distintas del mismo grupo seguidas en una clase.",
    ),
    "room_optimization": (
        "Optimización de aulas",
        "Raumoptimierung",
        "Sesiones fuera del aula pedida y de su cadena de alternativas.",
    ),
    "room_capacity": (
        "Capacidad del aula",
        "Raumkapazität",
        "Sesiones con más alumnos que plazas del aula.",
    ),
    "room_alternative_chain": (
        "Cadena de aulas alternativas",
        "Ausweichraumkette",
        "Posición en la cadena de alternativas del aula usada (1 = primera).",
    ),
    "distribution_same_day": (
        "Misma materia el mismo día",
        "Gleiches Fach am selben Tag",
        "Tramos separados de la misma materia en una clase el mismo día.",
    ),
    "distribution_uniform_week": (
        "Reparto uniforme en la semana",
        "Gleichmäßige Wochenverteilung",
        "Días de menos respecto al mejor reparto posible de la lección.",
    ),
    "distribution_same_period_consecutive_days": (
        "Mismo período en días seguidos",
        "Gleiche Stunde an Folgetagen",
        "Veces que una lección repite período en días seguidos.",
    ),
    "distribution_first_last_period": (
        "Último período del día",
        "Letzte Stunde des Tages",
        "Días en que una clase ocupa el último período de su rejilla.",
    ),
    "time_request_teacher": (
        "Deseos de profesores",
        "Zeitwünsche der Lehrer",
        "Suma de |valor| de los deseos negativos de profesores ocupados.",
    ),
    "time_request_class": (
        "Deseos de clases",
        "Zeitwünsche der Klassen",
        "Suma de |valor| de los deseos negativos de clases ocupadas.",
    ),
    "time_request_room": (
        "Deseos de aulas",
        "Zeitwünsche der Räume",
        "Suma de |valor| de los deseos negativos de aulas ocupadas.",
    ),
    "time_request_subject": (
        "Deseos de materias",
        "Zeitwünsche der Fächer",
        "Suma de |valor| de los deseos negativos de materias colocadas.",
    ),
    "time_request_unspecified": (
        "Deseos no especificados",
        "Unspezifizierte Wünsche",
        "Días, mañanas o tardes libres pedidos que no se consiguen.",
    ),
}
