$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "No se encontro .venv. Crea el entorno e instala requirements.txt."
}

Push-Location $PSScriptRoot
try {
    & $python -m PyInstaller --noconfirm --clean PSTReader.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller fallo con codigo $LASTEXITCODE."
    }
    Write-Output "Ejecutable generado en dist\PSTReader.exe"
}
finally {
    Pop-Location
}
