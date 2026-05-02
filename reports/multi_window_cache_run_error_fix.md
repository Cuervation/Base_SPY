# Multi Window Cache Run Error Fix

Fecha: 2026-04-26

## Diagnostico

Las corridas `EXP_172`, `EXP_173` y `EXP_174` quedaron en `run_error` porque el modo `multi_window_single_run` estaba generando el script derivado de `52` con un prelude de cache inyectado antes de `from __future__ import annotations`.

La traza cruda lo confirma en `window_52/stderr.log`:

- `SyntaxError: from __future__ imports must occur at the beginning of the file`

Eso rompe la ventana base `52` antes de que el flujo pueda derivar `24/8/4`.

## Causa raiz

Archivo: [`run_multi_agent_iteration.py`](C:\Pythons\ML-Trading\Base_Archivos_SPY\run_multi_agent_iteration.py)

- El bloque `SPY DATASET CACHE PRELUDE` se estaba prefijando al inicio del script generado.
- Eso desplazaba `from __future__ import annotations` fuera del primer bloque valido del archivo.
- Resultado: el subprocess de `52` fallaba y el executor marcaba `run_error`.

## Fix aplicado

### 1) Prelude de cache seguro para `from __future__`

Archivo: [`run_multi_agent_iteration.py`](C:\Pythons\ML-Trading\Base_Archivos_SPY\run_multi_agent_iteration.py)

- Se agrego `insert_text_after_future_imports(...)`.
- El prelude ahora se inserta despues de los `future imports`, no antes.
- Esto evita el `SyntaxError` en el script derivado de `52`.

### 2) Fallback al modo legacy

Archivo: [`run_multi_agent_iteration.py`](C:\Pythons\ML-Trading\Base_Archivos_SPY\run_multi_agent_iteration.py)

- Si la ventana reutilizada `52` falla dentro de `multi_window_single_run`, el runner apaga `window_reuse_enabled` y pasa a flujo legacy secuencial para las ventanas restantes de esa corrida.
- Se loguea el cambio con `fallback=legacy_sequential`.

### 3) Resumen final corregido

Archivo: [`scripts/loop/run_infinite_research_loop.py`](C:\Pythons\ML-Trading\Base_Archivos_SPY\scripts\loop\run_infinite_research_loop.py)

- Si existe cualquier `run_error`, el resumen final ya no puede quedar en `PASS`.
- Ahora baja a `FAIL`.
- Si solo hay señales no fatales, puede quedar en `PASS_WITH_WARNINGS`.
- La recomendacion ya no puede quedar en `seguir_loop` cuando hay `run_error`.

## Evidencia revisada

Se revisaron estos artefactos de `EXP_172`, `EXP_173` y `EXP_174`:

- `run_live_status.log`
- `run_status.json`
- `executor_output.json`
- `executor_output.partial.json`
- `experiment_manifest.json`
- `stderr.log`

## Verificacion

- `python -m py_compile run_multi_agent_iteration.py scripts\\loop\\run_infinite_research_loop.py validators\\validate_baseline_immutability.py` pasa.
- No se corrieron nuevas iteraciones.
- No se corrieron backtests nuevos.
- No se modifico `state/current_baseline.json`.

## Impacto esperado

- Evita el `SyntaxError` del derivado de `52`.
- Permite que el flujo reutilizado caiga a secuencial si esa via falla.
- Evita resúmenes falsamente optimistas cuando hubo `run_error`.

## Archivos tocados

- [`run_multi_agent_iteration.py`](C:\Pythons\ML-Trading\Base_Archivos_SPY\run_multi_agent_iteration.py)
- [`scripts/loop/run_infinite_research_loop.py`](C:\Pythons\ML-Trading\Base_Archivos_SPY\scripts\loop\run_infinite_research_loop.py)
- [`reports/multi_window_cache_run_error_fix.md`](C:\Pythons\ML-Trading\Base_Archivos_SPY\reports\multi_window_cache_run_error_fix.md)
