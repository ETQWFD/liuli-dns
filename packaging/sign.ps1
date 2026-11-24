# Authenticode signing helper.
#
# The private key MUST remain on the signing machine / HSM.  This script only
# addresses a certificate already installed in the Windows certificate store by
# its thumbprint; it never reads, copies or prints a PFX password or key.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File packaging\sign.ps1 `
#     -Target dist\LiuliDNS\LiuliDNS.exe -Thumbprint "<thumbprint>"
#   powershell ... -Target dist\LiuliDNS-Setup-0.1.0.exe -Thumbprint "<thumbprint>"

param(
    [Parameter(Mandatory = $true)]
    [string[]]$Target,
    [Parameter(Mandatory = $true)]
    [string]$Thumbprint,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $roots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "$env:ProgramFiles\Windows Kits\10\bin"
    ) | Where-Object { Test-Path $_ }
    foreach ($root in $roots) {
        $hit = Get-ChildItem $root -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\x64\\signtool.exe$" } |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    throw "signtool.exe not found. Install the Windows SDK signing tools."
}

$thumb = ($Thumbprint -replace " ", "").ToUpperInvariant()
$cert = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My -ErrorAction SilentlyContinue |
    Where-Object { $_.Thumbprint -eq $thumb } | Select-Object -First 1
if (-not $cert) {
    throw "Certificate $thumb not found in CurrentUser\My or LocalMachine\My."
}
if (-not $cert.HasPrivateKey) {
    throw "Certificate $thumb has no private key on this machine. Signing must run on the signing machine/HSM."
}
if ($cert.NotAfter -lt (Get-Date)) {
    throw "Certificate $thumb expired on $($cert.NotAfter)."
}

$signtool = Find-SignTool
foreach ($file in $Target) {
    if (-not (Test-Path $file)) { throw "Target not found: $file" }
    Write-Host "Signing $file"
    & $signtool sign /sha1 $thumb /fd SHA256 /tr $TimestampUrl /td SHA256 /v $file
    if ($LASTEXITCODE -ne 0) { throw "signtool sign failed for $file" }
    & $signtool verify /pa /v $file
    if ($LASTEXITCODE -ne 0) { throw "signature verification failed for $file" }
}
Write-Host "Signed and verified: $($Target -join ', ')"
Write-Host "Publisher subject: $($cert.Subject)"
Write-Host "Do not copy the private key, PFX or HSM credentials into the repository or the app."
