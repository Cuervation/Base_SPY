# Candidate Generation Exhaustion Diagnostic

- at: `2026-05-01T01:08:06`
- reason: `candidate_generation_parent_reset`
- final: `False`
- parent_run_id: `EXP_1288`
- current_parent_run_id: `EXP_1288`
- consecutive_no_material_candidate: `10`
- last_run_id: `EXP_1290`
- last_cgf_id: `CGF_000030`

## Recommended actions
- No seguir lanzando EXP si no hay candidato material.
- Revisar fallback_candidate_pool_considered y cooldowns activos.
- Cambiar parent/familia/eje antes de reintentar.
- Si el parent actual sigue agotado, usar baseline clean como parent temporal de exploracion.

## Recent results
| run_id | cgf_id | status | parent | windows |
| --- | --- | --- | --- | --- |
| EXP_1285 |  | run_ok | EXP_1284 | 52,4,8,24 |
| EXP_1286 |  | run_ok | EXP_1285 | 52,4,8,24 |
| EXP_1287 |  | run_ok | EXP_1286 | 52,4,8,24 |
| EXP_1288 |  | run_ok | EXP_1287 | 52,4,8,24 |
| EXP_1289 |  | run_ok | EXP_1288 | 52,4,8,24 |
| EXP_1290 | CGF_000021 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000022 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000023 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000024 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000025 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000026 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000027 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000028 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000029 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000030 | blocked_no_material_candidate | EXP_1288 |  |
