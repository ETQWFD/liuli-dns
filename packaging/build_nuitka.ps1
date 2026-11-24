# Optional Nuitka build (standalone, then wrapped by the same NSIS script).
# Run on Windows after activating a clean virtual environment.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_nuitka.ps1
#
# Nuitka is an alternative to PyInstaller; do not ship both payloads.

param(
    [string]$Python = "python",
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $Python -m venv .venv
}
$py = Join-Path $Root ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip wheel
& $py -m pip install -r client\requirements.txt
& $py -m pip install "nuitka>=2.6,<3" ordered-set zstandard

& (Join-Path $Root "scripts\check_secrets.ps1") -Root $Root

& $py -m nuitka `
    --standalone `
    --assume-yes-for-downloads `
    --enable-plugin=pyside6 `
    --windows-console-mode=disable `
    --windows-icon-from-ico=client\resources\app-icon.ico `
    --include-data-dir=client\app\qml=client\app\qml `
    --include-data-dir=client\resources=client\resources `
    --output-dir=dist-nuitka `
    --output-filename=LiuliDNS.exe `
    packaging\entry.py

$built = Join-Path $Root "dist-nuitka\entry.dist"
if (-not (Test-Path (Join-Path $built "LiuliDNS.exe"))) {
    throw "Nuitka output not found. Inspect dist-nuitka\entry.dist."
}
if (Test-Path (Join-Path $Root "dist\LiuliDNS")) {
    Remove-Item (Join-Path $Root "dist\LiuliDNS") -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $Root "dist") -Force | Out-Null
Copy-Item $built (Join-Path $Root "dist\LiuliDNS") -Recurse -Force
Copy-Item README.md (Join-Path $Root "dist\LiuliDNS\README.md") -Force
Copy-Item LICENSE  (Join-Path $Root "dist\LiuliDNS\LICENSE") -Force
Write-Host "Nuitka payload ready: dist\LiuliDNS\LiuliDNS.exe"
Write-Host "Now run makensis /DAPP_VERSION=$Version /DAPP_VERSION4=$Version.0 packaging\installer.nsi"
Write-Host "Then sign the EXE and installer with packaging\sign.ps1 (certificate on this machine only)."
