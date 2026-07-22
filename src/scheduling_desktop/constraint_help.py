"""Explicaciones en lenguaje sencillo de cada regla del horario (ayuda de la GUI).

El nombre y la descripción del catálogo del motor son técnicos; aquí se traducen a
algo que un profesor o coordinador entiende: un **nombre claro**, qué hace y un
ejemplo. Es texto de presentación (no lógica), indexado por el ``rule_id`` (nombre
del plugin).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConstraintHelp:
    """Ayuda amigable de una regla del horario."""

    title: str  # nombre claro para mostrar (en vez del técnico del catálogo)
    summary: str  # una línea, para el tooltip
    detail: str  # explicación con ejemplo, para el panel


_HELP: dict[str, ConstraintHelp] = {
    "room_capacity": ConstraintHelp(
        "El aula alcanza para el grupo",
        "El aula debe tener asientos suficientes para el grupo.",
        "Evita mandar un grupo a un aula demasiado pequeña.\n\n"
        "Ejemplo: un grupo de 30 estudiantes no cabe en un aula de 25 asientos.",
    ),
    "max_daily_load": ConstraintHelp(
        "Tope de clases por día",
        "Limita cuántas clases puede tener alguien en un mismo día.",
        "Impide sobrecargar un solo día a un docente o a un grupo.\n\n"
        "Ejemplo: que un docente no tenga más de 6 clases el mismo día.",
    ),
    "max_consecutive": ConstraintHelp(
        "No demasiadas clases seguidas",
        "Prohíbe muchas clases pegadas sin un respiro.",
        "Corta las 'maratones' de clases una tras otra.\n\n"
        "Ejemplo: un docente no puede tener más de 4 horas seguidas sin descanso.",
    ),
    "prefer_early_slots": ConstraintHelp(
        "Preferir las primeras horas",
        "Empuja las clases hacia la mañana cuando se puede.",
        "Coloca las clases más temprano si es posible. Es una preferencia, no una "
        "obligación.\n\nÚtil si se rinde más en las primeras horas.",
    ),
    "teacher_gaps": ConstraintHelp(
        "Menos horas libres sueltas",
        "Evita huecos: horas libres atrapadas entre dos clases.",
        "Reduce los 'huecos': una hora libre suelta entre dos clases del mismo "
        "docente o grupo.\n\nEjemplo: clase a 1ª y 3ª hora, con la 2ª libre = 1 hueco.",
    ),
    "task_continuity": ConstraintHelp(
        "Clases agrupadas, no dispersas",
        "Junta las clases en vez de repartirlas por todo el día.",
        "Prefiere las clases en bloques juntos, no salteadas.\n\n"
        "Ejemplo: dos clases seguidas mejor que dos con horas libres en medio.",
    ),
    "weekly_balance": ConstraintHelp(
        "Repartir la carga entre los días",
        "Reparte las clases pareja entre los días de la semana.",
        "Evita días muy cargados y días casi vacíos para un mismo grupo o docente.\n\n"
        "Ejemplo: mejor 4 clases el lunes y 4 el martes que 8 el lunes y 0 el martes.",
    ),
    "teacher_room_stability": ConstraintHelp(
        "El docente en su aula habitual",
        "Procura que el docente use siempre la misma aula.",
        "Menos cambios de aula = menos desplazamientos.\n\n"
        "Ejemplo: que un docente dé todas sus clases en el aula 101 en vez de rotar.",
    ),
    "daily_span": ConstraintHelp(
        "Jornada más corta",
        "Acorta el tramo de la primera a la última clase del día.",
        "Reduce la distancia entre la primera y la última clase del día.\n\n"
        "Ejemplo: mejor de 8 a 12 que de 8 a 16 con muchos huecos en medio.",
    ),
    "soft_max_consecutive": ConstraintHelp(
        "Evitar muchas clases seguidas",
        "Desanima (sin prohibir) las clases muy pegadas.",
        "Como el tope de clases seguidas, pero suave: intenta dar respiros cuando se "
        "puede, sin volver imposible el horario.",
    ),
    "subject_spread": ConstraintHelp(
        "Una hora de cada materia por día",
        "Reparte las horas de una materia en días distintos.",
        "Evita poner dos clases de la misma materia el mismo día en un grupo, para "
        "que queden repartidas en la semana.\n\n"
        "Ejemplo: 5 horas de Matemáticas quedan como 1 por día, no 3 el lunes.",
    ),
}

_DEFAULT = ConstraintHelp(
    "Regla del horario",
    "Ajusta cómo se arma el horario.",
    "Esta regla ajusta cómo se construye el horario. Actívala para que se tenga en "
    "cuenta y, si es una preferencia, sube su importancia para darle más peso.",
)


def constraint_help(rule_id: str) -> ConstraintHelp:
    """Ayuda amigable para una regla (o una genérica si no hay específica)."""
    return _HELP.get(rule_id, _DEFAULT)
