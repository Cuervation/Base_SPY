# controlled-exploration

## Objetivo

Generar hipótesis nuevas cuando capa normal y fallback no encuentran candidatos materiales, sin repetir ejes negativos ni duplicados.

## Regla: features derivadas disponibles

Controlled exploration puede proponer variables nuevas aunque no estén materializadas en el weekly master si se derivan de OHLCV semanal.

Variables derivables en runtime:

- `close_vs_sma8w_pct`
- `atr_14w_pct`
- `volume_ratio_vs_sma13w`
- `dist_to_high_26w_pct`

No bloquear estas variables solo porque falten como columna física. El backtest generado debe crearlas desde:

- `ticker`
- `signal_date`
- `close`
- `high`
- `low`
- `volume`

Si falta una columna fuente, se crea la feature como `NaN` y se registra como degradación de señal, no como crash del loop.

## Reglas de seguridad

- No repetir candidatos exactos.
- No repetir parámetro + dirección con historial negativo.
- No usar falta de 156 como blocker si 156 está prohibido por config.
- No promover baseline si empeora `spy_compare_52` contra parent.

---

## PROFILE_MODE dependency rule

When controlled exploration proposes changing `PROFILE_MODE`, it must also handle the dependent distance gate.

If `ENABLE_AVG_PROFILE_DISTANCE_GATE=true`, the proposal must include:

```json
{
  "parameter": "ENABLE_AVG_PROFILE_DISTANCE_GATE",
  "to_value": false,
  "dependency_reason": "semantic_scale_metric_profile_mode_changed"
}
```

Reason: `MAX_AVG_PROFILE_DISTANCE` is calibrated to the previous profile-mode scale. Keeping the old gate active after a profile-mode change makes the candidate invalid.

If this dependency is missing, preflight should block the candidate, but the supervisor must treat it as non-fatal and continue with controlled exploration.
