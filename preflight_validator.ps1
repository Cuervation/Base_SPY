param(
  [string]$DependenciesPath = "parameter_dependencies.json",
  [string]$CandidateConfigPath,
  [string]$ParentConfigPath,
  [string]$ChangeSetPath,
  [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function To-Hashtable([object]$obj) {
  $h = @{}
  if ($null -eq $obj) { return $h }
  if ($obj -is [System.Collections.IDictionary]) {
    foreach ($k in $obj.Keys) { $h[[string]$k] = $obj[$k] }
    return $h
  }
  foreach ($p in $obj.PSObject.Properties) {
    $h[[string]$p.Name] = $p.Value
  }
  return $h
}

function Normalize-Value([object]$v) {
  if ($null -eq $v) { return "" }
  if ($v -is [bool]) { return $(if ([bool]$v) { "true" } else { "false" }) }
  if ($v -is [int] -or $v -is [long] -or $v -is [double] -or $v -is [float] -or $v -is [decimal]) {
    return ([double]$v).ToString("0.############", [System.Globalization.CultureInfo]::InvariantCulture)
  }
  $s = [string]$v
  if ([string]::IsNullOrWhiteSpace($s)) { return "" }
  $t = $s.Trim()
  if ($t -match '^(?i:true|false)$') { return $t.ToLowerInvariant() }
  if ($t -match '^-?\d+([.,]\d+)?$') {
    $n = [double]($t -replace ',', '.')
    return $n.ToString("0.############", [System.Globalization.CultureInfo]::InvariantCulture)
  }
  return $t
}

function Bool-Value([object]$v) {
  if ($v -is [bool]) { return [bool]$v }
  $s = Normalize-Value $v
  return ($s -eq "true" -or $s -eq "1")
}

function Rule-MatchesParameter([hashtable]$rule, [string]$param) {
  if ($rule.ContainsKey("parameter") -and [string]$rule["parameter"] -eq $param) { return $true }
  if ($rule.ContainsKey("parameter_prefix")) {
    $prefix = [string]$rule["parameter_prefix"]
    if (-not [string]::IsNullOrWhiteSpace($prefix) -and $param.StartsWith($prefix)) { return $true }
  }
  return $false
}

$result = [ordered]@{
  pass = $false
  blocked = @()
  warnings = @()
  changed_parameters = @()
  effective_change_check = [ordered]@{
    no_op_detected = $false
    active_logic_changed = $false
    details = @()
  }
}

try {
  if ([string]::IsNullOrWhiteSpace($CandidateConfigPath) -or -not (Test-Path $CandidateConfigPath)) {
    throw "CandidateConfigPath invalido."
  }
  if ([string]::IsNullOrWhiteSpace($ParentConfigPath) -or -not (Test-Path $ParentConfigPath)) {
    throw "ParentConfigPath invalido."
  }
  if ([string]::IsNullOrWhiteSpace($ChangeSetPath) -or -not (Test-Path $ChangeSetPath)) {
    throw "ChangeSetPath invalido."
  }
  if (-not (Test-Path $DependenciesPath)) {
    throw "DependenciesPath invalido."
  }

  $deps = Get-Content -Path $DependenciesPath -Raw | ConvertFrom-Json
  $candidateRaw = Get-Content -Path $CandidateConfigPath -Raw | ConvertFrom-Json
  $parentRaw = Get-Content -Path $ParentConfigPath -Raw | ConvertFrom-Json
  $changesRaw = Get-Content -Path $ChangeSetPath -Raw | ConvertFrom-Json

  $candidate = To-Hashtable $candidateRaw
  $parent = To-Hashtable $parentRaw
  $main = To-Hashtable $changesRaw.main_change
  $dep = To-Hashtable $changesRaw.dependent_change

  if (-not $main.ContainsKey("parameter") -or [string]::IsNullOrWhiteSpace([string]$main["parameter"])) {
    $result.blocked += "Falta main_change.parameter."
  }

  $changedParams = @()
  if ($main.ContainsKey("parameter") -and -not [string]::IsNullOrWhiteSpace([string]$main["parameter"])) {
    $changedParams += [string]$main["parameter"]
  }
  if ($dep.Count -gt 0 -and $dep.ContainsKey("parameter") -and -not [string]::IsNullOrWhiteSpace([string]$dep["parameter"])) {
    $changedParams += [string]$dep["parameter"]
  }
  $changedParams = @($changedParams | Select-Object -Unique)
  $result.changed_parameters = $changedParams

  if ($changedParams.Count -eq 0) {
    $result.blocked += "No hay cambios declarados."
  }
  if ($changedParams.Count -gt 2) {
    $result.blocked += "Se detectaron mas de 2 cambios; maximo permitido: 1 principal + 1 dependiente."
  }

  # No-op real vs parent.
  $effectiveDiffCount = 0
  foreach ($p in $changedParams) {
    $parentV = if ($parent.ContainsKey($p)) { $parent[$p] } else { $null }
    $candV = if ($candidate.ContainsKey($p)) { $candidate[$p] } else { $null }
    if ((Normalize-Value $parentV) -ne (Normalize-Value $candV)) {
      $effectiveDiffCount += 1
      $result.effective_change_check.details += ("effective_diff " + $p + ": " + (Normalize-Value $parentV) + " -> " + (Normalize-Value $candV))
    }
  }
  if ($effectiveDiffCount -eq 0) {
    $result.effective_change_check.no_op_detected = $true
    $result.blocked += "No-op detectado: los cambios no modifican valores efectivos vs parent."
  }

  # Active-logic check.
  $activeChanged = $false
  foreach ($p in $changedParams) {
    $isActive = $true
    if ($p -eq "MAX_CLOSE_VS_SMA50_PCT" -and -not (Bool-Value $candidate["ENABLE_CLOSE_VS_SMA50_FILTER"])) { $isActive = $false }
    if ($p -eq "MAX_AVG_PROFILE_DISTANCE" -and -not (Bool-Value $candidate["ENABLE_AVG_PROFILE_DISTANCE_GATE"])) { $isActive = $false }
    if ($p.StartsWith("MOMENTUM_") -and [string](Normalize-Value $candidate["STRATEGY_FAMILY"]) -ne "momentum_rank") { $isActive = $false }
    if ($isActive) { $activeChanged = $true }
  }
  $result.effective_change_check.active_logic_changed = $activeChanged
  if (-not $activeChanged) {
    $result.blocked += "Cambio no operativo: no altera logica activa del script."
  }

  # Dependency rules.
  $rules = @($deps.rules)
  foreach ($ruleObj in $rules) {
    $rule = To-Hashtable $ruleObj
    $ruleMsg = if ($rule.ContainsKey("block_message")) { [string]$rule["block_message"] } else { "Regla de dependencia violada." }
    $matched = $false
    foreach ($p in $changedParams) {
      if (Rule-MatchesParameter -rule $rule -param $p) { $matched = $true; break }
    }
    if (-not $matched) { continue }

    if ($rule.ContainsKey("requires")) {
      $req = To-Hashtable $rule["requires"]
      foreach ($rk in $req.Keys) {
        $expected = Normalize-Value $req[$rk]
        $actual = if ($candidate.ContainsKey([string]$rk)) { Normalize-Value $candidate[[string]$rk] } else { "" }
        if ($expected -ne $actual) {
          $result.blocked += $ruleMsg
          break
        }
      }
    }

    if ($rule.ContainsKey("requires_any_changed_parameter")) {
      $requiredSet = @($rule["requires_any_changed_parameter"] | ForEach-Object { [string]$_ })
      $hasAny = $false
      foreach ($rp in $requiredSet) {
        if ($changedParams -contains $rp) { $hasAny = $true; break }
      }
      if (-not $hasAny) {
        $result.blocked += $ruleMsg
      }
    }
  }

  # Inactive parameter flag rules.
  $inactiveRules = @($deps.inactive_parameter_flags)
  foreach ($ruleObj in $inactiveRules) {
    $rule = To-Hashtable $ruleObj
    if (-not $rule.ContainsKey("parameter") -or -not $rule.ContainsKey("activation_flag")) { continue }
    $param = [string]$rule["parameter"]
    $flag = [string]$rule["activation_flag"]
    if (-not ($changedParams -contains $param)) { continue }
    if (-not (Bool-Value $candidate[$flag])) {
      $changedFlag = ($changedParams -contains $flag)
      if (-not $changedFlag) {
        $result.blocked += ("Parametro apagado: " + $param + " requiere activar " + $flag + " en la misma iteracion.")
      } else {
        $result.blocked += ("Cambio invalido: " + $param + " permanece inactivo porque " + $flag + "=False.")
      }
    }
  }

  $result.pass = ($result.blocked.Count -eq 0)
} catch {
  $result.pass = $false
  $result.blocked += ("preflight_exception: " + $_.Exception.Message)
}

$json = $result | ConvertTo-Json -Depth 8
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
  $json | Set-Content -Path $OutputPath -Encoding UTF8
}
Write-Output $json
exit 0
