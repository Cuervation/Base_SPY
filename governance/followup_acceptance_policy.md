# Follow-up Acceptance Policy

Source of truth: `agents/coordinator.md`

## Goal
Accept runs for follow-up when they provide useful evidence, even if they do not qualify for baseline.

## Acceptance Criteria (typical)
- Material change exists (not a no-op).
- Evidence is usable (at least short/medium windows are valid as per window policy).
- The run adds learning value (supports, refutes, or clarifies a hypothesis).

## Non-fatal Long Window Rule
- Missing/insufficient 156w depth must not be treated as a fatal error by default.
- If 4/8/24/52 are valid but 156 is `insufficient_depth`:
  - `accepted_for_followup = true` is allowed/expected when 52w signal is useful.
  - `promoted_to_baseline = false`
  - `recommended_next_action` often becomes `extend_validation`.

## Coordinator Output Contract
- If accepted for follow-up:
  - `decision_type = accepted_for_followup`
  - `accepted_for_followup = true`
  - `promoted_to_baseline = false`
