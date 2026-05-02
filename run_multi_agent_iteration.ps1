param(
  [string]$PythonExe = "python",
  [string]$BaselineJson = "state/current_baseline.json",
  [string]$ExperimentLog = "trackers/experiment_log.csv",
  [string]$DependenciesJson = "config/parameter_dependencies.json",
  [string]$EvaluationWindows = "4,8,24,52",
  [int]$YearValidationWindowWeeks = 156,
  [string]$Long156Policy = "cadence_only",
  [int]$Long156CadenceUsefulRuns = 4,
  [double]$Long156MinW52SpyCompare = 0.5,
  [double]$Long156MinW52WeeksTraded = 20.0,
  [double]$Long156MinW52Trades = 15.0,
  [int]$XlsxCadenceRuns = 5,
  [int]$ProfileCadenceRuns = 10,
  [switch]$DisableFastArtifacts,
  [switch]$DisableWindowReuse,
  [switch]$AllowProgressiveWindows,
  [int]$MinYearsVsSpy = 2,
  [int]$MaxNonPositiveYearsVsSpy = 0,
  [double]$TieLowPct = 0.0,
  [double]$TieHighPct = 1.0,
  [int]$TimeoutSecPerRun = 5400,
  [switch]$SkipIterationAudit,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = $PSScriptRoot
Set-Location $repo

# Prefer config/paths_config.json when present (reorg compatibility).
$pathsConfigPath = Join-Path $repo "config\\paths_config.json"
$pathsCfg = $null
if (Test-Path -LiteralPath $pathsConfigPath) {
  try { $pathsCfg = (Get-Content -LiteralPath $pathsConfigPath -Raw | ConvertFrom-Json) } catch { $pathsCfg = $null }
}
if ($pathsCfg -ne $null) {
  if ($pathsCfg.state.current_baseline) { $BaselineJson = [string]$pathsCfg.state.current_baseline }
  if ($pathsCfg.trackers.experiment_log) { $ExperimentLog = [string]$pathsCfg.trackers.experiment_log }
  # DependenciesJson is already under config/ by default.
}

function Resolve-Python([string]$candidate) {
  try {
    $cmd = Get-Command $candidate -ErrorAction Stop
    return $cmd.Source
  } catch {
    $fallback = "C:\Users\celestinoh\AppData\Local\Programs\Python\Python312\python.exe"
    if (Test-Path $fallback) { return $fallback }
    throw "No se encontro Python."
  }
}

$py = Resolve-Python $PythonExe
$script = Join-Path $repo "run_multi_agent_iteration.py"
if (-not (Test-Path $script)) { throw "No existe $script" }

  $argList = @(
    "--repo", "$repo",
    "--baseline-json", "$BaselineJson",
    "--experiment-log", "$ExperimentLog",
    "--dependencies-json", "$DependenciesJson",
    "--evaluation-windows", "$EvaluationWindows",
    "--year-validation-window-weeks", "$YearValidationWindowWeeks",
    "--long156-policy", "$Long156Policy",
  "--long156-cadence-useful-runs", "$Long156CadenceUsefulRuns",
  "--long156-min-w52-spy-compare", "$Long156MinW52SpyCompare",
  "--long156-min-w52-weeks-traded", "$Long156MinW52WeeksTraded",
  "--long156-min-w52-trades", "$Long156MinW52Trades",
  "--xlsx-cadence-runs", "$XlsxCadenceRuns",
  "--profile-cadence-runs", "$ProfileCadenceRuns",
  "--min-years-vs-spy", "$MinYearsVsSpy",
  "--max-nonpositive-years-vs-spy", "$MaxNonPositiveYearsVsSpy",
  "--tie-low", "$TieLowPct",
  "--tie-high", "$TieHighPct",
  "--timeout-sec-per-run", "$TimeoutSecPerRun"
)
if ($DisableFastArtifacts) { $argList += "--disable-fast-artifacts" }
if ($DisableWindowReuse) { $argList += "--disable-window-reuse" }
if ($AllowProgressiveWindows) { $argList += "--allow-progressive-windows" }
if ($DryRun) { $argList += "--dry-run" }

& $py $script @argList

$runRc = $LASTEXITCODE

if ($SkipIterationAudit) {
  Write-Warning "SkipIterationAudit fue solicitado, pero ETAPA 6 fuerza actualizacion de run_analysis_current.md e iteration_review_last_15.md."
}
$analysisScript = Join-Path $repo "scripts\\reports\\generate_run_analysis.py"
if (-not (Test-Path -LiteralPath $analysisScript)) {
  throw "No existe scripts\\reports\\generate_run_analysis.py (restructure required)."
}
try {
  & $py $analysisScript --repo "$repo" | Out-Host
} catch {
  Write-Warning ("No se pudo actualizar el reporte de auditoria post-run: {0}" -f $_.Exception.Message)
}

exit $runRc
