"""Modelo Canónico de Optimización (Fase 1).

Entidades universales del motor: Resource, Task, TimeSlot, Constraint,
Assignment y sus agregados (SchedulingProblem, Solution). Esta capa no conoce
dominios específicos (nada de docentes ni aulas) y no conoce ningún solver:
prohibido importar ``ortools`` aquí (verificado por ``tests/test_architecture.py``).
"""

from __future__ import annotations

from .assignment import Assignment
from .constraint import Constraint, ConstraintKind, HardConstraint, SoftConstraint
from .exceptions import (
    DomainError,
    InvalidAssignment,
    InvalidEntity,
    InvalidTimeGrid,
    ReferentialIntegrityError,
)
from .ids import ConstraintId, ResourceId, TaskId, TimeSlotIndex
from .problem import SchedulingProblem
from .requirement import ResourceRequirement
from .resource import Resource
from .solution import Penalty, Solution
from .task import Task
from .time_grid import Segment, TimeGrid, TimeSlot

__all__ = [
    "Assignment",
    "Constraint",
    "ConstraintId",
    "ConstraintKind",
    "DomainError",
    "HardConstraint",
    "InvalidAssignment",
    "InvalidEntity",
    "InvalidTimeGrid",
    "Penalty",
    "ReferentialIntegrityError",
    "Resource",
    "ResourceId",
    "ResourceRequirement",
    "SchedulingProblem",
    "Segment",
    "SoftConstraint",
    "Solution",
    "Task",
    "TaskId",
    "TimeGrid",
    "TimeSlot",
    "TimeSlotIndex",
]
