"""Dominios de las variables del DSL.

Describen el rango de una variable simbólica sin comprometer aún su
representación en el solver (eso lo decide el compilador). Módulo sin
dependencias, para evitar ciclos con ``expressions``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import DslError


class Domain:
    """Base de los dominios de variable."""


@dataclass(frozen=True, slots=True)
class BoolDomain(Domain):
    """Dominio booleano ``{0, 1}``."""


@dataclass(frozen=True, slots=True)
class IntDomain(Domain):
    """Dominio entero ``[lo, hi]`` (ambos inclusive)."""

    lo: int
    hi: int

    def __post_init__(self) -> None:
        if self.lo > self.hi:
            raise DslError(f"dominio entero inválido: lo={self.lo} > hi={self.hi}")
