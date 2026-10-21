$ErrorActionPreference = "Stop"

$isccCandidatos = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)

$iscc = $isccCandidatos | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $iscc) {
    throw "No se encontro Inno Setup. Instala Inno Setup 6 para generar el instalador."
}

$exe = Join-Path $PSScriptRoot "dist\PSTReader.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    & (Join-Path $PSScriptRoot "build.ps1")
}

Push-Location $PSScriptRoot
try {
    & $iscc /Qp "installer.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup fallo con codigo $LASTEXITCODE."
    }
    Write-Output "Instalador generado en dist\PSTReader-1.0.0-Setup.exe"
}
finally {
    Pop-Location
}
