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
_LUNCH = "lunch.json"
_SUBJECTS = "subjects.json"
_DIRECTORY = "directory.json"
_SCHOOLWEEKS = "schoolweeks.json"

#: Disponibilidad: recurso -> tupla de (día, período) BLOQUEADOS (Fase 7 E1).
Availability = dict[int, tuple[tuple[int, int], ...]]


@dataclass(frozen=True, slots=True)
class LunchWindow:
    """Ventana de almuerzo (Fase 7 E2): un rango de períodos donde cada docente

    debe tener **al menos una hora libre** para almorzar, en los días indicados.
    El motor elige qué período queda libre (no es fijo). Ejemplo: P4-P7 de lunes a
    viernes.
    """

    start: int  # período inicial dentro del día (0-based, inclusive)
    end: int  # período final (inclusive)
    days: tuple[int, ...]  # índices de día donde aplica


@dataclass(frozen=True, slots=True)
class SchoolPeriod:
    """Horas de reloj de un período dentro de una semana lectiva (presentacional)."""

    start: str = ""  # "07:00"
    end: str = ""  # "07:10"


@dataclass(frozen=True, slots=True)
class SchoolWeek:
    """Semana lectiva (marco horario) de una sección (Fase 7 E3).

    Describe la estructura horaria de una sección (Kinder/Primaria/Bachillerato):
    número de días lectivos, tope de períodos por día, horas de reloj de cada
    período, el corte Mañana/Tarde y los recreos. Las lecciones se **asignan** a
    una semana lectiva (no todas comparten estructura); el motor respeta sus
    recreos y su tope de períodos como horas no disponibles para esas clases. Las
    horas de reloj y el corte Mañana/Tarde son presentacionales (reportes/vista).
    """

    name: str
    days: int = 5  # número de días lectivos semanales
    max_periods: int = 0  # tope de períodos lectivos por día (0 = toda la rejilla)
    first_day: int = 0  # 0 = Lunes (presentacional)
    first_hour: int = 0  # número de la primera hora lectiva (presentacional)
    afternoon_from: int = -1  # primer período de la Tarde (-1 = todo Mañana)
    periods: tuple[SchoolPeriod, ...] = ()  # horas de reloj por número de período
    breaks: tuple[int, ...] = ()  # períodos que son recreo (no lectivos)


def _read_slots(entries: dict[str, Any], fname: str) -> Availability:
    return {
        int(rid): tuple((int(d), int(p)) for d, p in pairs)
        for rid, pairs in entries.get(fname, {}).get("blocked", {}).items()
    }


def _slots_doc(layer: Availability) -> dict[str, Any]:
    return {
        "blocked": {str(rid): [[d, p] for d, p in slots] for rid, slots in layer.items() if slots}
    }


def _read_lunch(entries: dict[str, Any]) -> LunchWindow | None:
    window = entries.get(_LUNCH, {}).get("window")
    if not window:
        return None
    return LunchWindow(
        start=int(window["start"]),
        end=int(window["end"]),
        days=tuple(int(d) for d in window.get("days", ())),
    )


def _read_school_weeks(entries: dict[str, Any]) -> tuple[SchoolWeek, ...]:
    raw = entries.get(_SCHOOLWEEKS, {}).get("weeks", ())
    return tuple(
        SchoolWeek(
            name=str(w["name"]),
            days=int(w.get("days", 5)),
            max_periods=int(w.get("max_periods", 0)),
            first_day=int(w.get("first_day", 0)),
            first_hour=int(w.get("first_hour", 0)),
            afternoon_from=int(w.get("afternoon_from", -1)),
            periods=tuple(
                SchoolPeriod(start=str(p.get("start", "")), end=str(p.get("end", "")))
                for p in w.get("periods", ())
            ),
            breaks=tuple(int(b) for b in w.get("breaks", ())),
        )
        for w in raw
    )


def _school_weeks_doc(weeks: tuple[SchoolWeek, ...]) -> dict[str, Any]:
    return {
        "weeks": [
            {
                "name": w.name,
                "days": w.days,
                "max_periods": w.max_periods,
                "first_day": w.first_day,
                "first_hour": w.first_hour,
                "afternoon_from": w.afternoon_from,
                "periods": [{"start": p.start, "end": p.end} for p in w.periods],
                "breaks": list(w.breaks),
            }
            for w in weeks
        ]
    }


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
    lunch_window: LunchWindow | None = None
    subjects: tuple[str, ...] = ()  # materias registradas (entidad de primera clase)
    # Datos maestros estilo Untis (Fase 7): campos de texto por entidad que no
    # afectan al solver (nombre completo, e-mail, sección, aula propia, color...).
    resource_info: dict[int, dict[str, str]] = field(default_factory=dict)
    subject_info: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Semanas lectivas (marcos horarios por sección, Fase 7 E3). Cada lección se
    #: asigna a una por su índice (atributo ``school_week`` de sus clases).
    school_weeks: tuple[SchoolWeek, ...] = ()

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
        entries[_AVAILABILITY] = _slots_doc(project.availability)
    if project.lunch_window is not None:
        window = project.lunch_window
        entries[_LUNCH] = {
            "window": {"start": window.start, "end": window.end, "days": list(window.days)}
        }
    if project.subjects:
        entries[_SUBJECTS] = {"names": list(project.subjects)}
    if project.resource_info or project.subject_info:
        entries[_DIRECTORY] = {
            "resources": {str(k): dict(v) for k, v in project.resource_info.items() if v},
            "subjects": {k: dict(v) for k, v in project.subject_info.items() if v},
        }
    if project.school_weeks:
        entries[_SCHOOLWEEKS] = _school_weeks_doc(project.school_weeks)
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
    return BjsProject(
        manifest=manifest,
        problem=problem,
        constraints=constraints,
        solver_config=solver_config,
        solution=solution,
        metrics=metrics,
        history=history,
        availability=_read_slots(entries, _AVAILABILITY),
        lunch_window=_read_lunch(entries),
        subjects=tuple(str(n) for n in entries.get(_SUBJECTS, {}).get("names", ())),
        resource_info={
            int(k): {str(a): str(b) for a, b in v.items()}
            for k, v in entries.get(_DIRECTORY, {}).get("resources", {}).items()
        },
        subject_info={
            str(k): {str(a): str(b) for a, b in v.items()}
            for k, v in entries.get(_DIRECTORY, {}).get("subjects", {}).items()
        },
        school_weeks=_read_school_weeks(entries),
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
