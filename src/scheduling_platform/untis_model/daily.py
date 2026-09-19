"""Del horario semanal al día concreto: quién falta y quién lo cubre.

El horario de Untis es **semanal** (día de la semana x hora), pero una ausencia
es de **fechas** ("Ana falta del 3 al 7 de octubre, de la 3ª a la 6ª hora").
Este módulo hace el puente, en lógica pura y sin dependencias nuevas:

- `day_lessons`: qué clases se dan una fecha concreta.
- `affected`: cuáles de ellas toca alguna ausencia, y por qué.
- `candidates`: quién puede cubrir una de ellas, de mejor a peor.
- `counters`: cuántas sustituciones lleva cada profesor.

Reglas del paso semana -> día
-----------------------------

1. Un día festivo (`UntisProject.is_holiday`) no tiene ninguna clase.
2. El día de la semana sale de la fecha (`weekday_of`, 1 = lunes), que es el
   `day` con el que están colocadas las asignaciones del horario.
3. Una lección marcada "ignorar" no se da nunca.
4. Se respetan las fechas de validez de la lección (`effective_begin` /
   `effective_end`) y, si la lección pertenece a un período lectivo, las fechas
   de ese período: fuera de ellas la lección no se da ese día.
5. Las líneas acopladas de una misma lección colocadas en la misma hora son
   **una sola** clase del día: sus profesores, clases y aulas se juntan.

Reglas de la resolución de ausencias
------------------------------------

Una ausencia puede ser de un profesor, de una clase o de un aula, y acota horas
solo en su primer y su último día (ver `Absence.covers`). Una clase del día está
**afectada** si alguna ausencia vigente a esa hora toca a uno de sus profesores,
a una de sus clases o a una de sus aulas.

Criterios del orden de candidatos
---------------------------------

Los candidatos se ordenan de mejor a peor por estos criterios, **en este orden**
(el primero que los distinga manda; ver `Candidate.score`):

a) **Libre y no ausente**: no es un criterio de orden sino un filtro duro. Quien
   a esa hora tiene clase, guardia de recreo o ya está puesto como sustituto,
   quien está ausente y quien tiene la reserva de sustitución al máximo
   (`LOCK_NEVER`) **no se propone nunca**.
b) **Ya está en el colegio** ese día (tiene clase, guardia de recreo o una
   sustitución antes o después) frente a quien tendría que venir solo para esto.
c) **Conoce el trabajo**: da esa materia a alguien, o da clase a alguno de los
   grupos afectados.
d) **Menos sustituciones acumuladas** en el contador (`COUNTER_SIGN`).
e) **Menos reserva de sustitución** (`Teacher.substitution_lock`): 1-8 solo
   penalizan el orden (cuanto más alta, más atrás); 9 lo deja fuera.

Las guardias de recreo (`UntisProject.supervisions`) se comparan por número de
período: en la rejilla de tiempo los recreos son períodos propios, con su propio
número, igual que las horas lectivas.

A igualdad de todo, manda el id del profesor, para que el orden sea siempre el
mismo con los mismos datos.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .common import EntityKind
from .lessons import Lesson
from .project import UntisProject
from .substitution import COUNTER_SIGN, Absence, weekday_of
from .timetable import Assignment, Timetable

#: Puntos del criterio (b): ya está en el colegio ese día.
SCORE_AT_SCHOOL = 100_000
#: Puntos del criterio (c): da la materia o da clase al grupo.
SCORE_KNOWS = 10_000
#: Tope del contador al puntuar, para que el criterio (d) nunca invada al (c).
COUNTER_CAP = 99
#: Puntos que resta cada sustitución acumulada (criterio d).
SCORE_PER_SUBSTITUTION = 10
#: Reserva de sustitución máxima (`Teacher.substitution_lock`).
LOCK_MAX = 9
#: Reserva que significa "no proponerlo nunca": filtro duro, no penalización.
LOCK_NEVER = 9


@dataclass(frozen=True, slots=True)
class DayLesson:
    """Una clase concreta de un día: la celda del horario llevada a la fecha."""

    date: str
    """Fecha `AAAAMMDD`."""
    day: int
    """Día de la semana (1 = lunes), el del horario semanal."""
    period: int
    lesson_number: int
    subject: str
    teachers: tuple[str, ...] = field(default_factory=tuple)
    classes: tuple[str, ...] = field(default_factory=tuple)
    rooms: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> tuple[str, int, int]:
        """Identidad de la clase del día: fecha, hora y lección."""
        return (self.date, self.period, self.lesson_number)


@dataclass(frozen=True, slots=True)
class AffectedLesson:
    """Una clase del día tocada por una o varias ausencias, con el motivo."""

    lesson: DayLesson
    absences: tuple[str, ...] = field(default_factory=tuple)
    """Ids de las ausencias que la tocan."""
    teachers: tuple[str, ...] = field(default_factory=tuple)
    """Profesores de la clase que faltan."""
    classes: tuple[str, ...] = field(default_factory=tuple)
    """Clases que no asisten."""
    rooms: tuple[str, ...] = field(default_factory=tuple)
    """Aulas que no están disponibles."""
    reason: str = ""
    """Por qué está afectada, en una frase corta en español."""

    @property
    def teacher_missing(self) -> bool:
        """`True` si lo que falta es (al menos) un profesor: hay que sustituir."""
        return bool(self.teachers)


@dataclass(frozen=True, slots=True)
class Candidate:
    """Un profesor que podría cubrir una clase, con su puntuación y su razón."""

    teacher: str
    score: int
    reason: str
    at_school: bool = False
    """Ya tiene clase o guardia ese día (criterio b)."""
    knows: bool = False
    """Da la materia o da clase a alguno de los grupos (criterio c)."""
    teaches_subject: bool = False
    teaches_class: bool = False
    counter: int = 0
    """Sustituciones que lleva acumuladas (criterio d)."""
    lock: int = 0
    """Reserva de sustitución 0-9 (criterio e)."""


# --------------------------------------------------------------------------- #
# Del horario semanal al día
# --------------------------------------------------------------------------- #


def _in_effect(project: UntisProject, lesson: Lesson, fecha: str) -> bool:
    """`True` si la lección rige esa fecha (fechas de validez y período lectivo)."""
    if lesson.effective_begin and fecha < lesson.effective_begin:
        return False
    if lesson.effective_end and fecha > lesson.effective_end:
        return False
    if not lesson.term:
        return True
    periodo = project.term_by_id.get(lesson.term)
    if periodo is None:
        return True
    if periodo.begin and fecha < periodo.begin:
        return False
    return not (periodo.end and fecha > periodo.end)


def _rooms_of(lesson: Lesson, asignaciones: list[Assignment]) -> tuple[str, ...]:
    """Aulas de la clase: las colocadas y, si no hay, las declaradas en las líneas."""
    colocadas = tuple(dict.fromkeys(a.room for a in asignaciones if a.room))
    if colocadas:
        return colocadas
    return tuple(dict.fromkeys(li.room for li in lesson.lines if li.room))


def day_lessons(
    project: UntisProject, timetable: Timetable | None, fecha: str
) -> tuple[DayLesson, ...]:
    """Clases que se dan esa fecha `AAAAMMDD`, ordenadas por hora y lección.

    Vacío si es festivo, si no hay horario o si la fecha cae en un día que el
    horario no usa (un domingo, por ejemplo).
    """
    numero_dia = weekday_of(fecha)
    if timetable is None or project.is_holiday(fecha):
        return ()
    lecciones = project.lesson_by_number
    por_celda: defaultdict[tuple[int, int], list[Assignment]] = defaultdict(list)
    for a in timetable.assignments:
        if a.day == numero_dia:
            por_celda[(a.lesson_number, a.period)].append(a)
    filas: list[DayLesson] = []
    for (numero, periodo), asignaciones in por_celda.items():
        le = lecciones.get(numero)
        if le is None or le.ignore or not _in_effect(project, le, fecha):
            continue
        filas.append(
            DayLesson(
                date=fecha,
                day=numero_dia,
                period=periodo,
                lesson_number=numero,
                subject=le.subjects[0] if le.subjects else "",
                teachers=le.teachers,
                classes=le.classes,
                rooms=_rooms_of(le, asignaciones),
            )
        )
    return tuple(sorted(filas, key=lambda f: (f.period, f.lesson_number)))


def day_lesson(
    project: UntisProject, timetable: Timetable | None, fecha: str, hora: int, leccion: int
) -> DayLesson | None:
    """Una clase concreta del día, o `None` si ese día no se da a esa hora."""
    for clase in day_lessons(project, timetable, fecha):
        if clase.period == hora and clase.lesson_number == leccion:
            return clase
    return None


# --------------------------------------------------------------------------- #
# Ausencias del día
# --------------------------------------------------------------------------- #


def _absence_text(ausencia: Absence) -> str:
    """Frase corta en español de una ausencia."""
    plantillas = {
        EntityKind.TEACHER: "falta {0}",
        EntityKind.CLASS: "no asiste la clase {0}",
        EntityKind.ROOM: "no está disponible el aula {0}",
    }
    texto = plantillas.get(ausencia.entity_kind, "ausencia de {0}").format(ausencia.entity_id)
    motivo = ausencia.reason.strip()
    return f"{texto} ({motivo})" if motivo else texto


def _reason_of(ausencias: list[Absence]) -> str:
    """Motivo conjunto: las frases de cada ausencia, separadas por punto y coma."""
    frases = [_absence_text(a) for a in ausencias]
    if not frases:
        return ""
    unido = "; ".join(frases)
    return unido[:1].upper() + unido[1:]


def affected(
    project: UntisProject, timetable: Timetable | None, fecha: str
) -> tuple[AffectedLesson, ...]:
    """Clases de esa fecha tocadas por alguna ausencia, con el motivo.

    Se mira ausencia por ausencia y hora por hora: una ausencia de varios días
    solo acota horas en su primer y su último día (ver `Absence.covers`).
    """
    vigentes = project.absences_on(fecha)
    if not vigentes:
        return ()
    resultado: list[AffectedLesson] = []
    for clase in day_lessons(project, timetable, fecha):
        tocan: list[Absence] = []
        profes: list[str] = []
        grupos: list[str] = []
        aulas: list[str] = []
        for a in vigentes:
            if not a.covers(fecha, clase.period):
                continue
            destino = {
                EntityKind.TEACHER: (clase.teachers, profes),
                EntityKind.CLASS: (clase.classes, grupos),
                EntityKind.ROOM: (clase.rooms, aulas),
            }.get(a.entity_kind)
            if destino is None or a.entity_id not in destino[0]:
                continue
            tocan.append(a)
            if a.entity_id not in destino[1]:
                destino[1].append(a.entity_id)
        if tocan:
            resultado.append(
                AffectedLesson(
                    lesson=clase,
                    absences=tuple(a.id for a in tocan),
                    teachers=tuple(profes),
                    classes=tuple(grupos),
                    rooms=tuple(aulas),
                    reason=_reason_of(tocan),
                )
            )
    return tuple(resultado)


# --------------------------------------------------------------------------- #
# Contadores
# --------------------------------------------------------------------------- #


def counters(
    project: UntisProject, desde: str | None = None, hasta: str | None = None
) -> dict[str, int]:
    """Sustituciones acumuladas por profesor (`COUNTER_SIGN`), en un tramo opcional.

    `desde` y `hasta` son fechas `AAAAMMDD` inclusive; `None` no acota ese
    extremo. Solo aparecen los profesores que asumen alguna decisión: las que
    no suman (supresión, cambio de aula, traslado, permuta) los dejan a 0.
    """
    total: dict[str, int] = {}
    for s in project.substitutions:
        if not s.teacher:
            continue
        if desde is not None and s.date < desde:
            continue
        if hasta is not None and s.date > hasta:
            continue
        total[s.teacher] = total.get(s.teacher, 0) + COUNTER_SIGN[s.kind]
    return total


# --------------------------------------------------------------------------- #
# Candidatos a sustituir
# --------------------------------------------------------------------------- #


def _busy_teachers(
    project: UntisProject,
    clases: tuple[DayLesson, ...],
    fecha: str,
    dia_semana: int,
    hora: int,
) -> set[str]:
    """Profesores con algo a esa hora: clase, guardia de recreo o sustitución."""
    ocupados = {t for c in clases if c.period == hora for t in c.teachers}
    for g in project.supervisions:
        if g.teacher and g.day == dia_semana and g.period == hora:
            ocupados.add(g.teacher)
    for s in project.substitutions_on(fecha):
        if s.period == hora and s.teacher:
            ocupados.add(s.teacher)
    return ocupados


def _absent_teachers(project: UntisProject, fecha: str, hora: int) -> set[str]:
    """Profesores con una ausencia vigente a esa hora."""
    return {
        a.entity_id
        for a in project.absences_on(fecha)
        if a.entity_kind is EntityKind.TEACHER and a.covers(fecha, hora)
    }


def _at_school(
    project: UntisProject,
    clases: tuple[DayLesson, ...],
    fecha: str,
    dia_semana: int,
    hora: int,
    profesor: str,
) -> bool:
    """`True` si ese profesor ya está en el colegio ese día por otra cosa.

    Cuenta la clase propia, la guardia de recreo y la sustitución ya puesta: una
    guardia obliga a venir igual que una clase.
    """
    if any(c.period != hora and profesor in c.teachers for c in clases):
        return True
    if any(
        g.teacher == profesor and g.day == dia_semana and g.period != hora
        for g in project.supervisions
    ):
        return True
    return any(s.period != hora and s.teacher == profesor for s in project.substitutions_on(fecha))


def _teaching_profile(project: UntisProject, profesor: str) -> tuple[set[str], set[str]]:
    """Materias que da y clases a las que da clase ese profesor."""
    materias: set[str] = set()
    grupos: set[str] = set()
    for le in project.lessons:
        for li in le.lines:
            if li.teacher == profesor:
                materias.add(li.subject)
                grupos.update(li.classes)
    return materias, grupos


def _candidate_reason(
    at_school: bool, teaches_subject: bool, teaches_class: bool, contador: int, lock: int
) -> str:
    """Explicación corta en español del puesto que ocupa un candidato."""
    partes = [
        "ya está en el centro" if at_school else "tendría que venir",
        "da la materia"
        if teaches_subject
        else ("da clase al grupo" if teaches_class else "no da la materia ni al grupo"),
        f"{contador} sustitución" if contador == 1 else f"{contador} sustituciones",
    ]
    if lock:
        partes.append(f"reserva {lock}")
    unido = ", ".join(partes)
    return unido[:1].upper() + unido[1:]


def candidates(
    project: UntisProject,
    timetable: Timetable | None,
    fecha: str,
    hora: int,
    leccion: int,
) -> tuple[Candidate, ...]:
    """Profesores que podrían cubrir esa clase, de mejor a peor.

    Filtro duro (criterio a): se descarta a quien está ausente, a quien a esa
    hora tiene clase, guardia de recreo o ya una sustitución, a los profesores
    de la propia lección y a quien tiene la reserva de sustitución en
    `LOCK_NEVER` (9 = no proponerlo nunca). El orden de los que quedan sigue los
    criterios (b) a (e) documentados arriba; `Candidate.score` es la puntuación
    equivalente (a más puntos, mejor) y `Candidate.reason` la explica en una
    frase.
    """
    objetivo = day_lesson(project, timetable, fecha, hora, leccion)
    if objetivo is None:
        return ()
    dia_semana = weekday_of(fecha)
    clases = day_lessons(project, timetable, fecha)
    fuera = _busy_teachers(project, clases, fecha, dia_semana, hora) | _absent_teachers(
        project, fecha, hora
    )
    fuera.update(objetivo.teachers)
    contadores = counters(project)
    grupos_objetivo = set(objetivo.classes)
    propuestas: list[Candidate] = []
    for profe in project.teachers:
        if profe.id in fuera or profe.substitution_lock >= LOCK_NEVER:
            continue
        materias, grupos = _teaching_profile(project, profe.id)
        da_materia = bool(objetivo.subject) and objetivo.subject in materias
        da_grupo = bool(grupos_objetivo & grupos)
        conoce = da_materia or da_grupo
        en_centro = _at_school(project, clases, fecha, dia_semana, hora, profe.id)
        contador = contadores.get(profe.id, 0)
        lock = profe.substitution_lock
        puntos = (
            (SCORE_AT_SCHOOL if en_centro else 0)
            + (SCORE_KNOWS if conoce else 0)
            + (COUNTER_CAP - min(max(contador, 0), COUNTER_CAP)) * SCORE_PER_SUBSTITUTION
            + (LOCK_MAX - lock)
        )
        propuestas.append(
            Candidate(
                teacher=profe.id,
                score=puntos,
                reason=_candidate_reason(en_centro, da_materia, da_grupo, contador, lock),
                at_school=en_centro,
                knows=conoce,
                teaches_subject=da_materia,
                teaches_class=da_grupo,
                counter=contador,
                lock=lock,
            )
        )
    return tuple(sorted(propuestas, key=lambda c: (-c.score, c.teacher)))
