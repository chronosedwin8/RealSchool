"""Ventana principal: cinta + área MDI + paneles acoplados (sección 8).

Como en Untis, cada ventana es un documento independiente que puede estar
abierto a la vez que las demás; la cinta agrupa las órdenes por pestaña y los
paneles de Diagnóstico y Registro se acoplan a los bordes. Mientras se optimiza,
todas las ventanas salvo la de Optimización quedan bloqueadas.

Para quien empieza: la página de Inicio aparece cuando no hay ninguna ventana
abierta, cada botón de la cinta lleva icono y una descripción con su atajo, F1
abre la ayuda de la ventana activa y la barra de estado resume el horario activo
(número de evaluación, sin colocar, choques y si hay cambios sin guardar).
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMdiArea,
    QMdiSubWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .help import GUIDE_KEY, HelpDialog, help_entry
from .icons import AMBER, GREEN, ICONS, RED, icon, icon_size
from .qt_bridge import FacadeBridge
from .registry import RIBBON_LABELS, RibbonTab, WindowSpec, load_windows
from .theme import fmt_int
from .windows.start import StartPage

#: Ventana que sigue activa mientras se optimiza.
OPTIMIZATION_KEY = "optimization"
#: Página de Inicio / Primeros pasos.
START_KEY = "start"

#: Claves de `QSettings`.
RECENT_KEY = "recent_files"
RECENT_MAX = 8
GEOMETRY_KEY = "main_window/geometry"
STATE_KEY = "main_window/state"

#: Ancho inicial del panel de Diagnóstico (que no se corten los grupos).
DIAGNOSIS_WIDTH = 360

_FILTERS = (
    "Proyectos y horarios Untis (*.rsp *.xml *.bjs);;Proyecto RealSchool (*.rsp);;"
    "Untis XmlInterface (*.xml);;Proyecto antiguo (*.bjs)"
)

#: Atajos de las ventanas principales (si la ventana no declara uno propio).
WINDOW_SHORTCUTS: dict[str, str] = {
    START_KEY: "Ctrl+0",
    "time_grids": "Ctrl+1",
    "classes": "Ctrl+2",
    "teachers": "Ctrl+3",
    "rooms": "Ctrl+4",
    "subjects": "Ctrl+5",
    "lessons": "Ctrl+6",
    OPTIMIZATION_KEY: "Ctrl+7",
    "evaluation": "Ctrl+8",
    "timetables": "Ctrl+9",
    "requests": "Ctrl+Shift+T",
    "planning": "Ctrl+Shift+P",
    "diagnosis": "Ctrl+Shift+D",
}

#: Icono de reserva cuando una ventana no declara el suyo.
_FALLBACK_ICONS: dict[str, str] = {
    OPTIMIZATION_KEY: "optimize",
    "settings": "school",
    START_KEY: "launch",
}

#: Órdenes que necesitan un proyecto abierto.
_SESSION_ACTIONS = ("save", "save_as", "undo", "redo")
#: Órdenes que se bloquean mientras se optimiza.
_FILE_ACTIONS = ("new", "open", "import", "save", "save_as", "undo", "redo")


def window_icon_name(spec: WindowSpec) -> str:
    """Icono de una ventana: el suyo, uno con su clave o uno de reserva."""
    if spec.icon in ICONS:
        return spec.icon
    if spec.key in _FALLBACK_ICONS:
        return _FALLBACK_ICONS[spec.key]
    return spec.key if spec.key in ICONS else "info"


def tooltip_html(title: str, description: str = "", shortcut: str = "") -> str:
    """Descripción de una orden: título, atajo y qué hace."""
    texto = f"<b>{escape(title)}</b>"
    if shortcut:
        texto += f" <span style='color:#64748b'>({escape(shortcut)})</span>"
    if description:
        texto += f"<br>{escape(description)}"
    return texto


class MainWindow(QMainWindow):
    """Cinta, área MDI y paneles."""

    def __init__(
        self, bridge: FacadeBridge | None = None, settings: QSettings | None = None
    ) -> None:
        super().__init__()
        self.bridge = bridge if bridge is not None else FacadeBridge()
        self.settings = settings if settings is not None else QSettings("RealSchool", "RealSchool")
        self.setWindowTitle("RealSchool")
        self.setWindowIcon(icon("school"))
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
        self._owned_actions: list[QAction] = []
        self._ribbon_buttons: list[QToolButton] = []
        self.help_dialog: HelpDialog | None = None
        self.wizard: QWidget | None = None
        self._busy = False
        """Último aviso de `busy_changed` (se sigue la señal, no el hilo)."""

        # --- paneles -------------------------------------------------------- #
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        registro = QDockWidget(self.tr("Registro"), self)
        registro.setObjectName("dock_log")
        registro.setWidget(self.log)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, registro)
        registro.hide()
        self._docks["log"] = registro

        for spec in self._specs.values():
            if spec.dock:
                self._make_dock(spec)
        if "diagnosis" in self._docks:
            self.resizeDocks(
                [self._docks["diagnosis"]], [DIAGNOSIS_WIDTH], Qt.Orientation.Horizontal
            )

        # --- cinta ---------------------------------------------------------- #
        self.ribbon = QTabWidget()
        self.ribbon.setObjectName("ribbon")
        self.ribbon.setDocumentMode(True)
        self.ribbon.setStyleSheet(
            "QTabWidget#ribbon QWidget#ribbon_page { background: #ffffff; }"
            " QLabel#ribbon_caption { color: #64748b; font-size: 8pt; }"
            " QToolButton#ribbon_button { padding: 2px 4px; min-width: 56px; }"
        )
        self._build_ribbon()
        barra = QToolBar(self.tr("Cinta"))
        barra.setObjectName("ribbon_bar")
        barra.setMovable(False)
        barra.setFloatable(False)
        barra.toggleViewAction().setEnabled(False)
        barra.addWidget(self.ribbon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, barra)

        # --- barra de estado -------------------------------------------------- #
        self.eval_button = self._status_button("evaluation")
        self.unplaced_button = self._status_button("ok")
        self.clashes_button = self._status_button("ok")
        self.dirty_label = QLabel()
        self.dirty_label.setStyleSheet("color: #b45309; font-weight: 600; padding: 0 6px;")
        self.statusBar().addPermanentWidget(self.eval_button)
        self.statusBar().addPermanentWidget(self.unplaced_button)
        self.statusBar().addPermanentWidget(self.clashes_button)
        self.statusBar().addPermanentWidget(self.dirty_label)

        # --- señales ------------------------------------------------------------ #
        self.bridge.status.connect(self._on_status)
        self.bridge.project_opened.connect(self._on_project_opened)
        self.bridge.project_changed.connect(lambda _label: self._update_title())
        self.bridge.refreshed.connect(self._refresh_status)
        self.bridge.busy_changed.connect(self._on_busy)
        self.bridge.language_changed.connect(lambda _lang: self._retranslate())

        self._restore_layout()
        self.show_window(START_KEY)
        self._update_title()
        self._refresh_status()

    # ===================================================================== #
    # Cinta
    # ===================================================================== #

    def _group_captions(self) -> dict[str, str]:
        """Grupo de la cinta de cada ventana."""
        colegio = self.tr("Colegio")
        entidades = self.tr("Entidades")
        tiempo = self.tr("Tiempo")
        return {
            START_KEY: colegio,
            "settings": colegio,
            "classes": entidades,
            "teachers": entidades,
            "rooms": entidades,
            "subjects": entidades,
            "departments": entidades,
            "student_groups": entidades,
            "time_grids": tiempo,
            "requests": tiempo,
            "lessons": self.tr("Lecciones"),
            "weighting": self.tr("Ajustes"),
            OPTIMIZATION_KEY: self.tr("Generar"),
            "evaluation": self.tr("Revisar"),
            "diagnosis": self.tr("Revisar"),
            "planning": self.tr("Planificar"),
            "timetables": self.tr("Salida"),
        }

    def _build_ribbon(self) -> None:
        for accion in self._owned_actions:
            self.removeAction(accion)
            accion.deleteLater()
        self._owned_actions.clear()
        self._ribbon_buttons.clear()
        self._actions.clear()
        self.ribbon.clear()
        lang = self.bridge.language
        grupos: dict[RibbonTab, list[tuple[str, list[QAction]]]] = {t: [] for t in RibbonTab}

        def grupo(tab: RibbonTab, caption: str) -> list[QAction]:
            for nombre, acciones in grupos[tab]:
                if nombre == caption:
                    return acciones
            nuevas: list[QAction] = []
            grupos[tab].append((caption, nuevas))
            return nuevas

        # --- Inicio: archivo y edición ------------------------------------------ #
        archivo = grupo(RibbonTab.HOME, self.tr("Archivo"))
        std = QKeySequence.StandardKey
        archivo.append(
            self._make_action(
                "new",
                self.tr("Nuevo"),
                "new",
                self.new_project,
                self.tr("Crea un colegio nuevo con un asistente paso a paso."),
                QKeySequence(std.New),
            )
        )
        archivo.append(
            self._make_action(
                "open",
                self.tr("Abrir"),
                "open",
                self.open_dialog,
                self.tr("Abre un proyecto de RealSchool (.rsp) o un archivo de Untis."),
                QKeySequence(std.Open),
            )
        )
        importar = self._make_action(
            "import",
            self.tr("Importar"),
            "import",
            self.import_xml_dialog,
            self.tr("Importa datos de Untis: un archivo XML o una carpeta de archivos GPU."),
            QKeySequence("Ctrl+I"),
        )
        menu = QMenu(self)
        menu.addAction(icon("import"), self.tr("Archivo XML de Untis..."), self.import_xml_dialog)
        menu.addAction(icon("gpu"), self.tr("Carpeta con archivos GPU..."), self.import_gpu_dialog)
        importar.setMenu(menu)
        archivo.append(importar)
        archivo.append(
            self._make_action(
                "save",
                self.tr("Guardar"),
                "save",
                self.save,
                self.tr("Guarda el proyecto en su archivo .rsp."),
                QKeySequence(std.Save),
            )
        )
        archivo.append(
            self._make_action(
                "save_as",
                self.tr("Guardar como"),
                "save_as",
                self.save_as,
                self.tr("Guarda el proyecto con otro nombre o en otra carpeta."),
                QKeySequence(std.SaveAs),
            )
        )
        edicion = grupo(RibbonTab.HOME, self.tr("Edición"))
        edicion.append(
            self._make_action(
                "undo",
                self.tr("Deshacer"),
                "undo",
                self.bridge.undo,
                self.tr("Deshace el último cambio."),
                QKeySequence(std.Undo),
            )
        )
        edicion.append(
            self._make_action(
                "redo",
                self.tr("Rehacer"),
                "redo",
                self.bridge.redo,
                self.tr("Vuelve a aplicar el cambio deshecho."),
                QKeySequence(std.Redo),
            )
        )

        # --- ventanas registradas ------------------------------------------------ #
        captions = self._group_captions()
        for spec in self._specs.values():
            atajo = spec.shortcut or WINDOW_SHORTCUTS.get(spec.key, "")
            ayuda = help_entry(spec.key)
            descripcion = spec.description(self.bridge.language) or (
                ayuda.summary if ayuda is not None else ""
            )
            accion = self._make_action(
                f"window:{spec.key}",
                spec.label(lang),
                window_icon_name(spec),
                self._opener(spec.key),
                descripcion,
                QKeySequence(atajo) if atajo else None,
            )
            caption = captions.get(spec.key, RIBBON_LABELS[spec.tab][1 if lang == "de" else 0])
            grupo(spec.tab, caption).append(accion)

        # --- Inicio: ayuda ------------------------------------------------------------ #
        ayuda_grupo = grupo(RibbonTab.HOME, self.tr("Ayuda"))
        ayuda_grupo.append(
            self._make_action(
                "guide",
                self.tr("Guía rápida"),
                "steps",
                self.show_quick_guide,
                self.tr("El flujo completo, de la rejilla de tiempo al horario impreso."),
                QKeySequence("Shift+F1"),
            )
        )
        ayuda_grupo.append(
            self._make_action(
                "help",
                self.tr("Ayuda"),
                "help",
                self.show_help,
                self.tr("Explica para qué sirve la ventana activa y cómo se usa."),
                QKeySequence(std.HelpContents),
            )
        )

        # --- Vista ---------------------------------------------------------------------- #
        ventanas = grupo(RibbonTab.VIEW, self.tr("Ventanas"))
        ventanas.append(
            self._make_action(
                "tile",
                self.tr("Mosaico"),
                "tile",
                self.tile,
                self.tr("Muestra todas las ventanas abiertas a la vez, una junto a otra."),
            )
        )
        ventanas.append(
            self._make_action(
                "cascade",
                self.tr("Cascada"),
                "cascade",
                self.cascade,
                self.tr("Superpone las ventanas abiertas, escalonadas."),
            )
        )
        ventanas.append(
            self._make_action(
                "tabs",
                self.tr("Pestañas"),
                "columns",
                self.tabbed,
                self.tr("Vuelve a mostrar una ventana cada vez, con pestañas."),
            )
        )
        paneles = grupo(RibbonTab.VIEW, self.tr("Paneles"))
        registro = self._docks["log"].toggleViewAction()
        registro.setText(self.tr("Registro"))
        registro.setIcon(icon("history"))
        registro.setShortcut(QKeySequence("Ctrl+Shift+L"))
        registro.setToolTip(
            tooltip_html(
                self.tr("Registro"),
                self.tr("Muestra u oculta la lista de mensajes de la sesión."),
                "Ctrl+Shift+L",
            )
        )
        self.addAction(registro)
        self._actions["log"] = registro
        paneles.append(registro)
        idiomas = grupo(RibbonTab.VIEW, self.tr("Idioma"))
        grupo_idioma = QActionGroup(self)
        for codigo, nombre in (("es", "Español"), ("de", "Deutsch")):
            accion = self._make_action(
                f"lang:{codigo}",
                nombre,
                "language",
                self._language_setter(codigo),
                self.tr("Cambia el idioma de toda la interfaz."),
            )
            accion.setCheckable(True)
            accion.setChecked(lang == codigo)
            grupo_idioma.addAction(accion)
            idiomas.append(accion)

        for tab in RibbonTab:
            es, de = RIBBON_LABELS[tab]
            self.ribbon.addTab(self._ribbon_page(grupos[tab]), de if lang == "de" else es)

    def _make_action(
        self,
        key: str,
        text: str,
        icon_name: str,
        slot: Callable[[], object],
        description: str,
        shortcut: QKeySequence | None = None,
    ) -> QAction:
        accion = QAction(icon(icon_name), text, self)
        atajo = ""
        if shortcut is not None and not shortcut.isEmpty():
            accion.setShortcut(shortcut)
            atajo = shortcut.toString(QKeySequence.SequenceFormat.NativeText)
        accion.setToolTip(tooltip_html(text, description, atajo))
        accion.setStatusTip(description)
        accion.setData(description)
        accion.triggered.connect(lambda _checked=False: slot())
        self.addAction(accion)
        self._owned_actions.append(accion)
        self._actions[key] = accion
        return accion

    def _ribbon_page(self, groups: list[tuple[str, list[QAction]]]) -> QWidget:
        pagina = QWidget()
        pagina.setObjectName("ribbon_page")
        fila = QHBoxLayout(pagina)
        fila.setContentsMargins(6, 2, 6, 0)
        fila.setSpacing(4)
        for indice, (caption, acciones) in enumerate(groups):
            if not acciones:
                continue
            if indice:
                linea = QFrame()
                linea.setFrameShape(QFrame.Shape.VLine)
                linea.setStyleSheet("color: #e2e8f0;")
                fila.addWidget(linea)
            caja = QVBoxLayout()
            caja.setSpacing(0)
            botones = QHBoxLayout()
            botones.setSpacing(1)
            for accion in acciones:
                boton = QToolButton()
                boton.setObjectName("ribbon_button")
                boton.setDefaultAction(accion)
                boton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                boton.setIconSize(icon_size("ribbon"))
                boton.setAutoRaise(True)
                if accion.menu() is not None:
                    boton.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
                botones.addWidget(boton)
                self._ribbon_buttons.append(boton)
            caja.addLayout(botones)
            etiqueta = QLabel(caption)
            etiqueta.setObjectName("ribbon_caption")
            etiqueta.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            caja.addWidget(etiqueta)
            fila.addLayout(caja)
        fila.addStretch(1)
        return pagina

    def ribbon_actions(self) -> list[QAction]:
        """Acciones visibles en la cinta (una por botón)."""
        return [b.defaultAction() for b in self._ribbon_buttons]

    def _language_setter(self, language: str) -> Callable[[], None]:
        def cambiar() -> None:
            self.bridge.set_language(language)

        return cambiar

    def _opener(self, key: str) -> Callable[[], None]:
        def abrir() -> None:
            self.show_window(key)

        return abrir

    # ===================================================================== #
    # Ventanas
    # ===================================================================== #

    def window_widget(self, key: str) -> QWidget:
        """El widget de una ventana (lo crea la primera vez)."""
        if key not in self._widgets:
            widget = self._specs[key].factory(self.bridge)
            self._widgets[key] = widget
            if isinstance(widget, StartPage):
                self._wire_start(widget)
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
            sub.setWindowIcon(icon(window_icon_name(spec)))
            sub.installEventFilter(self)
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

    def active_window_key(self) -> str:
        """Ventana activa: el panel con el foco o la ventana MDI actual."""
        foco = QApplication.focusWidget()
        if foco is not None:
            for key, dock in self._docks.items():
                if key in self._specs and dock.isVisible() and dock.isAncestorOf(foco):
                    return key
        actual = self.mdi.currentSubWindow()
        for key, sub in self._subwindows.items():
            if sub is actual and sub.isVisible():
                return key
        return START_KEY

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Close and isinstance(watched, QMdiSubWindow):
            cerrada = next((k for k, s in self._subwindows.items() if s is watched), "")
            if cerrada != START_KEY:
                QTimer.singleShot(0, self._show_start_if_empty)
        return super().eventFilter(watched, event)

    def _show_start_if_empty(self) -> None:
        if not self.open_keys():
            self.show_window(START_KEY)

    def tile(self) -> None:
        self.mdi.setViewMode(QMdiArea.ViewMode.SubWindowView)
        self.mdi.tileSubWindows()

    def cascade(self) -> None:
        self.mdi.setViewMode(QMdiArea.ViewMode.SubWindowView)
        self.mdi.cascadeSubWindows()

    def tabbed(self) -> None:
        self.mdi.setViewMode(QMdiArea.ViewMode.TabbedView)

    # --- página de Inicio -------------------------------------------------------- #

    def _wire_start(self, page: StartPage) -> None:
        page.new_requested.connect(self.new_project)
        page.open_requested.connect(self.open_dialog)
        page.import_xml_requested.connect(self.import_xml_dialog)
        page.import_gpu_requested.connect(self.import_gpu_dialog)
        page.example_requested.connect(self._open_confirmed)
        page.recent_requested.connect(self._open_confirmed)
        page.window_requested.connect(self.show_window)
        page.set_recent(self.recent_files())

    def start_page(self) -> StartPage:
        pagina = self.window_widget(START_KEY)
        assert isinstance(pagina, StartPage)
        return pagina

    # --- ayuda ---------------------------------------------------------------------- #

    def _help(self) -> HelpDialog:
        if self.help_dialog is None:
            temas = [(GUIDE_KEY, "steps")] + [
                (s.key, window_icon_name(s)) for s in self._specs.values()
            ]
            self.help_dialog = HelpDialog(temas, self)
        return self.help_dialog

    def show_help(self, key: str | None = None) -> HelpDialog:
        """Ayuda de la ventana activa (F1) o de `key`."""
        dialogo = self._help()
        dialogo.show_topic(key or self.active_window_key())
        dialogo.show()
        dialogo.raise_()
        return dialogo

    def show_quick_guide(self) -> HelpDialog:
        return self.show_help(GUIDE_KEY)

    # ===================================================================== #
    # Archivo
    # ===================================================================== #

    def new_project(self) -> None:
        """Abre el asistente «Crear un colegio nuevo»."""
        if self.bridge.busy or not self._confirm_discard():
            return
        from .widgets.wizard import NewSchoolWizard

        asistente = NewSchoolWizard(self.bridge, self)
        asistente.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        asistente.accepted.connect(lambda: self.show_window(START_KEY))
        self.wizard = asistente
        asistente.open()

    def open_dialog(self) -> None:
        if not self._confirm_discard():
            return
        ruta, _ = QFileDialog.getOpenFileName(self, self.tr("Abrir"), "", _FILTERS)
        if ruta:
            self.open_path(ruta)

    def import_xml_dialog(self) -> None:
        if not self._confirm_discard():
            return
        ruta, _ = QFileDialog.getOpenFileName(
            self, self.tr("Importar de Untis"), "", "Untis XmlInterface (*.xml)"
        )
        if ruta:
            self.open_path(ruta)

    def import_gpu_dialog(self) -> None:
        if not self._confirm_discard():
            return
        carpeta = QFileDialog.getExistingDirectory(
            self, self.tr("Carpeta con archivos GPU de Untis")
        )
        if carpeta:
            self.open_path(carpeta)

    def _open_confirmed(self, path: str) -> None:
        if self._confirm_discard():
            self.open_path(path)

    def open_path(self, path: str | Path) -> bool:
        try:
            self.bridge.open(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self.tr("Abrir"), str(exc))
            return False
        self.remember(path)
        return True

    def save(self) -> None:
        if not self.bridge.has_session:
            return
        if self.bridge.session.path is None:
            self.save_as()
        else:
            self.remember(self.bridge.save())

    def save_as(self) -> None:
        if not self.bridge.has_session:
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self, self.tr("Guardar como"), "", self.tr("Proyecto (*.rsp)")
        )
        if ruta:
            self.remember(self.bridge.save(ruta))

    def _confirm_discard(self) -> bool:
        if not self.bridge.has_session or not self.bridge.session.dirty:
            return True
        respuesta = QMessageBox.question(
            self, "RealSchool", self.tr("Hay cambios sin guardar. ¿Descartarlos?")
        )
        return respuesta == QMessageBox.StandardButton.Yes

    # --- recientes ------------------------------------------------------------------ #

    def recent_files(self) -> list[str]:
        """Proyectos recientes que siguen existiendo (el más reciente primero)."""
        valor = self.settings.value(RECENT_KEY, [])
        if isinstance(valor, str):
            valor = [valor] if valor else []
        if not isinstance(valor, list):
            return []
        return [str(v) for v in valor if isinstance(v, str) and Path(v).exists()][:RECENT_MAX]

    def remember(self, path: str | Path) -> None:
        """Pone `path` el primero de la lista de recientes."""
        ruta = str(Path(path).resolve())
        lista = [ruta, *(p for p in self.recent_files() if p != ruta)][:RECENT_MAX]
        self.settings.setValue(RECENT_KEY, lista)
        self.settings.sync()
        if START_KEY in self._widgets:
            self.start_page().set_recent(self.recent_files())

    # --- disposición --------------------------------------------------------------- #

    def _restore_layout(self) -> None:
        geometria = self.settings.value(GEOMETRY_KEY)
        if isinstance(geometria, QByteArray) and not geometria.isEmpty():
            self.restoreGeometry(geometria)
        estado = self.settings.value(STATE_KEY)
        if isinstance(estado, QByteArray) and not estado.isEmpty():
            self.restoreState(estado)

    def save_layout(self) -> None:
        """Guarda tamaño, posición y paneles para la próxima vez."""
        self.settings.setValue(GEOMETRY_KEY, self.saveGeometry())
        self.settings.setValue(STATE_KEY, self.saveState())
        self.settings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.bridge.busy:
            self.bridge.cancel_optimize()
        if self._confirm_discard():
            self.save_layout()
            if self.help_dialog is not None:
                self.help_dialog.close()
            event.accept()
        else:
            event.ignore()

    # ===================================================================== #
    # Estado
    # ===================================================================== #

    def _status_button(self, icon_name: str) -> QToolButton:
        boton = QToolButton()
        boton.setAutoRaise(True)
        boton.setIcon(icon(icon_name))
        boton.setIconSize(icon_size("small"))
        boton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        boton.clicked.connect(lambda: self.show_window("evaluation"))
        boton.hide()
        return boton

    def _refresh_status(self) -> None:
        botones = (self.eval_button, self.unplaced_button, self.clashes_button)
        if not self.bridge.has_session:
            for b in botones:
                b.hide()
            return
        ev = self.bridge.service.evaluation(self.bridge.session)
        abrir = self.tr("Clic para abrir la ventana Evaluación.")
        if ev is None:
            self.eval_button.setIcon(icon("info"))
            self.eval_button.setText(self.tr("Sin horario"))
            self.eval_button.setToolTip(
                self.tr("Aún no hay horario: genera uno en Horarios -> Optimización.")
            )
            self.eval_button.show()
            self.unplaced_button.hide()
            self.clashes_button.hide()
            return
        # El color del indicador resume el estado: rojo con choques, ámbar con
        # períodos sin colocar, verde si el horario está completo.
        estado = RED if ev.clashes else (AMBER if ev.unplaced_periods else GREEN)
        self.eval_button.setIcon(icon("evaluation", estado))
        self.eval_button.setText(self.tr("Evaluación: {0}").format(fmt_int(ev.total)))
        self.eval_button.setToolTip(
            self.tr("Número de evaluación del horario activo (más bajo es mejor). {0}").format(
                abrir
            )
        )
        self.unplaced_button.setIcon(icon("ok" if ev.unplaced_periods == 0 else "warning"))
        self.unplaced_button.setText(
            self.tr("Sin colocar: {0}").format(fmt_int(ev.unplaced_periods))
        )
        self.unplaced_button.setToolTip(
            self.tr("Períodos de clase que no caben en el horario. {0}").format(abrir)
        )
        self.clashes_button.setIcon(icon("ok" if ev.clashes == 0 else "error"))
        self.clashes_button.setText(self.tr("Choques: {0}").format(fmt_int(ev.clashes)))
        self.clashes_button.setToolTip(
            self.tr("Profesores, clases o aulas con dos clases a la vez. {0}").format(abrir)
        )
        for b in botones:
            b.show()

    def _on_status(self, text: str) -> None:
        if text:
            self.statusBar().showMessage(text, 8000)
            self.log.appendPlainText(text)

    def _on_project_opened(self) -> None:
        self._update_title()
        if not self.open_keys():
            self.show_window(START_KEY)

    def _on_busy(self, busy: bool) -> None:
        self._busy = busy
        for key, sub in self._subwindows.items():
            sub.setEnabled(not busy or key == OPTIMIZATION_KEY)
        self._sync_actions()

    def _sync_actions(self) -> None:
        """Activa o desactiva las órdenes según haya proyecto y se esté optimizando."""
        ocupado = self._busy or self.bridge.busy
        sesion = self.bridge.has_session
        for key, accion in self._actions.items():
            if key in _FILE_ACTIONS:
                accion.setEnabled(not ocupado and (sesion or key not in _SESSION_ACTIONS))
            elif key.startswith("window:") and key != f"window:{START_KEY}":
                accion.setEnabled(sesion)
        if sesion:
            s = self.bridge.session
            self._actions["undo"].setEnabled(s.can_undo and not ocupado)
            self._actions["redo"].setEnabled(s.can_redo and not ocupado)
        self._update_undo_tooltips()

    def _update_undo_tooltips(self) -> None:
        deshacer, rehacer = self._actions["undo"], self._actions["redo"]
        std = QKeySequence.StandardKey
        nat = QKeySequence.SequenceFormat.NativeText
        etiqueta_d = etiqueta_r = ""
        if self.bridge.has_session:
            etiqueta_d = self.bridge.session.undo_label
            etiqueta_r = self.bridge.session.redo_label
        titulo_d = (
            self.tr("Deshacer: {0}").format(etiqueta_d) if etiqueta_d else self.tr("Deshacer")
        )
        titulo_r = self.tr("Rehacer: {0}").format(etiqueta_r) if etiqueta_r else self.tr("Rehacer")
        deshacer.setToolTip(
            tooltip_html(
                titulo_d,
                self.tr("Deshace el último cambio."),
                QKeySequence(std.Undo).toString(nat),
            )
        )
        rehacer.setToolTip(
            tooltip_html(
                titulo_r,
                self.tr("Vuelve a aplicar el cambio deshecho."),
                QKeySequence(std.Redo).toString(nat),
            )
        )

    def _update_title(self) -> None:
        self._sync_actions()
        if not self.bridge.has_session:
            self.setWindowTitle("RealSchool")
            self.dirty_label.setText("")
            return
        s = self.bridge.session
        nombre = s.project.school.name or (s.path.stem if s.path else self.tr("sin título"))
        marca = " *" if s.dirty else ""
        self.setWindowTitle(f"RealSchool - {nombre}{marca}")
        self.dirty_label.setText(self.tr("Sin guardar") if s.dirty else "")
        self.dirty_label.setToolTip(
            self.tr("Hay cambios sin guardar: pulsa Ctrl+S para guardarlos.") if s.dirty else ""
        )

    def _retranslate(self) -> None:
        indice = self.ribbon.currentIndex()
        self._build_ribbon()
        self.ribbon.setCurrentIndex(indice)
        self._update_title()
        self._refresh_status()
        self._docks["log"].setWindowTitle(self.tr("Registro"))
        for key, sub in self._subwindows.items():
            sub.setWindowTitle(self._specs[key].label(self.bridge.language))
        for key, dock in self._docks.items():
            if key in self._specs:
                dock.setWindowTitle(self._specs[key].label(self.bridge.language))
        if self.help_dialog is not None:
            self.help_dialog.retranslate()
