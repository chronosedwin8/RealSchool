"""Modelos de vista de la Fachada Untis: datos listos para pintar, sin Qt.

La UI (`untis_desktop`) solo ve estas estructuras y la Fachada; nunca el modelo
de dominio directamente. Todo es inmutable y serializable a texto.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .columns import ColumnSpec, MasterKind

# --------------------------------------------------------------------------- #
# Resultados de operaciones
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EditResult:
    """Resultado de una edición: la UI pinta la celda en rojo si `ok` es falso."""

    ok: bool
    message: str = ""

    @classmethod
    def success(cls, message: str = "") -> EditResult:
        return cls(True, message)

    @classmethod
    def failure(cls, message: str) -> EditResult:
        return cls(False, message)


# --------------------------------------------------------------------------- #
# Datos maestros
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class MasterRow:
    """Una fila de una cuadrícula de datos maestros."""

    key: str
    cells: tuple[str, ...]
    issues: tuple[str, ...] = field(default_factory=tuple)
    """Hallazgos del diagnóstico de datos sobre esta entidad."""


@dataclass(frozen=True, slots=True)
class MasterTable:
    """Una ventana de datos maestros: columnas y filas."""

    kind: MasterKind
    columns: tuple[ColumnSpec, ...]
    rows: tuple[MasterRow, ...]
    references: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """Valores posibles de cada columna de referencia (desplegables)."""


# --------------------------------------------------------------------------- #
# Rejillas de tiempo
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PeriodRow:
    """Un período de una rejilla, como lo edita la ventana Rejilla."""

    number: int
    start: str
    """`HH:MM`."""
    end: str
    is_break: bool
    afternoon: bool


@dataclass(frozen=True, slots=True)
class GridView:
    """Una rejilla de tiempo: una pestaña de la ventana Rejilla."""

    id: str
    name: str
    days: tuple[int, ...]
    periods: tuple[PeriodRow, ...]
    classes: tuple[str, ...]
    """Clases que usan esta rejilla."""


# --------------------------------------------------------------------------- #
# Lecciones
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LessonLineRow:
    """Una línea de un acople (una sub-fila de la ventana Lecciones)."""

    index: int
    teacher: str
    subject: str
    classes: str
    student_group: str
    room: str


@dataclass(frozen=True, slots=True)
class LessonRow:
    """Una lección en la ventana Lecciones (columnas estilo Untis)."""

    number: int
    lines: tuple[LessonLineRow, ...]
    periods_per_week: int
    placed: int
    double_periods: str
    block: str
    time_grid: str
    fixed: bool
    ignore: bool
    not_same_day: bool
    weekly_value: float

    @property
    def is_coupled(self) -> bool:
        return len(self.lines) > 1

    @property
    def unplaced(self) -> int:
        return max(0, self.periods_per_week - self.placed)


@dataclass(frozen=True, slots=True)
class LoadSummary:
    """Barra de suma de la ventana Lecciones: períodos frente a carga."""

    entity_kind: str
    entity_id: str
    periods: int
    placed: int
    capacity: int
    """Celdas lectivas de la rejilla de la entidad (tope semanal)."""

    @property
    def overloaded(self) -> bool:
        return self.capacity > 0 and self.periods > self.capacity


# --------------------------------------------------------------------------- #
# Deseos de tiempo
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RequestGrid:
    """Rejilla días x períodos con los valores -3..+3 de una entidad."""

    entity_kind: str
    entity_id: str
    days: tuple[int, ...]
    periods: tuple[int, ...]
    values: dict[tuple[int, int], int]
    """`(día, período) -> valor`; las celdas sin deseo no aparecen (valor 0)."""
    day_values: dict[int, int] = field(default_factory=dict)
    """Deseo de día completo."""
    breaks: tuple[int, ...] = field(default_factory=tuple)

    def value(self, day: int, period: int) -> int:
        return self.values.get((day, period), 0)


# --------------------------------------------------------------------------- #
# Ponderación
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SliderView:
    """Un deslizador 0-5 de la ventana Ponderación."""

    criterion: str
    label: str
    label_de: str
    help: str
    value: int
    weight: int


@dataclass(frozen=True, slots=True)
class WeightingTabView:
    """Una pestaña de la ventana Ponderación."""

    tab: str
    label: str
    label_de: str
    sliders: tuple[SliderView, ...]


# --------------------------------------------------------------------------- #
# Evaluación y Diagnóstico
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CriterionLine:
    """Una línea de la ventana Evaluación / pestaña Análisis."""

    criterion: str
    label: str
    tab: str
    slider: int
    weight: int
    violations: int
    points: int


@dataclass(frozen=True, slots=True)
class EvaluationView:
    """Número de evaluación y su desglose, para un horario."""

    timetable_id: str
    total: int
    soft_points: int
    unplaced_periods: int
    clashes: int
    criteria: tuple[CriterionLine, ...]


@dataclass(frozen=True, slots=True)
class DiagnosisItem:
    """Un nodo hoja del árbol de Diagnóstico, con su salto."""

    branch: str
    """`datos` o `horario`."""
    group: str
    """Criterio o código de hallazgo."""
    severity: str
    message: str
    amount: int = 1
    entity_kind: str = ""
    entity_id: str = ""
    lesson: int | None = None
    day: int | None = None
    period: int | None = None


@dataclass(frozen=True, slots=True)
class DiagnosisView:
    """Árbol de Diagnóstico: datos de entrada y horario."""

    items: tuple[DiagnosisItem, ...]

    @property
    def errors(self) -> int:
        return sum(1 for i in self.items if i.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for i in self.items if i.severity == "warning")


# --------------------------------------------------------------------------- #
# Horarios y planificación
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class TimetableSummary:
    """Una versión de horario en la lista de horarios generados."""

    id: str
    name: str
    total: int
    unplaced: int
    clashes: int
    active: bool


@dataclass(frozen=True, slots=True)
class TimetableCell:
    """Una celda de la vista de horario de una clase/profesor/aula."""

    day: int
    period: int
    lesson: int
    subject: str
    teachers: tuple[str, ...]
    classes: tuple[str, ...]
    rooms: tuple[str, ...]
    fixed: bool = False
    conflict: bool = False
    color: str = ""


@dataclass(frozen=True, slots=True)
class TimetableGrid:
    """Horario de una entidad: días x períodos de su rejilla."""

    entity_kind: str
    entity_id: str
    title: str
    days: tuple[int, ...]
    periods: tuple[PeriodRow, ...]
    cells: tuple[TimetableCell, ...]
    unplaced: tuple[tuple[int, int], ...] = field(default_factory=tuple)
    """`(lección, períodos sin colocar)` de la entidad: lista del Diálogo de planificación."""

    def at(self, day: int, period: int) -> tuple[TimetableCell, ...]:
        return tuple(c for c in self.cells if c.day == day and c.period == period)


@dataclass(frozen=True, slots=True)
class MoveTarget:
    """Coste de soltar una sesión en una celda (Diálogo de planificación)."""

    day: int
    period: int
    feasible: bool
    reason: str = ""
    delta: int | None = None
    """Cambio del número de evaluación si se mueve ahí (`None` si no se calculó)."""


# --------------------------------------------------------------------------- #
# Optimización
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OptimizeRequest:
    """Datos de control del diálogo de Optimización."""

    strategy: str = "A"
    """`A`, `B`, `D`, `E` o `repair`."""
    time_limit: float | None = None
    seed: int = 0
    placement_share: float = 1.0
    optimize_teachers: bool = False
    polish: bool = True
    name: str = ""


@dataclass(frozen=True, slots=True)
class OptimizeProgress:
    """Evento de progreso para la ventana de Optimización."""

    phase: str
    iteration: int
    current: int
    best: int
    unplaced: int
    elapsed: float


@dataclass(frozen=True, slots=True)
class OptimizeOutcome:
    """Resultado del diálogo de Optimización. Nunca lanza: el error va aquí."""

    ok: bool
    status: str
    """`solved`, `cancelled` o `error`."""
    message: str
    timetable_id: str = ""
    evaluation: EvaluationView | None = None
    elapsed: float = 0.0
    log: tuple[str, ...] = field(default_factory=tuple)
