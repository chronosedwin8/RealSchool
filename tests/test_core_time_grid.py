"""Pruebas de la rejilla temporal discreta con segmentos (Fase 1, D1)."""

from __future__ import annotations

import dataclasses

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scheduling_platform.core import InvalidTimeGrid, Segment, TimeGrid, TimeSlotIndex

from .strategies import time_grids


def test_from_segment_lengths_construye_horizonte_y_segmentos() -> None:
    grid = TimeGrid.from_segment_lengths([3, 3])
    assert grid.horizon == 6
    assert len(grid.segments) == 2
    assert grid.segments[1].start == 3
    assert grid.segments[1].end == 6


def test_segment_of_localiza_el_segmento_correcto() -> None:
    grid = TimeGrid.from_segment_lengths([2, 2])
    assert grid.segment_of(TimeSlotIndex(0)).id == 0
    assert grid.segment_of(TimeSlotIndex(2)).id == 1


def test_slot_fuera_de_rejilla_lanza() -> None:
    grid = TimeGrid.from_segment_lengths([2])
    with pytest.raises(InvalidTimeGrid):
        grid.segment_of(TimeSlotIndex(5))


def test_contiguidad_respeta_fronteras_de_segmento() -> None:
    grid = TimeGrid.from_segment_lengths([2, 2])  # slots [0,1 | 2,3]
    assert grid.are_contiguous(TimeSlotIndex(0), TimeSlotIndex(1)) is True
    # 1 -> 2 cruza la frontera de segmento: NO contiguos
    assert grid.are_contiguous(TimeSlotIndex(1), TimeSlotIndex(2)) is False
    assert grid.are_contiguous(TimeSlotIndex(2), TimeSlotIndex(3)) is True


def test_valid_starts_same_segment_no_cruza_frontera() -> None:
    grid = TimeGrid.from_segment_lengths([3, 3])  # [0,1,2 | 3,4,5]
    # duración 2 dentro de un mismo segmento: {0,1} y {3,4}
    assert grid.valid_starts(2, same_segment=True) == frozenset(
        TimeSlotIndex(i) for i in (0, 1, 3, 4)
    )


def test_valid_starts_sin_same_segment_permite_cruce() -> None:
    grid = TimeGrid.from_segment_lengths([3, 3])
    # duración 2 sobre el horizonte 6: inicios 0..4
    assert grid.valid_starts(2, same_segment=False) == frozenset(TimeSlotIndex(i) for i in range(5))


def test_grid_con_segmentos_no_contiguos_lanza() -> None:
    with pytest.raises(InvalidTimeGrid):
        TimeGrid(segments=(Segment(0, TimeSlotIndex(0), 2), Segment(1, TimeSlotIndex(5), 2)))


def test_segmento_longitud_cero_lanza() -> None:
    with pytest.raises(InvalidTimeGrid):
        Segment(id=0, start=TimeSlotIndex(0), length=0)


def test_grid_es_inmutable() -> None:
    grid = TimeGrid.from_segment_lengths([2])
    with pytest.raises(dataclasses.FrozenInstanceError):
        grid.segments = ()  # type: ignore[misc]


@given(time_grids())
def test_property_horizonte_igual_suma_de_longitudes(grid: TimeGrid) -> None:
    assert grid.horizon == sum(s.length for s in grid.segments)


@given(time_grids())
def test_property_todo_slot_pertenece_a_exactamente_un_segmento(grid: TimeGrid) -> None:
    for index in range(grid.horizon):
        contenedores = [s for s in grid.segments if s.contains(TimeSlotIndex(index))]
        assert len(contenedores) == 1


@given(time_grids(), st.integers(min_value=1, max_value=6))
def test_property_valid_starts_caben_dentro_de_la_rejilla(grid: TimeGrid, duration: int) -> None:
    for start in grid.valid_starts(duration, same_segment=False):
        assert start + duration <= grid.horizon
