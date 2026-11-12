param(
    [int]$Port = 8001
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = $PSScriptRoot
$python = Join-Path $workspaceRoot '.venv\Scripts\python.exe'
$projectRoot = Join-Path $workspaceRoot 'AutoLedger_Local_Starter'

if (-not (Test-Path $python)) {
    throw "Virtual environment not found at $python. Create .venv and install requirements first."
}

Push-Location $workspaceRoot
try {
    & $python -m uvicorn backend.main:app --reload --app-dir $projectRoot --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Uvicorn exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}