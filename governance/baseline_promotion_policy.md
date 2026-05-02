# Baseline Promotion Policy

Source of truth: `agents/coordinator.md`

## Goal
Promote to baseline only when improvement is robust and not short-term noise.

## Required Separation
- `accepted_for_followup` and `promoted_to_baseline` are distinct outcomes.
- A run can be valuable for research without being baseline.

## Promotion Requirements (must all hold)
- Robust improvement vs parent (not only 4/8-week shine).
- Consistent compare vs SPY (prefer 24/52 robustness; multi-year only if real depth exists).
- No clear degradation of edge / basket quality.
- Enough validation depth for the current validation phase:
  - In `year1`: prioritize 52w vs SPY robustness.
  - In `multi_year`: require real 156w depth if promotion depends on it.

## Promotion Blockers (examples)
- Any multi-year requirement fails due to missing/insufficient real depth.
- Yearly vs SPY breakdown has non-positive years when policy forbids them.
- Clear deterioration vs parent on core 52w metrics.

## Coordinator Output Contract
- If promoted:
  - `decision_type = promoted_to_baseline`
  - `promoted_to_baseline = true`
  - `accepted_for_followup = false`
- If not promoted but still valuable:
  - `decision_type = accepted_for_followup`
  - `promoted_to_baseline = false`
