# Restricciones duras y blandas: el Scoring Engine y los Tiers

El motor distingue dos clases de restricción, con tratamientos matemáticos
distintos.

## HARD (Rule Engine) — invulnerables

Una restricción **dura** define la factibilidad: nunca puede romperse. Se compila
como ecuación o inecuación estricta. Si no se puede satisfacer, el modelo es
`INFEASIBLE`.

```
Exclusividad de recurso (HC-01/02/03): para cada recurso r y período t,
    Σ_a  ocupa(a, r, t)  ≤  1
```

No hay variables extra: si la suma excediera 1, el solver poda esa rama.

## SOFT (Scoring Engine) — penalizables

Una restricción **blanda** guía la calidad. Se permite incumplirla a cambio de un
**coste** en la función objetivo, mediante **variables de holgura** (*slack*):

```
Huecos docentes (SC-02): por cada hueco g_{p,d} ≥ 0,
    minimizar  Σ  g_{p,d}
```

Escribir una regla blanda es emitir un `PenaltyTerm(expr, weight, label)`; el
`ScoringEngine` las combina en un único objetivo a minimizar. Ver
[cómo crear restricciones](../sdk_guide/constraints.md).

## Tiers: jerarquía lexicográfica

Cuando compiten muchas reglas blandas, una métrica de gran escala podría anular a
una crítica de menor escala. El Scoring Engine lo evita con **Tiers**
(niveles lexicográficos) y **normalización por máximo teórico**:

| Tier | Prioridad | Multiplicador | Ejemplo |
|---|---|--:|---|
| 1 | Vital | ×10 000 | Huecos en materias troncales (SC-02) |
| 2 | Operativa | ×100 | Estabilidad de aula (SC-06) |
| 3 | Preferencial | ×1 | Preferencia de primera hora (SC-01) |

El coste efectivo de cada término es un **coeficiente entero** (CP-SAT no admite
fracciones):

```
coef = round( TIER_SCALE[tier] · weight · SCALE / theoretical_max )   (mínimo 1)
```

Con Tier 3 y sin máximo teórico, `coef = weight`: el comportamiento histórico. La
garantía clave, verificada por tests, es **dominancia lexicográfica**: una sola
violación de Tier 1 pesa más que **todas** las violaciones de Tier 3 juntas.

!!! info "Invariante suma = objetivo"
    El Informe de Penalizaciones usa el **mismo coeficiente efectivo** que la
    función objetivo, así que la suma del informe coincide exactamente con el valor
    del objetivo minimizado.

Detalle y justificación en **ADR-019** (catálogo canónico) y **ADR-020** (Tiers),
enlazados desde el [índice de decisiones](decisions.md).
