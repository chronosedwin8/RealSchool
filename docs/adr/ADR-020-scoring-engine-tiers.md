# ADR-020: Scoring Engine v2 — Tiers y normalización por máximo teórico

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
Con varias reglas blandas compitiendo (ADR-019), una métrica de mayor escala
(p. ej. minutos de tránsito de aula) podía dominar y anular a una crítica de menor
escala (un hueco en una materia troncal). La Actividad 2.3.C pide un Scoring
Engine que normalice y jerarquice para una optimización estable y predecible.

## Decisión

### 1. `PenaltyTerm` gana `tier` y `theoretical_max`
- `tier ∈ {1,2,3}` (1 vital, 2 operativa, 3 preferencial); por defecto 3.
- `theoretical_max` = peor caso posible de la holgura; si se indica, se normaliza.

### 2. Coeficiente entero unificado
CP-SAT solo admite coeficientes enteros, así que la normalización y el Tier se
pliegan en un único coeficiente por término:

```
coef = round(TIER_SCALE[tier] · weight · SCALE / theoretical_max)   (mínimo 1)
```

con `TIER_SCALE = {1: 10000, 2: 100, 3: 1}` y `SCALE = 1000`. Sin `theoretical_max`,
`coef = TIER_SCALE[tier] · weight`. **Con Tier 3 y sin máximo, `coef = weight`**:
comportamiento idéntico al histórico (retrocompatibilidad — todos los tests
previos siguen verdes sin tocarse).

### 3. Tiers operativos vía catálogo
`registry_from_catalog(ids)` construye un `ScoringEngine(tier_by_label=…)` que
asigna a cada criterio blando el Tier de su definición en el catálogo (indexado
por la etiqueta que emite el plugin). Un `ScoringEngine` vacío deja que cada
término conserve su propio `tier`.

### 4. Invariante suma = objetivo, preservado
El `SolutionInspector` usa **el mismo `effective_coefficient`** que construyó la
función objetivo (no el peso crudo). Así el Informe de Penalizaciones sigue
sumando exactamente el valor del objetivo, ahora también con Tiers. El engine le
pasa el `ScoringEngine` de su registro al `SolutionBuilder`.

## Consecuencias
- **Positivas:** dominancia lexicográfica garantizada y verificada (una violación
  Tier-1 pesa más que todas las Tier-3 juntas); normalización disponible por
  término; retrocompatibilidad total.
- **Negativas:** los coeficientes crecen (hasta ~10⁷); siguen dentro de int64 con
  holgura amplia para los tamaños reales. La normalización por término solo actúa
  cuando el plugin declara `theoretical_max`; poblarlo en cada regla es refinamiento
  futuro (las reglas actuales emiten holguras ya de escala pequeña).
- El error de redondeo del coeficiente entero es a lo sumo 1 unidad por término,
  irrelevante frente a las escalas de Tier.
