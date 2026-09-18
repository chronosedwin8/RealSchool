"""Registro de ventanas: cada módulo de `untis_desktop.windows` se declara solo.

Un módulo de ventana llama a `register(WindowSpec(...))` al importarse;
`load_windows()` importa todos los módulos del paquete con `pkgutil`, así que
añadir una ventana es añadir un archivo, sin tocar ninguna lista compartida.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtWidgets import QWidget

from .qt_bridge import FacadeBridge


class RibbonTab(StrEnum):
    """Pestañas de la cinta, como en Untis."""

    HOME = "home"
    MASTER_DATA = "master_data"
    LESSONS = "lessons"
    TIMETABLES = "timetables"
    MODULES = "modules"
    VIEW = "view"


#: Etiquetas de las pestañas de la cinta (español, alemán).
RIBBON_LABELS: dict[RibbonTab, tuple[str, str]] = {
    RibbonTab.HOME: ("Inicio", "Start"),
    RibbonTab.MASTER_DATA: ("Datos maestros", "Stammdaten"),
    RibbonTab.LESSONS: ("Lecciones", "Unterricht"),
    RibbonTab.TIMETABLES: ("Horarios", "Stundenpläne"),
    RibbonTab.MODULES: ("Módulos", "Module"),
    RibbonTab.VIEW: ("Vista", "Ansicht"),
}


@dataclass(frozen=True, slots=True)
class WindowSpec:
    """Una ventana del producto."""

    key: str
    title: str
    title_de: str
    tab: RibbonTab
    factory: Callable[[FacadeBridge], QWidget]
    order: int = 100
    shortcut: str = ""
    dock: str = ""
    """`""` = ventana MDI; `"right"` / `"bottom"` = panel acoplado."""
    icon: str = ""
    """Nombre semántico del icono (`untis_desktop.icons.ICONS`)."""
    tooltip: str = ""
    """Qué hace la ventana, en una frase (se muestra al pasar por la cinta)."""

    def label(self, language: str) -> str:
        return self.title_de if language == "de" else self.title


_SPECS: dict[str, WindowSpec] = {}


def register(spec: WindowSpec) -> WindowSpec:
    """Declara una ventana. Una clave repetida es un error de programación."""
    if spec.key in _SPECS and _SPECS[spec.key] is not spec:
        raise ValueError(f"Ventana registrada dos veces: {spec.key!r}")
    _SPECS[spec.key] = spec
    return spec


def specs() -> tuple[WindowSpec, ...]:
    """Ventanas registradas, en orden de cinta."""
    return tuple(sorted(_SPECS.values(), key=lambda s: (list(RibbonTab).index(s.tab), s.order)))


def spec(key: str) -> WindowSpec:
    return _SPECS[key]


def load_windows() -> tuple[WindowSpec, ...]:
    """Importa todos los módulos de `untis_desktop.windows` (se registran solos)."""
    from . import windows

    for info in pkgutil.iter_modules(windows.__path__):
        if not info.name.startswith("_"):
            importlib.import_module(f"{windows.__name__}.{info.name}")
    return specs()
