"""Registro de fallos de la aplicación de escritorio."""

from __future__ import annotations

from pathlib import Path

import pytest

from untis_desktop import crashlog


def test_registro_de_fallos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(crashlog, "_log", None)
    ruta = crashlog.install()
    assert ruta == tmp_path / "RealSchool" / "crash.log"
    crashlog.note("ventana: planning")
    crashlog.close_cleanly()
    texto = ruta.read_text(encoding="utf-8")
    assert "RealSchool iniciado" in texto
    assert "ventana: planning" in texto
    assert "cierre normal" in texto
    # Deja faulthandler como estaba para el resto de la sesión de pruebas.
    import faulthandler

    faulthandler.disable()
    monkeypatch.setattr(crashlog, "_log", None)
