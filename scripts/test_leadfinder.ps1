$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "..\.venv\Scripts\python.exe"

Push-Location $projectRoot
try {
    & $python manage.py check
    & $python -m pytest
}
finally {
    Pop-Location
}
