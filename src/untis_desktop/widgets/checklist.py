"""Lista «Primeros pasos»: el flujo de trabajo de Untis con su estado en vivo.

Cada paso dice qué hay que hacer, si ya está hecho (lo calcula la Fachada a
partir del proyecto abierto) y trae botones que abren la ventana adecuada. El
primer paso pendiente se resalta como «siguiente paso», así quien nunca ha
usado el programa sabe siempre por dónde seguir.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QCoreApplication, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..icons import icon, icon_size
from ..qt_bridge import FacadeBridge
from ..registry import spec
from ..theme import fmt_int


def translate(context: str, text: str) -> str:
    """`QCoreApplication.translate` con un nombre que `pyside6-lupdate` reconoce."""
    return QCoreApplication.translate(context, text)


class StepState(StrEnum):
    """Estado de un paso."""

    DONE = "done"
    PENDING = "pending"
    WARNING = "warning"
    """Hecho, pero con problemas que conviene revisar."""
    OPTIONAL = "optional"
    READY = "ready"
    """Disponible: no hay nada que completar, solo usarlo."""


#: Icono y color de cada estado.
STATE_STYLE: dict[StepState, tuple[str, str, str]] = {
    # estado: (icono, color del texto, fondo de la etiqueta)
    StepState.DONE: ("ok", "#15803d", "#dcfce7"),
    StepState.PENDING: ("steps", "#475569", "#f1f5f9"),
    StepState.WARNING: ("warning", "#b45309", "#fef3c7"),
    StepState.OPTIONAL: ("info", "#1d4ed8", "#dbeafe"),
    StepState.READY: ("activate", "#0f766e", "#ccfbf1"),
}


@dataclass(frozen=True, slots=True)
class StepStatus:
    """Un paso del flujo con su estado calculado."""

    key: str
    number: int
    title: str
    detail: str
    icon: str
    windows: tuple[str, ...]
    """Ventanas que abre el paso; la primera es la principal."""
    state: StepState


def state_label(state: StepState) -> str:
    return {
        StepState.DONE: translate("checklist", "✓ Hecho"),
        StepState.PENDING: translate("checklist", "Pendiente"),
        StepState.WARNING: translate("checklist", "Revisar"),
        StepState.OPTIONAL: translate("checklist", "Opcional"),
        StepState.READY: translate("checklist", "Disponible"),
    }[state]


def compute_steps(bridge: FacadeBridge) -> tuple[StepStatus, ...]:
    """Estado de los ocho pasos a partir del proyecto abierto."""
    t = translate
    titulos = (
        ("grid", t("checklist", "Rejilla de tiempo"), "time_grids", ("time_grids",)),
        (
            "master",
            t("checklist", "Datos maestros"),
            "classes",
            ("classes", "teachers", "rooms", "subjects"),
        ),
        ("lessons", t("checklist", "Lecciones"), "lessons", ("lessons",)),
        ("requests", t("checklist", "Deseos de tiempo (opcional)"), "requests", ("requests",)),
        ("weighting", t("checklist", "Ponderación (opcional)"), "weighting", ("weighting",)),
        ("generate", t("checklist", "Generar el horario"), "optimize", ("optimization",)),
        (
            "review",
            t("checklist", "Revisar y retocar"),
            "evaluation",
            ("evaluation", "diagnosis", "planning"),
        ),
        ("output", t("checklist", "Imprimir y exportar"), "print", ("timetables",)),
    )
    if not bridge.has_session:
        sin = t("checklist", "Crea o abre un colegio para empezar.")
        return tuple(
            StepStatus(k, n, titulo, sin, ic, ventanas, StepState.PENDING)
            for n, (k, titulo, ic, ventanas) in enumerate(titulos, start=1)
        )
    detalles = _details(bridge)
    return tuple(
        StepStatus(k, n, titulo, detalles[k][0], ic, ventanas, detalles[k][1])
        for n, (k, titulo, ic, ventanas) in enumerate(titulos, start=1)
    )


def _details(bridge: FacadeBridge) -> dict[str, tuple[str, StepState]]:
    """`paso -> (detalle, estado)` del proyecto abierto."""
    t = translate
    s = bridge.session
    svc = bridge.service
    p = s.project
    out: dict[str, tuple[str, StepState]] = {}

    # 1. Rejilla: al menos un día y un período lectivo.
    rejillas = svc.grids(s)
    con_horas = [g for g in rejillas if g.days and any(not x.is_break for x in g.periods)]
    if con_horas:
        g = con_horas[0]
        lectivos = [x for x in g.periods if not x.is_break]
        out["grid"] = (
            t("checklist", "{0}: {1} días, {2} períodos de {3} a {4}.").format(
                g.name or g.id, len(g.days), len(lectivos), g.periods[0].start, g.periods[-1].end
            ),
            StepState.DONE,
        )
    else:
        out["grid"] = (
            t("checklist", "Indica los días lectivos y las horas de cada período."),
            StepState.PENDING,
        )

    # 2. Datos maestros: clases, profesores y materias (las aulas son opcionales).
    n_cl, n_pr, n_au, n_ma = len(p.classes), len(p.teachers), len(p.rooms), len(p.subjects)
    resumen = t("checklist", "{0} clases, {1} profesores, {2} aulas, {3} materias.").format(
        n_cl, n_pr, n_au, n_ma
    )
    completo = n_cl > 0 and n_pr > 0 and n_ma > 0
    if not completo:
        resumen += " " + t("checklist", "Hace falta al menos una clase, un profesor y una materia.")
    out["master"] = (resumen, StepState.DONE if completo else StepState.PENDING)

    # 3. Lecciones, y que los datos no tengan errores.
    diagnostico = svc.diagnosis(s)
    errores_datos = sum(
        1 for i in diagnostico.items if i.branch == "datos" and i.severity == "error"
    )
    if not p.lessons:
        out["lessons"] = (
            t("checklist", "Di qué profesor da qué materia a qué clase y cuántas horas."),
            StepState.PENDING,
        )
    else:
        horas = sum(le.periods_per_week for le in p.lessons)
        texto = t("checklist", "{0} lecciones, {1} horas por semana.").format(
            fmt_int(len(p.lessons)), fmt_int(horas)
        )
        if errores_datos:
            texto += " " + t(
                "checklist", "{0} error(es) en los datos: mira el Diagnóstico."
            ).format(errores_datos)
            out["lessons"] = (texto, StepState.WARNING)
        else:
            out["lessons"] = (texto, StepState.DONE)

    # 4-5. Opcionales.
    deseos = len(p.time_requests)
    out["requests"] = (
        t("checklist", "{0} deseos marcados.").format(fmt_int(deseos))
        if deseos
        else t("checklist", "Marca las horas en las que alguien no puede tener clase."),
        StepState.DONE if deseos else StepState.OPTIONAL,
    )
    out["weighting"] = (
        t("checklist", "Decide qué criterios de calidad pesan más al generar."),
        StepState.OPTIONAL,
    )

    # 6. Generar.
    n_hor = len(p.timetables)
    out["generate"] = (
        t("checklist", "{0} horario(s) generado(s).").format(n_hor)
        if n_hor
        else t("checklist", "Abre Optimización y pulsa Iniciar."),
        StepState.DONE if n_hor else StepState.PENDING,
    )

    # 7. Revisar el horario activo.
    ev = svc.evaluation(s)
    if ev is None:
        out["review"] = (
            t("checklist", "Cuando haya un horario, revisa su evaluación y el Diagnóstico."),
            StepState.PENDING,
        )
    elif ev.unplaced_periods == 0 and ev.clashes == 0:
        out["review"] = (
            t("checklist", "Evaluación {0}: todo colocado y sin choques.").format(
                fmt_int(ev.total)
            ),
            StepState.DONE,
        )
    else:
        out["review"] = (
            t("checklist", "Evaluación {0}: {1} período(s) sin colocar, {2} choque(s).").format(
                fmt_int(ev.total), ev.unplaced_periods, ev.clashes
            ),
            StepState.WARNING,
        )

    # 8. Salida.
    out["output"] = (
        t("checklist", "Imprime o exporta a PDF / HTML los horarios de clases y profesores.")
        if n_hor
        else t("checklist", "Disponible cuando haya un horario generado."),
        StepState.READY if n_hor else StepState.PENDING,
    )
    return out


def _window_label(key: str, language: str) -> str:
    try:
        return spec(key).label(language)
    except KeyError:
        return key


def _window_icon(key: str) -> str:
    from ..icons import ICONS

    try:
        nombre = spec(key).icon
    except KeyError:
        nombre = ""
    if nombre in ICONS:
        return nombre
    return {"optimization": "optimize", "settings": "school", "start": "launch"}.get(
        key, key if key in ICONS else "info"
    )


class ChecklistWidget(QWidget):
    """Los pasos del flujo, con estado y botones para abrir cada ventana."""

    open_requested = Signal(str)
    """Clave de la ventana que el usuario quiere abrir."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.setObjectName("checklist")
        self.steps: tuple[StepStatus, ...] = ()
        self.buttons: dict[str, list[QPushButton]] = {}
        self.chips: dict[str, QLabel] = {}
        self.rows: dict[str, QFrame] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.refresh()

    # --- datos ------------------------------------------------------------ #

    def statuses(self) -> dict[str, StepState]:
        """Estado de cada paso (para pruebas y para el resumen de la página)."""
        return {p.key: p.state for p in self.steps}

    def next_step(self) -> StepStatus | None:
        """Primer paso obligatorio sin terminar."""
        for paso in self.steps:
            if paso.state in (StepState.PENDING, StepState.WARNING):
                return paso
        return None

    def refresh(self) -> None:
        self.steps = compute_steps(self.bridge)
        self._rebuild()

    # --- vista ------------------------------------------------------------- #

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                # Se oculta ya: `deleteLater` tarda un ciclo y se vería solapada.
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.buttons.clear()
        self.chips.clear()
        self.rows.clear()
        siguiente = self.next_step() if self.bridge.has_session else None
        for paso in self.steps:
            fila = self._row(paso, siguiente is not None and paso.key == siguiente.key)
            self._layout.addWidget(fila)
            self.rows[paso.key] = fila

    def _button(self, key: str, primary: bool, highlighted: bool) -> QPushButton:
        nombre = _window_label(key, self.bridge.language)
        imagen = (
            icon(_window_icon(key), "#ffffff")
            if primary and highlighted
            else icon(_window_icon(key))
        )
        boton = QPushButton(imagen, nombre)
        boton.setIconSize(icon_size("button") if primary else icon_size("small"))
        if primary:
            boton.setObjectName("primary" if highlighted else "step_button")
        else:
            boton.setObjectName("step_link")
            boton.setFlat(True)
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        boton.setToolTip(translate("checklist", "Abrir {0}").format(nombre))
        boton.setEnabled(self.bridge.has_session)
        boton.clicked.connect(lambda _c=False, k=key: self.open_requested.emit(k))
        return boton

    def _row(self, paso: StepStatus, is_next: bool) -> QFrame:
        fila = QFrame()
        fila.setObjectName("step_next" if is_next else "step")
        h = QHBoxLayout(fila)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(10)

        nombre_icono, color, fondo = STATE_STYLE[paso.state]
        numero = QLabel(str(paso.number))
        numero.setObjectName("step_number")
        if paso.state is StepState.DONE:
            numero.setPixmap(icon(nombre_icono).pixmap(24, 24))
            numero.setObjectName("step_number_done")
        numero.setFixedSize(26, 26)
        numero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(numero, 0, Qt.AlignmentFlag.AlignVCenter)

        imagen = QLabel()
        imagen.setPixmap(icon(paso.icon).pixmap(24, 24))
        imagen.setFixedSize(26, 26)
        h.addWidget(imagen, 0, Qt.AlignmentFlag.AlignVCenter)

        textos = QVBoxLayout()
        textos.setSpacing(1)
        titulo = QLabel(paso.title)
        titulo.setObjectName("step_title")
        if is_next:
            titulo.setText(paso.title + "   " + translate("checklist", "<- siguiente paso"))
        detalle = QLabel(paso.detail)
        detalle.setObjectName("step_detail")
        detalle.setWordWrap(True)
        detalle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        textos.addWidget(titulo)
        textos.addWidget(detalle)

        lista = [self._button(paso.windows[0], True, is_next)]
        if len(paso.windows) > 1:
            enlaces = QHBoxLayout()
            enlaces.setSpacing(2)
            tambien = QLabel(translate("checklist", "También:"))
            tambien.setObjectName("step_detail")
            enlaces.addWidget(tambien)
            for clave in paso.windows[1:]:
                boton = self._button(clave, False, False)
                enlaces.addWidget(boton)
                lista.append(boton)
            enlaces.addStretch(1)
            textos.addLayout(enlaces)
        h.addLayout(textos, 1)

        chip = QLabel(state_label(paso.state))
        chip.setObjectName("chip")
        chip.setStyleSheet(
            f"QLabel#chip {{ color: {color}; background: {fondo}; border-radius: 9px;"
            " padding: 2px 8px; font-weight: 600; }"
        )
        chip.setToolTip(state_label(paso.state))
        chip.setProperty("state", paso.state.value)
        self.chips[paso.key] = chip
        h.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)

        lista[0].setFixedWidth(190)
        h.addWidget(lista[0], 0, Qt.AlignmentFlag.AlignVCenter)
        self.buttons[paso.key] = lista
        return fila
