"""Pruebas del puente `untis_model` -> motor canónico (R2).

El criterio de aceptación de la fase es que la traducción sea **fiel**: el
`ValidationEngine` (juez independiente) debe señalar sobre el horario publicado
por Untis exactamente los choques reales —medidos por separado sobre el reloj de
pared— y ni uno más. El export real contiene 7 choques de profesor aceptados por
el planificador, así que "0 duras" no es alcanzable; "0 falsos positivos" sí.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

from scheduling_platform.bridge import (
    Clock,
    ResourceKind,
    SessionRef,
    UntisTranslator,
    is_duty,
    solution_to_timetable,
    timetable_to_solution,
    translate,
)
from scheduling_platform.engine import ValidationEngine
from scheduling_platform.interop.xml import read_xml
from scheduling_platform.untis_model import (
    Assignment,
    Lesson,
    LessonLine,
    PeriodDef,
    Room,
    SchoolClass,
    Subject,
    Teacher,
    TimeGrid,
    Timetable,
    UntisProject,
)

# --------------------------------------------------------------------------- #
# Datos
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def anon(anon_xml_path: Path) -> UntisProject:
    return read_xml(anon_xml_path)


def _two_grids() -> tuple[TimeGrid, TimeGrid]:
    """Dos rejillas con relojes distintos: el período 1 no coincide."""
    a = TimeGrid(
        id="A",
        days=(1, 2),
        periods=(PeriodDef(1, 480, 525), PeriodDef(2, 530, 575), PeriodDef(3, 580, 590)),
    )
    b = TimeGrid(
        id="B",
        days=(1, 2),
        periods=(PeriodDef(1, 500, 545), PeriodDef(2, 550, 595)),
    )
    return a, b


def _mini(**cambios: object) -> UntisProject:
    a, b = _two_grids()
    base: dict[str, object] = {
        "time_grids": (a, b),
        "classes": (SchoolClass(id="C1", time_grid="A"), SchoolClass(id="C2", time_grid="B")),
        "teachers": (Teacher(id="T1"), Teacher(id="T2"), Teacher(id="T3")),
        "rooms": (Room(id="R1", capacity=30), Room(id="R2", alternative_room="R3"), Room(id="R3")),
        "subjects": (Subject(id="MAT"), Subject(id="ING")),
        "lessons": (
            Lesson(
                number=1,
                lines=(LessonLine(subject="MAT", teacher="T1", classes=("C1",), room="R1"),),
                periods_per_week=2,
                time_grid="A",
            ),
            Lesson(  # acople de 2 líneas
                number=2,
                lines=(
                    LessonLine(subject="ING", teacher="T2", classes=("C2",), room="R2"),
                    LessonLine(subject="ING", teacher="T3", classes=("C2",)),
                ),
                periods_per_week=1,
                time_grid="B",
            ),
            Lesson(  # obligación no lectiva
                number=3,
                lines=(LessonLine(subject="MAT", teacher="T1"),),
                periods_per_week=1,
                time_grid="A",
            ),
        ),
    }
    base.update(cambios)
    return UntisProject(**base)  # type: ignore[arg-type]


def _wall_clock_collisions(project: UntisProject) -> set[tuple[str, frozenset[int]]]:
    """Choques de profesor medidos directamente sobre el reloj de pared.

    Método independiente del motor: compara intervalos de minutos reales entre
    lecciones lectivas distintas del mismo profesor.
    """
    lecciones = project.lesson_by_number
    grids = project.grid_by_id
    por_profe: defaultdict[str, list[tuple[int, int, int, int]]] = defaultdict(list)
    tt = project.timetables[0]
    for a in tt.assignments:
        le = lecciones[a.lesson_number]
        linea = le.lines[a.line]
        if linea.teacher is None or is_duty(le):
            continue
        p = grids[le.time_grid].period(a.period)
        assert p is not None
        por_profe[linea.teacher].append((a.day, p.start, p.end, a.lesson_number))

    choques: set[tuple[str, frozenset[int]]] = set()
    for profe, xs in por_profe.items():
        xs.sort()
        for i, (d1, _s1, e1, n1) in enumerate(xs):
            for d2, s2, _e2, n2 in xs[i + 1 :]:
                if d2 != d1:
                    break
                if s2 >= e1:
                    continue
                if n1 != n2:
                    choques.add((profe, frozenset({n1, n2})))
    return choques


_CAPACITY = re.compile(r"El recurso '(?P<res>.+)' aloja \d+ tareas a la vez")


# --------------------------------------------------------------------------- #
# Reloj
# --------------------------------------------------------------------------- #


def test_reloj_ida_y_vuelta() -> None:
    c = Clock(days=(1, 2, 4), day_start=420, day_end=1100)
    assert c.day_length == 680
    assert c.horizon == 680 * 3
    for dia in (1, 2, 4):
        for minuto in (420, 700, 1099):
            assert c.decode(c.slot(dia, minuto)) == (dia, minuto)
    with pytest.raises(ValueError):
        c.slot(1, 1100)
    with pytest.raises(ValueError):
        Clock(days=(), day_start=0, day_end=10)


def test_reloj_une_todas_las_rejillas() -> None:
    a, b = _two_grids()
    c = Clock.of((a, b))
    assert (c.day_start, c.day_end, c.days) == (480, 595, (1, 2))


# --------------------------------------------------------------------------- #
# Traducción sintética
# --------------------------------------------------------------------------- #


def test_traduce_acoples_como_una_tarea_por_sesion() -> None:
    tr = translate(_mini())
    # lección 1: 2 sesiones; lección 2 (acople): 1; lección 3 (obligación): fuera.
    assert sorted(tr.task_of) == [SessionRef(1, 0), SessionRef(1, 1), SessionRef(2, 0)]
    assert tr.duties == (3,)
    acople = tr.problem.task_by_id(tr.task_of[SessionRef(2, 0)])  # type: ignore[arg-type]
    tags = {r.tag for r in acople.requirements}
    assert {"teacher#T2", "teacher#T3", "group#C2"} <= tags
    assert "ING · C2" in acople.name


def test_dominio_respeta_la_rejilla_y_la_duracion() -> None:
    tr = translate(_mini())
    tarea = tr.problem.task_by_id(tr.task_of[SessionRef(1, 0)])  # type: ignore[arg-type]
    inicios = {tr.clock.decode(int(s)) for s in tarea.allowed_starts or ()}
    # Rejilla A, 45 min: períodos 1 y 2 (el 3 dura 10 min) en los días 1 y 2.
    assert inicios == {(1, 480), (1, 530), (2, 480), (2, 530)}
    assert tarea.duration == 45


def test_incluir_obligaciones() -> None:
    tr = UntisTranslator(include_duties=True).translate(_mini())
    assert SessionRef(3, 0) in tr.task_of
    assert tr.duties == (3,)


def test_optimizacion_de_profesores_es_opt_in() -> None:
    abierta = Lesson(
        number=9,
        lines=(
            LessonLine(subject="MAT", teacher="T1", classes=("C1",)),
            LessonLine(subject="MAT", teacher=None, classes=("C1",)),
        ),
        periods_per_week=1,
        time_grid="A",
    )
    proyecto = _mini(lessons=(*_mini().lessons, abierta))

    sin = translate(proyecto)
    tarea = sin.problem.task_by_id(sin.task_of[SessionRef(9, 0)])  # type: ignore[arg-type]
    assert not any(r.tag.startswith("teacherpool#") for r in tarea.requirements)

    con = UntisTranslator(optimize_teachers=True).translate(proyecto)
    tarea = con.problem.task_by_id(con.task_of[SessionRef(9, 0)])  # type: ignore[arg-type]
    pool = [r for r in tarea.requirements if r.tag == "teacherpool#MAT"]
    # T1 es fijo y también enseña MAT: la cantidad lo incluye (1 fijo + 1 hueco).
    assert [r.quantity for r in pool] == [2]


def test_pool_de_aulas_sigue_la_cadena_de_alternativas() -> None:
    tr = translate(_mini())
    r3 = tr.problem.resource_by_id(tr.rid_of[(ResourceKind.ROOM, "R3")])  # type: ignore[arg-type]
    # R2 es aula de ING y encadena con R3: R3 entra en el pool de ING.
    assert "roompool#ING" in r3.tags
    r1 = tr.problem.resource_by_id(tr.rid_of[(ResourceKind.ROOM, "R1")])  # type: ignore[arg-type]
    assert r1.attribute("seats") == 30


def test_ida_y_vuelta_sintetica_y_choque_entre_rejillas() -> None:
    """T1 en A 08:00-08:45 y en B 08:20-09:05 chocan aunque el nº de período difiera."""
    choque = Lesson(
        number=5,
        lines=(LessonLine(subject="MAT", teacher="T1", classes=("C2",)),),
        periods_per_week=1,
        time_grid="B",
    )
    tt = Timetable(
        id="ref",
        assignments=(
            Assignment(1, 0, 1, 1, room="R1"),
            Assignment(1, 0, 2, 2, room="R1"),
            Assignment(2, 0, 1, 2, room="R2"),
            Assignment(2, 1, 1, 2),
            Assignment(5, 0, 1, 1),  # B p1 = 08:20-09:05, solapa con A p1 08:00-08:45
        ),
    )
    proyecto = _mini(lessons=(*_mini().lessons, choque), timetables=(tt,))
    tr = translate(proyecto)
    rb = timetable_to_solution(tr, tt)
    assert rb.unplaced == () and rb.mismatched == ()

    informe = ValidationEngine().validate(tr.problem, rb.solution)
    recursos = {m["res"] for i in informe.issues if (m := _CAPACITY.match(i.message))}
    assert recursos == {"T1"}

    vuelta = solution_to_timetable(tr, rb.solution, timetable_id="ref", reference=tt)
    assert set(vuelta.assignments) == set(tt.assignments)


def test_solucion_con_inicio_fuera_de_rejilla_falla() -> None:
    from scheduling_platform.core import Assignment as CA
    from scheduling_platform.core import ResourceId, Solution, TaskId, TimeSlotIndex

    tr = translate(_mini())
    tid = tr.task_of[SessionRef(1, 0)]
    mala = Solution(
        assignments=(CA(TaskId(tid), TimeSlotIndex(tr.clock.slot(1, 481)), (ResourceId(0),)),),
        objective_value=0,
    )
    with pytest.raises(ValueError, match="no es inicio"):
        solution_to_timetable(tr, mala, timetable_id="x")


# --------------------------------------------------------------------------- #
# Datos reales (export seudonimizado)
# --------------------------------------------------------------------------- #


def test_real_traduce_todo_lo_lectivo(anon: UntisProject) -> None:
    tr = translate(anon)
    assert tr.untranslatable == ()
    lectivas = [le for le in anon.active_lessons if not is_duty(le) and le.periods_per_week]
    assert len(tr.duties) + len(lectivas) == len(
        [le for le in anon.active_lessons if le.periods_per_week]
    )
    # Toda sesión lectiva se traduce, esté colocada o no en el horario de Untis.
    assert len(tr.task_of) == sum(le.periods_per_week for le in lectivas)


def test_real_horario_untis_se_reconstruye_completo(anon: UntisProject) -> None:
    tr = translate(anon)
    rb = timetable_to_solution(tr, anon.timetables[0])
    assert rb.mismatched == ()
    assert len(rb.not_translated) == len(tr.duties)
    assert len(rb.solution.assignments) + len(rb.unplaced) == len(tr.task_of)


def test_real_validacion_sin_falsos_positivos(anon: UntisProject) -> None:
    """Criterio R2: el juez ve exactamente los choques reales, ni uno más."""
    tr = translate(anon)
    rb = timetable_to_solution(tr, anon.timetables[0])
    informe = ValidationEngine().validate(tr.problem, rb.solution)

    tipos = {i.kind for i in informe.issues}
    assert tipos <= {"capacity_exceeded"}, "solo choques de capacidad, nada estructural"

    nombre_de = {t.display_name: t.id for t in anon.teachers}
    motor = {
        nombre_de[m["res"]]
        for i in informe.issues
        if (m := _CAPACITY.match(i.message)) and m["res"] in nombre_de
    }
    reloj = _wall_clock_collisions(anon)
    assert motor == {profe for profe, _ in reloj}
    assert len(reloj) == 7


def test_real_ida_y_vuelta_del_horario(anon: UntisProject) -> None:
    tr = translate(anon)
    ref = anon.timetables[0]
    rb = timetable_to_solution(tr, ref)
    vuelta = solution_to_timetable(tr, rb.solution, timetable_id=ref.id, reference=ref)
    traducidas = {r.lesson for r in tr.task_of}
    esperado = {a for a in ref.assignments if a.lesson_number in traducidas}
    assert set(vuelta.assignments) == esperado


def test_real_mismas_lecciones_que_los_datos(real_xml_paths: list[Path]) -> None:
    for path in real_xml_paths:
        proyecto = read_xml(path)
        tr = translate(proyecto)
        rb = timetable_to_solution(tr, proyecto.timetables[0])
        assert rb.mismatched == ()
        informe = ValidationEngine().validate(tr.problem, rb.solution)
        assert {i.kind for i in informe.issues} <= {"capacity_exceeded"}


def test_deseo_menos_tres_recorta_el_dominio() -> None:
    from scheduling_platform.untis_model import EntityKind, TimeRequest

    veto = (
        TimeRequest(EntityKind.TEACHER, "T1", -3, day=1, period=1),
        TimeRequest(EntityKind.CLASS, "C1", -3, day=2),  # día completo
        TimeRequest(EntityKind.TEACHER, "T1", -2, day=1, period=2),  # blando: no recorta
    )
    tr = translate(_mini(time_requests=veto))
    tarea = tr.problem.task_by_id(tr.task_of[SessionRef(1, 0)])  # type: ignore[arg-type]
    inicios = {tr.clock.decode(int(s)) for s in tarea.allowed_starts or ()}
    # Rejilla A, 45 min = p1 (480) y p2 (530); sin (1, p1) ni el día 2 entero.
    assert inicios == {(1, 530)}


def test_leccion_fijada_queda_en_su_celda() -> None:
    fija = Lesson(
        number=1,
        lines=(LessonLine(subject="MAT", teacher="T1", classes=("C1",)),),
        periods_per_week=2,
        time_grid="A",
        fixed=True,
    )
    tt = Timetable(id="ref", assignments=(Assignment(1, 0, 1, 2), Assignment(1, 0, 2, 1)))
    tr = translate(_mini(lessons=(fija,), timetables=(tt,)))
    dominios = [
        {tr.clock.decode(int(s)) for s in tr.problem.task_by_id(tid).allowed_starts or ()}  # type: ignore[arg-type]
        for tid in tr.tasks_of_lesson(1)
    ]
    assert dominios == [{(1, 530)}, {(2, 480)}]
