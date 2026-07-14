"""Errores del DSL y de su compilación.

Se mantienen independientes de ``core.exceptions`` porque son errores de
*construcción y compilación* del modelo de optimización, no violaciones de
invariantes del dominio.
"""

from __future__ import annotations


class DslError(Exception):
    """Raíz de los errores del DSL."""


class UnsupportedConstraintError(DslError):
    """El compilador aún no sabe bajar esta forma de restricción a un solver."""
