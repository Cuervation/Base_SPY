# Research Mode Policy

Source of truth: `agents/coordinator.md`

## Modes (persisted)
- `refine_current_branch`
- `controlled_exploration`
- `extend_validation`
- `fix_process_before_more_research`
- `champion_hold`
- `safe_recovery_mode`

## Persisted Fields (branch_state)
- `current_mode`
- `mode_reason`
- `last_mode_change_at`
- `last_mode_change_run_id`
- `previous_mode`
- `mode_stability_counter`

## Operational Rule (critical)
- `current_mode` must influence candidate selection; avoid proposing the same type of change in all modes.

## Process-first Rule
- If the dominant friction is process/state handling/duplicate throttling, prioritize:
  - `fix_process_before_more_research`
