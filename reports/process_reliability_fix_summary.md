# Process Reliability Fix Summary

## 1. Executive Summary

Se frenó research y se aplicó un fix operativo para cierre robusto de runs incompletos.

Problema raíz confirmado:
- `run_multi_agent_iteration.py` escribía artifacts finales (`executor_output.json`, `coordinator_output.json`, `experiment_manifest.json`) en la fase final del flujo.
- Si el proceso terminaba antes de llegar a ese bloque (por abort/timeout externo o salida no controlada), quedaba solo `executor_output.partial.json` y faltaban finals.

Resultado del fix:
- ahora el runner tiene finalización defensiva por salida (`atexit`) para persistir estado mínimo de cierre;
- siempre intenta escribir `run_status.json`;
- si hay `executor_output.partial.json` utilizable y falta `executor_output.json`, lo sintetiza;
- si falta `experiment_manifest.json`, genera uno de tipo incomplete/recovery;
- no genera `coordinator_output.json` automáticamente si no hay finalización normal válida.

No se corrieron nuevas iteraciones, no se corrieron backtests, no se promovió baseline y no se modificó `state/current_baseline.json`.

## 2. Files Updated

- `run_multi_agent_iteration.py`
  - agregado cierre defensivo por `atexit`;
  - agregado `ensure_controlled_abort_artifacts(...)`;
  - agregado síntesis de `executor_output.json` desde `executor_output.partial.json` en abort controlado;
  - agregado generación de `experiment_manifest.json` incompleto cuando falta;
  - agregado escritura de `run_status.json` en salida de proceso;
  - agregado actualización de contexto de salida (`exit_ctx`) en rutas de retorno temprano.

- `validators/validate_required_run_artifacts.py`
  - ahora distingue explícitamente:
    - `COMPLETE`
    - `RECOVERABLE_PARTIAL_RUN`
    - `INCOMPLETE_NO_PARENT`
  - mantiene `FAIL_UNRECOVERABLE` para falta de plan/log.

- `runbooks/how_to_handle_recoverable_partial_run.md`
  - nuevo runbook operativo para manejo de runs recuperables/incompletos y reglas de parent safety.

## 3. EXP_142 Status

`runs/multi_agent_runs/EXP_142_260425014932/recovery_status.json` quedó alineado con la política solicitada:
- `do_not_use_as_parent: true`
- `safe_for_strategy_analysis: false`
- `safe_for_process_analysis: true`

Además, con el validador actualizado:
- estado de EXP_142: `RECOVERABLE_PARTIAL_RUN`.

## 4. Validation Performed (lightweight only)

Comandos ejecutados:

```powershell
python -m py_compile run_multi_agent_iteration.py validators\validate_required_run_artifacts.py
python validators\validate_required_run_artifacts.py --run-dir runs\multi_agent_runs\EXP_142_260425014932
```

Resultado:
- compilación: OK
- artifacts validator (EXP_142): `RECOVERABLE_PARTIAL_RUN`

## 5. Operational Guidance Before Resuming Research

- Mantener `EXP_142` fuera de parent selection (proceso-only evidence).
- Reanudar research solo después de verificar en la próxima corrida que:
  - `run_status.json` se genera siempre;
  - si hay abort controlado, aparece `executor_output.json` recuperado + `experiment_manifest.json` incomplete;
  - no se crea `coordinator_output.json` en recuperación parcial.
