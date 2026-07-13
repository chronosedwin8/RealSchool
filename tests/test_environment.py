"""Smoke tests del entorno: intérprete, paquete y dependencias clave."""

import sys
from importlib.metadata import version

import scheduling_platform


def test_python_es_314_o_superior() -> None:
    assert sys.version_info >= (3, 14)


def test_paquete_importable_con_version() -> None:
    assert scheduling_platform.__version__ == "0.1.0"


def test_ortools_instalado() -> None:
    mayor, menor = (int(p) for p in version("ortools").split(".")[:2])
    assert (mayor, menor) >= (9, 15)
