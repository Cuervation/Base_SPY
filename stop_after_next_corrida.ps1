param(
  [string]$TaskName = "SPY_MultiAgent_Watchdog",
  [int]$PollSeconds = 5,
  [int]$WaitIterationFinishTimeoutSec = 1800
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
$ts = Get-Date -Format "yyMMddHHmmss"
$logPath = Join-Path $logsDir ("stop_after_next_" + $ts + ".log")

function LogLine([string]$msg) {
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
  Write-Host $line
  Add-Content -Path $logPath -Encoding UTF8 -Value $line
}

function Get-LastRunId([string]$repoRoot) {
  $expRel = "trackers\\experiment_log.csv"
  if ($script:PathsCfg -ne $null -and $script:PathsCfg.trackers.experiment_log) { $expRel = [string]$script:PathsCfg.trackers.experiment_log }
  $expPath = Join-Path $repoRoot $expRel
  if (-not (Test-Path $expPath)) { return "" }
  try {
    $rows = @(Import-Csv -Path $expPath -Delimiter ';')
    if ($rows.Count -eq 0) { return "" }
    $last = $rows[$rows.Count - 1]
    $p = $last.PSObject.Properties["run_id"]
    if ($null -eq $p) { return "" }
    return [string]$p.Value
  } catch {
    return ""
  }
}

function Get-CimPowershellByPattern([string]$pattern) {
  try {
    return @(Get-CimInstance Win32_Process | Where-Object {
      $_.Name -match "powershell.exe|pwsh.exe" -and
      $_.CommandLine -match $pattern
    })
  } catch {
    return @()
  }
}

function Get-DescendantCimProcesses([int]$RootPid) {
  $all = @(Get-CimInstance Win32_Process)
  $childrenByParent = @{}
  foreach ($p in $all) {
    $k = [int]$p.ParentProcessId
    if (-not $childrenByParent.ContainsKey($k)) {
      $childrenByParent[$k] = New-Object System.Collections.ArrayList
    }
    [void]$childrenByParent[$k].Add($p)
  }
  $seen = New-Object 'System.Collections.Generic.HashSet[int]'
  $q = New-Object System.Collections.Queue
  $q.Enqueue($RootPid)
  $out = New-Object System.Collections.ArrayList
  while ($q.Count -gt 0) {
    $curr = [int]$q.Dequeue()
    if ($seen.Contains($curr)) { continue }
    [void]$seen.Add($curr)
    if (-not $childrenByParent.ContainsKey($curr)) { continue }
    foreach ($ch in $childrenByParent[$curr]) {
      [void]$out.Add($ch)
      $q.Enqueue([int]$ch.ProcessId)
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

LogLine "STOP_AFTER_NEXT start"
$startRunId = Get-LastRunId -repoRoot $repo
LogLine ("watching from start_run_id={0}" -f $startRunId)

while ($true) {
  Start-Sleep -Seconds $PollSeconds
  $currentRunId = Get-LastRunId -repoRoot $repo
  if (-not [string]::IsNullOrWhiteSpace($currentRunId) -and $currentRunId -ne $startRunId) {
    LogLine ("detected next completed run_id={0}" -f $currentRunId)
    break
  }
}

$deadline = (Get-Date).AddSeconds($WaitIterationFinishTimeoutSec)
while ((Get-Date) -lt $deadline) {
  $iterProcs = @(Get-CimPowershellByPattern -pattern "run_multi_agent_iteration\.ps1")
  if ($iterProcs.Count -eq 0) {
    LogLine "iteration process ended; proceeding to stop loop/watchdog"
    break
  }
  LogLine ("waiting iteration process to end... count={0}" -f $iterProcs.Count)
  Start-Sleep -Seconds 3
}

try {
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    LogLine ("scheduled task stopped: {0}" -f $TaskName)
  } else {
    LogLine ("scheduled task not found: {0}" -f $TaskName)
  }
} catch {
  LogLine ("failed stopping task {0}: {1}" -f $TaskName, $_.Exception.Message)
}

$loopProcs = @(Get-CimPowershellByPattern -pattern "run_multi_agent_executor_loop\.ps1")
if ($loopProcs.Count -eq 0) {
  LogLine "loop process already down"
} else {
  foreach ($lp in $loopProcs) {
    $pidVal = [int]$lp.ProcessId
    LogLine ("stopping loop process tree root_pid={0}" -f $pidVal)
    Stop-ProcessTree -RootPid $pidVal
  }
}

LogLine "STOP_AFTER_NEXT done"
