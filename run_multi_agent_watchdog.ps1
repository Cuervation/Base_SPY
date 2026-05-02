param(
  [int]$CheckIntervalMinutes = 15,
  [int]$StaleMinutes = 20,
  [int]$HardStuckMinutes = 90,
  [double]$CpuDeltaThreshold = 0.05,
  [string]$PythonExe = "python",
  [string]$EvaluationWindows = "4,8,24,52",
  [int]$YearValidationWindowWeeks = 156,
  [string]$Long156Policy = "threshold_or_cadence",
  [int]$Long156CadenceUsefulRuns = 3,
  [double]$Long156MinW52SpyCompare = 0.0,
  [double]$Long156MinW52WeeksTraded = 20.0,
  [double]$Long156MinW52Trades = 15.0,
  [int]$XlsxCadenceRuns = 5,
  [int]$ProfileCadenceRuns = 10,
  [bool]$DisableFastArtifacts = $false,
  [bool]$DisableWindowReuse = $false,
  [int]$MinYearsVsSpy = 2,
  [int]$MaxNonPositiveYearsVsSpy = 0,
  [int]$TimeoutSecPerRun = 5400,
  [int]$MaxIterations = 50,
  [int]$IntervalSeconds = 10,
  [double]$MinWeeksTraded = 20.0,
  [double]$MinTrades = 15.0,
  [double]$MinAvgNetReturnPct = 0.5,
  [double]$MaxExcludedWeeksRatio = 0.50,
  [bool]$RequireBeatSpy = $true,
  [int]$RequiredConsecutivePasses = 2
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = $PSScriptRoot
Set-Location $repo

# Prefer config/paths_config.json when present (reorg compatibility).
$pathsConfigPath = Join-Path $repo "config\\paths_config.json"
$script:PathsCfg = $null
if (Test-Path -LiteralPath $pathsConfigPath) {
  try { $script:PathsCfg = (Get-Content -LiteralPath $pathsConfigPath -Raw | ConvertFrom-Json) } catch { $script:PathsCfg = $null }
}

$watchdogLogsRel = "logs\\watchdog\\multi_agent_watchdog_logs"
if ($script:PathsCfg -ne $null -and $script:PathsCfg.logs.watchdog) { $watchdogLogsRel = [string]$script:PathsCfg.logs.watchdog }
$logsDir = Join-Path $repo $watchdogLogsRel
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
$pidFile = Join-Path $logsDir "executor_loop.pid"
$watchdogPidFile = Join-Path $logsDir "watchdog.pid"
$stateFile = Join-Path $logsDir "watchdog_health_state.json"
$sessionTs = Get-Date -Format "yyMMddHHmmss"
$watchdogLog = Join-Path $logsDir ("watchdog_" + $sessionTs + ".log")

function LogLine([string]$msg) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "[$ts] $msg"
  Write-Host $line
  Add-Content -Path $watchdogLog -Encoding UTF8 -Value $line
}

function Get-SafePropValue([object]$obj, [string]$name) {
  if ($null -eq $obj) { return $null }
  if ($obj -is [System.Collections.IDictionary]) {
    if ($obj.Contains($name)) { return $obj[$name] }
    return $null
  }
  $p = $obj.PSObject.Properties[$name]
  if ($null -eq $p) { return $null }
  return $p.Value
}

function Resolve-Long156PolicyFromBaseline() {
  try {
    $baselineRel = "state\\current_baseline.json"
    if ($script:PathsCfg -ne $null -and $script:PathsCfg.state.current_baseline) { $baselineRel = [string]$script:PathsCfg.state.current_baseline }
    $baselinePath = Join-Path $repo $baselineRel
    if (-not (Test-Path $baselinePath)) { return }
    $b = Get-Content -Path $baselinePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $validationPolicy = Get-SafePropValue -obj $b -name "validation_policy"
    $longPolicy = Get-SafePropValue -obj $validationPolicy -name "long_window_policy"
    if ($null -eq $longPolicy) { return }

    if (-not $PSBoundParameters.ContainsKey("Long156Policy")) {
      $v = [string](Get-SafePropValue -obj $longPolicy -name "run_156_policy")
      if (-not [string]::IsNullOrWhiteSpace($v)) { $script:Long156Policy = $v }
    }
    if (-not $PSBoundParameters.ContainsKey("Long156CadenceUsefulRuns")) {
      $v = Get-SafePropValue -obj $longPolicy -name "run_156_cadence_useful_runs"
      if ($null -ne $v) {
        $iv = [int]$v
        if ($iv -gt 0) { $script:Long156CadenceUsefulRuns = $iv }
      }
    }
    if (-not $PSBoundParameters.ContainsKey("Long156MinW52SpyCompare")) {
      $v = Get-SafePropValue -obj $longPolicy -name "run_156_min_w52_spy_compare"
      if ($null -ne $v) { $script:Long156MinW52SpyCompare = [double]$v }
    }
    if (-not $PSBoundParameters.ContainsKey("Long156MinW52WeeksTraded")) {
      $v = Get-SafePropValue -obj $longPolicy -name "run_156_min_w52_weeks_traded"
      if ($null -ne $v) { $script:Long156MinW52WeeksTraded = [double]$v }
    }
    if (-not $PSBoundParameters.ContainsKey("Long156MinW52Trades")) {
      $v = Get-SafePropValue -obj $longPolicy -name "run_156_min_w52_trades"
      if ($null -ne $v) { $script:Long156MinW52Trades = [double]$v }
    }
  } catch {}
}

function Get-ExecutorProcFromPidFile([string]$path) {
  if (-not (Test-Path $path)) { return $null }
  try {
    $raw = (Get-Content -Path $path -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    $pidNum = [int]$raw
    $p = Get-Process -Id $pidNum -ErrorAction SilentlyContinue
    if ($null -eq $p) { return $null }
    if ($p.ProcessName -notmatch "powershell|pwsh") { return $null }
    return $p
  } catch {
    return $null
  }
}

function Get-ExecutorProcFromCim() {
  try {
    $proc = Get-CimInstance Win32_Process | Where-Object {
      $_.Name -match "powershell.exe|pwsh.exe" -and
      $_.CommandLine -match "run_multi_agent_executor_loop\.ps1"
    } | Select-Object -First 1
    if ($proc) {
      return (Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue)
    }
  } catch {}
  return $null
}

function Start-ExecutorLoop() {
  $loopScript = Join-Path $repo "run_multi_agent_executor_loop.ps1"
  if (-not (Test-Path $loopScript)) {
    throw "No existe script: $loopScript"
  }

  $stamp = Get-Date -Format "yyMMddHHmmss"
  $outLog = Join-Path $logsDir ("executor_launcher_" + $stamp + "_out.log")
  $errLog = Join-Path $logsDir ("executor_launcher_" + $stamp + "_err.log")

  $p = Start-Process -FilePath "C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -ArgumentList @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-File", $loopScript,
      "-PythonExe", $PythonExe,
      "-EvaluationWindows", $EvaluationWindows,
      "-YearValidationWindowWeeks", $YearValidationWindowWeeks,
      "-Long156Policy", $Long156Policy,
      "-Long156CadenceUsefulRuns", $Long156CadenceUsefulRuns,
      "-Long156MinW52SpyCompare", $Long156MinW52SpyCompare,
      "-Long156MinW52WeeksTraded", $Long156MinW52WeeksTraded,
      "-Long156MinW52Trades", $Long156MinW52Trades,
      "-XlsxCadenceRuns", $XlsxCadenceRuns,
      "-ProfileCadenceRuns", $ProfileCadenceRuns,
      "-MinYearsVsSpy", $MinYearsVsSpy,
      "-MaxNonPositiveYearsVsSpy", $MaxNonPositiveYearsVsSpy,
      "-TimeoutSecPerRun", $TimeoutSecPerRun,
      "-MaxIterations", $MaxIterations,
      "-IntervalSeconds", $IntervalSeconds,
      "-MinWeeksTraded", $MinWeeksTraded,
      "-MinTrades", $MinTrades,
      "-MinAvgNetReturnPct", $MinAvgNetReturnPct,
      "-MaxExcludedWeeksRatio", $MaxExcludedWeeksRatio,
      "-RequiredConsecutivePasses", $RequiredConsecutivePasses
    ) `
    -WorkingDirectory $repo `
    -WindowStyle Minimized `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru

  [string]$p.Id | Set-Content -Path $pidFile -Encoding UTF8
  LogLine ("RELAUNCH ok pid={0} out={1} err={2}" -f $p.Id, $outLog, $errLog)
  return $p
}

function Get-DescendantCimProcesses([int]$RootPid) {
  $all = @(Get-CimInstance Win32_Process)
  $childrenByParent = @{}
  foreach ($p in $all) {
    $key = [int]$p.ParentProcessId
    if (-not $childrenByParent.ContainsKey($key)) {
      $childrenByParent[$key] = New-Object System.Collections.ArrayList
    }
    [void]$childrenByParent[$key].Add($p)
  }

  $seen = New-Object 'System.Collections.Generic.HashSet[int]'
  $queue = New-Object System.Collections.Queue
  $queue.Enqueue($RootPid)
  $out = New-Object System.Collections.ArrayList

  while ($queue.Count -gt 0) {
    $curr = [int]$queue.Dequeue()
    if ($seen.Contains($curr)) { continue }
    [void]$seen.Add($curr)
    if (-not $childrenByParent.ContainsKey($curr)) { continue }
    foreach ($ch in $childrenByParent[$curr]) {
      [void]$out.Add($ch)
      $queue.Enqueue([int]$ch.ProcessId)
    }
  }
  return @($out)
}

function Stop-ProcessTree([int]$RootPid) {
  $desc = @(Get-DescendantCimProcesses -RootPid $RootPid)
  $ids = New-Object System.Collections.Generic.List[int]
  foreach ($d in $desc) { [void]$ids.Add([int]$d.ProcessId) }
  [void]$ids.Add($RootPid)
  $unique = $ids | Select-Object -Unique | Sort-Object -Descending
  foreach ($id in $unique) {
    try { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue } catch {}
  }
}

function Get-LatestActivity() {
  $latestPath = ""
  $latestTs = [datetime]::MinValue

  $loopLogsRel = "logs\\loop\\multi_agent_loop_logs"
  if ($script:PathsCfg -ne $null -and $script:PathsCfg.logs.loop) { $loopLogsRel = [string]$script:PathsCfg.logs.loop }
  $loopLog = Get-ChildItem -Path (Join-Path $repo $loopLogsRel) -Filter "executor_loop_*.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if ($loopLog -and $loopLog.LastWriteTime -gt $latestTs) {
    $latestTs = $loopLog.LastWriteTime
    $latestPath = $loopLog.FullName
  }

  $iterLog = Get-ChildItem -Path (Join-Path $repo $loopLogsRel) -Filter "iter_*_out.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if ($iterLog -and $iterLog.LastWriteTime -gt $latestTs) {
    $latestTs = $iterLog.LastWriteTime
    $latestPath = $iterLog.FullName
  }

  $runsRel = "runs\\multi_agent_runs"
  if ($script:PathsCfg -ne $null -and $script:PathsCfg.runs.multi_agent_runs) { $runsRel = [string]$script:PathsCfg.runs.multi_agent_runs }
  $runsRoot = Join-Path $repo $runsRel
  if (-not (Test-Path $runsRoot)) {
    # Legacy fallback (pre-restructure)
    $runsRoot = Join-Path $repo "multi_agent_runs"
  }
  if (Test-Path $runsRoot) {
    $latestRunDir = Get-ChildItem -Path $runsRoot -Directory -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 1
    if ($latestRunDir) {
      $latestRunFile = Get-ChildItem -Path $latestRunDir.FullName -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
      if ($latestRunFile -and $latestRunFile.LastWriteTime -gt $latestTs) {
        $latestTs = $latestRunFile.LastWriteTime
        $latestPath = $latestRunFile.FullName
      }
    }
  }

  if ($latestTs -eq [datetime]::MinValue) {
    return $null
  }

  return [pscustomobject]@{
    last_write = $latestTs
    path = $latestPath
  }
}

function Load-State() {
  if (-not (Test-Path $stateFile)) { return @{} }
  try {
    $obj = Get-Content -Path $stateFile -Raw | ConvertFrom-Json
    $h = @{}
    foreach ($p in $obj.PSObject.Properties) { $h[[string]$p.Name] = $p.Value }
    return $h
  } catch {
    return @{}
  }
}

function Save-State([hashtable]$state) {
  ($state | ConvertTo-Json -Depth 8) | Set-Content -Path $stateFile -Encoding UTF8
}

function Parse-DateSafe([object]$value) {
  if ($null -eq $value) { return $null }
  $s = [string]$value
  if ([string]::IsNullOrWhiteSpace($s)) { return $null }
  try {
    return [datetime]::Parse($s)
  } catch {
    return $null
  }
}

function Get-RestartHistory24h([hashtable]$state, [datetime]$now) {
  $raw = $null
  if ($state.ContainsKey("restart_history")) {
    $raw = $state["restart_history"]
  }
  $hist = @()
  foreach ($entry in @($raw)) {
    $reason = [string](Get-SafePropValue -obj $entry -name "reason")
    $atRaw = Get-SafePropValue -obj $entry -name "at"
    $at = Parse-DateSafe $atRaw
    if ($null -eq $at) { continue }
    if (($now - $at).TotalHours -gt 24) { continue }
    $hist += [pscustomobject]@{
      at = $at.ToString("o")
      reason = $reason
    }
  }
  return @($hist)
}

function Get-LastExperimentRunId() {
  $expRel = "trackers\\experiment_log.csv"
  if ($script:PathsCfg -ne $null -and $script:PathsCfg.trackers.experiment_log) { $expRel = [string]$script:PathsCfg.trackers.experiment_log }
  $expPath = Join-Path $repo $expRel
  if (-not (Test-Path $expPath)) { return "" }
  try {
    $rows = @(Import-Csv -Path $expPath -Delimiter ';')
    if ($rows.Count -eq 0) { return "" }
    return [string]$rows[$rows.Count - 1].run_id
  } catch {
    return ""
  }
}

function Get-NoUsefulDeltaAssessment([int]$lookback = 8) {
  $rsRel = "state\\research_state.json"
  if ($script:PathsCfg -ne $null -and $script:PathsCfg.state.research_state) { $rsRel = [string]$script:PathsCfg.state.research_state }
  $researchPath = Join-Path $repo $rsRel
  if (-not (Test-Path $researchPath)) {
    return [pscustomobject]@{
      no_useful_delta = $false
      cause = "no_research_state"
      recent_count = 0
      useful_count = 0
      admin_blockers = 0
    }
  }

  try {
    $rs = Get-Content -Path $researchPath -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    return [pscustomobject]@{
      no_useful_delta = $false
      cause = "invalid_research_state"
      recent_count = 0
      useful_count = 0
      admin_blockers = 0
    }
  }

  $recent = @()
  $bm = Get-SafePropValue -obj $rs -name "branch_memory"
  foreach ($entry in @($bm)) {
    $rid = [string](Get-SafePropValue -obj $entry -name "run_id")
    if ([string]::IsNullOrWhiteSpace($rid) -or $rid -notmatch "^EXP_\d+$") { continue }
    $recent += $entry
  }
  if ($recent.Count -gt $lookback) {
    $recent = @($recent | Select-Object -Last $lookback)
  }

  $championRunIds = New-Object System.Collections.Generic.HashSet[string]
  $champRel = "runs\\champion_runs\\champion_runs.json"
  if ($script:PathsCfg -ne $null -and $script:PathsCfg.runs.champion_runs_json) { $champRel = [string]$script:PathsCfg.runs.champion_runs_json }
  $champPath = Join-Path $repo $champRel
  if (Test-Path $champPath) {
    try {
      $ch = Get-Content -Path $champPath -Raw -Encoding UTF8 | ConvertFrom-Json
      $chMap = Get-SafePropValue -obj $ch -name "champions"
      if ($chMap) {
        foreach ($p in $chMap.PSObject.Properties) {
          $rid = [string]$p.Value
          if (-not [string]::IsNullOrWhiteSpace($rid)) { [void]$championRunIds.Add($rid) }
        }
      }
    } catch {}
  }

  $usefulCount = 0
  $adminBlockers = 0
  $adminStatuses = @(
    "blocked_duplicate",
    "blocked_zigzag",
    "blocked_preflight",
    "blocked_branch_anchor",
    "blocked_no_material_candidate"
  )
  foreach ($entry in $recent) {
    $decision = [string](Get-SafePropValue -obj $entry -name "decision_type")
    $rid = [string](Get-SafePropValue -obj $entry -name "run_id")
    if ($decision -in @("accepted_for_followup", "promoted_to_baseline")) {
      $usefulCount += 1
      continue
    }
    if ($championRunIds.Contains($rid)) {
      $usefulCount += 1
      continue
    }
    $coStatus = [string](Get-SafePropValue -obj $entry -name "coordinator_status")
    if ($coStatus -in $adminStatuses) { $adminBlockers += 1 }
  }

  $noUseful = ($recent.Count -ge $lookback -and $usefulCount -eq 0)
  $cause = if ($adminBlockers -ge 3) { "admin_stagnation" } else { "research_stagnation" }
  return [pscustomobject]@{
    no_useful_delta = $noUseful
    cause = $cause
    recent_count = $recent.Count
    useful_count = $usefulCount
    admin_blockers = $adminBlockers
  }
}

function Set-ResearchMode([string]$mode, [string]$reason) {
  $rsRel2 = "state\\research_state.json"
  if ($script:PathsCfg -ne $null -and $script:PathsCfg.state.research_state) { $rsRel2 = [string]$script:PathsCfg.state.research_state }
  $researchPath = Join-Path $repo $rsRel2
  if (-not (Test-Path $researchPath)) { return $false }
  try {
    $rs = Get-Content -Path $researchPath -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    return $false
  }
  if ($null -eq $rs) { return $false }
  if ($null -eq (Get-SafePropValue -obj $rs -name "branch_state")) {
    $rs | Add-Member -NotePropertyName "branch_state" -NotePropertyValue ([pscustomobject]@{})
  }
  $bs = $rs.branch_state
  foreach ($prop in @("previous_mode","current_mode","mode_reason","last_mode_change_at","last_mode_change_run_id","mode_stability_counter")) {
    if ($null -eq (Get-SafePropValue -obj $bs -name $prop)) {
      $defaultValue = if ($prop -eq "mode_stability_counter") { 0 } else { "" }
      $bs | Add-Member -NotePropertyName $prop -NotePropertyValue $defaultValue -Force
    }
  }
  $prevMode = [string](Get-SafePropValue -obj $bs -name "current_mode")
  if ([string]::IsNullOrWhiteSpace($prevMode)) { $prevMode = "refine_current_branch" }
  $nowIso = (Get-Date).ToString("s")
  $runId = ""
  $st = Get-SafePropValue -obj $rs -name "state_tracking"
  if ($st) {
    $runId = [string](Get-SafePropValue -obj $st -name "last_successful_executor_run_id")
  }
  if ([string]::IsNullOrWhiteSpace($runId)) {
    $runId = Get-LastExperimentRunId
  }

  if ($prevMode -ne $mode) {
    $bs.previous_mode = $prevMode
    $bs.current_mode = $mode
    $bs.last_mode_change_at = $nowIso
    $bs.last_mode_change_run_id = $runId
    $bs.mode_stability_counter = 1
  } else {
    $stability = 0
    try { $stability = [int](Get-SafePropValue -obj $bs -name "mode_stability_counter") } catch {}
    $bs.mode_stability_counter = [Math]::Max(1, $stability + 1)
    if ([string]::IsNullOrWhiteSpace([string](Get-SafePropValue -obj $bs -name "last_mode_change_at"))) {
      $bs.last_mode_change_at = $nowIso
    }
    if ([string]::IsNullOrWhiteSpace([string](Get-SafePropValue -obj $bs -name "last_mode_change_run_id"))) {
      $bs.last_mode_change_run_id = $runId
    }
  }
  $bs.mode_reason = $reason
  $rs.updated_at = $nowIso
  try {
    ($rs | ConvertTo-Json -Depth 30) | Set-Content -Path $researchPath -Encoding UTF8
    return $true
  } catch {
    return $false
  }
}

if (Test-Path $watchdogPidFile) {
  try {
    $prevRaw = (Get-Content -Path $watchdogPidFile -Raw).Trim()
    if ($prevRaw) {
      $prevPid = [int]$prevRaw
      $prevProc = Get-Process -Id $prevPid -ErrorAction SilentlyContinue
      if ($prevProc -and $prevProc.Id -ne $PID -and $prevProc.ProcessName -match "powershell|pwsh") {
        LogLine ("EXIT duplicate watchdog detected. running_pid={0}" -f $prevProc.Id)
        exit 0
      }
    }
  } catch {}
}
[string]$PID | Set-Content -Path $watchdogPidFile -Encoding UTF8

if ($CheckIntervalMinutes -lt 1) { $CheckIntervalMinutes = 1 }
if ($StaleMinutes -lt $CheckIntervalMinutes) { $StaleMinutes = $CheckIntervalMinutes }
if ($HardStuckMinutes -lt ($StaleMinutes + $CheckIntervalMinutes)) { $HardStuckMinutes = $StaleMinutes + $CheckIntervalMinutes }
Resolve-Long156PolicyFromBaseline

LogLine "WATCHDOG start"
LogLine ("params: check_interval_min={0} stale_min={1} hard_stuck_min={2} eval_windows={3} year_window={4} long156_policy={5} long156_cadence={6} long156_min_w52_spy={7} long156_min_w52_weeks_traded={8} long156_min_w52_trades={9} xlsx_cadence={10} profile_cadence={11} disable_fast_artifacts={12} disable_window_reuse={13} min_years_vs_spy={14} max_nonpositive_years_vs_spy={15}" -f $CheckIntervalMinutes, $StaleMinutes, $HardStuckMinutes, $EvaluationWindows, $YearValidationWindowWeeks, $Long156Policy, $Long156CadenceUsefulRuns, $Long156MinW52SpyCompare, $Long156MinW52WeeksTraded, $Long156MinW52Trades, $XlsxCadenceRuns, $ProfileCadenceRuns, $DisableFastArtifacts, $DisableWindowReuse, $MinYearsVsSpy, $MaxNonPositiveYearsVsSpy)

$sleepSec = [int]($CheckIntervalMinutes * 60)

while ($true) {
  try {
  $state = Load-State
  $now = Get-Date
  $nowIso = $now.ToString("o")
  $restartHistory = @(Get-RestartHistory24h -state $state -now $now)
  $currCpu = @{}
  $cpuDeltaTotal = 0.0
  $staleMin = 999999.0
  $activityPath = ""
  $pyWorkers = 0
  $decision = "continue"
  $action = "none"
  $reason = "healthy"
  $healthClass = "loop_healthy"
  $noUseful = [pscustomobject]@{
    no_useful_delta = $false
    cause = "none"
    recent_count = 0
    useful_count = 0
    admin_blockers = 0
  }

  $hardStuckDetected = $false
  if ($state.ContainsKey("hard_stuck_detected")) {
    $hardStuckDetected = [bool]$state["hard_stuck_detected"]
  }
  $safeModeActive = $false
  if ($state.ContainsKey("safe_mode_active")) {
    $safeModeActive = [bool]$state["safe_mode_active"]
  }
  $noUsefulChecks = 0
  if ($state.ContainsKey("no_useful_delta_checks")) {
    try { $noUsefulChecks = [int]$state["no_useful_delta_checks"] } catch {}
  }
  $lastSuccessfulIterationAt = [string]$state["last_successful_iteration_at"]
  $lastSeenRunId = [string]$state["last_seen_run_id"]
  $currentRunId = Get-LastExperimentRunId
  $newRunObserved = (-not [string]::IsNullOrWhiteSpace($currentRunId) -and $currentRunId -ne $lastSeenRunId)
  if ($newRunObserved) {
    $lastSuccessfulIterationAt = $nowIso
  } elseif ([string]::IsNullOrWhiteSpace($lastSuccessfulIterationAt) -and -not [string]::IsNullOrWhiteSpace($currentRunId)) {
    $lastSuccessfulIterationAt = $nowIso
  }

  $loopProc = Get-ExecutorProcFromPidFile -path $pidFile
  if ($null -eq $loopProc) {
    $loopProc = Get-ExecutorProcFromCim
    if ($loopProc) {
      [string]$loopProc.Id | Set-Content -Path $pidFile -Encoding UTF8
      LogLine ("DISCOVERED running executor loop pid={0} (from process list)" -f $loopProc.Id)
    }
  }

  if ($null -eq $loopProc) {
    $decision = "restart"
    $action = "restart_loop_down"
    $reason = "loop_down"
    $healthClass = "process_down"
  } else {
    $activity = Get-LatestActivity
    if ($activity) {
      $staleMin = ($now - $activity.last_write).TotalMinutes
      $activityPath = [string]$activity.path
    }

    $desc = @(Get-DescendantCimProcesses -RootPid $loopProc.Id)
    $pyDesc = @($desc | Where-Object { $_.Name -match "python(\.exe|w\.exe)$" })
    $pyWorkers = $pyDesc.Count

    foreach ($p in $pyDesc) {
      $procId = [int]$p.ProcessId
      $cpu = 0.0
      try {
        $gp = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($gp) { $cpu = [double]$gp.CPU }
      } catch {}
      $currCpu[[string]$procId] = $cpu

      $prevCpu = $null
      $prevCpuMap = $null
      if ($state.ContainsKey("py_cpu")) {
        $prevCpuMap = $state["py_cpu"]
      }
      $hasPrevCpu = $false
      if ($null -ne $prevCpuMap) {
        if ($prevCpuMap -is [System.Collections.IDictionary]) {
          $hasPrevCpu = $prevCpuMap.Contains([string]$procId)
        } else {
          $prop = $prevCpuMap.PSObject.Properties[[string]$procId]
          $hasPrevCpu = ($null -ne $prop)
        }
      }
      if ($hasPrevCpu) {
        try {
          if ($prevCpuMap -is [System.Collections.IDictionary]) {
            $prevCpu = [double]$prevCpuMap[[string]$procId]
          } else {
            $prevCpu = [double]$prevCpuMap.([string]$procId)
          }
        } catch {
          $prevCpu = $null
        }
      }
      if ($null -ne $prevCpu) {
        $cpuDeltaTotal += [math]::Max(0.0, ($cpu - $prevCpu))
      }
    }

    if ($staleMin -gt $StaleMinutes) {
      if ($pyWorkers -gt 0 -and $cpuDeltaTotal -gt $CpuDeltaThreshold) {
        $decision = "continue_slow"
        $reason = "stale_logs_but_cpu_progress"
        $healthClass = "loop_alive_slow_progress"
      } elseif ($staleMin -ge $HardStuckMinutes) {
        $decision = "restart"
        $action = "kill_restart"
        $reason = "hard_stuck"
        $healthClass = "loop_hard_stuck_no_progress"
      } elseif ($pyWorkers -eq 0) {
        $decision = "restart"
        $action = "kill_restart"
        $reason = "stale_no_python_workers"
        $healthClass = "loop_stalled_workers_missing"
      } else {
        $decision = "continue_slow"
        $reason = "stale_with_python_no_cpu_delta"
        $healthClass = "loop_alive_waiting_cpu_delta"
      }
    }
  }

  if ($action -eq "none" -and $loopProc -ne $null) {
    $noUseful = Get-NoUsefulDeltaAssessment -lookback 8
    if ($noUseful.no_useful_delta) {
      $healthClass = "loop_alive_no_useful_delta"
      $reason = "no_useful_delta_recent"
      $noUsefulChecks = [Math]::Max(1, $noUsefulChecks + 1)
      if ($noUsefulChecks -ge 2 -and -not $safeModeActive) {
        if ($noUseful.cause -eq "admin_stagnation") {
          if (Set-ResearchMode -mode "fix_process_before_more_research" -reason "watchdog_no_useful_delta_admin_stagnation") {
            LogLine "MODE_SHIFT watchdog -> fix_process_before_more_research (no useful delta + admin blockers)"
          }
        } else {
          if (Set-ResearchMode -mode "controlled_exploration" -reason "watchdog_no_useful_delta_research_stagnation") {
            LogLine "MODE_SHIFT watchdog -> controlled_exploration (no useful delta + research stagnation)"
          }
        }
      }
    } else {
      $noUsefulChecks = 0
    }
  } elseif ($action -ne "none") {
    $noUsefulChecks = 0
  }

  $restartHappened = $false
  $restartReason = ""
  $loopPidForState = if ($loopProc) { $loopProc.Id } else { $null }
  if ($decision -eq "restart") {
    $restartReason = $reason
    try {
      if ($action -eq "kill_restart" -and $loopProc) {
        Stop-ProcessTree -RootPid $loopProc.Id
        Start-Sleep -Seconds 2
      }
      $newLoop = Start-ExecutorLoop
      $restartHappened = $true
      $loopPidForState = $newLoop.Id
      $restartHistory += [pscustomobject]@{
        at = $nowIso
        reason = $restartReason
      }
      $restartHistory = @(
        $restartHistory | Where-Object {
          $dt = Parse-DateSafe $_.at
          $dt -and (($now - $dt).TotalHours -le 24)
        }
      )
      if ($restartReason -eq "hard_stuck") {
        $hardStuckDetected = $true
      }
    } catch {
      LogLine ("RESTART failed: " + $_.Exception.Message)
    }
  }

  $restartCount24h = @($restartHistory).Count
  $sameReasonCount24h = 0
  if (-not [string]::IsNullOrWhiteSpace($restartReason)) {
    $sameReasonCount24h = @($restartHistory | Where-Object { ([string]$_.reason) -eq $restartReason }).Count
  }
  if ($restartHappened -and $sameReasonCount24h -ge 3) {
    $safeModeActive = $true
    if (Set-ResearchMode -mode "safe_recovery_mode" -reason ("watchdog_restarts_same_cause:{0}" -f $restartReason)) {
      LogLine ("MODE_SHIFT watchdog -> safe_recovery_mode (same restart cause x{0} in 24h: {1})" -f $sameReasonCount24h, $restartReason)
    }
  }
  if ($restartHappened -and $restartCount24h -ge 5) {
    $safeModeActive = $true
    if (Set-ResearchMode -mode "safe_recovery_mode" -reason "watchdog_high_restart_volume_24h") {
      LogLine ("MODE_SHIFT watchdog -> safe_recovery_mode (restart_count_last_24h={0})" -f $restartCount24h)
    }
  }
  if ($reason -eq "healthy" -and $restartCount24h -eq 0) {
    $hardStuckDetected = $false
    if ($safeModeActive) { $safeModeActive = $false }
  }

  LogLine ("COORDINATOR check pid={0} decision={1} action={2} health_class={3} stale_min={4:N1} py_workers={5} cpu_delta={6:N3} no_useful={7} no_useful_cause={8} no_useful_checks={9} restart_count_24h={10} same_reason_24h={11} safe_mode={12} activity='{13}' reason={14}" -f $loopPidForState, $decision, $action, $healthClass, $staleMin, $pyWorkers, $cpuDeltaTotal, [int]$noUseful.no_useful_delta, $noUseful.cause, $noUsefulChecks, $restartCount24h, $sameReasonCount24h, [int]$safeModeActive, $activityPath, $reason)

  $newState = @{}
  $newState["last_check"] = $nowIso
  $newState["last_loop_pid"] = $loopPidForState
  $newState["last_decision"] = $decision
  $newState["last_reason"] = $reason
  $newState["last_activity_path"] = $activityPath
  $newState["last_stale_min"] = [math]::Round($staleMin, 3)
  $newState["py_cpu"] = $currCpu
  $newState["last_restart_reason"] = if ($restartHappened) { $restartReason } else { [string]$state["last_restart_reason"] }
  $newState["restart_count_last_24h"] = $restartCount24h
  $newState["last_successful_iteration_at"] = $lastSuccessfulIterationAt
  $newState["hard_stuck_detected"] = [bool]$hardStuckDetected
  $newState["safe_mode_active"] = [bool]$safeModeActive
  $newState["health_class"] = $healthClass
  $newState["restart_history"] = @($restartHistory)
  $newState["last_seen_run_id"] = $currentRunId
  $newState["no_useful_delta_checks"] = [int]$noUsefulChecks
  $newState["no_useful_delta_recent"] = [bool]$noUseful.no_useful_delta
  $newState["no_useful_delta_cause"] = [string]$noUseful.cause
  Save-State -state $newState

  Start-Sleep -Seconds $sleepSec
  } catch {
    LogLine ("WATCHDOG loop_exception: " + $_.Exception.Message)
    Start-Sleep -Seconds ([Math]::Max(30, $sleepSec))
    continue
  }
}
