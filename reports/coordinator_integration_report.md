# Coordinator Integration Report

Date: 2026-04-24

Objective: integrate the coordinator role document into the new repo structure, and extract auditable governance policies + contracts + validators, without changing trading logic, running backtests, modifying baselines, or touching experiment logs.

## Files Moved
- `04_agent_coordinator.md` -> `agents/coordinator.md` (canonical doc)

Compatibility:
- `04_agent_coordinator.md` is kept as a stub pointing to `agents/coordinator.md` to avoid breaking references.

## Files Created
Governance policies (extracted from `agents/coordinator.md`):
- `governance/baseline_promotion_policy.md`
- `governance/followup_acceptance_policy.md`
- `governance/duplicate_zigzag_policy.md`
- `governance/insufficient_depth_policy.md`
- `governance/branch_anchor_policy.md`
- `governance/research_mode_policy.md`

State (new structured state location; legacy remains in repo root):
- `state/research_state.json`

Contracts:
- `contracts/coordinator_output.schema.json`

Validators:
- `validators/validate_coordinator_output.py`
- `validators/validate_duplicate_zigzag_policy.py`
- `validators/validate_promotion_rules.py`
- `validators/validate_insufficient_depth.py`
- `validators/validate_research_state.py`

## Rules Extracted (Summary)
Baseline promotion:
- Separate `accepted_for_followup` vs `promoted_to_baseline`.
- Promote only on robust improvement (24/52 robustness, multi-year only if real depth exists).

Follow-up acceptance:
- Accept runs that provide useful evidence even if not baseline.
- `insufficient_depth` is non-fatal; preserve shorter-window evidence.

Duplicate vs zig-zag:
- Exact repetition is `duplicate_recent_proposal` (not zig-zag).
- Only `true_zigzag_reversal` auto-blocks as zig-zag.
- `monotonic_refinement` is allowed.

Insufficient depth:
- Missing 156w real depth is not a fatal error by default.
- If 4/8/24/52 are valid and 156 is insufficient: allow follow-up, and do not baseline-promote when promotion depends on multi-year depth.

Branch anchor:
- Anchor a dominant parameter for ~3 iterations after strong evidence (promotion/follow-up with strong 52w vs parent, or repeated useful direction).
- Persisted anchor state is authoritative.

Research mode:
- Persist `current_mode` and change reasons.
- `current_mode` must influence candidate selection.
- If process friction dominates, prefer `fix_process_before_more_research`.

## Validators Created (How To Run)
From repo root:

```powershell
python validators\validate_research_state.py
python validators\validate_duplicate_zigzag_policy.py
python validators\validate_promotion_rules.py
python validators\validate_insufficient_depth.py
```

Coordinator output contract validation (point to any `coordinator_output.json`):

```powershell
python validators\validate_coordinator_output.py --path .\multi_agent_runs\EXP_XXX_...\coordinator_output.json
```

## Next Steps
1. Wire these validators into the iteration loop preflight/postflight (as non-blocking warnings at first).
2. Ensure the runtime code that writes coordinator output stays aligned with `contracts/coordinator_output.schema.json`.
3. Decide whether `state/research_state.json` becomes the single source of truth, or remains a derived/normalized mirror of `research_state.json`.

