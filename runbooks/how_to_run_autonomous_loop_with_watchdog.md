# Autonomous Loop Watchdog

## Arrancar

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/loop/start_watchdog.ps1
```

## Frenar

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/loop/stop_watchdog.ps1
```

## Logs

- `logs/autonomous_loop/watchdog.log`
- `logs/autonomous_loop/watchdog_start.log`
- `logs/autonomous_loop/watchdog_stop.log`
- `logs/autonomous_loop/watchdog.pid`

## Loop autónomo aparte

El watchdog no arranca el loop de research. Si el loop autónomo se va a ejecutar, debe lanzarse por separado.

## Alertas A Mirar

- `loop_status=running` pero no hay `python.exe` con `run_infinite_research_loop.py`
- `parent_valid=False` con `loop_status=running`
- `156_executed=True`
- `baseline_changed=True`
- `pending_promotion_review > 0`
- `status=FAIL`
- `incomplete_runs > 0`
- `no_parent_runs > 0`

## Cuándo Pedir Diagnóstico

- Si el watchdog marca `running` sin proceso `python.exe`.
- Si aparece `parent_valid=False` mientras el loop sigue vivo.
- Si reaparece `156` en cualquier ejecución.
- Si hay `FAIL`, `baseline_changed` o `pending_promotion_review`.
