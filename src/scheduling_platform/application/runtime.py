"""Puente entre la configuración del proyecto y el motor (casos de uso).

Traduce el ``.schedule`` (problema + config) a las piezas que el
``SchedulingEngine`` necesita, ejecuta el motor y **mapea el resultado a los
errores de aplicación** (y, por tanto, a los exit codes): infactible -> exit 2,
sin solución en el tiempo dado -> exit 3. Garantiza además que el no-solape
estructural esté siempre activo (un horario sin él permitiría choques).
"""

from __future__ import annotations

from ..core.problem import SchedulingProblem
from ..engine import EngineResult, SchedulingEngine
from ..pipeline import OptimizationPipeline
from ..pipeline.issues import ConflictReport
from ..plugins import PluginRegistry, registry_with
from ..plugins.catalog.structural import IntervalNoOverlapPlugin, ResourceNoOverlapPlugin
from ..sal.interface import SolverStatus
from .config import EngineConfig
from .config.plugins_config import PluginsConfig
from .errors import ConfigError, InfeasibleError, InternalError, SolveTimeoutError
from .project import BjsProject

_INTERVAL = "interval_no_overlap"
_RESOURCE = "resource_no_overlap"


def engine_config_of(project: BjsProject) -> EngineConfig:
    return project.solver_config


def plugins_config_of(project: BjsProject) -> PluginsConfig:
    return project.constraints


def build_registry(
    plugins_cfg: PluginsConfig, *, structural_only: bool = False, mip: bool = False
) -> tuple[PluginRegistry, bool]:
    """Registro + ``boolean_starts`` requerido para resolver.

    Siempre incluye el no-solape estructural. Los backends MILP (``mip=True``) no
    tienen intervalos nativos, así que usan la formulación **booleana** del
    no-solape (``ResourceNoOverlapPlugin``, que exige ``boolean_starts=True``);
    CP-SAT usa la compacta con intervalos.
    """
    structural = ResourceNoOverlapPlugin() if mip else IntervalNoOverlapPlugin()
    boolean = mip or plugins_cfg.requires_boolean_starts()
    if structural_only or not any(s.enabled for s in plugins_cfg.plugins):
        return registry_with([structural]), boolean
    if mip and _INTERVAL in {s.id for s in plugins_cfg.plugins if s.enabled}:
        raise ConfigError(
            "un backend MILP no admite 'interval_no_overlap'; usa 'resource_no_overlap'"
        )
    registry = plugins_cfg.build_registry()
    if _INTERVAL not in registry.names() and _RESOURCE not in registry.names():
        registry.register(structural)
    return registry, boolean


def analyze_feasibility(problem: SchedulingProblem) -> ConflictReport:
    """Análisis de factibilidad pre-solver (rápido, independiente del solver)."""
    return OptimizationPipeline().analyze(problem)


def run_engine(
    problem: SchedulingProblem,
    registry: PluginRegistry,
    *,
    solver_factory: object,
    solver_config: object,
    boolean_starts: bool,
    warm_start: object = None,
    on_event: object = None,
) -> EngineResult:
    """Ejecuta el motor y traduce el fracaso a un error de aplicación (exit code)."""
    engine = SchedulingEngine(
        registry=registry,
        solver_factory=solver_factory,  # type: ignore[arg-type]
        boolean_starts=boolean_starts,
    )
    result = engine.solve(
        problem,
        solver_config,  # type: ignore[arg-type]
        warm_start=warm_start,  # type: ignore[arg-type]
        on_event=on_event,  # type: ignore[arg-type]
    )
    if result.solved:
        return result
    if result.report is not None and not result.report.feasible:
        raise InfeasibleError(result.report.render())
    if result.status is SolverStatus.INFEASIBLE:
        raise InfeasibleError("el solver determinó que el modelo es infactible")
    if result.solution is None:
        raise SolveTimeoutError("no se encontró una solución factible en el tiempo dado")
    raise InternalError("se obtuvo una solución pero no superó la validación independiente")
