"""CLI `schedule-engine` con los formatos y estrategias Untis (R1/R3).

`convert` entre XmlInterface, GPU, `.rsp` y `.bjs`; `evaluate` y `solve`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scheduling_platform.cli import app

runner = CliRunner()


def _json(args: list[str]) -> dict[str, object]:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    salida: dict[str, object] = json.loads(result.stdout)
    return salida


@pytest.fixture
def rsp(anon_xml_path: Path, tmp_path: Path) -> Path:
    destino = tmp_path / "colegio.rsp"
    _json(["convert", str(anon_xml_path), str(destino)])
    return destino


def test_convert_xml_a_rsp(anon_xml_path: Path, tmp_path: Path) -> None:
    datos = _json(["convert", str(anon_xml_path), str(tmp_path / "c.rsp"), "--name", "Demo"])
    assert (datos["classes"], datos["teachers"], datos["lessons"]) == (66, 116, 722)
    assert datos["name"] == "Demo"
    assert (tmp_path / "c.rsp").is_file()


def test_convert_rsp_a_gpu_y_vuelta(rsp: Path, tmp_path: Path) -> None:
    carpeta = tmp_path / "gpu"
    datos = _json(["convert", str(rsp), str(carpeta)])
    archivos = {Path(str(f)).name.upper() for f in datos["files"]}  # type: ignore[attr-defined]
    assert {"GPU001.TXT", "GPU002.TXT", "GPU016.TXT"} <= archivos
    primera = (carpeta / "GPU001.TXT").read_text(encoding="cp1252").splitlines()[0]
    assert primera.startswith('40,"K1A"')
    vuelta = _json(["convert", str(carpeta), str(tmp_path / "desde_gpu.rsp")])
    assert vuelta["lessons"] == 722


def test_convert_rsp_a_xml(rsp: Path, tmp_path: Path) -> None:
    xml = tmp_path / "salida.xml"
    _json(["convert", str(rsp), str(xml)])
    assert "XmlInterface" in xml.read_text(encoding="utf-8")[:400]


def test_convert_destino_no_soportado(rsp: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["convert", str(rsp), str(tmp_path / "x.csv")])
    assert result.exit_code == 1
    assert "no soportado" in result.stderr


def test_evaluate(rsp: Path) -> None:
    datos = _json(["evaluate", str(rsp)])
    assert datos["clashes"] == 7
    assert datos["unplaced_periods"] == 4
    assert datos["criteria"]


def test_solve_reparar_sin_pulido(rsp: Path, tmp_path: Path) -> None:
    salida = tmp_path / "reparado.rsp"
    datos = _json(
        ["solve", str(rsp), "--strategy", "repair", "--no-polish", "-t", "30", "-o", str(salida)]
    )
    assert datos["status"] == "solved"
    assert datos["clashes"] == 0
    assert salida.is_file()
    assert _json(["evaluate", str(salida)])["clashes"] == 0


def test_solve_estrategia_desconocida(rsp: Path) -> None:
    result = runner.invoke(app, ["solve", str(rsp), "--strategy", "Z"])
    assert result.exit_code == 1
    assert "estrategia desconocida" in result.stderr


def test_solve_proyecto_inexistente(tmp_path: Path) -> None:
    result = runner.invoke(app, ["solve", str(tmp_path / "no.rsp")])
    assert result.exit_code == 1
