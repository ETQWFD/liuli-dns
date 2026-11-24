# LiuliDNS Windows build (PyInstaller + NSIS).
# Run on a Windows 10/11 x64 build machine, not on the Linux source host.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 `
#       -Thumbprint "<code-signing certificate thumbprint>"
#
# The signing certificate's private key stays in the Windows certificate store
# or an HSM on the signing machine.  This repository never contains a PFX,
# password, token or private key.

param(
    [string]$Python = "python",
    [string]$Thumbprint = $env:LIULI_SIGN_THUMBPRINT,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [string]$Version = "0.1.0",
    [switch]$SkipInstaller,
    [switch]$SkipSign
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Find-Tool([string]$Name, [string[]]$Candidates) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in $Candidates) {
        if (Test-Path $c) { return $c }
    }
    throw "Cannot find $Name. Install it or add it to PATH."
}

Write-Host "[1/6] Python virtual environment"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $Python -m venv .venv
}
$py = Join-Path $Root ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip wheel
& $py -m pip install -r client\requirements.txt
& $py -m pip install "pyinstaller==6.11.1"

Write-Host "[2/6] Static secret scan"
& (Join-Path $Root "scripts\check_secrets.ps1") -Root $Root

Write-Host "[3/6] PyInstaller onedir build"
& $py -m PyInstaller --noconfirm --clean packaging\liuli.spec
Copy-Item README.md (Join-Path $Root "dist\LiuliDNS\README.md") -Force
Copy-Item LICENSE  (Join-Path $Root "dist\LiuliDNS\LICENSE") -Force
Copy-Item docs\04-security-boundaries.md (Join-Path $Root "dist\LiuliDNS\SECURITY-BOUNDARIES.md") -Force

$exe = Join-Path $Root "dist\LiuliDNS\LiuliDNS.exe"
if (-not (Test-Path $exe)) { throw "Build failed: $exe not found" }

if (-not $SkipSign) {
    if (-not $Thumbprint) {
        Write-Warning "No -Thumbprint supplied. The EXE and installer will be UNSIGNED."
        Write-Warning "Do not publish unsigned builds as official releases."
    } else {
        Write-Host "[4/6] Authenticode signature on the EXE"
        & (Join-Path $Root "packaging\sign.ps1") -Target $exe -Thumbprint $Thumbprint -TimestampUrl $TimestampUrl
    }
} else {
    Write-Host "[4/6] Signing skipped"
}

if (-not $SkipInstaller) {
    Write-Host "[5/6] NSIS installer"
    $makensis = Find-Tool "makensis.exe" @(
        "$env:ProgramFiles\NSIS\makensis.exe",
        "${env:ProgramFiles(x86)}\NSIS\makensis.exe"
    )
    $Version4 = "$Version.0"
    & $makensis "/DAPP_VERSION=$Version" "/DAPP_VERSION4=$Version4" `
        "/DDIST_DIR=$Root\dist" "/DICON_PATH=$Root\client\resources\app-icon.ico" `
        "packaging\installer.nsi"
    $installer = Join-Path $Root "dist\LiuliDNS-Setup-$Version.exe"
    if (-not (Test-Path $installer)) { throw "Installer not found: $installer" }

    if (-not $SkipSign -and $Thumbprint) {
        Write-Host "[5b/6] Authenticode signature on the installer"
        & (Join-Path $Root "packaging\sign.ps1") -Target $installer -Thumbprint $Thumbprint -TimestampUrl $TimestampUrl
    }
}

Write-Host "[6/6] SHA-256 and release inventory"
$hashFile = Join-Path $Root "dist\SHA256SUMS.txt"
Get-ChildItem (Join-Path $Root "dist") -File | Where-Object {
    $_.Name -like "LiuliDNS-Setup-*.exe" -or $_.Name -eq "LiuliDNS.exe"
} | ForEach-Object {
    $h = Get-FileHash $_.FullName -Algorithm SHA256
    "$($h.Hash.ToLower())  $($_.Name)"
} | Set-Content -Encoding ascii $hashFile

Write-Host "Build complete. Release files:"
Get-ChildItem (Join-Path $Root "dist") -File | Select-Object Name, Length
Write-Host "Verify: signtool verify /pa /v dist\LiuliDNS.exe"
Write-Host "Installer: dist\LiuliDNS-Setup-$Version.exe"
Write-Host "Never commit .venv, dist, build, PFX files, tokens or private keys."
