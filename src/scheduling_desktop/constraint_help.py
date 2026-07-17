"""Explicaciones en lenguaje sencillo de cada restricción (ayuda de la GUI).

La descripción del catálogo del motor es técnica; aquí se traduce a algo que un
coordinador entiende: qué hace, por qué importa y un ejemplo. Es texto de ayuda
de presentación (no lógica), indexado por el ``rule_id`` (nombre del plugin).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConstraintHelp:
    """Ayuda amigable de una restricción."""

    summary: str  # una línea, para el tooltip
    detail: str  # explicación con ejemplo, para el panel


_HELP: dict[str, ConstraintHelp] = {
    "room_capacity": ConstraintHelp(
        "El aula debe tener cupos suficientes para el grupo.",
        "Evita asignar un grupo a un aula demasiado pequeña.\n\n"
        "Ejemplo: un grupo de 30 estudiantes no puede ir a un aula de 25 asientos.",
    ),
    "max_daily_load": ConstraintHelp(
        "Limita las horas de clase por día de un docente o grupo.",
        "Impide sobrecargar un solo día.\n\n"
        "Ejemplo: que un docente no tenga más de 6 clases el mismo día.",
    ),
    "max_consecutive": ConstraintHelp(
        "Prohíbe demasiadas clases seguidas sin descanso.",
        "Corta las 'maratones' de clases pegadas.\n\n"
        "Ejemplo: un docente no puede tener más de 4 períodos seguidos sin un respiro.",
    ),
    "prefer_early_slots": ConstraintHelp(
        "Prefiere las primeras horas del día.",
        "Empuja las clases hacia la mañana cuando es posible.\n\n"
        "Útil si rinde más temprano; es una preferencia, no una obligación.",
    ),
    "teacher_gaps": ConstraintHelp(
        "Evita las horas libres sueltas entre clases (huecos).",
        "Reduce los 'huecos': períodos libres atrapados entre dos clases del "
        "mismo docente o grupo.\n\n"
        "Ejemplo: clase a 1ª y 3ª hora, con la 2ª libre = 1 hueco a evitar.",
    ),
    "task_continuity": ConstraintHelp(
        "Agrupa las clases para que no queden fragmentadas.",
        "Prefiere bloques de clase juntos en vez de repartidos por todo el día.\n\n"
        "Ejemplo: dos clases seguidas mejor que dos clases con horas sueltas en medio.",
    ),
    "weekly_balance": ConstraintHelp(
        "Reparte la carga pareja entre los días.",
        "Evita días muy cargados y días casi vacíos para un mismo recurso.\n\n"
        "Ejemplo: mejor 4 clases lunes y 4 martes que 8 el lunes y 0 el martes.",
    ),
    "teacher_room_stability": ConstraintHelp(
        "Procura que el docente use siempre la misma aula.",
        "Menos cambios de aula = menos desplazamientos y montaje.\n\n"
        "Ejemplo: que un docente dé todas sus clases en el aula 101 en vez de rotar.",
    ),
    "daily_span": ConstraintHelp(
        "Acorta la jornada diaria (primera a última clase).",
        "Reduce la distancia entre la primera y la última clase del día.\n\n"
        "Ejemplo: mejor de 8 a 12 que de 8 a 16 con muchos huecos en medio.",
    ),
    "soft_max_consecutive": ConstraintHelp(
        "Desincentiva (sin prohibir) muchas clases seguidas.",
        "Como el máximo de consecutivas, pero blando: penaliza los excesos en vez "
        "de prohibirlos, para dar respiros cuando se pueda.",
    ),
}

_DEFAULT = ConstraintHelp(
    "Regla del motor de horarios.",
    "Esta regla ajusta cómo el motor construye el horario. Actívala para que la "
    "tenga en cuenta y, si es blanda, sube su peso para darle más importancia.",
)


def constraint_help(rule_id: str) -> ConstraintHelp:
    """Ayuda amigable para una restricción (o una genérica si no hay específica)."""
    return _HELP.get(rule_id, _DEFAULT)
