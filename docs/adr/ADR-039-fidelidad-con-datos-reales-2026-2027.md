# ADR-039: Fidelidad con los datos reales del curso 2026-2027

**Fecha:** 2026-09-18 · **Estado:** Aceptado

## Contexto

Se repitió la batería completa, desde cero, con el export real del curso
2026-2027 (XmlInterface + GPU001…GPU016): 82 clases, 154 profesores, 96 aulas,
884 lecciones, 6 rejillas, 2 429 sesiones y 5 582 deseos de tiempo. Los datos
destaparon cinco supuestos erróneos que los datos de 2025-2026 no revelaban, y la
generación desde cero dejaba 114 horas sin colocar (4,7 %).

## Decisión adoptada

1. **Id de lección de dos dígitos de línea.** `LS_134500` es la lección 1345,
   línea 00 (`LINES_PER_LESSON = 100`): hay acoples de hasta 45 líneas.
   Verificado contra GPU002 (884/884 números).
2. **Solo el deseo -3 es duro.** El +3 ("muy deseable") es blando, como en
   Untis: cuesta su valor por cada celda deseada que queda libre. Tratarlo como
   duro hacía imposibles horarios que Untis sí publica.
3. **Hora 0.** `SchoolInfo.first_period` (0 o 1): Untis numera los períodos del
   GPU001 con su etiqueta (este colegio empieza en la hora 0, la dirección de
   grupo de 10 min) mientras XML y GPU016 usan índices desde 1. Se detecta al
   leer el GPU001 (también el que acompaña a un XML) y se respeta al escribirlo:
   nuestro GPU001 es idéntico al de Untis (4 102/4 102 filas).
4. **Bytes que Untis escribe fuera de cp1252** (p. ej. 0x8D): manejador de
   errores `untis-cp1252` que los conserva byte a byte al leer y escribir.
5. **Deseos desde el GPU016 vecino.** El XmlInterface no exporta los deseos de
   tiempo: al abrir un XML se importan del GPU016 de la misma carpeta, si existe.
6. **Cualquier período lectivo, dure lo que dure.** La heurística exigía que una
   sesión fuera a un período de la misma duración que en la referencia (o la
   dominante de la rejilla). Untis no tiene esa regla; con ella, clases con 28
   sesiones solo tenían 27 celdas de 45 min libres de deseos -3. Ahora una
   sesión puede ir a cualquier período lectivo de su rejilla y los deseos reales
   del colegio deciden qué va en cada uno.

## Consecuencias técnicas

- Generación desde cero (estrategia A, 45 s, sin horario de Untis): 2 horas sin
  colocar de 2 429 (antes 114), 0 choques y ningún -3 incumplido, 110 709 puntos
  blandos frente a 142 317 del horario publicado por Untis (3 sin colocar, 3
  choques) con la misma ponderación. Reparar el horario de 2025-2026 coloca
  ahora también las 4 horas que Untis dejó fuera.
- El puente al motor mantiene una duración fija por `Task`: el motor congelado
  mide el tiempo en minutos para detectar choques entre rejillas con horas
  distintas. La toma del período donde la sesión está colocada en la referencia,
  así que todo horario de la heurística se traduce con sus duraciones reales.
  Solo las sesiones **sin colocar** usan la duración dominante; por eso la
  generación desde cero se hace con la heurística y CP-SAT repara y pule.
- `tests/test_real_2026_2027.py` fija todo lo anterior; se salta si el export
  real (con datos personales, fuera del repositorio) no está presente.
