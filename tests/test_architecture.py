"""Reglas de arquitectura verificadas sobre todo el código fuente.

1. El solver vive solo en la SAL: ninguna capa fuera de ``sal`` importa ``ortools``.
2. Frontera de la Capa de Aplicación (Fase 2): el Core de optimización nunca
   importa ``application`` ni ``cli`` (la dependencia va siempre hacia abajo).
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "scheduling_platform"
IMPORTA_ORTOOLS = re.compile(r"^\s*(?:import ortools|from ortools)", re.MULTILINE)
IMPORTA_APP = re.compile(r"^\s*(?:from|import)\s+[\w.]*\b(?:application|cli)\b", re.MULTILINE)

# Capas del Core de optimización: no pueden depender de la Capa de Aplicación.
CORE_LAYERS = {"core", "academic", "sal", "plugins", "pipeline", "engine", "dsl", "cir"}


def test_solo_sal_importa_ortools() -> None:
    infractores = [
        str(ruta.relative_to(SRC))
        for ruta in SRC.rglob("*.py")
        if "sal" not in ruta.relative_to(SRC).parts
        and IMPORTA_ORTOOLS.search(ruta.read_text(encoding="utf-8"))
    ]
    assert not infractores, f"Capas fuera de 'sal' importan ortools: {infractores}"


def test_el_core_no_importa_la_capa_de_aplicacion() -> None:
    infractores = [
        str(ruta.relative_to(SRC))
        for ruta in SRC.rglob("*.py")
        if ruta.relative_to(SRC).parts[0] in CORE_LAYERS
        and IMPORTA_APP.search(ruta.read_text(encoding="utf-8"))
    ]
    assert not infractores, f"El Core importa la Capa de Aplicación: {infractores}"
