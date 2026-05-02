# Blocked Preflight Fix Summary

## 1. Executive Summary

Se corrigió la clasificación de `blocked_preflight` para que sea un cierre válido de run bloqueado y no un falso `INCOMPLETE_NO_PARENT`.

Antes:
- un preflight bloqueado podía terminar sin `executor_output.json`
- el validador lo trataba como run incompleto
- eso confundía un stop controlado con un faltante de artifacts

Ahora:
- `run_multi_agent_iteration.py` persiste cierre explícito para `blocked_preflight`
- `run_status.json` queda con `status=blocked_preflight`
- `experiment_manifest.json` queda con `status=blocked_preflight`
- `recovery_status.json` queda con:
  - `do_not_use_as_parent=true`
  - `safe_for_strategy_analysis=false`
  - `safe_for_process_analysis=true`
- `validators/validate_required_run_artifacts.py` devuelve `BLOCKED_PREFLIGHT_COMPLETE`

No se corrieron nuevas iteraciones, no se corrieron backtests y no se modificó `state/current_baseline.json`.

## 2. Files Updated

- `run_multi_agent_iteration.py`
  - cierre explícito para rama `blocked_preflight`
  - escritura de `run_status.json`
  - escritura de `recovery_status.json`
  - protección del finalizer `ensure_controlled_abort_artifacts(...)` para no clasificar `blocked_preflight` como incompleto

- `validators/validate_required_run_artifacts.py`
  - detección de `blocked_preflight` vía `run_status.json` o `experiment_manifest.json`
  - retorno `BLOCKED_PREFLIGHT_COMPLETE`
  - no exige `executor_output.json` para este caso

## 3. New Semantics

`blocked_preflight` ahora significa:
- el run terminó de forma controlada antes del executor
- no es usable como parent
- sí es usable para análisis de proceso
- no debe confundirse con artifacts faltantes

## 4. Validation

Validaciones livianas realizadas:

```powershell
python -m py_compile run_multi_agent_iteration.py validators\validate_required_run_artifacts.py
python validators\validate_required_run_artifacts.py --run-dir runs\multi_agent_runs\EXP_143_260425110403
```

Resultado:
- compilación: OK
- validador sobre `EXP_143`: `BLOCKED_PREFLIGHT_COMPLETE`

## 5. Operational Note

Si vuelve a aparecer un `blocked_preflight`:
- frenar el loop de forma controlada
- no usar el run como parent
- no tratarlo como error de artifacts faltantes
- revisar la causa del preflight, no el cierre de persistencia
