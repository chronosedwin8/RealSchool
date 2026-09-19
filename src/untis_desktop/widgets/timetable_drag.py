"""Arrastrar y soltar clases dentro de una cuadrícula de horario.

La máquina de arrastre que estrenó el Diálogo de planificación, aquí sola y sin
ventana, para que la usen tanto ese diálogo como la ventana Horarios (que es
donde la gente mira el horario y espera poder moverlo, como en Untis).

- `MoveDragController` guarda el arrastre en curso (qué sesión, desde qué
  celda, qué destinos dio la Fachada y qué cambios de evaluación se han
  calculado ya), pinta ese estado en la tabla y, al soltar, mueve con
  `move_session`, que comprueba las duras y se puede deshacer con Ctrl+Z.
  Los destinos se piden una sola vez por arrastre y el cambio de evaluación
  (`move_delta`) solo al pasar por encima y una vez por celda: cuesta ~0,1 s en
  un colegio real.
- `MoveDragTable` es una `QTableWidget` que traduce el ratón y Esc a métodos
  del controlador. Cada ventana solo le dice cómo pasar de celda de la tabla a
  `(día, período)` y qué lección hay en cada celda.

Los textos se traducen en el contexto del Diálogo de planificación
(`PlanningWindow`), que es donde nacieron y donde el `.ts` ya los tiene: así
las dos ventanas dicen lo mismo en español y en alemán.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QCoreApplication, QMimeData, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from scheduling_platform.application import EditResult, UntisMoveTarget

from ..qt_bridge import FacadeBridge
from ..theme import TARGET_NO_COLOR, TARGET_OK_COLOR
from .timetable_cells import DELTA_ROLE

#: Tipo MIME del arrastre de una sesión (solo dentro de la aplicación).
MIME_SESSION = "application/x-realschool-session"

#: Espera antes de calcular el cambio de evaluación al pasar el ratón (ms).
HOVER_DELAY_MS = 120

#: Contexto de traducción de los textos del arrastre (ver la cabecera).
TR_CONTEXT = "PlanningWindow"

Cell = tuple[int, int]
"""`(día, período)`."""


def _tr(text: str) -> str:
    return QCoreApplication.translate(TR_CONTEXT, text)


@dataclass(slots=True)
class DragState:
    """Arrastre en curso: la sesión, sus destinos y la caché de cambios."""

    lesson: int
    source: Cell | None
    targets: dict[Cell, UntisMoveTarget]
    deltas: dict[Cell, int | None] = field(default_factory=dict)


class MoveDragController(QObject):
    """Mover una sesión arrastrándola: destinos, colores, cambio y soltar.

    La ventana que la usa aporta:

    - `cell_of(fila, columna)` y `position_of(día, período)`, las dos
      traducciones entre la tabla y la rejilla horaria (`None` en los recreos y
      fuera de la cuadrícula);
    - `repaint(celda)`, que repinta esa celda, o toda la tabla si es `None`;
    - `lesson_at(día, período)`, la lección que hay en esa celda (si la hay);
    - `message(texto)`, dónde se enseña el cambio de evaluación;
    - `after_move(celda)`, qué refrescar cuando el movimiento sale bien;
    - `shown_timetable()`, el horario que se está viendo: si no es el activo no
      se arrastra nada (tampoco si no hay proyecto abierto).
    """

    def __init__(
        self,
        table: QTableWidget,
        bridge: FacadeBridge,
        cell_of: Callable[[int, int], Cell | None],
        position_of: Callable[[int, int], tuple[int, int] | None],
        *,
        repaint: Callable[[Cell | None], None],
        lesson_at: Callable[[int, int], int | None] | None = None,
        message: Callable[[str], None] | None = None,
        after_move: Callable[[Cell], None] | None = None,
        shown_timetable: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__(table)
        self.table = table
        self.bridge = bridge
        self.cell_of = cell_of
        self.position_of = position_of
        self._repaint = repaint
        self._lesson_at = lesson_at
        self._message = message
        self._after_move = after_move
        self._shown = shown_timetable
        self._state: DragState | None = None
        self._hover: Cell | None = None
        self._pending: Cell | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(HOVER_DELAY_MS)
        self._timer.timeout.connect(self._hover_pending)

    # --- estado ------------------------------------------------------------ #

    @property
    def state(self) -> DragState | None:
        """Arrastre en curso, o `None` si no se está arrastrando nada."""
        return self._state

    @property
    def hover_cell(self) -> Cell | None:
        """Celda sobre la que está el ratón durante el arrastre."""
        return self._hover

    @property
    def enabled(self) -> bool:
        """`True` si se puede arrastrar: hay sesión y se ve el horario activo."""
        if not self.bridge.has_session:
            return False
        visto = self._shown() if self._shown is not None else None
        return visto is None or visto == self.bridge.session.active_timetable

    def targets(self) -> dict[Cell, UntisMoveTarget]:
        """Destinos del arrastre en curso (vacío si no se arrastra)."""
        return dict(self._state.targets) if self._state is not None else {}

    def lesson_at(self, day: int, period: int) -> int | None:
        return self._lesson_at(day, period) if self._lesson_at is not None else None

    def _timetable_id(self) -> str | None:
        return self._shown() if self._shown is not None else None

    def _say(self, text: str) -> None:
        if self._message is not None:
            self._message(text)

    def _touch(self, cell: Cell | None) -> None:
        """Repinta una celda concreta (nada si no hay celda)."""
        if cell is not None:
            self._repaint(cell)

    # --- empezar ----------------------------------------------------------- #

    def begin(self, lesson: int, cell: Cell | None) -> tuple[UntisMoveTarget, ...]:
        """Empieza a arrastrar una sesión: pide (una vez) los destinos y los pinta."""
        self.reset()
        if not self.enabled:
            return ()
        objetivos = self.bridge.service.move_targets(
            self.bridge.session, lesson, cell, self._timetable_id()
        )
        self._state = DragState(lesson, cell, {(t.day, t.period): t for t in objetivos})
        self._repaint(None)
        posibles = sum(1 for t in objetivos if t.feasible)
        self._say(_tr("Lección {0}: {1} destino(s) posible(s)").format(lesson, posibles))
        return objetivos

    def begin_at(self, cell: Cell) -> tuple[UntisMoveTarget, ...]:
        """Empieza a arrastrar la clase que hay en una celda (si hay alguna)."""
        leccion = self.lesson_at(*cell)
        return () if leccion is None else self.begin(leccion, cell)

    # --- pasar por encima --------------------------------------------------- #

    def hover(self, day: int, period: int) -> int | None:
        """El ratón pasa sobre una celda durante el arrastre: cambio de evaluación.

        Solo se calcula para destinos posibles y una vez por celda y arrastre.
        """
        estado = self._state
        if estado is None:
            return None
        anterior = self._hover
        self._hover = (day, period)
        self._touch(anterior)
        objetivo = estado.targets.get((day, period))
        if objetivo is None or not objetivo.feasible:
            motivo = objetivo.reason if objetivo is not None else _tr("fuera de la rejilla")
            self._say(_tr("No cabe: {0}").format(motivo))
            self._touch(self._hover)
            return None
        if (day, period) not in estado.deltas:
            estado.deltas[(day, period)] = self.bridge.service.move_delta(
                self.bridge.session,
                estado.lesson,
                estado.source,
                (day, period),
                self._timetable_id(),
            )
        delta = estado.deltas[(day, period)]
        if delta is None:
            self._say(_tr("Destino posible"))
        else:
            self._say(_tr("Cambio de evaluación: {0:+d}").format(delta))
        self._touch(self._hover)
        return delta

    def hover_later(self, cell: Cell | None) -> None:
        """Programa `hover` tras una espera corta (el ratón puede seguir de largo)."""
        self._pending = cell
        if cell is None:
            self._timer.stop()
            anterior = self._hover
            self._hover = None
            self._touch(anterior)
        else:
            self._timer.start()

    def _hover_pending(self) -> None:
        if self._pending is not None:
            self.hover(*self._pending)

    # --- soltar y cancelar --------------------------------------------------- #

    def drop_on(self, day: int, period: int) -> EditResult:
        """Suelta la sesión arrastrada en una celda."""
        estado = self._state
        if estado is None:
            return EditResult.failure(_tr("No se está arrastrando nada"))
        self.end()
        destino = (day, period)
        if destino == estado.source:
            return EditResult.success()
        objetivo = estado.targets.get(destino)
        if objetivo is None:
            mensaje = _tr("Esa celda no es un destino de la sesión")
            self.bridge.status.emit(mensaje)
            return EditResult.failure(mensaje)
        if not objetivo.feasible:
            mensaje = _tr("No cabe: {0}").format(objetivo.reason)
            self.bridge.status.emit(mensaje)
            return EditResult.failure(mensaje)
        s = self.bridge.session
        tt = self._timetable_id()
        resultado = self.bridge.edit(
            lambda: self.bridge.service.move_session(s, estado.lesson, estado.source, destino, tt)
        )
        if resultado.ok and self._after_move is not None:
            self._after_move(destino)
        return resultado

    def end(self) -> None:
        """Termina el arrastre y quita los colores de destino."""
        self._timer.stop()
        self._hover = None
        self._pending = None
        if self._state is not None:
            self._state = None
            self._repaint(None)

    def reset(self) -> None:
        """Olvida el arrastre sin repintar (proyecto nuevo, cambio de entidad)."""
        self._timer.stop()
        self._hover = None
        self._pending = None
        self._state = None

    def run(self, source: QWidget | None = None) -> None:
        """Arrastre real con `QDrag` (bucle de eventos propio de Qt)."""
        if self._state is None:
            return
        mime = QMimeData()
        mime.setData(MIME_SESSION, str(self._state.lesson).encode("ascii"))
        arrastre = QDrag(source if source is not None else self.table)
        arrastre.setMimeData(mime)
        arrastre.exec(Qt.DropAction.MoveAction)
        self.end()

    # --- pintura -------------------------------------------------------------- #

    def decorate(
        self, item: QTableWidgetItem, cell: Cell, background: QColor, tooltip: list[str]
    ) -> tuple[QColor, str]:
        """Añade a una celda el estado del arrastre: `(fondo, marca)`.

        Deja en `item` el cambio de evaluación que pinta el delegado y añade a
        `tooltip` el motivo por el que la clase cabe o no cabe ahí.
        """
        item.setData(DELTA_ROLE, None)
        estado = self._state
        if estado is None:
            return background, ""
        marca = "source" if cell == estado.source else ""
        objetivo = estado.targets.get(cell)
        if objetivo is not None:
            background = QColor(TARGET_OK_COLOR if objetivo.feasible else TARGET_NO_COLOR)
            if objetivo.feasible:
                delta = estado.deltas.get(cell)
                if delta is None:
                    tooltip.append(_tr("Destino posible"))
                else:
                    item.setData(DELTA_ROLE, delta)
                    tooltip.append(_tr("Cambio de evaluación: {0:+d}").format(delta))
            else:
                tooltip.append(_tr("No cabe: {0}").format(objetivo.reason))
            if objetivo.warning:
                tooltip.append(_tr("Ojo: {0}").format(objetivo.warning))
        if not marca and cell == self._hover:
            marca = "hover"
        return background, marca


class MoveDragTable(QTableWidget):
    """Cuadrícula de horario que se puede mover con el ratón.

    Solo traduce eventos a métodos del controlador (`begin_at`, `hover_later`,
    `drop_on`, `end`), que son los que ejercitan las pruebas sin ratón real.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.dragger: MoveDragController | None = None
        self._press: QPoint | None = None
        self._press_cell: Cell | None = None
        self._hover_cell: Cell | None = None
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(False)

    def cell_at(self, pos: QPoint) -> Cell | None:
        """`(día, período)` de la celda que hay bajo un punto del ratón."""
        if self.dragger is None:
            return None
        index = self.indexAt(pos)
        return self.dragger.cell_of(index.row(), index.column()) if index.isValid() else None

    def start_drag(self, cell: Cell) -> bool:
        """Empieza a arrastrar la clase de una celda; `False` si no hay nada que mover."""
        dragger = self.dragger
        if dragger is None or not dragger.begin_at(cell):
            return False
        dragger.run(self)
        return True

    # --- ratón ---------------------------------------------------------------- #

    def mousePressEvent(self, event: QMouseEvent) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self._press_cell = self.cell_at(self._press)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._press is not None
            and self._press_cell is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._press).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            celda = self._press_cell
            self._press = None
            self._press_cell = None
            self.start_drag(celda)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press = None
        self._press_cell = None
        super().mouseReleaseEvent(event)

    # --- arrastrar y soltar ------------------------------------------------------ #

    def _dragging(self) -> bool:
        return self.dragger is not None and self.dragger.state is not None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(MIME_SESSION) and self._dragging():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self.dragger is None or not self._dragging():
            event.ignore()
            return
        celda = self.cell_at(event.position().toPoint())
        if celda != self._hover_cell:
            self._hover_cell = celda
            self.dragger.hover_later(celda)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._hover_cell = None
        if self.dragger is not None:
            self.dragger.hover_later(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._hover_cell = None
        dragger = self.dragger
        celda = self.cell_at(event.position().toPoint())
        if dragger is None or celda is None or dragger.state is None:
            event.ignore()
            if dragger is not None:
                dragger.end()
            return
        if dragger.drop_on(*celda).ok:
            event.acceptProposedAction()
        else:
            event.ignore()

    # --- teclado ------------------------------------------------------------------ #

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self.dragger is not None:
            self.dragger.end()
            return
        super().keyPressEvent(event)
