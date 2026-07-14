"""Estrategias de Hypothesis para generar entidades canónicas válidas.

Compartidas por las pruebas property-based de la Fase 1.
"""

from __future__ import annotations

from hypothesis import strategies as st

from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    Task,
    TaskId,
    TimeGrid,
)


@st.composite
def time_grids(draw: st.DrawFn, max_segments: int = 5, max_length: int = 6) -> TimeGrid:
    """Rejillas válidas con 1..max_segments segmentos de 1..max_length slots."""
    lengths = draw(
        st.lists(st.integers(min_value=1, max_value=max_length), min_size=1, max_size=max_segments)
    )
    return TimeGrid.from_segment_lengths(lengths)


@st.composite
def resources(draw: st.DrawFn, resource_id: int = 0) -> Resource:
    """Recurso válido con tags e id dados."""
    tags = draw(st.sets(st.sampled_from(["teacher", "room", "group", "lab"]), max_size=3))
    capacity = draw(st.integers(min_value=1, max_value=4))
    return Resource(
        id=ResourceId(resource_id),
        name=f"R{resource_id}",
        tags=frozenset(tags),
        capacity=capacity,
    )


@st.composite
def tasks(draw: st.DrawFn, task_id: int = 0, max_duration: int = 3) -> Task:
    """Tarea válida (sin dominio temporal explícito) con un requerimiento."""
    duration = draw(st.integers(min_value=1, max_value=max_duration))
    tag = draw(st.sampled_from(["teacher", "room", "group"]))
    same_segment = draw(st.booleans())
    return Task(
        id=TaskId(task_id),
        name=f"T{task_id}",
        duration=duration,
        requirements=(ResourceRequirement(tag=tag),),
        same_segment=same_segment,
    )
