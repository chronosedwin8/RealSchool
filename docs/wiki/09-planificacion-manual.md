# Planificación manual

El Diálogo de planificación es donde se retoca el horario a mano: mover, intercambiar, fijar o
quitar clases viendo al momento si el cambio es posible y cuánto mejora o empeora el horario.

![Diálogo de planificación](img/planning.png)

## Qué se ve

Arriba, `Horario de:` elige el tipo (`Clase`, `Profesor` o `Aula`) y, al lado, la entidad
concreta. A la derecha, el número de evaluación del horario activo:
`Evaluación: 1.218.418 (4 sin colocar, 7 choques)`.

En el centro, la cuadrícula: los días en columnas, los períodos en filas con su hora de reloj.
Cada celda lleva la materia y el profesor, con el color de la materia. Los recreos salen en
gris y no se pueden usar.

A la izquierda, la lista `Sin colocar`. Abajo, el recordatorio:

> Arrastra una clase para moverla: verde = puede ir ahí, rojo = no cabe. Clic derecho para
> fijar, desprogramar o intercambiar. Esc cancela.

La leyenda de la barra de herramientas explica los colores: `Puede ir aquí`, `No cabe`,
`Choque`, `Fijada`, `Hora cerrada (-3)`.

El panel sigue lo que elijas en las demás ventanas, y el Diagnóstico salta aquí con doble clic.

## Mover una clase arrastrando

1. Pulsa sobre la celda que quieres mover y arrastra sin soltar.
2. La cuadrícula se pinta entera: **verde** donde la sesión puede ir, **rojo** donde no cabe.
3. Pasa el ratón por encima de un destino verde y espera un instante.
4. Suelta en el destino que quieras.

Si sueltas en un destino rojo no pasa nada y el motivo sale en la barra de estado. Esc cancela
el arrastre en cualquier momento.

El movimiento se puede deshacer con Ctrl+Z.

## Los destinos en verde y en rojo

Al empezar el arrastre, el programa calcula de una vez todos los destinos posibles y los
colorea. Cada celda roja lleva su motivo en la ayuda emergente, precedido de `No cabe:`

| Motivo | Qué quiere decir |
| --- | --- |
| `profesor T012 ocupado (lección 949)` | Ese profesor ya tiene clase a esa hora |
| `clase KK1 ocupado (lección 951)` | Esa clase ya tiene otra materia a esa hora |
| `aula A101 ocupado (lección 950)` | El aula que pide la lección está cogida |
| `deseo imposible (-3)` | La hora está cerrada para alguien de esa lección |
| `lección fijada` | La lección está fijada y no se mueve de su sitio |
| `la lección ya está en esa celda` | Otro período de la misma lección ocupa ese hueco |

Hay además un aviso que no impide soltar, precedido de `Ojo:` Por ejemplo
`esta hora dura 20 min y la clase ocupa 45`: cabe, pero la duración no coincide y eso costará
puntos.

## El cambio de evaluación antes de soltar

Esto es lo más útil del diálogo. Mientras arrastras, al pasar sobre un destino verde el
programa calcula el horario resultante de verdad y muestra el cambio exacto:

    Cambio de evaluación: -240

- Un número **negativo** significa que el horario mejora. Suelta sin miedo.
- Un número **positivo** significa que empeora. Suéltalo solo si sabes por qué lo haces (un
  compromiso con un profesor, una petición de familias).

El cálculo tarda un instante, así que deja el ratón quieto medio segundo sobre la celda. Si
todavía no está calculado, la celda dice solo `Destino posible`.

La etiqueta de al lado del arrastre también resume cuántas opciones tienes:
`Lección 948: 37 destino(s) posible(s)`.

## Fijar y desfijar

Fijar una clase significa clavarla: la optimización no la moverá de ahí en las siguientes
generaciones.

1. Haz clic en la celda.
2. Pulsa `Fijar` en la barra de herramientas, o clic derecho y `Fijar`.

El botón cambia a `Desfijar` cuando la celda ya está fijada. Las celdas fijadas se ven con un
borde oscuro y una chincheta en la esquina.

Es la herramienta para conservar lo que ya has negociado: fija esas horas y vuelve a generar
con tranquilidad, que no se te moverán.

También se puede fijar la lección entera desde la columna `Fijar` de
[Lecciones](05-lecciones.md).

## Desprogramar (F7)

Desprogramar quita la clase de su hora y la devuelve a la lista `Sin colocar`, sin borrarla.

1. Haz clic en la celda.
2. Pulsa F7, o el botón `Desprogramar`, o clic derecho y `Desprogramar (F7)`.

También funciona arrastrando: suelta la celda encima de la lista `Sin colocar`.

Sirve para desatascar. Si una zona del horario está mal, desprograma tres o cuatro sesiones,
mira dónde caben ahora y vuelve a colocarlas una a una.

## Intercambiar dos sesiones

Cuando el hueco al que quieres ir está ocupado, no hace falta desprogramar las dos: se
intercambian.

1. Haz clic en la primera celda.
2. Pulsa `Intercambiar`, o clic derecho y `Intercambiar con...`.
3. La barra dice `Elige la celda con la que intercambiar (Esc cancela)` y se marcan en verde las
   candidatas.
4. Haz clic en la celda con la que quieres cambiarla.

Solo son candidatas las celdas ocupadas por otra lección **de la misma duración**. Si no se
marca ninguna en verde, no hay ningún intercambio limpio posible desde esa celda.

## Cerrar y abrir una hora

Con el clic derecho sobre cualquier celda:

- `Cerrar esta hora`: `Pone un deseo -3: ni la optimización ni tú podréis poner clase aquí`.
- `Abrir esta hora`: `Vuelve a permitir clase aquí (quita el deseo -3)`.

Es el atajo rápido al marco horario: si al mirar el horario de un curso ves que la última hora
del viernes no debería existir, ciérrala desde aquí sin ir a
[Deseos de tiempo y marco horario](04-deseos-y-marco-horario.md).

Las horas cerradas se ven en gris oscuro, con la ayuda
`Hora cerrada (-3): aquí no puede haber clase`.

Ojo: cerrar horas reduce el sitio disponible. Si cierras demasiado, la próxima generación dejará
períodos sin colocar y el Diagnóstico te lo dirá.

## La lista de sesiones sin colocar

A la izquierda están los períodos de esa clase, profesor o aula que todavía no tienen hora.
Cada fila dice la lección, la materia, el profesor y cuántos faltan:

    948 KK-MUSI T022: 1 sin colocar

Para colocar una, arrástrala desde la lista hasta un hueco verde de la cuadrícula. Igual que al
mover, el destino se pinta y el cambio de evaluación se ve antes de soltar.

Cuando no queda nada pendiente, la lista pone `Todo colocado.`

El menú contextual también ofrece `Abrir lección {n}`, que muestra esa lección en la ventana
[Lecciones](05-lecciones.md). El doble clic sobre una celda hace lo mismo.

## Errores frecuentes

**"Arrastro una clase y toda la cuadrícula se pone roja."**
Esa sesión no cabe en ningún otro sitio con los datos actuales. Pasa el ratón por dos o tres
celdas rojas y lee el motivo: casi siempre es el mismo profesor ocupado en todas partes, o la
lección está fijada. Si es lo segundo, desfíjala primero.

**"He movido varias clases y ahora la Evaluación marca choques."**
Mover a mano puede dejar dos sesiones pisándose si el destino era rojo por otra entidad. Ve a
[Generar el horario](07-generar-el-horario.md), elige la estrategia `Reparar` y pulsa
`Iniciar`: corrige los choques tocando lo mínimo.

**"Quiero mover una clase y el programa dice 'lección fijada'."**
Alguien (o tú en otro momento) fijó esa lección. Haz clic en la celda y pulsa `Desfijar`, o
quita la marca de la columna `Fijar` en Lecciones.

---

Siguiente: [Horarios, impresión y PDF](10-horarios-impresion-y-pdf.md).
