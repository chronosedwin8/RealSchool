"""Piezas comunes de usabilidad para las ventanas: botones con icono, avisos y leyendas.

Todas las ventanas de datos y de horarios usan estas piezas para que se vean y
se comporten igual:

- `tool_button` / `make_action`: botón o acción con su icono semántico
  (`untis_desktop.icons`); el texto y la ayuda emergente se ponen con
  `set_texts`, que se vuelve a llamar al cambiar de idioma.
- `Banner`: franja con icono y texto (ayuda, aviso, error, correcto).
- `EmptyHint`: texto centrado sobre una tabla vacía ("Aún no hay clases...").
- `Legend`: tira de muestras de color con su significado.
- `exempt`: marca un botón cuyo texto ya es su significado (p. ej. la paleta
  -3..+3) para que la prueba de iconos lo deje pasar sin icono.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from ..icons import icon, icon_size
from ..theme import ERROR_COLOR

#: Propiedad dinámica que exime a un botón de llevar icono (con el motivo).
EXEMPT_PROPERTY = "usability_exempt"


def exempt(widget: QObject, reason: str) -> None:
    """Marca un botón cuyo propio texto es su significado (no necesita icono)."""
    widget.setProperty(EXEMPT_PROPERTY, reason)


def tool_button(
    icon_name: str,
    slot: Callable[[], object] | None = None,
    *,
    text_beside: bool = True,
    size: str = "button",
) -> QToolButton:
    """Botón de herramienta con icono y, por defecto, el texto al lado."""
    boton = QToolButton()
    boton.setIcon(icon(icon_name))
    boton.setIconSize(icon_size(size))
    boton.setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        if text_beside
        else Qt.ToolButtonStyle.ToolButtonIconOnly
    )
    if slot is not None:
        boton.clicked.connect(lambda _checked=False: slot())
    return boton


def make_action(
    parent: QObject, icon_name: str, slot: Callable[[], object] | None = None
) -> QAction:
    """Acción (menú, barra) con icono; el texto va aparte con `set_texts`."""
    accion = QAction(icon(icon_name), "", parent)
    if slot is not None:
        accion.triggered.connect(lambda _checked=False: slot())
    return accion


def set_texts(target: QAbstractButton | QAction, text: str, tooltip: str) -> None:
    """Texto visible y ayuda emergente (qué hace, no solo cómo se llama)."""
    target.setText(text)
    target.setToolTip(tooltip)
    if isinstance(target, QAction):
        target.setStatusTip(tooltip)


def icon_pixmap(name: str, size: str = "small") -> QPixmap:
    medida = icon_size(size)
    return icon(name).pixmap(medida)


def icon_label(name: str, size: str = "small") -> QLabel:
    """Etiqueta que solo muestra un icono."""
    etiqueta = QLabel()
    etiqueta.setPixmap(icon_pixmap(name, size))
    etiqueta.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return etiqueta


# --------------------------------------------------------------------------- #
# Franja de aviso
# --------------------------------------------------------------------------- #

#: Tipo de franja -> (icono, fondo, borde).
BANNER_STYLES: dict[str, tuple[str, str, str]] = {
    "info": ("info", "#eff6ff", "#bfdbfe"),
    "tip": ("tip", "#fffbeb", "#fde68a"),
    "warning": ("warning", "#fef3c7", "#f59e0b"),
    "error": ("error", ERROR_COLOR, "#f87171"),
    "ok": ("ok", "#dcfce7", "#86efac"),
}


class Banner(QFrame):
    """Franja con icono y texto que se ajusta al ancho (ayuda, aviso o error)."""

    def __init__(self, kind: str = "info", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        self.kind = ""
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        capa = QHBoxLayout(self)
        capa.setContentsMargins(6, 4, 6, 4)
        capa.setSpacing(6)
        capa.addWidget(self.icon)
        capa.addWidget(self.label, 1)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        if kind == self.kind:
            return
        self.kind = kind
        nombre, fondo, borde = BANNER_STYLES.get(kind, BANNER_STYLES["info"])
        self.icon.setPixmap(icon_pixmap(nombre))
        self.setStyleSheet(
            f"QFrame#banner {{ background: {fondo}; border: 1px solid {borde};"
            " border-radius: 4px; }"
        )

    def setText(self, text: str) -> None:
        self.label.setText(text)

    def text(self) -> str:
        return self.label.text()

    def show_message(self, text: str, kind: str | None = None) -> None:
        """Muestra el texto (u oculta la franja si está vacío)."""
        if kind is not None:
            self.set_kind(kind)
        self.label.setText(text)
        self.setVisible(bool(text))


# --------------------------------------------------------------------------- #
# Estado vacío
# --------------------------------------------------------------------------- #


class EmptyHint(QLabel):
    """Texto de ayuda centrado sobre la zona visible de una tabla vacía.

    No intercepta el ratón: se puede seguir haciendo clic en la fila en blanco.
    """

    def __init__(self, view: QAbstractScrollArea) -> None:
        super().__init__(view.viewport())
        self._viewport = view.viewport()
        self.setObjectName("empty_hint")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            "QLabel#empty_hint { color: #4b5563; background: #f9fafb;"
            " border: 1px dashed #cbd5e1; border-radius: 6px; padding: 14px; font-size: 11pt; }"
        )
        self._viewport.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._viewport and event.type() == QEvent.Type.Resize:
            self._place()
        return False

    def _place(self) -> None:
        zona = self._viewport.rect()
        ancho = max(160, min(zona.width() - 40, 520))
        self.setFixedWidth(ancho)
        alto = self.heightForWidth(ancho)
        self.setFixedHeight(max(alto, 40))
        self.move(zona.center().x() - ancho // 2, zona.center().y() - self.height() // 2)

    def show_hint(self, text: str) -> None:
        """Muestra el texto (u oculta la ayuda si está vacío)."""
        self.setText(text)
        if text:
            self._place()
            self.raise_()
        self.setVisible(bool(text))


# --------------------------------------------------------------------------- #
# Leyenda
# --------------------------------------------------------------------------- #

#: Muestra de una leyenda: `("fill", color)`, `("outline", color)` o `("icon", nombre)`.
type Swatch = tuple[str, str]


def swatch_pixmap(swatch: Swatch, side: int = 14) -> QPixmap:
    tipo, valor = swatch
    if tipo == "icon":
        return icon(valor).pixmap(QSize(side, side))
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(pixmap)
    marco = QRect(1, 1, side - 2, side - 2)
    if tipo == "fill":
        pintor.setBrush(QBrush(QColor(valor)))
        pintor.setPen(QPen(QColor("#6b7280")))
    else:
        pintor.setBrush(QBrush(QColor("#ffffff")))
        pintor.setPen(QPen(QColor(valor), 2))
    pintor.drawRect(marco)
    pintor.end()
    return pixmap


class Legend(QWidget):
    """Tira horizontal de muestras con su significado."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(2, 0, 2, 0)
        self._layout.setSpacing(4)
        self.texts: list[str] = []

    def set_items(self, items: Sequence[tuple[Swatch, str]], title: str = "") -> None:
        while self._layout.count():
            elemento = self._layout.takeAt(0)
            hijo = elemento.widget() if elemento is not None else None
            if hijo is not None:
                hijo.deleteLater()
        self.texts = []
        if title:
            cabecera = QLabel(title)
            cabecera.setStyleSheet("color: #4b5563;")
            self._layout.addWidget(cabecera)
        for swatch, texto in items:
            muestra = QLabel()
            muestra.setPixmap(swatch_pixmap(swatch))
            etiqueta = QLabel(texto)
            etiqueta.setStyleSheet("color: #374151;")
            self._layout.addWidget(muestra)
            self._layout.addWidget(etiqueta)
            self._layout.addSpacing(10)
            self.texts.append(texto)
        self._layout.addStretch(1)
