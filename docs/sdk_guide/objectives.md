# Crear funciones objetivo

El objetivo global es una **suma ponderada de holguras**: no lo escribes a mano,
lo compones aportando `PenaltyTerm` desde tus plugins. El `ScoringEngine` los
combina y el compilador los baja a `solver.minimize(...)`.

## El término de penalización

```python
from scheduling_platform.plugins import PenaltyTerm

PenaltyTerm(
    expr,               # LinearExpr de holgura, no negativa
    weight,             # importancia relativa (> 0)
    label,              # identifica el criterio en el informe
    tier=3,             # 1 vital · 2 operativa · 3 preferencial
    theoretical_max=None,  # peor caso posible -> normaliza si se indica
)
```

- **`expr`** es "cuánto se incumple": típicamente una suma de variables de holgura
  que otras restricciones fuerzan al alza cuando aparece el defecto.
- **`tier`** aplica un multiplicador de escala (×10 000 / ×100 / ×1) que garantiza
  dominancia lexicográfica entre prioridades.
- **`theoretical_max`** lleva la penalización a un rango comparable entre criterios
  de distinta escala (normalización).

## Componer varios objetivos

Cada plugin activo aporta sus términos; el `ScoringEngine` los suma:

```python
from scheduling_platform.plugins import ScoringEngine
objective = ScoringEngine().build_objective([term_a, term_b])
```

Con `registry_from_catalog`, los Tiers del catálogo se aplican automáticamente por
etiqueta. Ver [Restricciones y Tiers](../architecture/scoring_tiers.md).

## Patrón: minimizar un conteo

La receta habitual para una métrica "número de X":

1. Crea una booleana indicadora `x_i` por cada posible X.
2. Fuerza `x_i = 1` cuando X ocurre (restricciones de enlace, duras).
3. Penaliza `Σ x_i` con un `PenaltyTerm`.

`plugins/catalog/daily_quality.py` (huecos, continuidad, jornada) es el ejemplo de
referencia.

## Verificar el trade-off

Sube el `weight` (o el `tier`) de un criterio y comprueba que **prevalece** sobre
otro en la solución elegida (patrón en `tests/test_scoring_engine.py` y
`tests/test_scoring_tiers.py`). El invariante **suma de penalizaciones = objetivo**
te dice si tu término se está contabilizando como esperas.

Referencia: [API — plugins](../reference/plugins.md).
