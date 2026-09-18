"""Armazón de la UI: puente Qt, registro de ventanas y ventana principal (R4).

Las ventanas concretas se prueban en sus propios archivos; aquí se comprueba
que el armazón las descubre, las abre, bloquea la UI mientras se optimiza y
sincroniza selección, idioma y deshacer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from scheduling_platform.application import EditResult, MasterKind, OptimizeRequest
from untis_desktop.main_window import OPTIMIZATION_KEY, MainWindow
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.registry import RibbonTab, WindowSpec, load_windows, register, specs

# --------------------------------------------------------------------------- #
# Puente
# --------------------------------------------------------------------------- #


def test_puente_sin_sesion(qapp: QApplication) -> None:
    b = FacadeBridge()
    assert not b.has_session and not b.busy
    with pytest.raises(RuntimeError):
        _ = b.session


def test_puente_edita_avisa_y_deshace(qapp: QApplication) -> None:
    b = FacadeBridge()
    b.new("Demo")
    cambios: list[str] = []
    refrescos: list[bool] = []
    b.project_changed.connect(cambios.append)
    b.refreshed.connect(lambda: refrescos.append(True))

    r = b.edit(lambda: b.service.add_master(b.session, MasterKind.CLASSES, "5A"))
    assert r.ok and cambios == ["Añadir 5A"]
    b.edit(lambda: b.service.add_master(b.session, MasterKind.CLASSES, "5B"))
    qapp.processEvents()
    assert refrescos == [True]  # varios cambios, un solo refresco diferido

    fallo = b.edit(lambda: b.service.add_master(b.session, MasterKind.CLASSES, "5A"))
    assert not fallo.ok and len(cambios) == 2  # sin cambio, sin aviso

    assert b.undo()
    assert [c.id for c in b.session.project.classes] == ["5A"]
    assert b.redo() and not b.redo()


def test_puente_seleccion_sincronizada(qapp: QApplication) -> None:
    b = FacadeBridge()
    b.new()
    vistas: list[tuple[str, str]] = []
    b.selection_changed.connect(lambda k, i: vistas.append((k, i)))
    b.select("class", "5A")
    b.select("class", "5A")  # repetir no vuelve a emitir
    b.select("teacher", "ANA")
    assert vistas == [("class", "5A"), ("teacher", "ANA")]
    lecciones: list[int] = []
    b.lesson_selected.connect(lecciones.append)
    b.select_lesson(40)
    assert lecciones == [40]


def test_puente_idioma(qapp: QApplication) -> None:
    b = FacadeBridge()
    idiomas: list[str] = []
    b.language_changed.connect(idiomas.append)
    b.set_language("de")
    b.set_language("de")
    assert idiomas == ["de"] and b.language == "de"


def test_puente_optimizar_sincrono_bloquea_y_adopta(
    qapp: QApplication, anon_xml_path: Path
) -> None:
    b = FacadeBridge()
    b.attach(b.service.open(anon_xml_path))
    ocupado: list[bool] = []
    b.busy_changed.connect(ocupado.append)
    antes = len(b.session.project.timetables)
    out = b.run_optimize_sync(OptimizeRequest(strategy="repair", time_limit=20, polish=False))
    assert out.ok, out.message
    assert ocupado == [True, False]
    assert len(b.session.project.timetables) == antes + 1
    assert b.session.active_timetable == out.timetable_id
    assert out.evaluation is not None and out.evaluation.clashes == 0
    # Mientras está ocupado, editar se rechaza (se simula el estado).
    b._worker = object()  # type: ignore[assignment]
    try:
        assert not b.edit(lambda: EditResult.success()).ok
        assert not b.start_optimize(OptimizeRequest())
    finally:
        b._worker = None


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #


def test_registro_descubre_ventanas_y_rechaza_duplicados(qapp: QApplication) -> None:
    todas = load_windows()
    claves = {s.key for s in todas}
    # Las ventanas de R4/R5 que exige el documento maestro.
    esperadas = {
        "classes", "teachers", "rooms", "subjects", "departments", "student_groups",
        "time_grids", "requests", "lessons", "weighting", "settings",
        OPTIMIZATION_KEY, "evaluation", "diagnosis", "planning", "timetables",
    }  # fmt: skip
    assert esperadas <= claves
    assert specs() == todas
    orden = [list(RibbonTab).index(s.tab) for s in todas]
    assert orden == sorted(orden)

    otra = WindowSpec("classes", "x", "x", RibbonTab.HOME, lambda b: QLabel("x"))
    with pytest.raises(ValueError):
        register(otra)


# --------------------------------------------------------------------------- #
# Ventana principal
# --------------------------------------------------------------------------- #


@pytest.fixture
def shell(qapp: QApplication, anon_xml_path: Path) -> MainWindow:
    b = FacadeBridge()
    w = MainWindow(b)
    w.show()
    b.attach(b.service.open(anon_xml_path))
    qapp.processEvents()
    return w


def test_ventana_principal_abre_todas_las_ventanas(shell: MainWindow, qapp: QApplication) -> None:
    for spec in specs():
        widget = shell.show_window(spec.key)
        qapp.processEvents()
        assert widget is shell.window_widget(spec.key)  # se crea una sola vez
    mdi = {s.key for s in specs() if not s.dock}
    assert set(shell.open_keys()) == mdi
    assert shell.ribbon.count() == len(RibbonTab)


def test_ventana_principal_bloquea_durante_la_optimizacion(
    shell: MainWindow, qapp: QApplication
) -> None:
    shell.show_window("lessons")
    shell.show_window(OPTIMIZATION_KEY)
    shell.bridge.busy_changed.emit(True)
    subs = shell._subwindows
    assert not subs["lessons"].isEnabled()
    assert subs[OPTIMIZATION_KEY].isEnabled()
    assert not shell._actions["save"].isEnabled()
    shell.bridge.busy_changed.emit(False)
    assert subs["lessons"].isEnabled() and shell._actions["save"].isEnabled()


def test_ventana_principal_titulo_e_idioma(shell: MainWindow, qapp: QApplication) -> None:
    assert shell.windowTitle().startswith("RealSchool - ")
    shell.bridge.edit(
        lambda: shell.bridge.service.add_master(shell.bridge.session, MasterKind.ROOMS, "NUEVA")
    )
    assert shell.windowTitle().endswith("*")
    shell.show_window("lessons")
    shell.bridge.set_language("de")
    assert shell.ribbon.tabText(0) == "Start"
    assert shell._subwindows["lessons"].windowTitle() == "Unterricht"
    shell.bridge.set_language("es")
    assert shell.ribbon.tabText(0) == "Inicio"


def test_guardar_como_rsp(shell: MainWindow, tmp_path: Path) -> None:
    destino = shell.bridge.save(tmp_path / "colegio")
    assert destino.suffix == ".rsp" and destino.is_file()
    assert not shell.windowTitle().endswith("*")


def test_traduccion_alemana_completa() -> None:
    """Todas las cadenas de la UI tienen traducción al alemán (decisión 3)."""
    import xml.etree.ElementTree as ET

    from untis_desktop.i18n import TRANSLATIONS_DIR, qm_path

    raiz = ET.parse(TRANSLATIONS_DIR / "untis_desktop_de.ts").getroot()
    pendientes = [
        m.findtext("source")
        for m in raiz.iter("message")
        if (t := m.find("translation")) is not None
        and t.get("type") not in ("vanished", "obsolete")
        and (t.get("type") == "unfinished" or not (t.text or "").strip())
    ]
    assert pendientes == []
    assert qm_path("de").is_file()
