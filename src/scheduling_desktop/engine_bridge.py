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
    CancelToken,
    DashboardStats,
    EngineService,
    EntityTables,
    FocusOption,
    ProgressEvent,
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
    solve_progress = Signal(int, str)
    solve_finished = Signal(object)

    def __init__(self, service: EngineService | None = None) -> None:
        super().__init__()
        self._service = service or EngineService()
        self._session: Session | None = None
        self._cancel = CancelToken()
        self._worker: SolveWorker | None = None

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
        self.session_opened.emit()
        self.session_changed.emit()
        self.dirty_changed.emit(False)
        self.status_message.emit(f"Proyecto abierto: {Path(path).name}")

    def save(self, path: str | Path | None = None) -> None:
        self._service.save(self.session, path)
        self.dirty_changed.emit(False)
        self.status_message.emit("Proyecto guardado")

    # --- consultas (delegan en la Fachada) ------------------------------ #
    def tables(self) -> EntityTables:
        return self._service.tables(self.session)

    def focus_options(self) -> tuple[FocusOption, ...]:
        return self._service.focus_options(self.session)

    def timetable(self, focus_id: int) -> TimetableView:
        return self._service.timetable(self.session, focus_id)

    def dashboard(self) -> DashboardStats:
        return self._service.dashboard(self.session)

    def validate(self) -> ValidationReport:
        return self._service.validate(self.session)

    def available_solvers(self) -> tuple[str, ...]:
        return self._service.available_solvers()

    # --- edición básica ------------------------------------------------- #
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

    def _on_solved(self, outcome: SolveOutcome) -> None:
        if outcome.solved:
            self.dirty_changed.emit(True)
            self.session_changed.emit()
        self.solve_finished.emit(outcome)
