"""Ventanas de datos maestros: seis instancias del mismo `MasterDataGrid`.

Clases, Profesores, Aulas, Materias, Departamentos y Grupos de alumnos solo se
diferencian en el `MasterKind`: las columnas salen de la Fachada. La disposición
de columnas se guarda por clave de ventana.
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
        )
    )
