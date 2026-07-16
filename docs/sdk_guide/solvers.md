# Implementar un solver (`ISolver`)

La **Solver Abstraction Layer** es una interfaz pequeña de *handles opacos*: el
resto del sistema habla con `ISolver` y nunca ve tipos de un solver concreto.
Implementarla es cómo se añade Gurobi, un backend MILP o cualquier otro motor.

## El contrato

```python
from scheduling_platform.sal.interface import ISolver

class ISolver(ABC):
    def new_bool_var(self, name) -> SolverVar: ...
    def new_int_var(self, lo, hi, name) -> SolverVar: ...
    def new_int_var_from_values(self, values, name) -> SolverVar: ...
    def add_linear(self, terms, op, rhs) -> None: ...
    def add_all_different(self, variables) -> None: ...
    def add_bool_or(self, literals) -> None: ...
    def add_implication(self, antecedent, consequent) -> None: ...
    def new_interval(self, start, size, name) -> SolverInterval: ...
    def new_optional_interval(self, start, size, presence, name) -> SolverInterval: ...
    def add_no_overlap(self, intervals) -> None: ...
    def minimize(self, terms, constant=0) -> None: ...
    def add_hint(self, var, value) -> None: ...           # warm start
    def solve(self, config=None) -> SolverStatus: ...
    def value(self, var) -> int: ...
    def objective_value(self) -> int: ...
    def get_stats(self) -> dict[str, int]: ...            # opcional
```

Las variables (`SolverVar`) son **enteros opacos**: cada implementación mantiene su
propio mapeo interno a la variable nativa.

## Dos plantillas en el repo

- **`sal/ortools_solver.py`** (`ORToolsSolver`): CP-SAT, soporta todo (intervalos,
  reificación).
- **`sal/mip_solver.py`** (`MipSolver`): CBC/SCIP/HiGHS vía `pywraplp`. No tiene
  intervalos nativos, así que `new_interval`/`add_no_overlap` lanzan
  `UnsupportedOperation`; `bool_or`/`implication` se **linealizan**. Es la mejor
  plantilla para un backend MILP nuevo (p. ej. Gurobi, que ya funciona si hay
  licencia con el mismo `MipSolver("GUROBI")`).

!!! warning "Frontera de arquitectura"
    Tu implementación **debe** vivir en `sal/` — es la única capa autorizada a
    importar un solver. `tests/test_architecture.py` lo verifica.

## Registrar y usar

El solver se inyecta como *factory* (nunca se importa arriba):

```python
from scheduling_platform.engine import SchedulingEngine
engine = SchedulingEngine(registry=registry, solver_factory=MiSolver)
```

Desde el CLI/config, añade el nombre en `application/solvers.py`
(`SOLVER_FACTORIES`) y quedará disponible en `--solver` y en `solver_config.json`.

## Probarlo

Usa el **contrato de la SAL** (`tests/isolver_contract.py`) y una prueba
*differential*: resuelve el mismo modelo con tu solver y con CP-SAT y exige el
**mismo óptimo** (patrón en `tests/test_mip_solver.py`).

Referencia: [API — sal](../reference/sal.md).
