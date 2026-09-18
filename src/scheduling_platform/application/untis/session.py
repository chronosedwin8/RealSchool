"""Sesión de trabajo sobre un proyecto Untis, con deshacer/rehacer.

El modelo es inmutable, así que cada edición produce un `UntisProject` nuevo y
las instantáneas son baratas (comparten estructura). La sesión guarda la pila de
deshacer con una etiqueta legible por paso, para el menú Edición de la UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scheduling_platform.untis_model import UntisProject

#: Cuántos pasos de deshacer se guardan.
UNDO_LIMIT = 100


@dataclass(slots=True)
class UntisSession:
    """Proyecto abierto: estado mutable de la Fachada (la UI no lo toca directamente)."""

    project: UntisProject
    path: Path | None = None
    dirty: bool = False
    active_timetable: str | None = None
    """Id del horario que muestran las ventanas de horario y planificación."""
    _undo: list[tuple[str, UntisProject]] = field(default_factory=list)
    _redo: list[tuple[str, UntisProject]] = field(default_factory=list)

    def apply(self, project: UntisProject, label: str) -> None:
        """Sustituye el proyecto y apila el estado anterior para deshacer."""
        if project == self.project:
            return
        self._undo.append((label, self.project))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self.project = project
        self.dirty = True
        if (
            self.active_timetable is not None
            and project.timetable_by_id(self.active_timetable) is None
        ):
            self.active_timetable = project.timetables[-1].id if project.timetables else None

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str:
        return self._undo[-1][0] if self._undo else ""

    @property
    def redo_label(self) -> str:
        return self._redo[-1][0] if self._redo else ""

    def undo(self) -> bool:
        if not self._undo:
            return False
        label, previo = self._undo.pop()
        self._redo.append((label, self.project))
        self.project = previo
        self.dirty = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        label, siguiente = self._redo.pop()
        self._undo.append((label, self.project))
        self.project = siguiente
        self.dirty = True
        return True

    def mark_saved(self, path: Path) -> None:
        self.path = path
        self.dirty = False
