"""Interfaz del patrón Command (caso de uso encapsulado).

Cada operación de la CLI (generar, optimizar, validar, convertir...) es un
:class:`Command`: un objeto que lleva sus parámetros ya parseados y ejecuta la
lógica usando **exclusivamente la API pública del motor** a través del contexto
inyectado. Añadir una funcionalidad = añadir un archivo de comando, sin tocar el
dispatcher ni el parser CLI (Abierto/Cerrado).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..context import AppContext


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Resultado de un comando: dato estructurado + mensajes humanos + exit code.

    ``payload`` es la salida de datos (dict/list serializable) que el dispatcher
    emite por ``stdout``; ``messages`` son líneas humanas que van a ``stderr``.
    """

    exit_code: int = 0
    payload: Any | None = None
    messages: tuple[str, ...] = field(default_factory=tuple)


class Command(ABC):
    """Base de todos los casos de uso ejecutables por el dispatcher."""

    name: ClassVar[str]

    @abstractmethod
    def execute(self, ctx: AppContext) -> CommandResult:
        """Ejecuta el caso de uso con las dependencias del contexto."""
