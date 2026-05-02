param(
  [string]$PythonExe = "python",
  [string]$EvaluationWindows = "4,8,24,52",
  [int]$YearValidationWindowWeeks = 156,
  [string]$Long156Policy = "cadence_only",
  [int]$Long156CadenceUsefulRuns = 4,
  [double]$Long156MinW52SpyCompare = 0.5,
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
  [int]$IntervalSeconds = 5,
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

function LogLine([string]$path, [string]$msg) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "[$ts] $msg"
  Write-Host $line
  Add-Content -Path $path -Encoding UTF8 -Value $line
}

function Get-LastExperimentRow([string]$repoRoot) {
  $expRel = "trackers\\experiment_log.csv"
  if ($script:PathsCfg -ne $null -and $script:PathsCfg.trackers.experiment_log) { $expRel = [string]$script:PathsCfg.trackers.experiment_log }
  $expPath = Join-Path $repoRoot $expRel
  if (-not (Test-Path $expPath)) { return $null }
  $rows = @(Import-Csv -Path $expPath -Delimiter ';')
  if ($rows.Count -eq 0) { return $null }
  return $rows[$rows.Count - 1]
}

function To-DoubleSafe([object]$v) {
  if ($null -eq $v) { return $null }
  $s = [string]$v
  if ([string]::IsNullOrWhiteSpace($s)) { return $null }
  $s = $s.Trim() -replace ',', '.'
  if ($s -match '^-?\d+(\.\d+)?$') { return [double]$s }
  return $null
}

function Get-RowValue([object]$row, [string]$name) {
  if ($null -eq $row) { return $null }
  $prop = $row.PSObject.Properties[$name]
  if ($null -ne $prop) { return $prop.Value }
  return $null
}

function Read-JsonSafe([string]$path) {
  if (-not (Test-Path $path)) { return $null }
  try {
    return (Get-Content -Path $path -Raw -Encoding UTF8 | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Get-CurrentResearchMode([string]$repoRoot) {
  $rsRel = "state\\research_state.json"
  if ($script:PathsCfg -ne $null -and $script:PathsCfg.state.research_state) { $rsRel = [string]$script:PathsCfg.state.research_state }
  $researchPath = Join-Path $repoRoot $rsRel
  $rs = Read-JsonSafe -path $researchPath
  if ($null -eq $rs) { return "refine_current_branch" }
  $branch = $rs.branch_state
  if ($null -eq $branch) { return "refine_current_branch" }
  $mode = [string](Get-RowValue -row $branch -name "current_mode")
  if ([string]::IsNullOrWhiteSpace($mode)) {
    $next = [string](Get-RowValue -row $branch -name "recommended_next_action")
    if ($next -in @("controlled_exploration","extend_validation","champion_hold","safe_recovery_mode","fix_process_before_more_research")) {
      return $next
    }
    return "refine_current_branch"
  }
  return $mode
}

function Get-ModePaceSeconds(
  [string]$mode,
  [int]$baseSeconds,
  [int]$minSeconds = 0
) {
  $base = [Math]::Max(1, [int]$baseSeconds)
  $target = $base
  switch ($mode) {
    "extend_validation" { $target = [Math]::Max($base, 30) }
    "champion_hold" { $target = [Math]::Max($base, 45) }
    "safe_recovery_mode" { $target = [Math]::Max($base, 90) }
    "fix_process_before_more_research" { $target = [Math]::Max($base, 60) }
    default { $target = $base }
  }
  if ($minSeconds -gt 0) {
    $target = [Math]::Max($target, [int]$minSeconds)
  }
  return [int]$target
}

function Invoke-ModePacedSleep(
  [string]$repoRoot,
  [int]$baseSeconds,
  [string]$logPath,
  [string]$context,
  [int]$minSeconds = 0
) {
  $mode = Get-CurrentResearchMode -repoRoot $repoRoot
  $sleepSeconds = Get-ModePaceSeconds -mode $mode -baseSeconds $baseSeconds -minSeconds $minSeconds
  LogLine $logPath ("pace context={0} mode={1} sleep_sec={2}" -f $context, $mode, $sleepSeconds)
  Start-Sleep -Seconds $sleepSeconds
}

function Invoke-LoopAudit(
  [string]$repoRoot,
  [string]$pythonExe,
  [string]$logPath,
  [string]$contextTag
) {
  $analysisRel = "scripts\\reports\\generate_run_analysis.py"
  if ($script:PathsCfg -ne $null -and $script:PathsCfg.scripts.generate_run_analysis) { $analysisRel = [string]$script:PathsCfg.scripts.generate_run_analysis }
  $analysisScript = Join-Path $repoRoot $analysisRel
  if (-not (Test-Path $analysisScript)) {
    throw ("missing required analysis script: {0}" -f $analysisScript)
  }
  try {
    $auditOut = & $pythonExe $analysisScript --repo "$repoRoot" 2>&1
    $rc = $LASTEXITCODE
    if ($rc -eq 0) {
      $tail = ((@($auditOut) | Select-Object -Last 2) -join " | ")
      LogLine $logPath ("audit_ok context={0} rc={1} tail={2}" -f $contextTag, $rc, $tail)
    } else {
      $tail = ((@($auditOut) | Select-Object -Last 4) -join " | ")
      LogLine $logPath ("audit_error context={0} rc={1} tail={2}" -f $contextTag, $rc, $tail)
    }
  } catch {
    LogLine $logPath ("audit_exception context={0} err={1}" -f $contextTag, $_.Exception.Message)
  }
}

$loopLogsRel = "logs\\loop\\multi_agent_loop_logs"
if ($script:PathsCfg -ne $null -and $script:PathsCfg.logs.loop) { $loopLogsRel = [string]$script:PathsCfg.logs.loop }
$logsDir = Join-Path $repo $loopLogsRel
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
$sessionTs = Get-Date -Format "yyMMddHHmmss"
$sessionLog = Join-Path $logsDir ("executor_loop_" + $sessionTs + ".log")

LogLine $sessionLog "EXECUTOR LOOP start"
LogLine $sessionLog "params: max_iter=$MaxIterations eval_windows=$EvaluationWindows year_window=$YearValidationWindowWeeks long156_policy=$Long156Policy long156_cadence=$Long156CadenceUsefulRuns long156_min_w52_spy=$Long156MinW52SpyCompare long156_min_w52_weeks_traded=$Long156MinW52WeeksTraded long156_min_w52_trades=$Long156MinW52Trades xlsx_cadence=$XlsxCadenceRuns profile_cadence=$ProfileCadenceRuns disable_fast_artifacts=$DisableFastArtifacts disable_window_reuse=$DisableWindowReuse min_years_vs_spy=$MinYearsVsSpy max_nonpositive_years_vs_spy=$MaxNonPositiveYearsVsSpy min_weeks_traded=$MinWeeksTraded min_trades=$MinTrades min_avg_ret=$MinAvgNetReturnPct max_excluded_ratio=$MaxExcludedWeeksRatio require_beat_spy=$RequireBeatSpy req_passes=$RequiredConsecutivePasses"

$streak = 0
$lastRunDir = ""
$noProgressStreak = 0

for ($i = 1; $i -le $MaxIterations; $i++) {
  $runStamp = Get-Date -Format "yyMMddHHmmss"
  $outLog = Join-Path $logsDir ("iter_{0:D2}_{1}_out.log" -f $i, $runStamp)
  $errLog = Join-Path $logsDir ("iter_{0:D2}_{1}_err.log" -f $i, $runStamp)
  try {

  $beforeRow = Get-LastExperimentRow -repoRoot $repo
  $beforeRunId = [string](Get-RowValue -row $beforeRow -name "run_id")

  LogLine $sessionLog ("iteration {0}/{1}: launching run_multi_agent_iteration.ps1" -f $i, $MaxIterations)
  $iterArgs = @(
    "-ExecutionPolicy","Bypass",
    "-File",".\run_multi_agent_iteration.ps1",
    "-PythonExe",$PythonExe,
    "-EvaluationWindows",$EvaluationWindows,
    "-YearValidationWindowWeeks",$YearValidationWindowWeeks,
    "-Long156Policy",$Long156Policy,
    "-Long156CadenceUsefulRuns",$Long156CadenceUsefulRuns,
    "-Long156MinW52SpyCompare",$Long156MinW52SpyCompare,
    "-Long156MinW52WeeksTraded",$Long156MinW52WeeksTraded,
    "-Long156MinW52Trades",$Long156MinW52Trades,
    "-XlsxCadenceRuns",$XlsxCadenceRuns,
    "-ProfileCadenceRuns",$ProfileCadenceRuns,
    "-MinYearsVsSpy",$MinYearsVsSpy,
    "-MaxNonPositiveYearsVsSpy",$MaxNonPositiveYearsVsSpy,
    "-TimeoutSecPerRun",$TimeoutSecPerRun
  )
  if ($DisableFastArtifacts) { $iterArgs += "-DisableFastArtifacts" }
  if ($DisableWindowReuse) { $iterArgs += "-DisableWindowReuse" }
  $p = Start-Process -FilePath "C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -ArgumentList $iterArgs `
    -WorkingDirectory $repo `
    -WindowStyle Minimized `
    -PassThru `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog
  $startTs = Get-Date
  $lastHeartbeat = (Get-Date).AddMinutes(-10)
  while ($true) {
    $alive = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
    if (-not $alive) { break }
    $now = Get-Date
    if (($now - $lastHeartbeat).TotalSeconds -ge 20) {
      $elapsed = [int](($now - $startTs).TotalSeconds)
      $tail = ""
      if (Test-Path $outLog) {
        $tailLines = @(Get-Content -Path $outLog -Tail 3 -ErrorAction SilentlyContinue) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        $tail = ($tailLines -join " || ")
      }
      $tail = [string]$tail
      if ($tail.Length -gt 180) { $tail = $tail.Substring($tail.Length - 180) }
      LogLine $sessionLog ("iteration {0}: running... elapsed_sec={1} pid={2} tail={3}" -f $i, $elapsed, $p.Id, $tail)
      $lastHeartbeat = $now
    }
    Start-Sleep -Seconds 5
  }
  try { $p.Refresh() } catch {}
  $rc = $p.ExitCode
  if (Test-Path $outLog) {
    $tailOut = (Get-Content -Path $outLog -Tail 3 -ErrorAction SilentlyContinue) -join " | "
    if ($tailOut) { LogLine $sessionLog ("iteration {0}: out_tail={1}" -f $i, $tailOut) }
  }
  if (Test-Path $errLog) {
    $tailErrFinal = (Get-Content -Path $errLog -Tail 3 -ErrorAction SilentlyContinue) -join " | "
    if ($tailErrFinal) { LogLine $sessionLog ("iteration {0}: err_tail_final={1}" -f $i, $tailErrFinal) }
  }
  Invoke-LoopAudit -repoRoot $repo -pythonExe $PythonExe -logPath $sessionLog -contextTag ("iteration_{0}" -f $i)

  $afterRow = Get-LastExperimentRow -repoRoot $repo
  $afterRunId = [string](Get-RowValue -row $afterRow -name "run_id")
  $newRunDetected = ($afterRunId -ne "" -and $afterRunId -ne $beforeRunId)

  if (-not $newRunDetected) {
    LogLine $sessionLog ("iteration {0}: no new run_id detected (before='{1}', after='{2}'), rc={3}" -f $i, $beforeRunId, $afterRunId, $rc)
    $tailErr = ""
    if (Test-Path $errLog) {
      $tailErr = (Get-Content -Path $errLog -Tail 5 -ErrorAction SilentlyContinue) -join " | "
      if ($tailErr) { LogLine $sessionLog ("iteration {0}: err_tail={1}" -f $i, $tailErr) }
    }
    $noProgressStreak += 1
    if ($noProgressStreak -ge 3) {
      LogLine $sessionLog ("warning: {0} iteraciones consecutivas sin nueva corrida efectiva; se mantiene loop largo con ritmo conservador." -f $noProgressStreak)
    }
    $streak = 0
    if ($i -lt $MaxIterations) {
      Invoke-ModePacedSleep -repoRoot $repo -baseSeconds $IntervalSeconds -logPath $sessionLog -context ("iter_{0}_no_new_run" -f $i) -minSeconds 20
    }
    continue
  }

  $noProgressStreak = 0

  $resolvedRunDir = ""
  $rowRunDir = [string](Get-RowValue -row $afterRow -name "run_dir")
  if (-not [string]::IsNullOrWhiteSpace($rowRunDir)) {
    $resolvedRunDir = $rowRunDir
  }
  if ([string]::IsNullOrWhiteSpace($resolvedRunDir)) {
    $runsRel = "runs\\multi_agent_runs"
    if ($script:PathsCfg -ne $null -and $script:PathsCfg.runs.multi_agent_runs) { $runsRel = [string]$script:PathsCfg.runs.multi_agent_runs }
    $runsRoot = Join-Path $repo $runsRel
    if (-not (Test-Path $runsRoot)) { $runsRoot = Join-Path $repo "multi_agent_runs" }

    $latestRun = Get-ChildItem -Path $runsRoot -Directory -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 1
    if ($latestRun) { $resolvedRunDir = $latestRun.FullName }
  }
  if ($resolvedRunDir) { $lastRunDir = $resolvedRunDir }

  $status = [string](Get-RowValue -row $afterRow -name "status")
  $acceptedOrRejected = [string](Get-RowValue -row $afterRow -name "accepted_or_rejected")
  $w52WeeksTraded = To-DoubleSafe (Get-RowValue -row $afterRow -name "w52_weeks_traded")
  if ($null -eq $w52WeeksTraded) { $w52WeeksTraded = 0.0 }
  $w52Trades = To-DoubleSafe (Get-RowValue -row $afterRow -name "w52_trades")
  if ($null -eq $w52Trades) { $w52Trades = 0.0 }
  $w52AvgRet = To-DoubleSafe (Get-RowValue -row $afterRow -name "w52_avg_net_return_pct")
  if ($null -eq $w52AvgRet) { $w52AvgRet = To-DoubleSafe (Get-RowValue -row $afterRow -name "w52_avg_net_return") }
  if ($null -eq $w52AvgRet -and -not [string]::IsNullOrWhiteSpace($resolvedRunDir)) {
    $eoPath = Join-Path $resolvedRunDir "executor_output.json"
    $eo = Read-JsonSafe -path $eoPath
    if ($eo -and $eo.windows) {
      $w52 = $eo.windows.'52'
      if ($w52 -and $w52.metrics) {
        $w52AvgRet = To-DoubleSafe $w52.metrics.avg_net_return_pct
      }
    }
  }
  if ($null -eq $w52AvgRet) { $w52AvgRet = -9999.0 }
  $w52Spy = To-DoubleSafe (Get-RowValue -row $afterRow -name "w52_spy_compare")
  if ($null -eq $w52Spy) { $w52Spy = -9999.0 }
  $excludedRatio = [Math]::Max(0.0, [Math]::Min(1.0, (52.0 - $w52WeeksTraded) / 52.0))
  $spyOk = if ($RequireBeatSpy) { $w52Spy -gt 0.0 } else { $true }

  $multiYearPass = $false
  $multiYearYears = 0
  $multiYearNonPositive = 999
  $multiYearReason = "missing_validation"
  $validationPhase = "year1"
  if (-not [string]::IsNullOrWhiteSpace($resolvedRunDir)) {
    $coPath = Join-Path $resolvedRunDir "coordinator_output.json"
    $co = Read-JsonSafe -path $coPath
    if ($co) {
      $coPropNames = @($co.PSObject.Properties.Name)
      if (($coPropNames -contains "validation_phase") -and $co.validation_phase) {
        $validationPhase = [string]$co.validation_phase
      }
      if (($coPropNames -contains "multi_year_validation") -and $co.multi_year_validation) {
        $my = $co.multi_year_validation
        $tmpPass = Get-RowValue -row $my -name "pass"
        try {
          if ($null -ne $tmpPass) { $multiYearPass = [bool]$tmpPass } else { $multiYearPass = $false }
        } catch {
          $multiYearPass = $false
        }
        $tmpYears = To-DoubleSafe (Get-RowValue -row $my -name "years_evaluated")
        if ($null -ne $tmpYears) { $multiYearYears = [int][Math]::Round($tmpYears) }
        $tmpNonPos = To-DoubleSafe (Get-RowValue -row $my -name "nonpositive_years")
        if ($null -ne $tmpNonPos) { $multiYearNonPositive = [int][Math]::Round($tmpNonPos) }
        $tmpReason = Get-RowValue -row $my -name "reason"
        if (-not [string]::IsNullOrWhiteSpace([string]$tmpReason)) { $multiYearReason = [string]$tmpReason }
      }
    }
  }

  $phaseGatePass = $false
  if ($validationPhase -eq "multi_year") {
    $phaseGatePass = ($spyOk -and $multiYearPass)
  } else {
    $phaseGatePass = $spyOk
  }

  $pass = (
    ($status -eq "run_ok" -or $status -eq "run_partial_valid") -and
    ($acceptedOrRejected -eq "accepted") -and
    $w52WeeksTraded -ge $MinWeeksTraded -and
    $excludedRatio -le $MaxExcludedWeeksRatio -and
    $w52Trades -ge $MinTrades -and
    $w52AvgRet -ge $MinAvgNetReturnPct -and
    $phaseGatePass
  )

  if ($pass) { $streak += 1 } else { $streak = 0 }

  LogLine $sessionLog ("iteration {0}: run_id={1} status={2} accepted={3} validation_phase={4} w52_weeks_traded={5} excluded_ratio={6} w52_trades={7} w52_avg_ret={8} min_avg_ret={9} w52_spy={10} multi_year_pass={11} multi_years={12} nonpositive_years={13} phase_gate_pass={14} pass={15} streak={16}/{17} run={18} multi_year_reason={19}" -f $i, $afterRunId, $status, $acceptedOrRejected, $validationPhase, $w52WeeksTraded, [Math]::Round($excludedRatio,4), $w52Trades, $w52AvgRet, $MinAvgNetReturnPct, $w52Spy, [int]$multiYearPass, $multiYearYears, $multiYearNonPositive, [int]$phaseGatePass, [int]$pass, $streak, $RequiredConsecutivePasses, $lastRunDir, $multiYearReason)

  if ($streak -ge $RequiredConsecutivePasses) {
    if ($validationPhase -eq "multi_year") {
      LogLine $sessionLog ("milestone: {0} corridas consecutivas validas (52w + multi-anio > SPY). El loop continua en modo largo." -f $streak)
    } else {
      LogLine $sessionLog ("milestone: {0} corridas consecutivas validas en fase year1 (> SPY en 52w). El loop continua en modo largo." -f $streak)
    }
  }

  if ($i -lt $MaxIterations) {
    Invoke-ModePacedSleep -repoRoot $repo -baseSeconds $IntervalSeconds -logPath $sessionLog -context ("iter_{0}_post_run" -f $i)
  }
  } catch {
    $errMsg = $_.Exception.Message
    LogLine $sessionLog ("iteration {0}: loop_exception={1}" -f $i, $errMsg)
    if (Test-Path $errLog) {
      $tailErrEx = (Get-Content -Path $errLog -Tail 6 -ErrorAction SilentlyContinue) -join " | "
      if ($tailErrEx) { LogLine $sessionLog ("iteration {0}: err_tail_exception={1}" -f $i, $tailErrEx) }
    }
    Invoke-LoopAudit -repoRoot $repo -pythonExe $PythonExe -logPath $sessionLog -contextTag ("iteration_{0}_exception" -f $i)
    $streak = 0
    $noProgressStreak += 1
    if ($noProgressStreak -ge 3) {
      LogLine $sessionLog ("warning: {0} excepciones consecutivas en loop; se mantiene ejecucion con ritmo conservador para permitir autorecuperacion." -f $noProgressStreak)
    }
    if ($i -lt $MaxIterations) {
      Invoke-ModePacedSleep -repoRoot $repo -baseSeconds $IntervalSeconds -logPath $sessionLog -context ("iter_{0}_exception" -f $i) -minSeconds 30
    }
    continue
  }
}

LogLine $sessionLog ("STOP: alcanzado max_iterations={0} en loop largo (sin corte por racha de aceptadas)." -f $MaxIterations)

if ($lastRunDir) {
  LogLine $sessionLog ("last_run_dir={0}" -f $lastRunDir)
}
Invoke-LoopAudit -repoRoot $repo -pythonExe $PythonExe -logPath $sessionLog -contextTag "loop_end"
LogLine $sessionLog "EXECUTOR LOOP end"
