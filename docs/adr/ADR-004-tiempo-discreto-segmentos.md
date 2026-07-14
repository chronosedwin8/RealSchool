# ADR-004: Modelo temporal como rejilla discreta con segmentos

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
El motor necesita una noción de tiempo genérica (agnóstica al dominio) y
eficiente para CP-SAT, capaz de expresar que una tarea de varios slots no debe
cruzar una frontera natural (p. ej. un bloque doble que no cruza el día).

## Alternativas evaluadas
1. **Tiempo continuo (minutos reales)** — obligaría a discretizar igualmente
   para CP-SAT y añade aritmética innecesaria.
2. **Rejilla discreta plana** (solo `0..N-1`) — simple, pero incapaz de
   representar fronteras naturales sin metadatos externos.
3. **Rejilla discreta con segmentos** — slots enteros + partición en
   `Segment` contiguos que marcan fronteras.

## Decisión adoptada
Opción 3, implementada en `core/time_grid.py`: `TimeGrid` compuesta de
`Segment` contiguos sin huecos; `TimeSlot` como vista `(index, segment_id)`.
La contigüidad (`are_contiguous`) exige adyacencia **y** mismo segmento.
`valid_starts(duration, same_segment)` calcula los inicios factibles y será
reutilizada por el modelo CP-SAT (Fase 7). El mapeo `(día, período) <-> índice`
lo hará el adaptador académico (Fase 2); el núcleo no conoce "días".

## Consecuencias técnicas
- **Rendimiento:** enteros puros, óptimos para la propagación de CP-SAT.
- **Escalabilidad:** `segment_of` escanea segmentos (≈ decenas), no slots.
- **Extensibilidad:** un "segmento" sirve igual para día escolar, turno
  hospitalario o jornada fabril, sin acoplar el core a un dominio.
