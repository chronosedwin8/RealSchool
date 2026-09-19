"""Capa de Aplicación: casos de uso, dispatcher y contrato de proceso (Fase 2).

Se sitúa entre la CLI y la API pública del ``SchedulingEngine``. Encapsula cada
operación como un :class:`Command` (patrón Command + inyección de dependencias) y
garantiza el contrato de streams/exit-codes. **Regla de oro:** el Core de
optimización (``core``/``academic``/``sal``/``plugins``/``pipeline``/``engine``)
nunca importa esta capa (verificado por ``tests/test_architecture.py``).
"""

from __future__ import annotations

from ..pipeline.events import ProgressCallback, ProgressEvent
from .cancel import CancelToken
from .commands.base import Command, CommandResult
from .commands.config_validate import ConfigValidateCommand
from .commands.convert import ConvertCommand
from .commands.doctor import DoctorCommand
from .commands.inspect_project import ExplainCommand, ValidateCommand
from .commands.project_ops import (
    ProjectExtractCommand,
    ProjectInfoCommand,
    ProjectPackCommand,
    ProjectValidateCommand,
)
from .commands.solve import GenerateCommand, OptimizeCommand
from .config import (
    EngineConfig,
    PluginsConfig,
    PluginSetting,
    load_engine_config,
    load_plugins_config,
)
from .context import AppContext
from .dispatcher import CommandDispatcher
from .errors import (
    AppError,
    ConfigError,
    InfeasibleError,
    InternalError,
    SolveTimeoutError,
)
from .log import AppLogger
from .project import (
    BjsProject,
    LunchWindow,
    SchedulingOptions,
    SchoolPeriod,
    SchoolWeek,
    new_project,
    open_project,
    save_project,
)
from .service import EngineService, Session
from .solvers import SOLVER_NAMES, solver_factory_for
from .untis import (
    CRITERION_TEXTS,
    DEFAULT_GRID_ID,
    PROJECT_SUFFIX,
    TAB_LABELS,
    ColumnSpec,
    CriterionLine,
    DiagnosisItem,
    DiagnosisView,
    EditResult,
    EvaluationView,
    GridView,
    LessonLineRow,
    LoadSummary,
    MasterKind,
    MasterRow,
    MasterTable,
    OptimizeOutcome,
    OptimizeProgress,
    OptimizeRequest,
    PeriodRow,
    RequestGrid,
    SliderView,
    TimeFrame,
    TimetableGrid,
    TimetableSummary,
    UntisService,
    UntisSession,
    ValueType,
    WeightingTabView,
    columns,
    format_value,
    parse_value,
)
from .untis import (
    LessonRow as UntisLessonRow,
)
from .untis import (
    MoveTarget as UntisMoveTarget,
)
from .untis import (
    TimetableCell as UntisTimetableCell,
)
from .view_models import (
    ConstraintRow,
    DashboardStats,
    EntityTable,
    EntityTables,
    FocusOption,
    LessonRow,
    MoveTarget,
    ReportTable,
    SolveOutcome,
    TimetableCell,
    TimetableView,
    UnplacedClass,
    ValidationItem,
    ValidationReport,
)

__all__ = [
    "CRITERION_TEXTS",
    "DEFAULT_GRID_ID",
    "PROJECT_SUFFIX",
    "SOLVER_NAMES",
    "TAB_LABELS",
    "AppContext",
    "AppError",
    "AppLogger",
    "BjsProject",
    "CancelToken",
    "ColumnSpec",
    "Command",
    "CommandDispatcher",
    "CommandResult",
    "ConfigError",
    "ConfigValidateCommand",
    "ConstraintRow",
    "ConvertCommand",
    "CriterionLine",
    "DashboardStats",
    "DiagnosisItem",
    "DiagnosisView",
    "DoctorCommand",
    "EditResult",
    "EngineConfig",
    "EngineService",
    "EntityTable",
    "EntityTables",
    "EvaluationView",
    "ExplainCommand",
    "FocusOption",
    "GenerateCommand",
    "GridView",
    "InfeasibleError",
    "InternalError",
    "LessonLineRow",
    "LessonRow",
    "LoadSummary",
    "LunchWindow",
    "MasterKind",
    "MasterRow",
    "MasterTable",
    "MoveTarget",
    "OptimizeCommand",
    "OptimizeOutcome",
    "OptimizeProgress",
    "OptimizeRequest",
    "PeriodRow",
    "PluginSetting",
    "PluginsConfig",
    "ProgressCallback",
    "ProgressEvent",
    "ProjectExtractCommand",
    "ProjectInfoCommand",
    "ProjectPackCommand",
    "ProjectValidateCommand",
    "ReportTable",
    "RequestGrid",
    "SchedulingOptions",
    "SchoolPeriod",
    "SchoolWeek",
    "Session",
    "SliderView",
    "SolveOutcome",
    "SolveTimeoutError",
    "TimeFrame",
    "TimetableCell",
    "TimetableGrid",
    "TimetableSummary",
    "TimetableView",
    "UnplacedClass",
    "UntisLessonRow",
    "UntisMoveTarget",
    "UntisService",
    "UntisSession",
    "UntisTimetableCell",
    "ValidateCommand",
    "ValidationItem",
    "ValidationReport",
    "ValueType",
    "WeightingTabView",
    "columns",
    "format_value",
    "load_engine_config",
    "load_plugins_config",
    "new_project",
    "open_project",
    "parse_value",
    "save_project",
    "solver_factory_for",
]
