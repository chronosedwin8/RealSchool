"""Asistente «Crear un colegio nuevo».

Cinco páginas: colegio y curso, días de la semana, estructura de la jornada
(con vista previa de las horas), alta rápida de clases, profesores y materias,
y un resumen. Al terminar se construye la sesión con la Fachada y se adjunta al
puente de una sola vez: si algo falla a medias, el proyecto abierto no cambia.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from scheduling_platform.application import DEFAULT_GRID_ID, EditResult, MasterKind, UntisSession

from ..icons import icon, icon_size
from ..qt_bridge import FacadeBridge
from ..theme import BREAK_COLOR, day_name

#: Días que ofrece el asistente (1 = lunes ... 6 = sábado).
WEEK_DAYS = (1, 2, 3, 4, 5, 6)
MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True, slots=True)
class PreviewRow:
    """Un período de la vista previa (minutos desde medianoche)."""

    label: str
    start: int
    end: int
    is_break: bool


def clock(minutes: int) -> str:
    """Minutos desde medianoche -> `HH:MM` (admite pasar de las 24 h)."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def split_names(text: str) -> list[str]:
    """Nombres separados por comas, puntos y coma o saltos de línea, sin repetir."""
    vistos: list[str] = []
    for trozo in re.split(r"[,;\n\t]+", text):
        nombre = trozo.strip()
        if nombre and nombre not in vistos:
            vistos.append(nombre)
    return vistos


def preview_rows(
    start: int, periods: int, duration: int, gap: int, breaks: dict[int, int]
) -> tuple[PreviewRow, ...]:
    """Las mismas horas que generará la Fachada (`build_grid`)."""
    filas: list[PreviewRow] = []
    reloj = start
    for lectivo in range(1, periods + 1):
        filas.append(PreviewRow(str(lectivo), reloj, reloj + duration, False))
        reloj += duration + gap
        if lectivo in breaks and lectivo < periods:
            filas.append(PreviewRow("", reloj, reloj + breaks[lectivo], True))
            reloj += breaks[lectivo] + gap
    return tuple(filas)


# --------------------------------------------------------------------------- #
# Páginas
# --------------------------------------------------------------------------- #


def _message_label() -> QLabel:
    """Etiqueta de error en línea (oculta mientras no hay problema)."""
    etiqueta = QLabel()
    etiqueta.setObjectName("wizard_error")
    etiqueta.setWordWrap(True)
    etiqueta.setStyleSheet(
        "QLabel#wizard_error { color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca;"
        " border-radius: 6px; padding: 6px 8px; }"
    )
    etiqueta.hide()
    return etiqueta


def _hint(text: str) -> QLabel:
    etiqueta = QLabel(text)
    etiqueta.setWordWrap(True)
    etiqueta.setStyleSheet("color: #475569;")
    return etiqueta


class _Page(QWizardPage):
    """Página con mensaje de error en línea y validación propia."""

    def __init__(self) -> None:
        super().__init__()
        self.message = _message_label()

    def problem(self) -> str:
        """Motivo por el que la página no es válida (`""` si lo es)."""
        return ""

    def show_problem(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def validatePage(self) -> bool:
        motivo = self.problem()
        self.show_problem(motivo)
        return not motivo


class SchoolPage(_Page):
    """Nombre del colegio y fechas del curso."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle(self.tr("Tu colegio"))
        self.setSubTitle(self.tr("¿Cómo se llama el colegio y cuándo empieza y termina el curso?"))
        # El próximo curso empieza en septiembre de este año.
        anio = QDate.currentDate().year()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(self.tr("Por ejemplo: Colegio San José"))
        self.begin_edit = QDateEdit(QDate(anio, 9, 1))
        self.end_edit = QDateEdit(QDate(anio + 1, 6, 30))
        for fecha in (self.begin_edit, self.end_edit):
            fecha.setCalendarPopup(True)
            fecha.setDisplayFormat("dd/MM/yyyy")
        form = QFormLayout()
        form.addRow(self.tr("Nombre del colegio:"), self.name_edit)
        form.addRow(self.tr("Inicio del curso:"), self.begin_edit)
        form.addRow(self.tr("Fin del curso:"), self.end_edit)
        caja = QVBoxLayout(self)
        caja.addLayout(form)
        caja.addWidget(
            _hint(
                self.tr(
                    "Todo lo que indiques aquí se puede cambiar después en Inicio -> "
                    "Datos del colegio."
                )
            )
        )
        caja.addStretch(1)
        caja.addWidget(self.message)
        self.name_edit.textChanged.connect(lambda _t: self.show_problem(""))

    def problem(self) -> str:
        if not self.name_edit.text().strip():
            return self.tr("Escribe el nombre del colegio.")
        if self.end_edit.date() <= self.begin_edit.date():
            return self.tr("El fin del curso debe ser posterior a su inicio.")
        return ""


class WeekPage(_Page):
    """Días lectivos de la semana."""

    def __init__(self, language: str) -> None:
        super().__init__()
        self.setTitle(self.tr("La semana"))
        self.setSubTitle(self.tr("¿Qué días de la semana hay clase?"))
        self.day_checks: dict[int, QCheckBox] = {}
        rejilla = QGridLayout()
        for indice, dia in enumerate(WEEK_DAYS):
            casilla = QCheckBox(day_name(dia, language))
            casilla.setChecked(dia <= 5)
            casilla.toggled.connect(lambda _c: self.show_problem(""))
            self.day_checks[dia] = casilla
            rejilla.addWidget(casilla, indice // 3, indice % 3)
        caja = QVBoxLayout(self)
        caja.addLayout(rejilla)
        caja.addWidget(
            _hint(self.tr("Lo normal es de lunes a viernes. Marca el sábado si hay clase."))
        )
        caja.addStretch(1)
        caja.addWidget(self.message)

    def days(self) -> tuple[int, ...]:
        return tuple(d for d, c in self.day_checks.items() if c.isChecked())

    def problem(self) -> str:
        return "" if self.days() else self.tr("Marca al menos un día de clase.")


class _BreakRow(QWidget):
    """Una fila «recreo después del período N, de M minutos»."""

    def __init__(self, after: int, minutes: int) -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.after = QSpinBox()
        self.after.setRange(1, 15)
        self.after.setValue(after)
        self.minutes = QSpinBox()
        self.minutes.setRange(5, 120)
        self.minutes.setSingleStep(5)
        self.minutes.setValue(minutes)
        self.minutes.setSuffix(" min")
        self.remove = QToolButton()
        self.remove.setIcon(icon("delete"))
        self.remove.setIconSize(icon_size("small"))
        self.remove.setToolTip(self.tr("Quitar este recreo"))
        h.addWidget(QLabel(self.tr("Recreo después del período")))
        h.addWidget(self.after)
        h.addWidget(QLabel(self.tr("de")))
        h.addWidget(self.minutes)
        h.addWidget(self.remove)
        h.addStretch(1)


class DayPage(_Page):
    """Estructura de la jornada con vista previa de las horas."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle(self.tr("La jornada"))
        self.setSubTitle(
            self.tr(
                "¿A qué hora empieza la primera clase, cuánto dura cada una y cuándo hay "
                "recreo? A la derecha ves las horas que saldrán."
            )
        )
        self.start_edit = QTimeEdit(QTime(8, 0))
        self.start_edit.setDisplayFormat("HH:mm")
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(5, 240)
        self.duration_spin.setValue(45)
        self.duration_spin.setSuffix(" min")
        self.gap_spin = QSpinBox()
        self.gap_spin.setRange(0, 60)
        self.gap_spin.setValue(5)
        self.gap_spin.setSuffix(" min")
        self.periods_spin = QSpinBox()
        self.periods_spin.setRange(1, 15)
        self.periods_spin.setValue(7)
        form = QFormLayout()
        form.addRow(self.tr("Primera clase a las:"), self.start_edit)
        form.addRow(self.tr("Duración de cada período:"), self.duration_spin)
        form.addRow(self.tr("Cambio de clase:"), self.gap_spin)
        form.addRow(self.tr("Períodos de clase al día:"), self.periods_spin)

        self._break_rows: list[_BreakRow] = []
        self.breaks_box = QVBoxLayout()
        self.breaks_box.setSpacing(4)
        self.add_break_button = QPushButton(icon("break"), self.tr("Añadir recreo"))
        self.add_break_button.setIconSize(icon_size("button"))
        self.add_break_button.clicked.connect(lambda: self.add_break(self._next_break(), 20))

        izquierda = QVBoxLayout()
        izquierda.addLayout(form)
        titulo = QLabel(self.tr("Recreos"))
        titulo.setStyleSheet("font-weight: 600; margin-top: 8px;")
        izquierda.addWidget(titulo)
        izquierda.addLayout(self.breaks_box)
        izquierda.addWidget(self.add_break_button, 0, Qt.AlignmentFlag.AlignLeft)
        izquierda.addStretch(1)

        self.preview = QTableWidget(0, 3)
        self.preview.setHorizontalHeaderLabels(
            [self.tr("Período"), self.tr("Empieza"), self.tr("Termina")]
        )
        self.preview.verticalHeader().setVisible(False)
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.preview.setMinimumWidth(260)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: #334155;")
        derecha = QVBoxLayout()
        derecha.addWidget(self.preview, 1)
        derecha.addWidget(self.summary)

        columnas = QHBoxLayout()
        columnas.addLayout(izquierda, 1)
        columnas.addLayout(derecha, 1)
        caja = QVBoxLayout(self)
        caja.addLayout(columnas, 1)
        caja.addWidget(self.message)

        for spin in (self.duration_spin, self.gap_spin, self.periods_spin):
            spin.valueChanged.connect(lambda _v: self.update_preview())
        self.start_edit.timeChanged.connect(lambda _t: self.update_preview())
        self.add_break(3, 20)

    # --- recreos ----------------------------------------------------------- #

    def _next_break(self) -> int:
        usados = set(self.breaks())
        for candidato in range(3, 15):
            if candidato not in usados:
                return candidato
        return 1

    def add_break(self, after: int, minutes: int) -> None:
        fila = _BreakRow(after, minutes)
        fila.after.valueChanged.connect(lambda _v: self.update_preview())
        fila.minutes.valueChanged.connect(lambda _v: self.update_preview())
        fila.remove.clicked.connect(lambda: self._remove_break(fila))
        self._break_rows.append(fila)
        self.breaks_box.addWidget(fila)
        self.update_preview()

    def _remove_break(self, fila: _BreakRow) -> None:
        self._break_rows.remove(fila)
        fila.setParent(None)
        fila.deleteLater()
        self.update_preview()

    def clear_breaks(self) -> None:
        for fila in list(self._break_rows):
            self._remove_break(fila)

    def breaks(self) -> dict[int, int]:
        return {f.after.value(): f.minutes.value() for f in self._break_rows}

    # --- valores ----------------------------------------------------------- #

    def start_minutes(self) -> int:
        t = self.start_edit.time()
        return t.hour() * 60 + t.minute()

    def start_text(self) -> str:
        return clock(self.start_minutes())

    def rows(self) -> tuple[PreviewRow, ...]:
        return preview_rows(
            self.start_minutes(),
            self.periods_spin.value(),
            self.duration_spin.value(),
            self.gap_spin.value(),
            self.breaks(),
        )

    def problem(self) -> str:
        periodos = self.periods_spin.value()
        despues = [f.after.value() for f in self._break_rows]
        if len(despues) != len(set(despues)):
            return self.tr("Hay dos recreos después del mismo período: quita uno.")
        for n in despues:
            if n >= periodos:
                return self.tr(
                    "El recreo después del período {0} no cabe: la jornada tiene {1} "
                    "períodos y un recreo tiene que ir entre dos clases."
                ).format(n, periodos)
        filas = self.rows()
        if filas and filas[-1].end > MINUTES_PER_DAY:
            return self.tr(
                "La jornada terminaría después de medianoche ({0}). Empieza antes, acorta "
                "los períodos o reduce su número."
            ).format(clock(filas[-1].end))
        return ""

    def update_preview(self) -> None:
        filas = self.rows()
        self.preview.setRowCount(len(filas))
        gris = QColor(BREAK_COLOR)
        for i, fila in enumerate(filas):
            nombre = self.tr("Recreo") if fila.is_break else fila.label
            celdas = (nombre, clock(fila.start), clock(fila.end))
            for j, texto in enumerate(celdas):
                item = QTableWidgetItem(texto)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if fila.is_break:
                    item.setBackground(gris)
                self.preview.setItem(i, j, item)
        motivo = self.problem()
        self.show_problem(motivo)
        if filas and not motivo:
            self.summary.setText(
                self.tr("Jornada de {0} a {1}: {2} períodos de clase y {3} recreo(s).").format(
                    clock(filas[0].start),
                    clock(filas[-1].end),
                    self.periods_spin.value(),
                    sum(1 for f in filas if f.is_break),
                )
            )
        else:
            self.summary.setText("")


class PeoplePage(_Page):
    """Alta rápida de clases, profesores y materias (opcional)."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle(self.tr("Clases, profesores y materias"))
        self.setSubTitle(
            self.tr(
                "Opcional: escribe los nombres cortos separados por comas o uno por línea. "
                "Puedes dejarlo en blanco y añadirlos después."
            )
        )
        self.classes_edit = QPlainTextEdit()
        self.classes_edit.setPlaceholderText("1A, 1B, 2A, 2B")
        self.teachers_edit = QPlainTextEdit()
        self.teachers_edit.setPlaceholderText("ANA, LUIS, MARTA")
        self.subjects_edit = QPlainTextEdit()
        self.subjects_edit.setPlaceholderText("MAT, LEN, ING, EF")
        rejilla = QGridLayout()
        self.counts: dict[str, QLabel] = {}
        columnas = (
            ("classes", "classes", self.tr("Clases"), self.classes_edit),
            ("teachers", "teachers", self.tr("Profesores"), self.teachers_edit),
            ("subjects", "subjects", self.tr("Materias"), self.subjects_edit),
        )
        for col, (clave, nombre_icono, titulo, editor) in enumerate(columnas):
            cabecera = QLabel(f"<b>{titulo}</b>")
            imagen = QLabel()
            imagen.setPixmap(icon(nombre_icono).pixmap(20, 20))
            fila = QHBoxLayout()
            fila.addWidget(imagen)
            fila.addWidget(cabecera)
            fila.addStretch(1)
            rejilla.addLayout(fila, 0, col)
            editor.setTabChangesFocus(True)
            rejilla.addWidget(editor, 1, col)
            cuenta = QLabel()
            cuenta.setStyleSheet("color: #475569;")
            rejilla.addWidget(cuenta, 2, col)
            self.counts[clave] = cuenta
            editor.textChanged.connect(self._update_counts)
        caja = QVBoxLayout(self)
        caja.addLayout(rejilla, 1)
        caja.addWidget(
            _hint(
                self.tr(
                    "Los nombres cortos son los que salen en los horarios: usa pocas "
                    "letras (6A, ANA, MAT). Los nombres largos se completan luego en "
                    "Datos maestros."
                )
            )
        )
        caja.addWidget(self.message)
        self._update_counts()

    def classes(self) -> list[str]:
        return split_names(self.classes_edit.toPlainText())

    def teachers(self) -> list[str]:
        return split_names(self.teachers_edit.toPlainText())

    def subjects(self) -> list[str]:
        return split_names(self.subjects_edit.toPlainText())

    def _update_counts(self) -> None:
        self.counts["classes"].setText(self.tr("{0} clase(s)").format(len(self.classes())))
        self.counts["teachers"].setText(self.tr("{0} profesor(es)").format(len(self.teachers())))
        self.counts["subjects"].setText(self.tr("{0} materia(s)").format(len(self.subjects())))


class SummaryPage(_Page):
    """Resumen de lo que se va a crear y qué viene después."""

    def __init__(self, wizard: NewSchoolWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle(self.tr("Todo listo"))
        self.setSubTitle(self.tr("Revisa el resumen y pulsa Finalizar para crear el colegio."))
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        caja = QVBoxLayout(self)
        caja.addWidget(self.text)
        caja.addStretch(1)
        caja.addWidget(self.message)

    def initializePage(self) -> None:
        self.text.setText(self._wizard.summary_html())


# --------------------------------------------------------------------------- #
# Asistente
# --------------------------------------------------------------------------- #


class NewSchoolWizard(QWizard):
    """Crea un proyecto nuevo con la rejilla y los datos básicos ya puestos."""

    def __init__(self, bridge: FacadeBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self.problems: list[str] = []
        """Avisos no bloqueantes al crear (p. ej. un nombre de clase repetido)."""
        self.setWindowTitle(self.tr("Crear un colegio nuevo"))
        self.setWindowIcon(icon("wizard"))
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.HaveFinishButtonOnEarlyPages, True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setPixmap(QWizard.WizardPixmap.LogoPixmap, icon("school").pixmap(48, 48))
        self.setButtonText(QWizard.WizardButton.NextButton, self.tr("Siguiente >"))
        self.setButtonText(QWizard.WizardButton.BackButton, self.tr("< Atrás"))
        self.setButtonText(QWizard.WizardButton.FinishButton, self.tr("Finalizar"))
        self.setButtonText(QWizard.WizardButton.CancelButton, self.tr("Cancelar"))
        self.setMinimumSize(760, 560)

        self.school = SchoolPage()
        self.week = WeekPage(bridge.language)
        self.day = DayPage()
        self.people = PeoplePage()
        self.summary = SummaryPage(self)
        self.pages: tuple[_Page, ...] = (
            self.school,
            self.week,
            self.day,
            self.people,
            self.summary,
        )
        for pagina in self.pages:
            # Con los valores por defecto se puede terminar desde cualquier página.
            pagina.setFinalPage(True)
            self.addPage(pagina)

    # --- resumen ------------------------------------------------------------ #

    def summary_html(self) -> str:
        dias = self.week.days()
        filas = self.day.rows()
        nombres_dias = ", ".join(day_name(d, self.bridge.language) for d in dias)
        partes = [
            self.tr("<p>Se creará <b>{0}</b> con:</p>").format(
                self.school.name_edit.text().strip() or "-"
            ),
            "<ul>",
            self.tr("<li>Días de clase: {0}.</li>").format(nombres_dias or "-"),
        ]
        if filas:
            partes.append(
                self.tr(
                    "<li>{0} períodos de {1} min, de {2} a {3}, con {4} recreo(s).</li>"
                ).format(
                    self.day.periods_spin.value(),
                    self.day.duration_spin.value(),
                    clock(filas[0].start),
                    clock(filas[-1].end),
                    sum(1 for f in filas if f.is_break),
                )
            )
        partes.append(
            self.tr("<li>{0} clase(s), {1} profesor(es) y {2} materia(s).</li>").format(
                len(self.people.classes()),
                len(self.people.teachers()),
                len(self.people.subjects()),
            )
        )
        partes += [
            "</ul>",
            self.tr(
                "<p>Después verás la lista <b>Primeros pasos</b>, que te guía hasta el "
                "horario terminado.</p>"
            ),
        ]
        return "".join(partes)

    # --- creación ----------------------------------------------------------- #

    def first_problem(self) -> tuple[_Page, str] | None:
        """Primera página con un dato no válido."""
        for pagina in self.pages:
            motivo = pagina.problem()
            if motivo:
                return pagina, motivo
        return None

    def accept(self) -> None:
        """Finalizar: valida todas las páginas, crea el colegio y cierra."""
        fallo = self.first_problem()
        if fallo is not None:
            pagina, motivo = fallo
            self._go_to(pagina)
            pagina.show_problem(motivo)
            return
        motivo = self.create_project()
        if motivo:
            actual = self.currentPage()
            if isinstance(actual, _Page):
                actual.show_problem(motivo)
            return
        super().accept()

    def _go_to(self, pagina: _Page) -> None:
        """Lleva el asistente a `pagina` (hacia atrás o hacia delante)."""
        objetivo = self.pages.index(pagina)
        while True:
            actual = self.currentPage()
            if actual not in self.pages:
                return
            indice = self.pages.index(actual)
            if indice == objetivo:
                return
            antes = self.currentId()
            if indice > objetivo:
                self.back()
            else:
                self.next()
            if self.currentId() == antes:
                return

    def build_session(self) -> tuple[UntisSession | None, str]:
        """Sesión nueva con todos los datos del asistente (`None` + motivo si falla)."""
        svc = self.bridge.service
        sesion = svc.new(self.school.name_edit.text().strip())
        d = self.day
        pasos: tuple[Callable[[], EditResult], ...] = (
            lambda: svc.regenerate_grid(
                sesion,
                DEFAULT_GRID_ID,
                periods=d.periods_spin.value(),
                start=d.start_text(),
                duration=d.duration_spin.value(),
                gap=d.gap_spin.value(),
                breaks=d.breaks(),
            ),
            lambda: svc.set_grid_days(sesion, DEFAULT_GRID_ID, self.week.days()),
            lambda: svc.set_school_field(
                sesion, "school_year_begin", self.school.begin_edit.date().toString("yyyyMMdd")
            ),
            lambda: svc.set_school_field(
                sesion, "school_year_end", self.school.end_edit.date().toString("yyyyMMdd")
            ),
        )
        for paso in pasos:
            resultado = paso()
            if not resultado.ok:
                return None, resultado.message
        self.problems = []
        altas = (
            (MasterKind.CLASSES, self.people.classes()),
            (MasterKind.TEACHERS, self.people.teachers()),
            (MasterKind.SUBJECTS, self.people.subjects()),
        )
        for tipo, nombres in altas:
            for nombre in nombres:
                resultado = svc.add_master(sesion, tipo, nombre)
                if not resultado.ok:
                    self.problems.append(f"{nombre}: {resultado.message}")
        return sesion, ""

    def create_project(self) -> str:
        """Crea el colegio y lo abre. Devuelve el motivo del fallo (`""` si fue bien)."""
        if self.bridge.busy:
            return self.tr("Espera a que termine la optimización.")
        sesion, motivo = self.build_session()
        if sesion is None:
            return motivo
        self.bridge.attach(sesion)
        self.bridge.status.emit(self.tr("Colegio creado: {0}").format(sesion.project.school.name))
        for aviso in self.problems:
            self.bridge.status.emit(aviso)
        return ""
