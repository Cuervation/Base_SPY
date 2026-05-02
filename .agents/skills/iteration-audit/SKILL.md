---
name: iteration-audit
description: Auditá las últimas iteraciones del proyecto multiagente SPY, resumí qué mejoró y qué empeoró, calculá una evaluación estilo auditor v2, detectá fricciones del loop y proponé direcciones de cambio sin modificar código.
---

# Iteration Audit Skill

## Cuándo usar esta skill
Usá esta skill cuando el usuario quiera:
- revisar las últimas N iteraciones/corridas
- entender qué mejoró y qué empeoró
- detectar si el analyst, coordinator o el proceso están frenando el aprendizaje
- obtener una evaluación tipo auditor v2
- generar un reporte de resultados sin cambiar código

No uses esta skill para:
- implementar cambios
- tocar lógica de estrategia
- refactorizar runners
- modificar archivos del repo
- ejecutar fixes automáticamente

Tu trabajo acá es **solo análisis y síntesis**.

---

## Contexto del proyecto
Este repo usa un flujo multiagente para optimizar una estrategia SPY.

Roles esperados:
- `analyst`
- `coder`
- `executor`
- `coordinator`

La gobernanza del proyecto está en:
- `AGENTS.md`
- `spec/project_context.md`
- `agents/analyst.md`
- `agents/coder.md`
- `agents/executor.md`
- `agents/coordinator.md`
- `state/current_baseline.json`
- `state/research_state.json`

Antes de analizar corridas, leé esos archivos si existen.

---

## Reglas del proyecto que debés respetar
- trade con `net_return_pct > 1%` = ganador
- trade con `0% <= net_return_pct <= 1%` = empate
- trade con `net_return_pct < 0%` = perdedor
- robustez en `24/52` vale más que brillo en `4/8`
- comparación contra SPY es obligatoria
- `156` solo vale como multi-year real si hay profundidad real suficiente
- `insufficient_depth` no debe interpretarse automáticamente como fracaso total si `52` fue válida
- una corrida puede ser útil para follow-up aunque no sea baseline

---

## Qué archivos buscar
Para cada corrida, buscá preferentemente:
- `analyst_output.json`
- `executor_output.json`
- `coordinator_output.json`
- `experiment_manifest.json`
- `run_live_status.log`

Y si existen trackers acumulativos, dales prioridad para cubrir muchas corridas rápido:
- `trackers/experiment_log.csv`
- `trackers/agent_live_runs_master.csv`
- `run_summary_v2.csv`
- `leaderboard_v2.csv`
- `findings_v2.md`
- `score_reasons_v2.json`

---

## Alcance por defecto
Si el usuario no especifica otra cosa, auditá:
- las últimas `15` corridas (priorizando útiles cuando estén identificadas)

Si hay menos de 15, usá todas las disponibles.

---

## Qué tenés que analizar

### 1. Executive summary
Respondé:
- qué pasó en el bloque analizado
- si hubo progreso real o solo movimiento administrativo
- si la rama está viva, ruidosa, estancada o bloqueada por proceso

### 2. Tabla de corridas
Para cada iteración, intentá devolver:
- `run_id`
- `parent_run_id`
- cambio principal
- `decision_type`
- `accepted_for_followup`
- `promoted_to_baseline`
- `w24_spy_compare`
- `w52_spy_compare`
- status de `156`
- `research_value` estimado
- `branch_health` estimado

Si falta algún campo, indicá `n/a`.

### 3. Mejores corridas
Elegí las 3 a 5 mejores según:
- robustez 52w
- compare vs SPY
- valor de aprendizaje
- utilidad para follow-up o baseline

### 4. Peores corridas
Elegí las 3 a 5 peores según:
- fricción de proceso
- falta de evidencia nueva
- caída clara de calidad
- bloqueo inútil del loop

### 5. Qué aprendió el sistema
Identificá:
- señales de estrategia
- señales de basket/ranking
- señales de gates/filtros
- señales de proceso/gobernanza

### 6. Qué no está funcionando
Detectá:
- `blocked_duplicate`
- `blocked_zigzag`
- resets a initial queue
- `insufficient_depth`
- validación larga no real
- loops sin evidencia nueva
- sobreconcentración en pocos parámetros
- promotion demasiado fácil o rechazo demasiado duro

---

## Evaluación tipo auditor v2
Estimá siempre estos scores en escala 0-100:

- `process_reliability_score`
- `analyst_quality_score`
- `coordinator_quality_score`
- `research_effectiveness_score`
- `overall_agent_score`

### Cómo pensar los scores

#### process_reliability_score
Mide:
- consistencia del loop
- continuidad de estado
- profundidad real de ventanas
- ausencia de bloqueos tontos
- buen manejo de `156`

#### analyst_quality_score
Mide:
- calidad del diagnóstico
- causalidad de los cambios propuestos
- si entiende semana / basket / candidato individual
- si evita cambios mecánicos o repetitivos

#### coordinator_quality_score
Mide:
- si separa bien follow-up de baseline
- si bloquea bien duplicados vs zig-zag
- si conserva evidencia útil
- si orienta bien la rama

#### research_effectiveness_score
Mide:
- si las corridas dejaron aprendizaje útil
- si mejoran vs parent
- si mejoran vs SPY
- si el sistema convierte análisis en evidencia
- si la rama progresa o solo gira

#### overall_agent_score
Combiná las 4 anteriores con criterio razonable.
No hace falta fórmula fija si no existe una en el repo, pero sé consistente.

---

## Diagnóstico de rama
Estimá también:

- `research_value`: `high | medium | low | none`
- `branch_health`: `alive_and_improving | alive_but_noisy | stagnating | blocked_by_process | exhausted`
- `learning_signal`: `strong | medium | weak | absent`
- `stagnation_risk`: `low | medium | high`
- `main_friction`: `analyst | coordinator | long_window_depth | state_handling | candidate_generation | branch_stagnation | none`

Y elegí exactamente una:
- `refine_current_branch`
- `controlled_exploration`
- `evidence_based_rollback`
- `extend_validation`
- `stop_branch`
- `fix_process_before_more_research`

---

## Regla especial de dirección de cambio
Además del análisis, dejá:
- `recommended_change_directions`

Máximo 3 direcciones.
No propongas código exacto.
No implementes.
Solo direcciones de alto valor.

Ejemplos válidos:
- `hold_top_candidates_anchor_at_3`
- `short_monotonic_grid_on_max_avg_profile_distance`
- `extend_multi_year_validation`
- `fix_duplicate_blocking_policy`
- `diagnose_yearly_breakdown_vs_spy`
- `open_orthogonal_exploration_on_profile_mode`
- `reduce_parameter_whipsaw`

---

## Reglas de output
Tu salida debe ser clara y autocontenida.

Si el usuario pide un archivo, generá un markdown tipo:
- `iteration_review_last_15.md`

Estructura recomendada:
1. Executive summary
2. Qué cambió en estas iteraciones
3. Tabla de corridas
4. Mejores corridas
5. Peores corridas
6. Qué aprendió el sistema
7. Qué no está funcionando
8. Evaluación tipo auditor v2
9. Próximos cambios recomendados
10. Riesgos de seguir como está

Si el usuario no pide archivo, igual devolvé ese esquema en el chat.

---

## Límites
- no modificar código
- no tocar runners
- no actualizar baseline
- no cambiar `state/research_state.json`
- no disparar nuevas corridas
- no hacer fixes
- no inventar datos que no estén en los artefactos

Si falta información, decilo explícitamente.

---

## Heurísticas prácticas
- si `w52` mejora fuerte, eso pesa mucho más que un brillo corto en `4/8`
- si `156` no es real, no la trates como validación fuerte
- si hay muchas corridas bloqueadas por duplicado o zig-zag, eso es fricción de proceso
- si hay muchas corridas accepted_for_followup sin converger, puede haber estancamiento o ruido
- si el mismo parámetro va y vuelve muchas veces, detectá branch whipsaw
- distinguí progreso real de simple actividad

---

## Regla final
Tu misión no es decir “qué corrida ganó”.
Tu misión es decir:
- qué aprendió el sistema
- qué lo está frenando
- y qué dirección tiene más valor ahora
sin tocar nada del repo.
