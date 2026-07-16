"""Los ejemplos de docs/examples/ construyen y resuelven sin errores (D6)."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

from scheduling_platform.application import GenerateCommand, OptimizeCommand, open_project
from scheduling_platform.application.dispatcher import CommandDispatcher

_EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"


def _load_build(example: str):  # type: ignore[no-untyped-def]
    path = _EXAMPLES / example / "build.py"
    spec = importlib.util.spec_from_file_location(f"example_{example}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dispatch(command: object) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    code = CommandDispatcher().dispatch(command, out=out, err=err)  # type: ignore[arg-type]
    return code, out.getvalue()


@pytest.mark.parametrize("example", ["basic", "intermediate", "advanced"])
def test_el_ejemplo_construye_y_abre(example: str, tmp_path: Path) -> None:
    path = tmp_path / f"{example}.bjs"
    _load_build(example).build(path)
    project = open_project(path)
    assert project.manifest["project_name"]
    assert len(project.problem.tasks) >= 1


def test_basico_genera_horario_valido(tmp_path: Path) -> None:
    path = tmp_path / "basic.bjs"
    _load_build("basic").build(path)
    code, out = _dispatch(GenerateCommand(str(path), quick=True))
    assert code == 0
    assert '"hard_violations": 0' in out


def test_intermedio_optimiza(tmp_path: Path) -> None:
    path = tmp_path / "intermediate.bjs"
    _load_build("intermediate").build(path)
    code, out = _dispatch(OptimizeCommand(str(path)))
    assert code == 0
    assert '"hard_violations": 0' in out
    assert open_project(path).solution is not None


def test_avanzado_optimiza(tmp_path: Path) -> None:
    path = tmp_path / "advanced.bjs"
    _load_build("advanced").build(path)
    code, out = _dispatch(OptimizeCommand(str(path)))
    assert code == 0
    assert '"hard_violations": 0' in out
