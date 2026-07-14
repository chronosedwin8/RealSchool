"""DS-04 Colegio Alemán: importa el export real de Untis y compara.

Uso:
    .venv\\Scripts\\python.exe scripts\\ds04_colegio_aleman.py [ruta_untis.xml] [segundos]

1. Lee el export real de Untis.
2. Lo traduce al Modelo Canónico.
3. Reconstruye **el horario que Untis generó** y lo mide con nuestra vara.
4. Genera **nuestro** horario con el motor.
5. Imprime el Gap Analysis y vuelca un JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scheduling_platform.core import SchedulingProblem
from scheduling_platform.engine import (
    MetricsEngine,
    SchedulingEngine,
    ValidationEngine,
)
from scheduling_platform.plugins import registry_with
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.sal.interface import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver
from scheduling_platform.untis import (
    UntisToCanonicalAdapter,
    parse_untis,
    untis_reference_solution,
)

DEFAULT_XML = r"C:\Users\Colegio Aleman\untis_export\untis.xml"


def _linea(titulo: str) -> None:
    print(f"\n{'=' * 74}\n  {titulo}\n{'=' * 74}")


def _conflictos(report: object) -> list[str]:
    """Agrupa las incidencias por conflicto real.

    El Validation Engine trabaja al minuto: un solape de 45 minutos produce 45
    incidencias. Lo que interesa es *cuántos choques distintos* hay.
    """
    vistos: dict[str, str] = {}
    for issue in report.issues:  # type: ignore[attr-defined]
        if issue.kind != "capacity_exceeded":
            continue
        # "El recurso 'X' aloja 2 tareas a la vez en el período N (...): A, B."
        cabeza, _, cola = issue.message.partition(" en el período ")
        _, _, tareas = cola.partition("): ")
        clave = f"{cabeza}||{tareas}"
        vistos.setdefault(clave, f"{cabeza.replace('El recurso ', '')} -> {tareas}")
    return list(vistos.values())


def main() -> int:
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_XML)
    limite = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0

    if not ruta.exists():
        print(f"No encuentro el export: {ruta}")
        return 1

    _linea("1. EXPORT REAL DE UNTIS")
    export = parse_untis(ruta)
    print(f"  Institución:        {export.school}")
    print(f"  Marco horario:      {export.days} días x {export.periods_per_day} períodos")
    print(f"  Jornadas (timegrids): {len(export.timegrids)} -> {', '.join(export.timegrids)}")
    print(f"  Docentes:           {len(export.teachers)}")
    print(f"  Aulas:              {len(export.rooms)}")
    print(f"  Cursos:             {len(export.classes)}")
    print(f"  Materias:           {len(export.subjects)}")
    print(f"  Lecciones:          {len(export.lessons)}")
    print(f"  Clases a ubicar:    {export.total_periods}  (suma de períodos semanales)")

    _linea("2. HALLAZGO: EL PROPIO HORARIO DE UNTIS SE SOLAPA")
    # Medimos el horario real de Untis DOS veces: contando las obligaciones no
    # lectivas (reuniones, extracurriculares, preparación) como exclusivas, y sin
    # contarlas. La diferencia dice cómo trata Untis esas entradas.
    con_deberes = UntisToCanonicalAdapter(include_duties=True).translate(export)
    ref_con, _ = untis_reference_solution(con_deberes)
    p_con = SchedulingProblem(
        grid=con_deberes.problem.grid,
        resources=con_deberes.problem.resources,
        tasks=tuple(
            t for t in con_deberes.problem.tasks if t.id in {a.task_id for a in ref_con.assignments}
        ),
    )
    v_con = ValidationEngine().validate(p_con, ref_con)
    solapes_con = len(_conflictos(v_con))
    duties = sum(1 for c in con_deberes.couplings if not c.courses)
    print(f"  Obligaciones no lectivas en el export: {duties}")
    print("  (reuniones, extracurriculares, preparación, almuerzos: docente sin curso ni aula)")
    print(f"  Choques de docente en el horario de Untis, contándolas: {solapes_con}")
    print("\n  => Untis NO las trata como exclusivas: su propio horario las solapa con clases.")
    print("     Modelarlas con no-solape estricto sobrerrestringiría el problema, así que se")
    print("     excluyen del modelo (se reportan, no se planifican).")

    _linea("3. TRADUCCIÓN AL MODELO CANÓNICO (solo clases reales)")
    translation = UntisToCanonicalAdapter().translate(export)
    problem = translation.problem
    compartidas = sum(1 for c in translation.couplings if len(c.teachers) > 1)
    multi_curso = sum(1 for c in translation.couplings if len(c.courses) > 1)
    max_profes = max((len(c.teachers) for c in translation.couplings), default=0)
    print(f"  Acoples (clases reales): {len(translation.couplings)}")
    print(f"    - clases compartidas (varios profes en paralelo): {compartidas}")
    print(f"    - que abarcan varios cursos:                      {multi_curso}")
    print(f"    - máximo de profesores en paralelo:               {max_profes}")
    print(f"  Lecciones descartadas (sin recursos): {len(translation.skipped)}")
    if translation.pseudo_classes:
        print(
            f"  Pseudo-cursos (grupos de opción IB, no cursos reales): "
            f"{len(translation.pseudo_classes)} -> {', '.join(translation.pseudo_classes[:6])}"
        )
    print(f"  Tareas canónicas:   {len(problem.tasks)}")
    print(f"  Recursos canónicos: {len(problem.resources)}")
    print(f"  Horizonte:          {problem.horizon} períodos/semana")

    _linea("4. AUDITORÍA DEL HORARIO REAL DE UNTIS")
    referencia, sin_ubicar = untis_reference_solution(translation)
    print(f"  Sesiones ubicadas por Untis: {len(referencia.assignments)} de {len(problem.tasks)}")
    if sin_ubicar:
        print(f"  Sesiones que Untis dejó SIN ubicar: {sin_ubicar}")

    # Para medir a Untis con justicia, se le evalúa sobre el subconjunto que sí
    # ubicó: la sesión que dejó fuera se reporta aparte, no le hunde el score.
    ubicadas = {a.task_id for a in referencia.assignments}
    problema_untis = SchedulingProblem(
        grid=problem.grid,
        resources=problem.resources,
        tasks=tuple(t for t in problem.tasks if t.id in ubicadas),
    )

    validacion = ValidationEngine().validate(problema_untis, referencia)
    metrics = MetricsEngine()
    choques = _conflictos(validacion)
    if not choques:
        print("  Auditoría independiente: SIN choques de recurso.")
    else:
        print(f"  Auditoría independiente: {len(choques)} CHOQUES en el horario real de Untis.")
        print("  (un docente/aula/curso ocupado por dos clases a la vez, en reloj real)")
        for texto in choques[:6]:
            print(f"    - {texto}")
        if len(choques) > 6:
            print(f"    ... y {len(choques) - 6} más")

    _linea("5. NUESTRO MOTOR")
    engine = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin()]),
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )
    config = SolverConfig(max_time_in_seconds=limite, num_search_workers=8, random_seed=1)
    resultado = engine.solve(problem, config)
    telemetria = resultado.telemetry
    assert telemetria is not None

    print(f"  Estado:      {resultado.status.value if resultado.status else 'pre-solver'}")
    print(
        f"  Modelo:      {telemetria.num_variables} variables, "
        f"{telemetria.num_constraints} restricciones"
    )
    print(f"  Construir:   {telemetria.t_lower_ms + telemetria.t_compile_ms:.0f} ms")
    print(f"  Pases CIR:   {telemetria.t_passes_ms:.0f} ms")
    print(f"  Búsqueda:    {telemetria.t_solve_ms / 1000:.1f} s")
    print(f"  TOTAL:       {telemetria.t_total_ms / 1000:.1f} s")

    if not resultado.solved:
        print("\n  No se obtuvo horario válido:")
        print("  " + resultado.report.render().replace("\n", "\n  "))
        return 0

    _linea("6. GAP ANALYSIS — NUESTRO MOTOR vs UNTIS")
    assert resultado.solution is not None
    m_nuestro = metrics.compute(problem, resultado.solution)
    m_untis = metrics.compute(problema_untis, referencia)

    filas = [
        ("Sesiones ubicadas", len(resultado.solution.assignments), len(referencia.assignments)),
        ("Violaciones duras", m_nuestro.hard_violations, m_untis.hard_violations),
        ("Huecos docentes", m_nuestro.teacher_gaps, m_untis.teacher_gaps),
        ("Huecos estudiantes", m_nuestro.group_gaps, m_untis.group_gaps),
    ]
    print(f"  {'Métrica':24s} {'NOSOTROS':>12s} {'UNTIS':>12s}")
    print(f"  {'-' * 24} {'-' * 12} {'-' * 12}")
    for nombre, nuestro, untis in filas:
        print(f"  {nombre:24s} {nuestro:>12} {untis:>12}")
    print(
        f"  {'Uso de aulas':24s} {m_nuestro.room_utilization_pct:>11.1f}% "
        f"{m_untis.room_utilization_pct:>11.1f}%"
    )
    print(
        f"  {'Balance de carga':24s} {m_nuestro.teacher_load_balance_pct:>11.1f}% "
        f"{m_untis.teacher_load_balance_pct:>11.1f}%"
    )
    print(
        f"  {'Calidad (0-100)':24s} {m_nuestro.quality_score:>11.1f}  "
        f"{m_untis.quality_score:>11.1f}"
    )

    salida = {
        "dataset": "DS-04 Colegio Alemán",
        "fuente": str(ruta),
        "escala": {
            "docentes": len(export.teachers),
            "aulas": len(export.rooms),
            "cursos": len(export.classes),
            "clases_a_ubicar": len(problem.tasks),
        },
        "motor": {
            "estado": resultado.status.value if resultado.status else None,
            "variables": telemetria.num_variables,
            "restricciones": telemetria.num_constraints,
            "t_total_s": round(telemetria.t_total_ms / 1000, 1),
            "t_busqueda_s": round(telemetria.t_solve_ms / 1000, 1),
            "sesiones_ubicadas": len(resultado.solution.assignments),
            "violaciones_duras": m_nuestro.hard_violations,
            "huecos_docentes": m_nuestro.teacher_gaps,
            "huecos_estudiantes": m_nuestro.group_gaps,
            "uso_aulas_pct": round(m_nuestro.room_utilization_pct, 1),
            "calidad": round(m_nuestro.quality_score, 1),
        },
        "untis": {
            "sesiones_ubicadas": len(referencia.assignments),
            "sesiones_sin_ubicar": sin_ubicar,
            "violaciones_duras": m_untis.hard_violations,
            "huecos_docentes": m_untis.teacher_gaps,
            "huecos_estudiantes": m_untis.group_gaps,
            "uso_aulas_pct": round(m_untis.room_utilization_pct, 1),
            "calidad": round(m_untis.quality_score, 1),
        },
    }
    destino = Path("benchmarks") / "ds04_gap_analysis.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(salida, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Resultado volcado en: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
