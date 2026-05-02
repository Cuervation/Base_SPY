# Controlled Run 4,8,24 After Baseline Fix

Date: 2026-04-24

## 1. Executive Summary

Status: **PASS**

- RUN_ID: `EXP_137`
- Run dir: `runs/multi_agent_runs/EXP_137_260424182050/`
- Windows executed: `4, 8, 24`
- Forbidden windows executed (52/156): **no**
- Baseline modified: **no** (SHA256 unchanged)
- Experiment log updated: **yes** (+1 row)
- Coordinator contract valid: **yes**

## 2. Command Executed

```powershell
python run_multi_agent_iteration.py --repo . --baseline-json state/current_baseline.json --experiment-log trackers/experiment_log.csv --dependencies-json config/parameter_dependencies.json --evaluation-windows 4,8,24
```

## 3. Artifacts Generated

Run dir: `runs/multi_agent_runs/EXP_137_260424182050/`

- `executor_output.json`: present
- `coordinator_output.json`: present
- `experiment_manifest.json`: present
- `window_execution_plan.json`: present
- `window_04/`, `window_08/`, `window_24/`: present
- `window_52/`, `window_156/`: absent

## 4. Executor Result

- status: `run_ok`
- windows present in executor output: `4`, `8`, `24`
- insufficient_depth: not applicable (52/156 not executed)
- errors: none observed in run outputs

## 5. Coordinator Result

- status: `run_ok`
- gate_decision: `continue`
- decision_type: `rejected`
- accepted_for_followup: `false`
- promoted_to_baseline: `false`
- recommended_next_action: `controlled_exploration`
- recommended_change_directions: `['reactivate_disabled_gate']`

## 6. Validations

| validation | command | result |
|---|---|---|
| window constraints | `python validators/validate_window_constraints.py --run-dir runs/multi_agent_runs/EXP_137_260424182050 --allowed-windows 4,8,24` | OK |
| coordinator output | `python validators/validate_coordinator_output.py --path runs/multi_agent_runs/EXP_137_260424182050/coordinator_output.json` | OK |
| baseline immutability | `python validators/validate_baseline_immutability.py --baseline state/current_baseline.json --expected-hash EC47AB3890D5DCDAF3ECB00DE835B56D56A4BF007AB6C7965A090482628CCD9A` | OK |

## 7. State / Tracker Changes

- `state/current_baseline.json` changed: **no** (hash unchanged)
- `state/research_state.json` changed: **yes** (expected; updated_at/state tracking)
- `trackers/experiment_log.csv` rows added: **1** (136 -> 137)

## 8. Riesgos detectados

Criticos:
- none observed for this controlled run.

Medios:
- Coordinator continues to reject due to missing 24/52 robustness; this is expected given the run constraints (no 52).

Menores:
- none observed.

## 9. Veredicto

**listo_para_4_8_24_52_controlado**

Note:
- Keep 52 explicitly authorized (still avoid 156 unless explicitly requested).
- Do not apply baseline promotion without `--apply-baseline-promotion`.

