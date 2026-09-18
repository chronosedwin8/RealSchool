"""Página de Inicio: empezar un colegio y seguir los primeros pasos.

Es lo primero que se ve al abrir RealSchool y vuelve a aparecer cuando se
cierran todas las ventanas. Arriba, tarjetas grandes para crear, abrir,
importar o probar un ejemplo; debajo, la lista «Primeros pasos» con el estado
del proyecto y los proyectos recientes.

La página no abre diálogos por sí misma: emite señales y la ventana principal
decide (así se prueba sin clics reales).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..icons import icon
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import fmt_int
from ..widgets.checklist import ChecklistWidget

#: Proyecto de ejemplo (el export seudonimizado de las pruebas), si existe.
EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "untis_anon.xml"

START_QSS = """
QWidget#start_page { background: #f8fafc; }
QLabel#hero_title { font-size: 22pt; font-weight: 700; color: #0f172a; }
QLabel#hero_subtitle { font-size: 11pt; color: #475569; }
QLabel#section { font-size: 13pt; font-weight: 700; color: #0f172a; }
QLabel#section_hint { color: #64748b; }
QPushButton#card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;
                   text-align: left; }
QPushButton#card:hover { border: 1px solid #2563eb; background: #f8fbff; }
QPushButton#card:focus { border: 2px solid #2563eb; }
QLabel#card_title { font-size: 11pt; font-weight: 700; color: #0f172a; }
QLabel#card_text { color: #475569; }
QFrame#panel { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }
QFrame#step { background: #ffffff; border: 1px solid #eef2f7; border-radius: 8px; }
QFrame#step_next { background: #eff6ff; border: 1px solid #93c5fd; border-radius: 8px; }
QLabel#step_title { font-weight: 700; color: #0f172a; }
QLabel#step_detail { color: #475569; }
QLabel#step_number { background: #e2e8f0; color: #334155; border-radius: 13px;
                     font-weight: 700; }
QPushButton#primary { background: #2563eb; color: white; border: 0; border-radius: 6px;
                      padding: 4px 10px; font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#step_button { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px;
                          padding: 3px 10px; text-align: left; }
QPushButton#step_button:hover { border-color: #2563eb; }
QPushButton#step_button:disabled { color: #94a3b8; }
QPushButton#step_link { color: #1d4ed8; border: 0; padding: 1px 4px; text-align: left; }
QPushButton#step_link:hover { text-decoration: underline; }
QPushButton#step_link:disabled { color: #94a3b8; }
QLabel#chip { min-width: 70px; qproperty-alignment: AlignCenter; }
QListWidget#recent { border: 0; background: transparent; }
QListWidget#recent::item { padding: 6px 4px; border-radius: 6px; }
QListWidget#recent::item:hover { background: #eff6ff; }
QLabel#project_badge { background: #dbeafe; color: #1e3a8a; border-radius: 8px;
                       padding: 6px 12px; font-weight: 600; }
"""


class _TransparentLabel(QLabel):
    """Etiqueta que deja pasar los clics a la tarjeta que la contiene."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class ActionCard(QPushButton):
    """Tarjeta grande con icono, título y una línea de explicación."""

    def __init__(self, icon_name: str, title: str, text: str) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(QSize(220, 118))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(16, 14, 16, 14)
        caja.setSpacing(4)
        imagen = _TransparentLabel()
        imagen.setPixmap(icon(icon_name).pixmap(36, 36))
        self.title_label = _TransparentLabel(title)
        self.title_label.setObjectName("card_title")
        self.text_label = _TransparentLabel(text)
        self.text_label.setObjectName("card_text")
        self.text_label.setWordWrap(True)
        caja.addWidget(imagen)
        caja.addWidget(self.title_label)
        caja.addWidget(self.text_label, 1)
        self.setAccessibleName(title)
        self.setToolTip(text)

    def set_texts(self, title: str, text: str) -> None:
        self.title_label.setText(title)
        self.text_label.setText(text)
        self.setAccessibleName(title)
        self.setToolTip(text)


class StartPage(QScrollArea):
    """Inicio / Primeros pasos."""

    new_requested = Signal()
    open_requested = Signal()
    import_xml_requested = Signal()
    import_gpu_requested = Signal()
    example_requested = Signal(str)
    recent_requested = Signal(str)
    window_requested = Signal(str)

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self._stale = False
        self._recent: list[str] = []
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        pagina = QWidget()
        pagina.setObjectName("start_page")
        pagina.setStyleSheet(START_QSS)
        self.setWidget(pagina)

        raiz = QVBoxLayout(pagina)
        raiz.setContentsMargins(32, 24, 32, 24)
        raiz.setSpacing(18)

        # --- cabecera ------------------------------------------------------ #
        cabecera = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icon("launch").pixmap(48, 48))
        cabecera.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("hero_title")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("hero_subtitle")
        self.subtitle.setWordWrap(True)
        textos.addWidget(self.title)
        textos.addWidget(self.subtitle)
        cabecera.addLayout(textos, 1)
        self.project_badge = QLabel()
        self.project_badge.setObjectName("project_badge")
        cabecera.addWidget(self.project_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        raiz.addLayout(cabecera)

        # --- tarjetas -------------------------------------------------------- #
        self.cards: dict[str, ActionCard] = {
            "new": ActionCard("wizard", "", ""),
            "open": ActionCard("open", "", ""),
            "import": ActionCard("import", "", ""),
            "example": ActionCard("school", "", ""),
        }
        self.cards["new"].clicked.connect(self.new_requested.emit)
        self.cards["open"].clicked.connect(self.open_requested.emit)
        self.cards["import"].clicked.connect(self._import_menu)
        self.cards["example"].clicked.connect(
            lambda: self.example_requested.emit(str(EXAMPLE_PATH))
        )
        self.cards["example"].setVisible(EXAMPLE_PATH.is_file())
        fila = QHBoxLayout()
        fila.setSpacing(14)
        for tarjeta in self.cards.values():
            fila.addWidget(tarjeta)
        raiz.addLayout(fila)

        # --- primeros pasos y recientes -------------------------------------- #
        cuerpo = QGridLayout()
        cuerpo.setHorizontalSpacing(18)

        pasos = QFrame()
        pasos.setObjectName("panel")
        caja_pasos = QVBoxLayout(pasos)
        caja_pasos.setContentsMargins(16, 14, 16, 16)
        self.steps_title = QLabel()
        self.steps_title.setObjectName("section")
        self.steps_hint = QLabel()
        self.steps_hint.setObjectName("section_hint")
        self.steps_hint.setWordWrap(True)
        self.checklist = ChecklistWidget(bridge)
        self.checklist.open_requested.connect(self.window_requested.emit)
        caja_pasos.addWidget(self.steps_title)
        caja_pasos.addWidget(self.steps_hint)
        caja_pasos.addSpacing(6)
        caja_pasos.addWidget(self.checklist)
        caja_pasos.addStretch(1)

        recientes = QFrame()
        recientes.setObjectName("panel")
        caja_rec = QVBoxLayout(recientes)
        caja_rec.setContentsMargins(16, 14, 16, 16)
        self.recent_title = QLabel()
        self.recent_title.setObjectName("section")
        self.recent_empty = QLabel()
        self.recent_empty.setObjectName("section_hint")
        self.recent_empty.setWordWrap(True)
        self.recent_list = QListWidget()
        self.recent_list.setObjectName("recent")
        self.recent_list.setIconSize(QSize(20, 20))
        self.recent_list.itemActivated.connect(self._on_recent)
        self.recent_list.itemClicked.connect(self._on_recent)
        caja_rec.addWidget(self.recent_title)
        caja_rec.addWidget(self.recent_empty)
        caja_rec.addWidget(self.recent_list, 3)
        caja_rec.addStretch(1)
        self.tip = QLabel()
        self.tip.setObjectName("section_hint")
        self.tip.setWordWrap(True)
        caja_rec.addWidget(self.tip)

        cuerpo.addWidget(pasos, 0, 0)
        cuerpo.addWidget(recientes, 0, 1)
        cuerpo.setColumnStretch(0, 3)
        cuerpo.setColumnStretch(1, 1)
        raiz.addLayout(cuerpo, 1)

        bridge.refreshed.connect(self._on_refreshed)
        bridge.project_opened.connect(self.refresh)
        bridge.language_changed.connect(lambda _l: self.refresh())
        self.refresh()

    # --- datos ------------------------------------------------------------ #

    def set_recent(self, paths: list[str]) -> None:
        """Proyectos recientes (los decide la ventana principal)."""
        self._recent = list(paths)
        self.recent_list.clear()
        for ruta in self._recent:
            p = Path(ruta)
            item = QListWidgetItem(icon("open" if p.is_dir() else "save"), p.name or ruta)
            item.setToolTip(ruta)
            item.setData(Qt.ItemDataRole.UserRole, ruta)
            self.recent_list.addItem(item)
        self.recent_empty.setVisible(not self._recent)
        self.recent_list.setVisible(bool(self._recent))

    def recent_paths(self) -> list[str]:
        return list(self._recent)

    def _on_recent(self, item: QListWidgetItem) -> None:
        ruta = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(ruta, str):
            self.recent_requested.emit(ruta)

    def _on_refreshed(self) -> None:
        # Solo se recalcula si se ve: el Diagnóstico de un colegio grande cuesta.
        if self.isVisible():
            self.refresh()
        else:
            self._stale = True

    def showEvent(self, event: QShowEvent) -> None:
        if self._stale:
            self._stale = False
            self.refresh()
        super().showEvent(event)

    def _import_menu(self) -> None:
        menu = QMenu(self)
        xml = menu.addAction(icon("import"), self.tr("Archivo XML de Untis..."))
        gpu = menu.addAction(icon("gpu"), self.tr("Carpeta con archivos GPU..."))
        xml.triggered.connect(self.import_xml_requested.emit)
        gpu.triggered.connect(self.import_gpu_requested.emit)
        tarjeta = self.cards["import"]
        menu.popup(tarjeta.mapToGlobal(tarjeta.rect().bottomLeft()))

    # --- vista ------------------------------------------------------------- #

    def refresh(self) -> None:
        self._stale = False
        self._retranslate()
        self.checklist.refresh()
        self._update_project()

    def _update_project(self) -> None:
        if not self.bridge.has_session:
            self.project_badge.hide()
            self.subtitle.setText(
                self.tr(
                    "Crea el horario de tu colegio paso a paso. Empieza creando un colegio "
                    "nuevo o abriendo uno que ya tengas."
                )
            )
            return
        s = self.bridge.session
        p = s.project
        nombre = p.school.name or (s.path.stem if s.path else self.tr("Colegio sin nombre"))
        self.project_badge.setText(
            self.tr("{0}  |  {1} clases, {2} profesores, {3} lecciones").format(
                nombre, fmt_int(len(p.classes)), fmt_int(len(p.teachers)), fmt_int(len(p.lessons))
            )
        )
        self.project_badge.show()
        siguiente = self.checklist.next_step()
        if siguiente is None:
            self.subtitle.setText(
                self.tr("¡Horario completo! Revísalo, imprímelo o guárdalo (Ctrl+S).")
            )
        else:
            self.subtitle.setText(
                self.tr("Siguiente paso: {0}. {1}").format(siguiente.title, siguiente.detail)
            )

    def _retranslate(self) -> None:
        self.title.setText(self.tr("Bienvenido a RealSchool"))
        self.cards["new"].set_texts(
            self.tr("Crear un colegio nuevo"),
            self.tr("Un asistente te pide el nombre, los días y las horas de clase."),
        )
        self.cards["open"].set_texts(
            self.tr("Abrir proyecto"),
            self.tr("Continúa con un proyecto guardado de RealSchool (.rsp)."),
        )
        self.cards["import"].set_texts(
            self.tr("Importar de Untis"),
            self.tr("Trae tus datos desde un archivo XML o una carpeta de archivos GPU."),
        )
        self.cards["example"].set_texts(
            self.tr("Abrir un ejemplo"),
            self.tr("Explora un colegio real ya preparado, con su horario generado."),
        )
        self.steps_title.setText(self.tr("Primeros pasos"))
        self.steps_hint.setText(
            self.tr(
                "Sigue los pasos en orden; cada uno se marca solo cuando está hecho. "
                "El botón de cada paso abre la ventana donde se hace."
            )
        )
        self.recent_title.setText(self.tr("Proyectos recientes"))
        self.recent_empty.setText(
            self.tr("Aún no hay proyectos recientes. Los que abras o guardes aparecerán aquí.")
        )
        self.tip.setText(self.tr("Consejo: pulsa F1 en cualquier ventana para ver cómo se usa."))


register(
    WindowSpec(
        key="start",
        title="Primeros pasos",
        title_de="Erste Schritte",
        tab=RibbonTab.HOME,
        factory=StartPage,
        order=0,
        icon="launch",
        tooltip="Página de inicio: crear o abrir un colegio y la lista de pasos hasta el horario.",
        tooltip_de=(
            "Startseite: eine Schule anlegen oder öffnen und die Schritte bis zum Stundenplan."
        ),
    )
)
