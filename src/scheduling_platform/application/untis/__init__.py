"""Fachada Untis: casos de uso del producto para la UI (`untis_desktop`).

La UI solo importa `scheduling_platform.application` (verificado en
`tests/test_boundaries.py`); este subpaquete es lo que allí se reexporta.
"""

from .columns import ColumnSpec, MasterKind, ValueType, columns, format_value, parse_value
from .service import DEFAULT_GRID_ID, PROJECT_SUFFIX, UntisService, build_grid
from .session import UntisSession
from .texts import CRITERION_TEXTS, TAB_LABELS
from .views import (
    CriterionLine,
    DiagnosisItem,
    DiagnosisView,
    EditResult,
    EvaluationView,
    GridView,
    LessonLineRow,
    LessonRow,
    LoadSummary,
    MasterRow,
    MasterTable,
    MoveTarget,
    OptimizeOutcome,
    OptimizeProgress,
    OptimizeRequest,
    PeriodRow,
    RequestGrid,
    SliderView,
    TimetableCell,
    TimetableGrid,
    TimetableSummary,
    WeightingTabView,
)

__all__ = [
    "CRITERION_TEXTS",
    "DEFAULT_GRID_ID",
    "PROJECT_SUFFIX",
    "TAB_LABELS",
    "ColumnSpec",
    "CriterionLine",
    "DiagnosisItem",
    "DiagnosisView",
    "EditResult",
    "EvaluationView",
    "GridView",
    "LessonLineRow",
    "LessonRow",
    "LoadSummary",
    "MasterKind",
    "MasterRow",
    "MasterTable",
    "MoveTarget",
    "OptimizeOutcome",
    "OptimizeProgress",
    "OptimizeRequest",
    "PeriodRow",
    "RequestGrid",
    "SliderView",
    "TimetableCell",
    "TimetableGrid",
    "TimetableSummary",
    "UntisService",
    "UntisSession",
    "ValueType",
    "WeightingTabView",
    "build_grid",
    "columns",
    "format_value",
    "parse_value",
]
