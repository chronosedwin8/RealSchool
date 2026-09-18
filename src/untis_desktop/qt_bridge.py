"""Puente Qt de la Fachada: señales de cambio, selección sincronizada e hilos.

Es el único objeto Qt que conoce la `UntisService`. Las ventanas reciben el
puente, leen con `bridge.service` / `bridge.session` y editan a través de
`bridge.edit(...)`, que registra el cambio y avisa a todas las ventanas.

Selección sincronizada (sección 8 del documento maestro): elegir una clase en
Datos maestros emite `selection_changed("class", "5A")` y Lecciones, Horario y
Deseos se filtran solos.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from scheduling_platform.application import (
    CancelToken,
    EditResult,
    OptimizeOutcome,
    OptimizeRequest,
    UntisService,
    UntisSession,
)

#: Segundos mínimos entre dos avisos de progreso al hilo de la interfaz.
PROGRESS_INTERVAL = 0.1
#: Cada cuánto recoge la basura el hilo de la interfaz mientras se optimiza (ms).
GC_INTERVAL_MS = 2000


class OptimizeWorker(QThread):
    """Optimiza en un hilo sobre una instantánea de la sesión."""

    progressed = Signal(object)
    """`OptimizeProgress`."""
    done = Signal(object)
    """`OptimizeOutcome`."""

    def __init__(
        self,
        service: UntisService,
        snapshot: UntisSession,
        request: OptimizeRequest,
        cancel: CancelToken,
    ) -> None:
        super().__init__()
        self._service = service
        self.snapshot = snapshot
        self._request = request
        self._cancel = cancel

    def run(self) -> None:
        ultimo = [0.0]

        def progreso(evento: object) -> None:
            # Como mucho unos 10 avisos por segundo: la heurística puede producir
            # miles y cada uno repinta la ventana de Optimización.
            ahora = time.monotonic()
            if ahora - ultimo[0] >= PROGRESS_INTERVAL:
                ultimo[0] = ahora
                self.progressed.emit(evento)

        resultado = self._service.optimize(
            self.snapshot,
            self._request,
            on_progress=progreso,
            cancel=self._cancel,
        )
        self.done.emit(resultado)


class FacadeBridge(QObject):
    """Estado de la sesión abierta y avisos a las ventanas."""

    project_opened = Signal()
    project_changed = Signal(str)
    """Etiqueta de la edición (la de deshacer)."""
    refreshed = Signal()
    """Refresco agrupado y diferido: las ventanas pesadas se suscriben aquí."""
    selection_changed = Signal(str, str)
    """`(tipo, id)`: `class`, `teacher`, `room`, `subject`."""
    lesson_selected = Signal(int)
    status = Signal(str)
    busy_changed = Signal(bool)
    optimize_progress = Signal(object)
    optimize_finished = Signal(object)
    language_changed = Signal(str)

    def __init__(self, service: UntisService | None = None) -> None:
        super().__init__()
        self.service = service if service is not None else UntisService()
        self._session: UntisSession | None = None
        self._worker: OptimizeWorker | None = None
        self._cancel = CancelToken()
        self.selection: tuple[str, str] | None = None
        self.language = "es"
        self._pending = False
        # Mientras optimiza un hilo, la recolección automática de Python podría
        # dispararse en ese hilo y destruir objetos Qt de la interfaz: fallo
        # nativo (access violation). Se desactiva durante la optimización y se
        # recoge periódicamente desde el hilo de la interfaz.
        self._gc_timer = QTimer(self)
        self._gc_timer.setInterval(GC_INTERVAL_MS)
        self._gc_timer.timeout.connect(gc.collect)
        self._gc_was_enabled = gc.isenabled()
        self.project_changed.connect(self._schedule_refresh)
        self.project_opened.connect(self._schedule_refresh)

    # --- sesión ----------------------------------------------------------- #

    @property
    def has_session(self) -> bool:
        return self._session is not None

    @property
    def session(self) -> UntisSession:
        if self._session is None:
            raise RuntimeError("No hay proyecto abierto")
        return self._session

    @property
    def busy(self) -> bool:
        return self._worker is not None

    def new(self, name: str = "") -> None:
        self._set_session(self.service.new(name))

    def open(self, path: str | Path) -> None:
        self._set_session(self.service.open(path))
        self.status.emit(f"Abierto: {Path(path).name}")

    def attach(self, session: UntisSession) -> None:
        """Usa una sesión ya construida (pruebas, importadores)."""
        self._set_session(session)

    def _set_session(self, session: UntisSession) -> None:
        self._session = session
        self.selection = None
        self.project_opened.emit()

    def save(self, path: str | Path | None = None) -> Path:
        destino = self.service.save(self.session, path)
        self.status.emit(f"Guardado: {destino.name}")
        self.project_changed.emit("")
        return destino

    # --- edición ---------------------------------------------------------- #

    def edit(self, action: Callable[[], EditResult]) -> EditResult:
        """Ejecuta una edición de la Fachada y avisa si cambió algo."""
        if self.busy:
            return EditResult.failure("Espera a que termine la optimización")
        antes = self.session.project
        resultado = action()
        if resultado.message:
            self.status.emit(resultado.message)
        if self.session.project is not antes:
            self.project_changed.emit(self.session.undo_label)
        return resultado

    def undo(self) -> bool:
        if self.busy or not self.service.undo(self.session):
            return False
        self.project_changed.emit("")
        return True

    def redo(self) -> bool:
        if self.busy or not self.service.redo(self.session):
            return False
        self.project_changed.emit("")
        return True

    def notify_changed(self, label: str = "") -> None:
        """Para cambios hechos fuera de `edit` (p. ej. el horario activo)."""
        self.project_changed.emit(label)

    # --- selección sincronizada ------------------------------------------ #

    def select(self, kind: str, entity_id: str) -> None:
        if self.selection == (kind, entity_id):
            return
        self.selection = (kind, entity_id)
        self.selection_changed.emit(kind, entity_id)

    def select_lesson(self, number: int) -> None:
        self.lesson_selected.emit(number)

    # --- idioma ------------------------------------------------------------ #

    def set_language(self, language: str) -> None:
        if language != self.language:
            self.language = language
            self.language_changed.emit(language)

    # --- optimización ------------------------------------------------------ #

    def start_optimize(self, request: OptimizeRequest) -> bool:
        """Lanza la optimización en un hilo. `False` si ya hay una en curso."""
        if self.busy or not self.has_session:
            return False
        self._cancel.reset()
        instantanea = self.service.snapshot(self.session)
        self._worker = OptimizeWorker(self.service, instantanea, request, self._cancel)
        self._worker.progressed.connect(self.optimize_progress.emit)
        self._worker.done.connect(self._on_done)
        self.busy_changed.emit(True)
        self._suspend_gc()
        self._worker.start()
        return True

    def run_optimize_sync(self, request: OptimizeRequest) -> OptimizeOutcome:
        """Misma ruta que el hilo, pero en el hilo actual (pruebas deterministas)."""
        self._cancel.reset()
        instantanea = self.service.snapshot(self.session)
        worker = OptimizeWorker(self.service, instantanea, request, self._cancel)
        self._worker = worker
        self.busy_changed.emit(True)
        self._suspend_gc()
        salida: list[OptimizeOutcome] = []
        worker.progressed.connect(self.optimize_progress.emit)
        worker.done.connect(lambda o: salida.append(o))
        worker.run()
        self._finish(worker, salida[0])
        return salida[0]

    def cancel_optimize(self) -> None:
        self._cancel.cancel()

    def _on_done(self, outcome: object) -> None:
        worker = self._worker
        if worker is None or not isinstance(outcome, OptimizeOutcome):
            return
        worker.wait()
        self._finish(worker, outcome)

    def _suspend_gc(self) -> None:
        """Recolección solo en el hilo de la interfaz mientras trabaja el hilo."""
        self._gc_was_enabled = gc.isenabled()
        gc.disable()
        self._gc_timer.start()

    def _resume_gc(self) -> None:
        self._gc_timer.stop()
        if self._gc_was_enabled:
            gc.enable()
        gc.collect()

    def _finish(self, worker: OptimizeWorker, outcome: OptimizeOutcome) -> None:
        self._resume_gc()
        self._worker = None
        if outcome.ok and outcome.timetable_id:
            adopcion = self.service.adopt_timetable(
                self.session, worker.snapshot, outcome.timetable_id
            )
            if not adopcion.ok:
                self.status.emit(adopcion.message)
            else:
                self.project_changed.emit("Optimizar")
        self.busy_changed.emit(False)
        self.status.emit(outcome.message)
        self.optimize_finished.emit(outcome)

    # --- refresco agrupado -------------------------------------------------- #

    def _schedule_refresh(self) -> None:
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self._emit_refresh)

    def _emit_refresh(self) -> None:
        self._pending = False
        self.refreshed.emit()
