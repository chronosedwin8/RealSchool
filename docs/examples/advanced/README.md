# Ejemplo avanzado — Reglas por Tiers y benchmarking

Un grupo con seis clases donde **dos reglas blandas compiten**:

| Regla | Tier | Efecto |
|---|---|---|
| `weekly_balance` | 2 (operativa) | reparte las clases entre los días |
| `prefer_early_slots` | 3 (preferencial) | prefiere las primeras horas |

La **dominancia lexicográfica** de los Tiers garantiza que primero se equilibra la
semana; solo entre las opciones ya equilibradas se eligen las horas más tempranas.
(Concepto en [Restricciones y Tiers](../../architecture/scoring_tiers.md).)

## Ejecutar

```bash
python build.py                    # crea advanced.bjs
schedule-engine optimize advanced.bjs --json-stream
```

Con `--json-stream` verás el progreso en vivo (útil para una GUI):

```json
{"event": "solver_searching", "stage": "search", "percentage": 60}
{"event": "completed", "result": {"status": "optimal", "hard_violations": 0}}
```

## Añadir tu propia regla y medirla

1. Escribe el plugin siguiendo la [guía de restricciones](../../sdk_guide/constraints.md)
   y regístralo en el catálogo (`plugins/constraint_catalog.py`).
2. Actívalo en `constraints.json` del `.bjs` con su `tier` y `weight`.
3. Mídelo: el framework de benchmarking ejecuta escenarios con estadística
   (P50/P95/P99, IC95) y detecta regresiones.

```bash
python scripts/bench.py quick                 # suite rápida con estadística
python scripts/regression_gate.py             # falla si el P50 sube > 5% o baja el score
```

## Qué aprender aquí

- Cómo **combinar reglas de distinto Tier** y por qué el orden lexicográfico
  importa.
- Cómo el `.bjs` transporta la configuración completa (reglas, pesos, tiers).
- Cómo medir el impacto de una regla nueva sin degradar el resto.
