# How To Run Small Real Validation (4,8 Only)

Goal: run an operational validation with minimal windows (`4,8`) after restructure, without triggering longer windows (`24/52/156`).

## Key Semantics

### Strict windows (default)
If you pass `--evaluation-windows`, those are treated as the **only allowed windows**.

Example:
```powershell
python run_multi_agent_iteration.py --repo . --baseline-json state/current_baseline.json --experiment-log trackers/experiment_log.csv --dependencies-json config/parameter_dependencies.json --evaluation-windows 4,8
```

This will only execute windows `4` and `8`. Any attempt to run `24/52/156` is blocked with:
- status: `blocked_window_not_allowed`
- log line in `run_live_status.log`: `blocked_window_not_allowed ...`

### Progressive windows (explicit)
Progressive extension beyond requested windows is only allowed with:
```powershell
--allow-progressive-windows
```

## How To Validate A Run Respected Windows

After a run, validate the run directory:
```powershell
python validators/validate_window_constraints.py --run-dir runs/multi_agent_runs/EXP_XXX_... --allowed-windows 4,8
```

It will fail if forbidden folders exist (e.g., `window_24/`, `window_52/`, `window_156/`) or if `window_execution_plan.json` records executed windows outside the allowed set.

## Audit Artifact

Each run writes `window_execution_plan.json` into the run directory, containing:
- requested_windows
- allowed_windows
- progressive_windows_enabled
- executed_windows
- blocked_windows
- forbidden_windows

