# Validation After Restructure

## 1. Executive Summary

Status: **FAIL** (`corregir_antes_de_correr`)

- Estructura/carpetas objetivo: **OK** (creadas).
- Integracion de `coordinator` + governance + validators: **OK** a nivel de existencia y contenido base.
- Repo listo para volver a correr investigaciones: **NO** (hay riesgos/roturas de paths hardcodeados por la reorganizacion, sin compatibilidad).
- Riesgo de paths rotos: **ALTO (critico)**.
- Riesgo de contradiccion governance/state/contracts: **MEDIO** (principalmente contract/schema no restringe `recommended_next_action` como se espera; skills/docs aun referencian paths viejos).

Conteo (auditoria de esta corrida):
- Checks OK: 45+
- Warnings: 6+
- Errores: 3 (2 criticos)

Errores criticos:
- Scripts/PS1 referencian paths de archivos ya movidos (baseline/logs/trackers/scripts/runs/memory) y fallarian si se corre el loop sin ajustes o stubs.
- `contracts/coordinator_output.schema.json` no valida el enum de `auditor_v2_evaluation.recommended_next_action` segun el contrato esperado.

## 2. Checklist de estructura

| item | esperado | encontrado | status | comentario |
|---|---|---|---|---|
| spec/ | existe | si | OK |  |
| agents/ | existe | si | OK |  |
| .agents/skills/ | existe | si | OK |  |
| state/ | existe | si | OK |  |
| state/queues/ | existe | si | OK |  |
| config/ | existe | si | OK |  |
| scripts/ | existe | si | OK |  |
| scripts/metrics/ | existe | si | OK |  |
| scripts/reports/ | existe | si | OK |  |
| runs/ | existe | si | OK |  |
| trackers/ | existe | si | OK |  |
| reports/ | existe | si | OK |  |
| reports/iteration_reviews/ | existe | si | OK |  |
| logs/ | existe | si | OK |  |
| logs/launch/ | existe | si | OK |  |
| logs/loop/ | existe | si | OK |  |
| logs/watchdog/ | existe | si | OK |  |
| governance/ | existe | si | OK |  |
| contracts/ | existe | si | OK |  |
| validators/ | existe | si | OK |  |
| runbooks/ | existe | si | OK |  |
| outputs/ | existe | si | OK |  |
| cache/dataset/ | existe | si | OK |  |
| cache/trades/ | existe | si | OK |  |
| runtime/ | existe | si | OK |  |

## 3. Archivos faltantes

No se detectaron faltantes dentro del set explicitamente requerido por la auditoria.

Archivos de contracts opcionales (no presentes, no es error):
- `contracts/analyst_output.schema.json` (no existe)
- `contracts/executor_output.schema.json` (no existe)
- `contracts/experiment_manifest.schema.json` (no existe)

## 4. Archivos en raiz que deberian moverse

Sin mover en esta etapa (solo recomendacion; no se modifico nada):
- `run_multi_agent_iteration.py`, `run_multi_agent_iteration.ps1`, `run_multi_agent_executor_loop.ps1`, `run_multi_agent_watchdog.ps1`, `preflight_validator.ps1`: probablemente deberian vivir bajo `scripts/` o `runtime/` (pero hay dependencias de path).
- `run_analysis_current.md` / `run_analysis_current.csv`: podrian vivir bajo `reports/` u `outputs/`.
- `research_state.json`: permanece como legacy root; existe tambien `state/research_state.json` (posible duplicidad de fuente de verdad).
- Archivos grandes `sp500_feature_store_*.csv`: podrian vivir en `cache/dataset/` o una carpeta de data dedicada.

Basura/cache:
- `__pycache__/` permanece en raiz (correcto no tocar). Recomendacion: `.gitignore`.

## 5. Validacion de coordinator

Fuente: `agents/coordinator.md`

Estado: **OK (contenido)**.

Confirma que incluye:
- Follow-up vs baseline: incluye seccion y reglas para `accepted_for_followup` vs `promoted_to_baseline`. **OK**
- Duplicate vs zig-zag: define `duplicate_recent_proposal` vs `true_zigzag_reversal` y regla critica. **OK**
- Refinement monotonic: define `monotonic_refinement` como no bloqueable. **OK**
- Insufficient depth: define `insufficient_depth` como no fatal si 52 valida, preserva evidencia. **OK**
- Auditor v2: exige `auditor_v2_evaluation` y scores. **OK**
- Research modes: lista modos persistidos + campos requeridos. **OK**
- JSON output esperado: incluye estructura JSON. **OK**

Nota:
- El doc menciona persistencia en `current_baseline.json` / `research_state.json` en paths legacy; tras la reorganizacion, esos artefactos se movieron a `state/` y deberian alinearse en una futura etapa de refactor de paths (fuera de alcance de esta auditoria).

## 6. Validacion de governance

Archivos presentes:
- `governance/baseline_promotion_policy.md`: separa follow-up vs baseline. **OK**
- `governance/followup_acceptance_policy.md`: acepta evidencia util aunque no baseline; `insufficient_depth` no fatal. **OK**
- `governance/duplicate_zigzag_policy.md`: duplicado exacto no es zig-zag; solo `true_zigzag_reversal` autobloquea. **OK**
- `governance/insufficient_depth_policy.md`: `insufficient_depth` no fatal; preserva 24/52; permite follow-up y evita baseline cuando depende de multi-year. **OK**
- `governance/branch_anchor_policy.md`: ancla un parametro por iteraciones limitadas; persistencia manda. **OK**
- `governance/research_mode_policy.md`: define modos persistidos y regla de impacto en candidate selection. **OK**

No se detectaron contradicciones semanticas fuertes con `agents/coordinator.md`.

## 7. Validacion de state

Archivos presentes:
- `state/current_baseline.json` (movido desde raiz)
- `state/research_state.json` (estado normalizado)
- `state/parameter_effect_memory.json` (movido desde raiz)
- `state/queues/analyst_initial_tests_queue.json` (movido desde raiz)

`state/research_state.json` estructura requerida: **OK**.
- `branch_state.current_mode`: presente, valor `refine_current_branch` (valido).
- `branch_state.*` campos de modo: presentes.
- `parent_state.current_parent_run_id` y `parent_state.last_useful_run_id`: presentes.
- `branch_anchor`: presente.
- `friction_state`: presente.

Nota importante:
- Existe tambien `research_state.json` en raiz (legacy). Riesgo de doble fuente de verdad si el codigo sigue leyendo el legacy (ver seccion 10).

## 8. Validacion de contracts

Presente:
- `contracts/coordinator_output.schema.json` **OK** (existe, valida muchos campos estructurales y coherencia entre `decision_type` y booleanos).

Hallazgos:
- **ERROR (contract incompleto):** `auditor_v2_evaluation.recommended_next_action` esta tipado como string, pero no restringido al enum requerido:
  - `refine_current_branch`
  - `controlled_exploration`
  - `evidence_based_rollback`
  - `extend_validation`
  - `stop_branch`
  - `fix_process_before_more_research`

Impacto:
- Se puede aceptar un output del coordinator con valores invalidos y pasar schema, debilitando la gobernanza automatizada.

## 9. Validacion de validators

Presentes:
- `validators/validate_coordinator_output.py`
- `validators/validate_duplicate_zigzag_policy.py`
- `validators/validate_promotion_rules.py`
- `validators/validate_insufficient_depth.py`
- `validators/validate_research_state.py`

Estado: **OK (son validadores reales, no placeholders)**.
- Contienen logica: chequeos de frases requeridas en policies, estructura minima de state, y validacion basica/schema de coordinator output.

Nota:
- `validate_coordinator_output.py` hace validacion basica y usa `jsonschema` si esta instalado. Esto es razonable, pero implica que el entorno determina el nivel de strictness.

## 10. Posibles paths rotos

Estado: **CRITICO**. Se detectaron referencias hardcodeadas a paths legacy que ya no existen en raiz tras mover archivos.

Ejemplos (no exhaustivo; ver `rg`):

### Baseline y experiment log (movidos a `state/` y `trackers/`)
- `run_multi_agent_iteration.py`:
  - `--baseline-json` default `"current_baseline.json"`
  - `--experiment-log` default `"experiment_log.csv"`
- `run_multi_agent_iteration.ps1`:
  - `$BaselineJson = \"current_baseline.json\"`
  - `$ExperimentLog = \"experiment_log.csv\"`
- `scripts/reports/generate_run_analysis.py`:
  - `experiment_log = repo / \"experiment_log.csv\"`
  - `baseline_json = repo / \"current_baseline.json\"`
- `run_multi_agent_executor_loop.ps1`:
  - `Join-Path $repoRoot \"experiment_log.csv\"`
- `run_multi_agent_watchdog.ps1`:
  - `Join-Path $repo \"current_baseline.json\"`
  - `Join-Path $repo \"experiment_log.csv\"`

### Scripts movidos a `scripts/` pero runners esperan raiz
- `run_multi_agent_iteration.py`:
  - `extract_script = repo / \"extract_backtest_metrics.py\"` (ahora esta en `scripts/metrics/`)
- `run_multi_agent_iteration.ps1`:
  - `generate_run_analysis.py` se busca en raiz (ahora esta en `scripts/reports/`)

### Trackers movidos a `trackers/`
- `run_multi_agent_iteration.py`:
  - `agent_live_runs_master.csv` / `.xlsx` se buscan en raiz (ahora estan en `trackers/`)

### Logs movidos a `logs/`
- `run_multi_agent_iteration.py`, `run_multi_agent_watchdog.ps1`:
  - referencian `multi_agent_watchdog_logs/` y `multi_agent_loop_logs/` en raiz (ahora bajo `logs/`)

### Champions/memories movidos o desalineados
- `run_multi_agent_watchdog.ps1`:
  - `champion_runs.json` esperado en raiz (ahora `runs/champion_runs/champion_runs.json`)
- `run_multi_agent_iteration.py`:
  - `parameter_effect_memory.json` esperado en raiz (ahora `state/parameter_effect_memory.json`)
  - `subspace_cooldowns.json` sigue en raiz (OK), pero queda inconsistente con el resto de state.

### Skill references legacy paths
- `.agents/skills/iteration-audit/SKILL.md` lista como gobernanza:
  - `00_project_context.md`, `01_agent_analyst.md`, etc (ahora estan en `spec/` y `agents/`).
  - `current_baseline.json`, `research_state.json` (ahora se pretende `state/*`).

## 11. Riesgos detectados

Criticos:
- El loop/runners fallaran o leeran state equivocado por paths legacy (baseline/trackers/scripts/logs/memories/runs).
- Schema/contract no restringe `recommended_next_action`, debilitando enforcement automatico.

Medios:
- Doble estado (`research_state.json` legacy en raiz vs `state/research_state.json`) puede crear divergencia.
- Skills y docs aun refieren a paths viejos, riesgo de auditorias incompletas o confusion operativa.

Menores:
- Data/CSVs muy grandes en raiz: desorden operativo y riesgo de IO accidental.
- `__pycache__/` en raiz: ruido (recomendable `.gitignore`).

## 12. Recomendaciones

Hacer antes de correr de nuevo:
- Definir un plan de compatibilidad de paths: o actualizar runners/scripts a nuevos paths, o crear stubs/wrappers de compatibilidad (sin cambiar logica de trading).
- Alinear fuente de verdad del state: decidir si `state/research_state.json` reemplaza `research_state.json` legacy o si es solo espejo (y asegurar que el runtime lea una sola).
- Endurecer `contracts/coordinator_output.schema.json` para que `recommended_next_action` sea enum (y alinear validator si corresponde).

Hacer despues:
- Migrar gradualmente el resto de artefactos de raiz (`run_analysis_current.*`, scripts/ps1) a estructura nueva y actualizar referencias.
- Actualizar `.agents/skills/iteration-audit/SKILL.md` para apuntar a las rutas nuevas (sin cambiar la regla de no-modificacion de codigo).

Opcional:
- Crear `contracts/analyst_output.schema.json` y `contracts/executor_output.schema.json` para gobernanza completa del pipeline.

## 13. Veredicto final

**corregir_antes_de_correr**

