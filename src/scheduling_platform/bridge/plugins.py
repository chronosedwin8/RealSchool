"""Reglas CP-SAT del producto Untis, como plugins del SDK (ADR-036).

El documento maestro pedía extender el motor congelado para expresar criterios
Untis (dobles, secuencias, pool ordenado, contadores). No hace falta tocarlo: el
SDK de plugins ya es el punto de extensión. Estos plugins viven en `bridge`, que
es quien conoce la geometría Untis (qué inicio de tarea cubre qué período de qué
rejilla), y la reciben **precalculada**: el plugin solo codifica la lógica.

Todos trabajan sobre variables booleanas de inicio (`start#t#s`), así que se usan
en **ventanas** pequeñas (repair/polish), donde el modelo booleano es barato.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from scheduling_platform.dsl import BoolDomain, IntDomain, LinearExpr, Var
from scheduling_platform.dsl.logic import LinearConstraint
from scheduling_platform.plugins import (
    Contribution,
    PenaltyTerm,
    SchedulingModelContext,
    SchedulingPlugin,
)

#: Una colocación concreta: `(tarea, inicio)`.
type Placement = tuple[int, int]


def _valid(context: SchedulingModelContext, placement: Placement) -> bool:
    tarea, inicio = placement
    return inicio in context.valid_starts(tarea)


# --------------------------------------------------------------------------- #
# Cambio mínimo
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class MinimalChangePlugin(SchedulingPlugin):
    """Penaliza que una tarea abandone su inicio o sus aulas originales."""

    name: ClassVar[str] = "minimal_change"
    original: tuple[Placement, ...] = ()
    """`(tarea, inicio original)`."""
    rooms: tuple[tuple[int, int], ...] = ()
    """`(tarea, aula original)`."""
    weight: int = 10
    room_weight: int = 3

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        terminos: list[PenaltyTerm] = []
        for tarea, inicio in self.original:
            if not _valid(context, (tarea, inicio)):
                continue
            quedarse = context.start_var(tarea, inicio)
            terminos.append(
                PenaltyTerm(
                    LinearExpr.from_terms([(quedarse, -1)], constant=1), self.weight, self.name
                )
            )
        for tarea, aula in self.rooms:
            conserva = context.assign_var(tarea, aula)
            terminos.append(
                PenaltyTerm(
                    LinearExpr.from_terms([(conserva, -1)], constant=1),
                    self.room_weight,
                    f"{self.name}_room",
                )
            )
        return Contribution(penalties=tuple(terminos))


# --------------------------------------------------------------------------- #
# Pool ordenado con costes (optimización de aulas / cadena de alternativas)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OrderedPoolPlugin(SchedulingPlugin):
    """Cada recurso elegible tiene un coste; elegirlo lo paga (0 = el preferido)."""

    name: ClassVar[str] = "ordered_pool"
    costs: tuple[tuple[int, int, int], ...] = ()
    """`(tarea, recurso, coste)`."""
    label: str = "room_alternative_chain"
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        terminos = [
            PenaltyTerm(LinearExpr.of(context.assign_var(t, r)), self.weight * coste, self.label)
            for t, r, coste in self.costs
            if coste > 0
        ]
        return Contribution(penalties=tuple(terminos))


# --------------------------------------------------------------------------- #
# Combinaciones prohibidas blandas (secuencias de materias)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ForbiddenPairsPlugin(SchedulingPlugin):
    """Cada grupo es una violación si se da **alguna** de sus parejas de colocaciones.

    Sirve para "A antes que B el mismo día": el grupo de la pareja (A, B) lista
    las combinaciones `(inicio de A, inicio de B)` en las que B va antes que A.
    """

    name: ClassVar[str] = "forbidden_pairs"
    groups: tuple[tuple[tuple[Placement, Placement], ...], ...] = ()
    label: str = "subject_sequence"
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        restricciones: list[LinearConstraint] = []
        terminos: list[PenaltyTerm] = []
        for i, grupo in enumerate(self.groups):
            parejas = [(a, b) for a, b in grupo if _valid(context, a) and _valid(context, b)]
            if not parejas:
                continue
            v = Var(f"{self.label}#v{i}", BoolDomain())
            for a, b in parejas:
                x = context.start_var(*a)
                y = context.start_var(*b)
                # v >= x + y - 1
                restricciones.append(
                    LinearConstraint(LinearExpr.from_terms([(v, 1), (x, -1), (y, -1)], 1) >= 0)
                )
            terminos.append(PenaltyTerm(LinearExpr.of(v), self.weight, self.label))
        return Contribution(constraints=tuple(restricciones), penalties=tuple(terminos))


# --------------------------------------------------------------------------- #
# Mínimo de parejas logradas (períodos dobles)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class MinPairsPlugin(SchedulingPlugin):
    """Penaliza no alcanzar `minimum` parejas logradas (p. ej. dobles de una lección).

    Una pareja lograda es una combinación `(inicio de i, inicio de j)` que forma un
    doble: j empieza en el período lectivo contiguo al de i, el mismo día.
    """

    name: ClassVar[str] = "min_pairs"
    requirements: tuple[tuple[int, tuple[tuple[Placement, Placement], ...]], ...] = ()
    """`(mínimo, combinaciones que cuentan como pareja)` por lección."""
    label: str = "subject_double_periods"
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        restricciones: list[LinearConstraint] = []
        terminos: list[PenaltyTerm] = []
        for i, (minimo, combos) in enumerate(self.requirements):
            logradas: list[Var] = []
            for k, (a, b) in enumerate(combos):
                if not (_valid(context, a) and _valid(context, b)):
                    continue
                w = Var(f"{self.label}#w{i}#{k}", BoolDomain())
                x = context.start_var(*a)
                y = context.start_var(*b)
                restricciones.append(
                    LinearConstraint(LinearExpr.from_terms([(w, 1), (x, -1)]) <= 0)
                )
                restricciones.append(
                    LinearConstraint(LinearExpr.from_terms([(w, 1), (y, -1)]) <= 0)
                )
                logradas.append(w)
            if minimo <= 0:
                continue
            falta = Var(f"{self.label}#short{i}", IntDomain(0, minimo))
            # falta >= minimo - sum(w)
            restricciones.append(
                LinearConstraint(
                    LinearExpr.from_terms([(falta, 1), *((w, 1) for w in logradas)], -minimo) >= 0
                )
            )
            terminos.append(PenaltyTerm(LinearExpr.of(falta), self.weight, self.label))
        return Contribution(constraints=tuple(restricciones), penalties=tuple(terminos))


# --------------------------------------------------------------------------- #
# Huecos en períodos (clase o profesor sobre su propia rejilla)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class GapEntity:
    """Ocupación de una entidad (clase o profesor) en los períodos de su rejilla.

    `days[d][p]` son las colocaciones `(tarea, inicio)` de la ventana que ocupan el
    período `p` del día `d`; `fixed_busy[d][p]` dice si ya lo ocupa una sesión
    congelada (fuera de la ventana).
    """

    key: str
    label: str
    weight: int
    days: tuple[tuple[tuple[Placement, ...], ...], ...]
    fixed_busy: tuple[tuple[bool, ...], ...]


@dataclass(frozen=True, slots=True)
class PeriodGapsPlugin(SchedulingPlugin):
    """Huecos en **períodos**, como el evaluador de referencia, para varias entidades.

    Un período libre con ocupación antes y después, el mismo día, es un hueco.
    Formulación lineal: `antes[p] >= OR(ocupado[q], q < p)`, `despues[p] >=
    OR(ocupado[q], q > p)` y `hueco[p] >= antes + despues - ocupado - 1`; al
    minimizar, las cotas inferiores bastan.
    """

    name: ClassVar[str] = "period_gaps"
    entities: tuple[GapEntity, ...] = ()

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        restricciones: list[LinearConstraint] = []
        terminos: list[PenaltyTerm] = []
        for ent in self.entities:
            for d, periodos in enumerate(ent.days):
                fijos = ent.fixed_busy[d] if d < len(ent.fixed_busy) else ()
                ocupa = [
                    self._busy(context, cubren, p < len(fijos) and fijos[p])
                    for p, cubren in enumerate(periodos)
                ]
                self._day(ent, d, ocupa, restricciones, terminos)
        return Contribution(constraints=tuple(restricciones), penalties=tuple(terminos))

    @staticmethod
    def _busy(
        context: SchedulingModelContext, cubren: tuple[Placement, ...], fijo: bool
    ) -> LinearExpr | None:
        if fijo:
            return LinearExpr.of(1)
        vars_ = [context.start_var(*c) for c in cubren if _valid(context, c)]
        return LinearExpr.from_terms((v, 1) for v in vars_) if vars_ else None

    @staticmethod
    def _day(
        ent: GapEntity,
        d: int,
        ocupa: list[LinearExpr | None],
        restricciones: list[LinearConstraint],
        terminos: list[PenaltyTerm],
    ) -> None:
        n = len(ocupa)
        if n < 3 or sum(o is not None for o in ocupa) < 2:
            return  # con menos de dos períodos ocupables no puede haber hueco
        prefijo = f"{ent.label}#{ent.key}#d{d}"
        antes = [Var(f"{prefijo}#b{p}", BoolDomain()) for p in range(n)]
        despues = [Var(f"{prefijo}#a{p}", BoolDomain()) for p in range(n)]
        for p in range(n):
            previo = ocupa[p - 1] if p > 0 else None
            if previo is not None:
                restricciones.append(LinearConstraint(LinearExpr.of(antes[p]) - previo >= 0))
            if p > 0:
                restricciones.append(
                    LinearConstraint(
                        LinearExpr.from_terms([(antes[p], 1), (antes[p - 1], -1)]) >= 0
                    )
                )
            siguiente = ocupa[p + 1] if p < n - 1 else None
            if siguiente is not None:
                restricciones.append(LinearConstraint(LinearExpr.of(despues[p]) - siguiente >= 0))
            if p < n - 1:
                restricciones.append(
                    LinearConstraint(
                        LinearExpr.from_terms([(despues[p], 1), (despues[p + 1], -1)]) >= 0
                    )
                )
        for p in range(1, n - 1):
            hueco = Var(f"{prefijo}#g{p}", BoolDomain())
            expr = LinearExpr.from_terms([(hueco, 1), (antes[p], -1), (despues[p], -1)], 1)
            propio = ocupa[p]
            if propio is not None:
                expr = expr + propio
            restricciones.append(LinearConstraint(expr >= 0))
            terminos.append(PenaltyTerm(LinearExpr.of(hueco), ent.weight, ent.label))


__all__ = [
    "ForbiddenPairsPlugin",
    "GapEntity",
    "MinPairsPlugin",
    "MinimalChangePlugin",
    "OrderedPoolPlugin",
    "PeriodGapsPlugin",
    "Placement",
]
