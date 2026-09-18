"""Ventana principal: cinta + área MDI + paneles acoplados (sección 8).

Como en Untis, cada ventana es un documento independiente que puede estar
abierto a la vez que las demás; la cinta agrupa las órdenes por pestaña y los
paneles de Diagnóstico y Registro se acoplan a los bordes. Mientras se optimiza,
todas las ventanas salvo la de Optimización quedan bloqueadas.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMdiArea,
    QMdiSubWindow,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QToolBar,
    QWidget,
)

from .qt_bridge import FacadeBridge
from .registry import RIBBON_LABELS, RibbonTab, WindowSpec, load_windows

#: Ventana que sigue activa mientras se optimiza.
OPTIMIZATION_KEY = "optimization"

_FILTERS = (
    "Proyectos y horarios Untis (*.rsp *.xml *.bjs);;Proyecto RealSchool (*.rsp);;"
    "Untis XmlInterface (*.xml);;Proyecto antiguo (*.bjs)"
)


class MainWindow(QMainWindow):
    """Cinta, área MDI y paneles."""

    def __init__(self, bridge: FacadeBridge | None = None) -> None:
        super().__init__()
        self.bridge = bridge if bridge is not None else FacadeBridge()
        self.setWindowTitle("RealSchool")
        self.resize(1400, 900)

        self.mdi = QMdiArea()
        self.mdi.setViewMode(QMdiArea.ViewMode.TabbedView)
        self.mdi.setTabsClosable(True)
        self.mdi.setTabsMovable(True)
        self.setCentralWidget(self.mdi)

        self._specs = {s.key: s for s in load_windows()}
        self._widgets: dict[str, QWidget] = {}
        self._subwindows: dict[str, QMdiSubWindow] = {}
        self._docks: dict[str, QDockWidget] = {}
        self._actions: dict[str, QAction] = {}

        self.ribbon = QTabWidget()
        self.ribbon.setObjectName("ribbon")
        self.ribbon.setDocumentMode(True)
        self.ribbon.setMaximumHeight(96)
        self._build_ribbon()
        barra = QToolBar("Cinta")
        barra.setObjectName("ribbon_bar")
        barra.setMovable(False)
        barra.addWidget(self.ribbon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, barra)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        registro = QDockWidget("Registro", self)
        registro.setObjectName("dock_log")
        registro.setWidget(self.log)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, registro)
        self._docks["log"] = registro

        for spec in self._specs.values():
            if spec.dock:
                self._make_dock(spec)

        self.bridge.status.connect(self._on_status)
        self.bridge.project_opened.connect(self._update_title)
        self.bridge.project_changed.connect(lambda _label: self._update_title())
        self.bridge.busy_changed.connect(self._on_busy)
        self.bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._update_title()

    # --- cinta ------------------------------------------------------------ #

    def _build_ribbon(self) -> None:
        self.ribbon.clear()
        barras: dict[RibbonTab, QToolBar] = {}
        for tab in RibbonTab:
            barra = QToolBar()
            barra.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            barras[tab] = barra
            es, de = RIBBON_LABELS[tab]
            self.ribbon.addTab(barra, de if self.bridge.language == "de" else es)

        inicio = barras[RibbonTab.HOME]
        ordenes: tuple[tuple[str, str, QKeySequence.StandardKey, Callable[[], object]], ...] = (
            ("new", "Nuevo", QKeySequence.StandardKey.New, self.new_project),
            ("open", "Abrir", QKeySequence.StandardKey.Open, self.open_dialog),
            ("save", "Guardar", QKeySequence.StandardKey.Save, self.save),
            ("save_as", "Guardar como", QKeySequence.StandardKey.SaveAs, self.save_as),
            ("undo", "Deshacer", QKeySequence.StandardKey.Undo, self.bridge.undo),
            ("redo", "Rehacer", QKeySequence.StandardKey.Redo, self.bridge.redo),
        )
        for clave, texto, atajo, orden in ordenes:
            self._actions[clave] = self._add_action(inicio, texto, orden, atajo)

        for spec in self._specs.values():
            abrir = QAction(spec.label(self.bridge.language), self)
            if spec.shortcut:
                abrir.setShortcut(QKeySequence(spec.shortcut))
            abrir.triggered.connect(self._opener(spec.key))
            barras[spec.tab].addAction(abrir)
            self.addAction(abrir)
            self._actions[f"window:{spec.key}"] = abrir

        vista = barras[RibbonTab.VIEW]
        vistas: tuple[tuple[str, Callable[[], object]], ...] = (
            ("Mosaico", self.mdi.tileSubWindows),
            ("Cascada", self.mdi.cascadeSubWindows),
            ("Español", lambda: self.bridge.set_language("es")),
            ("Deutsch", lambda: self.bridge.set_language("de")),
        )
        for texto, orden in vistas:
            self._add_action(vista, texto, orden)

    def _add_action(
        self,
        bar: QToolBar,
        text: str,
        slot: Callable[[], object],
        shortcut: QKeySequence.StandardKey | None = None,
    ) -> QAction:
        accion = QAction(text, self)
        if shortcut is not None:
            accion.setShortcut(QKeySequence(shortcut))
        accion.triggered.connect(lambda _checked=False: slot())
        bar.addAction(accion)
        self.addAction(accion)
        return accion

    def _opener(self, key: str) -> Callable[[bool], None]:
        def abrir(_checked: bool = False) -> None:
            self.show_window(key)

        return abrir

    # --- ventanas ----------------------------------------------------------- #

    def window_widget(self, key: str) -> QWidget:
        """El widget de una ventana (lo crea la primera vez)."""
        if key not in self._widgets:
            self._widgets[key] = self._specs[key].factory(self.bridge)
        return self._widgets[key]

    def show_window(self, key: str) -> QWidget:
        """Abre o enfoca una ventana (MDI o panel)."""
        spec = self._specs[key]
        if spec.dock:
            dock = self._docks[key]
            dock.show()
            dock.raise_()
            return self.window_widget(key)
        widget = self.window_widget(key)
        sub = self._subwindows.get(key)
        if sub is None:
            sub = self.mdi.addSubWindow(widget)
            sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            sub.setWindowTitle(spec.label(self.bridge.language))
            self._subwindows[key] = sub
        sub.setEnabled(not self.bridge.busy or key == OPTIMIZATION_KEY)
        sub.show()
        widget.show()
        self.mdi.setActiveSubWindow(sub)
        return widget

    def _make_dock(self, spec: WindowSpec) -> None:
        dock = QDockWidget(spec.label(self.bridge.language), self)
        dock.setObjectName(f"dock_{spec.key}")
        dock.setWidget(self.window_widget(spec.key))
        area = (
            Qt.DockWidgetArea.RightDockWidgetArea
            if spec.dock == "right"
            else Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(area, dock)
        self._docks[spec.key] = dock

    def open_keys(self) -> tuple[str, ...]:
        """Ventanas MDI abiertas (para pruebas y para restaurar la sesión)."""
        return tuple(k for k, sub in self._subwindows.items() if sub.isVisible())

    # --- archivo ------------------------------------------------------------ #

    def new_project(self) -> None:
        if self._confirm_discard():
            self.bridge.new("Nuevo colegio")

    def open_dialog(self) -> None:
        if not self._confirm_discard():
            return
        ruta, _ = QFileDialog.getOpenFileName(self, "Abrir", "", _FILTERS)
        if ruta:
            self.open_path(ruta)

    def open_path(self, path: str | Path) -> None:
        try:
            self.bridge.open(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Abrir", str(exc))

    def save(self) -> None:
        if not self.bridge.has_session:
            return
        if self.bridge.session.path is None:
            self.save_as()
        else:
            self.bridge.save()

    def save_as(self) -> None:
        if not self.bridge.has_session:
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar como", "", "Proyecto (*.rsp)")
        if ruta:
            self.bridge.save(ruta)

    def _confirm_discard(self) -> bool:
        if not self.bridge.has_session or not self.bridge.session.dirty:
            return True
        respuesta = QMessageBox.question(
            self, "RealSchool", "Hay cambios sin guardar. ¿Descartarlos?"
        )
        return respuesta == QMessageBox.StandardButton.Yes

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.bridge.busy:
            self.bridge.cancel_optimize()
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    # --- estado -------------------------------------------------------------- #

    def _on_status(self, text: str) -> None:
        if text:
            self.statusBar().showMessage(text, 8000)
            self.log.appendPlainText(text)

    def _on_busy(self, busy: bool) -> None:
        for key, sub in self._subwindows.items():
            sub.setEnabled(not busy or key == OPTIMIZATION_KEY)
        for key, accion in self._actions.items():
            if key in ("new", "open", "save", "save_as", "undo", "redo"):
                accion.setEnabled(not busy)

    def _update_title(self) -> None:
        if not self.bridge.has_session:
            self.setWindowTitle("RealSchool")
            return
        s = self.bridge.session
        nombre = s.project.school.name or (s.path.stem if s.path else "sin título")
        marca = " *" if s.dirty else ""
        self.setWindowTitle(f"RealSchool - {nombre}{marca}")
        self._actions["undo"].setEnabled(s.can_undo and not self.bridge.busy)
        self._actions["redo"].setEnabled(s.can_redo and not self.bridge.busy)

    def _retranslate(self) -> None:
        indice = self.ribbon.currentIndex()
        self._build_ribbon()
        self.ribbon.setCurrentIndex(indice)
        for key, sub in self._subwindows.items():
            sub.setWindowTitle(self._specs[key].label(self.bridge.language))
        for key, dock in self._docks.items():
            if key in self._specs:
                dock.setWindowTitle(self._specs[key].label(self.bridge.language))
