"""Formato de proyecto unificado ``.schedule`` (Fase 2, H2).

Un ``.schedule`` es un **archivo ZIP** (al estilo de los documentos ofimáticos
modernos) que empaqueta todo el conocimiento de un proyecto escolar sin
fragmentación:

    project.json     metadatos (UUID, nombre, fecha, versión del motor)
    problem.json     problema del dominio canónico serializado
    config.yaml      pesos/solvers/flags (tipado fuerte en H3)
    solution.json    último horario generado (si existe)
    benchmarks/*.json  trazas históricas de telemetría local

Reutiliza los codecs de dominio ya existentes (``serialization/codec.py``): no se
reimplementa la serialización del problema ni de la solución. La escritura es
**atómica** (archivo temporal + ``os.replace``): un corte de energía no puede
corromper el proyecto original.
"""

from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml

from ..core.problem import SchedulingProblem
from ..core.solution import Solution
from ..serialization.codec import (
    problem_from_dict,
    problem_to_dict,
    solution_from_dict,
    solution_to_dict,
)
from .errors import ConfigError, InternalError

_PROJECT = "project.json"
_PROBLEM = "problem.json"
_CONFIG = "config.yaml"
_SOLUTION = "solution.json"
_BENCH_PREFIX = "benchmarks/"


def engine_version() -> str:
    try:
        return metadata.version("scheduling-platform")
    except metadata.PackageNotFoundError:  # pragma: no cover - sin instalar
        return "0.0.0"


@dataclass(frozen=True, slots=True)
class ScheduleProject:
    """Proyecto completo contenido en un ``.schedule``."""

    metadata: dict[str, Any]
    problem: SchedulingProblem
    config: dict[str, Any] = field(default_factory=dict)
    solution: Solution | None = None
    benchmarks: tuple[dict[str, Any], ...] = ()

    @classmethod
    def create(
        cls,
        name: str,
        problem: SchedulingProblem,
        *,
        config: dict[str, Any] | None = None,
    ) -> ScheduleProject:
        """Crea un proyecto nuevo con metadatos frescos (UUID, fecha, versión)."""
        meta = {
            "uuid": str(uuid.uuid4()),
            "name": name,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "engine_version": engine_version(),
        }
        return cls(metadata=meta, problem=problem, config=config or {})


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _to_zip_bytes(project: ScheduleProject) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_PROJECT, _dumps(project.metadata))
        archive.writestr(_PROBLEM, _dumps(problem_to_dict(project.problem)))
        archive.writestr(
            _CONFIG, yaml.safe_dump(project.config, sort_keys=False, allow_unicode=True)
        )
        if project.solution is not None:
            archive.writestr(_SOLUTION, _dumps(solution_to_dict(project.solution)))
        for i, trace in enumerate(project.benchmarks):
            archive.writestr(f"{_BENCH_PREFIX}{i:03d}.json", _dumps(trace))
    return buffer.getvalue()


def save_project(path: str | Path, project: ScheduleProject) -> None:
    """Escribe el proyecto como ``.schedule`` de forma **atómica**.

    Se serializa a un temporal en el mismo directorio y se renombra con
    ``os.replace`` (atómico dentro del mismo volumen), de modo que el archivo
    original nunca queda a medio escribir ante un fallo.
    """
    target = Path(path)
    data = _to_zip_bytes(project)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    except OSError as exc:  # pragma: no cover - E/S del sistema
        tmp.unlink(missing_ok=True)
        raise InternalError(f"no se pudo escribir {target}: {exc}") from exc


def open_project(path: str | Path) -> ScheduleProject:
    """Abre un ``.schedule`` **en memoria** y lo deserializa al modelo canónico."""
    target = Path(path)
    if not target.exists():
        raise ConfigError(f"no existe el proyecto: {target}")
    try:
        data = target.read_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if _PROJECT not in names or _PROBLEM not in names:
                raise ConfigError(f"{target} no es un .schedule válido (faltan piezas)")
            meta = json.loads(archive.read(_PROJECT))
            problem = problem_from_dict(json.loads(archive.read(_PROBLEM)))
            config = yaml.safe_load(archive.read(_CONFIG)) if _CONFIG in names else {}
            solution = (
                solution_from_dict(json.loads(archive.read(_SOLUTION)))
                if _SOLUTION in names
                else None
            )
            benchmarks = tuple(
                json.loads(archive.read(n))
                for n in sorted(names)
                if n.startswith(_BENCH_PREFIX) and n.endswith(".json")
            )
    except zipfile.BadZipFile as exc:
        raise ConfigError(f"{target} no es un archivo .schedule válido: {exc}") from exc
    return ScheduleProject(
        metadata=meta,
        problem=problem,
        config=config or {},
        solution=solution,
        benchmarks=benchmarks,
    )


def new_project(
    path: str | Path,
    name: str,
    problem: SchedulingProblem,
    *,
    config: dict[str, Any] | None = None,
) -> ScheduleProject:
    """Crea y persiste un proyecto ``.schedule`` nuevo. Devuelve el proyecto."""
    project = ScheduleProject.create(name, problem, config=config)
    save_project(path, project)
    return project
