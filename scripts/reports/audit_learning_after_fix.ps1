$ErrorActionPreference = "Stop"

$Base = "C:\Pythons\ML-Trading\Base_Archivos_SPY"
$Ts = Get-Date -Format "yyyyMMdd_HHmmss"
$Out = "$Base\reports\audit_learning_after_fix_$Ts.txt"

function Add($txt="") { $txt | Out-File $Out -Append -Encoding utf8 }

Set-Location $Base
"=== AUDITORIA POST FIX CANDIDATE LEARNING / GOVERNANCE ===" | Out-File $Out -Encoding utf8
Add "Fecha: $Ts"
Add "Base: $Base"
Add ""

Add "====================================="
Add "1) ESTADO ACTUAL"
Add "====================================="
if (Test-Path "$Base\state\autonomous_loop_state.json") {
  Get-Content "$Base\state\autonomous_loop_state.json" | Out-File $Out -Append -Encoding utf8
} else { Add "No existe state\autonomous_loop_state.json" }
Add ""

Add "====================================="
Add "2) SUMMARY LIVE"
Add "====================================="
if (Test-Path "$Base\reports\autonomous_loop_live_summary.md") {
  Get-Content "$Base\reports\autonomous_loop_live_summary.md" -Tail 160 | Out-File $Out -Append -Encoding utf8
} else { Add "No existe reports\autonomous_loop_live_summary.md" }
Add ""

$Log = "$Base\trackers\experiment_log.csv"
Add "====================================="
Add "3) ULTIMAS 30 CORRIDAS DESDE trackers\experiment_log.csv"
Add "====================================="
if (Test-Path $Log) {
  $rows = Import-Csv $Log -Delimiter ';'
  $rows | Select-Object -Last 30 |
    Select-Object run_id,parent_run_id,status,accepted_or_rejected,main_parameter,main_from,main_to,w52_spy_compare,notes,run_dir |
    Format-Table -AutoSize |
    Out-String -Width 700 |
    Out-File $Out -Append -Encoding utf8

  Add ""
  Add "====================================="
  Add "4) REPETICION DE TRANSICIONES ULTIMAS 60"
  Add "====================================="
  $rows | Select-Object -Last 60 |
    Where-Object { $_.status -match 'run_ok|run_partial_valid' -and $_.main_parameter } |
    ForEach-Object {
      [PSCustomObject]@{
        transition = "$($_.main_parameter) $($_.main_from) -> $($_.main_to)"
        decision = $_.accepted_or_rejected
        run_id = $_.run_id
      }
    } |
    Group-Object transition |
    Sort-Object Count -Descending |
    Select-Object -First 20 Count,Name |
    Format-Table -AutoSize |
    Out-String -Width 700 |
    Out-File $Out -Append -Encoding utf8

  Add ""
  Add "====================================="
  Add "5) ALERTA: EJES AGOTADOS QUE NO DEBEN REPETIRSE"
  Add "====================================="
  $badPatterns = @(
    'TOP_SIMILAR_SPY_WEEKS 28 -> 16',
    'TOP_CANDIDATES_NEXT_WEEK 2 -> 4',
    'TOP_CANDIDATES_NEXT_WEEK 2 -> 5',
    'MAX_AVG_PROFILE_DISTANCE 0.17 -> 0.15'
  )
  foreach ($p in $badPatterns) {
    $hits = $rows | Select-Object -Last 20 | Where-Object {
      "$($_.main_parameter) $($_.main_from) -> $($_.main_to)" -eq $p
    }
    if ($hits) {
      Add "MAL / REVISAR: apareció nuevamente $p"
      $hits | Select-Object run_id,status,accepted_or_rejected,notes | Format-Table -AutoSize | Out-String -Width 700 | Out-File $Out -Append -Encoding utf8
    } else {
      Add "OK: no apareció en últimas 20: $p"
    }
  }
} else {
  Add "No existe $Log"
}
Add ""

Add "====================================="
Add "6) PARAMETER EFFECT MEMORY: TRANSICIONES EXHAUSTED"
Add "====================================="
$Mem = "$Base\state\parameter_effect_memory.json"
if (Test-Path $Mem) {
  $json = Get-Content $Mem -Raw | ConvertFrom-Json
  $json.transitions |
    Where-Object { $_.current_effect_class -eq 'exhausted' -or (($_.total_attempts -ge 3) -and ($_.accepted_count -eq 0) -and ($_.rejected_count -ge 3)) } |
    Sort-Object total_attempts -Descending |
    Select-Object -First 30 parameter,from_value,to_value,total_attempts,accepted_count,rejected_count,current_effect_class,last_run_ids |
    Format-Table -AutoSize |
    Out-String -Width 700 |
    Out-File $Out -Append -Encoding utf8
} else { Add "No existe state\parameter_effect_memory.json" }
Add ""

Add "====================================="
Add "7) FALLBACK DIAGNOSIS / HARD BLOCK TRACE EN ULTIMAS CORRIDAS"
Add "====================================="
Get-ChildItem "$Base\runs\multi_agent_runs" -Directory -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 8 |
  ForEach-Object {
    $ao = Join-Path $_.FullName "analyst_output.json"
    if (Test-Path $ao) {
      Add "--- $($_.Name) ---"
      Select-String -Path $ao -Pattern "memory_hard_blocked_subspaces|hard_blocked_exhausted_or_memory_subspace|config_hash_already_tested_executed_run|duplicate_recent_proposal|cooldown_active" -Context 0,3 -ErrorAction SilentlyContinue |
        Out-String -Width 700 |
        Out-File $Out -Append -Encoding utf8
    }
  }

Add ""
Add "Archivo generado: $Out"
notepad $Out
