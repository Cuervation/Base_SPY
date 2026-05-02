# Repo Restructure Report

Timestamp: 2026-04-24 09:32:59

Constraints honored: no trading logic changes, no backtests run, no baseline content edited, no experiment_log content edited, no files deleted, no script refactors.

## Folders Created
- spec
- agents
- state/queues
- config
- scripts/metrics
- scripts/reports
- runs
- trackers
- reports/iteration_reviews
- logs/launch
- logs/loop
- logs/watchdog
- cache/dataset
- cache/trades
- runtime
- governance
- contracts
- validators
- runbooks
- outputs

## Files/Dirs Moved
- 00_project_context.md -> spec/project_context.md
- 01_agent_analyst.md -> agents/analyst.md
- 02_agent_coder.md -> agents/coder.md
- 03_agent_executor.md -> agents/executor.md
- analyst_initial_tests_queue.json -> state/queues/analyst_initial_tests_queue.json
- current_baseline.json -> state/current_baseline.json
- parameter_effect_memory.json -> state/parameter_effect_memory.json
- parameter_dependencies.json -> config/parameter_dependencies.json
- agent_live_runs_master.xlsx -> trackers/agent_live_runs_master.xlsx
- agent_live_runs_master.csv -> trackers/agent_live_runs_master.csv
- all_runs_full_stats.csv -> trackers/all_runs_full_stats.csv
- experiment_log.csv -> trackers/experiment_log.csv
- informe_EXP_067_a_ultima.md -> reports/informe_EXP_067_a_ultima.md
- iteration_review_last_15.md -> reports/iteration_reviews/iteration_review_last_15.md
- multi_agent_loop_launch_err.log -> logs/launch/multi_agent_loop_launch_err.log
- multi_agent_loop_launch_out.log -> logs/launch/multi_agent_loop_launch_out.log
- multi_agent_loop_logs -> logs/loop/multi_agent_loop_logs
- multi_agent_watchdog_logs -> logs/watchdog/multi_agent_watchdog_logs
- multi_agent_runs -> runs/multi_agent_runs
- champion_runs.json -> runs/champion_runs/champion_runs.json
- _dataset_cache -> cache/dataset/_dataset_cache
- _trade_cache -> cache/trades/_trade_cache
- OpenIAAgents -> runtime/OpenIAAgents
- extract_backtest_metrics.py -> scripts/metrics/extract_backtest_metrics.py
- generate_run_analysis.py -> scripts/reports/generate_run_analysis.py

## Files/Dirs Not Moved
- CONFLICT_EXISTS: 04_agent_coordinator.md -> agents/coordinator.md
- MISSING: AGENTS (no extension) -> AGENTS.md

## Potential Broken Paths (Not Auto-Fixed)
- Potential break: code/docs referencing root current_baseline.json now needs state/current_baseline.json (not updated per rules).
- Potential break: code referencing root experiment_log.csv now needs trackers/experiment_log.csv (not updated per rules).
- Potential break: code referencing extract_backtest_metrics.py or generate_run_analysis.py at repo root now needs scripts/metrics or scripts/reports paths (not updated per rules).
- Potential break: code referencing multi_agent_runs, multi_agent_loop_logs, multi_agent_watchdog_logs at repo root now needs runs/ or logs/ paths (not updated per rules).
- Potential break: tooling expecting champion_runs.json at repo root now needs runs/champion_runs/champion_runs.json (not updated per rules).

## Recommendations / Next Steps
- Recommend adding __pycache__/ and *.pyc to .gitignore (requested: do not touch __pycache__).
- After restructure, do a dedicated pass to update script paths/imports and PowerShell runners to new locations (out of scope for this step).
- Consider temporary compatibility wrappers if older paths must keep working (out of scope per rules).
