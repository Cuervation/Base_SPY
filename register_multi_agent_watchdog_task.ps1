param(
  [string]$TaskName = "SPY_MultiAgent_Watchdog",
  [int]$CheckIntervalMinutes = 15,
  [int]$StaleMinutes = 20,
  [int]$HardStuckMinutes = 90,
  [switch]$RunNow
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$watchdogScript = Join-Path $repo "run_multi_agent_watchdog.ps1"

if (-not (Test-Path $watchdogScript)) {
  throw "No existe script watchdog: $watchdogScript"
}

$argLine = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", "`"$watchdogScript`"",
  "-CheckIntervalMinutes", $CheckIntervalMinutes,
  "-StaleMinutes", $StaleMinutes,
  "-HardStuckMinutes", $HardStuckMinutes
) -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argLine -WorkingDirectory $repo
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn
$triggerStartup = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Days 365) `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($triggerLogon, $triggerStartup) -Settings $settings -Force | Out-Null

Write-Host "Task registered: $TaskName"
Write-Host ("Runs watchdog at startup + logon with auto-restart on failure (check={0}m stale={1}m hard_stuck={2}m)." -f $CheckIntervalMinutes, $StaleMinutes, $HardStuckMinutes)
Write-Host "To remove: Unregister-ScheduledTask -TaskName `"$TaskName`" -Confirm:`$false"
if ($RunNow) {
  Start-ScheduledTask -TaskName $TaskName
  Write-Host "Task started now."
}
