"""Casos de uso de la Capa de Aplicación (patrón Command)."""

from __future__ import annotations

from .base import Command, CommandResult
from .config_validate import ConfigValidateCommand
from .convert import ConvertCommand
from .doctor import DoctorCommand
from .inspect_project import ExplainCommand, ValidateCommand
from .project_ops import (
    ProjectExtractCommand,
    ProjectInfoCommand,
    ProjectPackCommand,
    ProjectValidateCommand,
)
from .solve import GenerateCommand, OptimizeCommand

__all__ = [
    "Command",
    "CommandResult",
    "ConfigValidateCommand",
    "ConvertCommand",
    "DoctorCommand",
    "ExplainCommand",
    "GenerateCommand",
    "OptimizeCommand",
    "ProjectExtractCommand",
    "ProjectInfoCommand",
    "ProjectPackCommand",
    "ProjectValidateCommand",
    "ValidateCommand",
]
