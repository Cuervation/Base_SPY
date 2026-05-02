# Short Window No Trades Handling

## Resumen

Se ajustó el manejo de ventanas derivadas cortas en `multi_window_single_run` para que una ventana con `trades = 0` no se trate como error técnico ni como `run_error`.

Ahora, cuando una ventana derivada corta no tiene actividad suficiente:

- `status = short_window_no_trades`
- `depth_ok = false`
- `reason = insufficient_short_window_activity`
- `spy_compare` puede quedar `null` o `NaN` sin romper el flujo

## Archivos tocados

- `run_multi_agent_iteration.py`
- `scripts/loop/run_infinite_research_loop.py`
- `validators/validate_short_window_no_trades.py`

## Comportamiento nuevo

- Las ventanas derivadas cortas con `trades = 0` quedan clasificadas como evidencia insuficiente.
- `short_window_no_trades` no bloquea la corrida como falla operativa.
- `52w` y `24w` válidas siguen siendo evidencia útil para la corrida.
- El loop final ya no considera este caso como fallo operacional.

## Validación

- `py_compile` pasó para los archivos modificados.
- El nuevo validador acepta `short_window_no_trades` como caso no fatal.

## Nota operativa

Este cambio no toca:

- estrategia de trading
- baseline
- promoción de baseline
- ejecución de `156`

