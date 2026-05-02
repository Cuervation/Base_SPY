# Autonomous Batch Final Summary (4,8,24,52)

## Result

**FAIL**

## Batch Configuration (as executed)

- max_iterations: 3
- evaluation_windows: 4,8,24,52 (strict)
- forbidden_windows: 156
- baseline promotion: disabled (no `--apply-baseline-promotion`)
- baseline immutability enforced: yes (validated via SHA256)
- parent constraint: **EXP_138 not allowed as parent** (respected; current parent at start was `EXP_134`)

## Runs Executed

| run_id | run_dir | windows completed | window_156 executed | required artifacts | coordinator valid | baseline changed | notes |
|---|---|---:|---|---|---|---|---|
| EXP_142 | `runs/multi_agent_runs/EXP_142_260425014932` | 4,8,24 (52 not reached) | no | **RECOVERABLE_PARTIAL_RUN** (missing finals) | missing file | no | `executor_output.partial.json` present; finals missing |

## Stop Reason

- **stop_if_missing_required_outputs = true** triggered on `EXP_142`:
  - Missing: `executor_output.json`, `coordinator_output.json`, `experiment_manifest.json`
  - Present: `executor_output.partial.json`, `window_execution_plan.json`, `run_live_status.log`
  - Marked: `runs/multi_agent_runs/EXP_142_260425014932/recovery_status.json` with `do_not_use_as_parent: true`

## Baseline / Windows Safety

- Baseline SHA256 before: `EC47AB3890D5DCDAF3ECB00DE835B56D56A4BF007AB6C7965A090482628CCD9A`
- Baseline SHA256 after:  `EC47AB3890D5DCDAF3ECB00DE835B56D56A4BF007AB6C7965A090482628CCD9A`
- Baseline changed: **no**
- 156 executed: **no** (window constraints validator passed)

## Outputs Missing (Critical)

For `EXP_142_260425014932`:

- Missing required outputs:
  - `executor_output.json`
  - `coordinator_output.json`
  - `experiment_manifest.json`
- Partial checkpoint present:
  - `executor_output.partial.json` (executed_windows: `[4,8,24]`)

## Best / Worst Run

- Best run: **N/A** (no completed runs with full artifacts in this batch)
- Worst run: **EXP_142** (incomplete; missing final artifacts)

## accepted_for_followup / pending promotion

- accepted_for_followup: **none** (no coordinator output produced)
- pending_promotion_review: **none** (no coordinator output; baseline not modified; no promotion applied)

## Final Recommendation

**fix_process_before_more_research**

Reason: the batch failed on process reliability (missing final artifacts) before reaching a full 4/8/24/52 run; recoverability exists via partial checkpoint, but we need stable end-to-end artifact persistence before continuing autonomous 52w validation.

