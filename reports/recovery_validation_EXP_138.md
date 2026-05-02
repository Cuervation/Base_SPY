# Recovery Validation EXP_138

Run dir: `runs/multi_agent_runs/EXP_138_260424193914`

## Summary

- Validation (required artifacts): **FAIL_MISSING_REQUIRED_OUTPUTS(needs_coordinator)** (missing `coordinator_output.json`).
- Recovery attempt: **executed** `scripts/recovery/finalize_incomplete_run.py` (default mode; **did not** append `experiment_log`, **did not** touch baseline).
- Recovery result: **partial success**
  - Reconstructed: `executor_output.json`, `experiment_manifest.json`
  - Generated/updated recovery metadata: `recovery_report.json` (and existing `recovery_status.json` kept)
  - Coordinator: **not recovered** (`coordinator_pending=true`)
- Parent safety: **still must NOT be used as parent**
  - `recovery_status.json` marks `do_not_use_as_parent: true` (process-evidence only).

## Commands Executed

```powershell
python validators\validate_required_run_artifacts.py --run-dir runs\multi_agent_runs\EXP_138_260424193914
python scripts\recovery\finalize_incomplete_run.py --run-dir runs\multi_agent_runs\EXP_138_260424193914
python validators\validate_required_run_artifacts.py --run-dir runs\multi_agent_runs\EXP_138_260424193914
```

## Artifacts Status (Post-Recovery)

- Present:
  - `window_execution_plan.json`
  - `run_live_status.log`
  - `executor_output.json` (reconstructed)
  - `experiment_manifest.json` (reconstructed)
  - `executor_output.partial.json`: not present in this historical run (expected for older runs)
  - `recovery_report.json`
  - `recovery_status.json`
- Missing (still blocking “complete run”):
  - `coordinator_output.json`

## Coordinator Execution

- Could the coordinator be executed during recovery: **No** (recovery script is intentionally conservative and does not regenerate coordinator output from partial signals).
- Current state: `coordinator_pending=true` (run is **recoverable for process evidence**, not for automated research progression).

## Experiment Manifest

- Generated during recovery: **Yes** (`experiment_manifest.json` created/updated based on available run-dir evidence).

## Baseline / Experiment Log Safety

- `state/current_baseline.json`: **not modified** (recovery script does not write baseline).
- `trackers/experiment_log.csv`: **not modified** (no `--append-experiment-log` flag used).

## Usability as Parent

- Still **not safe to use as parent** because:
  - `coordinator_output.json` missing
  - governance requires coordinator validation to drive branch decisions safely
  - `recovery_status.json` explicitly blocks parent use

## Next Steps

1. Keep EXP_138_260424193914 as **process evidence only** (as already decided).
2. If needed for audit completeness, consider a future safe “coordinator-only finalize” mode that:
   - reads existing `executor_output.json` and artifacts
   - generates `coordinator_output.json`
   - does **not** run backtests and does **not** touch baseline
   (not implemented here).
3. For future long runs, rely on checkpointing (`executor_output.partial.json` + `run_status.json`) to prevent missing artifacts on external timeouts.

