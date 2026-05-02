param(
  [int]$PollSeconds = 60,
  [string]$StopFile = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = $PSScriptRoot
Set-Location $repo
$repoRoot = Resolve-Path (Join-Path $repo "..\\..")
$logDir = Join-Path $repoRoot "logs\\autonomous_loop"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$watchdogLog = Join-Path $logDir "watchdog.log"
$pidFile = Join-Path $logDir "watchdog.pid"
$lockFile = Join-Path $logDir "watchdog.lock"
if ([string]::IsNullOrWhiteSpace($StopFile)) {
  $StopFile = Join-Path $logDir "watchdog.stop"
}

function Write-Log([string]$Message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "[$ts] $Message"
  Add-Content -LiteralPath $watchdogLog -Encoding UTF8 -Value $line
}

function Read-JsonSafe([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  try {
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Read-MdValue([string]$Path, [string]$Key) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  try {
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
  } catch {
    return $null
  }
  $escaped = [Regex]::Escape($Key)
  $patterns = @(
    "(?m)^\-\s*${escaped}:\s*`?(.*?)`?\s*$",
    "(?m)^-?\s*${escaped}:\s*`?(.*?)`?\s*$"
  )
  foreach ($pat in $patterns) {
    $m = [Regex]::Match($text, $pat)
    if ($m.Success) {
      return $m.Groups[1].Value.Trim()
    }
  }
  return $null
}

function Convert-ToInt([object]$Value, [int]$Default = 0) {
  if ($null -eq $Value) { return $Default }
  try {
    return [int]([string]$Value)
  } catch {
    return $Default
  }
}

function Convert-ToBool([object]$Value) {
  if ($null -eq $Value) { return $false }
  $s = ([string]$Value).Trim().ToLowerInvariant()
  return $s -in @("true", "1", "yes", "y")
}

function Get-LoopPythonProcess {
  try {
    return @(Get-CimInstance Win32_Process | Where-Object {
      $_.Name -eq "python.exe" -and
      [string]$_.CommandLine -match "run_infinite_research_loop\.py"
    })
  } catch {
    return @()
  }
}

function Get-AlertSnapshot {
  $statePath = Join-Path $repoRoot "state\\autonomous_loop_state.json"
  $livePath = Join-Path $repoRoot "reports\\autonomous_loop_live_summary.md"
  $finalPath = Join-Path $repoRoot "reports\\autonomous_loop_final_summary.md"

  $state = Read-JsonSafe $statePath
  $liveLoopStatus = Read-MdValue $livePath "loop_status"
  $liveParentValid = Read-MdValue $livePath "parent_valid"
  $finalStatus = Read-MdValue $finalPath "status"
  $finalBaselineChanged = Read-MdValue $finalPath "baseline_changed"
  $final156 = Read-MdValue $finalPath "156_executed"
  $finalIncomplete = Read-MdValue $finalPath "incomplete_runs"
  $finalNoParent = Read-MdValue $finalPath "no_parent_runs"
  $finalPending = Read-MdValue $finalPath "pending_promotion_review"
  $finalRecommended = Read-MdValue $finalPath "recommended_next_action"

  [pscustomobject]@{
    state = $state
    liveLoopStatus = $liveLoopStatus
    liveParentValid = $liveParentValid
    finalStatus = $finalStatus
    finalBaselineChanged = $finalBaselineChanged
    final156 = $final156
    finalIncomplete = $finalIncomplete
    finalNoParent = $finalNoParent
    finalPending = $finalPending
    finalRecommended = $finalRecommended
  }
}

Write-Log "watchdog start pid=$PID poll_seconds=$PollSeconds stop_file=$StopFile"
try {
  while ($true) {
    if (Test-Path -LiteralPath $StopFile) {
      Write-Log "stop file detected path=$StopFile"
      break
    }

    $snap = Get-AlertSnapshot
    $state = $snap.state
    $loopStatus = [string]($state.loop_status)
    $iterations = Convert-ToInt $state.iterations_completed 0
    $currentParent = [string]($state.current_parent_run_id)
    $stopReason = [string]($state.stop_reason)
    $activePids = @(Get-LoopPythonProcess)
    $hasLoopPython = $activePids.Count -gt 0
    $parentValid = Convert-ToBool $snap.liveParentValid
    $baselineChanged = Convert-ToBool $snap.finalBaselineChanged
    $executed156 = Convert-ToBool $snap.final156
    $pendingPromotion = Convert-ToInt $snap.finalPending 0
    $incompleteRuns = Convert-ToInt $snap.finalIncomplete 0
    $noParentRuns = Convert-ToInt $snap.finalNoParent 0
    $finalStatus = [string]$snap.finalStatus
    $recommended = [string]$snap.finalRecommended

    $alerts = New-Object System.Collections.Generic.List[string]
    if ($loopStatus -eq "running" -and -not $hasLoopPython) {
      $alerts.Add("loop_status=running but no python.exe live for run_infinite_research_loop.py")
    }
    if ($loopStatus -eq "running" -and -not $parentValid) {
      $alerts.Add("parent_valid=False with loop_status=running")
    }
    if ($executed156) {
      $alerts.Add("156_executed=True")
    }
    if ($baselineChanged) {
      $alerts.Add("baseline_changed=True")
    }
    if ($pendingPromotion -gt 0) {
      $alerts.Add("pending_promotion_review=$pendingPromotion")
    }
    if ($finalStatus -eq "FAIL") {
      $alerts.Add("status=FAIL")
    }
    if ($incompleteRuns -gt 0) {
      $alerts.Add("incomplete_runs=$incompleteRuns")
    }
    if ($noParentRuns -gt 0) {
      $alerts.Add("no_parent_runs=$noParentRuns")
    }
    if ($recommended -eq "fix_process_before_more_research") {
      $alerts.Add("recommended_next_action=fix_process_before_more_research")
    }

    $activePidList = if ($activePids.Count -gt 0) { ($activePids | ForEach-Object { $_.ProcessId }) -join "," } else { "" }
    Write-Log ("heartbeat loop_status={0} iterations_completed={1} parent_valid={2} has_python={3} final_status={4} current_parent_run_id={5} stop_reason={6} pids={7}" -f `
      $loopStatus, $iterations, $parentValid, $hasLoopPython, $finalStatus, $currentParent, $stopReason, $activePidList)

    foreach ($alert in $alerts) {
      Write-Log ("ALERT {0}" -f $alert)
    }

    Start-Sleep -Seconds $PollSeconds
  }
} finally {
  try {
    if (Test-Path -LiteralPath $pidFile) {
      $pidText = (Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8).Trim()
      if ($pidText -and ([int]$pidText -eq $PID)) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
      }
    }
    if (Test-Path -LiteralPath $lockFile) {
      $lock = Read-JsonSafe $lockFile
      if ($null -eq $lock -or [int]$lock.pid -eq $PID) {
        Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
      }
    }
  } catch {
    Write-Log ("cleanup_error {0}" -f $_.Exception.Message)
  }
  Write-Log "watchdog exit pid=$PID"
}
