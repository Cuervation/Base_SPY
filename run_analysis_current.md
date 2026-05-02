# Run Analysis (Current Snapshot)

- Generated at: **2026-05-02 10:23:21**

## 1. General State
- Total runs logged: **1306**
- Validation phase: **multi_year**
- Last useful run: **EXP_229**
- Last followup run: **EXP_185**
- Last promoted baseline: **EXP_229**
- Branch health: **stagnating**
- Main friction: **long_window_depth**
- Recommended next action: **controlled_exploration**
- Current mode: **controlled_exploration**
- Mode reason: **branch_reboot_from_exp127_due_to_stagnation**
- Previous mode: **controlled_exploration**
- Mode stability counter: **0**
- Last mode change: **2026-05-01T11:23:08** (run_id=EXP_127)
- Baseline updated_at: **2026-04-27T22:26:42**
- Research updated_at: **2026-05-01T11:23:08**
- Watchdog health class: **-**
- Watchdog last restart reason: **-**
- Watchdog restart count (24h): **0**
- Watchdog hard_stuck_detected: **0**
- Watchdog safe_mode_active: **0**
- Last successful iteration at: **-**
- Recent no-useful streak (max 10): **0**
- Branch anchor (persisted): baseline=``/None (active=0, rem=0) ; research=``/None (active=0, rem=0) ; sync_ok=1

## 2. Champions / Memory
- Champion best_w52_spy_compare: **EXP_162**
- Champion balance_quality_frequency: **EXP_392**
- Champion multi_year_real: **EXP_144**
- Champion orthogonal_exploration: **-**
- Champion recent_followup: **EXP_1290**
- Parameter effect transitions tracked: **54**
- Effect classes: strong_positive=2, mild_positive=5, neutral=18, unstable=2, exhausted=10, harmful=16
- Active cooldowns: **3** / total cooldown entries: **7**
- Acceptance trend: last15=**66.7%**, previous15=**0.0%**
- Learning trend avg w52_spy: last15=**2.204**, previous15=**-**

### Active champions
- `best_w52_spy_compare_run_id`: **EXP_162** | reusable_parent=1 | - | max_w52_spy_compare
- `best_balance_quality_frequency_run_id`: **EXP_392** | reusable_parent=1 | - | best_balance_quality_frequency_score
- `best_multi_year_real_run_id`: **EXP_144** | reusable_parent=1 | - | best_multi_year_real_depth_ok
- `best_recent_followup_run_id`: **EXP_1290** | reusable_parent=1 | - | latest_followup_or_champion_candidate
- `best_orthogonal_exploration_run_id`: **-** | reusable_parent=0 | - | -

### Top positive parameter impacts
- `TOP_CANDIDATES_NEXT_WEEK: 4 -> 2` class=strong_positive attempts=1 accepted=1 rejected=0 avg_delta_w52_spy=1.040 best=EXP_1280
- `MIN_SPY_CHANNEL_R2: 0.5 -> 0.6` class=strong_positive attempts=5 accepted=4 rejected=1 avg_delta_w52_spy=0.583 best=EXP_165
- `MAX_AVG_PROFILE_DISTANCE: 0.22 -> 0.17` class=mild_positive attempts=2 accepted=2 rejected=0 avg_delta_w52_spy=0.456 best=EXP_168
- `TOP_CANDIDATES_NEXT_WEEK: 3 -> 2` class=mild_positive attempts=5 accepted=5 rejected=0 avg_delta_w52_spy=0.396 best=EXP_333
- `MAX_AVG_PROFILE_DISTANCE: 0.2 -> 0.18` class=mild_positive attempts=2 accepted=2 rejected=0 avg_delta_w52_spy=0.315 best=EXP_1285
- `MAX_AVG_PROFILE_DISTANCE: 0.2 -> 0.17` class=mild_positive attempts=4 accepted=2 rejected=2 avg_delta_w52_spy=0.291 best=EXP_158
- `TOP_SIMILAR_SPY_WEEKS: 20 -> 28` class=mild_positive attempts=4 accepted=3 rejected=1 avg_delta_w52_spy=0.258 best=EXP_162

### Top negative / exhausted parameter impacts
- `ENABLE_VAR_ATR_14W_PCT: false -> true` class=harmful attempts=1 accepted=0 rejected=1 avg_delta_w52_spy=-3.602 best=EXP_235
- `TOP_CANDIDATES_NEXT_WEEK: 2 -> 5` class=exhausted attempts=9 accepted=0 rejected=9 avg_delta_w52_spy=-2.476 best=EXP_146
- `TOP_CANDIDATES_NEXT_WEEK: 2 -> 4` class=exhausted attempts=10 accepted=0 rejected=10 avg_delta_w52_spy=-2.002 best=EXP_145
- `TOP_CANDIDATES_NEXT_WEEK: 3 -> 5` class=exhausted attempts=4 accepted=0 rejected=4 avg_delta_w52_spy=-1.919 best=EXP_170
- `TOP_SIMILAR_SPY_WEEKS: 28 -> 16` class=exhausted attempts=13 accepted=0 rejected=13 avg_delta_w52_spy=-1.874 best=EXP_602
- `ENABLE_VAR_DIST_TO_HIGH_26W_PCT: false -> true` class=harmful attempts=1 accepted=0 rejected=1 avg_delta_w52_spy=-1.855 best=EXP_237
- `ENABLE_VAR_RET_4W_PCT: false -> true` class=harmful attempts=1 accepted=0 rejected=1 avg_delta_w52_spy=-1.522 best=EXP_230
- `ENABLE_VAR_VOLUME_RATIO_VS_SMA13W: false -> true` class=harmful attempts=1 accepted=0 rejected=1 avg_delta_w52_spy=-1.459 best=EXP_236

### Subspaces in cooldown
- `TOP_CANDIDATES_NEXT_WEEK: 2 -> 4` until=999999 reason=recent_exhausted_subspace override_only_if=evidence_based_retry_explicit | new_parent_champion | orthogonal_context_change
- `TOP_CANDIDATES_NEXT_WEEK: 2 -> 5` until=999999 reason=recent_exhausted_subspace override_only_if=evidence_based_retry_explicit | new_parent_champion | orthogonal_context_change
- `TOP_SIMILAR_SPY_WEEKS: 24 -> 16` until=999999 reason=recent_exhausted_subspace override_only_if=evidence_based_retry_explicit | new_parent_champion | orthogonal_context_change

## 3. Status Count
- `blocked_no_material_candidate`: **1020**
- `run_ok`: **165**
- `run_partial_valid`: **99**
- `blocked_duplicate`: **13**
- `run_error`: **6**
- `blocked_preflight`: **3**

## 4. Acceptance
- `accepted`: **98**
- `rejected`: **1208**
- Acceptance rate (last 15): **66.7%**

## 5. 52w Performance
- Best `w52_spy_compare`: **4.114** (EXP_112)
- Best `w52_pnl`: **1827.7** (EXP_061)
- Worst `w52_spy_compare`: **-0.051** (EXP_044)
- Avg `w52_spy_compare` (last 15 valid): **2.204**

## 6. Last 15 Runs

| run_id | status | accepted/rejected | main change | w52_trades | w52_pnl | w52_spy_compare |
|---|---|---|---|---:|---:|---:|
| EXP_1276 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1277 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1278 | run_ok | accepted | TOP_CANDIDATES_NEXT_WEEK: 5.0 -> 4 | 104 | 1146,9026 | 1,82191095604 |
| EXP_1279 | run_ok | rejected | TOP_SIMILAR_SPY_WEEKS: 20.0 -> 28 | 108 | 955,8 | 1,34764320753 |
| EXP_1280 | run_ok | accepted | TOP_CANDIDATES_NEXT_WEEK: 4.0 -> 2 | 54 | 875,4 | 2,86199667513 |
| EXP_1281 | run_ok | accepted | MAX_AVG_PROFILE_DISTANCE: 0.2 -> 0.17 | 50 | 905 | 3,18051911045 |
| EXP_1282 | run_ok | rejected | MIN_SPY_CHANNEL_R2: 0.55 -> 0.52 | 56 | 830,6 | 2,40654636696 |
| EXP_1283 | run_ok | accepted | TOP_CANDIDATES_NEXT_WEEK: 5.0 -> 3 | 81 | 1060,6 | 2,23853988501 |
| EXP_1284 | run_ok | accepted | MIN_SPY_CHANNEL_R2: 0.55 -> 0.5 | 90 | 1104 | 1,9548076914 |
| EXP_1285 | run_ok | accepted | MAX_AVG_PROFILE_DISTANCE: 0.2 -> 0.18 | 84 | 1188,4 | 2,26964160505 |
| EXP_1286 | run_ok | accepted | TOP_CANDIDATES_NEXT_WEEK: 3.0 -> 2 | 58 | 825,8 | 2,3418915645 |
| EXP_1287 | run_ok | accepted | MIN_SPY_CHANNEL_R2: 0.5 -> 0.47 | 60 | 876 | 2,38161436281 |
| EXP_1288 | run_ok | accepted | MAX_AVG_PROFILE_DISTANCE: 0.18 -> 0.17 | 58 | 880,8 | 2,44540944099 |
| EXP_1289 | run_ok | rejected | MIN_SPY_CHANNEL_R2: 0.47 -> 0.44 | 60 | 826 | 2,23458875436 |
| EXP_1290 | run_ok | accepted | MAX_AVG_PROFILE_DISTANCE: 0.2 -> 0.18 | 115 | 943,3653 | 1,16889905859 |

## 7. Subespacios agotados recientes (last 15)
- No se detectaron subespacios agotados con criterio actual.

## 8. Rechazos fuertes (w52_spy_compare alto)
| run_id | status | main change | w52_spy_compare | w52_pnl |
|---|---|---|---:|---:|
| EXP_1282 | run_ok | MIN_SPY_CHANNEL_R2: 0.55 -> 0.52 | 2,40654636696 | 830,6 |
| EXP_1289 | run_ok | MIN_SPY_CHANNEL_R2: 0.47 -> 0.44 | 2,23458875436 | 826 |

## 9. Corridas fuertes no convertidas a baseline
- Ultimo baseline promovido: **EXP_229**. Las siguientes corridas muestran senal 52w alta pero quedaron fuera de promocion:
- `EXP_1282`: w52_spy_compare=2,40654636696 status=run_ok accepted=rejected
- `EXP_1289`: w52_spy_compare=2,23458875436 status=run_ok accepted=rejected
