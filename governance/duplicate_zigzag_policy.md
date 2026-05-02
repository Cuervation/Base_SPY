# Duplicate vs Zig-zag Policy

Source of truth: `agents/coordinator.md`

## Objective
Block true administrative waste (no-op, exact duplicates, true zig-zags) without blocking valid refinement.

## Transition Classes
- `no_op_equivalence`: no effective behavior change.
- `duplicate_recent_proposal`: exact repeat of a recent proposal (NOT a zig-zag).
- `fresh_change`: new change without recent conflict.
- `monotonic_refinement`: same economic direction (should not be blocked).
- `controlled_exploration`: new orthogonal axis (should not be blocked automatically).
- `evidence_based_rollback`: partial rollback backed by evidence (should not be blocked automatically).
- `true_zigzag_reversal`: unjustified back-and-forth (this is the only class auto-blocked).

## Critical Rule
- Never classify an exact repetition as `true_zigzag_reversal`.
  - Exact repetition is `duplicate_recent_proposal`.

## Blocking Rules
- Always block `no_op_equivalence`.
- Block `duplicate_recent_proposal` as duplicate (not as zig-zag).
- Auto-block only `true_zigzag_reversal`.
