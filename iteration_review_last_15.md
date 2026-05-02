# iteration_review_last_15

## 1. Executive summary
- Corridas auditadas: **15**
- Aceptadas: **10** | Rechazadas: **5**
- Branch health (estado): **stagnating**
- Main friction (estado): **long_window_depth**
- Current mode (estado): **controlled_exploration**
- Mode reason (estado): **branch_reboot_from_exp127_due_to_stagnation**
- Mode stability counter (estado): **0**
- Watchdog health class: **n/a**
- Watchdog safe_mode_active: **0**
- Watchdog restart_count_last_24h: **0**
- Branch anchor: baseline=``/None rem=0 ; research=``/None rem=0 ; sync_ok=1

## 2. Que cambio en estas iteraciones
- Ultimo baseline promovido: **EXP_229**
- Ultima corrida util: **EXP_229**
- Distribucion de status: `{'blocked_no_material_candidate': 2, 'run_ok': 13}`

## 3. Tabla de corridas

| run_id | parent_run_id | cambio principal | decision | followup | baseline | w24_spy | w52_spy | 156_status |
|---|---|---|---|---|---|---:|---:|---|
| EXP_1276 | EXP_396 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1277 | EXP_396 | - | blocked_no_material_candidate | no | no |  |  | n/a |
| EXP_1278 | BASELINE_CLEAN | TOP_CANDIDATES_NEXT_WEEK: 5.0 -> 4 | run_ok | yes | no | 2,85149108474 | 1,82191095604 | n/a |
| EXP_1279 | EXP_1278 | TOP_SIMILAR_SPY_WEEKS: 20.0 -> 28 | run_ok | no | no | 1,22649108474 | 1,34764320753 | n/a |
| EXP_1280 | EXP_1278 | TOP_CANDIDATES_NEXT_WEEK: 4.0 -> 2 | run_ok | yes | no | 4,53899108474 | 2,86199667513 | n/a |
| EXP_1281 | EXP_1280 | MAX_AVG_PROFILE_DISTANCE: 0.2 -> 0.17 | run_ok | yes | no | 5,87480241439 | 3,18051911045 | n/a |
| EXP_1282 | EXP_1281 | MIN_SPY_CHANNEL_R2: 0.55 -> 0.52 | run_ok | no | no | 0,915787959427 | 2,40654636696 | n/a |
| EXP_1283 | BASELINE_CLEAN | TOP_CANDIDATES_NEXT_WEEK: 5.0 -> 3 | run_ok | yes | no | 3,20565775141 | 2,23853988501 | n/a |
| EXP_1284 | EXP_1283 | MIN_SPY_CHANNEL_R2: 0.55 -> 0.5 | run_ok | yes | no | 1,57518355034 | 1,9548076914 | n/a |
| EXP_1285 | EXP_1284 | MAX_AVG_PROFILE_DISTANCE: 0.2 -> 0.18 | run_ok | yes | no | 2,02689907054 | 2,26964160505 | n/a |
| EXP_1286 | EXP_1285 | TOP_CANDIDATES_NEXT_WEEK: 3.0 -> 2 | run_ok | yes | no | 0,86089783605 | 2,3418915645 | n/a |
| EXP_1287 | EXP_1286 | MIN_SPY_CHANNEL_R2: 0.5 -> 0.47 | run_ok | yes | no | 1,19498254577 | 2,38161436281 | n/a |
| EXP_1288 | EXP_1287 | MAX_AVG_PROFILE_DISTANCE: 0.18 -> 0.17 | run_ok | yes | no | 1,28975761006 | 2,44540944099 | n/a |
| EXP_1289 | EXP_1288 | MIN_SPY_CHANNEL_R2: 0.47 -> 0.44 | run_ok | no | no | 0,643636514062 | 2,23458875436 | n/a |
| EXP_1290 | BASELINE_CLEAN | MAX_AVG_PROFILE_DISTANCE: 0.2 -> 0.18 | run_ok | yes | no | 2,87480241439 | 1,16889905859 | n/a |

## 4. Mejores corridas
- `EXP_1281`: w52_spy_compare=3,18051911045, status=run_ok
- `EXP_1280`: w52_spy_compare=2,86199667513, status=run_ok
- `EXP_1288`: w52_spy_compare=2,44540944099, status=run_ok

## 5. Peores corridas
- `EXP_1276`: status=blocked_no_material_candidate, w52_spy_compare=
- `EXP_1277`: status=blocked_no_material_candidate, w52_spy_compare=

## 6. Que aprendio el sistema
- Hubo corridas aceptadas para follow-up, el loop siguio generando evidencia util.
- Promedio de w52_spy_compare en ultimas 13 validas: 2.204.

## 7. Que no esta funcionando
- Hay estancamiento ocasional por falta de candidato material.
- Hay rechazos con w52_spy_compare alto: posible conversion suboptima de evidencia a follow-up/baseline.

## 8. Evaluacion tipo auditor v2
- process_reliability_score: **95.00**
- analyst_quality_score: **90.00**
- coordinator_quality_score: **68.33**
- research_effectiveness_score: **93.33**
- overall_agent_score: **86.67**

## 9. Proximos 3 cambios recomendados
1. Forzar fallback de segunda capa antes de no_material_candidate_found.
2. Extender validacion a 156 solo cuando 52w sea fuerte para ahorrar tiempo y ruido.
3. Mantener anchor de parametro dominante 2-3 iteraciones para evitar whipsaw.

## 10. Riesgos de seguir como esta
- Riesgo de consumo de iteraciones por bloqueos administrativos (duplicate/zigzag/no_material).
- Riesgo de sobreajuste corto si no se privilegia senal en 52w.
- Riesgo de estancamiento de rama si no se alterna refine con exploracion ortogonal controlada.
- Riesgo de perder aprendizaje util al rechazar corridas con senal 52w fuerte sin follow-up claro.

> Nota: reporte generado automaticamente; los scores auditor v2 son estimados por heuristica sobre artefactos disponibles.
