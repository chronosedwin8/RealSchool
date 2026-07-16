"""Benchmark Runner: ejecuta el motor sobre un dataset y recoge evidencia.

Registra, para una ejecución (Actividad 3): latencia por etapa, composición del
modelo (variables por tipo, intervalos), recursos (RAM pico/promedio y CPU vía
:class:`ResourceMonitor`), calidad del horario y ratios de escalabilidad
(tiempo por docente/grupo/clase/variable). El resultado es serializable a JSON.
"""

from __future__ import annotations

import time
import tracemalloc
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ..academic import AcademicToCanonicalAdapter
from ..engine import EngineResult, MetricsEngine, SchedulingEngine, SolverFactory
from ..plugins.base import SchedulingPlugin
from ..plugins.catalog.structural import IntervalNoOverlapPlugin
from ..plugins.registry import registry_with
from ..sal.interface import SolverConfig
from ..serialization.formats import solution_to_json
from .datasets import DatasetSpec, build_academic
from .resource_monitor import ResourceMonitor


def _ratio(total_ms: float, count: int) -> float:
    return total_ms / count if count else 0.0


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    """Evidencia cuantitativa de una ejecución."""

    dataset: str
    tasks: int
    resources: int
    horizon: int
    teachers: int
    groups: int

    # Rendimiento (ms)
    t_adaptation_ms: float
    t_build_model_ms: float
    t_lower_ms: float
    t_passes_ms: float
    t_compile_ms: float
    t_solve_ms: float
    t_export_ms: float
    t_total_ms: float

    # Complejidad del modelo
    num_variables: int
    num_bool_vars: int
    num_int_vars: int
    num_continuous_vars: int
    num_intervals: int
    num_constraints: int
    constraints_eliminated: int
    num_branches: int
    num_conflicts: int
    threads: int

    # Recursos
    ram_peak_mb: float
    ram_avg_mb: float
    cpu_avg_pct: float
    cpu_max_pct: float

    # Escalabilidad (ms por unidad)
    ms_per_teacher: float
    ms_per_group: float
    ms_per_class: float
    ms_per_variable: float

    # Calidad
    status: str
    solved: bool
    hard_violations: int
    quality_score: float
    objective_value: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        return "\n".join(
            [
                f"== {self.dataset} ==",
                f"Tamaño:      {self.tasks} clases, {self.resources} recursos "
                f"({self.teachers} docentes, {self.groups} grupos), horizonte {self.horizon}",
                f"Modelo:      {self.num_variables} variables "
                f"({self.num_bool_vars} bool, {self.num_int_vars} int, "
                f"{self.num_intervals} intervalos), {self.num_constraints} restricciones "
                f"({self.constraints_eliminated} eliminadas por los pases)",
                f"Búsqueda:    {self.num_branches} ramas, {self.num_conflicts} conflictos, "
                f"{self.threads} hilos",
                f"Adaptación:  {self.t_adaptation_ms:.0f} ms",
                f"Construir:   {self.t_build_model_ms:.0f} ms",
                f"Lowering:    {self.t_lower_ms:.0f} ms",
                f"Pases:       {self.t_passes_ms:.0f} ms",
                f"Compilar:    {self.t_compile_ms:.0f} ms",
                f"Búsqueda:    {self.t_solve_ms:.0f} ms",
                f"Exportar:    {self.t_export_ms:.0f} ms",
                f"TOTAL:       {self.t_total_ms:.0f} ms",
                f"RAM:         {self.ram_peak_mb:.0f} MB pico / {self.ram_avg_mb:.0f} MB media",
                f"CPU:         {self.cpu_avg_pct:.0f}% media / {self.cpu_max_pct:.0f}% máx",
                f"Escala:      {self.ms_per_class:.2f} ms/clase, "
                f"{self.ms_per_variable:.3f} ms/variable",
                f"Resultado:   {self.status} (válido: {self.solved})",
                f"Calidad:     {self.quality_score:.1f}/100 "
                f"(violaciones duras: {self.hard_violations})",
            ]
        )


@dataclass(frozen=True, slots=True)
class BenchmarkRunner:
    """Ejecuta el motor sobre datasets sintéticos y mide."""

    solver_factory: SolverFactory
    plugins: Sequence[SchedulingPlugin] = field(
        default_factory=lambda: (IntervalNoOverlapPlugin(),)
    )
    metrics: MetricsEngine = field(default_factory=MetricsEngine)
    boolean_starts: bool = False
    """Por defecto, modelo compacto: los plugins por defecto no necesitan las
    booleanas de inicio, así que se omiten (modelo mucho más pequeño)."""

    def run(self, spec: DatasetSpec, config: SolverConfig | None = None) -> BenchmarkRun:
        tracemalloc.start()
        total_start = time.perf_counter()

        stage = time.perf_counter()
        academic = build_academic(spec)
        translation = AcademicToCanonicalAdapter().translate(academic)
        problem = translation.problem
        t_adaptation = (time.perf_counter() - stage) * 1000

        engine = SchedulingEngine(
            registry=registry_with(list(self.plugins)),
            solver_factory=self.solver_factory,
            boolean_starts=self.boolean_starts,
        )

        stage = time.perf_counter()
        with ResourceMonitor() as monitor:
            result: EngineResult = engine.solve(problem, config)
        t_engine = (time.perf_counter() - stage) * 1000

        stage = time.perf_counter()
        if result.solution is not None:
            solution_to_json(result.solution, indent=None)  # exportación real (medible)
        t_export = (time.perf_counter() - stage) * 1000

        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        telemetry = result.telemetry
        metrics = (
            self.metrics.compute(problem, result.solution) if result.solution is not None else None
        )

        teachers = sum(1 for r in problem.resources if "teacher" in r.tags)
        groups = sum(1 for r in problem.resources if "group" in r.tags)
        num_vars = telemetry.num_variables if telemetry else 0
        t_pipeline = telemetry.t_total_ms if telemetry else 0.0
        t_total = (time.perf_counter() - total_start) * 1000

        return BenchmarkRun(
            dataset=spec.name,
            tasks=len(problem.tasks),
            resources=len(problem.resources),
            horizon=problem.horizon,
            teachers=teachers,
            groups=groups,
            t_adaptation_ms=t_adaptation,
            t_build_model_ms=max(0.0, t_engine - t_pipeline),
            t_lower_ms=telemetry.t_lower_ms if telemetry else 0.0,
            t_passes_ms=telemetry.t_passes_ms if telemetry else 0.0,
            t_compile_ms=telemetry.t_compile_ms if telemetry else 0.0,
            t_solve_ms=telemetry.t_solve_ms if telemetry else 0.0,
            t_export_ms=t_export,
            t_total_ms=t_total,
            num_variables=num_vars,
            num_bool_vars=telemetry.num_bool_vars if telemetry else 0,
            num_int_vars=telemetry.num_int_vars if telemetry else 0,
            num_continuous_vars=telemetry.num_continuous_vars if telemetry else 0,
            num_intervals=telemetry.num_intervals if telemetry else 0,
            num_constraints=telemetry.num_constraints if telemetry else 0,
            constraints_eliminated=telemetry.constraints_eliminated if telemetry else 0,
            num_branches=telemetry.num_branches if telemetry else 0,
            num_conflicts=telemetry.num_conflicts if telemetry else 0,
            threads=telemetry.threads if telemetry else 0,
            ram_peak_mb=max(peak / (1024 * 1024), monitor.ram_peak_mb),
            ram_avg_mb=monitor.ram_avg_mb,
            cpu_avg_pct=monitor.cpu_avg_pct,
            cpu_max_pct=monitor.cpu_max_pct,
            ms_per_teacher=_ratio(t_total, teachers),
            ms_per_group=_ratio(t_total, groups),
            ms_per_class=_ratio(t_total, len(problem.tasks)),
            ms_per_variable=_ratio(t_total, num_vars),
            status=result.status.value if result.status else "detenido-pre-solver",
            solved=result.solved,
            hard_violations=metrics.hard_violations if metrics else -1,
            quality_score=metrics.quality_score if metrics else 0.0,
            objective_value=result.solution.objective_value if result.solution else -1,
        )
