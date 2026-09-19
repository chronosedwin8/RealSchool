"""Ayuda contextual (F1) y guía rápida del flujo de trabajo.

Cada ventana registrada tiene aquí una ficha breve: para qué sirve, los pasos
para usarla y algunos consejos. Los textos son propios (no se copia la ayuda de
Untis) y pasan por `translate("help", ...)` para que `pyside6-lupdate` los
extraiga al `.ts` del alemán.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from PySide6.QtCore import QCoreApplication, QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .icons import icon

#: Clave de la ficha con el flujo completo (Ayuda -> Guía rápida).
GUIDE_KEY = "guide"


def translate(context: str, text: str) -> str:
    """`QCoreApplication.translate` con un nombre que `pyside6-lupdate` reconoce."""
    return QCoreApplication.translate(context, text)


@dataclass(frozen=True, slots=True)
class HelpEntry:
    """Ficha de ayuda de una ventana."""

    title: str
    summary: str
    """Para qué sirve, en una o dos frases (también es la descripción de la cinta)."""
    steps: tuple[str, ...]
    tips: tuple[str, ...] = ()


def help_entries() -> dict[str, HelpEntry]:
    """Todas las fichas, traducidas al idioma activo."""
    return {
        GUIDE_KEY: HelpEntry(
            translate("help", "Guía rápida"),
            translate(
                "help",
                "Un horario se construye siempre en el mismo orden: primero el tiempo "
                "disponible, después quién enseña qué a quién, y por último se genera y "
                "se revisa. La página de Inicio marca cada paso en verde cuando está hecho.",
            ),
            (
                translate(
                    "help",
                    "Rejilla de tiempo: indica los días lectivos, las horas de cada "
                    "período y los recreos.",
                ),
                translate(
                    "help",
                    "Datos maestros: da de alta las clases, los profesores, las aulas y "
                    "las materias con un nombre corto.",
                ),
                translate(
                    "help",
                    "Lecciones: di qué profesor da qué materia a qué clase y cuántas "
                    "horas por semana.",
                ),
                translate(
                    "help",
                    "Deseos (opcional): marca las horas en las que alguien no puede o "
                    "prefiere no tener clase.",
                ),
                translate(
                    "help",
                    "Ponderación (opcional): decide qué criterios de calidad pesan más.",
                ),
                translate(
                    "help",
                    "Generar: abre Optimización y pulsa Iniciar. Puedes seguir el "
                    "progreso y detenerlo cuando quieras.",
                ),
                translate(
                    "help",
                    "Revisar: mira el número de evaluación y el Diagnóstico, y retoca a "
                    "mano en el Diálogo de planificación.",
                ),
                translate(
                    "help",
                    "Imprimir y exportar: en Horarios, elige clase, profesor o aula y "
                    "sácalo a PDF, HTML o impresora.",
                ),
            ),
            (
                translate(
                    "help",
                    "Guarda a menudo (Ctrl+S): el proyecto se guarda en un único archivo .rsp.",
                ),
                translate(
                    "help",
                    "Todo se puede deshacer con Ctrl+Z; la cinta dice qué se va a deshacer.",
                ),
                translate("help", "Pulsa F1 en cualquier ventana para ver su ayuda."),
            ),
        ),
        "start": HelpEntry(
            translate("help", "Inicio y primeros pasos"),
            translate(
                "help",
                "Punto de partida: crear, abrir o importar un colegio y seguir la lista "
                "de pasos hasta tener el horario.",
            ),
            (
                translate(
                    "help",
                    "Si empiezas de cero, pulsa «Crear un colegio nuevo»: un asistente te "
                    "pide el nombre, los días y el horario de la jornada.",
                ),
                translate(
                    "help",
                    "Si ya trabajas con Untis, usa «Importar de Untis» con el archivo XML "
                    "o la carpeta de archivos GPU.",
                ),
                translate(
                    "help",
                    "Sigue la lista «Primeros pasos»: cada paso tiene un botón que abre "
                    "la ventana adecuada.",
                ),
                translate("help", "Los pasos se marcan solos cuando los datos están completos."),
            ),
            (
                translate(
                    "help",
                    "Los últimos proyectos abiertos aparecen abajo para volver a ellos "
                    "con un clic.",
                ),
                translate("help", "Vuelve aquí en cualquier momento con Ctrl+0."),
            ),
        ),
        "settings": HelpEntry(
            translate("help", "Datos del colegio"),
            translate(
                "help",
                "Nombre del colegio, fechas del curso y textos que salen en los horarios "
                "impresos; también el idioma de la interfaz.",
            ),
            (
                translate("help", "Escribe el nombre del colegio tal como quieres verlo impreso."),
                translate(
                    "help",
                    "Indica el inicio y el fin del curso con el formato AAAAMMDD "
                    "(por ejemplo 20260901).",
                ),
                translate(
                    "help",
                    "Rellena los encabezados y el pie si quieres que aparezcan en las impresiones.",
                ),
            ),
            (
                translate(
                    "help",
                    "Un campo en rojo tiene un valor no válido: el mensaje de abajo "
                    "explica por qué.",
                ),
            ),
        ),
        "classes": _master(
            translate("help", "Clases"),
            translate(
                "help",
                "Los grupos de alumnos que reciben clase juntos (por ejemplo 6A o 1ºBach).",
            ),
            translate(
                "help",
                "Asigna a cada clase su rejilla de tiempo si el colegio tiene horarios "
                "distintos por etapa.",
            ),
        ),
        "teachers": _master(
            translate("help", "Profesores"),
            translate(
                "help",
                "El profesorado: nombre corto, nombre completo y datos para el cálculo "
                "de huecos y cargas.",
            ),
            translate(
                "help",
                "Usa nombres cortos fáciles de reconocer (tres o cuatro letras): son "
                "los que salen en los horarios.",
            ),
        ),
        "rooms": _master(
            translate("help", "Aulas"),
            translate(
                "help",
                "Las aulas y espacios: aulas de grupo, laboratorios, gimnasio, aulas de "
                "informática...",
            ),
            translate(
                "help",
                "Las aulas son opcionales: si una lección no pide aula, se coloca sin "
                "tenerla en cuenta.",
            ),
        ),
        "subjects": _master(
            translate("help", "Materias"),
            translate("help", "Las asignaturas que se imparten; cada una puede tener su color."),
            translate(
                "help",
                "El color de la materia es el que se usa en los horarios y en el "
                "Diálogo de planificación.",
            ),
        ),
        "departments": _master(
            translate("help", "Departamentos"),
            translate(
                "help",
                "Agrupan profesores y clases (por ejemplo por etapa o por edificio) para "
                "filtrar y ordenar.",
            ),
            translate("help", "Son opcionales: un colegio pequeño puede no usarlos."),
        ),
        "student_groups": _master(
            translate("help", "Grupos de alumnos"),
            translate(
                "help",
                "Subgrupos de una clase que se separan en algunas materias (desdobles, "
                "optativas, religión o valores...).",
            ),
            translate(
                "help",
                "Un grupo de alumnos se usa en la línea de una lección para indicar que "
                "solo asiste una parte de la clase.",
            ),
        ),
        "time_grids": HelpEntry(
            translate("help", "Rejillas de tiempo"),
            translate(
                "help",
                "Cuándo hay clase: días de la semana, hora de cada período y recreos. "
                "Todo el horario se coloca sobre esta rejilla.",
            ),
            (
                translate(
                    "help",
                    "Un proyecto nuevo ya trae la rejilla «Estándar»: comprueba que los "
                    "días y las horas son los de tu colegio.",
                ),
                translate(
                    "help",
                    "Para generar todas las horas de golpe indica la hora de inicio, la "
                    "duración, el cambio de clase y los recreos.",
                ),
                translate(
                    "help",
                    "Si una etapa tiene otro horario (por ejemplo Primaria), crea otra "
                    "rejilla y asígnala a sus clases.",
                ),
                translate(
                    "help",
                    "Para retocar un período concreto, edita su hora de inicio o de fin "
                    "en la tabla.",
                ),
            ),
            (
                translate(
                    "help",
                    "Un recreo es un período más marcado como recreo: en él no se coloca "
                    "ninguna clase.",
                ),
                translate(
                    "help",
                    "Cuando ya hay clases colocadas, las horas solo se pueden cambiar "
                    "período a período.",
                ),
            ),
        ),
        "requests": HelpEntry(
            translate("help", "Deseos de tiempo"),
            translate(
                "help",
                "Horas en las que un profesor, una clase, un aula o una materia no puede "
                "o prefiere no tener clase (o al revés).",
            ),
            (
                translate(
                    "help", "Elige a quién afecta el deseo: profesor, clase, aula o materia."
                ),
                translate(
                    "help",
                    "Pinta las celdas: -3 es imposible, 0 indiferente y +3 muy deseable.",
                ),
                translate(
                    "help",
                    "Usa los valores negativos suaves (-1, -2) cuando algo molesta pero "
                    "se puede aceptar.",
                ),
                translate(
                    "help",
                    "Marco horario: di de qué hora a qué hora hay clase y pulsa Aplicar. "
                    "Cierra sola las horas de fuera en todos los días.",
                ),
                translate(
                    "help",
                    "Con Aplicar a: todos los de su rejilla lo haces de una vez para "
                    "todos los cursos que comparten horario.",
                ),
                translate(
                    "help",
                    "Clic en el número de la hora: esa hora queda igual toda la semana. "
                    "Clic en el nombre del día: el día entero.",
                ),
            ),
            (
                translate(
                    "help",
                    "Demasiados -3 pueden hacer imposible colocar todas las clases: "
                    "resérvalos para lo que de verdad no se puede.",
                ),
            ),
        ),
        "lessons": HelpEntry(
            translate("help", "Lecciones"),
            translate(
                "help",
                "Qué se enseña: cada lección une materia, profesor y clase(s) con un "
                "número de horas por semana.",
            ),
            (
                translate("help", "Elige una clase o un profesor para ver solo sus lecciones."),
                translate(
                    "help",
                    "Añade una lección con la materia, el profesor, la clase y las horas "
                    "semanales.",
                ),
                translate(
                    "help",
                    "Para clases que se dan a la vez (desdobles, optativas), añade más "
                    "líneas a la misma lección: es un acople.",
                ),
                translate(
                    "help",
                    "Indica horas dobles o «no el mismo día» cuando haga falta.",
                ),
            ),
            (
                translate(
                    "help",
                    "El resumen de carga avisa si una clase o un profesor tiene más horas "
                    "que huecos en su rejilla.",
                ),
            ),
        ),
        "weighting": HelpEntry(
            translate("help", "Ponderación"),
            translate(
                "help",
                "Qué importa más al generar: evitar huecos, repartir la semana, respetar "
                "los deseos...",
            ),
            (
                translate(
                    "help",
                    "Recorre las pestañas y mueve cada deslizador de 0 (no importa) a 5 "
                    "(máxima importancia).",
                ),
                translate(
                    "help",
                    "Deja en 5 solo el criterio más importante: si todo es máximo, nada lo es.",
                ),
                translate(
                    "help",
                    "Vuelve a generar y compara el número de evaluación y el Diagnóstico.",
                ),
            ),
            (
                translate(
                    "help",
                    "Los valores por defecto funcionan bien para empezar: cámbialos solo "
                    "si el resultado no te convence.",
                ),
            ),
        ),
        "optimization": HelpEntry(
            translate("help", "Optimización"),
            translate(
                "help",
                "Calcula un horario completo que respeta la rejilla, las lecciones y los "
                "deseos, y lo mejora según la ponderación.",
            ),
            (
                translate(
                    "help",
                    "Elige la estrategia: una rápida para probar o una más larga para el "
                    "horario definitivo.",
                ),
                translate("help", "Pulsa Iniciar y sigue el progreso en pantalla."),
                translate(
                    "help",
                    "Puedes detener el cálculo cuando quieras: se queda el mejor horario "
                    "encontrado hasta ese momento.",
                ),
                translate(
                    "help",
                    "El resultado se guarda como un horario nuevo; los anteriores no se pierden.",
                ),
            ),
            (
                translate(
                    "help",
                    "Mientras se optimiza, las demás ventanas quedan bloqueadas para no "
                    "mezclar cambios.",
                ),
                translate(
                    "help",
                    "Si quedan clases sin colocar, mira el Diagnóstico: suele faltar "
                    "hueco para algún profesor o clase.",
                ),
            ),
        ),
        "evaluation": HelpEntry(
            translate("help", "Evaluación"),
            translate(
                "help",
                "La nota del horario: cuanto más bajo es el número de evaluación, mejor. "
                "Muestra de dónde vienen los puntos.",
            ),
            (
                translate(
                    "help",
                    "Mira primero los períodos sin colocar y los choques: deben ser cero.",
                ),
                translate(
                    "help",
                    "Después revisa el desglose por criterio: los de arriba son los que "
                    "más penalizan.",
                ),
                translate("help", "Compara los horarios generados y activa el que prefieras."),
            ),
            (
                translate(
                    "help",
                    "El número de evaluación también se ve en la barra de estado; haz "
                    "clic en él para abrir esta ventana.",
                ),
            ),
        ),
        "diagnosis": HelpEntry(
            translate("help", "Diagnóstico"),
            translate(
                "help",
                "Lista de problemas: errores en los datos de entrada y defectos del "
                "horario activo, agrupados por tipo.",
            ),
            (
                translate(
                    "help",
                    "Empieza por los errores (en rojo): impiden colocar clases o producen choques.",
                ),
                translate("help", "Despliega un grupo para ver cada caso concreto."),
                translate(
                    "help",
                    "Selecciona un caso para ir a la lección, la clase o el profesor afectado.",
                ),
            ),
            (translate("help", "Las advertencias (en ámbar) son mejoras posibles, no fallos."),),
        ),
        "planning": HelpEntry(
            translate("help", "Diálogo de planificación"),
            translate(
                "help",
                "Retoque manual del horario: mover, intercambiar, fijar o quitar clases "
                "viendo al momento si el cambio es posible.",
            ),
            (
                translate("help", "Elige la clase, el profesor o el aula que quieres ver."),
                translate(
                    "help",
                    "Arrastra una clase: las celdas verdes son destinos posibles y las "
                    "rojas, imposibles.",
                ),
                translate(
                    "help", "Fija las clases que no deben moverse en la próxima optimización."
                ),
                translate(
                    "help",
                    "Las clases sin colocar aparecen aparte: arrástralas a un hueco libre.",
                ),
            ),
            (
                translate(
                    "help", "Cada movimiento indica cuánto sube o baja el número de evaluación."
                ),
                translate("help", "Si te equivocas, Ctrl+Z deshace el último cambio."),
            ),
        ),
        "timetables": HelpEntry(
            translate("help", "Horarios"),
            translate(
                "help", "Ver, imprimir y exportar el horario de cada clase, profesor o aula."
            ),
            (
                translate("help", "Elige el tipo (clase, profesor o aula) y la entidad."),
                translate("help", "Revisa el horario en pantalla."),
                translate(
                    "help", "Imprímelo o expórtalo a PDF o HTML, uno a uno o todos a la vez."
                ),
            ),
            (
                translate(
                    "help",
                    "Los encabezados y el pie de las impresiones se editan en Datos del colegio.",
                ),
            ),
        ),
    }


def _master(title: str, summary: str, tip: str) -> HelpEntry:
    """Ficha común de las ventanas de datos maestros (misma tabla, otro tipo)."""
    return HelpEntry(
        title,
        summary,
        (
            translate("help", "Pulsa Añadir y escribe el nombre corto (debe ser único)."),
            translate(
                "help",
                "Completa las columnas que necesites directamente en la tabla, como en "
                "una hoja de cálculo.",
            ),
            translate(
                "help",
                "Selecciona una fila para ver sus lecciones y su horario en las demás ventanas.",
            ),
            translate(
                "help",
                "Para borrar, selecciona la fila y pulsa Borrar: si algo la usa, se te "
                "avisa antes.",
            ),
        ),
        (
            tip,
            translate(
                "help",
                "Una celda en rojo tiene un valor no válido; pasa el ratón por ella para "
                "ver el motivo.",
            ),
        ),
    )


def help_entry(key: str) -> HelpEntry | None:
    """Ficha de una ventana (o `None` si no la tiene)."""
    return help_entries().get(key)


def help_html(key: str) -> str:
    """Ficha en HTML sencillo para un `QTextBrowser`."""
    ficha = help_entry(key)
    if ficha is None:
        return f"<p>{escape(translate('help', 'No hay ayuda para esta ventana.'))}</p>"
    partes = [
        f"<h2>{escape(ficha.title)}</h2>",
        f"<p>{escape(ficha.summary)}</p>",
        f"<h3>{escape(translate('help', 'Cómo se usa'))}</h3>",
        "<ol>",
        *(f"<li style='margin-bottom:6px'>{escape(p)}</li>" for p in ficha.steps),
        "</ol>",
    ]
    if ficha.tips:
        partes += [
            f"<h3>{escape(translate('help', 'Consejos'))}</h3>",
            "<ul>",
            *(f"<li style='margin-bottom:6px'>{escape(t)}</li>" for t in ficha.tips),
            "</ul>",
        ]
    return "\n".join(partes)


_HELP_QSS = """
QListWidget#help_topics { border: 0; background: #f8fafc; font-size: 10pt; }
QListWidget#help_topics::item { padding: 6px 6px; }
QListWidget#help_topics::item:selected { background: #dbeafe; color: #0f172a; }
QTextBrowser#help_text { border: 0; background: #ffffff; padding: 12px; font-size: 10pt; }
"""


class HelpDialog(QDialog):
    """Ayuda: lista de temas a la izquierda y la ficha elegida a la derecha."""

    def __init__(self, topics: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        """`topics` son `(clave, icono)` en el orden en que se muestran."""
        super().__init__(parent)
        self.setObjectName("help_dialog")
        self.setWindowIcon(icon("help"))
        self.setStyleSheet(_HELP_QSS)
        self.resize(900, 640)
        self._topics = [(k, i) for k, i in topics if help_entry(k) is not None]
        self.current_key = ""
        self.list = QListWidget()
        self.list.setObjectName("help_topics")
        self.list.setIconSize(QSize(18, 18))
        self.list.setFixedWidth(250)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text = QTextBrowser()
        self.text.setObjectName("help_text")
        self.text.setOpenExternalLinks(False)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.close)
        self.close_button = botones.button(QDialogButtonBox.StandardButton.Close)
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(0)
        fila.addWidget(self.list)
        fila.addWidget(self.text, 1)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 8)
        caja.addLayout(fila, 1)
        caja.addWidget(botones)
        self.list.currentItemChanged.connect(self._on_item)
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(self.tr("Ayuda de RealSchool"))
        self.close_button.setText(self.tr("Cerrar"))
        actual = self.current_key
        fichas = help_entries()
        self.list.blockSignals(True)
        self.list.clear()
        for clave, nombre_icono in self._topics:
            item = QListWidgetItem(icon(nombre_icono), fichas[clave].title)
            item.setData(Qt.ItemDataRole.UserRole, clave)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if actual:
            self.show_topic(actual)

    def show_topic(self, key: str) -> None:
        """Muestra la ficha `key` (o la guía rápida si no existe)."""
        claves = [k for k, _ in self._topics]
        if key not in claves:
            key = GUIDE_KEY if GUIDE_KEY in claves else (claves[0] if claves else key)
        self.current_key = key
        self.text.setHtml(help_html(key))
        if key in claves:
            self.list.blockSignals(True)
            self.list.setCurrentRow(claves.index(key))
            self.list.blockSignals(False)

    def _on_item(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if item is not None:
            clave = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(clave, str):
                self.show_topic(clave)
