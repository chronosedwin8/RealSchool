"""Parser del XML nativo de Untis (XmlInterface 3.0).

Lee un export real de Untis y lo convierte en entidades planas. No interpreta ni
modela nada: solo lee. La interpretación (co-docencia, clases acopladas, pools de
aula) vive en el adaptador.

El export incluye ``<times>``: **el horario que Untis generó**. Se conserva,
porque es la referencia contra la que se compara nuestro motor.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

NS = {"u": "https://untis.at/untis/XmlInterface"}


@dataclass(frozen=True, slots=True)
class UntisRoom:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class UntisTeacher:
    id: str
    name: str
    department: str = ""


@dataclass(frozen=True, slots=True)
class UntisSubject:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class UntisClass:
    id: str
    name: str
    timegrid: str = ""


@dataclass(frozen=True, slots=True)
class UntisTime:
    """Una sesión ya ubicada por Untis."""

    day: int
    period: int
    room_id: str | None


@dataclass(frozen=True, slots=True)
class UntisLesson:
    id: str
    periods: int
    subject_id: str | None
    teacher_id: str | None
    class_ids: tuple[str, ...]
    studentgroup_id: str | None
    timegrid: str
    times: tuple[UntisTime, ...] = ()


@dataclass(frozen=True, slots=True)
class UntisPeriod:
    """Un período de una jornada, con su hora de reloj real."""

    timegrid: str
    day: int
    period: int
    start_min: int
    """Minutos desde medianoche."""
    end_min: int

    @property
    def duration(self) -> int:
        return self.end_min - self.start_min


@dataclass(frozen=True, slots=True)
class UntisExport:
    """Contenido completo de un export de Untis."""

    school: str
    rooms: tuple[UntisRoom, ...]
    teachers: tuple[UntisTeacher, ...]
    subjects: tuple[UntisSubject, ...]
    classes: tuple[UntisClass, ...]
    lessons: tuple[UntisLesson, ...]
    periods: tuple[UntisPeriod, ...]
    days: int
    periods_per_day: int
    timegrids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_periods(self) -> int:
        """Clases a ubicar en la semana (una por período de cada lección)."""
        return sum(lesson.periods for lesson in self.lessons)

    @property
    def day_start(self) -> int:
        return min(p.start_min for p in self.periods)

    @property
    def day_end(self) -> int:
        return max(p.end_min for p in self.periods)

    def period_at(self, timegrid: str, day: int, period: int) -> UntisPeriod | None:
        for p in self.periods:
            if p.timegrid == timegrid and p.day == day and p.period == period:
                return p
        return None


def _minutes(hhmm: str) -> int:
    """``"0935"`` -> 575 minutos desde medianoche."""
    limpio = hhmm.strip().zfill(4)
    return int(limpio[:2]) * 60 + int(limpio[2:])


def _text(element: ET.Element | None, tag: str, default: str = "") -> str:
    if element is None:
        return default
    node = element.find(f"u:{tag}", NS)
    return node.text if node is not None and node.text else default


def _ref(element: ET.Element, tag: str) -> str | None:
    node = element.find(f"u:{tag}", NS)
    if node is None:
        return None
    value = node.get("id", "").strip()
    return value or None


def _refs(element: ET.Element, tag: str) -> tuple[str, ...]:
    node = element.find(f"u:{tag}", NS)
    if node is None:
        return ()
    raw = node.get("id", "").strip()
    return tuple(part for part in raw.split(" ") if part)


def parse_untis(path: str | Path) -> UntisExport:
    """Lee un ``untis.xml`` y devuelve sus entidades."""
    root = ET.parse(Path(path)).getroot()

    general = root.find("u:general", NS)
    school = _text(general, "header1") or _text(general, "schoolname") or "Institución"

    days: set[int] = set()
    period_numbers: set[int] = set()
    timegrids: set[str] = set()
    periods: list[UntisPeriod] = []
    for tp in root.findall("u:timeperiods/u:timeperiod", NS):
        day = int(_text(tp, "day", "0"))
        number = int(_text(tp, "period", "0"))
        grid = _text(tp, "timegrid")
        days.add(day)
        period_numbers.add(number)
        timegrids.add(grid)
        periods.append(
            UntisPeriod(
                timegrid=grid,
                day=day,
                period=number,
                start_min=_minutes(_text(tp, "starttime", "0000")),
                end_min=_minutes(_text(tp, "endtime", "0000")),
            )
        )

    rooms = tuple(
        UntisRoom(id=r.get("id", ""), name=_text(r, "longname") or r.get("id", ""))
        for r in root.findall("u:rooms/u:room", NS)
    )
    teachers = tuple(
        UntisTeacher(
            id=t.get("id", ""),
            name=_text(t, "forename") or t.get("id", ""),
            department=_text(t, "text"),
        )
        for t in root.findall("u:teachers/u:teacher", NS)
    )
    subjects = tuple(
        UntisSubject(id=s.get("id", ""), name=_text(s, "longname") or s.get("id", ""))
        for s in root.findall("u:subjects/u:subject", NS)
    )
    classes = tuple(
        UntisClass(
            id=c.get("id", ""),
            name=_text(c, "longname") or c.get("id", ""),
            timegrid=_text(c, "timegrid"),
        )
        for c in root.findall("u:classes/u:class", NS)
    )

    lessons: list[UntisLesson] = []
    for ls in root.findall("u:lessons/u:lesson", NS):
        times: list[UntisTime] = []
        times_node = ls.find("u:times", NS)
        if times_node is not None:
            for t in times_node.findall("u:time", NS):
                times.append(
                    UntisTime(
                        day=int(_text(t, "assigned_day", "0")),
                        period=int(_text(t, "assigned_period", "0")),
                        room_id=_ref(t, "assigned_room"),
                    )
                )
        lessons.append(
            UntisLesson(
                id=ls.get("id", ""),
                periods=int(_text(ls, "periods", "0")),
                subject_id=_ref(ls, "lesson_subject"),
                teacher_id=_ref(ls, "lesson_teacher"),
                class_ids=_refs(ls, "lesson_classes"),
                studentgroup_id=_ref(ls, "lesson_studentgroups"),
                timegrid=_text(ls, "timegrid"),
                times=tuple(times),
            )
        )

    return UntisExport(
        school=school,
        rooms=rooms,
        teachers=teachers,
        subjects=subjects,
        classes=classes,
        lessons=tuple(lessons),
        periods=tuple(periods),
        days=max(days) if days else 5,
        periods_per_day=max(period_numbers) if period_numbers else 1,
        timegrids=tuple(sorted(timegrids)),
    )
