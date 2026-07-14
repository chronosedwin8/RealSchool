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


@dataclass(frozen=True, slots=True)
class EnumDomain(Domain):
    """Dominio con *exactamente* los valores permitidos (puede tener huecos).

    Imprescindible para variables como "el período en que empieza la clase",
    cuyos valores válidos no forman un rango contiguo (una clase de dos períodos
    no puede empezar a última hora del día). Sin esto habría que codificar el
    dominio con una booleana por valor, multiplicando el tamaño del modelo.
    """

    values: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise DslError("un dominio enumerado necesita al menos un valor")
        if list(self.values) != sorted(set(self.values)):
            raise DslError("los valores del dominio deben ir ordenados y sin repetir")
