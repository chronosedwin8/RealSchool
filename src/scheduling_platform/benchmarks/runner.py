"""Benchmark Runner: ejecuta el motor sobre un dataset y recoge evidencia.

Registra latencia por etapa, tamaño del modelo, memoria pico y calidad del
horario. El resultado es serializable a JSON para almacenarlo y comparar
versiones.
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
from .datasets import DatasetSpec, build_academic


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    """Evidencia cuantitativa de una ejecución."""

    dataset: str
    tasks: int
    resources: int
    horizon: int

    t_adaptation_ms: float
    t_build_model_ms: float
    t_lower_ms: float
    t_passes_ms: float
    t_compile_ms: float
    t_solve_ms: float
    t_total_ms: float

    num_variables: int
    num_constraints: int
    constraints_eliminated: int
    ram_peak_mb: float

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
                f"Tamaño:      {self.tasks} clases, {self.resources} recursos, "
                f"horizonte {self.horizon}",
                f"Modelo:      {self.num_variables} variables, "
                f"{self.num_constraints} restricciones "
                f"({self.constraints_eliminated} eliminadas por los pases)",
                f"Adaptación:  {self.t_adaptation_ms:.0f} ms",
                f"Construir:   {self.t_build_model_ms:.0f} ms",
                f"Lowering:    {self.t_lower_ms:.0f} ms",
                f"Pases:       {self.t_passes_ms:.0f} ms",
                f"Compilar:    {self.t_compile_ms:.0f} ms",
                f"Búsqueda:    {self.t_solve_ms:.0f} ms",
                f"TOTAL:       {self.t_total_ms:.0f} ms",
                f"RAM pico:    {self.ram_peak_mb:.0f} MB",
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
        result: EngineResult = engine.solve(problem, config)
        t_engine = (time.perf_counter() - stage) * 1000

        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        telemetry = result.telemetry
        metrics = (
            self.metrics.compute(problem, result.solution) if result.solution is not None else None
        )

        # el tiempo de construir el modelo es lo que el motor gasta antes del pipeline
        t_pipeline = telemetry.t_total_ms if telemetry else 0.0
        return BenchmarkRun(
            dataset=spec.name,
            tasks=len(problem.tasks),
            resources=len(problem.resources),
            horizon=problem.horizon,
            t_adaptation_ms=t_adaptation,
            t_build_model_ms=max(0.0, t_engine - t_pipeline),
            t_lower_ms=telemetry.t_lower_ms if telemetry else 0.0,
            t_passes_ms=telemetry.t_passes_ms if telemetry else 0.0,
            t_compile_ms=telemetry.t_compile_ms if telemetry else 0.0,
            t_solve_ms=telemetry.t_solve_ms if telemetry else 0.0,
            t_total_ms=(time.perf_counter() - total_start) * 1000,
            num_variables=telemetry.num_variables if telemetry else 0,
            num_constraints=telemetry.num_constraints if telemetry else 0,
            constraints_eliminated=telemetry.constraints_eliminated if telemetry else 0,
            ram_peak_mb=peak / (1024 * 1024),
            status=result.status.value if result.status else "detenido-pre-solver",
            solved=result.solved,
            hard_violations=metrics.hard_violations if metrics else -1,
            quality_score=metrics.quality_score if metrics else 0.0,
            objective_value=result.solution.objective_value if result.solution else -1,
        )
