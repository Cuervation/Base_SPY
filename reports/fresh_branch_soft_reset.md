# Fresh Branch Soft Reset

- reset_at: `2026-04-25T19:56:08`
- branch_id: `fresh_baseline_branch_260425`
- loop_status: `stopped_for_soft_reset`
- stop_reason: `parent_state_inconsistency`
- next_parent_source: `current_baseline`
- baseline_file: `state/current_baseline.json`
- backtests_executed: `false`

## Motivo

Se hizo soft reset por inconsistencias de estado operativo:

- `current_parent_run_id` apuntaba a `EXP_156` mientras el parent estaba marcado como invalido en el resumen vivo.
- El snapshot acumulado mantenia referencias viejas/inconsistentes de ultima corrida util.
- Habia corridas duplicadas para `EXP_154`, `EXP_155` y `EXP_156` con distintos `run_dir`.
- El `branch_anchor` activo no estaba sincronizado.

## Cambios aplicados

- `state/research_state.json` ahora inicia la rama `fresh_baseline_branch_260425`.
- `current_mode` quedo en `controlled_exploration`.
- `mode_reason` quedo en `soft_reset_from_parent_state_inconsistency`.
- `parent_state.current_parent_run_id` quedo en `null`.
- `parent_state.last_useful_run_id` quedo en `null`.
- `parent_state.parent_source` quedo en `current_baseline`.
- `parent_state.use_baseline_as_parent` quedo en `true`.
- `branch_anchor` quedo desactivado con reason `reset_due_to_parent_state_inconsistency`.
- `state/autonomous_loop_state.json` quedo en `stopped_for_soft_reset`.
- Se agrego `next_parent_source = current_baseline`.
- Se agrego `forbidden_parent_runs = ["EXP_138", "EXP_142", "EXP_143", "EXP_145", "EXP_156"]`.
- Se desactivaron las tareas programadas `SPY_Agent_Recurrent_Loop` y `SPY_MultiAgent_Watchdog` para evitar reinicios automaticos durante el reset.

## Cambios de supervisor

- `scripts/loop/run_infinite_research_loop.py` ahora respeta `use_baseline_as_parent=true`.
- `run_multi_agent_iteration.py` ahora evita el fallback a `latest_valid` cuando `use_baseline_as_parent=true`.
- El primer run nuevo queda configurado para partir desde `state/current_baseline.json` y no desde un `EXP_*` anterior.
- Cuando una corrida nueva de esta rama sea aceptada para follow-up, el estado puede pasar a usar ese nuevo run fresco como parent de la rama.

## Garantias del reset

- No se borraron runs historicos.
- No se borro ni reescribio `trackers/experiment_log.csv`.
- No se modifico `state/current_baseline.json`.
- No se promovio baseline.
- No se ejecutaron backtests.
- `EXP_138`, `EXP_142`, `EXP_143`, `EXP_145` y `EXP_156` quedan prohibidos como parent.
- Los `EXP_*` anteriores quedan como memoria/analisis, no como parent activo.

## Runs rezagados durante el stop

Mientras se frenaban los procesos vivos, un supervisor rezagado alcanzo a iniciar corridas `EXP_157` parciales:

- `runs/multi_agent_runs/EXP_157_260425195414`
- `runs/multi_agent_runs/EXP_157_260425195907`

Ambas quedaron marcadas con `recovery_status.json` como `aborted_for_soft_reset` y `do_not_use_as_parent=true`.
