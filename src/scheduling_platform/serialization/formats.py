"""Formatos de intercambio: JSON, YAML y el contenedor propio ``.proschedule``.

- **JSON / YAML**: representación abierta del problema y de la solución, útil
  para integraciones e inspección manual.
- **.proschedule**: contenedor propio *versionado* (JSON comprimido con gzip)
  que guarda el proyecto completo — problema, solución y metadatos — de forma
  que una ejecución limpia reproduzca el mismo horario.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..core.problem import SchedulingProblem
from ..core.solution import Solution
from .codec import Doc, problem_from_dict, problem_to_dict, solution_from_dict, solution_to_dict
from .exceptions import SerializationError, UnsupportedSchemaVersion

FORMAT_NAME = "proschedule"
SCHEMA_VERSION = 1


# --- JSON ---


def problem_to_json(problem: SchedulingProblem, *, indent: int | None = 2) -> str:
    return json.dumps(problem_to_dict(problem), indent=indent, ensure_ascii=False)


def problem_from_json(text: str) -> SchedulingProblem:
    return problem_from_dict(json.loads(text))


def solution_to_json(solution: Solution, *, indent: int | None = 2) -> str:
    return json.dumps(solution_to_dict(solution), indent=indent, ensure_ascii=False)


def solution_from_json(text: str) -> Solution:
    return solution_from_dict(json.loads(text))


# --- YAML ---


def problem_to_yaml(problem: SchedulingProblem) -> str:
    return yaml.safe_dump(problem_to_dict(problem), sort_keys=False, allow_unicode=True)


def problem_from_yaml(text: str) -> SchedulingProblem:
    return problem_from_dict(yaml.safe_load(text))


def solution_to_yaml(solution: Solution) -> str:
    return yaml.safe_dump(solution_to_dict(solution), sort_keys=False, allow_unicode=True)


def solution_from_yaml(text: str) -> Solution:
    return solution_from_dict(yaml.safe_load(text))


# --- contenedor .proschedule ---


@dataclass(frozen=True, slots=True)
class ProSchedule:
    """Proyecto completo: problema, solución (opcional) y metadatos."""

    problem: SchedulingProblem
    solution: Solution | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _to_document(project: ProSchedule) -> Doc:
    return {
        "format": FORMAT_NAME,
        "version": SCHEMA_VERSION,
        "metadata": dict(project.metadata),
        "problem": problem_to_dict(project.problem),
        "solution": None if project.solution is None else solution_to_dict(project.solution),
    }


def _from_document(doc: Doc) -> ProSchedule:
    if doc.get("format") != FORMAT_NAME:
        raise SerializationError(f"no es un documento {FORMAT_NAME}: {doc.get('format')!r}")
    version = int(doc.get("version", 0))
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(
            f"versión de esquema no soportada: {version} (se esperaba {SCHEMA_VERSION})"
        )
    solution_doc = doc.get("solution")
    return ProSchedule(
        problem=problem_from_dict(doc["problem"]),
        solution=None if solution_doc is None else solution_from_dict(solution_doc),
        metadata=dict(doc.get("metadata", {})),
    )


def save_proschedule(path: str | Path, project: ProSchedule) -> None:
    """Escribe el proyecto como ``.proschedule`` (JSON comprimido, versionado)."""
    payload = json.dumps(_to_document(project), ensure_ascii=False).encode("utf-8")
    with gzip.open(Path(path), "wb") as handle:
        handle.write(payload)


def load_proschedule(path: str | Path) -> ProSchedule:
    """Lee un ``.proschedule``, validando el formato y la versión del esquema."""
    with gzip.open(Path(path), "rb") as handle:
        doc = json.loads(handle.read().decode("utf-8"))
    return _from_document(doc)
