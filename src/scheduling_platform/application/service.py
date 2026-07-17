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

from ..core.ids import TaskId, TimeSlotIndex
from ..core.problem import SchedulingProblem
from ..core.resource import Resource
from ..core.task import Task
from ..engine import MetricsEngine, ReOptimizationEngine
from ..pipeline.events import ProgressCallback
from ..plugins import CONSTRAINT_CATALOG, ConstraintKind
from ..plugins.catalog.structural import IntervalNoOverlapPlugin
from .cancel import CancelToken
from .commands.solve import solution_summary
from .config import EngineConfig, PluginsConfig, PluginSetting
from .errors import AppError, ConfigError, InfeasibleError, InternalError, SolveTimeoutError
from .project import BjsProject, new_project, open_project, save_project
from .runtime import analyze_feasibility, build_registry, run_engine
from .solvers import SOLVER_NAMES, solver_factory_for
from .view_models import (
    ConstraintRow,
    DashboardStats,
    EntityTables,
    FocusOption,
    MoveTarget,
    ReportTable,
    SolveOutcome,
    TimetableView,
    ValidationItem,
    ValidationReport,
    entity_tables,
    focus_options,
    timetable_view,
)

_METRICS = MetricsEngine()
_CPSAT = "ortools_cpsat"
# El no-solape estructural es un invariante del motor (siempre activo vía
# build_registry); no se ofrece como restricción editable en la GUI.
_STRUCTURAL_NOOVERLAP = frozenset({"interval_no_overlap", "resource_no_overlap"})


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
        return entity_tables(session.project.problem)

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
        report = analyze_feasibility(project.problem)
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
        solver_name = solver or project.solver_config.default_solver
        try:
            factory = solver_factory_for(solver_name)
            is_cpsat = solver_name == _CPSAT
            registry, boolean = build_registry(
                project.constraints, structural_only=structural_only, mip=not is_cpsat
            )
        except ConfigError as exc:
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
                project.problem,
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

        summary = solution_summary(project.problem, result)
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
        problem = project.problem
        try:
            task = problem.task_by_id(TaskId(task_id))
        except Exception:
            return ()

        teacher_id = self._resource_of_tag(problem, task, "teacher#")
        group_id = self._resource_of_tag(problem, task, "group#")
        room_ids = {int(r.id) for r in problem.resources if "room" in r.tags}
        total_rooms = len(room_ids) or 1

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

        valid = problem.grid.valid_starts(task.duration, task.same_segment)
        targets: list[MoveTarget] = []
        for day, seg in enumerate(problem.grid.segments):
            for period in range(seg.length):
                start = int(seg.start) + period
                slots = range(start, start + task.duration)
                if start not in valid:
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
        problem = project.problem
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
        if target not in problem.grid.valid_starts(task.duration, task.same_segment):
            return SolveOutcome(False, "infeasible", "-", "la clase no cabe en ese período")

        # Problema temporal con la clase fijada en el destino; el resto, congelado.
        fixed_task = replace(task, allowed_starts=frozenset({target}))
        modified = replace(
            problem, tasks=tuple(fixed_task if t.id == task.id else t for t in problem.tasks)
        )
        config = project.solver_config.to_solver_config()
        if timeout is not None:
            config = replace(config, max_time_in_seconds=timeout)
        engine = ReOptimizationEngine(
            plugins=[IntervalNoOverlapPlugin()], solver_factory=solver_factory_for(_CPSAT)
        )
        result = engine.reoptimize(modified, project.solution, [TaskId(task_id)], config)
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
