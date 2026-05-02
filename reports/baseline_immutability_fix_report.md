# Baseline Immutability Fix Report

Date: 2026-04-24

## 1. Executive Summary

Problema detectado:
- Durante una corrida real normal (sin `promoted_to_baseline`), el runner modifico `state/current_baseline.json` escribiendo al menos `updated_at`.

Causa probable:
- `run_multi_agent_iteration.py` persistia baseline como parte de la persistencia de estado (por ejemplo en `persist_governance_state` y en branch anchor sync), independientemente de si hubo promocion real.

Solucion aplicada:
- Baseline inmutable durante corridas normales:
  - se eliminaron escrituras automaticas de baseline (`updated_at`, `branch_anchor`, etc.).
- Promocion de baseline solo con accion explicita:
  - nuevo flag `--apply-baseline-promotion`
  - si `promoted_to_baseline=true` pero no se pasa el flag, se registra `pending_baseline_promotion.json` en el run dir y NO se toca baseline.

Listo para repetir small real run:
- **Si**, repetir `4,8` y validar que el hash de baseline no cambie.

## 2. Archivos modificados

| archivo | cambio | motivo |
|---|---|---|
| `run_multi_agent_iteration.py` | remover escrituras de baseline en persistencia normal; agregar `--apply-baseline-promotion`; registrar pending promotion | baseline debe ser inmutable salvo promocion explicita |
| `governance/baseline_immutability_policy.md` | nueva policy | dejar contrato de gobernanza claro |
| `agents/coordinator.md` | aclarar que promoted_to_baseline no escribe baseline automaticamente | coherencia operativa |
| `validators/validate_baseline_immutability.py` | nuevo validador por hash | enforcement liviano |
| `tests/test_baseline_immutability.py` | test minimo (unittest) | validar regla de escritura |

## 3. Nueva política de baseline

- Se puede leer baseline siempre.
- No se puede escribir baseline durante corridas normales (incluye `updated_at`).
- `promoted_to_baseline=true`:
  - sin `--apply-baseline-promotion`: no se escribe baseline, queda `pending_baseline_promotion.json`.
  - con `--apply-baseline-promotion`: se permite escribir baseline (accion explicita del operador).

## 4. Validator agregado

Uso:
```powershell
python validators/validate_baseline_immutability.py --before-hash <HASH_ANTES> --after-hash <HASH_DESPUES>
```

O bien:
```powershell
python validators/validate_baseline_immutability.py --baseline state/current_baseline.json --expected-hash <HASH_ANTES>
```

## 5. Tests agregados

- `tests/test_baseline_immutability.py`

## 6. Riesgos pendientes

Críticos:
- Ninguno identificado para inmutabilidad si se respeta el flag.

Medios:
- Si existia automatizacion que dependia de `updated_at` en baseline, ahora debe mirar `state/research_state.json` o el `experiment_manifest.json` del run.

Menores:
- Baseline legacy en raiz puede seguir existiendo, pero el runtime usa `state/current_baseline.json`.

## 7. Próximo paso recomendado

- Repetir small real run `4,8`.
- Validar inmutabilidad:
  - capturar hash antes/despues con `validate_baseline_immutability.py`.
- No correr todavía `24/52/156`.

