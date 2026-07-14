# ADR-015: Formulación por intervalos y escala objetivo

**Fecha:** 2026-07-14 · **Estado:** Aceptado · **Salda la deuda de:** ADR-011

## Contexto
ADR-011 dejó registrada una deuda explícita: la formulación booleana del
no-solape genera O(tareas x recursos x períodos) variables auxiliares y no
escalaría a la institución objetivo (500 docentes, 300 aulas, 1500 grupos). La
Fase 11 debía medirlo y, si procedía, ejecutar la deuda.

**Se midió, y la deuda era real.** Con la formulación original el objetivo XL
tardaba **5,7 minutos** y **no encontraba solución**.

## Decisiones adoptadas

### 1. No-solape con intervalos opcionales (`IntervalNoOverlapPlugin`)
En vez de una variable de ocupación por (tarea, recurso, período), se crea **un
intervalo opcional por (tarea, recurso elegible)**, presente solo si la tarea usa
ese recurso, y se delega el no-solape en la restricción global del solver. El
tamaño del modelo deja de depender del horizonte.

Esto obligó a extender la SAL (`new_interval`, `new_optional_interval`,
`add_no_overlap`) y a propagarlo por DSL y CIR. **El dominio y las reglas no se
tocaron**: es exactamente la prueba de fuego que la arquitectura prometía.

**Corrección demostrada, no asumida:** un test *differential* verifica que ambas
formulaciones dan el mismo veredicto de factibilidad y el mismo óptimo sobre un
conjunto de instancias, y que ambos horarios superan la validación independiente.

### 2. Codificación booleana de inicios **opcional** (modo compacto)
Con intervalos, el inicio de una clase es una variable *entera* (`tstart`). Las
booleanas `start[t,s]` pasan a ser redundantes… salvo para las reglas que razonan
período a período (preferencias, almuerzo, carga diaria). Se hacen opcionales
(`boolean_starts=False`): cuando ninguna regla activa las necesita, el modelo
prescinde de ellas. Para que `tstart` siga siendo correcto por sí solo, su
dominio pasa a ser un **`EnumDomain`** con exactamente los inicios válidos
(pueden tener huecos: una clase doble no puede empezar a última hora).

Si una regla pide las booleanas estando desactivadas, se lanza
`BooleanStartsDisabled`: **falla claramente, no en silencio**.

### 3. Cuellos de botella eliminados (perfilado, no intuición)
La telemetría por etapa señaló dos problemas que no eran del solver sino de
nuestro código Python:
- `DetectContradictions` buscaba el dominio de cada variable recorriendo
  linealmente la tupla de variables (441k) **por cada restricción**: cuadrático.
  Se indexa en un dict. **143s → 1,8s (81x).**
- Los plugins se consultaban **dos veces** (una para el modelo, otra para las
  penalizaciones) y cruzaban todas las tareas contra todos los recursos.
  Se consulta una vez y se precalcula un índice recurso→tareas. **150s → 17s.**
- Las expresiones lineales se construían sumando término a término,
  re-normalizando en cada paso (O(k^2)). Se añade `LinearExpr.from_terms`, que
  normaliza una sola vez.

## Resultado medido (DS-XL: 500 docentes, 300 aulas, 1500 grupos, 7500 clases)

| | Antes (booleana) | Después (intervalos + compacto) |
|---|---|---|
| Variables | 441.000 | **52.500** (8,4x menos) |
| Pases del CIR | 143.431 ms | **374 ms** |
| Construcción del modelo | 150.330 ms | **6.658 ms** |
| Búsqueda | sin solución en 90s | **17.324 ms** |
| **Total** | 342s, **sin horario** | **32s, horario óptimo y válido** |
| RAM pico | 407 MB | **75 MB** |

**La escalabilidad objetivo de Prompt3 §4 se cumple**: 0 violaciones duras,
horario validado por el Validation Engine independiente.

## Consecuencias técnicas
- La formulación booleana (`ResourceNoOverlapPlugin`) **se conserva**: es la
  referencia contra la que se valida la compacta, y sigue siendo la única
  compatible con reglas que necesitan ocupación por período.
- **Aviso de diseño de datasets:** un colegio al 100% de ocupación de aulas es un
  problema de empaquetado perfecto, brutalmente difícil e irreal. Los datasets
  sintéticos operan al ~71%, la holgura con la que trabaja un colegio de verdad.
- **Deuda restante:** las reglas por período (preferencias, almuerzo, carga
  diaria) siguen exigiendo la codificación booleana. Reformularlas sobre `tstart`
  permitiría el modo compacto también con ellas activas.
