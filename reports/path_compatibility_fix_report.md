# Path Compatibility Fix Report

Date: 2026-04-24

## 1. Executive Summary

Se corrigieron los problemas criticos detectados en `reports/validation_after_restructure.md` para que el repo reorganizado pueda volver a correr sin romper por paths legacy ni leer state equivocado.

Que se corrigio:
- Se creo `config/paths_config.json` como fuente central de rutas.
- Se actualizaron runners (Python/PS1) y el generador de reportes para usar las rutas nuevas via `config/paths_config.json` (con fallback legacy donde aplica).
- Se definio que la fuente de verdad de state es `state/research_state.json` (no se borra `research_state.json` legacy en raiz).
- Se endurecio `contracts/coordinator_output.schema.json` con enums para `recommended_next_action` y campos clave del auditor_v2.
- Se reforzo `validators/validate_coordinator_output.py` para validar `recommended_next_action` aun sin `jsonschema` instalado.
- Se actualizo la skill `.agents/skills/iteration-audit/SKILL.md` para referenciar la estructura nueva.

Que NO se toco:
- No se cambio logica de trading.
- No se cambiaron parametros de estrategia.
- No se corrieron backtests ni el loop multiagente.
- No se promovio baseline.
- No se edito semantica de `state/current_baseline.json`.
- No se edito contenido de `trackers/experiment_log.csv` (solo se corrigieron referencias de path).
- No se borraron historicos.

Estado:
- Paths criticos (baseline/state/trackers/scripts/logs/runs) ya apuntan a la nueva estructura en los runners principales.
- El repo queda **listo_para_validacion_final** (con la nota de que algunos docs legacy en raiz siguen existiendo pero ya no son usados por los runners actualizados).

## 2. Archivos modificados

| archivo | cambio realizado | motivo |
|---|---|---|
| `config/paths_config.json` | agregado | configuracion central de rutas post-restructure |
| `run_multi_agent_iteration.py` | lectura de `paths_config`, defaults nuevos, resolucion de paths a state/trackers/scripts/logs/runs | evitar roturas por paths legacy y evitar leer state equivocado |
| `scripts/reports/generate_run_analysis.py` | lectura de `paths_config` y uso de paths nuevos | reportes deben leer trackers/state/runs/logs reorganizados |
| `run_multi_agent_iteration.ps1` | defaults nuevos + lectura `paths_config` + path nuevo a generate_run_analysis | runner no debe buscar artefactos en raiz |
| `run_multi_agent_executor_loop.ps1` | lectura `paths_config` + experiment_log/research_state/logs/analysis script por paths nuevos | loop largo no debe romper por paths legacy |
| `run_multi_agent_watchdog.ps1` | lectura `paths_config` + logs/baseline/exp_log/research_state/champions por paths nuevos | watchdog no debe reiniciar por falta de archivos movidos |
| `stop_after_next_corrida.ps1` | lectura `paths_config` + logs/experiment_log por paths nuevos | herramienta operativa compatible con estructura nueva |
| `contracts/coordinator_output.schema.json` | enums agregados para auditor_v2 (incluye `recommended_next_action`) | contract mas estricto y auditable |
| `validators/validate_coordinator_output.py` | validacion manual de `auditor_v2_evaluation.recommended_next_action` | no depender solo de jsonschema |
| `.agents/skills/iteration-audit/SKILL.md` | referencias legacy -> rutas nuevas | evitar auditorias que lean archivos ya movidos |

## 3. Paths legacy corregidos

| path viejo | path nuevo | archivo donde se corrigio |
|---|---|---|
| `current_baseline.json` | `state/current_baseline.json` | `run_multi_agent_iteration.py`, `run_multi_agent_iteration.ps1`, `run_multi_agent_watchdog.ps1`, `scripts/reports/generate_run_analysis.py` |
| `research_state.json` | `state/research_state.json` | `run_multi_agent_iteration.py`, `run_multi_agent_executor_loop.ps1`, `run_multi_agent_watchdog.ps1`, `scripts/reports/generate_run_analysis.py`, `.agents/skills/iteration-audit/SKILL.md` |
| `parameter_effect_memory.json` | `state/parameter_effect_memory.json` | `run_multi_agent_iteration.py`, `scripts/reports/generate_run_analysis.py` |
| `analyst_initial_tests_queue.json` | `state/queues/analyst_initial_tests_queue.json` | `run_multi_agent_iteration.py` |
| `experiment_log.csv` | `trackers/experiment_log.csv` | `run_multi_agent_iteration.py`, `run_multi_agent_iteration.ps1`, `run_multi_agent_executor_loop.ps1`, `run_multi_agent_watchdog.ps1`, `stop_after_next_corrida.ps1`, `scripts/reports/generate_run_analysis.py`, `.agents/skills/iteration-audit/SKILL.md` |
| `agent_live_runs_master.csv` | `trackers/agent_live_runs_master.csv` | `run_multi_agent_iteration.py` |
| `agent_live_runs_master.xlsx` | `trackers/agent_live_runs_master.xlsx` | `run_multi_agent_iteration.py` |
| `extract_backtest_metrics.py` | `scripts/metrics/extract_backtest_metrics.py` | `run_multi_agent_iteration.py` |
| `generate_run_analysis.py` | `scripts/reports/generate_run_analysis.py` | `run_multi_agent_iteration.ps1`, `run_multi_agent_executor_loop.ps1` |
| `multi_agent_loop_logs` | `logs/loop/multi_agent_loop_logs` | `run_multi_agent_executor_loop.ps1`, `run_multi_agent_watchdog.ps1` |
| `multi_agent_watchdog_logs` | `logs/watchdog/multi_agent_watchdog_logs` | `run_multi_agent_iteration.py`, `run_multi_agent_watchdog.ps1`, `stop_after_next_corrida.ps1` |
| `champion_runs.json` | `runs/champion_runs/champion_runs.json` | `run_multi_agent_iteration.py`, `run_multi_agent_watchdog.ps1`, `scripts/reports/generate_run_analysis.py` |
| `multi_agent_runs` | `runs/multi_agent_runs` | `run_multi_agent_iteration.py` |

Nota:
- `subspace_cooldowns.json` se mantuvo en raiz (no se movio en la reestructuracion); los runners siguen apuntando ahi.

## 4. Fuente de verdad del state

Fuente de verdad (runtime):
- current_baseline: `state/current_baseline.json`
- research_state: `state/research_state.json`
- parameter_effect_memory: `state/parameter_effect_memory.json`

El archivo legacy `research_state.json` en raiz:
- NO se borro.
- Los runners principales fueron actualizados para usar `state/research_state.json`.
- No se implemento sincronizacion automatica (deuda tecnica si alguien sigue usando el legacy).

## 5. Contract actualizado

`contracts/coordinator_output.schema.json` ahora valida con enum estricto:
- `auditor_v2_evaluation.recommended_next_action`:
  - `refine_current_branch`
  - `controlled_exploration`
  - `evidence_based_rollback`
  - `extend_validation`
  - `stop_branch`
  - `fix_process_before_more_research`

Tambien se agregaron enums para:
- `research_value`
- `branch_health`
- `learning_signal`
- `stagnation_risk`
- `main_friction`

## 6. Validadores ejecutados

| comando | resultado | comentario |
|---|---|---|
| `python validators/validate_research_state.py` | OK | estructura de `state/research_state.json` |
| `python validators/validate_duplicate_zigzag_policy.py` | OK | policy contiene reglas minimas |
| `python validators/validate_promotion_rules.py` | OK | policies followup/promotion consistentes |
| `python validators/validate_insufficient_depth.py` | OK | insufficient_depth no fatal y separacion baseline/followup |
| `python validators/validate_coordinator_output.py --path runs/multi_agent_runs/EXP_134_260423194104/coordinator_output.json` | OK (basic) | `jsonschema` no es requerido; se valido recommended_next_action manualmente |

## 7. Riesgos pendientes

Criticos:
- Ninguno restante relacionado a paths en los runners principales listados (ya apuntan a `paths_config.json`).

Medios:
- Persisten referencias legacy en docs de raiz (`AGENTS.md`, etc.) que mencionan nombres viejos; no rompe ejecucion, pero puede confundir.
- Algunos scripts no incluidos en la lista (p. ej. tooling ad-hoc) pueden seguir esperando paths legacy.

Menores:
- `__pycache__/` en raiz: recomendacion `.gitignore` (no se toco).

## 8. Proximos pasos

Estado sugerido: **listo_para_validacion_final**

Siguiente etapa (separada):
- Re-auditar `reports/validation_after_restructure.md` y re-ejecutar un grep global de paths legacy para docs (sin cambiar logica).
- Si se desea enforcement fuerte de schema via `jsonschema`, documentar dependencia o vendorizar validacion.

