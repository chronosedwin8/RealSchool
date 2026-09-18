# ADR-034: Reorientación del producto a Untis (motor congelado)

**Fecha:** 2026-09-18 · **Estado:** Aceptado

Supersede a `Prompt3.md`, `PLAN_DE_TRABAJO.md` y
`FasesPosteriores/ARCHITECTURE_AND_BENCHMARK.md` en todo lo que contradiga.
Anexo y fuente de verdad: [`REFACTOR_UNTIS_MAESTRO.md`](../../REFACTOR_UNTIS_MAESTRO.md).

## Contexto

RealSchool tiene el motor que Untis no tiene —CP-SAT exacto, explicación de
conflictos, reparación con *warm start*— pero no **es Untis por fuera**: su
vocabulario (Teacher/Room/Group de `academic/`, plugins `HC-xx`/`SC-xx`, pesos
en `engine.yaml`) no es el que maneja un planificador de horarios, y los acoples
(Kopplungen) se **infieren** con union-find en lugar de leerse como dato.

El centro de gravedad del proyecto (los ADR 001–033) ha estado en el motor
genérico. Para competir con Untis en un colegio real hay que invertirlo: el
producto pasa a ser el cliente de escritorio y el formato de proyecto; el motor,
una librería estable.

## Alternativas evaluadas

1. **Seguir ampliando la capa `academic/`** — conserva el código, pero su modelo
   no tiene secciones, acoples explícitos, deseos graduados ni períodos
   lectivos. Cada concepto Untis sería un parche sobre un vocabulario ajeno.
2. **Reescribir también el motor** — descartado: el motor ya absorbió el colegio
   real sin cambios (ADR-016) y repara 1.900 clases en <30 s (ADR-017). No hay
   motivo técnico para tocarlo más allá de extensiones puntuales.
3. **Adoptar el vocabulario Untis por encima de un motor congelado** —
   *adoptada*. Reescribe todo lo que está por encima de la Fachada y deja el
   motor como dependencia interna.

## Decisión adoptada

1. **Motor congelado** en la etiqueta `engine-1.0`: `core`, `dsl`, `cir`, `sal`,
   `pipeline`, `engine`, `plugins`, `benchmarks`. Solo cambia por las
   extensiones de la sección 7 del documento maestro, cada una con su ADR corto
   (ADR-035 en adelante).
2. **Capas nuevas de producto:**
   - `untis_model` — dominio Untis inmutable y **puro** (no importa el motor).
   - `interop` — XmlInterface, GPU, `.rsp`; solo conoce `untis_model`.
   - `bridge` — el **único** traductor `untis_model → core` y de la
     ponderación a términos de objetivo.
   - `heuristic` — colocación por dificultad + intercambios; algoritmo puro sin
     motor. El pulido CP-SAT lo orquesta `bridge`.
   - `untis_desktop` — réplica funcional de las ventanas Untis; solo importa la
     Fachada.
3. **Acoples explícitos.** Un nº de lección con varias líneas es un acople. El
   export XmlInterface lo codifica en el id: `LS_<nº><línea>` con la línea en
   0–9. Verificado sobre el export real 2025-2026: 722 lecciones, líneas
   contiguas 0…n−1 y horas idénticas entre líneas en el 100 % de los casos.
4. **Doble escala Untis.** Deseos de tiempo −3…+3 sobre los datos maestros y
   ponderaciones 0–5 (escala no lineal) sobre las reglas. Sustituyen al par
   HC/SC del catálogo como superficie de usuario.
5. **`academic/` obsoleto** con `DeprecationWarning`. Se mantiene solo como
   dependencia interna de `benchmarks` hasta migrarla.
6. **Fronteras verificadas por prueba** (`tests/test_boundaries.py`, por AST):
   `untis_model` puro; `interop` solo ve el modelo; `heuristic` no ve el motor;
   fuera del motor, solo `bridge` lo importa; el motor no importa el producto;
   `untis_desktop` solo importa la Fachada. Las capas legadas que aún importan
   el motor (`academic`, `application`, `serialization`, `untis`) están en una
   lista explícita que la prueba obliga a **encoger**: si una deja de importar el
   motor y sigue en la lista, la prueba falla.

## Consecuencias técnicas

- **Datos personales fuera del repositorio.** Los exports reales de Untis
  contienen nombres, correos y números de nómina. Se guardan en
  `tests/fixtures/real/` (ignorado por git) y los tests que los usan se saltan
  si faltan. La CI usa `tests/fixtures/untis_anon.xml`, generado por
  `scripts/anonymize_untis.py`: misma estructura y mismas colocaciones, sin un
  solo dato personal (ids de profesor que codificaban apellidos incluidos).
- **Semántica de `block` corregida con datos.** El campo `block` de Untis no es
  una lista de tamaños que sumen los períodos: 37 lecciones reales tienen
  `block="2,2"` con 2 períodos/semana y Untis las coloca como un único doble.
  Se guarda tal cual para la ida y vuelta y el requisito operativo se deduce en
  `double_periods_from_block`, validado contra las colocaciones reales.
- **Deuda asumida:** la Fachada actual (`EngineService`, `.bjs`) sigue viva hasta
  R4; convive con las capas nuevas y figura en la lista legada de fronteras.
- **Riesgo de marca:** se replica el modelo de interacción y la organización de
  ventanas de Untis, nunca sus textos, iconos ni capturas.
