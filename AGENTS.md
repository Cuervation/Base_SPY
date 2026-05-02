# AGENTS

Arquitectura multiagente limpia, acumulativa, causal y auditable para optimizar la estrategia SPY.

## Roles obligatorios

- `analyst`:
  analiza siempre la última corrida útil, entiende qué falló, propone 1 cambio principal (+1 dependiente solo si hay dependencia semántica/escala) y usa feedback del coordinator/auditor v2.

- `coder`:
  implementa exactamente sobre el último script ejecutado con éxito (`parent tecnico`).
  Nunca usa `baseline_human_stable` como parent técnico.
  No opina de estrategia.

- `executor`:
  solo ejecuta el script recibido, no toca código, devuelve métricas estándar y valida profundidad real en las ventanas operativas pedidas. Por default usa `4/8/24/52`; `156` queda reservado para validación multi-year condicional.

- `coordinator`:
  orquesta, valida dependencias, bloquea no-op/duplicados/zig-zag reales, compara contra última corrida útil y baseline promovido, separa follow-up de baseline, y además evalúa la calidad del aprendizaje como auditor v2.

---

## Principio central

El objetivo NO es solo correr experimentos.
El objetivo es maximizar aprendizaje útil y mejoras robustas.

Por eso, además de decidir si una corrida sigue o no, el sistema debe evaluar:
- si dejó evidencia útil
- si la rama sigue viva o está estancada
- si conviene refinar, explorar, rollback, extender validación o arreglar proceso antes de seguir

---

## Baseline limpio inicial

Archivo: `current_baseline.json`

Configuración base:
- `STRATEGY_FAMILY = "profile_match"`
- `PROFILE_MODE = "p25_p75"`
- `ENABLE_SPY_CHANNEL_R2_GATE = True`
- `MIN_SPY_CHANNEL_R2 = 0.55`
- `ENABLE_AVG_PROFILE_DISTANCE_GATE = True`
- `MAX_AVG_PROFILE_DISTANCE = 0.20`
- `ENABLE_CLOSE_VS_SMA50_FILTER = False`
- `MAX_CLOSE_VS_SMA50_PCT = 1.5`
- `TOP_CANDIDATES_NEXT_WEEK = 5`

Regla de trades:
- empate: `0% <= net_return_pct <= 1%`
- ganador: `> 1%`
- perdedor: `< 0%`

---

## Reglas operativas

1. No más de 1 cambio principal por iteración.
2. Cambio dependiente solo si el principal cambia semántica/escala.
3. Preflight obligatorio antes de ejecutar.
4. Bloqueo de tests no operativos.
5. Bloqueo de duplicados reales y zig-zag reales.
6. No bloquear refinements monotónicos razonables.
7. Comparación obligatoria contra SPY en las ventanas operativas pedidas. El default operativo es `4/8/24/52`.
8. Robustez en `24/52` pesa más que brillo en `4/8`.
9. `156` se usa como validación multi-year real solo si se pide explícitamente o si la política `long156` lo habilita, y solo cuando exista profundidad real suficiente.
10. `insufficient_depth` NO debe destruir automáticamente una corrida útil de `4/8/24/52`.
11. El coordinator puede fijar `branch_anchor` por 3 iteraciones cuando haya señal fuerte (promoción, follow-up con mejora clara vs SPY o repetición útil reciente).
12. Si `blocked_duplicate >= 20%` en las últimas 15 corridas, priorizar `fix_process_before_more_research`.

---

## Clasificación de transiciones

El coordinator debe clasificar cada propuesta como una de estas:

- `no_op_equivalence`
- `duplicate_recent_proposal`
- `fresh_change`
- `monotonic_refinement`
- `controlled_exploration`
- `evidence_based_rollback`
- `true_zigzag_reversal`

### Regla crítica
- `duplicate_recent_proposal` NO es zig-zag.
- solo `true_zigzag_reversal` se bloquea automáticamente por reversión real

### Branch Anchor
- Si se activa `branch_anchor`, se congela temporalmente el parámetro anclado durante `anchor_hold_iterations`.
- Durante el anclaje se bloquean reversas inmediatas salvo `evidence_based_rollback` explícito.
- El anchor activo persistido en `current_baseline.json` / `research_state.json` manda.
- Ejemplo histórico (no hardcoded): se usó `TOP_CANDIDATES_NEXT_WEEK=3` por 3 iteraciones en una rama previa.

### 52 Bueno / Yearly Flojo
- Si hay mejora clara en `52w` vs SPY pero no hay promoción por `yearly_vs_spy` o profundidad multi-year:
  - usar `accepted_for_followup = true`
  - usar `promoted_to_baseline = false`
  - usar `recommended_next_action = extend_validation`

---

## Política de ventanas

El executor usa por default:

`[4, 8, 24, 52]`

Función:
- `4`: smoke test rápido
- `8`: señal inicial
- `24`: primer filtro serio
- `52`: robustez anual
- `156`: robustez multi-year real opcional/condicional, solo si fue pedido explícitamente o habilitado por la política `long156`

### Reglas de profundidad
- si `156` no tiene profundidad real suficiente:
  - usar `status = insufficient_depth`
  - informar `requested_weeks` y `actual_weeks_run`
  - no tratarlo como error técnico fatal por defecto
  - no invalidar automáticamente una corrida útil de `52`
  - preservar la evidencia válida de `52`

---

## Estado persistido y decisiones

Hay que separar explícitamente:

### A. `accepted_for_followup`
La corrida:
- dejó información útil
- merece extensión o siguiente experimento
- aunque no alcance para baseline

### B. `promoted_to_baseline`
La corrida:
- mejora robustez real contra parent
- no depende de brillo corto
- mejora o sostiene comparación contra SPY
- no degrada claramente edge promedio
- pasa validación suficiente para promoción

### Regla importante
No confundir:
- última corrida útil para seguir investigando
con
- último baseline realmente promovido

---

## Evaluación tipo auditor v2

El coordinator, además de coordinar, debe producir una evaluación tipo auditor v2 con:

- `process_reliability_score`
- `analyst_quality_score`
- `coordinator_quality_score`
- `research_effectiveness_score`
- `overall_agent_score`

Y además:
- `research_value`
- `branch_health`
- `learning_signal`
- `stagnation_risk`
- `main_friction`
- `recommended_next_action`
- `recommended_change_directions`

---

## Qué significa buen funcionamiento del loop

Un loop sano:
- no se rompe por falta de profundidad
- no reinicia ramas útiles innecesariamente
- no promueve baseline demasiado fácil
- no mata ramas vivas por formalismos
- no se estanca en `no_material_candidate_found`
- convierte análisis en tests útiles
- convierte tests útiles en aprendizaje real

---

## Tests iniciales preparados

Archivo: `analyst_initial_tests_queue.json`

- `TEST_A`: activar filtro SMA50 + umbral `0.5`
- `TEST_B`: `PROFILE_MODE = zscore_distance` + ajuste dependiente para test válido

### Regla
Los tests con `status = completed` no deben volver a lanzarse salvo retry explícito y justificado.

---

## Artefactos por corrida

Carpeta: `multi_agent_runs\EXP_XXX_...`

- `analyst_output.json`
- `change_set.json`
- `preflight_output.json`
- `coder_output.json`
- `executor_output.json`
- `coordinator_output.json`
- `experiment_manifest.json`
- `candidate_config.json`
- `run_live_status.log`
- script candidato ejecutado
- logs/stdout/stderr por ventana operativa ejecutada; default `4/8/24/52`, con `156` solo si fue pedido explícitamente o habilitado por política `long156`

Trackers acumulativos recomendados:
- `experiment_log.csv`
- `agent_live_runs_master.csv`
- `agent_live_runs_master.xlsx`
- `findings_v2.md`
- `leaderboard_v2.csv`
- `run_summary_v2.csv`
- `score_reasons_v2.json`

---

## Criterio de equilibrio real

El loop usa fases:

### Fase `year1`
Prioridad inicial:
- superar SPY en `52` semanas
- demostrar utilidad de research real

### Fase `multi_year`
Después:
- sostener `52w`
- validar multi-año con `156` semanas reales cuando haya profundidad suficiente y la política lo habilite
- revisar `spy_yearly_breakdown`

### Regla
Una corrida puede ser muy valiosa para research sin ser baseline.

---

## Regla final del sistema

La misión del sistema no es solo “correr mucho”.
La misión es:

- aprender
- refinar
- evitar ruido
- preservar continuidad útil
- y encontrar mejoras robustas contra SPY.
