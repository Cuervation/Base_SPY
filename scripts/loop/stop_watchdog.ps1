param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = $PSScriptRoot
Set-Location $repo
$repoRoot = Resolve-Path (Join-Path $repo "..\\..")
$logDir = Join-Path $repoRoot "logs\\autonomous_loop"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$pidFile = Join-Path $logDir "watchdog.pid"
$lockFile = Join-Path $logDir "watchdog.lock"
$stopFile = Join-Path $logDir "watchdog.stop"
$stopLog = Join-Path $logDir "watchdog_stop.log"

function Write-StopLog([string]$Message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "[$ts] $Message"
  Add-Content -LiteralPath $stopLog -Encoding UTF8 -Value $line
}

function Read-Lock {
  if (-not (Test-Path -LiteralPath $lockFile)) { return $null }
  try {
    return (Get-Content -LiteralPath $lockFile -Raw -Encoding UTF8 | ConvertFrom-Json)
  } catch {
    return $null
  }
}

Write-StopLog "stop requested"
if (Test-Path -LiteralPath $stopFile) {
  Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
}

$pid = $null
if (Test-Path -LiteralPath $pidFile) {
  try { $pid = [int]((Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8).Trim()) } catch { $pid = $null }
}

$lock = Read-Lock
if ($null -ne $lock -and $null -eq $pid) {
  try { $pid = [int]$lock.pid } catch { $pid = $null }
}

if ($pid) {
  try {
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if ($proc) {
      Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
      Write-StopLog "process stopped pid=$pid"
    } else {
      Write-StopLog "process already absent pid=$pid"
    }
  } catch {
    Write-StopLog ("stop_error pid={0} err={1}" -f $pid, $_.Exception.Message)
  }
} else {
  Write-StopLog "no pid found"
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
Write-StopLog "cleanup complete"
exit 0
