# How To Handle Recoverable Partial Run

## Goal

Standardize what to do when a run ends without all final artifacts, so the process is auditable and we do not use incomplete runs as parent.

## Statuses (validator)

Use:

```powershell
python validators/validate_required_run_artifacts.py --run-dir runs/multi_agent_runs/EXP_XXX_...
```

Possible outcomes:

- `COMPLETE`
  - Required artifacts exist: `executor_output.json`, `coordinator_output.json`, `experiment_manifest.json`.
  - Run can be evaluated normally.

- `RECOVERABLE_PARTIAL_RUN`
  - `executor_output.partial.json` exists, but at least one final artifact is missing.
  - Run is recoverable for process continuity.
  - Default policy: do **not** use as parent until recovery is completed and reviewed.

- `INCOMPLETE_NO_PARENT`
  - Required final outputs are missing and the run cannot be treated as complete.
  - Must be marked `do_not_use_as_parent=true`.

## Recovery procedure (safe mode)

1. Validate run status:

```powershell
python validators/validate_required_run_artifacts.py --run-dir runs/multi_agent_runs/EXP_XXX_...
```

2. If status is `RECOVERABLE_PARTIAL_RUN`, finalize without side effects:

```powershell
python scripts/recovery/finalize_incomplete_run.py --run-dir runs/multi_agent_runs/EXP_XXX_...
```

3. Re-validate:

```powershell
python validators/validate_required_run_artifacts.py --run-dir runs/multi_agent_runs/EXP_XXX_...
```

## Parent safety rule

If a run is incomplete or recoverable:

- set `do_not_use_as_parent = true`
- set `safe_for_strategy_analysis = false`
- set `safe_for_process_analysis = true`

in `recovery_status.json`.

## Important safeguards

- Do not modify `state/current_baseline.json` during recovery.
- Do not append to `trackers/experiment_log.csv` unless explicitly authorized and reviewed.
- Do not auto-generate coordinator decisions from incomplete executor data.
- `coordinator_output.json` must only exist from normal coordinator flow (or explicit approved post-processing).
