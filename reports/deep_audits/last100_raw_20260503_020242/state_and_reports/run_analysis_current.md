# Run Analysis (Current Snapshot)

- Generated at: **2026-05-03 01:43:06**

## 1. General State
- Total runs logged: **1552**
- Validation phase: **multi_year**
- Last useful run: **EXP_229**
- Last followup run: **EXP_185**
- Last promoted baseline: **EXP_229**
- Branch health: **stagnating**
- Main friction: **candidate_generation**
- Recommended next action: **controlled_exploration**
- Current mode: **safe_recovery_mode**
- Mode reason: **watchdog_high_restart_volume_24h**
- Previous mode: **controlled_exploration**
- Mode stability counter: **4**
- Last mode change: **2026-05-02T19:53:08** (run_id=EXP_1386)
- Baseline updated_at: **2026-04-27T22:26:42**
- Research updated_at: **2026-05-03T01:43:02**
- Watchdog health class: **-**
- Watchdog last restart reason: **-**
- Watchdog restart count (24h): **0**
- Watchdog hard_stuck_detected: **0**
- Watchdog safe_mode_active: **0**
- Last successful iteration at: **-**
- Recent no-useful streak (max 10): **10**
- Branch anchor (persisted): baseline=``/None (active=0, rem=0) ; research=``/None (active=0, rem=0) ; sync_ok=1

## 2. Champions / Memory
- Champion best_w52_spy_compare: **EXP_1378**
- Champion balance_quality_frequency: **EXP_1422**
- Champion multi_year_real: **EXP_144**
- Champion orthogonal_exploration: **-**
- Champion recent_followup: **EXP_1422**
- Parameter effect transitions tracked: **61**
- Effect classes: strong_positive=3, mild_positive=5, neutral=20, unstable=3, exhausted=10, harmful=16
- Active cooldowns: **3** / total cooldown entries: **10**
- Acceptance trend: last15=**0.0%**, previous15=**0.0%**
- Learning trend avg w52_spy: last15=**-**, previous15=**-**

### Active champions
- `best_w52_spy_compare_run_id`: **EXP_1378** | reusable_parent=1 | MAX_CLOSE_VS_SMA50_PCT: 0.6 -> 0.3 | max_w52_spy_compare
- `best_balance_quality_frequency_run_id`: **EXP_1422** | reusable_parent=1 | MIN_SPY_CHANNEL_R2: 0.5 -> 0.6 | best_balance_quality_frequency_score
- `best_multi_year_real_run_id`: **EXP_144** | reusable_parent=1 | - | best_multi_year_real_depth_ok
- `best_recent_followup_run_id`: **EXP_1422** | reusable_parent=1 | MIN_SPY_CHANNEL_R2: 0.5 -> 0.6 | latest_followup_or_champion_candidate
- `best_orthogonal_exploration_run_id`: **-** | reusable_parent=0 | - | -

### Top positive parameter impacts
- `MAX_CLOSE_VS_SMA50_PCT: 0.6 -> 0.3` class=strong_positive attempts=1 accepted=1 rejected=0 avg_delta_w52_spy=2.350 best=EXP_1378
- `TOP_CANDIDATES_NEXT_WEEK: 4 -> 2` class=strong_positive attempts=1 accepted=1 rejected=0 avg_delta_w52_spy=1.040 best=EXP_1280
- `MIN_SPY_CHANNEL_R2: 0.5 -> 0.6` class=strong_positive attempts=7 accepted=6 rejected=1 avg_delta_w52_spy=0.697 best=EXP_1422
- `MAX_AVG_PROFILE_DISTANCE: 0.22 -> 0.17` class=mild_positive attempts=2 accepted=2 rejected=0 avg_delta_w52_spy=0.456 best=EXP_168
- `TOP_CANDIDATES_NEXT_WEEK: 3 -> 2` class=mild_positive attempts=5 accepted=5 rejected=0 avg_delta_w52_spy=0.396 best=EXP_333
- `MAX_AVG_PROFILE_DISTANCE: 0.2 -> 0.18` class=mild_positive attempts=2 accepted=2 rejected=0 avg_delta_w52_spy=0.315 best=EXP_1285
- `MAX_CLOSE_VS_SMA50_PCT: 0.75 -> 0.9` class=mild_positive attempts=1 accepted=1 rejected=0 avg_delta_w52_spy=0.312 best=EXP_1293
- `MAX_AVG_PROFILE_DISTANCE: 0.2 -> 0.17` class=mild_positive attempts=4 accepted=2 rejected=2 avg_delta_w52_spy=0.291 best=EXP_158

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
- `blocked_no_material_candidate`: **1245**
- `run_ok`: **186**
- `run_partial_valid`: **99**
- `blocked_duplicate`: **13**
- `run_error`: **6**
- `blocked_preflight`: **3**

## 4. Acceptance
- `accepted`: **107**
- `rejected`: **1445**
- Acceptance rate (last 15): **0.0%**

## 5. 52w Performance
- Best `w52_spy_compare`: **4.880** (EXP_1378)
- Best `w52_pnl`: **1827.7** (EXP_061)
- Worst `w52_spy_compare`: **-0.051** (EXP_044)
- Avg `w52_spy_compare` (last 15 valid): **-**

## 6. Last 15 Runs

| run_id | status | accepted/rejected | main change | w52_trades | w52_pnl | w52_spy_compare |
|---|---|---|---|---:|---:|---:|
| EXP_1522 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1523 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1524 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1525 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1526 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1527 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1528 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1529 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1530 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1531 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1532 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1533 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1534 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1535 | blocked_no_material_candidate | rejected | - | - | - | - |
| EXP_1536 | blocked_no_material_candidate | rejected | - | - | - | - |

## 7. Subespacios agotados recientes (last 15)
- No se detectaron subespacios agotados con criterio actual.

## 8. Rechazos fuertes (w52_spy_compare alto)
- No hay rechazos recientes con w52_spy_compare alto.

## 9. Corridas fuertes no convertidas a baseline
- No se detectaron corridas fuertes pendientes de conversion en el rango analizado.
