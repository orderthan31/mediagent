param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('analyze','extract_audio','generate_subtitle','encode','validate_video')]
    [string]$Agent,
    [Parameter(Mandatory=$true)][string]$InputRoot,
    [Parameter(Mandatory=$true)][string]$OutputRoot
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$env:PYTHONPATH = "$projectRoot\packages\shared;$projectRoot\agents\cpu"
Push-Location $projectRoot
try {
    $pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = 'python' }
    # Accept exactly one JSON command from stdin; never load legacy queue/settings.
    & $pythonPath -m video_service.cpu_agents --agent $Agent --input-root $InputRoot --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) { throw 'The explicit CPU command failed; receipt is preserved.' }
} finally {
    Pop-Location
}
