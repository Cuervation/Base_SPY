# Baseline Changed Regression Fix

Fecha: 2026-04-26

## Hallazgo

Durante `EXP_170`, el loop terminó como `run_ok/rejected`, pero el supervisor marcó `baseline_changed=True` y frenó con `stop_reason=baseline_changed`.

Eso no debería ocurrir cuando no se pasa `--apply-baseline-promotion`.

## Causa raiz

La escritura del baseline estaba demasiado permisiva en `run_multi_agent_iteration.py`:

- `ensure_baseline()` podía materializar o "normalizar" `state/current_baseline.json` con `save_json(...)` al arrancar.
- En la ruta de promoción, el código también actualizaba `baseline["updated_at"]`, lo que podía ensuciar el hash aunque la intención fuera solo auditar la corrida.

En otras palabras, el baseline no estaba estrictamente tratado como read-only fuera de una promoción aplicada explícitamente.

## Que se corrigio

### 1. Baseline read-only por defecto

Archivo: [`run_multi_agent_iteration.py`](C:\Pythons\ML-Trading\Base_Archivos_SPY\run_multi_agent_iteration.py)

- `ensure_baseline()` ya no escribe a disco.
- Si el baseline falta o es invalido, ahora se devuelve una version limpia en memoria sin persistir reparaciones automaticas.

### 2. El timestamp salio del baseline

Archivo: [`run_multi_agent_iteration.py`](C:\Pythons\ML-Trading\Base_Archivos_SPY\run_multi_agent_iteration.py)

- Se elimino `baseline["updated_at"] = ...` de la ruta de promocion.
- En su lugar, se guarda `last_promoted_baseline_at` en `state/research_state.json`.

### 3. Guard de escritura explicito

Archivo: [`run_multi_agent_iteration.py`](C:\Pythons\ML-Trading\Base_Archivos_SPY\run_multi_agent_iteration.py)

- La escritura de `state/current_baseline.json` queda permitida solo cuando:
  - `decision_type == "promoted_to_baseline"`, y
  - `--apply-baseline-promotion` esta presente.

## Verificacion

- `python -m py_compile run_multi_agent_iteration.py scripts\\loop\\run_infinite_research_loop.py validators\\validate_baseline_immutability.py` pasa.
- No se corrieron backtests nuevos.
- No se ejecuto el loop.
- No se modifico `state/current_baseline.json` en este fix.

## Impacto esperado

- Evita falsos `baseline_changed=True` en corridas rechazadas o de follow-up.
- Mantiene el baseline inmutable salvo promocion aplicada.
- Conserva el timestamp de auditoria en `research_state`, no en el baseline.

## Archivos tocados

- [`run_multi_agent_iteration.py`](C:\Pythons\ML-Trading\Base_Archivos_SPY\run_multi_agent_iteration.py)
- [`reports/baseline_changed_regression_fix.md`](C:\Pythons\ML-Trading\Base_Archivos_SPY\reports/baseline_changed_regression_fix.md)
