"""Fachada ``EngineService``: frontera única entre la GUI y el motor (Fase 5).

La app de escritorio (Fase 6) **solo** habla con esta clase y con
``view_models``; nunca con el problema canónico, el solver o el pipeline. Aquí se
consolidan los casos de uso en llamadas simples (abrir/guardar, tablas, horario,
validar, optimizar, editar) que reutilizan las piezas de las Fases 1-4
(``BjsProject``, ``runtime``, ``MetricsEngine``, catálogo). Es testeable de
cabeza, sin Qt: así garantizamos que **ninguna regla de negocio viva en la UI**.

Regla de oro: un fallo del motor (infactible, timeout, config) nunca escapa como
excepción hacia la interfaz; se devuelve como :class:`SolveOutcome` estructurado.
"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from ..core.ids import ResourceId, TaskId, TimeSlotIndex
from ..core.problem import SchedulingProblem
from ..core.requirement import ResourceRequirement
from ..core.resource import Resource
from ..core.task import Task
from ..core.time_grid import Segment
from ..engine import MetricsEngine, ReOptimizationEngine
from ..pipeline.events import ProgressCallback
from ..plugins import CONSTRAINT_CATALOG, ConstraintKind
from ..plugins.catalog.coupling import CoupledLessonsPlugin
from ..plugins.catalog.lunch import LunchWindowPlugin
from ..plugins.catalog.structural import IntervalNoOverlapPlugin
from .cancel import CancelToken
from .commands.solve import solution_summary
from .config import EngineConfig, PluginsConfig, PluginSetting
from .errors import AppError, ConfigError, InfeasibleError, InternalError, SolveTimeoutError
from .project import (
    BjsProject,
    LunchWindow,
    SchoolPeriod,
    SchoolWeek,
    new_project,
    open_project,
    save_project,
)
from .runtime import analyze_feasibility, build_registry, run_engine
from .solvers import SOLVER_NAMES, solver_factory_for
from .view_models import (
    ConstraintRow,
    DashboardStats,
    EntityTables,
    FocusOption,
    LessonRow,
    MoveTarget,
    ReportTable,
    SolveOutcome,
    TimetableView,
    ValidationItem,
    ValidationReport,
    entity_tables,
    focus_options,
    lesson_rows,
    timetable_view,
)

_METRICS = MetricsEngine()
_CPSAT = "ortools_cpsat"
# Invariantes del motor (siempre activos): el no-solape estructural y la
# simultaneidad de acoples. No se ofrecen como restricciones editables en la GUI.
_STRUCTURAL_NOOVERLAP = frozenset({"interval_no_overlap", "resource_no_overlap", "coupled_lessons"})


@dataclass(slots=True)
class Session:
    """Un proyecto abierto en la app: su ruta, su estado y si tiene cambios sin guardar."""

    project: BjsProject
    path: Path | None = None
    dirty: bool = False


class EngineService:
    """API interna que la GUI consume. Sin estado propio: opera sobre ``Session``."""

    # --- ciclo de vida del proyecto ------------------------------------- #
    def open(self, path: str | Path) -> Session:
        """Abre un ``.bjs`` (valida integridad y estructura)."""
        project = open_project(path)
        return Session(project=project, path=Path(path))

    def save(self, session: Session, path: str | Path | None = None) -> None:
        """Guarda el proyecto de forma atómica; marca la sesión como limpia."""
        target = Path(path) if path is not None else session.path
        if target is None:
            raise ConfigError("no hay ruta de destino para guardar el proyecto")
        save_project(target, session.project)
        session.path = target
        session.dirty = False

    def new(self, path: str | Path, name: str, project: BjsProject) -> Session:
        """Persiste un proyecto nuevo a partir de un ``BjsProject`` ya construido."""
        saved = new_project(
            path,
            name,
            project.problem,
            constraints=project.constraints,
            solver_config=project.solver_config,
        )
        return Session(project=saved, path=Path(path))

    # --- import / export ------------------------------------------------ #
    def import_untis(
        self, xml_path: str | Path, dest_bjs: str | Path, *, name: str | None = None
    ) -> Session:
        """Importa un export XML de Untis a un ``.bjs`` nuevo y lo abre."""
        from ..untis import UntisToCanonicalAdapter, parse_untis

        source = Path(xml_path)
        if not source.exists():
            raise ConfigError(f"no existe el archivo: {source}")
        if source.suffix.lower() != ".xml":
            raise ConfigError(f"formato no soportado: {source.suffix!r} (usa un .xml de Untis)")
        translation = UntisToCanonicalAdapter().translate(parse_untis(source))
        project = new_project(dest_bjs, name or source.stem, translation.problem)
        return Session(project=project, path=Path(dest_bjs))

    def export_json(self, session: Session, dest_file: str | Path) -> Path:
        """Exporta el proyecto (problema + solución + métricas) a un JSON legible."""
        from ..serialization.codec import problem_to_dict, solution_to_dict

        project = session.project
        doc = {
            "manifest": project.manifest,
            "problem": problem_to_dict(project.problem),
            "solution": (
                solution_to_dict(project.solution) if project.solution is not None else None
            ),
            "metrics": project.metrics,
        }
        target = Path(dest_file)
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    # --- versiones / snapshots ------------------------------------------ #
    def snapshot(self, session: Session) -> Path:
        """Guarda el proyecto y crea una copia con fecha para poder restaurarla."""
        if session.path is None:
            raise ConfigError("guarda el proyecto antes de crear una versión")
        self.save(session)
        folder = session.path.parent / f"{session.path.stem}_snapshots"
        folder.mkdir(exist_ok=True)
        dest = folder / f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.bjs"
        shutil.copy2(session.path, dest)
        return dest

    def list_snapshots(self, session: Session) -> tuple[Path, ...]:
        """Versiones guardadas del proyecto, de la más reciente a la más antigua."""
        if session.path is None:
            return ()
        folder = session.path.parent / f"{session.path.stem}_snapshots"
        if not folder.exists():
            return ()
        return tuple(sorted(folder.glob("*.bjs"), reverse=True))

    # --- consultas (modelos de vista) ----------------------------------- #
    def tables(self, session: Session) -> EntityTables:
        project = session.project
        return entity_tables(
            project.problem, project.subjects, project.resource_info, project.subject_info
        )

    # --- datos maestros estilo Untis (Fase 7) --------------------------- #
    def set_resource_info(self, session: Session, resource_id: int, field: str, value: str) -> None:
        """Fija un campo maestro de un recurso (nombre completo, e-mail, sección...)."""
        if not any(int(r.id) == resource_id for r in session.project.problem.resources):
            raise ConfigError(f"recurso inexistente: {resource_id}")
        info = {k: dict(v) for k, v in session.project.resource_info.items()}
        entry = info.setdefault(resource_id, {})
        value = value.strip()
        if value:
            entry[field] = value
        else:
            entry.pop(field, None)
        if not entry:
            info.pop(resource_id, None)
        session.project = replace(session.project, resource_info=info)
        session.dirty = True

    def set_subject_info(self, session: Session, subject: str, field: str, value: str) -> None:
        """Fija un campo maestro de una materia (nombre completo, sección, color)."""
        if subject not in session.project.subjects and subject not in self._derived_subjects(
            session
        ):
            raise ConfigError(f"materia inexistente: {subject}")
        info = {k: dict(v) for k, v in session.project.subject_info.items()}
        entry = info.setdefault(subject, {})
        value = value.strip()
        if value:
            entry[field] = value
        else:
            entry.pop(field, None)
        if not entry:
            info.pop(subject, None)
        session.project = replace(session.project, subject_info=info)
        session.dirty = True

    def subject_colors(self, session: Session) -> dict[str, str]:
        """Color configurado por materia (para pintar el horario, como Untis)."""
        return {
            name: info["color"]
            for name, info in session.project.subject_info.items()
            if info.get("color")
        }

    def focus_options(self, session: Session) -> tuple[FocusOption, ...]:
        return focus_options(session.project.problem)

    def timetable(self, session: Session, focus_id: int) -> TimetableView:
        return timetable_view(session.project.problem, session.project.solution, focus_id)

    def dashboard(self, session: Session) -> DashboardStats:
        project = session.project
        tables = entity_tables(project.problem)
        stats = DashboardStats(
            project_name=str(project.manifest.get("project_name", "Proyecto")),
            teachers=len(tables.teachers.rows),
            rooms=len(tables.rooms.rows),
            groups=len(tables.groups.rows),
            subjects=len(tables.subjects.rows),
            tasks=len(project.problem.tasks),
            solved=project.solution is not None,
        )
        if project.solution is None:
            return stats
        metrics = _METRICS.compute(project.problem, project.solution)
        last = project.history[-1].get("timestamp") if project.history else None
        return replace(
            stats,
            quality_score=round(metrics.quality_score, 1),
            hard_violations=metrics.hard_violations,
            room_utilization_pct=round(metrics.room_utilization_pct, 1),
            teacher_gaps=metrics.teacher_gaps,
            last_optimized=str(last) if last is not None else None,
        )

    def validate(self, session: Session) -> ValidationReport:
        """Consolida factibilidad estructural + consistencia del ``.bjs``."""
        project = session.project
        items: list[ValidationItem] = []
        report = analyze_feasibility(self._effective_problem(project))
        for issue in report.issues:
            items.append(ValidationItem("error", issue.message, ", ".join(issue.entities)))
        try:
            from .bjs_validation import check_consistency

            warnings = check_consistency(project)
        except ConfigError as exc:
            items.append(ValidationItem("error", str(exc)))
            warnings = ()
        items.extend(ValidationItem("warning", w) for w in warnings)
        feasible = report.feasible and not any(i.severity == "error" for i in items)
        return ValidationReport(feasible=feasible, items=tuple(items))

    def available_solvers(self) -> tuple[str, ...]:
        return SOLVER_NAMES

    # --- configuración del motor (Settings) ----------------------------- #
    def engine_settings(self, session: Session) -> EngineConfig:
        return session.project.solver_config

    def update_engine_settings(
        self,
        session: Session,
        *,
        default_solver: str | None = None,
        threads: int | None = None,
        max_time_seconds: float | None = None,
        random_seed: int | None = None,
    ) -> None:
        """Actualiza la configuración del motor del proyecto (solver, hilos, tiempo)."""
        cfg = session.project.solver_config
        new = replace(
            cfg,
            default_solver=default_solver if default_solver is not None else cfg.default_solver,
            threads=threads if threads is not None else cfg.threads,
            max_time_seconds=max_time_seconds
            if max_time_seconds is not None
            else cfg.max_time_seconds,
            random_seed=random_seed if random_seed is not None else cfg.random_seed,
        )
        new.validate()
        session.project = replace(session.project, solver_config=new)
        session.dirty = True

    def reports(self, session: Session) -> tuple[ReportTable, ...]:
        """Informes del horario: carga docente, uso de aulas y resumen de calidad."""
        project = session.project
        problem = project.problem
        solution = project.solution
        if solution is None:
            aviso = ReportTable(
                "empty",
                "Sin horario",
                ("Aviso",),
                (("Genera u optimiza el horario para ver los informes.",),),
            )
            return (aviso,)

        periods: dict[int, int] = defaultdict(int)
        classes: dict[int, int] = defaultdict(int)
        for assignment in solution.assignments:
            task = problem.task_by_id(assignment.task_id)
            for rid in assignment.resource_ids:
                periods[int(rid)] += task.duration
                classes[int(rid)] += 1

        horizon = problem.horizon or 1
        teachers = sorted(
            (r for r in problem.resources if "teacher" in r.tags), key=lambda r: r.name
        )
        rooms = sorted((r for r in problem.resources if "room" in r.tags), key=lambda r: r.name)
        teacher_rows = tuple(
            (r.name, str(classes.get(int(r.id), 0)), str(periods.get(int(r.id), 0)))
            for r in teachers
        )
        room_rows = tuple(
            (
                r.name,
                str(periods.get(int(r.id), 0)),
                f"{100 * periods.get(int(r.id), 0) / horizon:.0f}%",
            )
            for r in rooms
        )
        m = _METRICS.compute(problem, solution)
        quality_rows = (
            ("Calidad", f"{m.quality_score:.1f}/100"),
            ("Uso de aulas", f"{m.room_utilization_pct:.1f}%"),
            ("Huecos docentes", str(m.teacher_gaps)),
            ("Huecos grupos", str(m.group_gaps)),
            ("Balance de carga", f"{m.teacher_load_balance_pct:.1f}%"),
            ("Violaciones duras", str(m.hard_violations)),
        )
        return (
            ReportTable(
                "teacher_load", "Carga docente", ("Docente", "Clases", "Períodos"), teacher_rows
            ),
            ReportTable("room_usage", "Uso de aulas", ("Aula", "Períodos", "Ocupación"), room_rows),
            ReportTable("quality", "Resumen de calidad", ("Indicador", "Valor"), quality_rows),
        )

    def constraints_catalog(self, session: Session) -> tuple[ConstraintRow, ...]:
        """Catálogo de restricciones editables con su estado configurado.

        Solo las instanciables (con ``factory``) y no estructurales; deduplicadas
        por plugin. El estado (activa/tier/peso) sale de la ``PluginsConfig`` del
        proyecto o, en su defecto, de los valores por defecto del catálogo.
        """
        settings = {s.id: s for s in session.project.constraints.plugins}
        rows: list[ConstraintRow] = []
        seen: set[str] = set()
        for d in CONSTRAINT_CATALOG:
            if d.plugin_name is None or d.factory is None:
                continue
            if d.plugin_name in _STRUCTURAL_NOOVERLAP or d.plugin_name in seen:
                continue
            seen.add(d.plugin_name)
            setting = settings.get(d.plugin_name)
            is_soft = d.kind is ConstraintKind.SOFT
            weight = setting.weight if setting and setting.weight is not None else d.default_weight
            tier = setting.tier if setting and setting.tier is not None else d.tier
            rows.append(
                ConstraintRow(
                    rule_id=d.plugin_name,
                    catalog_id=d.id,
                    name=d.name,
                    description=d.description,
                    kind=d.kind.value,
                    enabled=setting.enabled if setting is not None else False,
                    weight=weight if weight is not None else 1,
                    tier=tier if tier is not None else 0,
                    default_weight=d.default_weight if d.default_weight is not None else 1,
                    default_tier=d.tier if d.tier is not None else 0,
                    editable_weight=is_soft,
                    editable_tier=is_soft,
                )
            )
        return tuple(rows)

    # --- optimización ---------------------------------------------------- #
    def optimize(
        self,
        session: Session,
        *,
        solver: str | None = None,
        seed: int | None = None,
        timeout: float | None = None,
        structural_only: bool = False,
        on_event: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> SolveOutcome:
        """Resuelve/optimiza el horario. Nunca lanza: devuelve un ``SolveOutcome``.

        En caso de éxito, actualiza la sesión (solución + métricas + historial) y
        la marca *sucia*; el llamador decide cuándo persistir con ``save``.
        """
        project = session.project
        problem = self._effective_problem(project)  # aplica los bloqueos de horas
        solver_name = solver or project.solver_config.default_solver
        try:
            factory = solver_factory_for(solver_name)
            is_cpsat = solver_name == _CPSAT
            registry, boolean = build_registry(
                project.constraints, structural_only=structural_only, mip=not is_cpsat
            )
            # Ventana de almuerzo: >= 1 hora libre en el rango (necesita inicios booleanos).
            if project.lunch_window is not None and not structural_only:
                window = project.lunch_window
                registry.register(
                    LunchWindowPlugin(start=window.start, end=window.end, days=window.days)
                )
                boolean = True
            # Acoples: clases simultáneas (invariante, no-op si no hay acoples).
            registry.register(CoupledLessonsPlugin())
        except (ConfigError, ValueError) as exc:
            return SolveOutcome(False, "error", solver_name, str(exc))

        solver_config = project.solver_config.to_solver_config()
        if seed is not None:
            solver_config = replace(solver_config, random_seed=seed)
        if timeout is not None:
            solver_config = replace(solver_config, max_time_in_seconds=timeout)
        if cancel is not None:
            solver_config = replace(solver_config, should_stop=cancel.is_cancelled)

        try:
            result = run_engine(
                problem,
                registry,
                solver_factory=factory,
                solver_config=solver_config,
                boolean_starts=boolean,
                on_event=on_event,
            )
        except InfeasibleError as exc:
            return SolveOutcome(False, "infeasible", solver_name, str(exc))
        except SolveTimeoutError as exc:
            return SolveOutcome(False, "timeout", solver_name, str(exc))
        except (ConfigError, InternalError, AppError) as exc:
            return SolveOutcome(False, "error", solver_name, str(exc))

        summary = solution_summary(problem, result)
        summary["solver"] = solver_name
        run_record = {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            **summary,
        }
        session.project = replace(
            project,
            solution=result.solution,
            metrics=summary,
            history=(*project.history, run_record),
        )
        session.dirty = True
        return SolveOutcome(True, "solved", solver_name, f"optimizado con {solver_name}", summary)

    # --- edición del horario (drag&drop) -------------------------------- #
    def move_targets(self, session: Session, task_id: int) -> tuple[MoveTarget, ...]:
        """Celdas (día, período) donde la clase puede colocarse, con su factibilidad.

        Verde (``feasible``) = cabe respetando las reglas duras con el resto del
        horario fijo: su docente y su grupo están libres y hay un aula disponible.
        Rojo = no cabe (ocupado o sin aula). Es un cálculo analítico (sin solver),
        así que sirve para el resaltado en vivo mientras se arrastra.
        """
        project = session.project
        if project.solution is None:
            return ()
        problem = self._effective_problem(project)  # allowed_starts ya excluye bloqueos
        try:
            task = problem.task_by_id(TaskId(task_id))
        except Exception:
            return ()

        teacher_id = self._resource_of_tag(problem, task, "teacher#")
        group_id = self._resource_of_tag(problem, task, "group#")
        room_ids = {int(r.id) for r in problem.resources if "room" in r.tags}
        total_rooms = len(room_ids) or 1
        blocked = self._blocked_linear(project, (teacher_id, group_id))

        teacher_busy: set[int] = set()
        group_busy: set[int] = set()
        rooms_used: dict[int, set[int]] = defaultdict(set)
        for assignment in project.solution.assignments:
            if int(assignment.task_id) == task_id:
                continue  # la propia clase no bloquea su destino
            other = problem.task_by_id(assignment.task_id)
            slots = range(int(assignment.start), int(assignment.start) + other.duration)
            rids = {int(r) for r in assignment.resource_ids}
            if teacher_id in rids:
                teacher_busy.update(slots)
            if group_id in rids:
                group_busy.update(slots)
            for room in rids & room_ids:
                for slot in slots:
                    rooms_used[slot].add(room)

        valid = problem.valid_starts_for(task)
        targets: list[MoveTarget] = []
        for day, seg in enumerate(problem.grid.segments):
            for period in range(seg.length):
                start = int(seg.start) + period
                slots = range(start, start + task.duration)
                if any(s in blocked for s in slots):
                    targets.append(MoveTarget(day, period, False, "hora bloqueada"))
                elif start not in valid:
                    targets.append(MoveTarget(day, period, False, "no cabe en el día"))
                elif any(s in teacher_busy for s in slots):
                    targets.append(MoveTarget(day, period, False, "docente ocupado"))
                elif any(s in group_busy for s in slots):
                    targets.append(MoveTarget(day, period, False, "grupo ocupado"))
                elif any(len(rooms_used[s]) >= total_rooms for s in slots):
                    targets.append(MoveTarget(day, period, False, "sin aula libre"))
                else:
                    targets.append(MoveTarget(day, period, True, "disponible"))
        return tuple(targets)

    def _blocked_linear(self, project: BjsProject, resource_ids: tuple[int, ...]) -> set[int]:
        """Slots lineales reservados (bloqueo + almuerzo) para los recursos dados."""
        segments = project.problem.grid.segments
        reserved = self._reserved(project)
        out: set[int] = set()
        for rid in resource_ids:
            for day, period in reserved.get(rid, set()):
                if 0 <= day < len(segments) and 0 <= period < segments[day].length:
                    out.add(int(segments[day].start) + period)
        return out

    def move_class(
        self, session: Session, task_id: int, day: int, period: int, *, timeout: float | None = 15.0
    ) -> SolveOutcome:
        """Mueve una clase a (día, período) **sin tocar el resto** del horario.

        Fija la clase en el destino y congela todas las demás; el motor solo
        reasigna el aula. Movimiento predecible: solo tiene éxito si el destino es
        factible (ver :meth:`move_targets`), y entonces ninguna otra clase se mueve.
        """
        project = session.project
        if project.solution is None:
            return SolveOutcome(False, "error", "-", "genera un horario antes de mover clases")
        problem = self._effective_problem(project)  # respeta los bloqueos de horas
        segments = problem.grid.segments
        if not 0 <= day < len(segments):
            return SolveOutcome(False, "error", "-", "día fuera de rango")
        seg = segments[day]
        if not 0 <= period < seg.length:
            return SolveOutcome(False, "error", "-", "período fuera de rango")

        try:
            task = problem.task_by_id(TaskId(task_id))
        except Exception:
            return SolveOutcome(False, "error", "-", f"clase inexistente: {task_id}")

        target = TimeSlotIndex(int(seg.start) + period)
        if target not in problem.valid_starts_for(task):
            return SolveOutcome(False, "infeasible", "-", "no cabe ahí (bloqueada u ocupada)")

        # Problema temporal con la clase fijada en el destino; el resto, congelado.
        fixed_task = replace(task, allowed_starts=frozenset({target}))
        modified = replace(
            problem, tasks=tuple(fixed_task if t.id == task.id else t for t in problem.tasks)
        )
        config = project.solver_config.to_solver_config()
        if timeout is not None:
            config = replace(config, max_time_in_seconds=timeout)
        # Si la clase está acoplada, sus compañeras de acople se mueven con ella.
        unfrozen = {task_id}
        cid = task.attribute("coupling", -1)
        if cid >= 0:
            seq = task.attribute("cseq", 0)
            unfrozen |= {
                int(t.id)
                for t in problem.tasks
                if t.attribute("coupling", -1) == cid and t.attribute("cseq", 0) == seq
            }
        engine = ReOptimizationEngine(
            plugins=[IntervalNoOverlapPlugin(), CoupledLessonsPlugin()],
            solver_factory=solver_factory_for(_CPSAT),
        )
        result = engine.reoptimize(
            modified, project.solution, [TaskId(t) for t in unfrozen], config
        )
        if not result.solved or result.solution is None:
            return SolveOutcome(False, "infeasible", _CPSAT, "no se puede mover ahí (ocupado)")

        # Se conserva el problema original (la clase no queda fijada para siempre).
        session.project = replace(project, solution=result.solution)
        session.dirty = True
        return SolveOutcome(True, "solved", _CPSAT, "clase movida")

    @staticmethod
    def _resource_of_tag(problem: SchedulingProblem, task: Task, prefix: str) -> int:
        """Id del recurso que porta el tag único (teacher#/group#) de la tarea."""
        tag = next((r.tag for r in task.requirements if r.tag.startswith(prefix)), None)
        if tag is None:
            return -1
        for resource in problem.resources:
            if tag in resource.tags:
                return int(resource.id)
        return -1

    # --- disponibilidad / bloqueo de horas (Fase 7 E1) ------------------ #
    def availability(self, session: Session, resource_id: int) -> frozenset[tuple[int, int]]:
        """Horas (día, período) BLOQUEADAS de un docente o grupo."""
        return frozenset(session.project.availability.get(resource_id, ()))

    def can_block(self, session: Session, resource_id: int) -> bool:
        """Solo docentes y grupos se bloquean (portan un tag único requerible)."""
        res = next((r for r in session.project.problem.resources if int(r.id) == resource_id), None)
        return res is not None and ("teacher" in res.tags or "group" in res.tags)

    def set_blocked(self, session: Session, resource_id: int, slots: set[tuple[int, int]]) -> None:
        """Fija el conjunto de horas bloqueadas de un recurso (reemplaza)."""
        availability = dict(session.project.availability)
        if slots:
            availability[resource_id] = tuple(sorted(slots))
        else:
            availability.pop(resource_id, None)
        session.project = replace(session.project, availability=availability)
        session.dirty = True

    def toggle_block(self, session: Session, resource_id: int, day: int, period: int) -> bool:
        """Alterna el bloqueo de una hora; devuelve el nuevo estado (True = bloqueada)."""
        current = set(self.availability(session, resource_id))
        cell = (day, period)
        if cell in current:
            current.discard(cell)
            blocked = False
        else:
            current.add(cell)
            blocked = True
        self.set_blocked(session, resource_id, current)
        return blocked

    # --- ventana de almuerzo (Fase 7 E2) -------------------------------- #
    def lunch_window(self, session: Session) -> LunchWindow | None:
        """Ventana de almuerzo configurada (rango de períodos con >= 1 hora libre)."""
        return session.project.lunch_window

    def set_lunch_window(
        self, session: Session, start: int, end: int, days: tuple[int, ...] | None = None
    ) -> None:
        """Define la ventana de almuerzo: entre ``start`` y ``end`` (0-based, inclusive).

        El motor garantizará que cada docente tenga al menos una hora libre en ese
        rango, en los ``days`` indicados (vacío/None = todos). No fija la hora: la
        elige el solver donde queden huecos.
        """
        if end < start:
            raise ConfigError("la ventana de almuerzo termina antes de empezar")
        window = LunchWindow(start=start, end=end, days=tuple(days) if days else ())
        session.project = replace(session.project, lunch_window=window)
        session.dirty = True

    def clear_lunch_window(self, session: Session) -> None:
        session.project = replace(session.project, lunch_window=None)
        session.dirty = True

    @staticmethod
    def _reserved(project: BjsProject) -> dict[int, set[tuple[int, int]]]:
        """Horas bloqueadas por recurso (disponibilidad; el almuerzo es una ventana)."""
        merged: dict[int, set[tuple[int, int]]] = defaultdict(set)
        for rid, pairs in project.availability.items():
            merged[rid].update(pairs)
        return merged

    @staticmethod
    def _week_blocked(week: SchoolWeek, segments: tuple[Segment, ...]) -> set[int]:
        """Slots lineales no disponibles para una semana lectiva: recreos, períodos

        por encima del tope y días fuera del número de días lectivos.
        """
        blocked: set[int] = set()
        breaks = set(week.breaks)
        for day, seg in enumerate(segments):
            if week.days and day >= week.days:
                blocked.update(range(int(seg.start), int(seg.end)))
                continue
            for period in range(seg.length):
                if period in breaks or (0 < week.max_periods <= period):
                    blocked.add(int(seg.start) + period)
        return blocked

    def _effective_problem(self, project: BjsProject) -> SchedulingProblem:
        """Aplica disponibilidad + almuerzo + semana lectiva: recorta ``allowed_starts``."""
        reserved = self._reserved(project)
        problem = project.problem
        segments = problem.grid.segments
        tag_blocked: dict[str, set[int]] = {}
        for rid, pairs in reserved.items():
            res = next((r for r in problem.resources if int(r.id) == rid), None)
            if res is None:
                continue
            tag = next((t for t in res.tags if t.startswith(("teacher#", "group#"))), None)
            if tag is None:
                continue
            slots = tag_blocked.setdefault(tag, set())
            for day, period in pairs:
                if 0 <= day < len(segments) and 0 <= period < segments[day].length:
                    slots.add(int(segments[day].start) + period)
        # Semanas lectivas: recreos/tope por clase (cacheado por índice de semana).
        week_blocked: dict[int, set[int]] = {}
        weeks = project.school_weeks
        uses_weeks = weeks and any(t.attribute("school_week", -1) >= 0 for t in problem.tasks)
        if not tag_blocked and not uses_weeks:
            return problem

        def blocked_for(task: Task) -> set[int]:
            blocked: set[int] = set()
            for req in task.requirements:
                blocked |= tag_blocked.get(req.tag, set())
            widx = task.attribute("school_week", -1)
            if 0 <= widx < len(weeks):
                if widx not in week_blocked:
                    week_blocked[widx] = self._week_blocked(weeks[widx], segments)
                blocked |= week_blocked[widx]
            return blocked

        new_tasks: list[Task] = []
        for task in problem.tasks:
            blocked = blocked_for(task)
            if not blocked:
                new_tasks.append(task)
                continue
            allowed = frozenset(
                start
                for start in problem.valid_starts_for(task)
                if not any((start + off) in blocked for off in range(task.duration))
            )
            new_tasks.append(replace(task, allowed_starts=allowed))
        return replace(problem, tasks=tuple(new_tasks))

    # --- CRUD de entidades y carga horaria (Fase 7 E4) ------------------ #
    def add_teacher(self, session: Session, name: str) -> int:
        """Crea un docente nuevo. Devuelve su id."""
        return self._add_resource(session, name, ("teacher", "teacher#{id}"))

    def add_group(self, session: Session, name: str, size: int = 30) -> int:
        """Crea un grupo nuevo (con su tamaño). Devuelve su id."""
        return self._add_resource(
            session, name, ("group", "group#{id}"), attributes=(("size", size),)
        )

    def add_room(self, session: Session, name: str, seats: int = 30) -> int:
        """Crea un aula nueva (con sus cupos). Devuelve su id."""
        return self._add_resource(
            session, name, ("room", "room#{id}", "roomtype#normal"), attributes=(("seats", seats),)
        )

    def _add_resource(
        self,
        session: Session,
        name: str,
        tags: tuple[str, ...],
        *,
        attributes: tuple[tuple[str, int], ...] = (),
    ) -> int:
        if not name.strip():
            raise ConfigError("el nombre no puede estar vacío")
        project = session.project
        new_id = max((int(r.id) for r in project.problem.resources), default=-1) + 1
        resolved = frozenset(tag.format(id=new_id) for tag in tags)
        resource = Resource(ResourceId(new_id), name.strip(), resolved, attributes=attributes)
        new_problem = replace(project.problem, resources=(*project.problem.resources, resource))
        session.project = self._structural_change(project, new_problem)
        session.dirty = True
        return new_id

    def remove_resource(self, session: Session, resource_id: int) -> None:
        """Elimina un docente/grupo/aula y las clases que dependen de él."""
        project = session.project
        problem = project.problem
        target = next((r for r in problem.resources if int(r.id) == resource_id), None)
        if target is None:
            raise ConfigError(f"recurso inexistente: {resource_id}")
        unique = {t for t in target.tags if t.startswith(("teacher#", "group#", "room#"))}
        resources = tuple(r for r in problem.resources if int(r.id) != resource_id)
        tasks = tuple(
            t for t in problem.tasks if not any(req.tag in unique for req in t.requirements)
        )
        if not resources or not tasks:
            raise ConfigError("no se puede eliminar: dejaría el proyecto sin recursos o sin clases")
        availability = {k: v for k, v in project.availability.items() if k != resource_id}
        resource_info = {k: v for k, v in project.resource_info.items() if k != resource_id}
        session.project = replace(
            self._structural_change(project, replace(problem, resources=resources, tasks=tasks)),
            availability=availability,
            resource_info=resource_info,
        )
        session.dirty = True

    def add_load(
        self,
        session: Session,
        group_ids: list[int],
        subject: str,
        teacher_ids: list[int],
        sessions: int,
        *,
        room_ids: list[int] | None = None,
        duration: int = 1,
        school_week: int = -1,
    ) -> list[int]:
        """Añade carga horaria: crea ``sessions`` clases de ``subject`` (una asignación).

        Una asignación puede acoplar **varios docentes**, **varios grupos** y
        **varias aulas** (clase combinada / co-docencia, la *Kopplung* de Untis):
        cada clase requiere a la vez todos ellos. Si no se dan aulas concretas, el
        solver elige una del pool. ``school_week`` (índice, -1 = ninguna) asigna la
        semana lectiva de la lección. Devuelve los ids de las clases creadas.
        """
        if not subject.strip():
            raise ConfigError("la materia no puede estar vacía")
        if sessions < 1:
            raise ConfigError("el número de sesiones debe ser >= 1")
        if not group_ids or not teacher_ids:
            raise ConfigError("una asignación necesita al menos un grupo y un docente")
        problem = session.project.problem

        def unique_tag(rid: int, kind: str, prefix: str) -> str:
            res = next((r for r in problem.resources if int(r.id) == rid), None)
            if res is None or kind not in res.tags:
                raise ConfigError(f"{kind} inexistente: {rid}")
            return next(t for t in res.tags if t.startswith(prefix))

        teacher_reqs = [
            ResourceRequirement(unique_tag(t, "teacher", "teacher#")) for t in teacher_ids
        ]
        group_tags = [unique_tag(g, "group", "group#") for g in group_ids]
        group_reqs = [ResourceRequirement(tag) for tag in group_tags]
        if room_ids:
            room_reqs = [ResourceRequirement(unique_tag(r, "room", "room#")) for r in room_ids]
        else:
            room_reqs = [ResourceRequirement("room")]
        requirements = tuple(teacher_reqs + group_reqs + room_reqs)

        size = sum(
            next(r for r in problem.resources if r.has_tag(tag)).attribute("size", 30)
            for tag in group_tags
        )
        base = max((int(t.id) for t in problem.tasks), default=-1) + 1
        tag_key = "-".join(str(g) for g in group_ids)
        attrs: tuple[tuple[str, int], ...] = (("size", size),)
        if 0 <= school_week < len(session.project.school_weeks):
            attrs = (*attrs, ("school_week", school_week))
        new_tasks = [
            Task(
                TaskId(base + s),
                f"{subject.strip()} · g{tag_key}#{s}",
                duration,
                requirements,
                attributes=attrs,
            )
            for s in range(sessions)
        ]
        subject_name = subject.strip()
        subjects = session.project.subjects
        if subject_name not in subjects:
            subjects = (*subjects, subject_name)
        session.project = replace(
            self._structural_change(
                session.project, replace(problem, tasks=(*problem.tasks, *new_tasks))
            ),
            subjects=subjects,
        )
        session.dirty = True
        return [base + s for s in range(sessions)]

    # --- lecciones (vista de carga estilo Untis) ------------------------ #
    def lessons(
        self, session: Session, *, group_id: int | None = None, teacher_id: int | None = None
    ) -> tuple[LessonRow, ...]:
        """Lecciones del proyecto, filtrables por grupo o por docente (como Untis).

        Las lecciones **acopladas** a una visible se incluyen inmediatamente
        después (aunque sean de otro grupo/docente), como las sub-filas de la
        vista de lecciones de Untis.
        """
        all_rows = lesson_rows(session.project.problem)
        rows: tuple[LessonRow, ...] = all_rows
        if group_id is not None:
            rows = tuple(r for r in rows if group_id in r.group_ids)
        if teacher_id is not None:
            rows = tuple(r for r in rows if teacher_id in r.teacher_ids)
        if group_id is None and teacher_id is None:
            return rows

        by_coupling: dict[int, list[LessonRow]] = defaultdict(list)
        for row in all_rows:
            if row.coupling_id >= 0:
                by_coupling[row.coupling_id].append(row)
        expanded: list[LessonRow] = []
        seen: set[str] = set()
        for row in rows:
            if row.key in seen:
                continue
            expanded.append(row)
            seen.add(row.key)
            if row.coupling_id >= 0:
                for partner in by_coupling.get(row.coupling_id, []):
                    if partner.key not in seen:
                        expanded.append(partner)
                        seen.add(partner.key)
        return tuple(expanded)

    def remove_lesson(self, session: Session, task_ids: list[int]) -> None:
        """Elimina una lección completa (todas sus sesiones)."""
        ids = set(task_ids)
        problem = session.project.problem
        keep = tuple(t for t in problem.tasks if int(t.id) not in ids)
        if len(keep) == len(problem.tasks):
            return
        if not keep:
            raise ConfigError("no se puede eliminar: dejaría el proyecto sin clases")
        session.project = self._structural_change(session.project, replace(problem, tasks=keep))
        session.dirty = True

    def set_lesson_hours(self, session: Session, task_ids: list[int], hours: int) -> None:
        """Cambia las horas semanales (HHs) de una lección: añade o quita sesiones."""
        if hours < 1:
            raise ConfigError("las horas semanales deben ser >= 1")
        problem = session.project.problem
        ids = sorted(set(task_ids))
        current = [t for t in problem.tasks if int(t.id) in set(ids)]
        if not current:
            raise ConfigError("lección inexistente")
        if hours == len(current):
            return
        if hours < len(current):
            drop = {int(t.id) for t in current[hours:]}
            tasks = tuple(t for t in problem.tasks if int(t.id) not in drop)
        else:
            template = current[0]
            subject = template.name.split(" · ", 1)[0]
            base = max(int(t.id) for t in problem.tasks) + 1
            extra = tuple(
                replace(template, id=TaskId(base + i), name=f"{subject} · x#{base + i}")
                for i in range(hours - len(current))
            )
            tasks = (*problem.tasks, *extra)
        session.project = self._structural_change(session.project, replace(problem, tasks=tasks))
        session.dirty = True

    def set_lesson_rooms(self, session: Session, task_ids: list[int], room_ids: list[int]) -> None:
        """Fija las aulas de una lección (vacío = vuelve al pool y el motor elige)."""
        problem = session.project.problem
        ids = set(task_ids)
        if not any(int(t.id) in ids for t in problem.tasks):
            raise ConfigError("lección inexistente")
        if room_ids:
            room_reqs = tuple(
                ResourceRequirement(self._room_unique_tag(problem, rid)) for rid in room_ids
            )
        else:
            room_reqs = (ResourceRequirement("room"),)

        def rebuilt(task: Task) -> Task:
            keep = tuple(r for r in task.requirements if r.tag.startswith(("teacher#", "group#")))
            return replace(task, requirements=keep + room_reqs)

        tasks = tuple(rebuilt(t) if int(t.id) in ids else t for t in problem.tasks)
        session.project = self._structural_change(session.project, replace(problem, tasks=tasks))
        session.dirty = True

    @staticmethod
    def _room_unique_tag(problem: SchedulingProblem, room_id: int) -> str:
        res = next((r for r in problem.resources if int(r.id) == room_id), None)
        if res is None or "room" not in res.tags:
            raise ConfigError(f"aula inexistente: {room_id}")
        return next(t for t in res.tags if t.startswith("room#"))

    def set_lesson_subject(self, session: Session, task_ids: list[int], subject: str) -> None:
        """Cambia la materia de una lección (edición en celda, como Excel)."""
        subject = subject.strip()
        if not subject:
            raise ConfigError("la materia no puede estar vacía")
        problem = session.project.problem
        ids = set(task_ids)
        if not any(int(t.id) in ids for t in problem.tasks):
            raise ConfigError("lección inexistente")
        tasks = tuple(
            replace(t, name=f"{subject} · {t.name.split(' · ', 1)[1]}")
            if int(t.id) in ids and " · " in t.name
            else (replace(t, name=f"{subject} · x#{int(t.id)}") if int(t.id) in ids else t)
            for t in problem.tasks
        )
        subjects = session.project.subjects
        if subject not in subjects:
            subjects = (*subjects, subject)
        session.project = replace(
            self._structural_change(session.project, replace(problem, tasks=tasks)),
            subjects=subjects,
        )
        session.dirty = True

    def set_lesson_teachers(
        self, session: Session, task_ids: list[int], teacher_ids: list[int]
    ) -> None:
        """Cambia los docentes de una lección (uno o varios: co-docencia)."""
        if not teacher_ids:
            raise ConfigError("una lección necesita al menos un docente")
        problem = session.project.problem
        reqs = tuple(
            ResourceRequirement(self._unique_tag_of(problem, t, "teacher")) for t in teacher_ids
        )
        self._rebuild_lesson_reqs(session, task_ids, keep=("group#",), extra=reqs)

    def set_lesson_groups(
        self, session: Session, task_ids: list[int], group_ids: list[int]
    ) -> None:
        """Cambia los grupos de una lección (uno o varios: clases combinadas)."""
        if not group_ids:
            raise ConfigError("una lección necesita al menos un grupo")
        problem = session.project.problem
        reqs = tuple(
            ResourceRequirement(self._unique_tag_of(problem, g, "group")) for g in group_ids
        )
        self._rebuild_lesson_reqs(session, task_ids, keep=("teacher#",), extra=reqs)

    def _rebuild_lesson_reqs(
        self,
        session: Session,
        task_ids: list[int],
        *,
        keep: tuple[str, ...],
        extra: tuple[ResourceRequirement, ...],
    ) -> None:
        problem = session.project.problem
        ids = set(task_ids)
        if not any(int(t.id) in ids for t in problem.tasks):
            raise ConfigError("lección inexistente")

        def rebuilt(task: Task) -> Task:
            kept = tuple(r for r in task.requirements if r.tag.startswith(keep))
            # "room", "room#N" y "roomtype#X" empiezan todos por "room".
            rooms = tuple(r for r in task.requirements if r.tag.startswith("room"))
            return replace(task, requirements=kept + extra + rooms)

        tasks = tuple(rebuilt(t) if int(t.id) in ids else t for t in problem.tasks)
        session.project = self._structural_change(session.project, replace(problem, tasks=tasks))
        session.dirty = True

    @staticmethod
    def _unique_tag_of(problem: SchedulingProblem, resource_id: int, kind: str) -> str:
        res = next((r for r in problem.resources if int(r.id) == resource_id), None)
        if res is None or kind not in res.tags:
            raise ConfigError(f"{kind} inexistente: {resource_id}")
        return next(t for t in res.tags if t.startswith(f"{kind}#"))

    # --- acoples (clases simultáneas, la Kopplung de Untis) -------------- #
    def couple_lessons(self, session: Session, lessons_task_ids: list[list[int]]) -> int:
        """Acopla lecciones: sus sesiones ocurren **a la misma hora**.

        Permite varios profesores en varios salones a la vez, con la misma
        materia o materias distintas. Las lecciones deben tener las mismas HHs
        (cada sesión i de una va con la sesión i de las demás). Devuelve el id
        del acople.
        """
        if len(lessons_task_ids) < 2:
            raise ConfigError("selecciona al menos dos lecciones para acoplar")
        groups = [sorted(set(ids)) for ids in lessons_task_ids]
        if len({len(g) for g in groups}) != 1:
            raise ConfigError("las lecciones a acoplar deben tener las mismas HHs")
        problem = session.project.problem
        by_id = {int(t.id): t for t in problem.tasks}
        for g in groups:
            for tid in g:
                if tid not in by_id:
                    raise ConfigError("lección inexistente")
        cid = max((t.attribute("coupling", -1) for t in problem.tasks), default=-1) + 1

        stamped: dict[int, tuple[int, int]] = {}
        for g in groups:
            for seq, tid in enumerate(g):
                stamped[tid] = (cid, seq)

        def stamp(task: Task) -> Task:
            mark = stamped.get(int(task.id))
            if mark is None:
                return task
            attrs = dict(task.attributes)
            attrs["coupling"], attrs["cseq"] = mark
            return replace(task, attributes=tuple(attrs.items()))

        tasks = tuple(stamp(t) for t in problem.tasks)
        session.project = self._structural_change(session.project, replace(problem, tasks=tasks))
        session.dirty = True
        return cid

    def uncouple_lesson(self, session: Session, task_ids: list[int]) -> None:
        """Deshace el acople completo al que pertenece la lección dada."""
        problem = session.project.problem
        ids = set(task_ids)
        cids = {
            t.attribute("coupling", -1)
            for t in problem.tasks
            if int(t.id) in ids and t.attribute("coupling", -1) >= 0
        }
        if not cids:
            return

        def clean(task: Task) -> Task:
            if task.attribute("coupling", -1) not in cids:
                return task
            attrs = tuple((k, v) for k, v in task.attributes if k not in ("coupling", "cseq"))
            return replace(task, attributes=attrs)

        tasks = tuple(clean(t) for t in problem.tasks)
        session.project = self._structural_change(session.project, replace(problem, tasks=tasks))
        session.dirty = True

    # --- materias (entidad de primera clase, Fase 7 E4) ----------------- #
    def add_subject(self, session: Session, name: str) -> None:
        """Da de alta una materia (aunque aún no tenga clases)."""
        name = name.strip()
        if not name:
            raise ConfigError("el nombre de la materia no puede estar vacío")
        if name in session.project.subjects or name in self._derived_subjects(session):
            raise ConfigError(f"la materia ya existe: {name}")
        session.project = replace(session.project, subjects=(*session.project.subjects, name))
        session.dirty = True

    def rename_subject(self, session: Session, old: str, new: str) -> None:
        """Renombra una materia (en la lista y en los nombres de sus clases)."""
        new = new.strip()
        if not new:
            raise ConfigError("el nombre de la materia no puede estar vacío")
        project = session.project
        subjects = tuple(new if s == old else s for s in project.subjects)
        if old not in project.subjects and old not in self._derived_subjects(session):
            raise ConfigError(f"materia inexistente: {old}")
        tasks = tuple(
            replace(t, name=f"{new} · {t.name.split(' · ', 1)[1]}")
            if t.name.split(" · ", 1)[0] == old and " · " in t.name
            else t
            for t in project.problem.tasks
        )
        subject_info = {(new if k == old else k): v for k, v in project.subject_info.items()}
        session.project = replace(
            self._structural_change(project, replace(project.problem, tasks=tasks)),
            subjects=subjects if old in project.subjects else project.subjects,
            subject_info=subject_info,
        )
        session.dirty = True

    def remove_subject(self, session: Session, subject: str) -> None:
        """Elimina una materia: la quita del alta y borra todas sus clases."""
        project = session.project
        problem = project.problem
        keep = tuple(t for t in problem.tasks if t.name.split(" · ", 1)[0] != subject)
        if not keep:
            raise ConfigError("no se puede eliminar: dejaría el proyecto sin clases")
        subjects = tuple(s for s in project.subjects if s != subject)
        subject_info = {k: v for k, v in project.subject_info.items() if k != subject}
        session.project = replace(
            self._structural_change(project, replace(problem, tasks=keep)),
            subjects=subjects,
            subject_info=subject_info,
        )
        session.dirty = True

    def _derived_subjects(self, session: Session) -> set[str]:
        return {t.name.split(" · ", 1)[0] for t in session.project.problem.tasks}

    # --- semanas lectivas (marcos horarios por sección, Fase 7 E3) ------ #
    def grid_size(self, session: Session) -> tuple[int, int]:
        """(días, períodos por día) de la rejilla del proyecto."""
        segments = session.project.problem.grid.segments
        return len(segments), max(seg.length for seg in segments)

    def school_weeks(self, session: Session) -> tuple[SchoolWeek, ...]:
        """Semanas lectivas definidas (marcos horarios por sección)."""
        return session.project.school_weeks

    def add_school_week(
        self, session: Session, name: str, *, days: int = 5, max_periods: int = 0
    ) -> int:
        """Crea una semana lectiva (marco horario). Devuelve su índice."""
        name = name.strip()
        if not name:
            raise ConfigError("el nombre de la semana lectiva no puede estar vacío")
        weeks = session.project.school_weeks
        if any(w.name == name for w in weeks):
            raise ConfigError(f"la semana lectiva ya existe: {name}")
        week = SchoolWeek(name=name, days=days, max_periods=max_periods)
        session.project = replace(session.project, school_weeks=(*weeks, week))
        session.dirty = True
        return len(weeks)

    def rename_school_week(self, session: Session, index: int, name: str) -> None:
        """Renombra una semana lectiva."""
        name = name.strip()
        if not name:
            raise ConfigError("el nombre de la semana lectiva no puede estar vacío")
        weeks = self._week_at(session, index)
        session.project = replace(
            session.project,
            school_weeks=tuple(
                replace(w, name=name) if i == index else w for i, w in enumerate(weeks)
            ),
        )
        session.dirty = True

    def remove_school_week(self, session: Session, index: int) -> None:
        """Elimina una semana lectiva y la desasigna de las lecciones que la usaban."""
        weeks = self._week_at(session, index)
        remaining = tuple(w for i, w in enumerate(weeks) if i != index)
        problem = session.project.problem

        def remap(task: Task) -> Task:
            widx = task.attribute("school_week", -1)
            if widx < 0:
                return task
            if widx == index:
                attrs = tuple((k, v) for k, v in task.attributes if k != "school_week")
            elif widx > index:
                attrs = tuple((k, v - 1 if k == "school_week" else v) for k, v in task.attributes)
            else:
                return task
            return replace(task, attributes=attrs)

        tasks = tuple(remap(t) for t in problem.tasks)
        session.project = replace(
            self._structural_change(session.project, replace(problem, tasks=tasks)),
            school_weeks=remaining,
        )
        session.dirty = True

    def set_school_week_field(self, session: Session, index: int, field: str, value: int) -> None:
        """Cambia un campo entero de la semana lectiva (días, tope, corte, etc.)."""
        week = self._week_at(session, index)[index]
        if field == "days":
            updated = replace(week, days=value)
        elif field == "max_periods":
            updated = replace(week, max_periods=value)
        elif field == "afternoon_from":
            updated = replace(week, afternoon_from=value)
        elif field == "first_day":
            updated = replace(week, first_day=value)
        elif field == "first_hour":
            updated = replace(week, first_hour=value)
        else:
            raise ConfigError(f"campo de semana lectiva inválido: {field}")
        self._store_week(session, index, updated)

    def set_school_week_period(
        self, session: Session, index: int, period: int, start: str, end: str
    ) -> None:
        """Fija las horas de reloj (presentacionales) de un período de la semana."""
        if period < 0:
            raise ConfigError("período inválido")
        week = self._week_at(session, index)[index]
        periods = list(week.periods)
        while len(periods) <= period:
            periods.append(SchoolPeriod())
        periods[period] = SchoolPeriod(start=start.strip(), end=end.strip())
        self._store_week(session, index, replace(week, periods=tuple(periods)))

    def toggle_school_week_break(self, session: Session, index: int, period: int) -> bool:
        """Alterna un recreo (período no lectivo). Devuelve el nuevo estado."""
        week = self._week_at(session, index)[index]
        breaks = set(week.breaks)
        if period in breaks:
            breaks.discard(period)
            is_break = False
        else:
            breaks.add(period)
            is_break = True
        self._store_week(session, index, replace(week, breaks=tuple(sorted(breaks))))
        return is_break

    def lesson_school_week(self, session: Session, task_ids: list[int]) -> int:
        """Semana lectiva asignada a una lección (-1 = ninguna)."""
        ids = set(task_ids)
        for task in session.project.problem.tasks:
            if int(task.id) in ids:
                return task.attribute("school_week", -1)
        return -1

    def set_lesson_school_week(self, session: Session, task_ids: list[int], index: int) -> None:
        """Asigna (o quita, con -1) la semana lectiva de una lección."""
        if index >= len(session.project.school_weeks):
            raise ConfigError(f"semana lectiva inexistente: {index}")
        problem = session.project.problem
        ids = set(task_ids)
        if not any(int(t.id) in ids for t in problem.tasks):
            raise ConfigError("lección inexistente")

        def stamp(task: Task) -> Task:
            if int(task.id) not in ids:
                return task
            attrs = [(k, v) for k, v in task.attributes if k != "school_week"]
            if index >= 0:
                attrs.append(("school_week", index))
            return replace(task, attributes=tuple(attrs))

        tasks = tuple(stamp(t) for t in problem.tasks)
        session.project = self._structural_change(session.project, replace(problem, tasks=tasks))
        session.dirty = True

    def _week_at(self, session: Session, index: int) -> tuple[SchoolWeek, ...]:
        weeks = session.project.school_weeks
        if not 0 <= index < len(weeks):
            raise ConfigError(f"semana lectiva inexistente: {index}")
        return weeks

    def _store_week(self, session: Session, index: int, week: SchoolWeek) -> None:
        weeks = session.project.school_weeks
        session.project = replace(
            session.project,
            school_weeks=tuple(week if i == index else w for i, w in enumerate(weeks)),
        )
        session.dirty = True

    @staticmethod
    def _structural_change(project: BjsProject, problem: SchedulingProblem) -> BjsProject:
        """Aplica un cambio estructural: invalida la solución y las métricas previas."""
        return replace(project, problem=problem, solution=None, metrics=None)

    # --- edición básica -------------------------------------------------- #
    def rename_resource(self, session: Session, resource_id: int, name: str) -> None:
        """Renombra un recurso (docente/aula/grupo)."""
        self._replace_resource(session, resource_id, lambda r: replace(r, name=name))

    def set_room_seats(self, session: Session, resource_id: int, seats: int) -> None:
        """Cambia la capacidad (cupos) de un aula."""

        def mutate(res: Resource) -> Resource:
            attrs = dict(res.attributes)
            attrs["seats"] = seats
            return replace(res, attributes=tuple(attrs.items()))

        self._replace_resource(session, resource_id, mutate)

    def set_group_size(self, session: Session, resource_id: int, size: int) -> None:
        """Cambia el tamaño de un grupo."""

        def mutate(res: Resource) -> Resource:
            attrs = dict(res.attributes)
            attrs["size"] = size
            return replace(res, attributes=tuple(attrs.items()))

        self._replace_resource(session, resource_id, mutate)

    def set_rule(
        self,
        session: Session,
        rule_id: str,
        *,
        enabled: bool | None = None,
        weight: int | None = None,
        tier: int | None = None,
    ) -> None:
        """Activa/desactiva o repondera una restricción del catálogo."""
        project = session.project
        settings = list(project.constraints.plugins)
        for i, setting in enumerate(settings):
            if setting.id == rule_id:
                settings[i] = replace(
                    setting,
                    enabled=setting.enabled if enabled is None else enabled,
                    weight=setting.weight if weight is None else weight,
                    tier=setting.tier if tier is None else tier,
                )
                break
        else:
            settings.append(
                PluginSetting(
                    id=rule_id,
                    enabled=True if enabled is None else enabled,
                    weight=weight,
                    tier=tier,
                )
            )
        new_constraints = PluginsConfig(tuple(settings))
        new_constraints.validate()
        session.project = replace(project, constraints=new_constraints)
        session.dirty = True

    def _replace_resource(
        self, session: Session, resource_id: int, mutate: Callable[[Resource], Resource]
    ) -> None:
        project = session.project
        found = False
        new_resources: list[Resource] = []
        for res in project.problem.resources:
            if int(res.id) == resource_id:
                new_resources.append(mutate(res))
                found = True
            else:
                new_resources.append(res)
        if not found:
            raise ConfigError(f"recurso inexistente: {resource_id}")
        new_problem = replace(project.problem, resources=tuple(new_resources))
        session.project = replace(project, problem=new_problem)
        session.dirty = True


__all__ = [
    "CancelToken",
    "EngineConfig",
    "EngineService",
    "Session",
    "SolveOutcome",
]
