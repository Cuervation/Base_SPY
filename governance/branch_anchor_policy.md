# Branch Anchor Policy

Source of truth: `agents/coordinator.md`

## Objective
Reduce whipsaw by temporarily freezing a dominant parameter when evidence is strong.

## Activation Triggers (any)
- `promoted_to_baseline`, or
- `accepted_for_followup` with clear 52w improvement vs parent, or
- repeated useful direction/value recently.

## Effect
- Anchor a single parameter for `anchor_hold_iterations` (default 3).
- Block immediate reversals/nearby backtracks unless explicit `evidence_based_rollback`.

## Persistence Rule
- The persisted anchor in `current_baseline.json` / `research_state.json` is authoritative.
