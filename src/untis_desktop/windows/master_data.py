"""Ventanas de datos maestros: seis instancias del mismo `MasterDataGrid`.

Clases, Profesores, Aulas, Materias, Departamentos y Grupos de alumnos solo se
diferencian en el `MasterKind`: las columnas salen de la Fachada. La disposición
de columnas se guarda por clave de ventana.

Las seis traen la carga masiva de `MasterDataGrid` (copiar, pegar, Importar CSV
y Exportar CSV), que es como un colegio mete sus 150 profesores sin teclearlos
fila a fila; la ayuda de la cinta lo dice para que se encuentre sin buscar.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from scheduling_platform.application import MasterKind

from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..widgets.master_grid import MasterDataGrid

#: `(clave, tipo, título, título en alemán)` en el orden de la cinta.
MASTER_WINDOWS: tuple[tuple[str, MasterKind, str, str], ...] = (
    ("classes", MasterKind.CLASSES, "Clases", "Klassen"),
    ("teachers", MasterKind.TEACHERS, "Profesores", "Lehrer"),
    ("rooms", MasterKind.ROOMS, "Aulas", "Räume"),
    ("subjects", MasterKind.SUBJECTS, "Materias", "Fächer"),
    ("departments", MasterKind.DEPARTMENTS, "Departamentos", "Abteilungen"),
    ("student_groups", MasterKind.STUDENT_GROUPS, "Grupos de alumnos", "Schülergruppen"),
)

#: Lo mismo para las seis: cómo se meten los datos de golpe (se añade a la ayuda
#: de la cinta, para que la carga masiva se vea sin abrir la ventana).
BULK_HINT = " Se puede cargar de golpe desde un CSV o pegando desde Excel."

BULK_HINT_DE = " Kann per CSV oder Einfügen aus Excel auf einmal geladen werden."

#: Qué es cada ventana, en una frase (ayuda de la cinta). El icono es la clave.
MASTER_TOOLTIPS: dict[str, str] = {
    "classes": "Lista de clases (grupos de alumnos fijos) con su rejilla, aula base y límites.",
    "teachers": "Lista de profesores con sus límites de horas, huecos y días.",
    "rooms": "Lista de aulas con su capacidad y el aula alternativa si están ocupadas.",
    "subjects": "Lista de materias con sus colores y reglas (dobles, aula obligatoria...).",
    "departments": "Departamentos para agrupar profesores y materias.",
    "student_groups": "Grupos de alumnos que se separan de la clase para una materia.",
}

MASTER_TOOLTIPS_DE: dict[str, str] = {
    "classes": "Liste der Klassen mit Zeitraster, Stammraum und Grenzen.",
    "teachers": "Liste der Lehrkräfte mit ihren Grenzen für Stunden, Hohlstunden und Tage.",
    "rooms": "Liste der Räume mit Kapazität und Ausweichraum, wenn sie belegt sind.",
    "subjects": "Liste der Fächer mit Farben und Regeln (Doppelstunden, Pflichtraum...).",
    "departments": "Abteilungen, um Lehrkräfte und Fächer zu gruppieren.",
    "student_groups": "Schülergruppen, die sich für ein Fach von der Klasse trennen.",
}


def _factory(key: str, kind: MasterKind) -> Callable[[FacadeBridge], QWidget]:
    def crear(bridge: FacadeBridge) -> QWidget:
        return MasterDataGrid(bridge, kind, key)

    return crear


for _orden, (_clave, _tipo, _titulo, _titulo_de) in enumerate(MASTER_WINDOWS, start=1):
    register(
        WindowSpec(
            key=_clave,
            title=_titulo,
            title_de=_titulo_de,
            tab=RibbonTab.MASTER_DATA,
            factory=_factory(_clave, _tipo),
            order=_orden,
            icon=_clave,
            tooltip=MASTER_TOOLTIPS[_clave] + BULK_HINT,
            tooltip_de=MASTER_TOOLTIPS_DE[_clave] + BULK_HINT_DE,
        )
    )
