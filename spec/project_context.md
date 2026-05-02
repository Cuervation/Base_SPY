# 00 Project Context

## Objetivo
Optimizar estrategia SPY con flujo multiagente acumulativo, causal, auditable y con aprendizaje útil.

## Principio central
El objetivo NO es solo correr experimentos.
El objetivo es:
- mejorar la estrategia
- preservar continuidad útil
- maximizar aprendizaje real
- evitar loops que consumen corridas sin dejar evidencia nueva

## Aprendizajes válidos (conservados)
- El cuello principal está en entrada, gates y calidad del basket; no en salida.
- El ladder actual no parece ser el cuello de botella.
- `avg_profile_distance` importa, según `PROFILE_MODE`.
- No conviene relajar demasiado `MIN_SPY_CHANNEL_R2`.
- Top 3 suele ser más sano que top 5.
- Comparar siempre contra SPY año por año.
- Robustez 24/52 pesa más que brillo 4/8.
- La semana sola no siempre alcanza: también importa la calidad individual del candidato.
- La validación larga (`156`) es valiosa, pero no debe destruir evidencia útil de `52` si la profundidad real no alcanza.
- Una corrida puede ser muy útil para follow-up aunque no sea baseline.

## Regla de evidencia
- 4 semanas: débil
- 8 semanas: exploratoria/media
- 24 semanas: alta
- 52 semanas: muy alta
- 156 semanas: multi-year real, solo si existe profundidad real suficiente

## Regla de trades
- empate: `0% <= net_return_pct <= 1%`
- ganador: `>1%`
- perdedor: `<0%`

## Arquitectura
1. Analyst diagnostica la última corrida útil y propone 1 cambio principal (+1 dependiente solo si hace falta).
2. Coordinator valida materialidad, duplicados, zig-zag reales y consistencia de estado.
3. Coder implementa sobre parent técnico (último script ejecutado con éxito).
4. Executor corre ventanas reales y progresivas: `4 -> 8 -> 24 -> 52 -> 156`.
5. Coordinator clasifica resultado:
   - `rejected`
   - `accepted_for_followup`
   - `promoted_to_baseline`
6. Coordinator además evalúa estilo auditor v2:
   - `process_reliability_score`
   - `analyst_quality_score`
   - `coordinator_quality_score`
   - `research_effectiveness_score`
   - `overall_agent_score`
7. Se registra todo en trackers acumulativos.

## Regla sobre profundidad real
Si `156` no tiene profundidad suficiente:
- marcar `insufficient_depth`
- preservar la mejor evidencia válida alcanzada
- no tratarlo automáticamente como run_error fatal
- no promover multi_year si no hay profundidad real
- pero tampoco tirar una corrida sana de 4/8/24/52

## Regla de continuidad
No confundir:
- última corrida útil para seguir investigando
con
- último baseline realmente promovido

Ambas cosas deben persistirse por separado.

## Regla de calidad de research
Una corrida valiosa puede:
- mejorar métricas
- confirmar una hipótesis
- descartar una hipótesis
- o revelar un cuello de botella de proceso

No todo valor pasa por promoción a baseline.

## Regla de cambio
- no más de 1 cambio principal por iteración
- cambio dependiente solo si hay dependencia semántica o de escala
- preferir cambios simples y causales
- evitar cambios grandes o mezclados
- no rehacer toda la estrategia si todavía hay refinements razonables

## Qué consideramos mal funcionamiento del loop
- resets tontos a `initial_test_queue`
- duplicados mal clasificados como zig-zag
- `insufficient_depth` tratado como fatal
- ramas que se estancan en `no_material_candidate_found`
- corridas que no dejan evidencia nueva
- promotion demasiado fácil
- rechazo de corridas útiles solo por formalismos

## Meta operativa
Subir:
- `research_effectiveness_score`
sin romper:
- `process_reliability_score`
