# Watchdog Setup And Start

- status: `started`
- started_at: `2026-04-26T10:21:13-03:00`
- pid: `6116`

## Archivos

- created: `scripts/loop/watch_autonomous_loop.ps1`
- created: `scripts/loop/start_watchdog.ps1`
- created: `scripts/loop/stop_watchdog.ps1`
- created: `runbooks/how_to_run_autonomous_loop_with_watchdog.md`
- created: `reports/watchdog_setup_and_start_report.md`
- modified: `scripts/loop/watch_autonomous_loop.ps1`

## Estado

- watchdog_started: `true`
- pid_file: `logs/autonomous_loop/watchdog.pid`
- lock_file: `logs/autonomous_loop/watchdog.lock`
- main_log: `logs/autonomous_loop/watchdog.log`
- start_log: `logs/autonomous_loop/watchdog_start.log`
- stop_log: `logs/autonomous_loop/watchdog_stop.log`

## Stop

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/loop/stop_watchdog.ps1
```

## Next

- arrancar o detener el loop autónomo por separado cuando se pida explícitamente
- revisar `logs/autonomous_loop/watchdog.log` para alertas de estado del loop
