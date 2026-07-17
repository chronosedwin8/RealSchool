"""Puente Qt sobre la Fachada ``EngineService`` (Fase 6).

Adapta la API interna del motor al mundo de señales de Qt: mantiene la sesión
abierta, reemite los cambios como señales para que los módulos se refresquen, y
corre la optimización en un ``QThread`` (``SolveWorker``) publicando el progreso
en vivo. La cancelación usa el ``CancelToken`` de la Fachada. Ningún módulo de la
UI habla con el motor salvo a través de este puente.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from scheduling_platform.application import (
    BjsProject,
    CancelToken,
    ConstraintRow,
    DashboardStats,
    EngineConfig,
    EngineService,
    EntityTables,
    FocusOption,
    LessonRow,
    LunchWindow,
    MoveTarget,
    ProgressEvent,
    ReportTable,
    Session,
    SolveOutcome,
    TimetableView,
    ValidationReport,
)


class SolveWorker(QThread):
    """Ejecuta ``optimize`` fuera del hilo de la UI y emite progreso + resultado."""

    progressed = Signal(int, str)
    finished_outcome = Signal(object)

    def __init__(
        self,
        service: EngineService,
        session: Session,
        *,
        solver: str,
        seed: int | None,
        timeout: float | None,
        structural_only: bool,
        cancel: CancelToken,
    ) -> None:
        super().__init__()
        self._service = service
        self._session = session
        self._solver = solver
        self._seed = seed
        self._timeout = timeout
        self._structural_only = structural_only
        self._cancel = cancel

    def run(self) -> None:
        outcome = self._service.optimize(
            self._session,
            solver=self._solver,
            seed=self._seed,
            timeout=self._timeout,
            structural_only=self._structural_only,
            on_event=self._on_event,
            cancel=self._cancel,
        )
        self.finished_outcome.emit(outcome)

    def _on_event(self, event: ProgressEvent) -> None:
        # Corre en el hilo del worker; la conexión en cola lo entrega a la UI.
        self.progressed.emit(event.percentage, event.stage)


class EngineBridge(QObject):
    """Estado de la app (sesión) + señales; única puerta de la UI al motor."""

    session_opened = Signal()
    session_changed = Signal()
    dirty_changed = Signal(bool)
    status_message = Signal(str)
    notification = Signal(str, str)  # nivel ("info"/"success"/"error"), texto
    solve_progress = Signal(int, str)
    solve_finished = Signal(object)

    def __init__(self, service: EngineService | None = None) -> None:
        super().__init__()
        self._service = service or EngineService()
        self._session: Session | None = None
        self._cancel = CancelToken()
        self._worker: SolveWorker | None = None
        self._undo_stack: list[BjsProject] = []

    # --- sesión --------------------------------------------------------- #
    @property
    def has_session(self) -> bool:
        return self._session is not None

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("no hay ningún proyecto abierto")
        return self._session

    @property
    def path(self) -> Path | None:
        return self._session.path if self._session is not None else None

    def open_path(self, path: str | Path) -> None:
        self._session = self._service.open(path)
        self._undo_stack.clear()
        self.session_opened.emit()
        self.session_changed.emit()
        self.dirty_changed.emit(False)
        self._announce("info", f"Proyecto abierto: {Path(path).name}")

    def save(self, path: str | Path | None = None) -> None:
        self._service.save(self.session, path)
        self.dirty_changed.emit(False)
        self._announce("success", "Proyecto guardado")

    # --- import / export / versiones ------------------------------------ #
    def import_untis(self, xml_path: str | Path, dest_bjs: str | Path) -> None:
        """Importa un XML de Untis y lo abre como proyecto activo."""
        self._session = self._service.import_untis(xml_path, dest_bjs)
        self._undo_stack.clear()
        self.session_opened.emit()
        self.session_changed.emit()
        self.dirty_changed.emit(False)
        self._announce("success", f"Importado desde Untis: {Path(xml_path).name}")

    def export_json(self, dest_file: str | Path) -> None:
        self._service.export_json(self.session, dest_file)
        self._announce("success", f"Exportado a JSON: {Path(dest_file).name}")

    def snapshot(self) -> Path:
        dest = self._service.snapshot(self.session)
        self.dirty_changed.emit(False)
        self._announce("success", f"Versión creada: {dest.name}")
        return dest

    def list_snapshots(self) -> tuple[Path, ...]:
        return self._service.list_snapshots(self.session)

    # --- configuración del motor (Settings) ----------------------------- #
    def engine_settings(self) -> EngineConfig:
        return self._service.engine_settings(self.session)

    def update_engine_settings(
        self,
        *,
        default_solver: str | None = None,
        threads: int | None = None,
        max_time_seconds: float | None = None,
        random_seed: int | None = None,
    ) -> None:
        self._service.update_engine_settings(
            self.session,
            default_solver=default_solver,
            threads=threads,
            max_time_seconds=max_time_seconds,
            random_seed=random_seed,
        )
        self.dirty_changed.emit(True)
        self._announce("info", "Configuración del motor actualizada")

    def _announce(self, level: str, text: str) -> None:
        self.status_message.emit(text)
        self.notification.emit(level, text)

    # --- consultas (delegan en la Fachada) ------------------------------ #
    def tables(self) -> EntityTables:
        return self._service.tables(self.session)

    def focus_options(self) -> tuple[FocusOption, ...]:
        return self._service.focus_options(self.session)

    def timetable(self, focus_id: int) -> TimetableView:
        return self._service.timetable(self.session, focus_id)

    def move_targets(self, task_id: int) -> tuple[MoveTarget, ...]:
        return self._service.move_targets(self.session, task_id)

    # --- disponibilidad / bloqueo de horas ------------------------------ #
    def can_block(self, resource_id: int) -> bool:
        return self._service.can_block(self.session, resource_id)

    def blocked_hours(self, resource_id: int) -> frozenset[tuple[int, int]]:
        return self._service.availability(self.session, resource_id)

    def toggle_block(self, resource_id: int, day: int, period: int) -> bool:
        blocked = self._service.toggle_block(self.session, resource_id, day, period)
        self.dirty_changed.emit(True)
        self.session_changed.emit()
        estado = "bloqueada" if blocked else "liberada"
        self.status_message.emit(f"Hora {estado} (día {day + 1}, período {period + 1})")
        return blocked

    # --- ventana de almuerzo -------------------------------------------- #
    def lunch_window(self) -> LunchWindow | None:
        return self._service.lunch_window(self.session)

    def set_lunch_window(self, start: int, end: int, days: tuple[int, ...] | None = None) -> None:
        self._service.set_lunch_window(self.session, start, end, days)
        self.dirty_changed.emit(True)
        self.session_changed.emit()
        self._announce("info", f"Ventana de almuerzo: periodos {start + 1} a {end + 1}")

    def clear_lunch_window(self) -> None:
        self._service.clear_lunch_window(self.session)
        self.dirty_changed.emit(True)
        self.session_changed.emit()
        self._announce("info", "Ventana de almuerzo quitada")

    def dashboard(self) -> DashboardStats:
        return self._service.dashboard(self.session)

    def validate(self) -> ValidationReport:
        return self._service.validate(self.session)

    def constraints_catalog(self) -> tuple[ConstraintRow, ...]:
        return self._service.constraints_catalog(self.session)

    def reports(self) -> tuple[ReportTable, ...]:
        return self._service.reports(self.session)

    def available_solvers(self) -> tuple[str, ...]:
        return self._service.available_solvers()

    # --- edición básica ------------------------------------------------- #
    # --- CRUD de entidades y carga horaria ------------------------------ #
    def add_teacher(self, name: str) -> int:
        new_id = self._service.add_teacher(self.session, name)
        self._after_edit()
        self._announce("success", f"Docente añadido: {name}")
        return new_id

    def add_group(self, name: str, size: int) -> int:
        new_id = self._service.add_group(self.session, name, size)
        self._after_edit()
        self._announce("success", f"Grupo añadido: {name}")
        return new_id

    def add_room(self, name: str, seats: int) -> int:
        new_id = self._service.add_room(self.session, name, seats)
        self._after_edit()
        self._announce("success", f"Aula añadida: {name}")
        return new_id

    def remove_resource(self, resource_id: int) -> None:
        self._service.remove_resource(self.session, resource_id)
        self._after_edit()
        self._announce("info", "Recurso eliminado")

    def add_subject(self, name: str) -> None:
        self._service.add_subject(self.session, name)
        self._after_edit()
        self._announce("success", f"Materia añadida: {name}")

    # --- datos maestros estilo Untis ------------------------------------ #
    def set_resource_info(self, resource_id: int, field: str, value: str) -> bool:
        self._service.set_resource_info(self.session, resource_id, field, value)
        self._after_edit()
        return True

    def set_subject_info(self, subject: str, field: str, value: str) -> bool:
        self._service.set_subject_info(self.session, subject, field, value)
        self._after_edit()
        return True

    def subject_colors(self) -> dict[str, str]:
        return self._service.subject_colors(self.session)

    def rename_subject(self, old: str, new: str) -> bool:
        self._service.rename_subject(self.session, old, new)
        self._after_edit()
        return True

    def remove_subject(self, subject: str) -> None:
        self._service.remove_subject(self.session, subject)
        self._after_edit()
        self._announce("info", f"Materia eliminada: {subject}")

    def add_load(
        self,
        group_ids: list[int],
        subject: str,
        teacher_ids: list[int],
        sessions: int,
        room_ids: list[int] | None = None,
    ) -> None:
        self._service.add_load(
            self.session, group_ids, subject, teacher_ids, sessions, room_ids=room_ids
        )
        self._after_edit()
        self._announce("success", f"Carga añadida: {subject} ({sessions}h)")

    # --- lecciones (vista de carga estilo Untis) ------------------------ #
    def lessons(
        self, *, group_id: int | None = None, teacher_id: int | None = None
    ) -> tuple[LessonRow, ...]:
        return self._service.lessons(self.session, group_id=group_id, teacher_id=teacher_id)

    def remove_lesson(self, task_ids: list[int]) -> None:
        self._service.remove_lesson(self.session, task_ids)
        self._after_edit()
        self._announce("info", "Lección eliminada")

    def set_lesson_hours(self, task_ids: list[int], hours: int) -> None:
        self._service.set_lesson_hours(self.session, task_ids, hours)
        self._after_edit()

    def set_lesson_rooms(self, task_ids: list[int], room_ids: list[int]) -> None:
        self._service.set_lesson_rooms(self.session, task_ids, room_ids)
        self._after_edit()
        self._announce("info", "Aulas de la lección actualizadas")

    def set_group_size(self, resource_id: int, size: int) -> bool:
        self._service.set_group_size(self.session, resource_id, size)
        self._after_edit()
        return True

    def rename_resource(self, resource_id: int, name: str) -> bool:
        self._service.rename_resource(self.session, resource_id, name)
        self._after_edit()
        return True

    def set_room_seats(self, resource_id: int, seats: int) -> bool:
        self._service.set_room_seats(self.session, resource_id, seats)
        self._after_edit()
        return True

    def set_rule(
        self,
        rule_id: str,
        *,
        enabled: bool | None = None,
        weight: int | None = None,
        tier: int | None = None,
    ) -> None:
        self._service.set_rule(self.session, rule_id, enabled=enabled, weight=weight, tier=tier)
        self._after_edit()

    def _after_edit(self) -> None:
        self.dirty_changed.emit(True)
        self.session_changed.emit()

    # --- optimización --------------------------------------------------- #
    def start_optimize(
        self,
        *,
        solver: str,
        seed: int | None = None,
        timeout: float | None = None,
        structural_only: bool = False,
    ) -> None:
        """Lanza la optimización en un hilo aparte. No bloquea la UI."""
        if self._worker is not None and self._worker.isRunning():
            return
        self._cancel.reset()
        worker = SolveWorker(
            self._service,
            self.session,
            solver=solver,
            seed=seed,
            timeout=timeout,
            structural_only=structural_only,
            cancel=self._cancel,
        )
        worker.progressed.connect(self._relay_progress)
        worker.finished_outcome.connect(self._on_solved)
        self._worker = worker
        worker.start()

    def _relay_progress(self, percentage: int, stage: str) -> None:
        self.solve_progress.emit(percentage, stage)

    def cancel_optimize(self) -> None:
        """Solicita detener la búsqueda de forma cooperativa."""
        self._cancel.cancel()
        self.status_message.emit("Cancelando…")

    # --- edición del horario (drag&drop + deshacer) --------------------- #
    def move_class(self, task_id: int, day: int, period: int) -> SolveOutcome:
        """Mueve una clase y reoptimiza; apila el estado previo para deshacer."""
        before = self.session.project
        outcome = self._service.move_class(self.session, task_id, day, period)
        if outcome.solved:
            self._undo_stack.append(before)
            self.dirty_changed.emit(True)
            self.session_changed.emit()
        self.status_message.emit(outcome.message)
        return outcome

    def undo(self) -> bool:
        """Deshace el último movimiento restaurando el estado previo."""
        if not self._undo_stack:
            return False
        self.session.project = self._undo_stack.pop()
        self.session.dirty = True
        self.dirty_changed.emit(True)
        self.session_changed.emit()
        self.status_message.emit("Movimiento deshecho")
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def _on_solved(self, outcome: SolveOutcome) -> None:
        if outcome.solved:
            self.dirty_changed.emit(True)
            self.session_changed.emit()
            self._announce("success", f"Optimización terminada: {outcome.message}")
        else:
            self._announce("error", f"Optimización sin éxito: {outcome.message}")
        self.solve_finished.emit(outcome)
