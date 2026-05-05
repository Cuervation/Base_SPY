# iteration_review_last_15

## 1. Executive summary
- Corridas auditadas: **15**
- Aceptadas: **0** | Rechazadas: **15**
- Branch health (estado): **stagnating**
- Main friction (estado): **candidate_generation**
- Current mode (estado): **safe_recovery_mode**
- Mode reason (estado): **watchdog_high_restart_volume_24h**
- Mode stability counter (estado): **4**
- Watchdog health class: **n/a**
- Watchdog safe_mode_active: **0**
- Watchdog restart_count_last_24h: **0**
- Branch anchor: baseline=``/None rem=0 ; research=``/None rem=0 ; sync_ok=1

## 2. Que cambio en estas iteraciones
- Ultimo baseline promovido: **EXP_229**
- Ultima corrida util: **EXP_229**
- Distribucion de status: `{'blocked_no_material_candidate': 15}`

## 3. Tabla de corridas

| run_id | parent_run_id | cambio principal | decision | followup | baseline | w24_spy | w52_spy | 156_status |
|---|---|---|---|---|---|---:|---:|---|
| EXP_1522 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1523 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1524 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1525 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1526 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1527 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1528 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1529 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1530 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1531 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1532 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1533 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1534 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1535 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1536 | EXP_392 | - | blocked_no_material_candidate | no | no |  |  | n/a |

## 4. Mejores corridas
- n/a

## 5. Peores corridas
- `EXP_1522`: status=blocked_no_material_candidate, w52_spy_compare=
- `EXP_1523`: status=blocked_no_material_candidate, w52_spy_compare=
- `EXP_1524`: status=blocked_no_material_candidate, w52_spy_compare=

## 6. Que aprendio el sistema
- No hay evidencia suficiente para afirmar aprendizaje solido en este bloque.

## 7. Que no esta funcionando
- Hay estancamiento ocasional por falta de candidato material.
- Falta senal suficiente en 52w dentro del bloque auditado.

## 8. Evaluacion tipo auditor v2
- process_reliability_score: **62.50**
- analyst_quality_score: **45.00**
- coordinator_quality_score: **55.00**
- research_effectiveness_score: **40.00**
- overall_agent_score: **50.62**

## 9. Proximos 3 cambios recomendados
1. Forzar fallback de segunda capa antes de no_material_candidate_found.
2. Extender validacion a 156 solo cuando 52w sea fuerte para ahorrar tiempo y ruido.
3. Mantener anchor de parametro dominante 2-3 iteraciones para evitar whipsaw.

## 10. Riesgos de seguir como esta
- Riesgo de consumo de iteraciones por bloqueos administrativos (duplicate/zigzag/no_material).
- Riesgo de sobreajuste corto si no se privilegia senal en 52w.
- Riesgo de estancamiento de rama si no se alterna refine con exploracion ortogonal controlada.

> Nota: reporte generado automaticamente; los scores auditor v2 son estimados por heuristica sobre artefactos disponibles.
