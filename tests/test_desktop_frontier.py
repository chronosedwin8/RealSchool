"""Frontera de arquitectura de la app de escritorio (Fase 6).

Dos invariantes:
1. El motor (``scheduling_platform``) **nunca** importa la GUI (``scheduling_desktop``).
2. La GUI habla con el motor **solo** a través de la Fachada
   (``scheduling_platform.application``): nunca importa ``core``/``engine``/``sal``/…
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
_PLATFORM = _SRC / "scheduling_platform"
_DESKTOP = _SRC / "scheduling_desktop"


def _python_files(root: Path) -> list[Path]:
    return list(root.rglob("*.py"))


def test_el_motor_no_importa_la_gui() -> None:
    culpables = [
        path
        for path in _python_files(_PLATFORM)
        if "scheduling_desktop" in path.read_text(encoding="utf-8")
    ]
    assert not culpables, f"el motor no debe importar la GUI: {culpables}"


def test_la_gui_solo_importa_la_fachada() -> None:
    # Cualquier import de scheduling_platform.X debe ser de application (o el paquete raíz).
    pattern = re.compile(r"scheduling_platform\.(?!application)(\w+)")
    violaciones: list[str] = []
    for path in _python_files(_DESKTOP):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            violaciones.append(f"{path.name}: scheduling_platform.{match.group(1)}")
    assert not violaciones, f"la GUI solo puede importar la Fachada: {violaciones}"
