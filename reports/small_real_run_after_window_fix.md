# Small Real Run After Restructure (After Window Fix)

Date: 2026-04-24

## 1. Executive Summary

Status: **FAIL**

- Run dir: `runs/multi_agent_runs/EXP_135_260424144330/`
- Run completed: **yes** (`run_ok`)
- Path/import errors: **none observed**
- Windows executed: **4, 8 only** (strict constraint respected)
- Forbidden windows executed (24/52/156): **no**
- Baseline promoted automatically: **no**
- `trackers/experiment_log.csv` updated: **yes** (+1 row)
- `state/current_baseline.json` modified: **YES (unexpected)**  
  Baseline file hash changed; observed `updated_at` was written to `2026-04-24T14:50:06`.

Reason for FAIL:
- The run respected the strict window constraint, but it **modified `state/current_baseline.json`** (at least `updated_at`), which violates the run constraint “No modificar current_baseline”.

## 2. Comando ejecutado

```powershell
python run_multi_agent_iteration.py --repo . --baseline-json state/current_baseline.json --experiment-log trackers/experiment_log.csv --dependencies-json config/parameter_dependencies.json --evaluation-windows 4,8
```

## 3. Archivos generados

| archivo | existe | comentario |
|---|---:|---|
| `analyst_output.json` | sí | generado |
| `coder_output.json` | sí | generado |
| `executor_output.json` | sí | generado |
| `coordinator_output.json` | sí | generado |
| `experiment_manifest.json` | sí | generado |
| `run_live_status.log` | sí | generado |
| `window_execution_plan.json` | sí | generado (nuevo control) |

## 4. Resultado del executor

- Ventanas corridas: `4`, `8`
- Status:
  - `executor_output.status = run_ok`
- `window_execution_plan.json`:
  - requested_windows: `[4, 8]`
  - allowed_windows: `[4, 8]`
  - progressive_windows_enabled: `false`
  - executed_windows: `[4, 8]`
  - forbidden_windows: `[24, 52, 156]`

## 5. Resultado del coordinator

Desde `coordinator_output.json`:
- status: `run_ok`
- gate_decision: `continue`
- decision_type: `rejected`
- accepted_for_followup: `false`
- promoted_to_baseline: `false`
- auditor_v2_evaluation.recommended_next_action: `controlled_exploration`
- auditor_v2_evaluation.recommended_change_directions: `['reactivate_disabled_gate']`

Nota:
- No se aplico ninguna promoción (solo se reporta).

## 6. Validación de contracts

- `python validators/validate_coordinator_output.py --path runs/multi_agent_runs/EXP_135_260424144330/coordinator_output.json`
  - **OK**

## 7. Seguridad de baseline/state

### current_baseline
- `state/current_baseline.json` modificado: **sí (unexpected)**
  - Se observó `updated_at = 2026-04-24T14:50:06`.

### research_state
- `state/research_state.json` modificado: **sí**
  - `updated_at = 2026-04-24T14:50:06`.
  - Esto es esperable si el flujo persiste estado de rama/memoria.

### experiment_log
- `trackers/experiment_log.csv` actualizado: **sí**
- Filas nuevas: **1** (count 134 -> 135)

## 8. Riesgos detectados

Críticos:
- El runner escribe en `state/current_baseline.json` durante una corrida normal (al menos `updated_at`). Si la política operativa requiere baseline inmutable salvo promoción explícita, esto debe corregirse antes de más corridas.

Medios:
- `baseline_reference.script` dentro del baseline apunta a un path legacy (`...\\multi_agent_runs\\...`) que ya no coincide con `runs/multi_agent_runs/` (no rompe esta corrida, pero es deuda de paths).

Menores:
- Ninguno adicional observado.

## 9. Veredicto

**corregir_antes_de_mas_corridas**

Acción recomendada:
- Antes de repetir otra corrida real, decidir si:
  1. es aceptable que `state/current_baseline.json` se modifique solo en metadatos (`updated_at`), o
  2. hay que ajustar el flujo para que baseline no se toque salvo promoción explícita.

Recordatorio:
- No correr todavía `24/52/156`.

