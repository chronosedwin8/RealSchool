"""``FakeSolver``: implementación de ``ISolver`` para pruebas.

No resuelve nada: registra todas las llamadas recibidas (variables creadas,
restricciones publicadas, objetivo) para poder inspeccionarlas en los tests, y
devuelve un resultado predefinido con ``set_result``. Permite verificar que el
DSL y el compilador producen las llamadas correctas sin depender de OR-Tools.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .interface import (
    ISolver,
    Literal,
    RelOp,
    SolverConfig,
    SolverInterval,
    SolverStatus,
    SolverVar,
)


@dataclass(frozen=True, slots=True)
class LinearRecord:
    terms: tuple[tuple[SolverVar, int], ...]
    op: RelOp
    rhs: int


@dataclass(frozen=True, slots=True)
class ImplicationRecord:
    antecedent: Literal
    consequent: Literal


@dataclass(frozen=True, slots=True)
class IntervalRecord:
    start: SolverVar
    size: int
    presence: Literal | None
    name: str


@dataclass(slots=True)
class FakeSolver(ISolver):
    """Solver de mentira que registra el modelo recibido."""

    var_kind: dict[SolverVar, str] = field(default_factory=dict)
    var_name: dict[SolverVar, str] = field(default_factory=dict)
    int_domains: dict[SolverVar, tuple[int, int]] = field(default_factory=dict)
    enum_domains: dict[SolverVar, tuple[int, ...]] = field(default_factory=dict)
    linear_constraints: list[LinearRecord] = field(default_factory=list)
    all_different: list[tuple[SolverVar, ...]] = field(default_factory=list)
    bool_ors: list[tuple[Literal, ...]] = field(default_factory=list)
    implications: list[ImplicationRecord] = field(default_factory=list)
    intervals: list[IntervalRecord] = field(default_factory=list)
    no_overlaps: list[tuple[SolverInterval, ...]] = field(default_factory=list)
    objective_terms: tuple[tuple[SolverVar, int], ...] = ()
    objective_constant: int = 0
    has_objective: bool = False
    configs_seen: list[SolverConfig | None] = field(default_factory=list)
    _next_handle: int = 0
    _status: SolverStatus = SolverStatus.UNKNOWN
    _values: dict[SolverVar, int] = field(default_factory=dict)
    _objective_value: int = 0

    def _new_handle(self) -> SolverVar:
        handle = SolverVar(self._next_handle)
        self._next_handle += 1
        return handle

    def new_bool_var(self, name: str) -> SolverVar:
        handle = self._new_handle()
        self.var_kind[handle] = "bool"
        self.var_name[handle] = name
        return handle

    def new_int_var(self, lo: int, hi: int, name: str) -> SolverVar:
        handle = self._new_handle()
        self.var_kind[handle] = "int"
        self.var_name[handle] = name
        self.int_domains[handle] = (lo, hi)
        return handle

    def new_int_var_from_values(self, values: Sequence[int], name: str) -> SolverVar:
        handle = self._new_handle()
        self.var_kind[handle] = "int"
        self.var_name[handle] = name
        self.enum_domains[handle] = tuple(values)
        self.int_domains[handle] = (min(values), max(values))
        return handle

    def add_linear(self, terms: Sequence[tuple[SolverVar, int]], op: RelOp, rhs: int) -> None:
        self.linear_constraints.append(LinearRecord(tuple(terms), op, rhs))

    def add_all_different(self, variables: Sequence[SolverVar]) -> None:
        self.all_different.append(tuple(variables))

    def add_bool_or(self, literals: Sequence[Literal]) -> None:
        self.bool_ors.append(tuple(literals))

    def add_implication(self, antecedent: Literal, consequent: Literal) -> None:
        self.implications.append(ImplicationRecord(antecedent, consequent))

    def new_interval(self, start: SolverVar, size: int, name: str) -> SolverInterval:
        return self._record_interval(IntervalRecord(start, size, None, name))

    def new_optional_interval(
        self, start: SolverVar, size: int, presence: Literal, name: str
    ) -> SolverInterval:
        return self._record_interval(IntervalRecord(start, size, presence, name))

    def _record_interval(self, record: IntervalRecord) -> SolverInterval:
        handle = SolverInterval(len(self.intervals))
        self.intervals.append(record)
        return handle

    def add_no_overlap(self, intervals: Sequence[SolverInterval]) -> None:
        self.no_overlaps.append(tuple(intervals))

    def minimize(self, terms: Sequence[tuple[SolverVar, int]], constant: int = 0) -> None:
        self.objective_terms = tuple(terms)
        self.objective_constant = constant
        self.has_objective = True

    def set_result(
        self,
        status: SolverStatus,
        values: Mapping[SolverVar, int] | None = None,
        objective_value: int = 0,
    ) -> None:
        """Predefine lo que devolverán ``solve``/``value``/``objective_value``."""
        self._status = status
        self._values = dict(values) if values is not None else {}
        self._objective_value = objective_value

    def solve(self, config: SolverConfig | None = None) -> SolverStatus:
        self.configs_seen.append(config)
        return self._status

    def value(self, var: SolverVar) -> int:
        return self._values[var]

    def objective_value(self) -> int:
        return self._objective_value
