# Performance Bottleneck Report

Fecha: 2026-04-26

## Resumen ejecutivo

El tiempo por iteracion del loop autonomo SPY se consume casi por completo en la ejecucion secuencial de ventanas de backtest, especialmente `24` y `52`. El resto del costo viene de relecturas repetidas de CSV grandes, arranque de subprocesos por ventana, y escritura pesada de trackers en Excel.

No hay evidencia de que `scripts/loop/run_infinite_research_loop.py` sea el cuello principal; es orquestacion. El costo fuerte esta en `run_multi_agent_iteration.py` y en los scripts que ese archivo invoca para extraer metricas y actualizar artefactos.

## Ranking de cuellos de botella probables

### 1) Backtests por ventana ejecutados en serie

**Impacto:** alto  
**Archivos involucrados:**
- `run_multi_agent_iteration.py:4706-4804`
- `run_multi_agent_iteration.py:8403-8506`
- `run_multi_agent_iteration.py:8521-8575`
- `run_multi_agent_iteration.py:8654-8655`

**Por que es el principal cuello:**
- Cada ventana se ejecuta con `subprocess.Popen(...)` en un proceso Python separado.
- El loop espera a que termine una ventana antes de arrancar la siguiente.
- Las ventanas `4/8/24/52` no corren en paralelo.
- Las trazas recientes muestran duraciones crecientes por ventana, con `24` muy por encima de `4` y `8`, y `52` como la mas cara.

**Evidencia de codigo:**
- `run_window_backtest()` crea un script parcheado por ventana y lanza un proceso nuevo.
- `_run_window()` llama una vez por ventana.
- `execution_order` sigue siendo secuencial.

### 2) Relectura de datos grandes y recalculo por proceso

**Impacto:** alto  
**Archivos involucrados:**
- `run_multi_agent_iteration.py:688-730`
- `run_multi_agent_iteration.py:4658-4703`
- `scripts/metrics/extract_backtest_metrics.py:32-163`

**Por que pesa mucho:**
- `compute_last_n_weeks_start_date()` lee el CSV semanal en chunks para calcular el inicio dinamico.
- `extract_backtest_metrics.py` vuelve a leer CSV/Excel para extraer resultados y calcular comparaciones contra SPY.
- Aunque hay cache en memoria para el indice semanal, esa cache solo ayuda dentro del mismo proceso; no sobrevive entre corridas separadas.
- Cada ventana arranca en un proceso nuevo, asi que parte del parsing se repite.

**Señal importante:**
- El extractor usa `pd.read_csv(..., chunksize=200000)` sobre el CSV semanal.
- Si hay XLSX, tambien puede leerlo con `pd.read_excel(...)`.

### 3) Escritura y refresco pesado de tracker en Excel

**Impacto:** medio  
**Archivos involucrados:**
- `run_multi_agent_iteration.py:6294-6396`
- `run_multi_agent_iteration.py:9056-9066`

**Por que importa:**
- Cada corrida agrega una fila al CSV maestro.
- En cadencia, el codigo relee todo el CSV maestro con `pd.read_csv(...)` y lo reescribe completo a XLSX con `df.to_excel(...)`.
- Eso no ocurre en cada ventana, pero cuando cae en la iteracion que toca, introduce un pico de costo innecesario.

**Lectura clave:**
- El costo no esta en append al CSV, sino en la regeneracion completa del XLSX.

### 4) Preflight validator invocado como proceso aparte

**Impacto:** bajo a medio  
**Archivos involucrados:**
- `run_multi_agent_iteration.py:4585-4593`
- `preflight_validator.ps1:1-207`

**Por que suma:**
- Se lanza como subproceso PowerShell.
- La logica interna es liviana; el costo probable es el arranque del proceso y la I/O de JSON.
- No parece el principal consumidor de tiempo, pero es un overhead fijo por iteracion.

### 5) Supervisor y estado live/final

**Impacto:** bajo  
**Archivos involucrados:**
- `scripts/loop/run_infinite_research_loop.py:242-262`
- `scripts/loop/run_infinite_research_loop.py:363-437`
- `scripts/loop/run_infinite_research_loop.py:499-550`
- `scripts/loop/run_infinite_research_loop.py:1000-1049`

**Por que no es el gran problema:**
- Lee JSON y CSV de estado, decide parent y escribe summaries.
- Es costeo de orquestacion, no de computo numerico.
- Puede fallar logicamente, pero no explica por si solo las demoras largas por iteracion.

## Scripts de backtest y analisis revisados

- `run_multi_agent_iteration.py`
- `scripts/metrics/extract_backtest_metrics.py`
- `scripts/reports/generate_run_analysis.py`
- `preflight_validator.ps1`

`scripts/reports/generate_run_analysis.py` es pesado cuando se ejecuta porque vuelve a cargar CSV/Excel y genera reportes completos, pero no parece estar en la ruta critica de cada ventana. Es mas bien un consumidor de tiempo de post-procesamiento manual o programado.

## Optimizaciones seguras

### 1) Reusar cache de fechas/indice semanal dentro de la misma iteracion

**Impacto esperado:** alto  
**Riesgo:** bajo  
**Idea:**
- Extender el cache ya existente en `compute_last_n_weeks_start_date()` para cubrir mas consultas dentro de la misma corrida.
- Evitar recalcular el corte temporal para cada ventana si el dataset y la fecha de fin son los mismos.

### 2) Deferir el refresco XLSX fuera del hot path

**Impacto esperado:** medio  
**Riesgo:** bajo a medio  
**Idea:**
- Mantener el CSV maestro en linea durante la iteracion.
- Mover la regeneracion completa del XLSX a un job aparte, o subir la cadencia.

### 3) Reducir relecturas del CSV semanal para extraccion de metricas

**Impacto esperado:** alto  
**Riesgo:** bajo  
**Idea:**
- Preindexar el weekly CSV una vez por proceso.
- Reusar el subset SPY ya filtrado para todas las ventanas del mismo run.

### 4) Cargar solo columnas necesarias en postprocesamiento

**Impacto esperado:** medio  
**Riesgo:** bajo  
**Idea:**
- En scripts de extraccion y analisis, usar `usecols` agresivo donde sea posible.
- Evitar `read_excel` salvo que sea realmente necesario.

### 5) Separar analisis pesado del loop activo

**Impacto esperado:** medio  
**Riesgo:** bajo  
**Idea:**
- Dejar `generate_run_analysis.py` como paso manual o diferido.
- No ejecutarlo dentro de la ruta critica del loop autonomo.

## Optimizaciones riesgosas

### 1) Paralelizar `4/8/24/52` sin rediseñar el flujo

**Impacto potencial:** alto  
**Riesgo:** alto  
**Motivo:**
- Hoy el flujo asume orden secuencial, parent context y checkpoints por ventana.
- Paralelizar puede romper trazabilidad, saturar I/O y complicar la reconstruccion de artefactos.

### 2) Reusar artefactos de una ventana para inferir otra sin validacion fuerte

**Impacto potencial:** alto  
**Riesgo:** medio a alto  
**Motivo:**
- Puede acelerar, pero reduce independencia de evidencia.
- Es facil terminar con resultados rapidos pero menos auditablemente validos.

### 3) Eliminar preflight o summaries para ganar tiempo

**Impacto potencial:** bajo a medio  
**Riesgo:** alto  
**Motivo:**
- Quitaria guardrails utiles y hace mas dificil detectar estados invalidos o contaminados.

## Cambios recomendados en orden

1. Cachear y reusar lectura/filtrado de `weekly_csv` dentro de `run_multi_agent_iteration.py`.
2. Evitar regenerar XLSX completo en cada cadencia baja; moverlo fuera del loop caliente o subir la cadencia.
3. Reducir el costo del extractor de metricas, idealmente reusando datos ya cargados en memoria o en cache local.
4. Mantener `preflight_validator.ps1` como guardrail, pero evitar invocarlo mas de lo necesario.
5. Revaluar paralelismo solo si la traza demuestra que la serializacion sigue siendo el mayor freno despues de cachear lecturas.

## Que no tocar

- Logica de trading.
- Baseline limpio en `state/current_baseline.json`.
- Politica de `156`.
- Validaciones de parent, no-op, dependencia y ventana.
- Semantica de promotion / follow-up.
- Orden causal de los artefactos.
- Criterios de auditoria del coordinator.

## Estimacion cualitativa de impacto

- Backtests secuenciales por ventana: **alto**
- Parsing/relectura de CSV grandes: **alto**
- Refresco completo de Excel: **medio**
- Preflight en PowerShell: **bajo a medio**
- Orquestacion del supervisor: **bajo**

## Conclusión

Si el objetivo es bajar tiempo por iteracion sin cambiar estrategia, el mejor retorno esta en:

1. reducir I/O repetida,
2. cachear lecturas dentro de la corrida,
3. sacar XLSX del camino caliente,
4. y solo despues pensar en paralelismo.

El cuello real no parece estar en la logica del loop autonomo, sino en como se materializa cada ventana y como se re-leen los artefactos alrededor de ella.
