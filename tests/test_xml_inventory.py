"""Cobertura del XmlInterface en el modelo (`scripts/xml_fields_inventory.py`).

El export seudonimizado debe quedar al 100 %: toda ruta con datos o se conserva
en la ida y vuelta `read_xml` -> `write_xml` (MODELED) o es metadato derivado
que se regenera (REGENERATED). Ninguna ruta con datos puede quedar DROPPED.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "xml_fields_inventory.py"


@pytest.fixture(scope="module")
def inventario() -> ModuleType:
    spec = importlib.util.spec_from_file_location("xml_fields_inventory", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Las dataclasses resuelven sus anotaciones a través de `sys.modules`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_anon_fixture_is_fully_covered(inventario: ModuleType, anon_xml_path: Path) -> None:
    informe = inventario.inventory([anon_xml_path])
    assert inventario.dropped_with_data(informe) == []
    estados = {f.path: f.coverage.value for f in informe}
    assert estados["document/lessons/lesson/occurence"] == "MODELED"
    assert estados["document/subjects/subject/backcolor"] == "MODELED"
    assert estados["document/lesson_date_schemes/lesson_date_scheme/date_scheme"] == "MODELED"
    assert estados["document/general/termbegindate"] == "MODELED"
    assert estados["document/lessons/lesson/times/time/assigned_starttime"] == "REGENERATED"
    assert estados["document/@date"] == "REGENERATED"
    assert set(estados.values()) == {"MODELED", "REGENERATED"}
    assert "Cobertura: 60/60 (100.0 %)" in inventario.render(informe)


def test_main_exit_code(inventario: ModuleType, anon_xml_path: Path) -> None:
    assert inventario.main([str(anon_xml_path)]) == 0


def test_lost_data_is_reported_as_dropped(inventario: ModuleType, tmp_path: Path) -> None:
    """Una sección sin sitio en el modelo con datos se detecta y hace fallar."""
    fuente = tmp_path / "con_festivos.xml"
    fuente.write_text(
        '<document xmlns="https://untis.at/untis/XmlInterface">'
        "<holidays><holiday id='HD_1'><longname>Navidad</longname></holiday></holidays>"
        "<subjects><subject id='SU_A'><longname>A</longname></subject></subjects>"
        "</document>",
        encoding="utf-8",
    )
    perdidas = {f.path for f in inventario.dropped_with_data(inventario.inventory([fuente]))}
    assert perdidas == {
        "document/holidays/holiday/@id",
        "document/holidays/holiday/longname",
    }
    assert inventario.main([str(fuente)]) == 1


def test_real_exports_are_fully_covered(inventario: ModuleType, real_xml_paths: list[Path]) -> None:
    assert inventario.dropped_with_data(inventario.inventory(real_xml_paths)) == []
