"""El dominio no depende del solver (criterio de salida Fases 1 y 2).

Complementa a ``test_architecture.py`` (que analiza el código fuente) con una
verificación *dinámica*: se importan los paquetes ``core`` y ``academic`` en un
subproceso donde ``ortools`` está bloqueado en ``sys.meta_path``. Si algún
módulo del dominio lo necesitara en tiempo de importación, el subproceso
fallaría.
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

for package_name in ("scheduling_platform.core", "scheduling_platform.academic"):
    package = importlib.import_module(package_name)
    for module in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package_name}.{module.name}")

print("DOMAIN_OK")
"""


def test_dominio_importa_sin_ortools() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "DOMAIN_OK" in result.stdout
