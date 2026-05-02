# Window Constraint Fix Report

Date: 2026-04-24

## 1. Executive Summary

Bug detected:
- A "small real run" requested with `--evaluation-windows 4,8` still progressed to `24` and started `52`.

Probable cause:
- The executor always built and followed a progressive window plan (`build_progressive_window_plan`) even when the user explicitly requested a limited subset.

Solution applied:
- `--evaluation-windows` is now **strict by default**: only the requested windows are allowed.
- Progressive extension is only enabled when `--allow-progressive-windows` is explicitly provided.
- Added a pre-window guard that blocks forbidden windows before folder creation and aborts the run with `blocked_window_not_allowed`.
- Added auditable `window_execution_plan.json` in each run directory.

Ready to repeat small real run:
- **Yes** (repeat `4,8` only), and validate with `validators/validate_window_constraints.py`.

## 2. Archivos modificados

| archivo | cambio | motivo |
|---|---|---|
| `run_multi_agent_iteration.py` | strict window constraints + `--allow-progressive-windows` + pre-window guard + `window_execution_plan.json` | prevent accidental 24/52/156 on minimal runs |
| `validators/validate_window_constraints.py` | new validator for run dirs | automated enforcement |
| `tests/test_window_constraints.py` | minimal unit tests (stdlib `unittest`) | verify strictness logic without backtests |
| `runbooks/how_to_run_small_real_validation.md` | runbook documenting strict windows + validator usage | operational clarity |

## 3. Nueva semántica de --evaluation-windows

### Modo estricto (default)
- If `--evaluation-windows` is provided, those windows are the only allowed ones.
- Any attempt to run a window outside allowed set is blocked with status:
  - `blocked_window_not_allowed`

### Modo progresivo (explicit)
- Use `--allow-progressive-windows` to allow the progressive plan to extend beyond the requested list.

## 4. Validator agregado

Usage:
```powershell
python validators/validate_window_constraints.py --run-dir <RUN_DIR> --allowed-windows 4,8
```

It fails if:
- `window_24/`, `window_52/`, or `window_156/` exists when not allowed, or
- `window_execution_plan.json` records executed windows outside the allowed set.

## 5. Tests agregados

- `tests/test_window_constraints.py` (stdlib `unittest`; no backtests)

## 6. Riesgos pendientes

Críticos:
- None identified for the window-constraint bug.

Medios:
- If some automation depended on implicit progressive behavior with a reduced `--evaluation-windows` list, it must now pass `--allow-progressive-windows`.

Menores:
- Existing partially written runs (like the earlier `EXP_135_260424120531`) will fail the new validator, as expected.

## 7. Próximo paso recomendado

- Repetir small real run con `--evaluation-windows 4,8` (sin `--allow-progressive-windows`).
- Validar el run dir con:
  - `python validators/validate_window_constraints.py --run-dir runs/multi_agent_runs/<RUN_DIR> --allowed-windows 4,8`

No correr todavía `24/52/156`.

