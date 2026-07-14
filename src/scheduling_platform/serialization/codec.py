"""Codec canónico: entidades del Modelo Canónico <-> diccionarios planos.

Es la única capa que conoce la *forma* de los datos serializados. JSON, YAML y
el contenedor ``.proschedule`` se limitan a escribir/leer estos diccionarios, de
modo que un cambio de formato de fichero no toca la traducción de entidades.
"""

from __future__ import annotations

from typing import Any

from ..core.assignment import Assignment
from ..core.constraint import Constraint, HardConstraint, SoftConstraint
from ..core.ids import ConstraintId, ResourceId, TaskId, TimeSlotIndex
from ..core.problem import SchedulingProblem
from ..core.requirement import ResourceRequirement
from ..core.resource import Resource
from ..core.solution import Penalty, Solution
from ..core.task import Task
from ..core.time_grid import Segment, TimeGrid
from .exceptions import SerializationError

Doc = dict[str, Any]


# --- rejilla temporal ---


def grid_to_dict(grid: TimeGrid) -> Doc:
    return {
        "segments": [{"id": s.id, "start": int(s.start), "length": s.length} for s in grid.segments]
    }


def grid_from_dict(doc: Doc) -> TimeGrid:
    segments = tuple(
        Segment(id=int(s["id"]), start=TimeSlotIndex(int(s["start"])), length=int(s["length"]))
        for s in doc["segments"]
    )
    return TimeGrid(segments=segments)


# --- entidades ---


def resource_to_dict(resource: Resource) -> Doc:
    return {
        "id": int(resource.id),
        "name": resource.name,
        "tags": sorted(resource.tags),
        "capacity": resource.capacity,
        "attributes": [[key, value] for key, value in resource.attributes],
    }


def resource_from_dict(doc: Doc) -> Resource:
    return Resource(
        id=ResourceId(int(doc["id"])),
        name=str(doc["name"]),
        tags=frozenset(doc.get("tags", ())),
        capacity=int(doc.get("capacity", 1)),
        attributes=tuple((str(k), int(v)) for k, v in doc.get("attributes", ())),
    )


def task_to_dict(task: Task) -> Doc:
    allowed = task.allowed_starts
    return {
        "id": int(task.id),
        "name": task.name,
        "duration": task.duration,
        "requirements": [{"tag": r.tag, "quantity": r.quantity} for r in task.requirements],
        "allowed_starts": None if allowed is None else sorted(int(s) for s in allowed),
        "same_segment": task.same_segment,
        "attributes": [[key, value] for key, value in task.attributes],
    }


def task_from_dict(doc: Doc) -> Task:
    allowed = doc.get("allowed_starts")
    return Task(
        id=TaskId(int(doc["id"])),
        name=str(doc["name"]),
        duration=int(doc["duration"]),
        requirements=tuple(
            ResourceRequirement(tag=str(r["tag"]), quantity=int(r.get("quantity", 1)))
            for r in doc["requirements"]
        ),
        allowed_starts=None
        if allowed is None
        else frozenset(TimeSlotIndex(int(s)) for s in allowed),
        same_segment=bool(doc.get("same_segment", True)),
        attributes=tuple((str(k), int(v)) for k, v in doc.get("attributes", ())),
    )


def constraint_to_dict(constraint: Constraint) -> Doc:
    doc: Doc = {
        "kind": constraint.kind.value,
        "id": int(constraint.id),
        "name": constraint.name,
    }
    if isinstance(constraint, SoftConstraint):
        doc["weight"] = constraint.weight
    return doc


def constraint_from_dict(doc: Doc) -> Constraint:
    kind = str(doc["kind"])
    cid = ConstraintId(int(doc["id"]))
    name = str(doc["name"])
    if kind == "hard":
        return HardConstraint(id=cid, name=name)
    if kind == "soft":
        return SoftConstraint(id=cid, name=name, weight=int(doc["weight"]))
    raise SerializationError(f"tipo de restricción desconocido: {kind}")


# --- agregados ---


def problem_to_dict(problem: SchedulingProblem) -> Doc:
    return {
        "grid": grid_to_dict(problem.grid),
        "resources": [resource_to_dict(r) for r in problem.resources],
        "tasks": [task_to_dict(t) for t in problem.tasks],
        "constraints": [constraint_to_dict(c) for c in problem.constraints],
    }


def problem_from_dict(doc: Doc) -> SchedulingProblem:
    return SchedulingProblem(
        grid=grid_from_dict(doc["grid"]),
        resources=tuple(resource_from_dict(r) for r in doc["resources"]),
        tasks=tuple(task_from_dict(t) for t in doc["tasks"]),
        constraints=tuple(constraint_from_dict(c) for c in doc.get("constraints", ())),
    )


def solution_to_dict(solution: Solution) -> Doc:
    return {
        "assignments": [
            {
                "task_id": int(a.task_id),
                "start": int(a.start),
                "resource_ids": [int(r) for r in a.resource_ids],
            }
            for a in solution.assignments
        ],
        "objective_value": solution.objective_value,
        "penalties": [{"source": p.source, "amount": p.amount} for p in solution.penalties],
    }


def solution_from_dict(doc: Doc) -> Solution:
    return Solution(
        assignments=tuple(
            Assignment(
                task_id=TaskId(int(a["task_id"])),
                start=TimeSlotIndex(int(a["start"])),
                resource_ids=tuple(ResourceId(int(r)) for r in a["resource_ids"]),
            )
            for a in doc["assignments"]
        ),
        objective_value=int(doc["objective_value"]),
        penalties=tuple(
            Penalty(source=str(p["source"]), amount=int(p["amount"]))
            for p in doc.get("penalties", ())
        ),
    )
