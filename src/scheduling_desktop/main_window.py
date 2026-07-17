"""Ventana principal: el shell que hospeda los módulos (Fase 6).

Menú/toolbar, dock del Explorer a la izquierda, área central con pestañas de
módulos (``QStackedWidget``) y barra de estado. Orquesta la navegación y refleja
las señales del puente (título, estado, cambios sin guardar). No contiene lógica
de negocio: delega todo en ``EngineBridge``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QStackedWidget,
    QStyle,
    QToolBar,
)

from .engine_bridge import EngineBridge
from .modules import (
    PAGE_CONSTRAINTS,
    PAGE_DASHBOARD,
    PAGE_DATA,
    PAGE_OPTIMIZE,
    PAGE_REPORTS,
    PAGE_SCHEDULE,
    PAGE_VALIDATION,
)
from .modules.constraint_manager import ConstraintManagerModule
from .modules.dashboard import DashboardModule
from .modules.data_manager import DataManagerModule
from .modules.explorer import ExplorerTree
from .modules.optimization_console import OptimizationConsoleModule
from .modules.reports import ReportsModule
from .modules.schedule_editor import ScheduleEditorModule
from .modules.validation_center import ValidationCenterModule

_FILTER = "Proyecto RealSchool (*.bjs)"


class MainWindow(QMainWindow):
    """Contenedor visual del motor headless."""

    def __init__(self, bridge: EngineBridge | None = None) -> None:
        super().__init__()
        self._bridge = bridge or EngineBridge()
        self.setWindowTitle("RealSchool")
        self.resize(1200, 780)

        self._dashboard = DashboardModule(self._bridge)
        self._data = DataManagerModule(self._bridge)
        self._schedule = ScheduleEditorModule(self._bridge)
        self._constraints = ConstraintManagerModule(self._bridge)
        self._validation = ValidationCenterModule(self._bridge)
        self._reports = ReportsModule(self._bridge)
        self._optimize = OptimizationConsoleModule(self._bridge)

        self._stack = QStackedWidget()
        self._pages: dict[str, int] = {}
        for page, widget in (
            (PAGE_DASHBOARD, self._dashboard),
            (PAGE_DATA, self._data),
            (PAGE_SCHEDULE, self._schedule),
            (PAGE_CONSTRAINTS, self._constraints),
            (PAGE_VALIDATION, self._validation),
            (PAGE_REPORTS, self._reports),
            (PAGE_OPTIMIZE, self._optimize),
        ):
            self._pages[page] = self._stack.addWidget(widget)
        self.setCentralWidget(self._stack)

        self._validation.navigate.connect(self.show_page)
        self._explorer = ExplorerTree(self._bridge)
        self._explorer.navigate.connect(self.show_page)
        dock = QDockWidget("Explorador", self)
        dock.setWidget(self._explorer)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self._build_menu()
        self._build_toolbar()
        self.statusBar().showMessage("Abre un proyecto .bjs para empezar")

        self._bridge.session_opened.connect(self._on_session_opened)
        self._bridge.status_message.connect(self.statusBar().showMessage)
        self._bridge.dirty_changed.connect(self._on_dirty)
        self._set_enabled(False)

    # --- construcción --------------------------------------------------- #
    def _build_menu(self) -> None:
        archivo = self.menuBar().addMenu("&Archivo")

        self._act_open = QAction("&Abrir…", self)
        self._act_open.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open.triggered.connect(self.open_dialog)
        archivo.addAction(self._act_open)

        self._act_save = QAction("&Guardar", self)
        self._act_save.setShortcut(QKeySequence.StandardKey.Save)
        self._act_save.triggered.connect(self.save)
        archivo.addAction(self._act_save)

        archivo.addSeparator()
        salir = QAction("&Salir", self)
        salir.setShortcut(QKeySequence.StandardKey.Quit)
        salir.triggered.connect(self.close)
        archivo.addAction(salir)

        ver = self.menuBar().addMenu("&Ver")
        for label, page in (
            ("Tablero", PAGE_DASHBOARD),
            ("Datos", PAGE_DATA),
            ("Horario", PAGE_SCHEDULE),
            ("Restricciones", PAGE_CONSTRAINTS),
            ("Validación", PAGE_VALIDATION),
            ("Informes", PAGE_REPORTS),
            ("Optimización", PAGE_OPTIMIZE),
        ):
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, p=page: self.show_page(p))
            ver.addAction(action)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Principal")
        bar.setMovable(False)
        bar.setIconSize(QSize(26, 26))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.addToolBar(bar)
        style = self.style()

        def icon(pixmap: QStyle.StandardPixmap) -> QIcon:
            return style.standardIcon(pixmap)

        bar.addAction(icon(QStyle.StandardPixmap.SP_DirOpenIcon), "Abrir", self.open_dialog)
        bar.addAction(icon(QStyle.StandardPixmap.SP_DialogSaveButton), "Guardar", self.save)
        bar.addSeparator()
        nav = (
            ("Tablero", QStyle.StandardPixmap.SP_FileDialogInfoView, PAGE_DASHBOARD),
            ("Datos", QStyle.StandardPixmap.SP_FileDialogListView, PAGE_DATA),
            ("Horario", QStyle.StandardPixmap.SP_FileDialogDetailedView, PAGE_SCHEDULE),
            ("Restricciones", QStyle.StandardPixmap.SP_FileDialogContentsView, PAGE_CONSTRAINTS),
            ("Validación", QStyle.StandardPixmap.SP_MessageBoxWarning, PAGE_VALIDATION),
            ("Informes", QStyle.StandardPixmap.SP_FileDialogInfoView, PAGE_REPORTS),
            ("Optimizar", QStyle.StandardPixmap.SP_MediaPlay, PAGE_OPTIMIZE),
        )
        for label, pixmap, page in nav:
            bar.addAction(icon(pixmap), label, lambda _=False, p=page: self.show_page(p))

    # --- navegación / acciones ------------------------------------------ #
    def show_page(self, page: str) -> None:
        if page in self._pages:
            self._stack.setCurrentIndex(self._pages[page])

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", "", _FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path: str | Path) -> None:
        self._bridge.open_path(path)

    def save(self) -> None:
        if not self._bridge.has_session:
            return
        if self._bridge.path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto", "", _FILTER)
            if not path:
                return
            self._bridge.save(path)
        else:
            self._bridge.save()

    # --- reacción a señales --------------------------------------------- #
    def _on_session_opened(self) -> None:
        self._set_enabled(True)
        for module in (
            self._dashboard,
            self._data,
            self._schedule,
            self._constraints,
            self._validation,
            self._reports,
            self._optimize,
        ):
            module.refresh()
        self._explorer.refresh()
        self.show_page(PAGE_DASHBOARD)
        self._update_title(dirty=False)

    def _on_dirty(self, dirty: bool) -> None:
        self._update_title(dirty=dirty)

    def _update_title(self, *, dirty: bool) -> None:
        name = self._bridge.path.name if self._bridge.path is not None else "sin título"
        marca = "•" if dirty else ""
        self.setWindowTitle(f"RealSchool — {name}{marca}")

    def _set_enabled(self, enabled: bool) -> None:
        self._act_save.setEnabled(enabled)
        self._stack.setEnabled(enabled)
