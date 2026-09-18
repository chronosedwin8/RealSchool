"""Banco de la heurística (R3): estrategias A y B frente al horario de Untis.

Carga un export XmlInterface (por defecto el seudonimizado de los tests),
deduce los recreos y compara, con la **misma ponderación** (la del proyecto),
el horario publicado por Untis con el que generan las estrategias pedidas:
tiempo, % sin colocar, choques, puntos blandos, número de evaluación y el
desglose de los criterios que más pesan.

Uso::

    .venv/Scripts/python.exe scripts/bench_heuristic.py [--xml RUTA] [--a 60] [--b 300]
        [--seed 0] [--strategies A,B]

Objetivo del documento maestro (sección 7): A < 2 min, B <= 15 min, <= 2 %
sin colocar y B igual o mejor que Untis en el número de evaluación.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from scheduling_platform.heuristic import Progress, Strategy, optimize
from scheduling_platform.interop.xml import read_xml
from scheduling_platform.untis_model import UntisProject
from scheduling_platform.untis_model.breaks import infer_breaks
from scheduling_platform.untis_model.evaluation import Evaluator, Report

DEFAULT_XML = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "untis_anon.xml"


@dataclass(frozen=True, slots=True)
class Row:
    """Una fila de la tabla: un horario evaluado."""

    name: str
    seconds: float | None
    report: Report
    iterations: int = 0


def lective_sessions(project: UntisProject) -> int:
    """Sesiones lectivas (con alumnos) de las lecciones activas."""
    return sum(
        le.periods_per_week
        for le in project.active_lessons
        if any(line.classes or line.student_group for line in le.lines)
    )


def resource_clashes(report: Report) -> int:
    """Choques de profesor, clase o aula (duros de verdad)."""
    return sum(1 for c in report.clashes if c.kind in ("teacher", "class", "room"))


def print_table(rows: list[Row], lectivas: int) -> None:
    cabecera = (
        f"{'horario':<10} {'tiempo':>8} {'sin col.':>9} {'%':>6} {'choques':>8} "
        f"{'blandos':>9} {'total':>9} {'iter/s':>8}"
    )
    print(cabecera)
    print("-" * len(cabecera))
    for r in rows:
        e = r.report.evaluation
        tiempo = f"{r.seconds:7.1f}s" if r.seconds is not None else f"{'-':>8}"
        ritmo = f"{r.iterations / r.seconds:8.0f}" if r.seconds and r.iterations else f"{'-':>8}"
        pct = 100.0 * e.unplaced_periods / max(1, lectivas)
        print(
            f"{r.name:<10} {tiempo} {e.unplaced_periods:>9} {pct:>5.2f}% "
            f"{resource_clashes(r.report):>8} {e.soft_points:>9} {e.total:>9} {ritmo}"
        )


def print_criteria(rows: list[Row], top: int = 10) -> None:
    """Puntos de los criterios que más pesan en alguno de los horarios."""
    criterios: list[str] = []
    for r in rows:
        for s in r.report.evaluation.by_contribution()[:top]:
            if s.points and s.criterion not in criterios:
                criterios.append(s.criterion)
    print()
    cabecera = f"{'criterio (violaciones x peso)':<44}" + "".join(f"{r.name:>14}" for r in rows)
    print(cabecera)
    print("-" * len(cabecera))
    for c in criterios:
        celdas = ""
        for r in rows:
            s = next(x for x in r.report.evaluation.scores if x.criterion == c)
            celdas += f"{f'{s.violations}x{s.weight}={s.points}':>14}"
        print(f"{c:<44}{celdas}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--xml", type=Path, default=DEFAULT_XML)
    parser.add_argument("--a", type=float, default=60.0, help="segundos de la estrategia A")
    parser.add_argument("--b", type=float, default=300.0, help="segundos de la estrategia B")
    parser.add_argument("--d", type=float, default=300.0, help="segundos de la estrategia D")
    parser.add_argument("--e", type=float, default=1800.0, help="segundos de la estrategia E")
    parser.add_argument("--repair", type=float, default=20.0, help="segundos de REPARAR")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--strategies", default="A,B", help="lista separada por comas")
    parser.add_argument("--quiet", action="store_true", help="sin progreso intermedio")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    project = infer_breaks(read_xml(args.xml))
    ev = Evaluator(project)
    lectivas = lective_sessions(project)
    print(
        f"{args.xml.name}: {len(project.active_lessons)} lecciones, {lectivas} sesiones "
        f"lectivas, {len(project.time_grids)} rejillas (carga {time.perf_counter() - t0:.1f}s)"
    )
    filas: list[Row] = []
    if project.timetables:
        filas.append(Row("Untis", None, ev.report(project.timetables[0])))

    tiempos = {"A": args.a, "B": args.b, "D": args.d, "E": args.e, "REPAIR": args.repair}
    for nombre in (x.strip().upper() for x in args.strategies.split(",") if x.strip()):
        estrategia = Strategy.REPAIR if nombre == "REPAIR" else Strategy(nombre)
        ultimo = [0.0]

        def progreso(p: Progress, nombre: str = nombre, ultimo: list[float] = ultimo) -> None:
            if args.quiet or p.elapsed - ultimo[0] < 10.0:
                return
            ultimo[0] = p.elapsed
            print(
                f"  [{nombre}] {p.elapsed:6.1f}s {p.phase:<11} mejor={p.best} "
                f"actual={p.current} sin colocar={p.unplaced}",
                flush=True,
            )

        print(f"\n== Estrategia {nombre}: {tiempos[nombre]:.0f}s", flush=True)
        res = optimize(
            project,
            strategy=estrategia,
            seed=args.seed,
            time_limit=tiempos[nombre],
            on_progress=progreso,
        )
        rep = ev.report(res.timetable)
        if rep.evaluation != res.evaluation:
            print("ERROR: la evaluación devuelta no coincide con el evaluador", file=sys.stderr)
            return 1
        filas.append(Row(nombre, res.elapsed, rep, res.iterations))
        print(f"  reinicios={res.restarts} iteraciones={res.iterations}")

    print()
    print_table(filas, lectivas)
    print_criteria(filas)
    kinds = Counter(c.kind for r in filas[1:] for c in r.report.clashes)
    if kinds:
        print(f"\nChoques en los horarios generados: {dict(kinds)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
