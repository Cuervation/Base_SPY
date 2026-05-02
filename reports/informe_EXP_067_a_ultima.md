# Informe de Corridas EXP_067 a EXP_123

- Corridas analizadas: **57**
- Rango: **EXP_067 -> EXP_123**
- Aceptadas: **15**
- Rechazadas: **42**
- Acceptance rate: **26.3%**
- Corridas con w52_spy_compare informado: **50**
- Promedio w52_spy_compare: **1.935**
- % corridas con w52_spy_compare > 0: **100.0%**

## Estado de corridas (status)
- `run_partial_valid`: **35**
- `run_ok`: **15**
- `blocked_duplicate`: **5**
- `blocked_preflight`: **1**
- `run_error`: **1**

## Parametros mas tocados
- `TOP_SIMILAR_SPY_WEEKS`: **24** veces
- `TOP_CANDIDATES_NEXT_WEEK`: **17** veces
- `MAX_AVG_PROFILE_DISTANCE`: **13** veces
- `MIN_SPY_CHANNEL_R2`: **3** veces

## Top 5 por w52_spy_compare
| run_id | status | accepted | main_change | w52_spy_compare | w52_pnl |
|---|---|---|---|---:|---:|
| EXP_112 | run_partial_valid | rejected | MAX_AVG_PROFILE_DISTANCE: 0.26->0.17 | 4.113595 | 919.200 |
| EXP_110 | run_partial_valid | accepted | TOP_CANDIDATES_NEXT_WEEK: 3.0->2 | 3.819279 | 969.800 |
| EXP_075 | run_ok | accepted | MAX_AVG_PROFILE_DISTANCE: 0.2->0.17 | 3.460708 | 959.800 |
| EXP_074 | run_ok | accepted | TOP_CANDIDATES_NEXT_WEEK: 3.0->2 | 3.271636 | 1010.400 |
| EXP_076 | run_ok | accepted | MAX_AVG_PROFILE_DISTANCE: 0.17->0.22 | 3.271636 | 1010.400 |

## Bottom 5 por w52_spy_compare
| run_id | status | accepted | main_change | w52_spy_compare | w52_pnl |
|---|---|---|---|---:|---:|
| EXP_070 | run_ok | rejected | MAX_AVG_PROFILE_DISTANCE: 0.2->0.17 | 1.061232 | 828.000 |
| EXP_078 | run_ok | accepted | TOP_CANDIDATES_NEXT_WEEK: 2.0->5 | 1.178507 | 1113.137 |
| EXP_071 | run_ok | rejected | MAX_AVG_PROFILE_DISTANCE: 0.2->0.18 | 1.211472 | 1034.000 |
| EXP_067 | run_ok | accepted | MIN_SPY_CHANNEL_R2: 0.55->0.58 | 1.298924 | 1086.503 |
| EXP_117 | run_partial_valid | rejected | TOP_SIMILAR_SPY_WEEKS: 24.0->16 | 1.350950 | 943.503 |

## Top 5 por PnL 52w
| run_id | status | accepted | main_change | w52_pnl | w52_spy_compare |
|---|---|---|---|---:|---:|
| EXP_068 | run_ok | accepted | TOP_SIMILAR_SPY_WEEKS: 20.0->24 | 1237.137 | 1.539939 |
| EXP_078 | run_ok | accepted | TOP_CANDIDATES_NEXT_WEEK: 2.0->5 | 1113.137 | 1.178507 |
| EXP_087 | run_ok | accepted | MIN_SPY_CHANNEL_R2: 0.61->0.64 | 1112.200 | 2.867890 |
| EXP_072 | run_ok | accepted | TOP_CANDIDATES_NEXT_WEEK: 5.0->3 | 1100.600 | 2.246945 |
| EXP_080 | run_ok | accepted | TOP_CANDIDATES_NEXT_WEEK: 5.0->3 | 1100.600 | 2.246945 |

## Top 5 por Win Rate 52w
| run_id | status | accepted | w52_wins | w52_trades | w52_winrate | main_change |
|---|---|---|---:|---:|---:|---|
| EXP_112 | run_partial_valid | rejected | 19 | 42 | 45.24% | MAX_AVG_PROFILE_DISTANCE: 0.26->0.17 |
| EXP_075 | run_ok | accepted | 21 | 48 | 43.75% | MAX_AVG_PROFILE_DISTANCE: 0.2->0.17 |
| EXP_110 | run_partial_valid | accepted | 21 | 48 | 43.75% | TOP_CANDIDATES_NEXT_WEEK: 3.0->2 |
| EXP_074 | run_ok | accepted | 23 | 54 | 42.59% | TOP_CANDIDATES_NEXT_WEEK: 3.0->2 |
| EXP_076 | run_ok | accepted | 23 | 54 | 42.59% | MAX_AVG_PROFILE_DISTANCE: 0.17->0.22 |

## Ultimas corridas (EXP_116 en adelante)
| run_id | status | accepted | parent_run_id | main_change | w24_spy | w52_spy | w52_pnl |
|---|---|---|---|---|---:|---:|---:|
| EXP_116 | run_partial_valid | accepted | EXP_114 | TOP_CANDIDATES_NEXT_WEEK: 4.0->5 | 9,45597799414 | 1,61034112728 | 1099,1373 |
| EXP_117 | run_partial_valid | rejected | EXP_116 | TOP_SIMILAR_SPY_WEEKS: 24.0->16 | 8,45597799414 | 1,35095029395 | 943,5026 |
| EXP_118 | run_partial_valid | rejected | EXP_116 | MAX_AVG_PROFILE_DISTANCE: 0.26->0.17 |  | 1,6174653822 | 814 |
| EXP_119 | run_partial_valid | rejected | EXP_116 | TOP_SIMILAR_SPY_WEEKS: 24.0->16 | 8,45597799414 | 1,35095029395 | 943,5026 |
| EXP_120 | run_partial_valid | rejected | EXP_116 | MAX_AVG_PROFILE_DISTANCE: 0.26->0.17 |  | 1,6174653822 | 814 |
| EXP_121 | run_partial_valid | rejected | EXP_116 | TOP_SIMILAR_SPY_WEEKS: 24.0->16 | 8,45597799414 | 1,35095029395 | 943,5026 |
| EXP_122 | run_partial_valid | rejected | EXP_116 | MAX_AVG_PROFILE_DISTANCE: 0.26->0.17 |  | 1,6174653822 | 814 |
| EXP_123 | run_partial_valid | rejected | EXP_116 | TOP_SIMILAR_SPY_WEEKS: 24.0->16 | 8,45597799414 | 1,35095029395 | 943,5026 |

## Diagnostico
- Se observa alta friccion de proceso por bloqueos y rechazos repetidos en subespacios similares.
- Desde EXP_116 en adelante predominan pruebas sobre TOP_SIMILAR_SPY_WEEKS y MAX_AVG_PROFILE_DISTANCE sin mejora robusta vs parent util.
- Hay evidencia util historica (corridas aceptadas y baseline promovido), pero el bloque reciente esta mas cerca de estancamiento que de mejora acumulativa.
- Conviene priorizar cambios ortogonales guiados por diagnostico de calidad de basket/candidato en lugar de repetir el mismo par de parametros.
