"""El núcleo canónico no depende del solver (Fase 1, criterio de salida).

Complementa a ``test_architecture.py`` (que analiza el código fuente) con una
verificación *dinámica*: se importa todo el paquete ``core`` en un subproceso
donde ``ortools`` está bloqueado en ``sys.meta_path``. Si algún módulo del core
lo necesitara en tiempo de importación, el subproceso fallaría.
"""

from __future__ import annotations

import subprocess
import sys

_SUBPROCESS = """
import sys

class _BlockOrtools:
    def find_spec(self, name, path=None, target=None):
        if name == "ortools" or name.startswith("ortools."):
            raise ImportError("ortools bloqueado para la prueba de aislamiento")
        return None

sys.meta_path.insert(0, _BlockOrtools())

import importlib
import pkgutil
import scheduling_platform.core as core

for module in pkgutil.iter_modules(core.__path__):
    importlib.import_module(f"scheduling_platform.core.{module.name}")

print("CORE_OK")
"""


def test_core_importa_sin_ortools() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CORE_OK" in result.stdout
