# Auditoría de aprendizaje y continuidad

- Repo: `C:\Pythons\ML-Trading\Base_Archivos_SPY`
- Generado: `2026-05-01 09:21:40`
- Últimas corridas analizadas: **150**
- Rango: **EXP_1141 → EXP_1290**

## Veredicto

**MIXTO: seguir solo con pocas iteraciones y monitoreo.**

- El lote terminó como completed. Se puede decidir con métricas del lote.
- v4 parece aplicado por marcadores principales.
- Seguir solo con lote chico: pocas corridas reales; el generador está trabado.
- Hubo 10 accepted_for_followup: hay alguna señal de aprendizaje.
- ALERTA: streak no_material de 137. Debería cortar con candidate_generation_exhausted, no seguir.
- Hay 30 filas en candidate_generation_failures.csv: v4/CGF está registrando fallas.
- Existe diagnóstico candidate_generation_exhaustion. Conviene leerlo antes de seguir.

## Estado del loop

- loop_status: `completed`
- stop_reason: ``
- last_run_id: `EXP_1290`
- last_run_status: `run_ok`
- current_parent_run_id: `EXP_1290`
- iterations_completed: `30`
- updated_at: `2026-05-01T01:36:10`
- consecutive_no_material_candidate: `0`
- force_next_candidate_generation_mode: `controlled_exploration`
- candidate_generation_escape_active: `True`
- candidate_generation_escape_event: `{"action": "reset_parent_to_baseline_clean_for_candidate_generation", "at": "2026-05-01T01:08:06", "consecutive_no_material_candidate": 10, "last_run_id": "EXP_1290", "level": "parent_reset", "next_mode": "controlled_exploration", "parent_run_id": "EXP_1288", "reason": "too_many_no_material_candidate_parent_reset"}`
- branch_exhausted_event: ``

## Procesos vivos relacionados

```txt
﻿

ProcessId   : 2000
Name        : msedgewebview2.exe
CommandLine : "C:\Program Files (x86)\Microsoft\EdgeWebView\Application\147.0.3912.86\msedgewebview2.exe" 
              --embedded-browser-webview=1 --webview-exe-name=ms-teams.exe --webview-exe-version=26072.521.4595.7966 --
              user-data-dir="C:\Users\celestinoh\AppData\Local\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTe
              ams\EBWebView" --noerrdialogs --embedded-browser-webview-dpi-awareness=2 
              --autoplay-policy=no-user-gesture-required --disable-background-timer-throttling --disable-features=msEnh
              ancedTrackingPreventionEnabled,BreakoutBoxPreferCaptureTimestampInVideoFrames,BlockCrossPartitionBlobUrlF
              etching,msWebOOUI --enable-blink-features=IndexedDbGetAllRecords --enable-features=msSingleSignOnOSForPri
              maryAccountIsShared,SharedArrayBuffer,AutofillReplaceCachedWebElementsByRendererIds,msWebView2TerminateSe
              rviceWorkerWhenIdleIgnoringCdpSessions,msWebView2SetUserAgentOverrideOnIframes,PreferredAudioOutputDevice
              s,DocumentPolicyIncludeJSCallStacksInCrashReports,RendererHangWatcher:delay/13s,msPageInteractionManagerW
              ebview2,UnresponsiveMultipleStackCollection:delay/0.1s/count/5,PartitionedCookies,ThirdPartyStoragePartit
              ioning,msWebView2TextureStream,msWebView2EnableDraggableRegions,msAbydos,msAbydosHandwritingAttr,msAbydos
              GestureSupport --gpu-watchdog-timeout-seconds=60 --isolate-origins=https://[*.]microsoft.com,https://[*.]
              sharepoint.com,https://[*.]sharepointonline.com,https://mesh-hearts-teams.azurewebsites.net,https://[*.]m
              eshxp.net,https://res-sdf.cdn.office.net,https://res.cdn.office.net,https://copilot.teams.cloud.microsoft
              ,https://local.copilot.teams.office.com,https://m365copilotchat.svc.cloud.microsoft,https://m365copilotap
              p.svc.cloud.microsoft --js-flags=--stack-trace-limit=50 --lang=es-ES 
              --mojo-named-platform-channel-pipe=18020.21612.7224103538610466312 
              /pfhostedapp:f50686b1540c524e06fc1ca8e48e4dce80be883d

ProcessId   : 13880
Name        : msedgewebview2.exe
CommandLine : "C:\Program Files (x86)\Microsoft\EdgeWebView\Application\147.0.3912.86\msedgewebview2.exe" 
              --type=gpu-process --gpu-watchdog-timeout-seconds=60 --noerrdialogs --user-data-dir="C:\Users\celestinoh\
              AppData\Local\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\EBWebView" 
              --webview-exe-name=ms-teams.exe --webview-exe-version=26072.521.4595.7966 --embedded-browser-webview=1 
              --embedded-browser-webview-dpi-awareness=2 --gpu-preferences=SAAAAAAAAADgAAAEAAAAAAAAAAAAAGAAAQAAAAAAAAAA
              AAAAAAAAAAIAAAAAAAAAAAAAAAAAAAAQAAAAAAAAABAAAAAAAAAACAAAAAAAAAAIAAAAAAAAAA== --startup-read-main-dll 
              --metrics-shmem-handle=1900,i,17638021759444889813,1614797576540072882,262144 
              --field-trial-handle=1552,i,5694440315177228672,3671769314314985019,262144 --enable-features=AutofillRepl
              aceCachedWebElementsByRendererIds,DocumentPolicyIncludeJSCallStacksInCrashReports,PartitionedCookies,Pref
              erredAudioOutputDevices,SharedArrayBuffer,ThirdPartyStoragePartitioning,msAbydos,msAbydosGestureSupport,m
              sAbydosHandwritingAttr,msPageInteractionManagerWebview2,msSingleSignOnOSForPrimaryAccountIsShared,msWebVi
              ew2EnableDraggableRegions,msWebView2SetUserAgentOverrideOnIframes,msWebView2TerminateServiceWorkerWhenIdl
              eIgnoringCdpSessions,msWebView2TextureStream --disable-features=BlockCrossPartitionBlobUrlFetching,Breako
              utBoxPreferCaptureTimestampInVideoFrames,msEnhancedTrackingPreventionEnabled,msWebOOUI 
              --variations-seed-version 
              --pseudonymization-salt-handle=1548,i,8380973175030313129,12730281238668135738,4 
              --trace-process-track-uuid=31907089
```

## ¿Está aplicado v4?

| check | ok |
| --- | --- |
| exists:autonomy_batch_audit.py | True |
| exists:autonomy_contract.json | True |
| exists:reconcile_loop_state.py | True |
| exists:run_infinite_research_loop.py | True |
| exists:run_multi_agent_iteration.py | True |
| exists:safe_io.py | True |
| exists:verify_autonomy_patch.ps1 | False |
| marker:CGF_ | True |
| marker:candidate_generation_exhausted | True |
| marker:candidate_generation_exhaustion_diagnostic | True |
| marker:candidate_generation_failures | True |
| marker:iteration_timeout_seconds | True |
| marker:quarantine | True |
| marker:safe_io | True |
| marker:single_instance_lock_enabled | True |
| marker:stop_on_baseline_change | True |
| marker:timeout= | True |


**v4_aplicado_completo_por_marcadores:** `True`

## Resumen numérico

- Total runs analizadas: **150**
- Corridas reales con ventanas/status real: **13** (8.67%)
- Corridas vacías/sin ventanas reales: **137** (91.33%)
- No material / CGF: **137** (91.33%)
- Accepted for follow-up: **10** (6.67%)
- Promoted to baseline: **0**
- Errores operativos: **0**
- Candidate generation failures CSV: **30**
- Longest no_material streak: **137**
  - Desde **EXP_1141** hasta **EXP_1277**

## Distribución por clasificación

| classification | count |
| --- | --- |
| blocked_no_material_candidate | 137 |
| baseline_changed | 13 |

## Distribución por parent

| parent_run_id | count |
| --- | --- |
| (vacío) | 150 |

## Distribución por ventanas

| executed_windows | count |
| --- | --- |
| (sin ventanas) | 137 |
| 4,8,24,52 | 13 |

## Últimas corridas reales con métricas encontradas

_Sin datos._

## Accepted recientes

| run_id | classification | parent_run_id | executed_windows | w52_avg_net_return_pct | w52_spy_compare | w52_pnl | w52_trades | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXP_1278 | baseline_changed |  | 4,8,24,52 |  |  |  |  | refine_current_branch |
| EXP_1280 | baseline_changed |  | 4,8,24,52 |  |  |  |  | extend_validation |
| EXP_1281 | baseline_changed |  | 4,8,24,52 |  |  |  |  | extend_validation |
| EXP_1283 | baseline_changed |  | 4,8,24,52 |  |  |  |  | refine_current_branch |
| EXP_1284 | baseline_changed |  | 4,8,24,52 |  |  |  |  | refine_current_branch |
| EXP_1285 | baseline_changed |  | 4,8,24,52 |  |  |  |  | extend_validation |
| EXP_1286 | baseline_changed |  | 4,8,24,52 |  |  |  |  | extend_validation |
| EXP_1287 | baseline_changed |  | 4,8,24,52 |  |  |  |  | refine_current_branch |
| EXP_1288 | baseline_changed |  | 4,8,24,52 |  |  |  |  | extend_validation |
| EXP_1290 | baseline_changed |  | 4,8,24,52 |  |  |  |  | refine_current_branch |

## Últimas 60 corridas

| run_id | classification | status | parent_run_id | executed_windows | accepted_for_followup | promoted_to_baseline | reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EXP_1231 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1232 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1233 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1234 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1235 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1236 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1237 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1238 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1239 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1240 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1241 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1242 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1243 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1244 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1245 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1246 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1247 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1248 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1249 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1250 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1251 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1252 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1253 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1254 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1255 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1256 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1257 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1258 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1259 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1260 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1261 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1262 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1263 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1264 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1265 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1266 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1267 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1268 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1269 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1270 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1271 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1272 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1273 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1274 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1275 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1276 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1277 | blocked_no_material_candidate | blocked_no_material_candidate |  |  | False | False | controlled_exploration |
| EXP_1278 | baseline_changed | run_ok |  | 4,8,24,52 | True | False | refine_current_branch |
| EXP_1279 | baseline_changed | run_ok |  | 4,8,24,52 | False | False | controlled_exploration |
| EXP_1280 | baseline_changed | run_ok |  | 4,8,24,52 | True | False | extend_validation |
| EXP_1281 | baseline_changed | run_ok |  | 4,8,24,52 | True | False | extend_validation |
| EXP_1282 | baseline_changed | run_ok |  | 4,8,24,52 | False | False | controlled_exploration |
| EXP_1283 | baseline_changed | run_ok |  | 4,8,24,52 | True | False | refine_current_branch |
| EXP_1284 | baseline_changed | run_ok |  | 4,8,24,52 | True | False | refine_current_branch |
| EXP_1285 | baseline_changed | run_ok |  | 4,8,24,52 | True | False | extend_validation |
| EXP_1286 | baseline_changed | run_ok |  | 4,8,24,52 | True | False | extend_validation |
| EXP_1287 | baseline_changed | run_ok |  | 4,8,24,52 | True | False | refine_current_branch |
| EXP_1288 | baseline_changed | run_ok |  | 4,8,24,52 | True | False | extend_validation |
| EXP_1289 | baseline_changed | run_ok |  | 4,8,24,52 | False | False | controlled_exploration |
| EXP_1290 | baseline_changed | run_ok |  | 4,8,24,52 | True | False | refine_current_branch |

## Diagnósticos v4 / agotamiento

- candidate_generation_failures.csv: `C:\Pythons\ML-Trading\Base_Archivos_SPY\state\candidate_generation_failures.csv`
- exhaustion diagnostic MD: `C:\Pythons\ML-Trading\Base_Archivos_SPY\reports\candidate_generation_exhaustion_diagnostic.md`

### Preview diagnostic MD

```md
# Candidate Generation Exhaustion Diagnostic

- at: `2026-05-01T01:08:06`
- reason: `candidate_generation_parent_reset`
- final: `False`
- parent_run_id: `EXP_1288`
- current_parent_run_id: `EXP_1288`
- consecutive_no_material_candidate: `10`
- last_run_id: `EXP_1290`
- last_cgf_id: `CGF_000030`

## Recommended actions
- No seguir lanzando EXP si no hay candidato material.
- Revisar fallback_candidate_pool_considered y cooldowns activos.
- Cambiar parent/familia/eje antes de reintentar.
- Si el parent actual sigue agotado, usar baseline clean como parent temporal de exploracion.

## Recent results
| run_id | cgf_id | status | parent | windows |
| --- | --- | --- | --- | --- |
| EXP_1285 |  | run_ok | EXP_1284 | 52,4,8,24 |
| EXP_1286 |  | run_ok | EXP_1285 | 52,4,8,24 |
| EXP_1287 |  | run_ok | EXP_1286 | 52,4,8,24 |
| EXP_1288 |  | run_ok | EXP_1287 | 52,4,8,24 |
| EXP_1289 |  | run_ok | EXP_1288 | 52,4,8,24 |
| EXP_1290 | CGF_000021 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000022 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000023 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000024 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000025 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000026 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000027 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000028 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000029 | blocked_no_material_candidate | EXP_1288 |  |
| EXP_1290 | CGF_000030 | blocked_no_material_candidate | EXP_1288 |  |

```
- exhaustion diagnostic JSON: `C:\Pythons\ML-Trading\Base_Archivos_SPY\reports\candidate_generation_exhaustion_diagnostic.json`

## Archivos generados

- `learning_status_report.md`
- `latest_runs_learning_summary.csv`
- `latest_real_runs.csv`
- `latest_accepted_runs.csv`
- `latest_operational_errors.csv`
- `latest_no_material_runs.csv`
- `selected_run_ids.txt`
- `active_loop_processes.txt`
