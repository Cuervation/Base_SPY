# Performance Safe Optimization Report

## 1. Executive Summary

Se aplicaron dos mejoras seguras para bajar tiempo por iteración sin cambiar lógica de trading, parámetros, baseline, ventanas, criterios de coordinator ni política de promoción.

Cambios principales:
- El tracker XLSX deja de regenerarse por defecto dentro del loop caliente.
- Los artefactos XLSX de ventana quedan desactivados por defecto; el flujo usa CSV/fast artifacts salvo flag explícito.
- Se cachea el cálculo de fechas de inicio por ventana dentro del proceso.
- El extractor de métricas reduce lecturas de CSV y cachea en disco el subset SPY del weekly master.

No se tocaron:
- Estrategia.
- `state/current_baseline.json`.
- Políticas de 156.
- Parent validation.
- Follow-up / promotion.

## 2. Archivos modificados

| Archivo | Cambio | Motivo |
|---|---|---|
| `run_multi_agent_iteration.py` | Agregado `cfg_bool` | Leer flags booleanos desde config de forma segura. |
| `run_multi_agent_iteration.py` | Agregado cache `_SPY_WEEK_START_RESULT_CACHE` | Evitar recalcular `compute_last_n_weeks_start_date` con mismos parámetros en la misma corrida. |
| `run_multi_agent_iteration.py` | `append_master_tracker(..., refresh_xlsx=False)` | Mantener append CSV pero no regenerar XLSX salvo habilitación explícita. |
| `run_multi_agent_iteration.py` | Flags `--enable-tracker-xlsx-refresh` y `--enable-window-xlsx-artifacts` | Permitir Excel solo cuando se pida explícitamente. |
| `run_multi_agent_iteration.py` | `allow_xlsx` depende de `window_xlsx_artifacts_enabled` | Sacar artefactos XLSX de ventana del hot path. |
| `scripts/metrics/extract_backtest_metrics.py` | `usecols` por tipo de CSV | Leer solo columnas necesarias para summary/weekly/trades. |
| `scripts/metrics/extract_backtest_metrics.py` | Cache SPY returns en `_dataset_cache/metrics/` | Evitar reescanear el weekly master completo por cada ventana. |

## 3. Nueva política de Excel

Durante el loop autónomo, por defecto:
- se sigue actualizando el CSV maestro;
- no se regenera `agent_live_runs_master.xlsx`;
- no se exportan XLSX por ventana;
- se usan CSV artifacts / fast artifacts.

Para regenerar XLSX de tracker en una corrida puntual:

```powershell
python run_multi_agent_iteration.py ... --enable-tracker-xlsx-refresh
```

Para habilitar XLSX de ventana en una corrida puntual:

```powershell
python run_multi_agent_iteration.py ... --enable-window-xlsx-artifacts
```

## 4. Cache / reducción de CSV

Se agregaron dos niveles de reducción de I/O:

1. `compute_last_n_weeks_start_date` cachea por:
   - archivo weekly,
   - mtime/tamaño,
   - fecha de fin,
   - ventana,
   - política de next week.

2. `extract_backtest_metrics.py` crea un cache chico con columnas SPY:
   - `signal_date`
   - `ret_1w_pct`

Ruta del cache:

```txt
_dataset_cache/metrics/spy_weekly_returns_<hash>.csv
```

## 5. Validaciones realizadas

```powershell
python -S -m py_compile run_multi_agent_iteration.py scripts/metrics/extract_backtest_metrics.py
```

Resultado: OK.

No se corrieron backtests ni loop infinito.

## 6. Riesgos pendientes

### Bajos
- Si algún flujo externo dependía de XLSX actualizado en cada corrida, ahora deberá pedirlo con flag o regenerarlo manualmente.

### Medios
- La primera corrida después del cambio puede tardar parecido si todavía no existe cache SPY; las siguientes deberían leer el cache pequeño.

### No tocado a propósito
- Paralelización de ventanas.
- Early stop.
- Lógica de trading.
- Política de 156.

## 7. Próximo paso recomendado

Probar una sola iteración:

```powershell
python scripts\loop\run_infinite_research_loop.py --repo . --windows 4,8,24,52 --max-iterations 1
```

Si pasa, probar 5 iteraciones:

```powershell
python scripts\loop\run_infinite_research_loop.py --repo . --windows 4,8,24,52 --max-iterations 5
```

Revisar en el log que aparezca:

```txt
tracker_xlsx=0
window_xlsx=0
```
