# Ejemplo intermedio — Estabilidad de aula

Un docente con tres clases y tres aulas equivalentes de un mismo *pool*. La regla
blanda `teacher_room_stability` (Tier 2) empuja a concentrar al docente en las
menos aulas posibles: menos desplazamientos.

## Ejecutar

```bash
python build.py                        # crea intermediate.bjs
schedule-engine optimize intermediate.bjs
```

## Salida esperada

`optimize` resuelve y guarda métricas e historial. El horario es válido y usa
**una sola aula** para las tres clases (van en períodos distintos por el mismo
docente):

```json
{
  "status": "optimal",
  "hard_violations": 0,
  "solver": "ortools_cpsat"
}
```

Comprueba las métricas guardadas:

```bash
schedule-engine project info intermediate.bjs
```

## Qué aprender aquí

- Cómo se **configura una regla blanda** con su `tier` y `weight` (via
  `PluginsConfig`, que se guarda en `constraints.json` dentro del `.bjs`).
- Que `optimize` persiste `metrics.json` y anexa a `history.json`.
- El patrón de *pool* de aulas (`roompool#S`) que da libertad de reasignación.

Siguiente: [ejemplo avanzado](../advanced/README.md).
