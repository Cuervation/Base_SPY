# Smoke Test After Restructure

Date: 2026-04-24

Objective: minimal smoke test post-restructure to confirm runners can resolve paths/state/config/contracts/scripts without breaking, while avoiding real backtests and avoiding consuming a real iteration (prefer dry-run).

## 1. Preconditions (Critical Paths)

Confirmed present:
- `config/paths_config.json`
- `state/current_baseline.json`
- `state/research_state.json`
- `trackers/experiment_log.csv`
- `scripts/metrics/extract_backtest_metrics.py`
- `scripts/reports/generate_run_analysis.py`
- `runs/multi_agent_runs/`
- `logs/loop/multi_agent_loop_logs/`
- `logs/watchdog/multi_agent_watchdog_logs/`

## 2. Validators Executed (Lightweight Only)

| command | result | notes |
|---|---|---|
| `python validators/validate_research_state.py` | OK | `state/research_state.json` structure present |
| `python validators/validate_insufficient_depth.py` | OK | policy content only (no backtest needed) |
| `python validators/validate_promotion_rules.py` | OK | policy content only (no backtest needed) |
| `python validators/validate_coordinator_output.py --path runs/multi_agent_runs/EXP_134_260423194104/coordinator_output.json` | OK (basic) | schema used if available; includes manual `recommended_next_action` check |

Note:
- `validators/validate_coordinator_output.py` does not provide `--self-test`; it requires `--path`.

## 3. Dry-Run Execution

Dry-run exists and was executed:

Command:
```powershell
python run_multi_agent_iteration.py --repo . --baseline-json state/current_baseline.json --experiment-log trackers/experiment_log.csv --dependencies-json config/parameter_dependencies.json --evaluation-windows 4,8 --dry-run
```

Result:
- Completed successfully.
- Confirmed message: `DRY_RUN completado: analyst+coder+preflight OK, sin ejecutar backtests.`
- Created run directory: `runs/multi_agent_runs/EXP_135_260424115755/`

## 4. Baseline / Research State / Experiment Log Safety Check

To avoid unintended writes in test mode, SHA256 was checked before and after dry-run for:
- `state/current_baseline.json` (unchanged)
- `state/research_state.json` (unchanged)
- `trackers/experiment_log.csv` (unchanged)

Interpretation:
- Dry-run did not modify baseline, research_state, or experiment_log content.

## 5. Import/Path Errors

No import/path errors observed during:
- lightweight validators
- `run_multi_agent_iteration.py --dry-run`

## 6. Readiness For a Small Real Run

Status: **ready_for_small_real_run (with constraints)**

Rationale:
- Path resolution works with the reorganized structure.
- State/config/contracts/validators load without breaking.
- Dry-run demonstrates analyst/coder/preflight pipeline is healthy without executing backtests.

Constraints for any next real run:
- Keep windows minimal (e.g., `4,8`) and avoid long validation (24/52/156) unless explicitly requested.
- Confirm desired behavior regarding creating run artifacts in `runs/multi_agent_runs/`.

