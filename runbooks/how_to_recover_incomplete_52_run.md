# How To Recover An Incomplete 52w Run

Objective: recover missing final artifacts (`executor_output.json`, `coordinator_output.json`, `experiment_manifest.json`) when long 52w runs complete window work but the orchestrator terminates before final persistence (e.g., external timeout).

## 1) Detect an Incomplete Run

Run the required-artifacts validator:
```powershell
python validators/validate_required_run_artifacts.py --run-dir runs/multi_agent_runs/EXP_XXX_...
```

Outcomes:
- `OK`: run has all required artifacts.
- `RECOVERABLE_PARTIAL_RUN`: partial checkpoint exists (`executor_output.partial.json`), final artifacts missing.
- `FAIL_MISSING_REQUIRED_OUTPUTS`: missing required artifacts and no partial checkpoint.
- `FAIL_UNRECOVERABLE`: missing plan/log or window folder constraints broken.

## 2) Finalize / Recover

Run recovery finalizer:
```powershell
python scripts/recovery/finalize_incomplete_run.py --run-dir runs/multi_agent_runs/EXP_XXX_...
```

What it does:
- Reads `window_execution_plan.json`
- Reads `executor_output.partial.json` (if present)
- Reads `window_*/window_result.json` (if present)
- Uses `run_live_status.log` as a fallback
- Attempts to reconstruct a minimal `executor_output.json` and `experiment_manifest.json`
- Writes `recovery_report.json`

What it does NOT do (by default):
- Does NOT modify `state/current_baseline.json`
- Does NOT append to `trackers/experiment_log.csv`
- Does NOT attempt to regenerate coordinator output (marks `coordinator_pending=true` instead)

## 3) When NOT to Append Experiment Log

Do not append the experiment log automatically if:
- you cannot confirm the coordinator output and decision outcome
- you are missing metrics that are normally recorded in the tracker

Prefer manual review for such cases.

## 4) Human Review Triggers

Ask for human review if:
- `coordinator_output.json` is missing after recovery (expected today)
- recovered executor output is partial or missing key windows
- there is any sign `state/current_baseline.json` changed unexpectedly

