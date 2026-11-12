$ErrorActionPreference = 'Stop'

$workspaceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$envPath = Join-Path $workspaceRoot '.env'
$psql = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'

if (-not (Test-Path $envPath)) {
    throw "Workspace .env not found at $envPath. Copy .env.example and configure it first."
}
if (-not (Test-Path $psql)) {
    throw "PostgreSQL psql.exe not found at $psql. Update this script for your installation."
}

$settings = @{}
foreach ($line in Get-Content $envPath) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
        $settings[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'")
    }
}

foreach ($key in @('DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD')) {
    if (-not $settings.ContainsKey($key) -or -not $settings[$key]) {
        throw "Required .env value $key is missing."
    }
}

$previousPassword = $env:PGPASSWORD
$env:PGPASSWORD = $settings['DB_PASSWORD']
try {
    Get-ChildItem $PSScriptRoot -Filter '*.sql' | Sort-Object Name | ForEach-Object {
        Write-Host "Applying additive migration $($_.Name)"
        & $psql -X -w -v ON_ERROR_STOP=1 -h $settings['DB_HOST'] -p $settings['DB_PORT'] -U $settings['DB_USER'] -d $settings['DB_NAME'] -f $_.FullName
        if ($LASTEXITCODE -ne 0) {
            throw "Migration failed: $($_.Name)"
        }
    }
    Write-Host 'Database schema and demo rows are current. Existing rows were not deleted.'
}
finally {
    if ($null -eq $previousPassword) {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
    else {
        $env:PGPASSWORD = $previousPassword
    }
}