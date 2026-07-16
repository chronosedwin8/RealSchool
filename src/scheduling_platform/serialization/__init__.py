"""Serialización del proyecto (Fase 10).

El motor sigue sin conocer bases de datos ni ficheros: esta capa traduce las
entidades del Modelo Canónico a documentos (JSON, YAML) y al contenedor propio
versionado ``.proschedule``.
"""

from __future__ import annotations

from .bjs import (
    FORMAT_VERSION,
    MANIFEST,
    BjsChecksumError,
    BjsError,
    build_manifest,
    extract,
    pack,
    pack_dir,
    read,
)
from .codec import problem_from_dict, problem_to_dict, solution_from_dict, solution_to_dict
from .exceptions import SerializationError, UnsupportedSchemaVersion
from .formats import (
    FORMAT_NAME,
    SCHEMA_VERSION,
    ProSchedule,
    load_proschedule,
    problem_from_json,
    problem_from_yaml,
    problem_to_json,
    problem_to_yaml,
    save_proschedule,
    solution_from_json,
    solution_from_yaml,
    solution_to_json,
    solution_to_yaml,
)

__all__ = [
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "MANIFEST",
    "SCHEMA_VERSION",
    "BjsChecksumError",
    "BjsError",
    "ProSchedule",
    "SerializationError",
    "UnsupportedSchemaVersion",
    "build_manifest",
    "extract",
    "load_proschedule",
    "pack",
    "pack_dir",
    "problem_from_dict",
    "problem_from_json",
    "problem_from_yaml",
    "problem_to_dict",
    "problem_to_json",
    "problem_to_yaml",
    "read",
    "save_proschedule",
    "solution_from_dict",
    "solution_from_json",
    "solution_from_yaml",
    "solution_to_dict",
    "solution_to_json",
    "solution_to_yaml",
]
