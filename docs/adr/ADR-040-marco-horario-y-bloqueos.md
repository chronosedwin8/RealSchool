# ADR-040: Marco horario y bloqueo de horas

**Fecha:** 2026-09-18 · **Estado:** Aceptado

## Contexto

Al generar un horario desde cero con los datos reales de 2026-2027, el programa
colocaba clase a horas en las que el colegio ya no da servicio. El motor sí
tenía la restricción (un deseo -3 es un bloqueo absoluto y lo respetan la
heurística, CP-SAT y el movimiento manual), pero la interfaz solo permitía
pintar celda a celda o un día entero: cerrar las horas 7 y 8 de 82 clases eran
820 clics. En la práctica, la función existía y era inservible.

La documentación de Untis confirma que ese es su mecanismo: los deseos -3
("keinesfalls Unterricht") son bloqueos absolutos que no hay que ponderar, y
son lo que usa un colegio para decir hasta qué hora tiene clase cada curso. El
export real lo demuestra: 3.930 celdas -3 en el curso 2026-2027. Untis también
asume la misma distribución de horas todos los días salvo que se active su
"Tageszeitraster", así que nuestra rejilla por rejilla (no por día) es fiel.

## Decisión adoptada

1. **Marco horario** como concepto de primera clase, pero guardado como deseos
   -3: `UntisService.time_frame` lo lee ("1-6") y `set_time_frame` lo fija
   cerrando las horas lectivas de fuera en todos los días. Al ser deseos, se
   exporta a Untis sin inventar nada y vuelve igual.
2. **Edición en bloque**: `set_requests` aplica el mismo deseo a varias
   entidades y celdas en un solo paso de deshacer. Una celda es `(día, hora)`
   con `día=None` (esa hora toda la semana) o `hora=None` (el día entero).
3. **Alcance** en la ventana de Deseos: lo que se pinta y el marco horario se
   aplican a este elemento, a todos los que comparten su rejilla o a todos.
4. **Bloquear desde el horario**: `set_blocked`/`blocked_cells` y, en el
   Diálogo de planificación, "Cerrar esta hora" / "Abrir esta hora" con clic
   derecho. Las horas cerradas se dibujan con trama gris allí y en Horarios.
5. **Diagnóstico**: error `marco_horario_insuficiente` cuando una clase necesita
   más horas de las que tiene abiertas (antes se descubría al no poder colocar);
   avisos `marco_horario_abierto` (jornada abierta de más) y
   `hora_corta_abierta` (una hora mucho más corta que las demás sigue abierta,
   como la hora de dirección de grupo de 10 min).
6. **El diálogo de mover ofrece todas las horas lectivas**, como el generador, y
   avisa cuando la hora dura otra cosa ("esta hora dura 10 min y la clase ocupa
   45") en vez de ocultarla.

## Alternativa descartada

Un criterio de ponderación `lesson_period_duration` que costara puntos por
colocar una sesión en una hora de otra duración. Se implementó y se retiró: la
duración prevista de cada sesión sale del horario de referencia, que es el mismo
que se está editando, así que al mover una sesión cambiaba la vara de medir y el
cambio de evaluación que anuncia el diálogo dejaba de coincidir con el real. La
respuesta fiel a Untis es cerrar esas horas con -3, que ahora cuesta un clic, y
que el Diagnóstico avise de ellas.

## Consecuencias

- El marco horario solo maneja deseos de hora completa (`día=None`); los
  bloqueos de celdas sueltas son decisiones aparte y no se tocan al aplicarlo.
- `RequestGrid` gana `period_values` y una fila "Toda la semana" en la rejilla;
  `value()` hereda día y hora, `own_value()` devuelve solo lo escrito en la celda.
- Generación desde cero en 2026-2027 tras el cambio: 4 horas sin colocar de
  2.429 (0,16 %), 0 choques, 108.705 puntos blandos frente a 142.317 de Untis.
