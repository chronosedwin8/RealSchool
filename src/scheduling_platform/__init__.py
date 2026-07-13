"""Scheduling Optimization Platform.

Motor genérico de calendarización por restricciones. El núcleo solo conoce
entidades canónicas (Resource, Task, TimeSlot, Constraint, Assignment); los
dominios específicos (como el Módulo Académico) se conectan mediante
adaptadores. La resolución se delega a solvers intercambiables detrás de la
Solver Abstraction Layer (SAL), pasando por el pipeline de compilación
DSL -> CIR -> Optimizer Passes -> Solver Compiler.

Fuente de verdad de la especificación: ``Prompt3.md``.
Plan de fases: ``PLAN_DE_TRABAJO.md``.
"""

__version__ = "0.1.0"
