# ADR-037: Heurística de generación y Fachada Untis

**Fecha:** 2026-09-18 · **Estado:** Aceptado

## Contexto

El motor CP-SAT no genera desde cero un horario del tamaño del Colegio Alemán
en un tiempo razonable (ADR-016). Untis lo hace con una heurística de dos fases:
colocación por dificultad e intercambios. La fase R3 exige replicarlo, con las
estrategias A/B/D/E y Reparar, y una Fachada que la UI (R4) pueda usar sin
conocer el dominio.

## Decisión adoptada

1. **`heuristic/`**, algoritmo puro sobre `untis_model` (no ve el motor):
   - modelo compacto construido una vez; choques medidos sobre el **reloj de
     pared** con intervalos elementales y máscaras de bits por recurso y día;
   - **evaluación incremental exacta** por ámbitos (entidad-día, entidad-semana,
     lección): un movimiento recalcula solo lo que toca, con funciones que copian
     literalmente las del evaluador de referencia. Un test exige que el estado
     incremental coincida con `Evaluator.report` tras cada movimiento;
   - fase 1: colocación de lo más difícil a lo más fácil en la celda de menor
     coste, con expulsión acotada; fase 2: recocido simulado con reubicación,
     cadenas tipo Kempe, intercambios, dobles como pareja, cambio de aula e
     inserción de no colocadas;
   - estrategias: A (una pasada), B/E (reinicios que recalientan desde el
     mejor), D (coloca solo el % más difícil), Reparar (cambio mínimo).
2. **Orquestador en `bridge/optimize.py`**: B/D/E terminan con Reparar CP-SAT si
   quedan choques o sesiones sueltas; Reparar usa CP-SAT primero y la heurística
   para pulir. Nunca se devuelve un horario peor que el de partida.
3. **Los choques cuentan en el número de evaluación** (`CLASH_PENALTY`, igual que
   un período sin colocar): antes, un horario con choques podía puntuar mejor que
   uno limpio.
4. **Fachada Untis** (`application/untis/`): `UntisService` sin estado sobre una
   `UntisSession` con deshacer/rehacer (el modelo es inmutable: cada paso es una
   instantánea barata). Las ediciones devuelven `EditResult` en vez de lanzar,
   para que la UI marque la celda en rojo; `optimize` nunca lanza. Las columnas
   de las cuadrículas se derivan de los campos del modelo.
5. **CLI**: `schedule-engine convert` entre XML, GPU, `.rsp` y `.bjs`;
   `solve --strategy A|B|D|E|repair` y `evaluate`.

## Consecuencias técnicas

Sobre el export real 2025-2026, con la ponderación por defecto y los recreos
deducidos (`scripts/bench_heuristic.py`):

| Horario | Tiempo | Sin colocar | Choques | Puntos blandos |
| --- | --- | --- | --- | --- |
| Publicado por Untis | – | 4 | 7 | 118.418 |
| Estrategia A | 60 s | 0 | 0 | 10.301 |
| Estrategia B | 300 s | 0 | 0 | 8.322 |

Criterios de aceptación de R3 cumplidos (A < 2 min, B ≤ 15 min, ≤ 2 % sin
colocar, B mejor que Untis con la misma ponderación). Salvedad: Untis optimizó
con la ponderación propia del colegio, que el XML no exporta; con la misma
ponderación que Untis los números serían otros. Donde la heurística queda peor
que Untis: reparto uniforme en la semana, equilibrio de carga diaria y dobles —
objetivos naturales de afinado. Velocidad: ~35.000 movimientos probados y
~10.000 puntuados por segundo.
