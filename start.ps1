param(
    [int]$Port = 8001
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = $PSScriptRoot
$projectRoot = Join-Path $workspaceRoot 'AutoLedger_Local_Starter'
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$workspacePython = Join-Path $workspaceRoot '.venv\Scripts\python.exe'

if (Test-Path $projectPython) {
    $python = $projectPython
}
elseif (Test-Path $workspacePython) {
    $python = $workspacePython
}
else {
    throw "Virtual environment not found. Create .venv in the project or workspace root and install requirements first."
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