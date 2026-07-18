"""Ventana principal: shell MDI con ventanas padre/hijo, como Untis (Fase 6).

Cada módulo se abre como una **ventana hija** dentro del área central
(``QMdiArea``): se pueden tener varias a la vez (horario del grupo + horario del
docente + lecciones), moverlas, ponerlas en cascada o mosaico — el flujo de
trabajo de Untis. La toolbar y el menú abren/enfocan cada ventana. No contiene
lógica de negocio: delega todo en ``EngineBridge``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMdiArea,
    QMdiSubWindow,
    QStyle,
    QToolBar,
    QWidget,
)

from .engine_bridge import EngineBridge
from .modules import (
    PAGE_CONSTRAINTS,
    PAGE_DASHBOARD,
    PAGE_DATA,
    PAGE_DESIDERATA,
    PAGE_HELP,
    PAGE_IMPORT_EXPORT,
    PAGE_LOAD,
    PAGE_LOGS,
    PAGE_NOTIFICATIONS,
    PAGE_OPTIMIZE,
    PAGE_PLUGINS,
    PAGE_PROJECT,
    PAGE_REPORTS,
    PAGE_SCHEDULE,
    PAGE_SCHOOL_WEEK,
    PAGE_SETTINGS,
    PAGE_VALIDATION,
)
from .modules.constraint_manager import ConstraintManagerModule
from .modules.dashboard import DashboardModule
from .modules.data_manager import DataManagerModule
from .modules.desiderata import DesiderataModule
from .modules.help_center import HelpCenterModule
from .modules.import_export import ImportExportModule
from .modules.lessons import LessonsModule
from .modules.log_viewer import LogViewerModule
from .modules.notification_center import NotificationCenterModule
from .modules.optimization_console import OptimizationConsoleModule
from .modules.plugin_manager import PluginManagerModule
from .modules.project_manager import ProjectManagerModule
from .modules.reports import ReportsModule
from .modules.schedule_editor import ScheduleEditorModule
from .modules.school_week import SchoolWeekModule
from .modules.settings import SettingsModule
from .modules.validation_center import ValidationCenterModule

_FILTER = "Proyecto RealSchool (*.bjs)"


class MainWindow(QMainWindow):
    """Contenedor visual del motor headless (MDI, como Untis)."""

    def __init__(self, bridge: EngineBridge | None = None) -> None:
        super().__init__()
        self._bridge = bridge or EngineBridge()
        self.setWindowTitle("RealSchool")
        self.resize(1400, 860)

        self._dashboard = DashboardModule(self._bridge)
        self._data = DataManagerModule(self._bridge)
        self._lessons = LessonsModule(self._bridge)
        self._school_week = SchoolWeekModule(self._bridge)
        self._desiderata = DesiderataModule(self._bridge)
        self._schedule = ScheduleEditorModule(self._bridge)
        self._constraints = ConstraintManagerModule(self._bridge)
        self._validation = ValidationCenterModule(self._bridge)
        self._reports = ReportsModule(self._bridge)
        self._import_export = ImportExportModule(self._bridge)
        self._project = ProjectManagerModule(self._bridge)
        self._settings = SettingsModule(self._bridge)
        self._plugins = PluginManagerModule(self._bridge)
        self._logs = LogViewerModule(self._bridge)
        self._notifications = NotificationCenterModule(self._bridge)
        self._help = HelpCenterModule(self._bridge)
        self._optimize = OptimizationConsoleModule(self._bridge)

        # Área MDI: cada módulo vive en una ventana hija (padre/hijo, como Untis).
        self._mdi = QMdiArea()
        self._mdi.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._mdi.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setCentralWidget(self._mdi)

        self._pages: dict[str, tuple[QWidget, str]] = {
            PAGE_DASHBOARD: (self._dashboard, "Tablero"),
            PAGE_DATA: (self._data, "Datos maestros"),
            PAGE_LOAD: (self._lessons, "Carga (lecciones)"),
            PAGE_SCHOOL_WEEK: (self._school_week, "Semana lectiva"),
            PAGE_DESIDERATA: (self._desiderata, "Desiderata (bloqueos)"),
            PAGE_SCHEDULE: (self._schedule, "Horario"),
            PAGE_CONSTRAINTS: (self._constraints, "Restricciones"),
            PAGE_VALIDATION: (self._validation, "Validación"),
            PAGE_REPORTS: (self._reports, "Informes"),
            PAGE_IMPORT_EXPORT: (self._import_export, "Importar / Exportar"),
            PAGE_PROJECT: (self._project, "Proyecto y versiones"),
            PAGE_SETTINGS: (self._settings, "Configuración"),
            PAGE_PLUGINS: (self._plugins, "Extensiones"),
            PAGE_LOGS: (self._logs, "Registro (logs)"),
            PAGE_NOTIFICATIONS: (self._notifications, "Notificaciones"),
            PAGE_HELP: (self._help, "Ayuda"),
            PAGE_OPTIMIZE: (self._optimize, "Optimización"),
        }
        self._subwindows: dict[str, QMdiSubWindow] = {}

        self._validation.navigate.connect(self.show_page)

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
            ("Datos maestros", PAGE_DATA),
            ("Carga (lecciones)", PAGE_LOAD),
            ("Semana lectiva", PAGE_SCHOOL_WEEK),
            ("Desiderata (bloqueos)", PAGE_DESIDERATA),
            ("Horario", PAGE_SCHEDULE),
            ("Restricciones", PAGE_CONSTRAINTS),
            ("Validación", PAGE_VALIDATION),
            ("Informes", PAGE_REPORTS),
            ("Importar/Exportar", PAGE_IMPORT_EXPORT),
            ("Proyecto", PAGE_PROJECT),
            ("Optimización", PAGE_OPTIMIZE),
            ("Configuración", PAGE_SETTINGS),
            ("Extensiones", PAGE_PLUGINS),
            ("Registro (logs)", PAGE_LOGS),
            ("Notificaciones", PAGE_NOTIFICATIONS),
            ("Ayuda", PAGE_HELP),
        ):
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, p=page: self.show_page(p))
            ver.addAction(action)

        ventana = self.menuBar().addMenu("Ve&ntana")
        cascada = QAction("Cascada", self)
        cascada.triggered.connect(self._mdi.cascadeSubWindows)
        ventana.addAction(cascada)
        mosaico = QAction("Mosaico", self)
        mosaico.triggered.connect(self._mdi.tileSubWindows)
        ventana.addAction(mosaico)
        cerrar = QAction("Cerrar todas", self)
        cerrar.triggered.connect(self._mdi.closeAllSubWindows)
        ventana.addAction(cerrar)

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
            ("Carga", QStyle.StandardPixmap.SP_FileDialogNewFolder, PAGE_LOAD),
            ("Semana", QStyle.StandardPixmap.SP_FileDialogListView, PAGE_SCHOOL_WEEK),
            ("Bloqueos", QStyle.StandardPixmap.SP_DialogCancelButton, PAGE_DESIDERATA),
            ("Horario", QStyle.StandardPixmap.SP_FileDialogDetailedView, PAGE_SCHEDULE),
            ("Restricciones", QStyle.StandardPixmap.SP_FileDialogContentsView, PAGE_CONSTRAINTS),
            ("Validación", QStyle.StandardPixmap.SP_MessageBoxWarning, PAGE_VALIDATION),
            ("Informes", QStyle.StandardPixmap.SP_FileDialogInfoView, PAGE_REPORTS),
            ("Import/Export", QStyle.StandardPixmap.SP_ArrowDown, PAGE_IMPORT_EXPORT),
            ("Proyecto", QStyle.StandardPixmap.SP_DirIcon, PAGE_PROJECT),
            ("Optimizar", QStyle.StandardPixmap.SP_MediaPlay, PAGE_OPTIMIZE),
        )
        for label, pixmap, page in nav:
            bar.addAction(icon(pixmap), label, lambda _=False, p=page: self.show_page(p))

    # --- navegación / acciones ------------------------------------------ #
    def show_page(self, page: str) -> None:
        """Abre (o enfoca) la ventana hija del módulo, estilo Untis."""
        entry = self._pages.get(page)
        if entry is None:
            return
        widget, title = entry
        sub = self._subwindows.get(page)
        if sub is None:
            sub = self._mdi.addSubWindow(widget)
            sub.setWindowTitle(title)
            # Cerrar la ventana hija solo la oculta (se puede reabrir).
            sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            sub.resize(1080, 660)
            self._subwindows[page] = sub
        sub.show()
        # Al cerrar una subventana, Qt oculta explícitamente su widget interno;
        # al reabrirla hay que mostrarlo también o queda una ventana vacía.
        widget.show()
        sub.raise_()
        self._mdi.setActiveSubWindow(sub)

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
        for widget, _title in self._pages.values():
            refresh = getattr(widget, "refresh", None)
            if callable(refresh):
                refresh()
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
        self._mdi.setEnabled(enabled)
