# Artifact Persistence Fix Report

Date: 2026-04-24

## 1. Executive Summary

Problema detectado:
- En un run 4,8,24,52 (EXP_138) se completaron las ventanas segun `run_live_status.log`, pero faltaron artefactos finales:
  - `executor_output.json`
  - `coordinator_output.json`
  - `experiment_manifest.json`
- Causa probable: termination externa (timeout) luego de una ventana larga (52w) antes del "final persist".

Solucion aplicada:
- Checkpoint incremental y atomico del executor tras cada ventana:
  - `executor_output.partial.json` (atomic write)
- Summary por ventana:
  - `window_XX/window_result.json` (atomic write)
- Estado final best-effort:
  - `run_status.json` (atomic write)
- Recovery tooling:
  - `scripts/recovery/finalize_incomplete_run.py` para reconstruir artefactos minimos sin tocar baseline ni experiment_log.
- Validator:
  - `validators/validate_required_run_artifacts.py`

Listo para repetir batch 4,8,24,52:
- **Mejorado** para no perder evidencia aunque el proceso termine. Recomendacion: reintentar con max_iterations=1 y validar artefactos con el nuevo validator.

## 2. Archivos modificados

| archivo | cambio | motivo |
|---|---|---|
| `run_multi_agent_iteration.py` | `executor_output.partial.json` + `window_result.json` + `run_status.json` con escritura atomica | evitar perdida de evidencia en runs largos |
| `scripts/recovery/finalize_incomplete_run.py` | nuevo script de recovery/finalizacion | reconstruir artefactos minimos sin backtests |
| `validators/validate_required_run_artifacts.py` | nuevo validador | detectar OK / recoverable / fail |
| `runbooks/how_to_recover_incomplete_52_run.md` | nuevo runbook | guiar operacion de recovery |
| `runs/multi_agent_runs/EXP_138_260424193914/recovery_status.json` | marcado como incomplete/recoverable | no usar como parent, si para analisis de proceso |
| `tests/test_run_artifact_persistence.py` | tests minimos (unittest) | validar clasificacion basica sin backtests |

## 3. Nueva política de checkpointing

- `executor_output.partial.json`:
  - se actualiza despues de cada ventana completada
  - escritura atomica (.tmp + rename)
- `window_result.json`:
  - se escribe dentro de cada `window_XX/` con resumen de status/metrics/outputs
  - escritura atomica
- `run_status.json`:
  - se escribe al final como resumen best-effort (si se llega)

## 4. Recovery de runs incompletos

### Validar artefactos requeridos
```powershell
python validators/validate_required_run_artifacts.py --run-dir runs/multi_agent_runs/EXP_XXX_...
```

### Finalizar un run incompleto (sin tocar baseline/experiment_log)
```powershell
python scripts/recovery/finalize_incomplete_run.py --run-dir runs/multi_agent_runs/EXP_XXX_...
```

Notas:
- No modifica `state/current_baseline.json`.
- No modifica `trackers/experiment_log.csv` por defecto (solo con flag explicito, no recomendado automaticamente).
- Si falta `coordinator_output.json`, deja `coordinator_pending=true`.

## 5. Estado de EXP_138

- Marcado como: `incomplete_recoverable_candidate`
- safe_for_strategy_analysis: **no**
- safe_for_process_analysis: **si**
- do_not_use_as_parent: **si**

## 6. Tests agregados

- `tests/test_run_artifact_persistence.py`

## 7. Próximo paso recomendado

- Ejecutar recovery (dry) sobre EXP_138:
  - `python scripts/recovery/finalize_incomplete_run.py --run-dir runs/multi_agent_runs/EXP_138_260424193914`
  - `python validators/validate_required_run_artifacts.py --run-dir runs/multi_agent_runs/EXP_138_260424193914`
- Repetir batch chico con `max_iterations=1` usando ventanas `4,8,24,52`.
- No correr 156.
- No promover baseline.

