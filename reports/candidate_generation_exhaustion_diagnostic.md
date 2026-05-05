# Candidate Generation Exhaustion Diagnostic

- at: `2026-05-03T13:25:38`
- reason: `candidate_generation_forced_orthogonal_after_no_material_streak`
- final: `False`
- parent_run_id: `EXP_1422`
- current_parent_run_id: `EXP_1422`
- consecutive_no_material_candidate: `5`
- last_run_id: `EXP_1538`
- last_cgf_id: `CGF_000035`

## Recommended actions
- No seguir lanzando EXP si no hay candidato material.
- Revisar fallback_candidate_pool_considered y cooldowns activos.
- Cambiar parent/familia/eje antes de reintentar.
- Si el parent actual sigue agotado, usar baseline clean como parent temporal de exploracion.

## Recent results
| run_id | cgf_id | status | parent | windows |
| --- | --- | --- | --- | --- |
| EXP_1537 |  | run_ok | EXP_1422 | 52,4,8,24 |
| EXP_1538 | CGF_000031 | blocked_no_material_candidate | EXP_1422 |  |
| EXP_1538 | CGF_000032 | blocked_no_material_candidate | EXP_1422 |  |
| EXP_1538 | CGF_000033 | blocked_no_material_candidate | EXP_1422 |  |
| EXP_1538 | CGF_000034 | blocked_no_material_candidate | EXP_1422 |  |
| EXP_1538 | CGF_000035 | blocked_no_material_candidate | EXP_1422 |  |
