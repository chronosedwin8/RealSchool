"""Regla de arquitectura (Prompt3 §2.2): el solver vive solo en la SAL.

Ninguna capa fuera de ``scheduling_platform.sal`` puede importar ``ortools``.
Esta prueba recorre todo el código fuente y falla si encuentra violaciones.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "scheduling_platform"
IMPORTA_ORTOOLS = re.compile(r"^\s*(?:import ortools|from ortools)", re.MULTILINE)


def test_solo_sal_importa_ortools() -> None:
    infractores = [
        str(ruta.relative_to(SRC))
        for ruta in SRC.rglob("*.py")
        if "sal" not in ruta.relative_to(SRC).parts
        and IMPORTA_ORTOOLS.search(ruta.read_text(encoding="utf-8"))
    ]
    assert not infractores, f"Capas fuera de 'sal' importan ortools: {infractores}"
