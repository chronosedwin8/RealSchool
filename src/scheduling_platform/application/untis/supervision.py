"""Fachada de las guardias de recreo (Pausenaufsichten).

Mixin de `UntisService` con los casos de uso de la ventana Guardias: las zonas
que hay que vigilar, la parrilla de turnos `zona x (día, recreo)`, la
asignación a mano, el reparto automático (`heuristic.supervision`) y el resumen
de minutos por profesor.

Igual que el resto de la Fachada: nada lanza por datos inválidos; todo devuelve
`EditResult` para que la ventana pinte el motivo. Pasarse del máximo de guardia
de un profesor **avisa pero se permite** cuando lo hace una persona a mano, que
es lo que hace Untis; el reparto automático, en cambio, nunca se lo salta.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from scheduling_platform.heuristic.supervision import (
    assign_supervisions,
    grid_of_area,
    supervision_minutes,
)
from scheduling_platform.untis_model import (
    PeriodDef,
    PeriodKind,
    Supervision,
    SupervisionArea,
    TimeGrid,
    UntisProject,
    minutes_to_hhmm,
)

from .session import UntisSession
from .views import EditResult

#: Peso por defecto de una zona nueva (0-5, como las ponderaciones de Untis).
DEFAULT_AREA_WEIGHT = 3


# --------------------------------------------------------------------------- #
# Modelos de vista
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SupervisionAreaRow:
    """Una zona de vigilancia en la lista de zonas."""

    id: str
    name: str
    time_grid: str
    weight: int
    text: str
    shifts: int
    """Turnos que tiene la zona en la parrilla."""
    assigned: int
    """De esos turnos, cuántos tienen profesor."""

    @property
    def uncovered(self) -> int:
        return self.shifts - self.assigned


@dataclass(frozen=True, slots=True)
class SupervisionSlot:
    """Un recreo de la rejilla: una columna de la parrilla."""

    day: int
    period: int
    start: str
    """`HH:MM`."""
    end: str
    minutes: int


@dataclass(frozen=True, slots=True)
class SupervisionCell:
    """Un turno de la parrilla (puede no existir todavía)."""

    area: str
    day: int
    period: int
    teacher: str = ""
    fixed: bool = False
    minutes: int = 0
    exists: bool = True
    """`False` si en esa zona y recreo no hay turno creado."""

    @property
    def assigned(self) -> bool:
        return bool(self.teacher)


@dataclass(frozen=True, slots=True)
class SupervisionGrid:
    """La parrilla completa: zonas x recreos de una rejilla."""

    grid_id: str
    slots: tuple[SupervisionSlot, ...]
    areas: tuple[SupervisionAreaRow, ...]
    cells: tuple[SupervisionCell, ...]
    teachers: tuple[str, ...]
    """Profesores que se pueden elegir en el desplegable de una celda."""
    message: str = ""
    """Por qué la parrilla está vacía (sin rejilla, sin recreos, sin zonas)."""

    def cell(self, area: str, day: int, period: int) -> SupervisionCell | None:
        """El turno de esa zona y recreo, o `None` si no hay."""
        for c in self.cells:
            if c.area == area and c.day == day and c.period == period:
                return c
        return None

    @property
    def uncovered(self) -> int:
        """Turnos existentes sin profesor."""
        return sum(1 for c in self.cells if c.exists and not c.assigned)


@dataclass(frozen=True, slots=True)
class SupervisionLoad:
    """Carga de guardias de un profesor: lo asignado frente a su máximo."""

    teacher: str
    name: str
    minutes: int
    shifts: int
    maximum: int | None = None
    """`Teacher.supervision_max`; `None` = sin límite."""

    @property
    def over_max(self) -> bool:
        """`True` si se ha pasado de su máximo semanal."""
        return self.maximum is not None and self.minutes > self.maximum

    @property
    def free(self) -> int | None:
        """Minutos que aún le caben (`None` si no tiene límite)."""
        return None if self.maximum is None else self.maximum - self.minutes


# --------------------------------------------------------------------------- #
# Ayudas privadas
# --------------------------------------------------------------------------- #


def _clock(minutes: int) -> str:
    """Minutos desde medianoche -> `HH:MM`."""
    texto = minutes_to_hhmm(minutes)
    return f"{texto[:2]}:{texto[2:]}"


def _breaks(grid: TimeGrid) -> tuple[PeriodDef, ...]:
    """Recreos de la rejilla, en orden."""
    return tuple(
        p for p in sorted(grid.periods, key=lambda p: p.number) if p.kind is PeriodKind.BREAK
    )


def _grid(project: UntisProject, grid_id: str) -> TimeGrid | None:
    """La rejilla pedida o, sin id, la primera del proyecto."""
    if grid_id:
        return project.grid_by_id.get(grid_id)
    return project.time_grids[0] if project.time_grids else None


def _areas_of_grid(project: UntisProject, grid: TimeGrid) -> tuple[SupervisionArea, ...]:
    """Zonas que vigilan los recreos de esa rejilla."""
    zonas: list[SupervisionArea] = []
    for a in project.supervision_areas:
        propia = grid_of_area(project, a)
        if propia is not None and propia.id == grid.id:
            zonas.append(a)
    return tuple(zonas)


def _minutes_by_teacher(project: UntisProject) -> dict[str, int]:
    """Minutos de guardia que lleva asignados cada profesor."""
    zonas = project.area_by_id
    minutos: dict[str, int] = {}
    for s in project.supervisions:
        if not s.teacher:
            continue
        rejilla = grid_of_area(project, zonas.get(s.area))
        minutos[s.teacher] = minutos.get(s.teacher, 0) + supervision_minutes(rejilla, s)
    return minutos


def _with_supervisions(
    project: UntisProject, supervisions: tuple[Supervision, ...]
) -> UntisProject:
    return dataclasses.replace(project, supervisions=supervisions)


# --------------------------------------------------------------------------- #
# Mixin
# --------------------------------------------------------------------------- #


class SupervisionMixin:
    """Casos de uso de las guardias de recreo (lo hereda `UntisService`).

    Ningún método usa estado propio: solo la `UntisSession` que recibe, así que
    también funciona en una instancia suelta (`SupervisionFacade`).
    """

    # --- zonas -------------------------------------------------------------- #

    def supervision_areas(self, session: UntisSession) -> tuple[SupervisionAreaRow, ...]:
        """Zonas de vigilancia con cuántos turnos tienen y cuántos cubiertos."""
        p = session.project
        filas: list[SupervisionAreaRow] = []
        for a in p.supervision_areas:
            turnos = [s for s in p.supervisions if s.area == a.id]
            filas.append(
                SupervisionAreaRow(
                    id=a.id,
                    name=a.display_name,
                    time_grid=a.time_grid,
                    weight=a.weight,
                    text=a.text,
                    shifts=len(turnos),
                    assigned=sum(1 for s in turnos if s.assigned),
                )
            )
        return tuple(filas)

    def add_supervision_area(
        self,
        session: UntisSession,
        area_id: str,
        *,
        name: str = "",
        time_grid: str = "",
        weight: int = DEFAULT_AREA_WEIGHT,
    ) -> EditResult:
        """Crea una zona que vigilar (patio, pasillo, comedor...)."""
        p = session.project
        ident = area_id.strip()
        if not ident:
            return EditResult.failure("La zona necesita un nombre corto")
        if ident in p.area_by_id:
            return EditResult.failure(f"La zona {ident!r} ya existe")
        if time_grid and time_grid not in p.grid_by_id:
            return EditResult.failure(f"No existe la rejilla {time_grid!r}")
        try:
            zona = SupervisionArea(id=ident, name=name.strip(), time_grid=time_grid, weight=weight)
        except ValueError as exc:
            return EditResult.failure(str(exc))
        nuevas = (*p.supervision_areas, zona)
        session.apply(
            dataclasses.replace(p, supervision_areas=nuevas), f"Añadir zona de guardia {ident}"
        )
        return EditResult.success()

    def rename_supervision_area(self, session: UntisSession, area_id: str, name: str) -> EditResult:
        """Nombre largo de la zona (el id no cambia: lo usan los turnos)."""
        p = session.project
        zona = p.area_by_id.get(area_id)
        if zona is None:
            return EditResult.failure(f"No existe la zona {area_id!r}")
        nueva = dataclasses.replace(zona, name=name.strip())
        zonas = tuple(nueva if a.id == area_id else a for a in p.supervision_areas)
        session.apply(dataclasses.replace(p, supervision_areas=zonas), f"Renombrar zona {area_id}")
        return EditResult.success()

    def remove_supervision_area(self, session: UntisSession, area_id: str) -> EditResult:
        """Borra la zona y, con ella, todos sus turnos."""
        p = session.project
        if area_id not in p.area_by_id:
            return EditResult.failure(f"No existe la zona {area_id!r}")
        zonas = tuple(a for a in p.supervision_areas if a.id != area_id)
        turnos = tuple(s for s in p.supervisions if s.area != area_id)
        session.apply(
            dataclasses.replace(p, supervision_areas=zonas, supervisions=turnos),
            f"Borrar zona {area_id}",
        )
        return EditResult.success()

    # --- parrilla de turnos --------------------------------------------------- #

    def supervision_grid(self, session: UntisSession, grid_id: str = "") -> SupervisionGrid:
        """Parrilla zonas x (día, recreo) de una rejilla, para pintarla."""
        p = session.project
        profesores = tuple(t.id for t in p.teachers if t.supervision_max != 0)
        grid = _grid(p, grid_id)
        if grid is None:
            return SupervisionGrid("", (), (), (), profesores, "El proyecto no tiene rejillas")
        recreos = _breaks(grid)
        huecos = tuple(
            SupervisionSlot(d, per.number, _clock(per.start), _clock(per.end), per.duration)
            for d in sorted(grid.days)
            for per in recreos
        )
        zonas = _areas_of_grid(p, grid)
        filas = tuple(f for f in self.supervision_areas(session) if f.id in {a.id for a in zonas})
        turnos = {s.key: s for s in p.supervisions}
        celdas = tuple(self._cell(turnos, zona.id, hueco) for zona in zonas for hueco in huecos)
        aviso = ""
        if not recreos:
            aviso = f"La rejilla {grid.display_name} no tiene ningún recreo"
        elif not zonas:
            aviso = "Aún no hay zonas que vigilar en esta rejilla"
        return SupervisionGrid(grid.id, huecos, filas, celdas, profesores, aviso)

    @staticmethod
    def _cell(
        turnos: dict[tuple[str, int, int], Supervision], area: str, slot: SupervisionSlot
    ) -> SupervisionCell:
        s = turnos.get((area, slot.day, slot.period))
        if s is None:
            return SupervisionCell(area, slot.day, slot.period, exists=False)
        return SupervisionCell(
            area=area,
            day=slot.day,
            period=slot.period,
            teacher=s.teacher,
            fixed=s.fixed,
            minutes=s.minutes or slot.minutes,
        )

    def build_supervision_shifts(self, session: UntisSession, grid_id: str = "") -> EditResult:
        """Crea los turnos vacíos que falten: uno por zona, día y recreo.

        No toca los que ya existen, así que se puede volver a pulsar después de
        añadir una zona o un recreo sin perder lo repartido.
        """
        p = session.project
        grid = _grid(p, grid_id)
        if grid is None:
            return EditResult.failure("El proyecto no tiene rejillas de tiempo")
        recreos = _breaks(grid)
        if not recreos:
            return EditResult.failure(
                f"La rejilla {grid.display_name!r} no tiene recreos: márcalos en Rejillas de tiempo"
            )
        zonas = _areas_of_grid(p, grid)
        if not zonas:
            return EditResult.failure("Crea antes alguna zona que vigilar")
        existentes = {s.key for s in p.supervisions}
        nuevos = [
            Supervision(area=a.id, day=d, period=per.number)
            for a in zonas
            for d in sorted(grid.days)
            for per in recreos
            if (a.id, d, per.number) not in existentes
        ]
        if not nuevos:
            return EditResult.success("La parrilla ya estaba completa")
        session.apply(
            _with_supervisions(p, (*p.supervisions, *nuevos)),
            f"Generar guardias de {grid.id}",
        )
        return EditResult.success(f"{len(nuevos)} turno(s) de guardia creados")

    def add_supervision(
        self, session: UntisSession, area: str, day: int, period: int, *, minutes: int = 0
    ) -> EditResult:
        """Añade un turno suelto a una zona en un recreo concreto."""
        p = session.project
        zona = p.area_by_id.get(area)
        if zona is None:
            return EditResult.failure(f"No existe la zona {area!r}")
        fallo = self._check_slot(p, zona, day, period)
        if fallo is not None:
            return fallo
        if (area, day, period) in {s.key for s in p.supervisions}:
            return EditResult.failure(
                f"La zona {area!r} ya tiene turno ese día en el recreo {period}"
            )
        try:
            turno = Supervision(area=area, day=day, period=period, minutes=minutes)
        except ValueError as exc:
            return EditResult.failure(str(exc))
        session.apply(_with_supervisions(p, (*p.supervisions, turno)), f"Añadir guardia en {area}")
        return EditResult.success()

    def remove_supervision(
        self, session: UntisSession, area: str, day: int, period: int
    ) -> EditResult:
        """Quita un turno de la parrilla."""
        p = session.project
        restantes = tuple(s for s in p.supervisions if s.key != (area, day, period))
        if len(restantes) == len(p.supervisions):
            return EditResult.failure(f"No hay turno de {area!r} ese día en el recreo {period}")
        session.apply(_with_supervisions(p, restantes), f"Quitar guardia de {area}")
        return EditResult.success()

    @staticmethod
    def _check_slot(
        project: UntisProject, area: SupervisionArea, day: int, period: int
    ) -> EditResult | None:
        """Comprueba que ese día y ese recreo existen en la rejilla de la zona."""
        grid = grid_of_area(project, area)
        if grid is None:
            return EditResult.failure(f"La zona {area.id!r} no tiene rejilla de tiempo")
        if day not in grid.days:
            return EditResult.failure(f"La rejilla {grid.id!r} no tiene el día {day}")
        definicion = grid.period(period)
        if definicion is None or definicion.kind is not PeriodKind.BREAK:
            return EditResult.failure(
                f"El período {period} no es un recreo de la rejilla {grid.id!r}"
            )
        return None

    # --- asignación a mano ------------------------------------------------------ #

    def set_supervision_teacher(
        self,
        session: UntisSession,
        area: str,
        day: int,
        period: int,
        teacher: str,
        *,
        fixed: bool = True,
    ) -> EditResult:
        """Pone (o quita, con `teacher=""`) el profesor de un turno.

        Lo puesto a mano queda fijado, que es lo que hace Untis: el reparto
        automático lo respeta. Si con esto el profesor se pasa de su máximo
        semanal, se avisa en el mensaje pero se hace igual.
        """
        p = session.project
        zona = p.area_by_id.get(area)
        if zona is None:
            return EditResult.failure(f"No existe la zona {area!r}")
        turno = next((s for s in p.supervisions if s.key == (area, day, period)), None)
        if turno is None:
            return EditResult.failure(f"No hay turno de {area!r} ese día en el recreo {period}")
        nombre = teacher.strip()
        if nombre and nombre not in p.teacher_by_id:
            return EditResult.failure(f"No existe el profesor {nombre!r}")
        if nombre and any(
            s.teacher == nombre and s.slot == (day, period) and s.area != area
            for s in p.supervisions
        ):
            return EditResult.failure(
                f"{nombre} ya vigila otra zona en ese recreo; nadie puede estar en dos sitios"
            )
        nuevo = dataclasses.replace(turno, teacher=nombre, fixed=bool(nombre) and fixed)
        etiqueta = f"Guardia de {area}" if nombre else f"Quitar guardia de {area}"
        session.apply(
            _with_supervisions(
                p, tuple(nuevo if s.key == turno.key else s for s in p.supervisions)
            ),
            etiqueta,
        )
        return EditResult.success(self._over_max_warning(session.project, nombre))

    def clear_supervision_teacher(
        self, session: UntisSession, area: str, day: int, period: int
    ) -> EditResult:
        """Deja el turno sin profesor (vuelve al reparto automático)."""
        return self.set_supervision_teacher(session, area, day, period, "")

    def set_supervision_fixed(
        self, session: UntisSession, area: str, day: int, period: int, fixed: bool
    ) -> EditResult:
        """Fija o suelta un turno: lo fijado no lo mueve el reparto automático."""
        p = session.project
        turno = next((s for s in p.supervisions if s.key == (area, day, period)), None)
        if turno is None:
            return EditResult.failure(f"No hay turno de {area!r} ese día en el recreo {period}")
        if fixed and not turno.teacher:
            return EditResult.failure("Un turno sin profesor no se puede fijar")
        nuevo = dataclasses.replace(turno, fixed=fixed)
        session.apply(
            _with_supervisions(
                p, tuple(nuevo if s.key == turno.key else s for s in p.supervisions)
            ),
            f"{'Fijar' if fixed else 'Soltar'} guardia de {area}",
        )
        return EditResult.success()

    @staticmethod
    def _over_max_warning(project: UntisProject, teacher: str) -> str:
        """Aviso si el profesor se pasa de sus minutos de guardia a la semana."""
        if not teacher:
            return ""
        prof = project.teacher_by_id.get(teacher)
        if prof is None or prof.supervision_max is None:
            return ""
        minutos = _minutes_by_teacher(project).get(teacher, 0)
        if minutos <= prof.supervision_max:
            return ""
        return (
            f"Aviso: {teacher} llega a {minutos} min de guardia y su máximo es "
            f"{prof.supervision_max} min"
        )

    # --- reparto automático -------------------------------------------------- #

    def distribute_supervisions(
        self,
        session: UntisSession,
        *,
        timetable_id: str | None = None,
        seed: int = 0,
    ) -> EditResult:
        """Reparte los turnos sin profesor sobre el horario activo.

        Hace falta un horario: un profesor solo puede vigilar un recreo si ese
        día da clase justo antes o justo después.
        """
        p = session.project
        if not p.supervisions:
            return EditResult.failure("No hay turnos de guardia: genera antes la parrilla")
        elegido = timetable_id if timetable_id is not None else session.active_timetable
        horario = p.timetable_by_id(elegido) if elegido else None
        if horario is None:
            horario = p.timetables[0] if p.timetables else None
        if horario is None:
            return EditResult.failure(
                "Hace falta un horario generado para saber quién está en el colegio"
            )
        resultado = assign_supervisions(p, horario, seed=seed)
        session.apply(_with_supervisions(p, resultado.supervisions), "Repartir guardias")
        cubiertos = resultado.assigned
        mensaje = f"{cubiertos} de {resultado.total} turno(s) con profesor"
        if resultado.uncovered:
            mensaje += f"; {resultado.uncovered} sin cubrir (nadie disponible)"
        return EditResult.success(mensaje)

    # --- resumen por profesor --------------------------------------------------- #

    def supervision_load(self, session: UntisSession) -> tuple[SupervisionLoad, ...]:
        """Minutos de guardia de cada profesor frente a su máximo.

        Salen los que tienen algún turno y los que tienen máximo declarado
        (aunque aún no vigilen nada), de más cargado a menos.
        """
        p = session.project
        minutos = _minutes_by_teacher(p)
        turnos: dict[str, int] = {}
        for s in p.supervisions:
            if s.teacher:
                turnos[s.teacher] = turnos.get(s.teacher, 0) + 1
        cargas = [
            SupervisionLoad(
                teacher=t.id,
                name=t.display_name,
                minutes=minutos.get(t.id, 0),
                shifts=turnos.get(t.id, 0),
                maximum=t.supervision_max,
            )
            for t in p.teachers
            if minutos.get(t.id, 0) or t.supervision_max is not None
        ]
        return tuple(sorted(cargas, key=lambda c: (-c.minutes, c.teacher)))


class SupervisionFacade(SupervisionMixin):
    """El mixin a solas, para usarlo antes de que `UntisService` lo herede."""
