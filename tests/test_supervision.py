"""Guardias de recreo (Pausenaufsichten): modelo, reparto, Fachada y ventana.

El proyecto de pruebas es minúsculo y siempre el mismo, para que todo sea
determinista: una rejilla `G` de dos días con un solo recreo (el período 3, de
20 min, entre las horas 2 y 4), cuatro profesores y un horario que los coloca a
propósito antes, después o lejos del recreo.

- ANA da clase las horas 2 y 4 del día 1: está a los dos lados del recreo.
- BEA solo la hora 2 del día 1: está solo antes.
- CAR la hora 4 del día 1 y la hora 2 del día 2: un lado cada día.
- DAN daría clase pegada al recreo, pero tiene `supervision_max = 0`.
- EVA solo da clase la hora 1: nunca está junto al recreo.

Mientras la Fachada no herede el mixin se prueba con `_Servicio`, que es
exactamente `class _Servicio(SupervisionMixin, UntisService)`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest
from PySide6.QtWidgets import QApplication, QComboBox
from pytestqt.qtbot import QtBot

from scheduling_platform.application import EditResult, UntisService, UntisSession
from scheduling_platform.application.untis import build_grid
from scheduling_platform.application.untis.supervision import (
    SupervisionFacade,
    SupervisionMixin,
)
from scheduling_platform.heuristic.supervision import (
    SupervisionOutcome,
    assign_supervisions,
    neighbour_periods,
    supervision_minutes,
)
from scheduling_platform.untis_model import (
    Assignment,
    Lesson,
    LessonLine,
    Supervision,
    SupervisionArea,
    Teacher,
    Timetable,
    UntisProject,
)
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.registry import RibbonTab, spec
from untis_desktop.windows.supervision import SupervisionWindow

#: Duración del recreo de la rejilla de pruebas.
BREAK_MINUTES = 20
#: Número del período de recreo en esa rejilla.
BREAK_PERIOD = 3


class _Servicio(SupervisionMixin, UntisService):
    """La Fachada con el mixin de guardias, hasta que `service.py` lo herede."""


# --------------------------------------------------------------------------- #
# Proyecto de pruebas
# --------------------------------------------------------------------------- #


def _lesson(number: int, teacher: str) -> Lesson:
    return Lesson(
        number=number,
        lines=(LessonLine(subject="MAT", teacher=teacher, classes=("5A",)),),
        periods_per_week=2,
        time_grid="G",
    )


#: Profesor -> celdas `(día, hora)` en las que da clase en el horario de prueba.
CLASSES: dict[str, tuple[tuple[int, int], ...]] = {
    "ANA": ((1, 2), (1, 4)),
    "BEA": ((1, 2),),
    "CAR": ((1, 4), (2, 2)),
    "DAN": ((1, 2), (1, 4)),
    "EVA": ((1, 1), (2, 1)),
}


def _project(
    *,
    areas: tuple[str, ...] = ("PATIO", "PASILLO"),
    days: tuple[int, ...] = (1, 2),
    maximums: dict[str, int | None] | None = None,
) -> UntisProject:
    """Proyecto con rejilla, profesores, horario y zonas (sin turnos)."""
    topes = maximums or {"DAN": 0}
    grid = build_grid("G", days=days, periods=4, start="08:00", duration=45, breaks={2: 20})
    profesores = tuple(Teacher(id=t, supervision_max=topes.get(t)) for t in sorted(CLASSES))
    lecciones = tuple(_lesson(i + 1, t) for i, t in enumerate(sorted(CLASSES)))
    asignaciones = tuple(
        Assignment(lesson_number=i + 1, line=0, day=d, period=p)
        for i, t in enumerate(sorted(CLASSES))
        for d, p in CLASSES[t]
        if d in days
    )
    return UntisProject(
        time_grids=(grid,),
        teachers=profesores,
        lessons=lecciones,
        timetables=(Timetable(id="T1", name="Horario", assignments=asignaciones),),
        supervision_areas=tuple(SupervisionArea(id=a, weight=3) for a in areas),
    )


def _with_shifts(project: UntisProject, *keys: tuple[str, int, int]) -> UntisProject:
    turnos = tuple(Supervision(area=a, day=d, period=p) for a, d, p in keys)
    return dataclasses.replace(project, supervisions=turnos)


def _all_shifts(project: UntisProject, days: tuple[int, ...] = (1, 2)) -> UntisProject:
    """Parrilla completa: un turno por zona y día en el recreo."""
    return _with_shifts(
        project,
        *((a.id, d, BREAK_PERIOD) for a in project.supervision_areas for d in days),
    )


def _session(project: UntisProject) -> UntisSession:
    return UntisSession(project)


# --------------------------------------------------------------------------- #
# Modelo
# --------------------------------------------------------------------------- #


def test_modelo_zona_y_turno() -> None:
    zona = SupervisionArea(id="PATIO", name="Patio grande", weight=5)
    assert zona.display_name == "Patio grande"
    assert SupervisionArea(id="X").display_name == "X"
    turno = Supervision(area="PATIO", day=2, period=3, teacher="ANA")
    assert turno.slot == (2, 3) and turno.key == ("PATIO", 2, 3) and turno.assigned
    assert not Supervision(area="PATIO", day=1, period=3).assigned


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "", "weight": 1},
        {"id": "P", "weight": 9},
    ],
)
def test_modelo_zona_rechaza_lo_invalido(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SupervisionArea(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"area": "", "day": 1, "period": 3},
        {"area": "P", "day": 0, "period": 3},
        {"area": "P", "day": 1, "period": 0},
        {"area": "P", "day": 1, "period": 3, "minutes": -5},
    ],
)
def test_modelo_turno_rechaza_lo_invalido(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Supervision(**kwargs)  # type: ignore[arg-type]


def test_minutos_y_vecinos_del_recreo() -> None:
    p = _project()
    grid = p.time_grids[0]
    assert neighbour_periods(grid, BREAK_PERIOD) == (2, 4)
    assert neighbour_periods(grid, 1) == (None, 2)
    turno = Supervision(area="PATIO", day=1, period=BREAK_PERIOD)
    assert supervision_minutes(grid, turno) == BREAK_MINUTES
    assert supervision_minutes(grid, dataclasses.replace(turno, minutes=15)) == 15
    assert supervision_minutes(None, turno) == 0


# --------------------------------------------------------------------------- #
# Reparto (heurística)
# --------------------------------------------------------------------------- #


def _minutes_of(outcome: SupervisionOutcome, teacher: str) -> int:
    return outcome.minutes_by_teacher.get(teacher, 0)


def test_reparto_cubre_y_no_repite_profesor_en_el_mismo_recreo() -> None:
    p = _all_shifts(_project())
    r = assign_supervisions(p)
    assert r.total == 4
    # Día 1: ANA, BEA y CAR son candidatos; día 2 solo CAR, así que una zona
    # del día 2 se queda sin cubrir (nadie puede estar en dos sitios a la vez).
    assert r.assigned == 3 and r.uncovered == 1
    por_celda: dict[tuple[int, int], set[str]] = {}
    for s in r.supervisions:
        if s.assigned:
            assert s.teacher not in por_celda.setdefault(s.slot, set())
            por_celda[s.slot].add(s.teacher)
    assert r.elapsed >= 0.0


def test_solo_vigila_quien_da_clase_antes_o_despues() -> None:
    p = _all_shifts(_project())
    r = assign_supervisions(p)
    profesores = {s.teacher for s in r.supervisions if s.assigned}
    assert "EVA" not in profesores, "EVA solo da clase la hora 1, lejos del recreo"
    assert "DAN" not in profesores, "DAN tiene supervision_max = 0"
    assert profesores <= {"ANA", "BEA", "CAR"}


def test_sin_horario_nadie_es_candidato() -> None:
    p = dataclasses.replace(_all_shifts(_project()), timetables=())
    r = assign_supervisions(p)
    assert r.uncovered == r.total == 4
    assert r.minutes_by_teacher == {}


def test_reparto_determinista_con_la_misma_semilla() -> None:
    p = _all_shifts(_project())
    uno = assign_supervisions(p, seed=7)
    otro = assign_supervisions(p, seed=7)
    assert uno.supervisions == otro.supervisions
    assert assign_supervisions(p, seed=1).assigned == uno.assigned


def test_reparto_respeta_el_maximo_de_minutos() -> None:
    """ANA solo puede hacer un turno; el resto va a los demás candidatos."""
    p = _all_shifts(_project(maximums={"DAN": 0, "ANA": BREAK_MINUTES}))
    r = assign_supervisions(p)
    assert _minutes_of(r, "ANA") <= BREAK_MINUTES
    assert r.assigned == 3


def test_reparto_sin_nadie_con_cupo_deja_los_turnos_sin_cubrir() -> None:
    topes = {"ANA": 0, "BEA": 0, "CAR": 0, "DAN": 0, "EVA": 0}
    r = assign_supervisions(_all_shifts(_project(maximums=topes)))
    assert r.uncovered == r.total == 4 and r.assigned == 0


def test_reparto_equilibra_los_minutos() -> None:
    """Cuatro zonas un solo día: ANA y BEA se reparten dos turnos cada una."""
    p = _project(areas=("A", "B", "C", "D"), days=(1,))
    r = assign_supervisions(_all_shifts(p, days=(1,)))
    assert r.assigned == 4 and r.uncovered == 0
    assert set(r.minutes_by_teacher) == {"ANA", "BEA", "CAR"}
    assert r.spread <= BREAK_MINUTES
    assert sum(r.minutes_by_teacher.values()) == 4 * BREAK_MINUTES


def test_los_turnos_fijos_no_se_mueven() -> None:
    p = _all_shifts(_project())
    # BEA fijada en el día 1 aunque el reparto preferiría a ANA (está a los dos
    # lados); y EVA fijada a mano aunque no sea candidata.
    turnos = tuple(
        dataclasses.replace(s, teacher="BEA", fixed=True)
        if s.key == ("PATIO", 1, BREAK_PERIOD)
        else dataclasses.replace(s, teacher="EVA", fixed=True)
        if s.key == ("PASILLO", 1, BREAK_PERIOD)
        else s
        for s in p.supervisions
    )
    r = assign_supervisions(dataclasses.replace(p, supervisions=turnos))
    fijos = {s.key: s.teacher for s in r.supervisions if s.fixed}
    assert fijos == {("PATIO", 1, BREAK_PERIOD): "BEA", ("PASILLO", 1, BREAK_PERIOD): "EVA"}
    assert _minutes_of(r, "EVA") == BREAK_MINUTES


def test_los_asignados_sin_fijar_se_vuelven_a_repartir() -> None:
    p = _all_shifts(_project())
    sucio = dataclasses.replace(
        p,
        supervisions=tuple(
            dataclasses.replace(s, teacher="EVA") if s.day == 1 else s for s in p.supervisions
        ),
    )
    r = assign_supervisions(sucio)
    assert "EVA" not in {s.teacher for s in r.supervisions if s.assigned}


def test_el_reparto_se_puede_parar() -> None:
    p = _all_shifts(_project())
    r = assign_supervisions(p, should_stop=lambda: True)
    assert r.total == 4 and r.uncovered <= 4


def test_sin_turnos_el_resultado_esta_vacio() -> None:
    r = assign_supervisions(_project())
    assert r.total == 0 and r.uncovered == 0 and r.spread == 0


# --------------------------------------------------------------------------- #
# Fachada
# --------------------------------------------------------------------------- #


@pytest.fixture
def svc() -> _Servicio:
    return _Servicio()


@pytest.fixture
def sesion() -> UntisSession:
    return _session(_project())


def test_fachada_zonas_anadir_renombrar_y_borrar(svc: _Servicio, sesion: UntisSession) -> None:
    assert [z.id for z in svc.supervision_areas(sesion)] == ["PATIO", "PASILLO"]
    assert svc.add_supervision_area(sesion, "COMEDOR", time_grid="G").ok
    assert [z.id for z in svc.supervision_areas(sesion)] == ["PATIO", "PASILLO", "COMEDOR"]
    assert not svc.add_supervision_area(sesion, "COMEDOR").ok
    assert not svc.add_supervision_area(sesion, "  ").ok
    assert not svc.add_supervision_area(sesion, "X", time_grid="NO").ok
    assert not svc.add_supervision_area(sesion, "X", weight=9).ok

    assert svc.rename_supervision_area(sesion, "COMEDOR", "Comedor grande").ok
    fila = next(z for z in svc.supervision_areas(sesion) if z.id == "COMEDOR")
    assert fila.name == "Comedor grande"
    assert not svc.rename_supervision_area(sesion, "NO", "x").ok

    assert svc.remove_supervision_area(sesion, "COMEDOR").ok
    assert not svc.remove_supervision_area(sesion, "COMEDOR").ok
    assert svc.undo(sesion) and "COMEDOR" in sesion.project.area_by_id


def test_fachada_borrar_zona_se_lleva_sus_turnos(svc: _Servicio) -> None:
    s = _session(_all_shifts(_project()))
    assert svc.remove_supervision_area(s, "PATIO").ok
    assert {t.area for t in s.project.supervisions} == {"PASILLO"}
    assert svc.undo(s)
    assert len(s.project.supervisions) == 4


def test_fachada_genera_la_parrilla(svc: _Servicio, sesion: UntisSession) -> None:
    resultado = svc.build_supervision_shifts(sesion, "G")
    assert resultado.ok and "4" in resultado.message
    assert {t.key for t in sesion.project.supervisions} == {
        (a, d, BREAK_PERIOD) for a in ("PATIO", "PASILLO") for d in (1, 2)
    }
    # Idempotente: volver a pulsar no duplica nada.
    assert svc.build_supervision_shifts(sesion, "G").ok
    assert len(sesion.project.supervisions) == 4


def test_fachada_parrilla_sin_rejilla_sin_recreos_y_sin_zonas(svc: _Servicio) -> None:
    vacio = _session(UntisProject())
    assert not svc.build_supervision_shifts(vacio).ok

    sin_recreos = build_grid("S", days=(1,), periods=2, start="08:00", duration=45)
    s = _session(dataclasses.replace(_project(), time_grids=(sin_recreos,)))
    assert not svc.build_supervision_shifts(s, "S").ok

    sin_zonas = _session(dataclasses.replace(_project(), supervision_areas=()))
    assert not svc.build_supervision_shifts(sin_zonas, "G").ok
    assert not svc.build_supervision_shifts(sin_zonas, "NO").ok


def test_fachada_vista_de_la_parrilla(svc: _Servicio) -> None:
    s = _session(_all_shifts(_project()))
    vista = svc.supervision_grid(s, "G")
    assert vista.grid_id == "G"
    assert [(h.day, h.period) for h in vista.slots] == [(1, BREAK_PERIOD), (2, BREAK_PERIOD)]
    assert vista.slots[0].start == "08:45" and vista.slots[0].minutes == BREAK_MINUTES
    assert len(vista.cells) == 4 and vista.uncovered == 4
    assert "DAN" not in vista.teachers, "supervision_max = 0 no sale en el desplegable"
    celda = vista.cell("PATIO", 1, BREAK_PERIOD)
    assert celda is not None and celda.exists and not celda.assigned
    assert vista.cell("PATIO", 7, BREAK_PERIOD) is None
    assert svc.supervision_grid(_session(UntisProject()), "").message


def test_fachada_parrilla_avisa_cuando_falta_algo(svc: _Servicio) -> None:
    sin_zonas = _session(dataclasses.replace(_project(), supervision_areas=()))
    assert "zonas" in svc.supervision_grid(sin_zonas, "G").message
    sin_recreos = build_grid("S", days=(1,), periods=2, start="08:00", duration=45)
    s = _session(dataclasses.replace(_project(), time_grids=(sin_recreos,)))
    assert "recreo" in svc.supervision_grid(s, "S").message


def test_fachada_turno_suelto_y_duplicado(svc: _Servicio, sesion: UntisSession) -> None:
    assert svc.add_supervision(sesion, "PATIO", 1, BREAK_PERIOD).ok
    duplicado = svc.add_supervision(sesion, "PATIO", 1, BREAK_PERIOD)
    assert not duplicado.ok and "ya tiene turno" in duplicado.message
    assert not svc.add_supervision(sesion, "NO", 1, BREAK_PERIOD).ok
    assert not svc.add_supervision(sesion, "PATIO", 1, 2).ok, "la hora 2 no es un recreo"
    assert not svc.add_supervision(sesion, "PATIO", 5, BREAK_PERIOD).ok, "día fuera de la rejilla"
    assert svc.remove_supervision(sesion, "PATIO", 1, BREAK_PERIOD).ok
    assert not svc.remove_supervision(sesion, "PATIO", 1, BREAK_PERIOD).ok


def test_fachada_asignar_y_quitar_profesor(svc: _Servicio) -> None:
    s = _session(_all_shifts(_project()))
    assert svc.set_supervision_teacher(s, "PATIO", 1, BREAK_PERIOD, "ANA").ok
    turno = next(t for t in s.project.supervisions if t.key == ("PATIO", 1, BREAK_PERIOD))
    assert turno.teacher == "ANA" and turno.fixed, "a mano queda fijado, como en Untis"

    assert not svc.set_supervision_teacher(s, "PATIO", 1, BREAK_PERIOD, "NADIE").ok
    assert not svc.set_supervision_teacher(s, "NO", 1, BREAK_PERIOD, "ANA").ok
    assert not svc.set_supervision_teacher(s, "PATIO", 2, 9, "ANA").ok
    choque = svc.set_supervision_teacher(s, "PASILLO", 1, BREAK_PERIOD, "ANA")
    assert not choque.ok and "dos sitios" in choque.message

    assert svc.clear_supervision_teacher(s, "PATIO", 1, BREAK_PERIOD).ok
    turno = next(t for t in s.project.supervisions if t.key == ("PATIO", 1, BREAK_PERIOD))
    assert not turno.assigned and not turno.fixed
    assert svc.undo(s), "cada paso se puede deshacer"


def test_fachada_avisa_al_pasarse_del_maximo_pero_deja(svc: _Servicio) -> None:
    p = _all_shifts(_project(maximums={"DAN": 0, "ANA": BREAK_MINUTES}))
    s = _session(p)
    assert svc.set_supervision_teacher(s, "PATIO", 1, BREAK_PERIOD, "ANA").message == ""
    segundo = svc.set_supervision_teacher(s, "PATIO", 2, BREAK_PERIOD, "ANA")
    assert segundo.ok and "Aviso" in segundo.message and "40" in segundo.message
    carga = next(c for c in svc.supervision_load(s) if c.teacher == "ANA")
    assert carga.minutes == 40 and carga.maximum == BREAK_MINUTES and carga.over_max
    assert carga.free == -BREAK_MINUTES and carga.shifts == 2


def test_fachada_fijar_y_soltar(svc: _Servicio) -> None:
    s = _session(_all_shifts(_project()))
    assert not svc.set_supervision_fixed(s, "PATIO", 1, BREAK_PERIOD, True).ok
    assert not svc.set_supervision_fixed(s, "NO", 1, BREAK_PERIOD, False).ok
    assert svc.set_supervision_teacher(s, "PATIO", 1, BREAK_PERIOD, "ANA").ok
    assert svc.set_supervision_fixed(s, "PATIO", 1, BREAK_PERIOD, False).ok
    turno = next(t for t in s.project.supervisions if t.key == ("PATIO", 1, BREAK_PERIOD))
    assert turno.assigned and not turno.fixed


def test_fachada_reparto_automatico(svc: _Servicio) -> None:
    s = _session(_all_shifts(_project()))
    assert not svc.distribute_supervisions(_session(_project())).ok, "sin turnos no hay reparto"
    sin_horario = _session(dataclasses.replace(_all_shifts(_project()), timetables=()))
    fallo = svc.distribute_supervisions(sin_horario)
    assert not fallo.ok and "horario" in fallo.message

    resultado = svc.distribute_supervisions(s, seed=3)
    assert resultado.ok and "sin cubrir" in resultado.message
    assert sum(1 for t in s.project.supervisions if t.assigned) == 3
    assert svc.undo(s) and not any(t.assigned for t in s.project.supervisions)


def test_fachada_reparto_respeta_lo_puesto_a_mano(svc: _Servicio) -> None:
    s = _session(_all_shifts(_project()))
    assert svc.set_supervision_teacher(s, "PATIO", 1, BREAK_PERIOD, "BEA").ok
    assert svc.distribute_supervisions(s).ok
    turno = next(t for t in s.project.supervisions if t.key == ("PATIO", 1, BREAK_PERIOD))
    assert turno.teacher == "BEA" and turno.fixed


def test_fachada_resumen_por_profesor(svc: _Servicio) -> None:
    topes = {"DAN": 0, "ANA": 60, "BEA": None}
    s = _session(_all_shifts(_project(maximums=topes)))
    assert svc.distribute_supervisions(s).ok
    cargas = svc.supervision_load(s)
    assert [c.minutes for c in cargas] == sorted((c.minutes for c in cargas), reverse=True)
    por_id = {c.teacher: c for c in cargas}
    assert sum(c.shifts for c in cargas) == 3
    assert sum(c.minutes for c in cargas) == 3 * BREAK_MINUTES
    assert por_id["ANA"].maximum == 60 and not por_id["ANA"].over_max
    assert por_id["DAN"].minutes == 0 and por_id["DAN"].maximum == 0


def test_la_fachada_suelta_hace_lo_mismo() -> None:
    """`SupervisionFacade` es el mixin a solas: no usa estado del servicio."""
    s = _session(_all_shifts(_project()))
    suelta = SupervisionFacade()
    assert suelta.distribute_supervisions(s).ok
    assert len(suelta.supervision_areas(s)) == 2


# --------------------------------------------------------------------------- #
# Ventana de escritorio
# --------------------------------------------------------------------------- #


@pytest.fixture
def bridge(qapp: QApplication) -> Iterator[FacadeBridge]:
    b = FacadeBridge(_Servicio())
    yield b
    b.set_language("es")


@pytest.fixture
def ventana(qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication) -> SupervisionWindow:
    bridge.attach(_session(_all_shifts(_project())))
    w = SupervisionWindow(bridge)
    qtbot.addWidget(w)
    qapp.processEvents()
    return w


def _combo(window: SupervisionWindow, area: str, day: int) -> QComboBox:
    combo = window.cell_combos[(area, day, BREAK_PERIOD)]
    assert isinstance(combo, QComboBox)
    return combo


def test_ventana_registrada_en_la_cinta() -> None:
    ficha = spec("supervision")
    assert ficha.tab is RibbonTab.MODULES and ficha.icon == "break"
    assert len(ficha.tooltip) > 20 and ficha.tooltip.endswith(".")
    assert ficha.title_de == "Pausenaufsichten" and ficha.tooltip_de


def test_ventana_sin_proyecto_no_se_rompe(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = SupervisionWindow(bridge)
    qtbot.addWidget(w)
    assert w.table.rowCount() == 0 and w.grid_view is None
    assert not w.distribute_action.isEnabled()
    assert not w.add_area().ok and not w.build_shifts().ok and not w.distribute().ok


def test_ventana_pinta_la_parrilla(ventana: SupervisionWindow) -> None:
    assert ventana.grid_id == "G"
    assert ventana.table.rowCount() == 2 and ventana.table.columnCount() == 2
    assert ventana.table.verticalHeaderItem(0).text() == "PATIO"
    assert "Lunes" in ventana.table.horizontalHeaderItem(0).text()
    assert len(ventana.cell_combos) == 4
    assert _combo(ventana, "PATIO", 1).currentData() == ""
    assert "sin cubrir" in ventana.banner.text()


def test_ventana_asigna_con_el_desplegable(ventana: SupervisionWindow, qapp: QApplication) -> None:
    combo = _combo(ventana, "PATIO", 1)
    combo.setCurrentIndex(combo.findData("ANA"))
    qapp.processEvents()
    turno = next(t for t in ventana.bridge.session.project.supervisions if t.key == ("PATIO", 1, 3))
    assert turno.teacher == "ANA" and turno.fixed
    assert _combo(ventana, "PATIO", 1).currentData() == "ANA"
    assert ventana.load_table.rowCount() >= 1
    # El mismo profesor en otra zona del mismo recreo: la Fachada lo rechaza.
    otro = _combo(ventana, "PASILLO", 1)
    otro.setCurrentIndex(otro.findData("ANA"))
    qapp.processEvents()
    assert "dos sitios" in ventana.banner.text()
    assert _combo(ventana, "PASILLO", 1).currentData() == ""


def test_ventana_reparte_y_deshace(ventana: SupervisionWindow) -> None:
    resultado = ventana.distribute()
    assert resultado.ok
    asignados = [t for t in ventana.bridge.session.project.supervisions if t.assigned]
    assert len(asignados) == 3
    assert ventana.load_table.rowCount() == len({t.teacher for t in asignados})
    assert ventana.bridge.undo()


def test_ventana_zonas_turnos_y_seleccion(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    bridge.attach(_session(dataclasses.replace(_project(), supervision_areas=())))
    w = SupervisionWindow(bridge)
    qtbot.addWidget(w)
    assert "zonas" in w.banner.text()
    assert w.create_area("COMEDOR", "Comedor").ok
    assert not w.create_area("COMEDOR").ok
    assert w.build_shifts().ok
    assert w.table.rowCount() == 1 and w.table.columnCount() == 2
    assert w.table.verticalHeaderItem(0).text() == "Comedor"

    assert not w.clear_selected().ok, "sin celda seleccionada no hay nada que quitar"
    assert not w.remove_area().ok
    w.table.setCurrentCell(0, 0)
    celda = w.selected_cell()
    assert celda is not None and celda.area == "COMEDOR"
    assert w.set_teacher("COMEDOR", 1, BREAK_PERIOD, "ANA").ok
    w.table.setCurrentCell(0, 0)
    assert w.unfix_action.isEnabled() and w.unfix_selected().ok
    assert w.clear_selected().ok
    w.table.setCurrentCell(0, 0)
    assert w.remove_area().ok and w.table.rowCount() == 0
    qapp.processEvents()


def test_ventana_iconos_ayudas_y_leyenda(ventana: SupervisionWindow) -> None:
    for accion in (
        ventana.add_action,
        ventana.rename_action,
        ventana.remove_action,
        ventana.build_action,
        ventana.distribute_action,
        ventana.unfix_action,
        ventana.clear_action,
    ):
        ayuda = accion.toolTip().strip()
        assert not accion.icon().isNull() and ayuda and ayuda != accion.text()
    assert len(ventana.legend.texts) == 4
    assert ventana.grid_combo.toolTip() and ventana.load_box.title()


def test_ventana_cambia_de_idioma(ventana: SupervisionWindow, qapp: QApplication) -> None:
    ventana.bridge.set_language("de")
    qapp.processEvents()
    assert "Montag" in ventana.table.horizontalHeaderItem(0).text()
    ventana.bridge.set_language("es")
    qapp.processEvents()
    assert "Lunes" in ventana.table.horizontalHeaderItem(0).text()


def test_ventana_usa_la_fachada_suelta_si_el_servicio_no_lleva_el_mixin(
    qtbot: QtBot, qapp: QApplication
) -> None:
    """Hasta que `UntisService` herede el mixin, la ventana funciona igual."""
    b = FacadeBridge(UntisService())
    b.attach(_session(_all_shifts(_project())))
    w = SupervisionWindow(b)
    qtbot.addWidget(w)
    qapp.processEvents()
    assert not isinstance(b.service, SupervisionMixin)
    assert len(w.cell_combos) == 4
    resultado: EditResult = w.distribute()
    assert resultado.ok
