"""Catálogo canónico de restricciones (Actividad 2).

Clasifica cada restricción del motor sobre el **Modelo Canónico** (Resource con
tags ``teacher``/``room``/``group``, Task, TimeSlot, Assignment) y la enlaza con
el plugin que la implementa. Es la fuente única de verdad para la documentación
(``scripts/catalog.py``), los benchmarks y las auditorías.

Cada entrada tiene: ``id``, ``name``, ``description``, ``kind`` (HARD / SOFT /
STRUCTURAL), ``tier`` (nivel lexicográfico del Scoring Engine para las blandas) y
el ``plugin_name`` que la realiza (``None`` si se satisface *por construcción*,
p. ej. la disponibilidad estricta, que vive en el dominio de ``tstart``).

Las duras nunca se rompen (peso infinito, ``kind=HARD``); las blandas se penalizan
en la función objetivo jerarquizada (ver ``scoring.py`` y ``ADR-020``).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum

from .base import SchedulingPlugin
from .catalog.coupling import CoupledLessonsPlugin
from .catalog.daily_quality import (
    DailySpanPlugin,
    SoftMaxConsecutivePlugin,
    TaskContinuityPlugin,
    TeacherGapsPlugin,
    WeeklyBalancePlugin,
)
from .catalog.load import MaxConsecutivePlugin, MaxDailyLoadPlugin
from .catalog.preferences import PreferEarlySlotsPlugin
from .catalog.quality import TeacherRoomStabilityPlugin
from .catalog.room import RoomCapacityPlugin
from .catalog.structural import IntervalNoOverlapPlugin, ResourceNoOverlapPlugin
from .registry import PluginRegistry
from .scoring import ScoringEngine

# --- Tiers del Scoring Engine (multiplicadores de escala, ADR-020) ---
TIER_VITAL = 1
TIER_OPERATIVA = 2
TIER_PREFERENCIAL = 3


class ConstraintKind(Enum):
    """Naturaleza de la restricción en el motor."""

    HARD = "hard"  # invulnerable (Rule Engine): su violación es INFEASIBLE
    SOFT = "soft"  # penalizable (Scoring Engine)
    STRUCTURAL = "structural"  # semántica de las variables, no regla de negocio


@dataclass(frozen=True, slots=True)
class ConstraintDefinition:
    """Metadato canónico de una restricción."""

    id: str
    name: str
    description: str
    kind: ConstraintKind
    plugin_name: str | None = None
    tier: int | None = None
    default_weight: int | None = None
    factory: Callable[[], SchedulingPlugin] | None = None
    note: str = ""

    @property
    def weight_label(self) -> str:
        if self.kind is ConstraintKind.HARD:
            return "∞"
        if self.default_weight is None:
            return "—"
        return str(self.default_weight)


CONSTRAINT_CATALOG: tuple[ConstraintDefinition, ...] = (
    # --- HARD (invulnerables) ---
    ConstraintDefinition(
        "HC-01",
        "Exclusividad de recursos humanos",
        "Un Resource PERSON (teacher) no puede estar en dos Task en el mismo TimeSlot.",
        ConstraintKind.HARD,
        plugin_name="interval_no_overlap",
        factory=IntervalNoOverlapPlugin,
    ),
    ConstraintDefinition(
        "HC-02",
        "Consistencia de colectivos",
        "Un Resource GROUP no participa en varias Task en paralelo en el mismo TimeSlot.",
        ConstraintKind.HARD,
        plugin_name="interval_no_overlap",
    ),
    ConstraintDefinition(
        "HC-03",
        "Exclusividad espacial",
        "Un Resource LOCATION (room) no alberga dos Task simultáneas en el mismo TimeSlot.",
        ConstraintKind.HARD,
        plugin_name="interval_no_overlap",
    ),
    ConstraintDefinition(
        "HC-01B",
        "Exclusividad de recursos (formulación booleana)",
        "Variante período-a-período del no-solape, para benchmarks MIP sin intervalos nativos.",
        ConstraintKind.HARD,
        plugin_name="resource_no_overlap",
        factory=ResourceNoOverlapPlugin,
    ),
    ConstraintDefinition(
        "HC-04",
        "Capacidad volumétrica de infraestructura",
        "La capacity del LOCATION debe cubrir la suma de size de los GROUP de la Task.",
        ConstraintKind.HARD,
        plugin_name="room_capacity",
        factory=RoomCapacityPlugin,
    ),
    ConstraintDefinition(
        "HC-05",
        "Disponibilidad estricta de recursos",
        "Una Task solo cae en TimeSlots de la intersección de disponibilidades de sus recursos.",
        ConstraintKind.HARD,
        plugin_name=None,
        note="Por construcción: el dominio de 'tstart' son los inicios válidos (allowed_starts).",
    ),
    ConstraintDefinition(
        "HC-06",
        "Simultaneidad estricta de tareas (clases combinadas)",
        "Las Task acopladas (Kopplung) comparten obligatoriamente el mismo TimeSlot.",
        ConstraintKind.HARD,
        plugin_name=None,
        note="Por construcción: un acople es UNA Task canónica con N profesores/cursos/aulas.",
    ),
    ConstraintDefinition(
        "HC-07",
        "Equipamiento mínimo de ubicación (especialidad del aula)",
        "Si la Task pide required_features, el LOCATION debe poseerlas en sus atributos.",
        ConstraintKind.HARD,
        plugin_name=None,
        note="Por construcción: matching por tags (roomtype#, equip#) en el adaptador académico.",
    ),
    ConstraintDefinition(
        "HC-08",
        "Carga diaria máxima",
        "Límite de períodos que un recurso ocupa por día operativo (segmento).",
        ConstraintKind.HARD,
        plugin_name="max_daily_load",
        factory=lambda: MaxDailyLoadPlugin(limits=(("teacher", 6), ("group", 8))),
    ),
    ConstraintDefinition(
        "HC-09",
        "Máximo de bloques consecutivos (dura)",
        "Ningún recurso encadena más de N períodos de clase sin descanso.",
        ConstraintKind.HARD,
        plugin_name="max_consecutive",
        factory=lambda: MaxConsecutivePlugin(limits=(("teacher", 4),)),
    ),
    ConstraintDefinition(
        "HC-10",
        "Franja de almuerzo protegida",
        "Un docente no puede tener clase en los períodos reservados para el almuerzo.",
        ConstraintKind.HARD,
        plugin_name="teacher_lunch",
        note="Requiere parámetro lunch_slots.",
    ),
    ConstraintDefinition(
        "HC-11",
        "Inicios prohibidos",
        "Ciertas Task no pueden empezar en TimeSlots vetados.",
        ConstraintKind.HARD,
        plugin_name="forbidden_starts",
        note="Requiere parámetro forbidden.",
    ),
    ConstraintDefinition(
        "HC-12",
        "Horario congelado (reoptimización)",
        "Clases fijadas a su TimeSlot/recurso previo durante una reoptimización parcial.",
        ConstraintKind.HARD,
        plugin_name="frozen_schedule",
        note="Requiere parámetro frozen.",
    ),
    ConstraintDefinition(
        "HC-13",
        "Ventana de almuerzo",
        "En un rango de períodos por día, el recurso debe tener >= 1 período libre.",
        ConstraintKind.HARD,
        plugin_name="lunch_window",
        note="Requiere parámetros start/end/days; la elige el solver (no es fija).",
    ),
    ConstraintDefinition(
        "HC-14",
        "Acoples de lecciones (simultaneidad)",
        "Las Task que comparten (coupling, cseq) inician en el mismo TimeSlot (Kopplung).",
        ConstraintKind.HARD,
        plugin_name="coupled_lessons",
        factory=CoupledLessonsPlugin,
        note="Los ids de acople viajan como atributos de las Task; siempre activo.",
    ),
    # --- SOFT (penalizables), con Tier ---
    ConstraintDefinition(
        "SC-01",
        "Preferencia temporal de recurso",
        "Penaliza colocar una Task en TimeSlots poco convenientes (prefiere las primeras horas).",
        ConstraintKind.SOFT,
        plugin_name="prefer_early_slots",
        tier=TIER_PREFERENCIAL,
        default_weight=1,
        factory=PreferEarlySlotsPlugin,
    ),
    ConstraintDefinition(
        "SC-02",
        "Minimización de huecos de recursos",
        "Penaliza los TimeSlots libres intercalados entre la primera y la última clase del día.",
        ConstraintKind.SOFT,
        plugin_name="teacher_gaps",
        tier=TIER_VITAL,
        default_weight=1,
        factory=TeacherGapsPlugin,
    ),
    ConstraintDefinition(
        "SC-03",
        "Evitar franjas extremas",
        "Penaliza colocar Task en los TimeSlots clasificados como última hora del día.",
        ConstraintKind.SOFT,
        plugin_name="avoid_slots",
        tier=TIER_PREFERENCIAL,
        default_weight=1,
        note="Requiere parámetro slots (los períodos a evitar).",
    ),
    ConstraintDefinition(
        "SC-04",
        "Continuidad y agrupamiento de tareas",
        "Penaliza la fragmentación: cada bloque de clase separado del día suma penalización.",
        ConstraintKind.SOFT,
        plugin_name="task_continuity",
        tier=TIER_OPERATIVA,
        default_weight=1,
        factory=TaskContinuityPlugin,
    ),
    ConstraintDefinition(
        "SC-05",
        "Balance semanal de carga",
        "Penaliza la carga del día más cargado de un recurso, repartiendo entre los días.",
        ConstraintKind.SOFT,
        plugin_name="weekly_balance",
        tier=TIER_OPERATIVA,
        default_weight=1,
        factory=WeeklyBalancePlugin,
    ),
    ConstraintDefinition(
        "SC-06",
        "Estabilidad geográfica (aula base)",
        "Penaliza cada aula distinta que usa un docente (menos desplazamientos).",
        ConstraintKind.SOFT,
        plugin_name="teacher_room_stability",
        tier=TIER_OPERATIVA,
        default_weight=1,
        factory=TeacherRoomStabilityPlugin,
    ),
    ConstraintDefinition(
        "SC-07",
        "Límite de permanencia diaria (jornada)",
        "Penaliza la longitud de la jornada (del primer al último período ocupado del día).",
        ConstraintKind.SOFT,
        plugin_name="daily_span",
        tier=TIER_PREFERENCIAL,
        default_weight=1,
        factory=DailySpanPlugin,
    ),
    ConstraintDefinition(
        "SC-08",
        "Fatiga operativa continua (blanda)",
        "Penaliza encadenar más de N períodos de clase seguidos sin descanso.",
        ConstraintKind.SOFT,
        plugin_name="soft_max_consecutive",
        tier=TIER_OPERATIVA,
        default_weight=1,
        factory=lambda: SoftMaxConsecutivePlugin(limits=(("teacher", 3),)),
    ),
)


def catalog_by_id() -> dict[str, ConstraintDefinition]:
    """Índice ID -> definición."""
    return {d.id: d for d in CONSTRAINT_CATALOG}


def plugin_names_in_catalog() -> frozenset[str]:
    """Nombres de plugin referenciados por el catálogo (los ``None`` se omiten)."""
    return frozenset(d.plugin_name for d in CONSTRAINT_CATALOG if d.plugin_name is not None)


def registry_from_catalog(
    ids: Iterable[str],
    *,
    weight_overrides: Mapping[str, int] | None = None,
    scoring: ScoringEngine | None = None,
) -> PluginRegistry:
    """Construye un ``PluginRegistry`` con los plugins de las restricciones pedidas.

    Solo se instancian las entradas con ``factory`` (las que no requieren
    parámetros de dominio). Varias IDs pueden mapear al mismo plugin (HC-01/02/03
    -> interval_no_overlap): se deduplica por nombre. ``weight_overrides`` ajusta
    el peso de un plugin blando por su ID (vía ``dataclasses.replace``).
    """
    index = catalog_by_id()
    weights = weight_overrides or {}
    if scoring is None:
        # Tiers operativos: cada criterio blando hereda el Tier de su definición,
        # indexado por la etiqueta que emite el plugin (== plugin_name).
        tier_by_label = {
            d.plugin_name: d.tier
            for d in CONSTRAINT_CATALOG
            if d.kind is ConstraintKind.SOFT and d.plugin_name is not None and d.tier is not None
        }
        scoring = ScoringEngine(tier_by_label=tier_by_label)
    registry = PluginRegistry(scoring=scoring)
    seen: set[str] = set()
    for cid in ids:
        definition = index.get(cid)
        if definition is None:
            raise KeyError(f"restricción desconocida en el catálogo: {cid}")
        if definition.factory is None or definition.plugin_name in seen:
            continue
        plugin = definition.factory()
        override = weights.get(cid)
        if override is not None and hasattr(plugin, "weight"):
            plugin = dataclasses.replace(plugin, weight=override)  # type: ignore[type-var]
        registry.register(plugin)
        seen.add(plugin.name)
    return registry


def render_catalog_table() -> str:
    """Catálogo como tabla de texto (documentación viva)."""
    header = f"{'ID':<7} {'TIPO':<11} {'TIER':<5} {'PESO':<5} NOMBRE"
    lines = [header, "-" * len(header)]
    for d in CONSTRAINT_CATALOG:
        tier = "" if d.tier is None else f"T{d.tier}"
        lines.append(f"{d.id:<7} {d.kind.value:<11} {tier:<5} {d.weight_label:<5} {d.name}")
    return "\n".join(lines)
