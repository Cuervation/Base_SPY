# Multi-window Single-run + Dataset Cache Implementation

## Cambios incluidos

1. `run_multi_agent_iteration.py`
   - `strict_progressive_windows` ya no desactiva `window_reuse_enabled`.
   - Cuando las ventanas solicitadas incluyen `52`, el runner ejecuta primero la ventana mayor (`52`) y deriva `24`, `8` y `4` desde los artefactos de esa corrida.
   - Se genera `multi_window_derived_metrics.json` en el run dir.
   - Las ventanas derivadas generan `window_XX/window_result.json` para mantener trazabilidad.
   - El `executor_output.json` ahora marca `multi_window_single_run=true` cuando aplica.
   - El `perf_summary` registra `derived_windows`.
   - Los scripts de ventana reciben un prelude best-effort para cachear lecturas CSV grandes en Parquet.

2. `config/dataset_cache_config.json`
   - Configuración del cache persistente en disco.
   - Cache por defecto en `_dataset_cache/prepared`.
   - Formato objetivo: Parquet.

3. `scripts/cache/dataset_cache.py`
   - Helper que monkey-patchea `pandas.read_csv` dentro de los scripts de ventana.
   - Si el CSV grande ya fue cacheado y el archivo fuente no cambió, lee Parquet.
   - Si falla el cache o falta motor Parquet, vuelve automáticamente al CSV original.

4. `scripts/cache/build_dataset_cache.py`
   - Script opcional para precalentar cache.

5. `validators/validate_dataset_cache.py`
   - Valida manifest y archivos cacheados.

## Impacto esperado

- La mejora fuerte viene de ejecutar solo `52` y derivar `24/8/4`.
- En base a la comparación previa con EXP_162, el ahorro esperado es de aproximadamente 30% a 45% por iteración.
- El cache Parquet agrega una mejora adicional si los CSV grandes se leen repetidamente entre iteraciones.

## Cómo probar

Primero compilar:

```powershell
python -m py_compile run_multi_agent_iteration.py scripts\cache\dataset_cache.py scripts\cache\build_dataset_cache.py validators\validate_dataset_cache.py
```

Después correr una sola iteración:

```powershell
python scripts\loop\run_infinite_research_loop.py --repo . --windows 4,8,24,52 --max-iterations 1
```

En `run_live_status.log` deberías ver:

```text
EXECUTOR multi_window_single_run enabled=1 source_window=52 derive_windows=[4, 8, 24]
EXECUTOR window_derived weeks=24 from_window=52
EXECUTOR window_derived weeks=8 from_window=52
EXECUTOR window_derived weeks=4 from_window=52
```

También debería existir:

```text
runs/multi_agent_runs/<RUN_ID>/multi_window_derived_metrics.json
```

## Cómo desactivar

Para volver al comportamiento anterior:

```powershell
python scripts\loop\run_infinite_research_loop.py --repo . --windows 4,8,24,52 --max-iterations 1 --disable-window-reuse
```

También se puede desactivar el cache en:

```text
config/dataset_cache_config.json
```

poniendo:

```json
"enabled": false
```

## Riesgos

- Si alguna ventana recalculara señales de forma distinta según `TEST_START`, la derivación desde `52` podría no ser equivalente. En EXP_162 ya se verificó que las métricas de `24/8/4` matchean recortando desde `52`.
- El cache Parquet depende de tener un motor compatible instalado (`pyarrow` o `fastparquet`). Si no existe, el helper vuelve al CSV original sin romper.

## Qué no se tocó

- Estrategia.
- Baseline.
- Política de promoción.
- 156.
- Criterios del coordinator.
