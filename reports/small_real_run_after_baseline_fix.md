# Small Real Run After Baseline Immutability Fix

Date: 2026-04-24

## 1. Executive Summary

Status: **PASS**

- Run dir: `runs/multi_agent_runs/EXP_136_260424173358/`
- Windows executed: `4, 8` only
- Forbidden windows executed (24/52/156): **no**
- Baseline changed: **no** (SHA256 unchanged)
- Research state changed: **yes** (expected)
- Experiment log added one row: **yes** (135 -> 136)
- Coordinator output contract valid: **yes**

Ready for controlled 4,8,24:
- **Yes**, from an operational perspective (paths + strict windows + baseline immutability).
- Still recommended to keep 24 explicitly authorized (do not run 52/156 yet).

## 2. Baseline Hash

- baseline_hash_before (SHA256): `EC47AB3890D5DCDAF3ECB00DE835B56D56A4BF007AB6C7965A090482628CCD9A`
- baseline_hash_after  (SHA256): `EC47AB3890D5DCDAF3ECB00DE835B56D56A4BF007AB6C7965A090482628CCD9A`

## 3. Command Executed

```powershell
python run_multi_agent_iteration.py --repo . --baseline-json state/current_baseline.json --experiment-log trackers/experiment_log.csv --dependencies-json config/parameter_dependencies.json --evaluation-windows 4,8
```

## 4. Artifacts / Files Generated

| file | exists | comment |
|---|---:|---|
| `executor_output.json` | yes | generated |
| `coordinator_output.json` | yes | generated |
| `experiment_manifest.json` | yes | generated |
| `run_live_status.log` | yes | generated |
| `window_execution_plan.json` | yes | generated |
| `window_04/` | yes | generated |
| `window_08/` | yes | generated |
| `window_24/` | no | correctly absent |
| `window_52/` | no | correctly absent |
| `window_156/` | no | correctly absent |

## 5. Executor Result

- `executor_output.status`: `run_ok`
- Windows present in executor output: `['4', '8']`
- `window_execution_plan.json`:
  - requested_windows: `[4, 8]`
  - allowed_windows: `[4, 8]`
  - progressive_windows_enabled: `false`
  - executed_windows: `[4, 8]`
  - forbidden_windows: `[24, 52, 156]`

## 6. Coordinator Result

From `coordinator_output.json`:
- status: `run_ok`
- gate_decision: `continue`
- decision_type: `rejected`
- accepted_for_followup: `false`
- promoted_to_baseline: `false`
- recommended_next_action: `controlled_exploration`
- recommended_change_directions: `['reactivate_disabled_gate']`

## 7. Validations

| command | result |
|---|---|
| `python validators/validate_window_constraints.py --run-dir runs/multi_agent_runs/EXP_136_260424173358 --allowed-windows 4,8` | OK |
| `python validators/validate_coordinator_output.py --path runs/multi_agent_runs/EXP_136_260424173358/coordinator_output.json` | OK |
| `python validators/validate_baseline_immutability.py --baseline state/current_baseline.json --expected-hash EC47AB3890D5DCDAF3ECB00DE835B56D56A4BF007AB6C7965A090482628CCD9A` | OK |

## 8. State / Tracker Changes

- `state/current_baseline.json` changed: **no**
- `state/research_state.json` changed: **yes** (expected; updated_at and branch_state may update)
- `trackers/experiment_log.csv` row count: **+1** (135 -> 136)

## 9. Verdict

**listo_para_4_8_24_controlado**

Constraints to keep:
- Do not run 52/156 without explicit authorization.
- Do not apply baseline promotion without explicit `--apply-baseline-promotion`.

