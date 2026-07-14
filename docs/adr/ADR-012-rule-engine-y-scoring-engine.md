# ADR-012: Rule Engine y Scoring Engine

**Fecha:** 2026-07-14 · **Estado:** Aceptado

## Contexto
Prompt3 §2.4 exige separar matemáticamente las reglas **duras** (el solver debe
satisfacerlas) de las **blandas** (variables de holgura penalizadas en una
función objetivo unificada, con normalización de pesos para evitar dominancia).

## Decisiones adoptadas

### 1. Una única interfaz de plugin para ambos motores
`Contribution` lleva ahora `constraints` (Rule Engine) y `penalties`
(Scoring Engine). Un mismo plugin puede aportar ambas cosas; el registro decide
qué hacer con cada una. No hay dos jerarquías de plugin: el motor las distingue
por el *tipo de aportación*, no por el tipo de plugin.

### 2. `PenaltyTerm(expr, weight, label)` como unidad de holgura
`expr` es una expresión lineal no negativa (cuánto se incumple la preferencia),
`weight` su importancia y `label` el criterio, que alimentará el Informe de
Penalizaciones (Fase 9). El `ScoringEngine` construye
`minimizar sum(peso_i * holgura_i)`; sin penalizaciones no hay objetivo (puro
problema de factibilidad). `normalize_weights` escala pesos crudos preservando
proporciones y garantizando un mínimo de 1, de modo que ningún criterio quede
anulado ni domine por magnitud arbitraria.

### 3. Ocupación compartida en el contexto
Varias reglas (no-solape, carga diaria, consecutivas) necesitan "el recurso R
está ocupado en el slot K". Se centraliza en `context.occupancy(...)`, que
devuelve la variable y sus restricciones de enlace (`occ = assign AND cover`
linealizado). Las keys coinciden entre plugins, así que los enlaces duplicados
son inocuos y el pase de deduplicación del CIR los colapsa.

### 4. Atributos numéricos genéricos en el Modelo Canónico
`Resource.attribute(...)` y `Task.attribute(...)` (tuplas `(nombre, valor)`)
permiten que las reglas lean datos del dominio (asientos del aula, tamaño del
grupo) **sin que el núcleo conozca su significado**. Esto salda la deuda de
ADR-006 sin acoplar el canónico al dominio académico.

### 5. Plugins configurables con una sola instancia
Los límites se pasan como mapas (`limits=(("teacher", 6), ("group", 8))`) para
que una única instancia cubra varias categorías, evitando colisiones de nombre
en el registro.

## Qué es estructural y qué es una regla

| Requisito de Prompt3 | Dónde vive |
|---|---|
| Intensidad horaria exacta | Estructural: cada sesión es una tarea con *exactly-one-start* |
| Bloques dobles/triples consecutivos | Estructural: la sesión **es** el bloque (duración + `same_segment`) |
| Disponibilidad docente | Estructural: el adaptador la convierte en `allowed_starts` |
| Un recurso, una clase a la vez | `ResourceNoOverlapPlugin` |
| Máx. horas diarias / consecutivas | `MaxDailyLoadPlugin`, `MaxConsecutivePlugin` |
| Capacidad del aula | `RoomCapacityPlugin` (vía atributos) |
| Bloqueos administrativos / eventos | `ForbiddenStartsPlugin` |
| Preferencias horarias | `PreferEarlySlotsPlugin`, `AvoidSlotsPlugin` (blandas) |

**Diferidos** (requieren más maquinaria, Fase 9/10): huecos docentes y de
estudiantes, balance de carga, minimizar cambios de aula/edificio. Todos se
expresan sobre la misma ocupación ya disponible, sin tocar el núcleo.

## Consecuencias técnicas
- **Descubrimiento valioso:** una regla dura que contradice una estructural
  (aula demasiado pequeña siendo la única) es detectada por los pases del CIR
  **antes de invocar al solver**, y explicada. La infactibilidad tiene dos vías
  legítimas: `INFEASIBLE` del solver o contradicción estructural explicada.
- Las blandas **nunca** vuelven infactible un horario (verificado en pruebas).
- El trade-off de pesos funciona: subir el peso de un criterio lo hace
  prevalecer (verificado end-to-end con OR-Tools).
