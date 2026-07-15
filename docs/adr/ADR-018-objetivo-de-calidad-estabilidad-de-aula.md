# ADR-018: Objetivo de calidad — estabilidad de aula, y el motor supera a Untis

**Fecha:** 2026-07-14 · **Estado:** Aceptado

## Contexto
ADR-017 (warm start) reparaba el horario de Untis pero no lo mejoraba: el
objetivo era pura factibilidad. Faltaba un objetivo de **calidad** medible sobre
el que el motor pudiera superar a Untis.

## Elección del objetivo, guiada por datos

Se midió la calidad de los 4 horarios reales de Untis:

- **Huecos docentes en minutos:** ~63.000–73.000. Métrica **ruidosa**: cuenta
  recreos y almuerzo como "hueco". Descartada como objetivo hasta tener una
  definición por-período limpia.
- **Dispersión de aulas:** cada docente usa **3,1–3,5 aulas de media** (máximo
  10–18). Métrica **limpia, expresable y con margen de mejora**. Elegida.

## Decisión

### 1. `TeacherRoomStabilityPlugin` (blanda)
Por cada par (docente, aula) crea un indicador `uses` que se activa si alguna
clase del docente usa esa aula (`assign[tarea, aula] -> uses[docente, aula]`), y
penaliza su suma. Se expresa **sobre las variables `assign` ya existentes** (modo
compacto, sin booleanas de período). Solo cubre clases de **un único docente**:
en una clase compartida las N aulas se reparten simétricamente entre los N
profesores y atribuir un aula a uno concreto no está determinado.

### 2. Dos fases (reparar, luego pulir)
Dar libertad de horario Y de aula a la vez hace que el solver deshaga el horario
(en pruebas: solo conservaba el 78% y no mejoraba las aulas). La solución:

1. **Reparar:** warm start con el horario de Untis, solo factibilidad -> horario
   válido que conserva el 93–96%.
2. **Pulir:** se **fijan las horas** de ese horario (cada tarea con un único
   inicio permitido) y se optimiza **solo la asignación de aulas** con el
   objetivo de estabilidad. El horario no se mueve; solo mejoran las aulas.

## Resultado medido (4 cursos reales, 40 s por fase)

| Curso | Pares docente-aula (Untis → motor) | Media | Máximo | Reducción |
|---|---|---|---|---|
| 2023–2024 | 311 → 223 | 3,5 → 2,5 | 11 → 6 | **−28%** |
| 2024–2025 | 313 → 252 | 3,5 → 2,8 | 13 → 7 | **−19%** |
| 2025–2026 | 316 → 255 | 3,4 → 2,8 | 10 → 7 | **−19%** |
| 2026–2027 | 370 → 295 | 3,1 → 2,5 | 18 → 8 | **−20%** |

En los cuatro: **0 violaciones duras**, 93–96% del horario conservado, y una
reducción del **19–28%** de los desplazamientos de aula. El caso extremo (un
docente en 18 aulas) baja a 8.

## Consecuencias técnicas
- **Por fin un gap analysis con el motor ganando** en una métrica concreta y
  verificable, sobre datos reales, sin tocar el horario del colegio.
- La comparación es **honesta y acotada**: mide clases de un solo docente (lo que
  el objetivo optimiza sin ambigüedad); las compartidas se dejan como están.
- El objetivo se expresa con el DSL existente: **ninguna extensión** de la SAL ni
  del CIR.
- **Deuda:** el objetivo de huecos docentes sigue pendiente; necesita una
  definición por-período (excluyendo recesos) y probablemente ocupación booleana,
  que no escala en modo compacto. Es el siguiente reto de calidad.
