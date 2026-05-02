param(
  [int]$PollSeconds = 60
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = $PSScriptRoot
Set-Location $repo
$repoRoot = Resolve-Path (Join-Path $repo "..\\..")
$logDir = Join-Path $repoRoot "logs\\autonomous_loop"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$watchdogScript = Join-Path $repo "watch_autonomous_loop.ps1"
$pidFile = Join-Path $logDir "watchdog.pid"
$lockFile = Join-Path $logDir "watchdog.lock"
$startLog = Join-Path $logDir "watchdog_start.log"
$stopFile = Join-Path $logDir "watchdog.stop"

function Write-StartLog([string]$Message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "[$ts] $Message"
  Add-Content -LiteralPath $startLog -Encoding UTF8 -Value $line
}

function Read-Lock {
  if (-not (Test-Path -LiteralPath $lockFile)) { return $null }
  try {
    return (Get-Content -LiteralPath $lockFile -Raw -Encoding UTF8 | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Test-AlivePid([object]$PidValue) {
  try {
    $pid = [int]$PidValue
    return [bool](Get-Process -Id $pid -ErrorAction SilentlyContinue)
  } catch {
    return $false
  }
}

Write-StartLog "start requested poll_seconds=$PollSeconds"
if (Test-Path -LiteralPath $stopFile) {
  Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
}

$existingPid = $null
if (Test-Path -LiteralPath $pidFile) {
  try { $existingPid = [int]((Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8).Trim()) } catch { $existingPid = $null }
}
$lock = Read-Lock
if ($null -ne $lock -and (Test-AlivePid $lock.pid)) {
  Write-StartLog "watchdog already running pid=$($lock.pid)"
  exit 0
}
if ($existingPid -and (Test-AlivePid $existingPid)) {
  Write-StartLog "watchdog already running pid=$existingPid"
  exit 0
}

if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue }
if (Test-Path -LiteralPath $lockFile) { Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue }

$lockObj = [pscustomobject]@{
  pid = $null
  started_at = (Get-Date).ToString("o")
  poll_seconds = $PollSeconds
  script = $watchdogScript
}
$lockJson = $lockObj | ConvertTo-Json -Depth 4
Set-Content -LiteralPath $lockFile -Value $lockJson -Encoding UTF8

$startOut = Join-Path $logDir "watchdog_start_stdout.log"
$startErr = Join-Path $logDir "watchdog_start_stderr.log"
$proc = Start-Process -FilePath "C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" `
  -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $watchdogScript,
    "-PollSeconds", $PollSeconds,
    "-StopFile", $stopFile
  ) `
  -WorkingDirectory $repoRoot `
  -WindowStyle Hidden `
  -PassThru `
  -RedirectStandardOutput $startOut `
  -RedirectStandardError $startErr

$lockObj.pid = $proc.Id
Set-Content -LiteralPath $lockFile -Value ($lockObj | ConvertTo-Json -Depth 4) -Encoding UTF8
[string]$proc.Id | Set-Content -LiteralPath $pidFile -Encoding UTF8

Write-StartLog "watchdog started pid=$($proc.Id) pid_file=$pidFile lock_file=$lockFile"
Write-StartLog "watchdog log=$([string](Join-Path $logDir 'watchdog.log'))"
Write-StartLog "watchdog stdout=$startOut stderr=$startErr"
exit 0
