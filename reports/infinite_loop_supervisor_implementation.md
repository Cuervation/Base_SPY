# Infinite Loop Supervisor Implementation

## 1. Executive Summary

Se implemento un supervisor autonomo para el loop multiagente con:
- seleccion de parent valida y descartando runs incompletos o marcados `do_not_use_as_parent`
- bloqueo explicito de `156`
- soporte de `dry-run` sin backtests ni mutacion de baseline
- trazabilidad viva en `state/autonomous_loop_state.json` y `reports/autonomous_loop_live_summary.md`
- resumen final en `reports/autonomous_loop_final_summary.md`

Validacion liviana ejecutada:
- `python -m py_compile ...` sobre runner, supervisor y validadores
- tests unitarios nuevos
- `python validators/validate_required_run_artifacts.py --run-dir runs/multi_agent_runs/EXP_143_260425110403` -> `BLOCKED_PREFLIGHT_COMPLETE`
- `python scripts/loop/run_infinite_research_loop.py --repo . --windows 4,8,24,52 --max-iterations 0 --dry-run`

No se ejecuto loop real, no se corrio 156 y no se modifico `state/current_baseline.json`.

## 2. Archivos creados o modificados

| Archivo | Cambio | Motivo |
| --- | --- | --- |
| `scripts/loop/run_infinite_research_loop.py` | Nuevo supervisor autonomo con dry-run, parent selection, validacion y resumenes | Ejecutar loop estable sin prompts por corrida |
| `scripts/loop/__init__.py` | Nuevo | Permitir import limpio del supervisor |
| `scripts/__init__.py` | Nuevo | Hacer `scripts` importable como paquete |
| `config/autonomous_loop_config.json` | Nuevo | Centralizar ventanas, paradas y paths del loop |
| `state/autonomous_loop_state.json` | Nuevo template | Estado vivo listo para el primer arranque real |
| `reports/autonomous_loop_live_summary.md` | Nuevo template | Resumen vivo actualizable por iteracion |
| `run_multi_agent_iteration.py` | Modificado | Hacer que `parent_state` sea fuente valida de parent y persistir parent activo |
| `tests/test_autonomous_loop_parent_selection.py` | Nuevo | Verificar que se salten parents invalidos y gane el champion valido |
| `tests/test_forbidden_156_window.py` | Nuevo | Verificar bloqueo de `156` en el plan |
| `tests/test_blocked_preflight_complete.py` | Nuevo | Verificar clasificacion `BLOCKED_PREFLIGHT_COMPLETE` |
| `tests/test_no_parent_incomplete_runs.py` | Nuevo | Verificar clasificacion `INCOMPLETE_NO_PARENT` |
| `tests/test_baseline_not_modified_by_loop.py` | Nuevo | Verificar que el dry-run no modifica baseline |

## 3. Como correr el loop infinito

```powershell
python scripts/loop/run_infinite_research_loop.py --repo . --windows 4,8,24,52 --max-iterations 0
```

Notas:
- `--max-iterations 0` significa infinito.
- `156` queda fuera del loop por config y por guardas duras.
- el supervisor escribe `loop_trace.jsonl`, `state/autonomous_loop_state.json` y los summary files durante ejecucion.

## 4. Como detenerlo

- `Ctrl+C` para parada limpia.
- El supervisor captura la interrupcion y escribe el resumen final.
- Tambien frena por:
  - `promoted_to_baseline=true` sin aplicar promotion
  - `fix_process_before_more_research`
  - baseline cambiado
  - demasiados fallos operativos o warnings
  - `BLOCKED_PREFLIGHT_COMPLETE` segun politica de stop controlado

## 5. Como revisar el live summary

Abrir:

`reports/autonomous_loop_live_summary.md`

Ese archivo muestra:
- estado del loop
- iteraciones completadas
- parent actual
- ultimo run
- ultimos runs procesados

## 6. Como saber si hay pending promotion

Revisar:
- `reports/autonomous_loop_final_summary.md`
- `runs/multi_agent_runs/<RUN_ID>/pending_promotion_review.json`

Si aparece `promoted_to_baseline=true`, el supervisor no aplica la promotion automaticamente y la deja como pendiente.

## 7. Que runs quedan prohibidos como parent

El supervisor y el runner ahora excluyen:
- runs con `do_not_use_as_parent=true`
- runs con `coordinator_output.json` faltante
- runs con `executor_output.json` faltante
- runs con `experiment_manifest.json` faltante
- `RECOVERABLE_PARTIAL_RUN`
- `INCOMPLETE_NO_PARENT`
- `blocked_preflight` incompleto
- `BLOCKED_PREFLIGHT_COMPLETE` como parent tecnico

## 8. Estado de validacion

Resultado de la simulacion liviana:
- parent selection: OK
- bloqueo de `156`: OK
- blocked preflight complete: OK
- baseline immutability en dry-run: OK

## 9. Proximo paso recomendado

Ejecutar el supervisor real con:

```powershell
python scripts/loop/run_infinite_research_loop.py --repo . --windows 4,8,24,52 --max-iterations 0
```

Y monitorear:
- `reports/autonomous_loop_live_summary.md`
- `state/autonomous_loop_state.json`
- `logs/autonomous_loop/loop_trace.jsonl`

