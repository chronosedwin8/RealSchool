"""Celdas de horario compartidas por el Diálogo de planificación y la ventana Horarios.

- Roles de datos que lee el delegado (choque, fijada, cambio de evaluación,
  marca de arrastre).
- `TimetableCellDelegate`: pinta encima de la celda normal el borde rojo del
  choque, la chincheta de las lecciones fijadas, la marca del origen del
  arrastre y el cambio del número de evaluación.
- `readable_colors`: fondo de la materia y el color de texto que se lee sobre él.
- `cell_tooltip`: toda la información de la celda en la ayuda emergente.
- `legend_items`: la leyenda de colores y marcas.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QModelIndex, QPersistentModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from scheduling_platform.application import UntisTimetableCell

from ..icons import icon
from ..theme import CONFLICT_COLOR, TARGET_NO_COLOR, TARGET_OK_COLOR, subject_color, text_color_for
from .uikit import Swatch

#: Roles de datos que lee el delegado.
CONFLICT_ROLE = Qt.ItemDataRole.UserRole + 1
FIXED_ROLE = Qt.ItemDataRole.UserRole + 2
DELTA_ROLE = Qt.ItemDataRole.UserRole + 3
MARK_ROLE = Qt.ItemDataRole.UserRole + 4
"""Marca de la celda: `source` (origen del arrastre o del intercambio) o `hover`."""

_CONTEXT = "TimetableCells"


def _tr(text: str) -> str:
    return QCoreApplication.translate(_CONTEXT, text)


def readable_colors(
    cells: Sequence[UntisTimetableCell], *, colors: bool = True
) -> tuple[QColor, QColor]:
    """`(fondo, texto)` de una celda: color de la materia y texto legible encima."""
    fondo = (
        subject_color(cells[0].subject, cells[0].color) if cells and colors else QColor("#ffffff")
    )
    return fondo, text_color_for(fondo)


def cell_tooltip(cells: Sequence[UntisTimetableCell]) -> str:
    """Ayuda emergente con toda la información de las lecciones de una celda."""
    bloques: list[str] = []
    for c in cells:
        lineas = [_tr("Lección {0}: {1}").format(c.lesson, c.subject)]
        if c.teachers:
            lineas.append(_tr("Profesores: {0}").format(", ".join(c.teachers)))
        if c.classes:
            lineas.append(_tr("Clases: {0}").format(", ".join(c.classes)))
        if c.rooms:
            lineas.append(_tr("Aulas: {0}").format(", ".join(c.rooms)))
        if c.fixed:
            lineas.append(_tr("Fijada: la optimización no la mueve"))
        if c.conflict:
            lineas.append(_tr("Choque: un profesor, clase o aula está ocupado dos veces"))
        bloques.append("\n".join(lineas))
    return "\n\n".join(bloques)


def legend_items(*, targets: bool) -> list[tuple[Swatch, str]]:
    """Leyenda: destinos (solo al planificar), choque y fijada."""
    items: list[tuple[Swatch, str]] = []
    if targets:
        items.append((("fill", TARGET_OK_COLOR), _tr("Puede ir aquí")))
        items.append((("fill", TARGET_NO_COLOR), _tr("No cabe")))
    items.append((("outline", CONFLICT_COLOR), _tr("Choque")))
    items.append((("icon", "fix"), _tr("Fijada")))
    return items


class TimetableCellDelegate(QStyledItemDelegate):
    """Pinta sobre la celda normal: choque, fijada, origen y cambio de evaluación."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        rect: QRect = option.rect
        painter.save()
        if index.data(FIXED_ROLE):
            painter.setPen(QPen(QColor("#1f2937"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(2, 2, -2, -2))
            lado = 14
            chincheta = QRect(rect.right() - lado - 3, rect.top() + 3, lado, lado)
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(chincheta.adjusted(-1, -1, 1, 1))
            icon("fix").paint(painter, chincheta)
        if index.data(CONFLICT_ROLE):
            painter.setPen(QPen(QColor(CONFLICT_COLOR), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -2, -2))
        marca = index.data(MARK_ROLE)
        if marca in ("source", "hover"):
            color = "#2563eb" if marca == "source" else "#111827"
            painter.setPen(QPen(QColor(color), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(3, 3, -4, -4))
        delta = index.data(DELTA_ROLE)
        if isinstance(delta, int):
            painter.setPen(QPen(QColor("#065f46" if delta <= 0 else "#991b1b")))
            painter.drawText(
                rect.adjusted(3, 2, -3, -2),
                int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight),
                f"{delta:+d}",
            )
        painter.restore()
