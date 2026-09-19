"""Sustituciones (Vertretungsplanung) en la Fachada: el parte del día.

Este módulo aporta `SubstitutionMixin`, el trozo de la Fachada que maneja el
calendario (festivos), las ausencias de profesores, clases y aulas, y las
decisiones que se toman para un día concreto: sustituir, suprimir o cambiar de
aula. `UntisService` lo hereda, así que la UI lo usa como cualquier otro método
de la Fachada.

Como el resto de la Fachada: nada lanza por datos inválidos (el error va en el
`EditResult`), cada edición pasa por `session.apply(...)` para que se pueda
deshacer, y lo que devuelve son vistas inmutables listas para pintar.

Los ids de ausencias (`A-1`, `A-2`, ...) y de decisiones (`S-1`, `S-2`, ...) se
generan solos y son estables: una decisión que se corrige conserva su id, y un
id liberado solo se reutiliza cuando no queda ninguno por delante.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from scheduling_platform.untis_model import (
    Absence,
    EntityKind,
    Holiday,
    Substitution,
    SubstitutionKind,
    Timetable,
    UntisProject,
    parse_date,
    weekday_of,
)
from scheduling_platform.untis_model.daily import (
    AffectedLesson,
    affected,
    candidates,
    counters,
    day_lesson,
    day_lessons,
)

from .session import UntisSession
from .views import EditResult

#: Prefijo de los ids automáticos de ausencia.
ABSENCE_PREFIX = "A"
#: Prefijo de los ids automáticos de decisión del día.
SUBSTITUTION_PREFIX = "S"
#: Prefijo de los ids automáticos de festivo.
HOLIDAY_PREFIX = "H"

#: Tipos de entidad que pueden faltar, con su `EntityKind`.
ABSENCE_KINDS: dict[str, EntityKind] = {
    "teacher": EntityKind.TEACHER,
    "class": EntityKind.CLASS,
    "room": EntityKind.ROOM,
}

#: Nombre en español de cada tipo de decisión (la UI lo traduce si hace falta).
KIND_LABELS: dict[str, str] = {
    SubstitutionKind.SUBSTITUTION.value: "Sustitución",
    SubstitutionKind.SUPERVISION.value: "Cuidado del grupo",
    SubstitutionKind.CANCELLED.value: "Clase suprimida",
    SubstitutionKind.ROOM.value: "Cambio de aula",
    SubstitutionKind.MOVED.value: "Traslado",
    SubstitutionKind.SWAP.value: "Permuta",
    SubstitutionKind.EXTRA.value: "Servicio extra",
}


# --------------------------------------------------------------------------- #
# Vistas
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class HolidayRow:
    """Un festivo en la lista del calendario."""

    id: str
    name: str
    begin: str
    """Fecha `AAAAMMDD`."""
    end: str

    @property
    def label(self) -> str:
        """Texto corto: nombre y fechas."""
        tramo = self.begin if self.begin == self.end else f"{self.begin}-{self.end}"
        return f"{self.name} ({tramo})"


@dataclass(frozen=True, slots=True)
class AbsenceRow:
    """Una ausencia en la lista del día."""

    id: str
    entity_kind: str
    """`teacher`, `class` o `room`."""
    entity_id: str
    name: str
    """Nombre largo de la entidad que falta."""
    begin: str
    end: str
    first_period: int | None = None
    last_period: int | None = None
    reason: str = ""
    text: str = ""

    @property
    def periods_label(self) -> str:
        """Horas que abarca, p. ej. `"3-6"`, `"desde 3"` o `"todo el día"`."""
        if self.first_period is None and self.last_period is None:
            return "todo el día"
        if self.first_period is not None and self.last_period is not None:
            return f"{self.first_period}-{self.last_period}"
        if self.first_period is not None:
            return f"desde {self.first_period}"
        return f"hasta {self.last_period}"


@dataclass(frozen=True, slots=True)
class DayRow:
    """Una línea del parte del día: una clase afectada o ya decidida."""

    period: int
    lesson: int
    subject: str
    teachers: tuple[str, ...] = field(default_factory=tuple)
    classes: tuple[str, ...] = field(default_factory=tuple)
    rooms: tuple[str, ...] = field(default_factory=tuple)
    absent_teachers: tuple[str, ...] = field(default_factory=tuple)
    absent_classes: tuple[str, ...] = field(default_factory=tuple)
    absent_rooms: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""
    kind: str = ""
    """Tipo de decisión tomada; vacío si aún no hay ninguna."""
    kind_label: str = ""
    substitute: str = ""
    new_room: str = ""
    note: str = ""
    absence: str = ""
    """Id de la ausencia que la provoca."""

    @property
    def decided(self) -> bool:
        """`True` si ya hay una decisión para esta clase."""
        return bool(self.kind)

    @property
    def pending(self) -> bool:
        """`True` si falta un profesor y todavía no hay quien la cubra."""
        if not self.absent_teachers:
            return False
        return not self.kind or (
            not self.substitute
            and self.kind
            in (SubstitutionKind.SUBSTITUTION.value, SubstitutionKind.SUPERVISION.value)
        )


@dataclass(frozen=True, slots=True)
class DayReport:
    """El parte de un día: festivo, ausencias y clases afectadas o decididas."""

    date: str
    weekday: int
    """Día de la semana (1 = lunes)."""
    holiday: str = ""
    """Nombre del festivo; vacío si es día lectivo."""
    timetable: str = ""
    """Id del horario con el que se ha calculado."""
    absences: tuple[AbsenceRow, ...] = field(default_factory=tuple)
    rows: tuple[DayRow, ...] = field(default_factory=tuple)
    message: str = ""
    """Por qué el parte está vacío, si lo está."""

    @property
    def is_holiday(self) -> bool:
        return bool(self.holiday)

    @property
    def pending(self) -> int:
        """Cuántas clases quedan por resolver."""
        return sum(1 for r in self.rows if r.pending)


@dataclass(frozen=True, slots=True)
class CandidateRow:
    """Un profesor propuesto para cubrir una clase."""

    teacher: str
    name: str
    score: int
    reason: str
    at_school: bool = False
    knows: bool = False
    counter: int = 0
    lock: int = 0


@dataclass(frozen=True, slots=True)
class CounterRow:
    """Contador de sustituciones de un profesor."""

    teacher: str
    name: str
    count: int
    """Puntos del contador (`COUNTER_SIGN`)."""
    assigned: int
    """Cuántas decisiones asume en el tramo."""
    lock: int = 0


# --------------------------------------------------------------------------- #
# Utilidades puras del módulo
# --------------------------------------------------------------------------- #


def _next_id(existentes: set[str], prefijo: str) -> str:
    """Primer id libre de la forma `<prefijo>-<n>` (estable y determinista)."""
    n = 1
    while f"{prefijo}-{n}" in existentes:
        n += 1
    return f"{prefijo}-{n}"


def _valid_date(valor: str, campo: str) -> str:
    """Normaliza una fecha `AAAAMMDD`; lanza `ValueError` con un texto claro."""
    texto = valor.strip()
    if not texto:
        raise ValueError(f"Falta la fecha de {campo} (AAAAMMDD)")
    parse_date(texto)
    return texto


def _period_or_none(valor: int | None, campo: str) -> int | None:
    if valor is not None and valor < 1:
        raise ValueError(f"La {campo} debe ser 1 o mayor")
    return valor


# --------------------------------------------------------------------------- #
# Mixin de la Fachada
# --------------------------------------------------------------------------- #


class SubstitutionMixin:
    """Calendario, ausencias y parte del día. Lo hereda `UntisService`."""

    # --- apoyos ---------------------------------------------------------- #

    def _active_timetable(
        self, session: UntisSession, timetable_id: str | None = None
    ) -> Timetable | None:
        """Horario con el que se resuelve el día: el pedido o el activo."""
        return session.project.timetable_by_id(timetable_id or session.active_timetable or "")

    @staticmethod
    def _entity_name(project: UntisProject, kind: str, entity_id: str) -> str:
        indices = {
            "teacher": {t.id: t.display_name for t in project.teachers},
            "class": {c.id: c.display_name for c in project.classes},
            "room": {r.id: r.display_name for r in project.rooms},
        }
        return indices.get(kind, {}).get(entity_id, entity_id)

    @classmethod
    def _absence_row(cls, project: UntisProject, a: Absence) -> AbsenceRow:
        return AbsenceRow(
            id=a.id,
            entity_kind=a.entity_kind.value,
            entity_id=a.entity_id,
            name=cls._entity_name(project, a.entity_kind.value, a.entity_id),
            begin=a.begin,
            end=a.last_day,
            first_period=a.first_period,
            last_period=a.last_period,
            reason=a.reason,
            text=a.text,
        )

    # --- calendario ------------------------------------------------------- #

    def holidays(self, session: UntisSession) -> tuple[HolidayRow, ...]:
        """Festivos del curso, ordenados por fecha de inicio."""
        filas = [
            HolidayRow(h.id, h.display_name, h.begin or h.end, h.end or h.begin)
            for h in session.project.holidays
        ]
        return tuple(sorted(filas, key=lambda f: (f.begin, f.id)))

    def add_holiday(
        self, session: UntisSession, name: str, begin: str, end: str = ""
    ) -> EditResult:
        """Da de alta un festivo o un tramo de vacaciones."""
        titulo = name.strip()
        if not titulo:
            return EditResult.failure("El festivo necesita un nombre")
        try:
            inicio = _valid_date(begin, "inicio")
            final = _valid_date(end, "fin") if end.strip() else inicio
        except ValueError as exc:
            return EditResult.failure(str(exc))
        if final < inicio:
            return EditResult.failure("El festivo termina antes de empezar")
        p = session.project
        ident = _next_id({h.id for h in p.holidays}, HOLIDAY_PREFIX)
        nuevo = Holiday(ident, titulo, inicio, final)
        session.apply(
            dataclasses.replace(p, holidays=(*p.holidays, nuevo)), f"Añadir festivo {titulo}"
        )
        return EditResult.success(f"Festivo {ident} dado de alta")

    def remove_holiday(self, session: UntisSession, holiday_id: str) -> EditResult:
        """Quita un festivo del calendario."""
        p = session.project
        restantes = tuple(h for h in p.holidays if h.id != holiday_id)
        if len(restantes) == len(p.holidays):
            return EditResult.failure(f"No existe el festivo {holiday_id!r}")
        session.apply(dataclasses.replace(p, holidays=restantes), f"Borrar festivo {holiday_id}")
        return EditResult.success()

    # --- ausencias -------------------------------------------------------- #

    def absences(self, session: UntisSession, date: str = "") -> tuple[AbsenceRow, ...]:
        """Ausencias del proyecto o, con `date`, las vigentes ese día."""
        p = session.project
        vigentes = p.absences_on(date) if date else p.absences
        filas = [self._absence_row(p, a) for a in vigentes]
        return tuple(sorted(filas, key=lambda f: (f.begin, f.entity_kind, f.entity_id, f.id)))

    def add_absence(
        self,
        session: UntisSession,
        entity_kind: str,
        entity_id: str,
        begin: str,
        end: str = "",
        first_period: int | None = None,
        last_period: int | None = None,
        reason: str = "",
        text: str = "",
    ) -> EditResult:
        """Da de alta la falta de un profesor, una clase o un aula."""
        kind = ABSENCE_KINDS.get(entity_kind)
        if kind is None:
            return EditResult.failure(f"No se puede dar de baja a {entity_kind!r}")
        p = session.project
        conocidos = {
            "teacher": {t.id for t in p.teachers},
            "class": {c.id for c in p.classes},
            "room": {r.id for r in p.rooms},
        }[entity_kind]
        ident_entidad = entity_id.strip()
        if ident_entidad not in conocidos:
            return EditResult.failure(f"{entity_id!r} no existe")
        try:
            inicio = _valid_date(begin, "inicio")
            final = _valid_date(end, "fin") if end.strip() else inicio
            primera = _period_or_none(first_period, "primera hora")
            ultima = _period_or_none(last_period, "última hora")
        except ValueError as exc:
            return EditResult.failure(str(exc))
        if final < inicio:
            return EditResult.failure("La ausencia termina antes de empezar")
        if primera is not None and ultima is not None and primera > ultima:
            return EditResult.failure("La primera hora es posterior a la última")
        ident = _next_id({a.id for a in p.absences}, ABSENCE_PREFIX)
        try:
            nueva = Absence(
                id=ident,
                entity_kind=kind,
                entity_id=ident_entidad,
                begin=inicio,
                end=final,
                first_period=primera,
                last_period=ultima,
                reason=reason.strip(),
                text=text.strip(),
            )
        except ValueError as exc:
            return EditResult.failure(str(exc))
        session.apply(
            dataclasses.replace(p, absences=(*p.absences, nueva)),
            f"Añadir ausencia de {ident_entidad}",
        )
        return EditResult.success(f"Ausencia {ident} dada de alta")

    def remove_absence(self, session: UntisSession, absence_id: str) -> EditResult:
        """Quita una ausencia y las decisiones que venían de ella."""
        p = session.project
        restantes = tuple(a for a in p.absences if a.id != absence_id)
        if len(restantes) == len(p.absences):
            return EditResult.failure(f"No existe la ausencia {absence_id!r}")
        decisiones = tuple(s for s in p.substitutions if s.absence != absence_id)
        session.apply(
            dataclasses.replace(p, absences=restantes, substitutions=decisiones),
            f"Borrar ausencia {absence_id}",
        )
        return EditResult.success()

    # --- parte del día ---------------------------------------------------- #

    def day_report(
        self, session: UntisSession, date: str, timetable_id: str | None = None
    ) -> DayReport:
        """Parte del día: ausencias, clases afectadas y decisiones ya tomadas."""
        p = session.project
        try:
            dia = _valid_date(date, "día")
        except ValueError as exc:
            return DayReport(date=date.strip(), weekday=0, message=str(exc))
        festivo = next((h.display_name for h in p.holidays if h.covers(dia)), "")
        tt = self._active_timetable(session, timetable_id)
        ausencias = self.absences(session, dia)
        cabecera = DayReport(
            date=dia,
            weekday=weekday_of(dia),
            holiday=festivo,
            timetable=tt.id if tt is not None else "",
            absences=ausencias,
        )
        if festivo:
            return dataclasses.replace(cabecera, message=f"Día sin clase: {festivo}")
        if tt is None:
            return dataclasses.replace(cabecera, message="No hay ningún horario activo")
        filas = self._day_rows(p, tt, dia)
        mensaje = "" if filas else "Ningún cambio este día"
        return dataclasses.replace(cabecera, rows=filas, message=mensaje)

    def _day_rows(
        self, project: UntisProject, timetable: Timetable, dia: str
    ) -> tuple[DayRow, ...]:
        """Clases afectadas por una ausencia, más las que ya tienen decisión."""
        tocadas: dict[tuple[int, int], AffectedLesson] = {
            (a.lesson.period, a.lesson.lesson_number): a for a in affected(project, timetable, dia)
        }
        decisiones = {(s.period, s.lesson_number): s for s in project.substitutions_on(dia)}
        filas: list[DayRow] = []
        for clave in sorted(set(tocadas) | set(decisiones)):
            hora, leccion = clave
            info = tocadas.get(clave)
            clase = (
                info.lesson
                if info is not None
                else day_lesson(project, timetable, dia, hora, leccion)
            )
            decision = decisiones.get(clave)
            filas.append(
                DayRow(
                    period=hora,
                    lesson=leccion,
                    subject=clase.subject if clase is not None else "",
                    teachers=clase.teachers if clase is not None else (),
                    classes=clase.classes if clase is not None else (),
                    rooms=clase.rooms if clase is not None else (),
                    absent_teachers=info.teachers if info is not None else (),
                    absent_classes=info.classes if info is not None else (),
                    absent_rooms=info.rooms if info is not None else (),
                    reason=info.reason if info is not None else "",
                    kind=decision.kind.value if decision is not None else "",
                    kind_label=KIND_LABELS[decision.kind.value] if decision is not None else "",
                    substitute=decision.teacher if decision is not None else "",
                    new_room=decision.room if decision is not None else "",
                    note=decision.note if decision is not None else "",
                    absence=self._absence_of(info, decision),
                )
            )
        return tuple(filas)

    @staticmethod
    def _absence_of(info: AffectedLesson | None, decision: Substitution | None) -> str:
        if decision is not None and decision.absence:
            return decision.absence
        if info is not None and info.absences:
            return info.absences[0]
        return ""

    # --- decisiones -------------------------------------------------------- #

    def substitute_candidates(
        self,
        session: UntisSession,
        date: str,
        period: int,
        lesson: int,
        timetable_id: str | None = None,
    ) -> tuple[CandidateRow, ...]:
        """Profesores que podrían cubrir esa clase, de mejor a peor."""
        p = session.project
        try:
            dia = _valid_date(date, "día")
        except ValueError:
            return ()
        tt = self._active_timetable(session, timetable_id)
        return tuple(
            CandidateRow(
                teacher=c.teacher,
                name=self._entity_name(p, "teacher", c.teacher),
                score=c.score,
                reason=c.reason,
                at_school=c.at_school,
                knows=c.knows,
                counter=c.counter,
                lock=c.lock,
            )
            for c in candidates(p, tt, dia, period, lesson)
        )

    def _decide(
        self,
        session: UntisSession,
        dia: str,
        hora: int,
        leccion: int,
        etiqueta: str,
        *,
        kind: SubstitutionKind,
        teacher: str = "",
        room: str = "",
        absent_teacher: str = "",
        absence: str = "",
        note: str = "",
    ) -> EditResult:
        """Guarda (o corrige) la decisión de una clase, conservando su id."""
        p = session.project
        previa = next(
            (
                s
                for s in p.substitutions
                if s.date == dia and s.period == hora and s.lesson_number == leccion
            ),
            None,
        )
        ident = (
            previa.id
            if previa is not None
            else _next_id({s.id for s in p.substitutions}, SUBSTITUTION_PREFIX)
        )
        otras = tuple(s for s in p.substitutions if s.id != ident)
        try:
            nueva = Substitution(
                id=ident,
                date=dia,
                period=hora,
                lesson_number=leccion,
                kind=kind,
                absent_teacher=absent_teacher,
                teacher=teacher,
                room=room,
                absence=absence,
                note=note,
            )
        except ValueError as exc:
            return EditResult.failure(str(exc))
        session.apply(dataclasses.replace(p, substitutions=(*otras, nueva)), etiqueta)
        return EditResult.success()

    def _target(
        self, session: UntisSession, dia: str, hora: int, leccion: int, timetable_id: str | None
    ) -> tuple[AffectedLesson | None, str]:
        """Comprueba que la clase existe ese día; devuelve su ausencia y el error."""
        tt = self._active_timetable(session, timetable_id)
        if tt is None:
            return None, "No hay ningún horario activo"
        if session.project.is_holiday(dia):
            return None, f"El {dia} no hay clase"
        clase = day_lesson(session.project, tt, dia, hora, leccion)
        if clase is None:
            return None, f"La lección {leccion} no se da el {dia} a la hora {hora}"
        info = next(
            (
                a
                for a in affected(session.project, tt, dia)
                if a.lesson.period == hora and a.lesson.lesson_number == leccion
            ),
            None,
        )
        return info, ""

    def assign_substitute(
        self,
        session: UntisSession,
        date: str,
        period: int,
        lesson: int,
        teacher: str,
        kind: str = SubstitutionKind.SUBSTITUTION.value,
        note: str = "",
        timetable_id: str | None = None,
        *,
        force: bool = False,
    ) -> EditResult:
        """Pone a un profesor a cubrir una clase.

        Sin `force` solo acepta a quien la Fachada propondría: quien está
        ocupado a esa hora o ausente se rechaza con el motivo.
        """
        try:
            dia = _valid_date(date, "día")
        except ValueError as exc:
            return EditResult.failure(str(exc))
        if kind not in KIND_LABELS:
            return EditResult.failure(f"Tipo de decisión desconocido: {kind!r}")
        if teacher not in {t.id for t in session.project.teachers}:
            return EditResult.failure(f"El profesor {teacher!r} no existe")
        info, error = self._target(session, dia, period, lesson, timetable_id)
        if error:
            return EditResult.failure(error)
        if not force:
            posibles = {
                c.teacher
                for c in self.substitute_candidates(session, dia, period, lesson, timetable_id)
            }
            if teacher not in posibles:
                return EditResult.failure(
                    f"{teacher} no está libre esa hora (usa force=True para ponerlo igualmente)"
                )
        ausente = info.teachers[0] if info is not None and info.teachers else ""
        return self._decide(
            session,
            dia,
            period,
            lesson,
            f"Sustituir {ausente or lesson} por {teacher}",
            kind=SubstitutionKind(kind),
            teacher=teacher,
            absent_teacher=ausente,
            absence=info.absences[0] if info is not None and info.absences else "",
            note=note.strip(),
        )

    def cancel_lesson(
        self,
        session: UntisSession,
        date: str,
        period: int,
        lesson: int,
        note: str = "",
        timetable_id: str | None = None,
    ) -> EditResult:
        """Marca una clase como suprimida (no se da)."""
        try:
            dia = _valid_date(date, "día")
        except ValueError as exc:
            return EditResult.failure(str(exc))
        info, error = self._target(session, dia, period, lesson, timetable_id)
        if error:
            return EditResult.failure(error)
        return self._decide(
            session,
            dia,
            period,
            lesson,
            f"Suprimir la lección {lesson}",
            kind=SubstitutionKind.CANCELLED,
            absent_teacher=info.teachers[0] if info is not None and info.teachers else "",
            absence=info.absences[0] if info is not None and info.absences else "",
            note=note.strip(),
        )

    def change_room(
        self,
        session: UntisSession,
        date: str,
        period: int,
        lesson: int,
        room: str,
        timetable_id: str | None = None,
        *,
        force: bool = False,
    ) -> EditResult:
        """Cambia de aula una clase concreta de un día."""
        try:
            dia = _valid_date(date, "día")
        except ValueError as exc:
            return EditResult.failure(str(exc))
        if room not in {r.id for r in session.project.rooms}:
            return EditResult.failure(f"El aula {room!r} no existe")
        info, error = self._target(session, dia, period, lesson, timetable_id)
        if error:
            return EditResult.failure(error)
        if not force:
            libre, motivo = self._room_is_free(session, dia, period, lesson, room, timetable_id)
            if not libre:
                return EditResult.failure(motivo)
        return self._decide(
            session,
            dia,
            period,
            lesson,
            f"Cambiar al aula {room}",
            kind=SubstitutionKind.ROOM,
            room=room,
            absent_teacher=info.teachers[0] if info is not None and info.teachers else "",
            absence=info.absences[0] if info is not None and info.absences else "",
        )

    def _room_is_free(
        self,
        session: UntisSession,
        dia: str,
        hora: int,
        leccion: int,
        aula: str,
        timetable_id: str | None,
    ) -> tuple[bool, str]:
        """`(libre, motivo)`: si el aula está ocupada o ausente a esa hora."""
        p = session.project
        tt = self._active_timetable(session, timetable_id)
        for a in p.absences_on(dia):
            if a.entity_kind is EntityKind.ROOM and a.entity_id == aula and a.covers(dia, hora):
                return False, f"El aula {aula} también está ausente esa hora"
        for clase in day_lessons(p, tt, dia):
            if clase.period == hora and clase.lesson_number != leccion and aula in clase.rooms:
                return False, f"El aula {aula} está ocupada por la lección {clase.lesson_number}"
        for s in p.substitutions_on(dia):
            if s.period == hora and s.lesson_number != leccion and s.room == aula:
                return False, f"El aula {aula} ya se ha asignado a la lección {s.lesson_number}"
        return True, ""

    def clear_decision(
        self, session: UntisSession, date: str, period: int, lesson: int
    ) -> EditResult:
        """Borra la decisión de una clase (vuelve a quedar pendiente)."""
        p = session.project
        restantes = tuple(
            s
            for s in p.substitutions
            if not (s.date == date and s.period == period and s.lesson_number == lesson)
        )
        if len(restantes) == len(p.substitutions):
            return EditResult.failure("Esa clase no tiene ninguna decisión")
        session.apply(
            dataclasses.replace(p, substitutions=restantes),
            f"Quitar la decisión de la lección {lesson}",
        )
        return EditResult.success()

    # --- contadores -------------------------------------------------------- #

    def substitution_counters(
        self, session: UntisSession, begin: str = "", end: str = ""
    ) -> tuple[CounterRow, ...]:
        """Contador por profesor, de más a menos (tramo de fechas opcional)."""
        p = session.project
        desde = begin.strip() or None
        hasta = end.strip() or None
        puntos = counters(p, desde, hasta)
        asumidas: dict[str, int] = {}
        for s in p.substitutions:
            if not s.teacher:
                continue
            if (desde is not None and s.date < desde) or (hasta is not None and s.date > hasta):
                continue
            asumidas[s.teacher] = asumidas.get(s.teacher, 0) + 1
        filas = [
            CounterRow(
                teacher=t.id,
                name=t.display_name,
                count=puntos.get(t.id, 0),
                assigned=asumidas.get(t.id, 0),
                lock=t.substitution_lock,
            )
            for t in p.teachers
        ]
        return tuple(sorted(filas, key=lambda f: (-f.count, -f.assigned, f.teacher)))
