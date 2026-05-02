# parameter-precheck

## Objective

Prevent wasted backtests by using historical memory before selecting a candidate.

## When to use

Before any analyst proposal is accepted for execution.

## Required inputs

- `trackers/experiment_log.csv`
- `state/parameter_effect_memory.json`
- recent `runs/multi_agent_runs/EXP_*` metadata when available

## Required checks

1. Exact duplicate: same parameter + from_value + to_value in last 50 runs.
2. No-op normalized changes.
3. Active cooldowns / exhausted subspaces.
4. Repeated negative parameter + direction.
5. Frequency increased while quality/edge fell.
6. Transition memory rejected with no accepted follow-up.

## Required result

Return one of:

- `allowed`
- `blocked`
- `allowed_explore`

`allowed_explore` is valid only for controlled exploration and never bypasses exact duplicate/no-op/cooldown blocks.
