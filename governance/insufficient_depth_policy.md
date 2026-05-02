# Insufficient Depth Policy

Source of truth: `agents/coordinator.md`

## Window Policy
- Windows: `[4, 8, 24, 52, 156]` (progressive real windows).

## Definition
`insufficient_depth` means the requested window could not be evaluated with real depth (e.g., 156w not available).

## Non-fatal Rule (critical)
- `insufficient_depth` must NOT be treated as a fatal technical error by default.
- Preserve usable evidence from shorter valid windows (especially 24/52).

## Coordinator Rules
- If 4/8/24/52 are valid and 156 is `insufficient_depth`:
  - allow `accepted_for_followup = true`
  - require `promoted_to_baseline = false` (do not promote when promotion depends on real multi-year depth)
  - forbid baseline promotion if real multi-year depth is required
  - recommend `extend_validation` when 52w signal is strong
