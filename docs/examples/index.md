# Ejemplos ejecutables

Proyectos completos y funcionales, ejecutables con `schedule-engine` sin
modificaciones. Cada carpeta trae un `build.py` que genera el `.bjs` de entrada,
un `README.md` con los comandos y la salida esperada.

| Nivel | Qué muestra |
|---|---|
| [Básico](basic/README.md) | Un horario mínimo factible, resuelto con `generate`. |
| [Intermedio](intermediate/README.md) | Configurar una regla blanda (estabilidad de aula) y `optimize`. |
| [Avanzado](advanced/README.md) | Varias reglas por Tiers + cómo medir con benchmarks. |

Todos se validan en CI: un test recorre `docs/examples/` y comprueba que cada uno
construye su proyecto y resuelve sin errores.

```bash
# patrón común
python docs/examples/basic/build.py        # crea basic.bjs
schedule-engine generate basic.bjs --quick
```
