"""Lecciones (Unterricht) con acoples explícitos.

Un número de lección con varias líneas **es** un acople (Kopplung). El export
XmlInterface codifica ambas cosas en el id: `LS_<nº lección><línea con 2 cifras>`
(`LS_134500` = lección 1345, línea 00). Verificado con dos cursos reales del
Colegio Alemán: los números así obtenidos coinciden exactamente con los de
`GPU002.TXT` que escribe Untis (884 de 884) y hay acoples de hasta 45 líneas,
todas contiguas 00…n-1 y con horas idénticas. Por eso el acople deja de
inferirse con union-find y pasa a ser dato de entrada.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import UNSET, MinMax

#: Cuántas líneas caben en un número de lección con la codificación de Untis.
LINES_PER_LESSON = 100


def split_lesson_id(raw: str) -> tuple[int, int]:
    """Parte un id `LS_134501` en `(nº de lección, nº de línea)` -> `(1345, 1)`."""
    texto = raw[3:] if raw.startswith("LS_") else raw
    if not texto.isdigit():
        raise ValueError(f"Id de lección no numérico: {raw!r}")
    numero = int(texto)
    return divmod(numero, LINES_PER_LESSON)


def build_lesson_id(number: int, line: int) -> str:
    """Construye el id XmlInterface de una línea: `(1345, 1)` -> `LS_134501`."""
    if not 0 <= line < LINES_PER_LESSON:
        raise ValueError(f"Nº de línea fuera de 0-{LINES_PER_LESSON - 1}: {line}")
    return f"LS_{number * LINES_PER_LESSON + line}"


def double_periods_from_block(block: tuple[int, ...], periods_per_week: int) -> MinMax:
    """Deduce el rango de períodos dobles a partir del campo `block` de Untis.

    Semántica verificada contra las colocaciones reales del Colegio Alemán:

    - `block` vacío: sin exigencia (`UNSET`).
    - todos los valores 2 y más de uno (`"2,2"`): la lección va entera en
      dobles, `periods_per_week // 2` de ellos. Con 2 períodos es un único doble.
    - un solo 2 (`"2"`): al menos un doble, como mucho `periods_per_week // 2`.

    Otras longitudes (bloques de 3+) no aparecen en los datos y se tratan como
    "al menos un bloque", sin fijar el número de dobles.
    """
    if not block or periods_per_week < 2:
        return UNSET
    maximo = periods_per_week // 2
    if all(b == 2 for b in block) and len(block) > 1:
        return MinMax(maximo, maximo)
    if block == (2,):
        return MinMax(1, maximo)
    return UNSET


@dataclass(frozen=True, slots=True)
class LessonLine:
    """Una línea del acople: un profesor en paralelo con los demás.

    `teacher=None` deja el profesor sin fijar y activa la optimización de
    profesores: el motor lo elige del pool habilitado para la materia.
    """

    subject: str
    teacher: str | None = None
    classes: tuple[str, ...] = field(default_factory=tuple)
    student_group: str | None = None
    room: str | None = None
    alternative_room: str | None = None
    weekly_value: float = 0.0
    """Valor semanal (Wochenwert) que esta línea aporta al profesor."""

    def __post_init__(self) -> None:
        if not self.subject:
            raise ValueError("La línea de lección necesita materia")
        if len(set(self.classes)) != len(self.classes):
            raise ValueError(f"Línea con clases repetidas: {self.classes}")

    @property
    def needs_teacher_optimization(self) -> bool:
        """`True` si el profesor está sin asignar y debe elegirlo el motor."""
        return self.teacher is None


@dataclass(frozen=True, slots=True)
class Lesson:
    """Una lección de Untis: un número, N líneas acopladas y sus restricciones."""

    number: int
    lines: tuple[LessonLine, ...]
    periods_per_week: int
    time_grid: str = ""
    double_periods: MinMax = UNSET
    """Cuántos períodos dobles admite la lección (criterio blando ponderado)."""
    block: tuple[int, ...] = field(default_factory=tuple)
    """Campo `block` de Untis tal cual (`"2,2"` → `(2, 2)`), para ida y vuelta.

    No es una lista de tamaños que sumen los períodos: sobre el export real,
    `block="2,2"` aparece con solo 2 períodos/semana y Untis lo coloca como un
    único período doble. Cada valor es una longitud de bloque exigida; el
    requisito operativo para el motor vive en `double_periods`
    (ver `double_periods_from_block`).
    """
    fixed: bool = False
    ignore: bool = False
    not_same_day: bool = False
    sequence_after: str | None = None
    """Materia que debe ir antes que ésta el mismo día (secuencia de materias)."""
    weekly_value: float = 0.0
    term: str | None = None
    lesson_group: str | None = None
    effective_begin: str = ""
    """Fecha `AAAAMMDD` desde la que rige la lección (`effectivebegindate`)."""
    effective_end: str = ""
    """Fecha `AAAAMMDD` hasta la que rige la lección (`effectiveenddate`)."""
    occurrence: str = ""
    """Patrón de ocurrencia por día del curso (elemento `occurence` [sic] del XML)."""

    def __post_init__(self) -> None:
        if self.number < 0:
            raise ValueError(f"Nº de lección negativo: {self.number}")
        if not self.lines:
            raise ValueError(f"Lección {self.number}: sin líneas")
        if len(self.lines) > LINES_PER_LESSON:
            raise ValueError(
                f"Lección {self.number}: {len(self.lines)} líneas, "
                f"el máximo de Untis es {LINES_PER_LESSON}"
            )
        if self.periods_per_week < 0:
            raise ValueError(f"Lección {self.number}: períodos/semana negativo")
        if any(b < 1 for b in self.block):
            raise ValueError(f"Lección {self.number}: bloque de longitud < 1")

    @property
    def id(self) -> str:
        """Id XmlInterface de la primera línea."""
        return build_lesson_id(self.number, 0)

    @property
    def is_coupled(self) -> bool:
        """`True` si la lección tiene más de una línea (acople)."""
        return len(self.lines) > 1

    @property
    def subjects(self) -> tuple[str, ...]:
        """Materias distintas de las líneas, en orden de aparición."""
        return tuple(dict.fromkeys(line.subject for line in self.lines))

    @property
    def teachers(self) -> tuple[str, ...]:
        """Profesores asignados, sin repetir y sin los huecos a optimizar."""
        return tuple(dict.fromkeys(line.teacher for line in self.lines if line.teacher is not None))

    @property
    def classes(self) -> tuple[str, ...]:
        """Todas las clases implicadas por el acople, sin repetir."""
        return tuple(dict.fromkeys(c for line in self.lines for c in line.classes))

    @property
    def student_groups(self) -> tuple[str, ...]:
        """Grupos de alumnos implicados, sin repetir."""
        return tuple(
            dict.fromkeys(
                line.student_group for line in self.lines if line.student_group is not None
            )
        )

    def line_id(self, index: int) -> str:
        """Id XmlInterface de la línea `index`."""
        if not 0 <= index < len(self.lines):
            raise IndexError(f"Lección {self.number}: no existe la línea {index}")
        return build_lesson_id(self.number, index)
