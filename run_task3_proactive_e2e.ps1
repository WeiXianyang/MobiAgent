param(
  [string]$ServiceIp = "127.0.0.1",
  [int]$ModelPort = 7000,
  [string]$ModelName = "fengerhu1/MobiMind-1.5-4B",
  [string]$ModelBaseUrl = $env:TASK3_MODEL_BASE_URL,
  [ValidateSet("Android", "Harmony")]
  [string]$Device = "Android",
  [switch]$UseLocalPort,
  [switch]$SkipRemoteCheck,
  [switch]$SkipDeviceCheck,
  [switch]$SkipRag,
  [switch]$ExecuteServiceOpportunities,
  [string]$ScheduledInstruction = "0分钟后打开淘宝搜索护肤品",
  [string]$ScheduledNow = "2026-05-26T00:00:00"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
  $Py = "python"
}

$Task2Artifacts = Join-Path $RepoRoot "runner\mobiagent\profile_pipeline\artifacts"
$Task3Artifacts = Join-Path $RepoRoot "runner\mobiagent\proactive_service\artifacts"
$Task3Report = Join-Path $RepoRoot "docs\task3\task3-proactive-service-report.md"

$env:MOBIAGENT_DECIDER_MODEL = $ModelName
$env:MOBIAGENT_GROUNDER_MODEL = $ModelName
$env:MOBIAGENT_PLANNER_MODEL = $ModelName

if (-not $UseLocalPort) {
  if ([string]::IsNullOrWhiteSpace($ModelBaseUrl)) {
    throw "ModelBaseUrl is required when -UseLocalPort is not set. Pass -ModelBaseUrl or set TASK3_MODEL_BASE_URL."
  }
  $env:MOBIAGENT_DECIDER_BASE_URL = $ModelBaseUrl
  $env:MOBIAGENT_GROUNDER_BASE_URL = $ModelBaseUrl
  $env:MOBIAGENT_PLANNER_BASE_URL = $ModelBaseUrl
} else {
  Remove-Item Env:\MOBIAGENT_DECIDER_BASE_URL -ErrorAction SilentlyContinue
  Remove-Item Env:\MOBIAGENT_GROUNDER_BASE_URL -ErrorAction SilentlyContinue
  Remove-Item Env:\MOBIAGENT_PLANNER_BASE_URL -ErrorAction SilentlyContinue
}

Push-Location $RepoRoot
try {
  & $Py -m runner.mobiagent.profile_pipeline.cli build-profile
  if ($LASTEXITCODE -ne 0) { throw "task2 build-profile failed" }

  if (-not $SkipRag) {
    & $Py -m runner.mobiagent.profile_pipeline.cli build-rag
    if ($LASTEXITCODE -ne 0) { throw "task2 build-rag failed" }
  }

  $doctorArgs = @(
    "-m", "runner.mobiagent.proactive_service.cli", "doctor",
    "--strict",
    "--artifacts-dir", $Task2Artifacts,
    "--output-dir", $Task3Artifacts,
    "--service-ip", $ServiceIp,
    "--model-port", "$ModelPort",
    "--model-name", $ModelName
  )
  if (-not $UseLocalPort) {
    $doctorArgs += @("--model-base-url", $ModelBaseUrl)
  }
  if ($SkipRemoteCheck) {
    $doctorArgs += "--skip-remote-check"
  }
  if ($SkipDeviceCheck) {
    $doctorArgs += "--skip-device-check"
  }
  & $Py @doctorArgs
  if ($LASTEXITCODE -ne 0) { throw "task3 doctor failed" }

  & $Py -m runner.mobiagent.proactive_service.cli complete-task --task "帮我处理近期购物需求" --artifacts-dir $Task2Artifacts --output-dir $Task3Artifacts
  if ($LASTEXITCODE -ne 0) { throw "task3 complete-task failed" }

  & $Py -m runner.mobiagent.proactive_service.cli plan-service-opportunities --artifacts-dir $Task2Artifacts --output-dir $Task3Artifacts --service-ip $ServiceIp --model-port $ModelPort --model-name $ModelName --device $Device
  if ($LASTEXITCODE -ne 0) { throw "task3 plan-service-opportunities failed" }

  if ($ExecuteServiceOpportunities) {
    $executeArgs = @(
      "-m", "runner.mobiagent.proactive_service.cli", "execute-service-opportunities",
      "--execute",
      "--artifacts-dir", $Task2Artifacts,
      "--output-dir", $Task3Artifacts,
      "--service-ip", $ServiceIp,
      "--model-port", "$ModelPort",
      "--model-name", $ModelName,
      "--device", $Device
    )
    if (-not $UseLocalPort) {
      $executeArgs += @("--model-base-url", $ModelBaseUrl)
    }
    & $Py @executeArgs
    if ($LASTEXITCODE -ne 0) { throw "task3 execute-service-opportunities failed" }
  }

  $createScheduledArgs = @(
    "-m", "runner.mobiagent.proactive_service.cli", "create-scheduled-todo",
    "--instruction", $ScheduledInstruction,
    "--now", $ScheduledNow,
    "--output-dir", $Task3Artifacts,
    "--model-name", $ModelName,
    "--device", $Device
  )
  if (-not $UseLocalPort) {
    $createScheduledArgs += @("--model-base-url", $ModelBaseUrl)
  }
  & $Py @createScheduledArgs
  if ($LASTEXITCODE -ne 0) { throw "task3 create-scheduled-todo failed" }

  & $Py -m runner.mobiagent.proactive_service.cli run-scheduled-todos --now $ScheduledNow --output-dir $Task3Artifacts --service-ip $ServiceIp --model-port $ModelPort
  if ($LASTEXITCODE -ne 0) { throw "task3 run-scheduled-todos failed" }

  & $Py -m runner.mobiagent.proactive_service.cli weekly-report --artifacts-dir $Task2Artifacts --output-dir $Task3Artifacts --days 7
  if ($LASTEXITCODE -ne 0) { throw "task3 weekly-report failed" }

  & $Py -m runner.mobiagent.proactive_service.cli export-ppt-outline --artifacts-dir $Task2Artifacts --output-dir $Task3Artifacts --days 7
  if ($LASTEXITCODE -ne 0) { throw "task3 export-ppt-outline failed" }

  & $Py -m runner.mobiagent.proactive_service.cli export-image-prompts --artifacts-dir $Task2Artifacts --output-dir $Task3Artifacts --days 7
  if ($LASTEXITCODE -ne 0) { throw "task3 export-image-prompts failed" }

  & $Py -m runner.mobiagent.proactive_service.cli report --artifacts-dir $Task2Artifacts --output-dir $Task3Artifacts --report-path $Task3Report
  if ($LASTEXITCODE -ne 0) { throw "task3 report failed" }
} finally {
  Pop-Location
}
