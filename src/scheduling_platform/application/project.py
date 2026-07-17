"""Proyecto tipado ``.bjs`` (Fase 3, B2): interpreta el contenedor crudo.

Sobre el contenedor de ``serialization/bjs.py`` (dicts crudos, Core-safe), esta
capa reconstruye el proyecto **tipado**: el problema canónico (partido en
``calendar``/``resources``/``tasks`` para diffs de Git limpios), la config de
restricciones (``PluginsConfig``) y de solver (``EngineConfig``), la solución, las
métricas y el historial. Aquí sí se conoce la config, por eso vive en
``application`` y no en ``serialization`` (frontera de arquitectura).

Supersede al formato ``.schedule`` de la Fase 2: mismo patrón (escritura atómica,
apertura en memoria) heredado del contenedor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

from ..benchmarks import Provenance
from ..core.problem import SchedulingProblem
from ..core.solution import Solution
from ..serialization.bjs import build_manifest, extract, pack, pack_dir, read
from ..serialization.codec import (
    problem_from_dict,
    problem_to_dict,
    solution_from_dict,
    solution_to_dict,
)
from ..serialization.exceptions import SerializationError
from .config import EngineConfig, PluginsConfig
from .config.load import engine_config_from_mapping, plugins_config_from_list
from .errors import ConfigError

_CALENDAR = "calendar.json"
_RESOURCES = "resources.json"
_TASKS = "tasks.json"
_CONSTRAINTS = "constraints.json"
_SOLVER = "solver_config.json"
_SOLUTION = "solution.json"
_METRICS = "metrics.json"
_HISTORY = "history.json"
_AVAILABILITY = "availability.json"

#: Disponibilidad: recurso -> tupla de (día, período) BLOQUEADOS (Fase 7 E1).
Availability = dict[int, tuple[tuple[int, int], ...]]


def engine_version() -> str:
    try:
        return metadata.version("scheduling-platform")
    except metadata.PackageNotFoundError:  # pragma: no cover - sin instalar
        return "0.0.0"


def _signature() -> dict[str, Any]:
    prov = Provenance.capture()
    return {
        "engine_version": engine_version(),
        "git_commit": prov.git_commit,
        "build_environment": f"{prov.os}-Python{prov.python_version}",
    }


def _split_problem(problem: SchedulingProblem) -> dict[str, Any]:
    doc = problem_to_dict(problem)
    return {
        _CALENDAR: {"grid": doc["grid"], "constraints": doc.get("constraints", [])},
        _RESOURCES: {"resources": doc["resources"]},
        _TASKS: {"tasks": doc["tasks"]},
    }


def _merge_problem(entries: dict[str, Any]) -> SchedulingProblem:
    calendar, resources, tasks = entries[_CALENDAR], entries[_RESOURCES], entries[_TASKS]
    return problem_from_dict(
        {
            "grid": calendar["grid"],
            "constraints": calendar.get("constraints", []),
            "resources": resources["resources"],
            "tasks": tasks["tasks"],
        }
    )


@dataclass(frozen=True, slots=True)
class BjsProject:
    """Proyecto completo contenido en un ``.bjs`` (núcleo canónico)."""

    manifest: dict[str, Any]
    problem: SchedulingProblem
    constraints: PluginsConfig = field(default_factory=lambda: PluginsConfig(()))
    solver_config: EngineConfig = field(default_factory=EngineConfig)
    solution: Solution | None = None
    metrics: dict[str, Any] | None = None
    history: tuple[dict[str, Any], ...] = ()
    availability: Availability = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        name: str,
        problem: SchedulingProblem,
        *,
        constraints: PluginsConfig | None = None,
        solver_config: EngineConfig | None = None,
    ) -> BjsProject:
        return cls(
            manifest=build_manifest(project_name=name, engine_signature=_signature()),
            problem=problem,
            constraints=constraints or PluginsConfig(()),
            solver_config=solver_config or EngineConfig(),
        )


def save_project(path: str | Path, project: BjsProject) -> None:
    """Empaqueta el proyecto como ``.bjs`` de forma atómica (vía el contenedor)."""
    entries = _split_problem(project.problem)
    entries[_CONSTRAINTS] = {"plugins": [asdict(s) for s in project.constraints.plugins]}
    entries[_SOLVER] = asdict(project.solver_config)
    if project.solution is not None:
        entries[_SOLUTION] = solution_to_dict(project.solution)
    if project.metrics is not None:
        entries[_METRICS] = project.metrics
    if project.history:
        entries[_HISTORY] = {"runs": list(project.history)}
    if project.availability:
        entries[_AVAILABILITY] = {
            "blocked": {
                str(rid): [[d, p] for d, p in slots]
                for rid, slots in project.availability.items()
                if slots
            }
        }
    pack(path, entries, project.manifest)


def open_project(path: str | Path) -> BjsProject:
    """Lee un ``.bjs`` (verifica integridad + estructura) y reconstruye el proyecto tipado.

    Cualquier problema de contenedor (ZIP inválido, checksum, versión) se traduce
    a ``ConfigError`` para que la CLI salga con código 1 (no 4), con detalle.
    """
    from .bjs_validation import check_structure

    try:
        manifest, entries = read(path)
    except SerializationError as exc:
        raise ConfigError(str(exc)) from exc
    check_structure(entries)  # fase estructural: errores claros por archivo/campo
    problem = _merge_problem(entries)
    constraints = plugins_config_from_list(entries.get(_CONSTRAINTS, {}).get("plugins", []))
    solver_config = engine_config_from_mapping(entries.get(_SOLVER, {}))
    solution = solution_from_dict(entries[_SOLUTION]) if _SOLUTION in entries else None
    metrics = entries.get(_METRICS)
    history = tuple(entries.get(_HISTORY, {}).get("runs", []))
    availability: Availability = {
        int(rid): tuple((int(d), int(p)) for d, p in pairs)
        for rid, pairs in entries.get(_AVAILABILITY, {}).get("blocked", {}).items()
    }
    return BjsProject(
        manifest=manifest,
        problem=problem,
        constraints=constraints,
        solver_config=solver_config,
        solution=solution,
        metrics=metrics,
        history=history,
        availability=availability,
    )


def new_project(
    path: str | Path,
    name: str,
    problem: SchedulingProblem,
    *,
    constraints: PluginsConfig | None = None,
    solver_config: EngineConfig | None = None,
) -> BjsProject:
    """Crea y persiste un ``.bjs`` nuevo. Devuelve el proyecto."""
    project = BjsProject.create(name, problem, constraints=constraints, solver_config=solver_config)
    save_project(path, project)
    return project


def extract_project(path: str | Path, out_dir: str | Path) -> list[Path]:
    """Descomprime un ``.bjs`` a JSONs git-friendly (errores -> ConfigError)."""
    try:
        return extract(path, out_dir)
    except SerializationError as exc:
        raise ConfigError(str(exc)) from exc


def pack_project(src_dir: str | Path, path: str | Path) -> BjsProject:
    """Re-empaqueta un directorio a ``.bjs`` y **valida** el resultado. Devuelve el proyecto."""
    try:
        pack_dir(src_dir, path)
    except SerializationError as exc:
        raise ConfigError(str(exc)) from exc
    return open_project(path)  # valida estructura + integridad + referencial
