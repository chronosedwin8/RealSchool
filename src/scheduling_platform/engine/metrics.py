"""Metrics Engine: KPIs objetivos de un horario.

Permite comparar dos horarios con números en vez de impresiones. Todas las
métricas se calculan a partir del horario ya construido (independiente del
solver), igual que el Validation Engine.

KPIs:
- **Uso de aulas**: porcentaje de períodos-aula efectivamente ocupados.
- **Huecos**: períodos libres *intercalados* entre clases dentro de un mismo día
  (los huecos al principio o al final del día no cuentan).
- **Balance de carga**: cuán pareja es la carga semanal entre los docentes.
- **Score de calidad (0-100)**: combinación configurable de los anteriores, para
  tener una cifra única comparable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..core.problem import SchedulingProblem
from ..core.solution import Solution
from .validation import ValidationEngine

TEACHER_TAG = "teacher"
GROUP_TAG = "group"
ROOM_TAG = "room"


@dataclass(frozen=True, slots=True)
class ScheduleMetrics:
    """Indicadores de calidad de un horario."""

    room_utilization_pct: float
    teacher_gaps: int
    group_gaps: int
    teacher_load_balance_pct: float
    objective_value: int
    hard_violations: int
    quality_score: float

    def render(self) -> str:
        return "\n".join(
            [
                f"Uso de aulas:        {self.room_utilization_pct:.1f}%",
                f"Huecos docentes:     {self.teacher_gaps}",
                f"Huecos estudiantes:  {self.group_gaps}",
                f"Balance de carga:    {self.teacher_load_balance_pct:.1f}%",
                f"Penalización total:  {self.objective_value}",
                f"Violaciones duras:   {self.hard_violations}",
                f"Calidad:             {self.quality_score:.1f}/100",
            ]
        )


@dataclass(frozen=True, slots=True)
class GapDistribution:
    """Distribución de huecos por recurso (Actividad 10).

    ``per_resource`` mapea cada recurso a su número de huecos intercalados;
    ``histogram`` cuenta cuántos recursos tienen 0, 1, 2... huecos. Permite
    comparar con Untis no solo el total de huecos sino su reparto (¿unos pocos
    docentes concentran los huecos, o están repartidos?).
    """

    per_resource: dict[int, int]
    mean: float
    maximum: int
    variance: float
    histogram: dict[int, int]

    def render(self) -> str:
        return (
            f"huecos/recurso: media {self.mean:.2f}, máx {self.maximum}, "
            f"varianza {self.variance:.2f}"
        )


@dataclass(frozen=True, slots=True)
class MetricsComparison:
    """Diferencia entre dos horarios (``candidate`` frente a ``baseline``)."""

    baseline: ScheduleMetrics
    candidate: ScheduleMetrics

    @property
    def quality_delta(self) -> float:
        return self.candidate.quality_score - self.baseline.quality_score

    @property
    def candidate_is_better(self) -> bool:
        return self.quality_delta > 0

    def render(self) -> str:
        signo = "+" if self.quality_delta >= 0 else ""
        return (
            f"Calidad: {self.baseline.quality_score:.1f} -> "
            f"{self.candidate.quality_score:.1f} ({signo}{self.quality_delta:.1f})"
        )


@dataclass(frozen=True, slots=True)
class MetricsEngine:
    """Calcula los KPIs de un horario. Los pesos del score son configurables."""

    gap_weight: float = 2.0
    balance_weight: float = 0.3
    validator: ValidationEngine = field(default_factory=ValidationEngine)

    def compute(self, problem: SchedulingProblem, solution: Solution) -> ScheduleMetrics:
        occupancy = self._occupancy(problem, solution)
        rooms = self._resources_with(problem, ROOM_TAG)
        teachers = self._resources_with(problem, TEACHER_TAG)
        groups = self._resources_with(problem, GROUP_TAG)

        utilization = self._utilization(problem, occupancy, rooms)
        teacher_gaps = sum(self._gaps(problem, occupancy, rid) for rid in teachers)
        group_gaps = sum(self._gaps(problem, occupancy, rid) for rid in groups)
        balance = self._balance(occupancy, teachers)
        violations = len(self.validator.validate(problem, solution).issues)

        quality = 100.0
        quality -= self.gap_weight * (teacher_gaps + group_gaps)
        quality -= self.balance_weight * (100.0 - balance)
        quality -= 100.0 * violations  # una violación dura arruina el horario
        quality = max(0.0, min(100.0, quality))

        return ScheduleMetrics(
            room_utilization_pct=utilization,
            teacher_gaps=teacher_gaps,
            group_gaps=group_gaps,
            teacher_load_balance_pct=balance,
            objective_value=solution.objective_value,
            hard_violations=violations,
            quality_score=quality,
        )

    def gap_distribution(
        self, problem: SchedulingProblem, solution: Solution, tag: str = TEACHER_TAG
    ) -> GapDistribution:
        """Reparto de huecos entre los recursos del tipo ``tag`` (Actividad 10)."""
        occupancy = self._occupancy(problem, solution)
        resources = self._resources_with(problem, tag)
        per_resource = {rid: self._gaps(problem, occupancy, rid) for rid in resources}
        counts = list(per_resource.values())
        if not counts:
            return GapDistribution({}, 0.0, 0, 0.0, {})
        mean = sum(counts) / len(counts)
        variance = sum((c - mean) ** 2 for c in counts) / len(counts)
        histogram: dict[int, int] = {}
        for c in counts:
            histogram[c] = histogram.get(c, 0) + 1
        return GapDistribution(
            per_resource=per_resource,
            mean=mean,
            maximum=max(counts),
            variance=variance,
            histogram=dict(sorted(histogram.items())),
        )

    def compare(
        self, problem: SchedulingProblem, baseline: Solution, candidate: Solution
    ) -> MetricsComparison:
        return MetricsComparison(
            baseline=self.compute(problem, baseline),
            candidate=self.compute(problem, candidate),
        )

    # --- cálculo interno ---

    @staticmethod
    def _resources_with(problem: SchedulingProblem, tag: str) -> tuple[int, ...]:
        return tuple(int(r.id) for r in problem.resources if tag in r.tags)

    @staticmethod
    def _occupancy(problem: SchedulingProblem, solution: Solution) -> dict[int, set[int]]:
        """Recurso -> slots que ocupa."""
        occupancy: dict[int, set[int]] = defaultdict(set)
        for assignment in solution.assignments:
            task = problem.task_by_id(assignment.task_id)
            for rid in assignment.resource_ids:
                for offset in range(task.duration):
                    occupancy[int(rid)].add(int(assignment.start) + offset)
        return occupancy

    @staticmethod
    def _utilization(
        problem: SchedulingProblem, occupancy: dict[int, set[int]], rooms: tuple[int, ...]
    ) -> float:
        if not rooms:
            return 0.0
        disponible = len(rooms) * problem.horizon
        ocupado = sum(len(occupancy.get(rid, set())) for rid in rooms)
        return 100.0 * ocupado / disponible

    @staticmethod
    def _gaps(problem: SchedulingProblem, occupancy: dict[int, set[int]], rid: int) -> int:
        """Períodos libres intercalados entre la primera y la última clase de cada día."""
        slots = occupancy.get(rid, set())
        if not slots:
            return 0
        total = 0
        for segment in problem.grid.segments:
            del_dia = sorted(s for s in slots if int(segment.start) <= s < int(segment.end))
            if len(del_dia) >= 2:
                span = del_dia[-1] - del_dia[0] + 1
                total += span - len(del_dia)
        return total

    @staticmethod
    def _balance(occupancy: dict[int, set[int]], teachers: tuple[int, ...]) -> float:
        """100% si todos los docentes tienen la misma carga; baja con la dispersión."""
        if len(teachers) < 2:
            return 100.0
        cargas = [len(occupancy.get(rid, set())) for rid in teachers]
        mayor = max(cargas)
        if mayor == 0:
            return 100.0
        return 100.0 * (1.0 - (mayor - min(cargas)) / mayor)


__all__ = ["GapDistribution", "MetricsComparison", "MetricsEngine", "ScheduleMetrics"]
