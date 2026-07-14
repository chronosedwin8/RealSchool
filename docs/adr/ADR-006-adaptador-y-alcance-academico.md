# ADR-006: Adaptador por tags y alcance de entidades del Módulo Académico

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
Prompt3 §4 enumera ~30 entidades académicas. La Fase 2 debe (a) traducir el
dominio académico al Modelo Canónico sin modificar el núcleo (Fase 1) y (b)
evitar el sobrediseño de modelar 30 entidades antes de tener un motor que las
use.

## Alternativas evaluadas
1. **Modelar las 30 entidades ya** — inflaría la fase, con entidades sin
   consumidor (no testeable de forma significativa) y alto riesgo de rework.
2. **Extender el Modelo Canónico** para requerir recursos por ID específico
   (docente/grupo fijos) — acoplaría el núcleo al caso académico.
3. **Subconjunto representativo + emparejamiento por tags** — modelar solo las
   entidades necesarias para producir `Resource`/`Task`/`TimeGrid` y usar el
   mecanismo de tags existente para fijar/elegir recursos.

## Decisión adoptada
Opción 3.
- **Entidades modeladas:** `TimeFrame`, `Room`, `Teacher` (+disponibilidad),
  `StudentGroup`, `Subject`, `TeachingAssignment`, `AcademicProblem`.
- **Traducción:** docente/grupo/aula -> `Resource` unario (capacidad canónica 1).
  Docente y grupo se **fijan** con tags únicos (`teacher#id`, `group#id`); el
  aula se **elige** con tag compartido (`room` / `roomtype#tipo`). Cada sesión
  de `session_lengths` -> un `Task`. La disponibilidad del docente se traduce a
  `allowed_starts`. El adaptador conserva mapeos inversos y reconstruye un
  `AcademicSchedule` (preludio del Solution Builder, Fase 9).
- **Entidades diferidas** (Institución, Sede, Campus, Edificio, Piso, Nivel,
  Sección, Estudiante, Calendario, Período, Receso, Almuerzo, Evento): se
  añadirán sin rehacer el adaptador porque o bien *agrupan/escopan* entidades
  existentes o se expresan como *restricciones* (Fase 8).

## Consecuencias técnicas
- **Núcleo intacto:** el emparejamiento específico se logra con el mecanismo de
  tags de la Fase 1; no se tocó el Modelo Canónico.
- **Elegancia:** "un grupo no puede tener dos clases a la vez" emerge gratis del
  no-solape de un recurso unario.
- **Deuda controlada:** los asientos del aula (`Room.capacity`) no son capacidad
  canónica; su restricción `size <= asientos` queda para la Fase 8. Un aula del
  tipo requerido inexistente produce una tarea infactible, explicada en Fase 5.
