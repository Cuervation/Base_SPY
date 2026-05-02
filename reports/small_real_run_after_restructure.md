# Small Real Run After Restructure

Date: 2026-04-24

## 1. Executive Summary

Status: **FAIL** (`fail_operativo`)

- Intended windows: `4,8` only (operational validation).
- Run directory created: `runs/multi_agent_runs/EXP_135_260424120531/`
- Completion: **NOT completed** (process was terminated to enforce the constraint "do not run 24/52/156").
- Path/import errors: **none observed**.
- Baseline modified: **NO** (SHA256 unchanged).
- Research state modified: **NO** (SHA256 unchanged).
- Experiment log updated: **NO** (row count unchanged; SHA256 unchanged).

Critical issue detected:
- Despite `--evaluation-windows 4,8`, the executor progressed to `24` and started `52`. This violates the run constraint and blocks proceeding with real-run validation under the requested limits.

## 2. Comando ejecutado

```powershell
python run_multi_agent_iteration.py --repo . --baseline-json state/current_baseline.json --experiment-log trackers/experiment_log.csv --dependencies-json config/parameter_dependencies.json --evaluation-windows 4,8
```

## 3. Archivos generados

Run dir: `runs/multi_agent_runs/EXP_135_260424120531/`

| archivo | existe | comentario |
|---|---:|---|
| `analyst_output.json` | sí | generado |
| `coder_output.json` | sí | generado |
| `preflight_output.json` | sí | generado |
| `executor_output.json` | no | no llegó a persistir output final (proceso detenido) |
| `coordinator_output.json` | no | no llegó a persistir output final (proceso detenido) |
| `experiment_manifest.json` | no | no llegó a persistir output final (proceso detenido) |
| `run_live_status.log` | sí | evidencia de ejecución por ventanas |

Nota:
- Se crearon subcarpetas `window_04/`, `window_08/`, `window_24/`, `window_52/` durante la ejecución.

## 4. Resultado del executor

Desde `run_live_status.log`:
- 4w: `run_ok`
- 8w: `run_ok`
- 24w: `run_ok` (no permitido por la consigna; motivo de abort)
- 52w: **iniciado** (no permitido; proceso detenido inmediatamente después de detectar el desvío)

Insufficient depth:
- No evaluado (no se llegó a 156 por diseño; aun así, el plan avanzó a 52).

Errores:
- No se observan errores de import/path en el log.

## 5. Resultado del coordinator

No disponible:
- `coordinator_output.json` no fue generado por la interrupción manual para evitar ventanas largas.

## 6. Validación de contracts

No ejecutable para este run:
- No existe `coordinator_output.json` para validar.

## 7. Seguridad de baseline/state

Checks realizados por hash y conteo:
- `state/current_baseline.json` modificado: **no**
- `state/research_state.json` modificado: **no**
- `trackers/experiment_log.csv` actualizado: **no**
- Filas nuevas en experiment_log: **0**

## 8. Riesgos detectados

Críticos:
- El flag `--evaluation-windows 4,8` no limita efectivamente la ejecución a 4/8; el plan progresivo ejecuta 24 y comienza 52. Esto impide un “small real run” bajo restricciones operativas.

Medios:
- Se generan artefactos parciales en `runs/multi_agent_runs/` cuando se aborta la corrida (ruido operativo).

Menores:
- Ninguno adicional observado.

## 9. Veredicto

**corregir_antes_de_mas_corridas**

Motivo:
- Antes de una corrida real mínima controlada, hay que asegurar que el runner respete estrictamente las ventanas pedidas (4/8) sin progresar a 24/52/156.

Recordatorio:
- No se ejecutaron backtests largos de forma intencional; el avance a 24/52 fue un comportamiento del runner, por eso se detuvo la ejecución.

