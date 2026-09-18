"""Ventana Horarios: vistas de horario con formatos, varios paneles, impresión y exportación.

Como en Untis, un horario de clase, profesor, aula o materia se muestra con un
*formato* (qué campos lleva cada celda, tamaño de letra y colores). La ventana
admite 1, 2 o 4 horarios a la vez; con "Sincronizar" marcado, los paneles
siguen la selección del resto de ventanas (elegir una clase en Datos maestros
cambia el panel de clases). Desde aquí se imprime o se exporta a PDF y HTML
(uno o todos los horarios de un tipo) y a GPU/XML para MiUntisWeb y Untis.

Las celdas usan texto negro o blanco según el color de la materia, marcan los
choques con borde rojo y las lecciones fijadas con una chincheta; una leyenda
lo explica y la ayuda emergente de cada celda trae la lección completa.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QShowEvent
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import MasterKind, TimetableGrid

from ..export.html import FORMATS, TimetableFormat, cell_lines, timetable_html
from ..export.pdf import html_to_pdf, print_html
from ..icons import icon, icon_size
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import BREAK_COLOR, day_name
from ..widgets.timetable_cells import (
    CONFLICT_ROLE,
    FIXED_ROLE,
    TimetableCellDelegate,
    cell_tooltip,
    legend_items,
    readable_colors,
)
from ..widgets.uikit import Legend, set_texts

#: Icono de cada tipo de horario.
KIND_ICONS: dict[str, str] = {
    "class": "classes",
    "teacher": "teachers",
    "room": "rooms",
    "subject": "subjects",
}

#: Tipos de horario y su ventana de datos maestros.
KINDS: tuple[tuple[str, MasterKind], ...] = (
    ("class", MasterKind.CLASSES),
    ("teacher", MasterKind.TEACHERS),
    ("room", MasterKind.ROOMS),
    ("subject", MasterKind.SUBJECTS),
)
#: Disposiciones: nº de paneles -> (filas, columnas).
LAYOUTS: dict[int, tuple[int, int]] = {1: (1, 1), 2: (1, 2), 4: (2, 2)}


def safe_filename(text: str) -> str:
    """Nombre de archivo seguro para el id de una entidad."""
    limpio = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE).strip("._")
    return limpio or "horario"


class TimetablePane(QFrame):
    """Un horario dentro de la ventana: selector de entidad y cuadrícula de solo lectura."""

    def __init__(self, window: TimetablesWindow, default_kind: str) -> None:
        super().__init__()
        self.owner = window
        self.grid: TimetableGrid | None = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.kind_combo = QComboBox()
        for clave, _master in KINDS:
            self.kind_combo.addItem(icon(KIND_ICONS[clave]), clave, clave)
        self.kind_combo.setCurrentIndex(self.kind_combo.findData(default_kind))
        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumContentsLength(10)
        self.title_label = QLabel()
        fuente = QFont()
        fuente.setBold(True)
        self.title_label.setFont(fuente)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.setItemDelegate(TimetableCellDelegate(self.table))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        barra = QHBoxLayout()
        barra.addWidget(self.kind_combo)
        barra.addWidget(self.entity_combo, 1)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(3, 3, 3, 3)
        capa.addLayout(barra)
        capa.addWidget(self.title_label)
        capa.addWidget(self.table, 1)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self.entity_combo.currentIndexChanged.connect(self._on_entity_changed)

    @property
    def kind(self) -> str:
        return str(self.kind_combo.currentData())

    @property
    def entity_id(self) -> str:
        return self.entity_combo.currentText()

    def retranslate(self) -> None:
        nombres = {
            "class": self.tr("Clase"),
            "teacher": self.tr("Profesor"),
            "room": self.tr("Aula"),
            "subject": self.tr("Materia"),
        }
        for i in range(self.kind_combo.count()):
            self.kind_combo.setItemText(i, nombres[str(self.kind_combo.itemData(i))])
        self.kind_combo.setToolTip(self.tr("Tipo de horario: de clase, profesor, aula o materia"))
        self.entity_combo.setToolTip(self.tr("La clase, profesor, aula o materia que se muestra"))

    def load_entities(self) -> None:
        """Rellena el combo de entidades conservando la elegida."""
        actual = self.entity_id
        ids = self.owner.entity_ids(self.kind)
        self.entity_combo.blockSignals(True)
        self.entity_combo.clear()
        self.entity_combo.addItems(ids)
        if actual in ids:
            self.entity_combo.setCurrentText(actual)
        self.entity_combo.blockSignals(False)

    def set_entity(self, kind: str, entity_id: str) -> bool:
        ids = self.owner.entity_ids(kind)
        if entity_id not in ids:
            return False
        self.kind_combo.blockSignals(True)
        self.kind_combo.setCurrentIndex(self.kind_combo.findData(kind))
        self.kind_combo.blockSignals(False)
        self.entity_combo.blockSignals(True)
        self.entity_combo.clear()
        self.entity_combo.addItems(ids)
        self.entity_combo.setCurrentText(entity_id)
        self.entity_combo.blockSignals(False)
        self.reload()
        return True

    def _on_kind_changed(self, _index: int) -> None:
        self.load_entities()
        self.reload()
        self.owner.pane_changed(self)

    def _on_entity_changed(self, _index: int) -> None:
        self.reload()
        self.owner.pane_changed(self)

    def reload(self) -> None:
        """Relee el horario de la entidad elegida y lo pinta."""
        bridge = self.owner.bridge
        if not bridge.has_session or not self.entity_id:
            self.grid = None
        else:
            self.grid = bridge.service.timetable_grid(bridge.session, self.kind, self.entity_id)
        self.redraw()

    def redraw(self) -> None:
        """Pinta la cuadrícula con el formato actual de la ventana."""
        fmt = self.owner.format()
        tabla = self.table
        tabla.clear()
        grid = self.grid
        if grid is None:
            self.title_label.setText("")
            tabla.setRowCount(0)
            tabla.setColumnCount(0)
            return
        self.title_label.setText(grid.title)
        fuente = QFont()
        fuente.setPointSize(fmt.font_size)
        tabla.setFont(fuente)
        idioma = self.owner.bridge.language
        tabla.setColumnCount(len(grid.days))
        tabla.setRowCount(len(grid.periods))
        tabla.setHorizontalHeaderLabels([day_name(d, idioma) for d in grid.days])
        tabla.setVerticalHeaderLabels([f"{p.number}\n{p.start}-{p.end}" for p in grid.periods])
        for fila, periodo in enumerate(grid.periods):
            for col, dia in enumerate(grid.days):
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if periodo.is_break:
                    item.setBackground(QBrush(QColor(BREAK_COLOR)))
                    item.setToolTip(self.tr("Recreo"))
                else:
                    celdas = grid.at(dia, periodo.number)
                    item.setText("\n".join(cell_lines(celdas, fmt)))
                    fondo, texto = readable_colors(celdas, colors=fmt.colors)
                    item.setBackground(QBrush(fondo))
                    item.setForeground(QBrush(texto))
                    item.setData(CONFLICT_ROLE, any(c.conflict for c in celdas))
                    item.setData(FIXED_ROLE, any(c.fixed for c in celdas))
                    if any(c.fixed for c in celdas):
                        negrita = QFont(fuente)
                        negrita.setBold(True)
                        item.setFont(negrita)
                    item.setToolTip(cell_tooltip(celdas))
                tabla.setItem(fila, col, item)

    def cell_text(self, day: int, period: int) -> str:
        """Texto que muestra la celda `(día, período)`."""
        grid = self.grid
        if grid is None or day not in grid.days:
            return ""
        col = grid.days.index(day)
        fila = next((i for i, p in enumerate(grid.periods) if p.number == period), None)
        if fila is None:
            return ""
        item = self.table.item(fila, col)
        return item.text() if item is not None else ""


class TimetablesWindow(QWidget):
    """Horarios con formatos, varios paneles sincronizados y exportación."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self._stale = True
        self._active = 0
        self._entity_cache: dict[str, list[str]] = {}

        # --- barra de formato ---------------------------------------------- #
        self.layout_combo = QComboBox()
        for n in LAYOUTS:
            self.layout_combo.addItem(str(n), n)
        self.format_combo = QComboBox()
        for clave in FORMATS:
            self.format_combo.addItem(clave, clave)
        self.subject_check = QCheckBox()
        self.teacher_check = QCheckBox()
        self.room_check = QCheckBox()
        self.class_check = QCheckBox()
        self.colors_check = QCheckBox()
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 24)
        self.sync_check = QCheckBox()
        self.sync_check.setChecked(True)
        self._lbl_layout = QLabel()
        self._lbl_format = QLabel()
        self._lbl_font = QLabel()

        iconos_casillas = (
            (self.subject_check, "subjects"),
            (self.teacher_check, "teachers"),
            (self.room_check, "rooms"),
            (self.class_check, "classes"),
            (self.colors_check, "visible"),
            (self.sync_check, "couple"),
        )
        for casilla, nombre in iconos_casillas:
            casilla.setIcon(icon(nombre))
            casilla.setIconSize(icon_size("small"))
        self.legend = Legend()

        self.print_button = QToolButton()
        self.print_button.setIcon(icon("print"))
        self.print_button.setIconSize(icon_size("button"))
        self.print_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.print_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.export_menu = QMenu(self)
        self.export_menu.setToolTipsVisible(True)
        self.export_menu.menuAction().setIcon(icon("export"))
        self.print_button.setMenu(self.export_menu)
        self._actions = {
            "print": self.export_menu.addAction(icon("print"), "", self.print_dialog),
            "pdf": self.export_menu.addAction(icon("pdf"), "", self._ask_pdf),
            "html": self.export_menu.addAction(icon("html"), "", self._ask_html),
            "all_html": self.export_menu.addAction(
                icon("html"), "", lambda: self._ask_all(pdf=False)
            ),
            "all_pdf": self.export_menu.addAction(icon("pdf"), "", lambda: self._ask_all(pdf=True)),
            "gpu": self.export_menu.addAction(icon("gpu"), "", self._ask_gpu),
            "xml": self.export_menu.addAction(icon("export"), "", self._ask_xml),
        }
        self.export_menu.insertSeparator(self._actions["all_html"])
        self.export_menu.insertSeparator(self._actions["gpu"])

        barra = QHBoxLayout()
        for w in (
            self._lbl_layout,
            self.layout_combo,
            self._lbl_format,
            self.format_combo,
            self.subject_check,
            self.teacher_check,
            self.room_check,
            self.class_check,
            self.colors_check,
            self._lbl_font,
            self.font_size,
            self.sync_check,
        ):
            barra.addWidget(w)
        barra.addStretch(1)
        barra.addWidget(self.print_button)

        # --- paneles ------------------------------------------------------------ #
        tipos = ("class", "teacher", "room", "subject")
        self.panes = [TimetablePane(self, tipos[i]) for i in range(max(LAYOUTS))]
        self._pane_area = QWidget()
        self._pane_grid = QGridLayout(self._pane_area)
        self._pane_grid.setContentsMargins(0, 0, 0, 0)

        principal = QVBoxLayout(self)
        principal.addLayout(barra)
        principal.addWidget(self._pane_area, 1)
        principal.addWidget(self.legend)

        self._apply_format_to_controls(FORMATS["class"])
        self.format_combo.currentIndexChanged.connect(self._on_format_selected)
        for control in (
            self.subject_check,
            self.teacher_check,
            self.room_check,
            self.class_check,
            self.colors_check,
        ):
            control.toggled.connect(lambda _v: self._render_all())
        self.font_size.valueChanged.connect(lambda _v: self._render_all())
        self.layout_combo.currentIndexChanged.connect(
            lambda _i: self.set_pane_count(int(self.layout_combo.currentData()))
        )
        self.set_pane_count(1)

        bridge.refreshed.connect(self._on_refreshed)
        bridge.project_opened.connect(self._on_project_opened)
        bridge.selection_changed.connect(self._on_selection_changed)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()

    # --- textos --------------------------------------------------------------- #

    def _retranslate(self) -> None:
        self._lbl_layout.setText(self.tr("Horarios:"))
        self._lbl_format.setText(self.tr("Formato:"))
        self._lbl_font.setText(self.tr("Letra:"))
        nombres = {
            "class": self.tr("Clase"),
            "teacher": self.tr("Profesor"),
            "room": self.tr("Aula"),
            "full": self.tr("Completo"),
            "compact": self.tr("Compacto"),
            "print": self.tr("Impresión (sin colores)"),
        }
        for i in range(self.format_combo.count()):
            clave = str(self.format_combo.itemData(i))
            self.format_combo.setItemText(i, nombres.get(clave, clave))
        casillas = (
            (self.subject_check, self.tr("Materia"), self.tr("Muestra la materia en cada celda")),
            (self.teacher_check, self.tr("Profesor"), self.tr("Muestra el profesor en cada celda")),
            (self.room_check, self.tr("Aula"), self.tr("Muestra el aula en cada celda")),
            (self.class_check, self.tr("Clase"), self.tr("Muestra la clase en cada celda")),
            (
                self.colors_check,
                self.tr("Colores"),
                self.tr("Pinta cada celda con el color de su materia"),
            ),
            (
                self.sync_check,
                self.tr("Sincronizar"),
                self.tr("Los horarios siguen lo que eliges en las demás ventanas"),
            ),
        )
        for casilla, texto, ayuda in casillas:
            set_texts(casilla, texto, ayuda)
        self.layout_combo.setToolTip(self.tr("Cuántos horarios se ven a la vez: 1, 2 o 4"))
        self.format_combo.setToolTip(self.tr("Formato predefinido: qué datos lleva cada celda"))
        self.font_size.setToolTip(self.tr("Tamaño de la letra en las celdas"))
        self.legend.set_items(legend_items(targets=False), self.tr("Leyenda:"))
        set_texts(
            self.print_button,
            self.tr("Imprimir / Exportar"),
            self.tr("Imprime el horario o lo guarda como PDF, HTML, GPU o XML"),
        )
        self.export_menu.menuAction().setText(self.tr("Imprimir / Exportar"))
        self.export_menu.menuAction().setToolTip(self.tr("Imprime o exporta horarios"))
        textos = {
            "print": (
                self.tr("Imprimir..."),
                self.tr("Imprime el horario del panel activo"),
            ),
            "pdf": (
                self.tr("PDF del horario..."),
                self.tr("Guarda el horario del panel activo como PDF"),
            ),
            "html": (
                self.tr("HTML del horario..."),
                self.tr("Guarda el horario del panel activo como página web"),
            ),
            "all_html": (
                self.tr("Exportar todos (HTML, uno por entidad)..."),
                self.tr("Una página web por cada clase (o profesor, aula...) en una carpeta"),
            ),
            "all_pdf": (
                self.tr("Exportar todos (un PDF)..."),
                self.tr("Todos los horarios del tipo del panel activo en un único PDF"),
            ),
            "gpu": (
                self.tr("Exportar GPU (MiUntisWeb)..."),
                self.tr("Archivos GPU del horario activo, para subirlos a MiUntisWeb"),
            ),
            "xml": (
                self.tr("Exportar XML (Untis)..."),
                self.tr("Todo el proyecto en XML para abrirlo en Untis"),
            ),
        }
        for clave, accion in self._actions.items():
            set_texts(accion, *textos[clave])
        for pane in self.panes:
            pane.retranslate()
            pane.redraw()

    # --- formato ------------------------------------------------------------------ #

    def format(self) -> TimetableFormat:
        """Formato de celda según los controles."""
        return TimetableFormat(
            subject=self.subject_check.isChecked(),
            teacher=self.teacher_check.isChecked(),
            room=self.room_check.isChecked(),
            school_class=self.class_check.isChecked(),
            font_size=self.font_size.value(),
            colors=self.colors_check.isChecked(),
        )

    def select_format(self, key: str) -> None:
        """Elige un formato predefinido (`FORMATS`)."""
        self.format_combo.setCurrentIndex(self.format_combo.findData(key))

    def _on_format_selected(self, _index: int) -> None:
        clave = str(self.format_combo.currentData())
        if clave in FORMATS:
            self._apply_format_to_controls(FORMATS[clave])
            self._render_all()

    def _apply_format_to_controls(self, fmt: TimetableFormat) -> None:
        controles: tuple[tuple[QCheckBox, bool], ...] = (
            (self.subject_check, fmt.subject),
            (self.teacher_check, fmt.teacher),
            (self.room_check, fmt.room),
            (self.class_check, fmt.school_class),
            (self.colors_check, fmt.colors),
        )
        for control, valor in controles:
            control.blockSignals(True)
            control.setChecked(valor)
            control.blockSignals(False)
        self.font_size.blockSignals(True)
        self.font_size.setValue(fmt.font_size)
        self.font_size.blockSignals(False)

    def _render_all(self) -> None:
        for pane in self.visible_panes():
            pane.redraw()

    # --- paneles ------------------------------------------------------------------- #

    def visible_panes(self) -> list[TimetablePane]:
        return self.panes[: self.pane_count]

    @property
    def pane_count(self) -> int:
        return int(self.layout_combo.currentData())

    def set_pane_count(self, count: int) -> None:
        """1, 2 o 4 horarios en la ventana."""
        if count not in LAYOUTS:
            return
        if self.pane_count != count:
            self.layout_combo.blockSignals(True)
            self.layout_combo.setCurrentIndex(self.layout_combo.findData(count))
            self.layout_combo.blockSignals(False)
        for pane in self.panes:
            self._pane_grid.removeWidget(pane)
            pane.setVisible(False)
        _filas, columnas = LAYOUTS[count]
        for i, pane in enumerate(self.panes[:count]):
            self._pane_grid.addWidget(pane, i // columnas, i % columnas)
            pane.setVisible(True)
            if pane.grid is None and self.bridge.has_session:
                pane.load_entities()
                pane.reload()
        self._active = min(self._active, count - 1)

    @property
    def active_pane(self) -> TimetablePane:
        return self.panes[self._active]

    def pane_changed(self, pane: TimetablePane) -> None:
        """Un panel cambió de entidad: pasa a ser el activo y, si hay sincronía, avisa."""
        self._active = self.panes.index(pane)
        if self.sync_check.isChecked() and pane.entity_id:
            self.bridge.select(pane.kind, pane.entity_id)

    def _on_selection_changed(self, kind: str, entity_id: str) -> None:
        if not self.sync_check.isChecked() or not self.bridge.has_session:
            return
        paneles = [p for p in self.visible_panes() if p.kind == kind]
        if not paneles:
            paneles = [self.active_pane]
        for pane in paneles:
            if (pane.kind, pane.entity_id) != (kind, entity_id):
                pane.set_entity(kind, entity_id)

    def entity_ids(self, kind: str) -> list[str]:
        if kind not in self._entity_cache:
            maestro = dict(KINDS).get(kind)
            if maestro is None or not self.bridge.has_session:
                return []
            tabla = self.bridge.service.master_table(self.bridge.session, maestro)
            self._entity_cache[kind] = [r.key for r in tabla.rows]
        return self._entity_cache[kind]

    # --- refresco -------------------------------------------------------------------- #

    def _on_project_opened(self) -> None:
        self._entity_cache = {}
        for pane in self.panes:
            pane.grid = None
            pane.entity_combo.blockSignals(True)
            pane.entity_combo.clear()
            pane.entity_combo.blockSignals(False)

    def _on_refreshed(self) -> None:
        if self.isVisible():
            self.refresh()
        else:
            self._stale = True

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def refresh(self) -> None:
        """Relee las entidades y los horarios de los paneles visibles."""
        self._stale = False
        self._entity_cache = {}
        for pane in self.visible_panes():
            pane.load_entities()
            pane.reload()
        if self.bridge.selection is not None:
            self._on_selection_changed(*self.bridge.selection)

    # --- exportación -------------------------------------------------------------------- #

    def html(self, grids: Sequence[TimetableGrid] | None = None) -> str:
        """HTML de los horarios indicados (por defecto, el del panel activo)."""
        lista = list(grids) if grids is not None else self._active_grids()
        return timetable_html(lista, self.format(), language=self.bridge.language)

    def _active_grids(self) -> list[TimetableGrid]:
        grid = self.active_pane.grid
        return [grid] if grid is not None else []

    def export_html(self, path: str | Path) -> Path:
        destino = Path(path)
        destino.write_text(self.html(), encoding="utf-8")
        self.bridge.status.emit(self.tr("HTML exportado: {0}").format(destino.name))
        return destino

    def export_pdf(self, path: str | Path) -> Path:
        destino = html_to_pdf(self.html(), path)
        self.bridge.status.emit(self.tr("PDF exportado: {0}").format(destino.name))
        return destino

    def export_all(
        self,
        kind: str,
        folder: str | Path,
        *,
        pdf: bool = False,
        ids: Sequence[str] | None = None,
    ) -> list[Path]:
        """Exporta todos los horarios de un tipo: un HTML por entidad o un solo PDF."""
        carpeta = Path(folder)
        carpeta.mkdir(parents=True, exist_ok=True)
        s = self.bridge.session
        elegidos = list(ids) if ids is not None else self.entity_ids(kind)
        grids = [self.bridge.service.timetable_grid(s, kind, e) for e in elegidos]
        fmt = self.format()
        idioma = self.bridge.language
        if pdf:
            destino = html_to_pdf(
                timetable_html(grids, fmt, language=idioma), carpeta / f"horarios_{kind}.pdf"
            )
            escritos = [destino]
        else:
            escritos = []
            for grid in grids:
                destino = carpeta / f"{kind}_{safe_filename(grid.entity_id)}.html"
                destino.write_text(timetable_html([grid], fmt, language=idioma), encoding="utf-8")
                escritos.append(destino)
        self.bridge.status.emit(
            self.tr("{0} archivo(s) exportado(s) en {1}").format(len(escritos), carpeta)
        )
        return escritos

    def export_gpu(self, folder: str | Path) -> list[Path]:
        """GPU001-007/GPU016 del horario activo (MiUntisWeb / Untis)."""
        escritos = self.bridge.service.export_gpu(self.bridge.session, folder)
        self.bridge.status.emit(self.tr("GPU exportado: {0} archivo(s)").format(len(escritos)))
        return escritos

    def export_xml(self, path: str | Path) -> Path:
        destino = self.bridge.service.export_xml(self.bridge.session, path)
        self.bridge.status.emit(self.tr("XML exportado: {0}").format(Path(destino).name))
        return destino

    # --- diálogos (envoltorios de las órdenes anteriores) ---------------------------------- #

    def _default_name(self, suffix: str) -> str:
        grid = self.active_pane.grid
        base = safe_filename(grid.entity_id) if grid is not None else "horario"
        return f"{base}{suffix}"

    def print_dialog(self) -> None:
        if not self._active_grids():
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialogo = QPrintDialog(printer, self)
        if dialogo.exec() == QPrintDialog.DialogCode.Accepted:
            print_html(self.html(), printer)

    def _ask_pdf(self) -> None:
        if not self._active_grids():
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self, self.tr("Exportar PDF"), self._default_name(".pdf"), "PDF (*.pdf)"
        )
        if ruta:
            self.export_pdf(ruta)

    def _ask_html(self) -> None:
        if not self._active_grids():
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self, self.tr("Exportar HTML"), self._default_name(".html"), "HTML (*.html *.htm)"
        )
        if ruta:
            self.export_html(ruta)

    def _ask_all(self, *, pdf: bool) -> None:
        if not self.bridge.has_session:
            return
        carpeta = QFileDialog.getExistingDirectory(self, self.tr("Carpeta de destino"))
        if carpeta:
            self.export_all(self.active_pane.kind, carpeta, pdf=pdf)

    def _ask_gpu(self) -> None:
        if not self.bridge.has_session:
            return
        carpeta = QFileDialog.getExistingDirectory(self, self.tr("Carpeta para los archivos GPU"))
        if carpeta:
            self.export_gpu(carpeta)

    def _ask_xml(self) -> None:
        if not self.bridge.has_session:
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self, self.tr("Exportar XML"), "untis.xml", "XML (*.xml)"
        )
        if ruta:
            self.export_xml(ruta)


register(
    WindowSpec(
        key="timetables",
        title="Horarios",
        title_de="Stundenpläne",
        tab=RibbonTab.TIMETABLES,
        factory=lambda bridge: TimetablesWindow(bridge),
        order=5,
        icon="timetables",
        tooltip="Ver, imprimir y exportar los horarios de clases, profesores, aulas y materias.",
        tooltip_de=(
            "Stundenpläne von Klassen, Lehrkräften, Räumen und Fächern ansehen, drucken und "
            "exportieren."
        ),
    )
)
