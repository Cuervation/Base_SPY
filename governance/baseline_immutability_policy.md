# Baseline Immutability Policy

Source of truth: `AGENTS.md` and `agents/coordinator.md`

## Objective
Keep the official baseline (`state/current_baseline.json`) immutable during normal research runs.

## Rules (critical)
- `state/current_baseline.json` is the single source of truth for the official baseline.
- It MUST NOT be modified during normal runs:
  - do not update `updated_at`
  - do not write `branch_anchor`
  - do not write `state_tracking`
- Normal runs MAY update:
  - `state/research_state.json`
  - `trackers/experiment_log.csv`
  - run artifacts such as `experiment_manifest.json`, `executor_output.json`, `coordinator_output.json`

## Promotion Is Explicit
- `promoted_to_baseline = true` is a **recommendation/decision**, not an automatic file write.
- Applying promotion requires an explicit operator action (CLI flag), e.g.:
  - `--apply-baseline-promotion`

## Pending Promotion
If a run recommends baseline promotion but promotion is not explicitly applied:
- record it as **pending**, do not modify the baseline file.
- store a run artifact such as `pending_baseline_promotion.json` in the run directory.

