# Supervisor Hard Guard Fix

- updated_at: `2026-04-25T21:00:37`
- status: `implemented`
- scope: `loop supervisor hard guard + state consistency`

## What Changed

- `scripts/loop/run_infinite_research_loop.py` now treats explicit `--windows` as the source of truth.
- Config-side `156` no longer leaks into the effective loop windows when `--windows` is passed.
- The supervisor now aborts before any run if `parent_valid=false`.
- The supervisor now aborts before any run if `effective_windows` contains `156`.
- `reports/autonomous_loop_live_summary.md` was moved out of `running` after the prior `FAIL`.
- `validators/validate_loop_supervisor_state.py` was added to catch the bad state combinations.

## Guards Added

- `parent_valid=false` => hard stop before execution.
- `156` in effective windows => hard stop before execution.
- `selected_parent_run_id` with invalid parent => validator failure.
- `live_summary running` while `final_summary FAIL` => validator failure.

## Operational Outcome

- No backtests were run for this fix.
- `state/current_baseline.json` was not modified.
- Historical runs were not deleted.
