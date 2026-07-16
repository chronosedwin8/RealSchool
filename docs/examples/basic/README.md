# Ejemplo básico

Un horario mínimo factible: un docente, un aula y cinco clases de un período en
una semana de 5 × 5.

## Ejecutar

```bash
python build.py                       # crea basic.bjs
schedule-engine project validate basic.bjs
schedule-engine generate basic.bjs --quick
```

## Salida esperada

`generate` produce un horario válido (sin violaciones duras):

```json
{
  "status": "optimal",
  "objective_value": 0,
  "quality_score": 100.0,
  "hard_violations": 0
}
```

## Qué aprender aquí

- Cómo se construye un `SchedulingProblem` canónico mínimo (`build.py`).
- Que `generate --quick` busca la primera solución factible.
- Que el `.bjs` guarda el horario resultante de forma atómica.

Siguiente: [ejemplo intermedio](../intermediate/README.md).
