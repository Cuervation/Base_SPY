# iteration_review_last_15

## 1. Executive summary
- Corridas auditadas: **15**
- Aceptadas: **4** | Rechazadas: **11**
- Branch health (estado): **alive_but_noisy**
- Main friction (estado): **long_window_depth**
- Current mode (estado): **refine_current_branch**
- Mode reason (estado): **bootstrap_from_recommended_next_action**
- Mode stability counter (estado): **1**
- Watchdog health class: **n/a**
- Watchdog safe_mode_active: **0**
- Watchdog restart_count_last_24h: **0**
- Branch anchor: baseline=``/None rem=0 ; research=``/None rem=0 ; sync_ok=1

## 2. Que cambio en estas iteraciones
- Ultimo baseline promovido: **EXP_068**
- Ultima corrida util: **EXP_134**
- Distribucion de status: `{'run_partial_valid': 14, 'run_ok': 1}`

## 3. Tabla de corridas

| run_id | parent_run_id | cambio principal | decision | followup | baseline | w24_spy | w52_spy | 156_status |
|---|---|---|---|---|---|---:|---:|---|
| EXP_120 | EXP_116 | MAX_AVG_PROFILE_DISTANCE: 0.26 -> 0.17 | run_partial_valid | no | no |  | 1,6174653822 | n/a |
| EXP_121 | EXP_116 | TOP_SIMILAR_SPY_WEEKS: 24.0 -> 16 | run_partial_valid | no | no | 8,45597799414 | 1,35095029395 | n/a |
| EXP_122 | EXP_116 | MAX_AVG_PROFILE_DISTANCE: 0.26 -> 0.17 | run_partial_valid | no | no |  | 1,6174653822 | n/a |
| EXP_123 | EXP_116 | TOP_SIMILAR_SPY_WEEKS: 24.0 -> 16 | run_partial_valid | no | no | 8,45597799414 | 1,35095029395 | n/a |
| EXP_124 | EXP_116 | ENABLE_CLOSE_VS_SMA50_FILTER: False -> True | run_partial_valid | no | no | 0,622988052573 | 1,02448759537 | n/a |
| EXP_125 | EXP_116 | MAX_AVG_PROFILE_DISTANCE: 0.26 -> 0.22 | run_partial_valid | yes | no | 1,2692264809 | 1,61034112728 | n/a |
| EXP_126 | EXP_125 | TOP_CANDIDATES_NEXT_WEEK: 5.0 -> 2 | run_ok | yes | no | 3,5959438722 | 3,81927862728 | n/a |
| EXP_127 | EXP_126 | MAX_AVG_PROFILE_DISTANCE: 0.22 -> 0.17 | run_partial_valid | yes | no | 4,11359533063 | 4,11359533063 | n/a |
| EXP_128 | EXP_127 | TOP_CANDIDATES_NEXT_WEEK: 2.0 -> 4 | run_partial_valid | no | no | 1,7230546144 | 1,7230546144 | n/a |
| EXP_129 | EXP_127 | TOP_CANDIDATES_NEXT_WEEK: 2.0 -> 4 | run_partial_valid | no | no | 1,7230546144 | 1,7230546144 | n/a |
| EXP_130 | EXP_127 | TOP_CANDIDATES_NEXT_WEEK: 2.0 -> 4 | run_partial_valid | no | no | 1,7230546144 | 1,7230546144 | n/a |
| EXP_131 | EXP_127 | TOP_CANDIDATES_NEXT_WEEK: 2.0 -> 5 | run_partial_valid | no | no | 1,6174653822 | 1,6174653822 | n/a |
| EXP_132 | EXP_127 | TOP_CANDIDATES_NEXT_WEEK: 2.0 -> 5 | run_partial_valid | no | no | 1,6174653822 | 1,6174653822 | n/a |
| EXP_133 | EXP_127 | TOP_CANDIDATES_NEXT_WEEK: 2.0 -> 5 | run_partial_valid | no | no | 1,6174653822 | 1,6174653822 | n/a |
| EXP_134 | EXP_127 | TOP_CANDIDATES_NEXT_WEEK: 2.0 -> 3 | run_partial_valid | yes | no | 3,20883342587 | 3,20883342587 | n/a |

## 4. Mejores corridas
- `EXP_127`: w52_spy_compare=4,11359533063, status=run_partial_valid
- `EXP_126`: w52_spy_compare=3,81927862728, status=run_ok
- `EXP_134`: w52_spy_compare=3,20883342587, status=run_partial_valid

## 5. Peores corridas
- `EXP_124`: status=run_partial_valid, w52_spy_compare=1,02448759537
- `EXP_121`: status=run_partial_valid, w52_spy_compare=1,35095029395
- `EXP_123`: status=run_partial_valid, w52_spy_compare=1,35095029395

## 6. Que aprendio el sistema
- Hubo corridas aceptadas para follow-up, el loop siguio generando evidencia util.
- Promedio de w52_spy_compare en ultimas 15 validas: 1.982.
- Se preservo evidencia parcial cuando hubo validacion larga no completa.

## 7. Que no esta funcionando
- Subespacios agotados repetidos en bloque reciente: TOP_CANDIDATES_NEXT_WEEK:2->4, TOP_CANDIDATES_NEXT_WEEK:2->5.

## 8. Evaluacion tipo auditor v2
- process_reliability_score: **100.00**
- analyst_quality_score: **85.33**
- coordinator_quality_score: **60.33**
- research_effectiveness_score: **85.33**
- overall_agent_score: **82.75**

## 9. Proximos 3 cambios recomendados
1. Extender validacion a 156 solo cuando 52w sea fuerte para ahorrar tiempo y ruido.
2. Mantener anchor de parametro dominante 2-3 iteraciones para evitar whipsaw.

## 10. Riesgos de seguir como esta
- Riesgo de consumo de iteraciones por bloqueos administrativos (duplicate/zigzag/no_material).
- Riesgo de sobreajuste corto si no se privilegia senal en 52w.
- Riesgo de estancamiento de rama si no se alterna refine con exploracion ortogonal controlada.
- Riesgo de whipsaw parametrico por insistencia en subespacios agotados.

> Nota: reporte generado automaticamente; los scores auditor v2 son estimados por heuristica sobre artefactos disponibles.
