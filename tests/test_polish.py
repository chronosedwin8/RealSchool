"""Pulido CP-SAT por ventanas, plugins Untis del puente y desglose por criterio.

Cada plugin se comprueba resolviendo de verdad con CP-SAT y midiendo el
resultado con el evaluador de referencia, que es el juez del producto.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scheduling_platform.bridge import translate
from scheduling_platform.bridge.plugins import (
    ForbiddenPairsPlugin,
    MinimalChangePlugin,
    OrderedPoolPlugin,
)
from scheduling_platform.bridge.polish import polish
from scheduling_platform.bridge.repair import repair
from scheduling_platform.engine import MetricsEngine, SchedulingEngine
from scheduling_platform.interop.xml import read_xml
from scheduling_platform.plugins import registry_with
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.sal.interface import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver
from scheduling_platform.untis_model import (
    Assignment,
    Lesson,
    LessonLine,
    MinMax,
    PeriodDef,
    Room,
    SchoolClass,
    Subject,
    Teacher,
    TimeGrid,
    Timetable,
    UntisProject,
)
from scheduling_platform.untis_model.breaks import infer_breaks
from scheduling_platform.untis_model.evaluation import Evaluator


def _grid(days: tuple[int, ...] = (1,), periods: int = 4) -> TimeGrid:
    return TimeGrid(
        id="G",
        days=days,
        periods=tuple(
            PeriodDef(n, 480 + (n - 1) * 50, 480 + (n - 1) * 50 + 45) for n in range(1, periods + 1)
        ),
    )


def _proyecto(
    lecciones: tuple[Lesson, ...],
    celdas: dict[int, list[tuple[int, int]]],
    *,
    grid: TimeGrid | None = None,
    **cambios: object,
) -> UntisProject:
    tt = Timetable(
        id="t", assignments=tuple(Assignment(n, 0, d, p) for n, cs in celdas.items() for d, p in cs)
    )
    base: dict[str, object] = {
        "time_grids": (grid or _grid(),),
        "classes": (SchoolClass(id="C1", time_grid="G"), SchoolClass(id="C2", time_grid="G")),
        "teachers": (Teacher(id="T1"), Teacher(id="T2")),
        "subjects": (Subject(id="MAT"), Subject(id="ING")),
        "lessons": lecciones,
        "timetables": (tt,),
    }
    base.update(cambios)
    return UntisProject(**base)  # type: ignore[arg-type]


def _leccion(n: int, *, per: int, profe: str = "T1", clase: str = "C1", **kw: object) -> Lesson:
    return Lesson(
        number=n,
        lines=(LessonLine(subject="MAT", teacher=profe, classes=(clase,)),),
        periods_per_week=per,
        time_grid="G",
        **kw,  # type: ignore[arg-type]
    )


def _viol(p: UntisProject, tt: Timetable, criterio: str) -> int:
    e = Evaluator(p).evaluate(tt)
    return next(s.violations for s in e.scores if s.criterion == criterio)


# --------------------------------------------------------------------------- #
# Pulido de extremo a extremo (plugins PeriodGaps y MinPairs)
# --------------------------------------------------------------------------- #


def test_pulido_cierra_el_hueco_de_la_clase() -> None:
    p = _proyecto((_leccion(1, per=2),), {1: [(1, 1), (1, 3)]})
    assert _viol(p, p.timetables[0], "class_gaps") == 1
    out = polish(p, p.timetables[0], time_limit=20, window_time=5)
    assert out.improved
    assert _viol(p, out.timetable, "class_gaps") == 0
    assert out.after.clashes == 0


def test_pulido_logra_el_doble_pedido() -> None:
    le = _leccion(1, per=2, double_periods=MinMax(1, 1))
    p = _proyecto((le,), {1: [(1, 1), (2, 3)]}, grid=_grid(days=(1, 2)))
    assert _viol(p, p.timetables[0], "subject_double_periods") == 1
    out = polish(p, p.timetables[0], time_limit=20, window_time=5)
    assert _viol(p, out.timetable, "subject_double_periods") == 0


def test_pulido_respeta_lo_congelado_de_otras_clases() -> None:
    # T1 da clase a C2 en p2 (congelado para la ventana de C1): C1 no puede usar p2.
    c1 = _leccion(1, per=2)
    c2 = _leccion(2, per=1, clase="C2")
    p = _proyecto((c1, c2), {1: [(1, 1), (1, 3)], 2: [(1, 2)]})
    out = polish(p, p.timetables[0], time_limit=20, window_time=5)
    assert out.after.clashes == 0
    assert out.after.total <= out.before.total


def test_pulido_nunca_empeora_y_sin_nada_que_mejorar_no_cambia() -> None:
    p = _proyecto((_leccion(1, per=2),), {1: [(1, 1), (1, 2)]})
    out = polish(p, p.timetables[0], time_limit=10, window_time=3)
    assert out.after.total <= out.before.total
    assert not out.improved
    assert out.timetable == p.timetables[0]


def test_pulido_parada_cooperativa() -> None:
    p = _proyecto((_leccion(1, per=2),), {1: [(1, 1), (1, 3)]})
    out = polish(p, p.timetables[0], time_limit=10, should_stop=lambda: True)
    assert out.windows_tried == 0 and out.timetable == p.timetables[0]


# --------------------------------------------------------------------------- #
# Plugins sueltos, resueltos con CP-SAT
# --------------------------------------------------------------------------- #


def _resolver(p: UntisProject, *plugins: object) -> dict[int, int]:
    tr = translate(p)
    motor = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin(), *plugins]),  # type: ignore[list-item]
        solver_factory=ORToolsSolver,
    )
    res = motor.solve(tr.problem, SolverConfig(max_time_in_seconds=10, random_seed=0))
    assert res.solved and res.solution is not None
    return {int(a.task_id): int(a.start) for a in res.solution.assignments}


def test_pares_prohibidos_evitan_el_orden_vetado() -> None:
    p = _proyecto((_leccion(1, per=1), _leccion(2, per=1, profe="T2")), {})
    tr = translate(p)
    a = tr.tasks_of_lesson(1)[0]
    b = tr.tasks_of_lesson(2)[0]
    inicios = sorted(tr.problem.task_by_id(a).allowed_starts or ())  # type: ignore[arg-type]
    # Veta "b antes que a" en todas las combinaciones: a debe ir primero.
    grupo = tuple(((a, int(sa)), (b, int(sb))) for sa in inicios for sb in inicios if sb < sa)
    sol = _resolver(p, ForbiddenPairsPlugin(groups=(grupo,), weight=100))
    assert sol[a] < sol[b]


def test_pool_ordenado_prefiere_el_aula_mas_barata() -> None:
    le = Lesson(
        number=1,
        lines=(LessonLine(subject="MAT", teacher="T1", classes=("C1",), room="R1"),),
        periods_per_week=1,
        time_grid="G",
    )
    p = _proyecto((le,), {}, rooms=(Room(id="R1", alternative_room="R2"), Room(id="R2")))
    tr = translate(p)
    t = tr.tasks_of_lesson(1)[0]
    from scheduling_platform.bridge import ResourceKind

    r1 = tr.rid_of[(ResourceKind.ROOM, "R1")]
    r2 = tr.rid_of[(ResourceKind.ROOM, "R2")]
    motor = SchedulingEngine(
        registry=registry_with(
            [IntervalNoOverlapPlugin(), OrderedPoolPlugin(costs=((t, r1, 5), (t, r2, 0)))]
        ),
        solver_factory=ORToolsSolver,
    )
    res = motor.solve(tr.problem, SolverConfig(max_time_in_seconds=10, random_seed=0))
    assert res.solution is not None
    elegido = {int(r) for r in res.solution.assignments[0].resource_ids}
    assert r2 in elegido and r1 not in elegido


def test_cambio_minimo_prefiere_quedarse() -> None:
    p = _proyecto((_leccion(1, per=1),), {})
    tr = translate(p)
    t = tr.tasks_of_lesson(1)[0]
    inicios = sorted(tr.problem.task_by_id(t).allowed_starts or ())  # type: ignore[arg-type]
    objetivo = int(inicios[-1])
    sol = _resolver(p, MinimalChangePlugin(original=((t, objetivo),), weight=50))
    assert sol[t] == objetivo


# --------------------------------------------------------------------------- #
# Desglose por criterio (extensión del motor, ADR-036)
# --------------------------------------------------------------------------- #


def test_desglose_suma_el_objetivo() -> None:
    p = _proyecto((_leccion(1, per=1),), {})
    tr = translate(p)
    t = tr.tasks_of_lesson(1)[0]
    inicios = sorted(tr.problem.task_by_id(t).allowed_starts or ())  # type: ignore[arg-type]
    # Obliga a moverse (se veta quedarse) para que haya penalización.
    motor = SchedulingEngine(
        registry=registry_with(
            [
                IntervalNoOverlapPlugin(),
                MinimalChangePlugin(original=((t, int(inicios[0])),), weight=7),
            ]
        ),
        solver_factory=ORToolsSolver,
    )
    from dataclasses import replace

    problema = replace(
        tr.problem,
        tasks=tuple(
            replace(x, allowed_starts=frozenset(inicios[1:])) if int(x.id) == t else x
            for x in tr.problem.tasks
        ),
    )
    res = motor.solve(problema, SolverConfig(max_time_in_seconds=10, random_seed=0))
    assert res.solution is not None
    desglose = MetricsEngine().breakdown(res.solution)
    assert desglose.total == res.solution.objective_value
    assert sum(c.points for c in desglose.by_criterion) == desglose.total
    assert desglose.of("no_existe") == 0
    assert "Objetivo total" in desglose.render()


# --------------------------------------------------------------------------- #
# Export real
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def anon(anon_xml_path: Path) -> UntisProject:
    return infer_breaks(read_xml(anon_xml_path))


def test_real_reparar_y_pulir_mejora_a_untis(anon: UntisProject) -> None:
    ev = Evaluator(anon)
    untis = ev.evaluate(anon.timetables[0])
    reparado = repair(anon, anon.timetables[0], time_limit=30, include_unplaced=False)
    out = polish(anon, reparado.timetable, time_limit=20, window_time=4, max_windows=4)
    assert out.after.clashes == 0
    assert out.after.total <= out.before.total
    # Sin choques y con menos puntos blandos que el horario publicado por Untis.
    assert out.after.clashes < untis.clashes
    assert out.after.soft_points < untis.soft_points


def test_real_todas_las_etiquetas_cp_sat_son_criterios(anon: UntisProject) -> None:
    """Contrato de `bridge.objective`: nada que CP-SAT optimice queda sin nombre Untis."""
    from scheduling_platform.bridge.objective import criterion_points, unknown_labels
    from scheduling_platform.bridge.rebuild import timetable_to_solution
    from scheduling_platform.bridge.weighting import CP_CRITERIA, Geometry, window_plugins
    from scheduling_platform.plugins import SchedulingModelContext
    from scheduling_platform.untis_model import Weighting

    tr = translate(anon)
    ev = Evaluator(anon)
    base = timetable_to_solution(tr, anon.timetables[0]).solution
    clase = next(iter(ev.class_grid))
    ventana = {
        tid for ref, tid in tr.task_of.items() if clase in anon.lesson_by_number[ref.lesson].classes
    }
    plugins = window_plugins(tr, Geometry.of(tr), ev, base, ventana, clase, Weighting())
    from scheduling_platform.bridge.repair import _subproblem

    sub, _ = _subproblem(tr.problem, base, ventana)
    ctx = SchedulingModelContext.build(sub)
    etiquetas = {t.label for p in plugins for t in p.contribute(ctx).penalties}
    assert unknown_labels(etiquetas) == set()
    assert set(CP_CRITERIA) <= set(Weighting.criteria())
    assert criterion_points(base) == {}  # una solución reconstruida no trae penalizaciones
