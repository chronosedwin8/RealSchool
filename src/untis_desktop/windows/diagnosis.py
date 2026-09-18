"""Panel Diagnóstico: datos de entrada y horario, siempre a mano (panel derecho).

Árbol de tres niveles como en Untis: rama ("Datos de entrada" / "Horario") ->
grupo (criterio o código de hallazgo, con cantidad y suma) -> hallazgo. Los
grupos del horario llegan de la Fachada ordenados por peso; se conserva ese
orden y los errores van siempre primero. Doble clic en un hallazgo salta a la
lección o a la entidad y abre el Diálogo de planificación.

Calcular el diagnóstico cuesta 0,1-0,3 s en un colegio real, así que el panel
solo se recalcula si está visible y agrupa las ediciones seguidas (espera
corta) para no frenar el arrastre en el Diálogo de planificación. Al abrir otro
proyecto el árbol viejo se vacía enseguida (aunque el panel esté oculto) y se
recalcula en cuanto se ve.

Los grupos se muestran con nombres legibles (la etiqueta del criterio o una
frase para cada código de hallazgo), nunca con el código interno.
"""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QShowEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import CRITERION_TEXTS, DiagnosisItem, DiagnosisView

from ..icons import icon
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import fmt_int
from ..widgets.uikit import Banner

#: Icono de cada rama del árbol.
BRANCH_ICONS: dict[str, str] = {"datos": "table", "horario": "timetables"}

#: Rol con el índice del hallazgo en `DiagnosisPanel.items`.
ITEM_ROLE = Qt.ItemDataRole.UserRole + 1
#: Espera para agrupar refrescos seguidos (ms).
DEBOUNCE_MS = 250

_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}
_ENTITY_KINDS = ("class", "teacher", "room", "subject")


def entity_of(item: DiagnosisItem) -> tuple[str, str] | None:
    """Entidad a la que salta un hallazgo (`tipo`, `id`), si la hay.

    Los choques no traen `entity_kind`, pero su grupo lo dice (`choque_teacher`).
    """
    if not item.entity_id:
        return None
    tipo = item.entity_kind
    if not tipo and item.group.startswith("choque_"):
        tipo = item.group.removeprefix("choque_")
    return (tipo, item.entity_id) if tipo in _ENTITY_KINDS else None


class DiagnosisPanel(QWidget):
    """Árbol de Diagnóstico con salto a la lección o entidad."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.view: DiagnosisView | None = None
        self.items: list[DiagnosisItem] = []
        self._stale = True

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        fuerte = self.summary.font()
        fuerte.setBold(True)
        self.summary.setFont(fuerte)
        self.model = QStandardItemModel(self)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setIndentation(14)
        self.tree.doubleClicked.connect(self._on_double_clicked)
        self.hint = Banner("tip")

        capa = QVBoxLayout(self)
        capa.setContentsMargins(2, 2, 2, 2)
        capa.addWidget(self.summary)
        capa.addWidget(self.tree, 1)
        capa.addWidget(self.hint)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh)

        bridge.refreshed.connect(self._on_refreshed)
        bridge.project_opened.connect(self._on_project_opened)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()

    # --- textos -------------------------------------------------------------- #

    def _retranslate(self) -> None:
        self._set_headers()
        self.hint.setText(
            self.tr(
                "Doble clic en un hallazgo para ir a su lección en el Diálogo de planificación."
            )
        )
        if self.view is not None:
            self._fill(self.view)
        else:
            self._show_pending()

    def _set_headers(self) -> None:
        self.model.setHorizontalHeaderLabels([self.tr("Hallazgo"), self.tr("Nº"), self.tr("Suma")])
        for col, ayuda in enumerate(
            (
                self.tr("Qué problema es; despliega el grupo para ver cada caso"),
                self.tr("Cuántos casos hay en el grupo"),
                self.tr("Cantidad total (p. ej. períodos o huecos) del grupo"),
            )
        ):
            cabecera = self.model.horizontalHeaderItem(col)
            if cabecera is not None:
                cabecera.setToolTip(ayuda)
        cabecera_vista = self.tree.header()
        if cabecera_vista.count() >= 3:
            cabecera_vista.setStretchLastSection(False)
            cabecera_vista.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            cabecera_vista.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            cabecera_vista.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

    def _show_pending(self) -> None:
        """Texto del resumen mientras no hay diagnóstico calculado."""
        self.summary.setStyleSheet("")
        if self.bridge.has_session:
            self.summary.setText(self.tr("Calculando el diagnóstico..."))
        else:
            self.summary.setText(self.tr("Sin proyecto: abre o crea uno para ver su diagnóstico."))

    def group_label(self, group: str) -> str:
        """Nombre legible de un grupo (criterio o código de hallazgo)."""
        textos = CRITERION_TEXTS.get(group)
        if textos is not None:
            return textos[1] if self.bridge.language == "de" and textos[1] else textos[0]
        especiales = {
            "no_colocados": self.tr("Períodos sin colocar"),
            "choque_teacher": self.tr("Choques de profesores"),
            "choque_class": self.tr("Choques de clases"),
            "choque_room": self.tr("Choques de aulas"),
            "choque_time_request": self.tr("Deseos imposibles (-3) incumplidos"),
            "grid_sin_periodos": self.tr("Rejillas sin períodos"),
            "clase_rejilla_inexistente": self.tr("Clases con una rejilla que no existe"),
            "clase_aula_base_inexistente": self.tr("Clases con un aula base que no existe"),
            "profesor_aula_base_inexistente": self.tr("Profesores con un aula base que no existe"),
            "aula_alternativa_inexistente": self.tr("Aulas alternativas que no existen"),
            "aula_cadena_ciclica": self.tr("Aulas alternativas en círculo"),
            "linea_materia_inexistente": self.tr("Líneas con una materia que no existe"),
            "linea_profesor_inexistente": self.tr("Líneas con un profesor que no existe"),
            "linea_clase_inexistente": self.tr("Líneas con una clase que no existe"),
            "linea_grupo_inexistente": self.tr("Líneas con un grupo de alumnos que no existe"),
            "linea_aula_inexistente": self.tr("Líneas con un aula que no existe"),
            "linea_sin_alumnos": self.tr("Líneas sin clases ni grupo"),
            "leccion_duplicada": self.tr("Lecciones con el número repetido"),
            "leccion_sin_horas": self.tr("Lecciones sin períodos por semana"),
            "leccion_rejilla_inexistente": self.tr("Lecciones con una rejilla que no existe"),
            "dobles_imposibles": self.tr("Dobles que no pueden cumplirse"),
            "clase_sobrecargada": self.tr("Clases con más períodos que huecos"),
            "deseo_contradictorio": self.tr("Deseos de tiempo contradictorios"),
        }
        texto = especiales.get(group)
        if texto is not None:
            return texto
        legible = group.replace("_", " ").strip()
        return legible[:1].upper() + legible[1:]

    def group_help(self, group: str) -> str:
        """Ayuda emergente de un grupo: qué cuenta y qué hacer."""
        textos = CRITERION_TEXTS.get(group)
        if textos is not None and textos[2]:
            return f"{self.group_label(group)}\n{textos[2]}"
        if group.startswith("choque_"):
            return self.tr(
                "{0}\nUn recurso está ocupado dos veces a la misma hora. Corrígelo moviendo "
                "una de las lecciones o con Reparar en Optimización."
            ).format(self.group_label(group))
        if group == "no_colocados":
            return self.tr(
                "{0}\nPeríodos que aún no tienen hora. Arrástralos desde la lista del "
                "Diálogo de planificación."
            ).format(self.group_label(group))
        return self.tr(
            "{0}\nError en los datos de entrada: corrígelo en la ventana indicada."
        ).format(self.group_label(group))

    # --- refresco perezoso ------------------------------------------------------ #

    def _on_project_opened(self) -> None:
        """Otro proyecto: el árbol viejo ya no vale; se vacía y se marca pendiente."""
        self._stale = True
        self.view = None
        self.items = []
        self.model.removeRows(0, self.model.rowCount())
        self._show_pending()

    def _on_refreshed(self) -> None:
        if self.isVisible():
            self._timer.start()
        else:
            self._stale = True
            if self.view is None:
                self._show_pending()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._stale:
            self._timer.start()

    def refresh(self) -> None:
        """Recalcula el diagnóstico (horario activo) y rehace el árbol."""
        self._timer.stop()
        self._stale = False
        if not self.bridge.has_session:
            self.view = None
            self.items = []
            self.model.removeRows(0, self.model.rowCount())
            self._show_pending()
            return
        self.view = self.bridge.service.diagnosis(self.bridge.session)
        self._fill(self.view)

    def _fill(self, view: DiagnosisView) -> None:
        self.items = list(view.items)
        self.model.removeRows(0, self.model.rowCount())
        iconos = {"error": icon("error"), "warning": icon("warning"), "info": icon("info")}
        colores = {"error": QBrush(QColor("#b91c1c")), "warning": QBrush(QColor("#92400e"))}
        ramas = (("datos", self.tr("Datos de entrada")), ("horario", self.tr("Horario")))
        for rama, titulo in ramas:
            grupos: dict[str, list[int]] = defaultdict(list)
            for i, it in enumerate(self.items):
                if it.branch == rama:
                    grupos[it.group].append(i)
            orden = sorted(
                grupos.items(),
                key=lambda kv: min(_SEVERITY_RANK.get(self.items[i].severity, 3) for i in kv[1]),
            )
            total = sum(len(v) for v in grupos.values())
            nodo = QStandardItem(icon(BRANCH_ICONS[rama]), f"{titulo} ({total})")
            nodo.setData(rama, Qt.ItemDataRole.UserRole)
            nodo.setToolTip(
                self.tr("Problemas de los datos: se ven antes de optimizar")
                if rama == "datos"
                else self.tr("Problemas del horario activo: choques, huecos, deseos...")
            )
            fuente = nodo.font()
            fuente.setBold(True)
            nodo.setFont(fuente)
            fila_rama = [nodo, QStandardItem(str(total)), QStandardItem("")]
            for grupo, indices in orden:
                severidad = min(
                    (self.items[i].severity for i in indices),
                    key=lambda s: _SEVERITY_RANK.get(s, 3),
                )
                suma = sum(self.items[i].amount for i in indices)
                g = QStandardItem(self.group_label(grupo))
                g.setData(grupo, Qt.ItemDataRole.UserRole)
                g.setToolTip(self.group_help(grupo))
                if severidad in iconos:
                    g.setIcon(iconos[severidad])
                if severidad in colores:
                    g.setForeground(colores[severidad])
                fila_grupo = [g, QStandardItem(str(len(indices))), QStandardItem(str(suma))]
                for i in indices:
                    it = self.items[i]
                    hoja = QStandardItem(it.message)
                    hoja.setData(i, ITEM_ROLE)
                    hoja.setToolTip(it.message)
                    if it.severity in iconos:
                        hoja.setIcon(iconos[it.severity])
                    g.appendRow([hoja, QStandardItem(""), QStandardItem(str(it.amount))])
                nodo.appendRow(fila_grupo)
            self.model.appendRow(fila_rama)
        for fila in range(self.model.rowCount()):
            self.tree.expand(self.model.index(fila, 0))
        self._set_headers()
        self.summary.setText(
            self.tr("{0} error(es), {1} advertencia(s)").format(
                fmt_int(view.errors), fmt_int(view.warnings)
            )
        )
        self.summary.setStyleSheet(
            "color: #b91c1c;" if view.errors else ("color: #92400e;" if view.warnings else "")
        )

    # --- consulta (pruebas y otras ventanas) --------------------------------- #

    def branch_counts(self) -> dict[str, int]:
        """Hallazgos por rama tal como los muestra el árbol."""
        cuenta: dict[str, int] = {}
        for fila in range(self.model.rowCount()):
            nodo = self.model.item(fila, 0)
            rama = str(nodo.data(Qt.ItemDataRole.UserRole))
            cuenta[rama] = sum(nodo.child(g, 0).rowCount() for g in range(nodo.rowCount()))
        return cuenta

    def group_counts(self, branch: str) -> dict[str, int]:
        """Hallazgos por grupo dentro de una rama."""
        for fila in range(self.model.rowCount()):
            nodo = self.model.item(fila, 0)
            if nodo.data(Qt.ItemDataRole.UserRole) == branch:
                return {
                    str(nodo.child(g, 0).data(Qt.ItemDataRole.UserRole)): nodo.child(
                        g, 0
                    ).rowCount()
                    for g in range(nodo.rowCount())
                }
        return {}

    def item_index(self, position: int) -> QModelIndex:
        """Índice del árbol del hallazgo `items[position]` (inválido si no está)."""
        for fila in range(self.model.rowCount()):
            nodo = self.model.item(fila, 0)
            for g in range(nodo.rowCount()):
                grupo = nodo.child(g, 0)
                for h in range(grupo.rowCount()):
                    hoja = grupo.child(h, 0)
                    if hoja.data(ITEM_ROLE) == position:
                        return hoja.index()
        return QModelIndex()

    # --- salto ------------------------------------------------------------------ #

    def _on_double_clicked(self, index: QModelIndex | QPersistentModelIndex) -> None:
        dato = index.sibling(index.row(), 0).data(ITEM_ROLE)
        if isinstance(dato, int) and 0 <= dato < len(self.items):
            self.jump(self.items[dato])

    def jump(self, item: DiagnosisItem) -> None:
        """Salta a la entidad y a la lección del hallazgo y abre la planificación."""
        entidad = entity_of(item)
        if entidad is None and item.lesson is None:
            return
        # Primero se abre la planificación: si aún no existía, así recibe el salto.
        principal = self.window()
        abrir = getattr(principal, "show_window", None)
        if callable(abrir) and principal is not self:
            abrir("planning")
        if entidad is not None:
            self.bridge.select(*entidad)
        if item.lesson is not None:
            self.bridge.select_lesson(item.lesson)


register(
    WindowSpec(
        key="diagnosis",
        title="Diagnóstico",
        title_de="Diagnose",
        tab=RibbonTab.TIMETABLES,
        factory=lambda bridge: DiagnosisPanel(bridge),
        order=3,
        dock="right",
        icon="diagnosis",
        tooltip="Lista de problemas de los datos y del horario, con salto a cada lección.",
        tooltip_de=(
            "Liste der Probleme in den Daten und im Stundenplan, mit Sprung zu jedem Unterricht."
        ),
    )
)
