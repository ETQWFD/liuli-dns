# Fail-closed secret scan for Windows build/release machines.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\check_secrets.ps1 -Root .
param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)
$ErrorActionPreference = "Stop"
Set-Location $Root

$targets = @("client", "backend\app", "packaging", "deploy", "docs", "scripts", "README.md", "LICENSE", "LICENSE-CLIENT") |
    Where-Object { Test-Path $_ }

$patterns = @(
    '-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'AKIA[0-9A-Z]{16}',
    'ghp_[A-Za-z0-9]{36}',
    'github_pat_[A-Za-z0-9_]{20,}',
    'sk-[A-Za-z0-9]{32,}',
    'xox[baprs]-[A-Za-z0-9-]{10,}',
    'LIULI_(SECRET_KEY|CERT_MASTER_KEY|CODE_PEPPER|DOC_PEPPER|ADMIN_PASSWORD_HASH|ADMIN_TOTP_SECRET|SMTP_PASSWORD)=[A-Za-z0-9_+/=-]{40,}',
    '(password|passwd|secret|api_key|access_token|refresh_token)[ \t]*[:=][ \t]*["''][A-Za-z0-9_./+=-]{24,}["'']',
    'Authorization:[ \t]*Bearer[ \t]+[A-Za-z0-9._-]{30,}'
)

$excludeDirs = @(".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "dist", "build", "data", "tests", "screenshots")
$hits = @()
foreach ($pat in $patterns) {
    $files = Get-ChildItem $targets -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
        $p = $_.FullName
        ($excludeDirs | Where-Object { $p -match "\\$_\$" }).Count -eq 0 -and
        $_.Extension -notin @(".png", ".jpg", ".jpeg", ".ico", ".pdf", ".zip", ".so", ".dll", ".exe") -and
        $_.Name -notin @(".env.example", "check_secrets.sh", "check_secrets.ps1")
    }
    foreach ($f in $files) {
        $m = Select-String -Path $f.FullName -Pattern $pat -AllMatches -ErrorAction SilentlyContinue
        foreach ($x in $m) { $hits += "$($f.FullName):$($x.LineNumber):$($x.Line.Trim())" }
    }
}

$badFiles = Get-ChildItem . -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -in @(".env", ".pfx", ".p12") -or $_.Extension -in @(".pem", ".key") -or $_.Name -eq "id_rsa"
} | Where-Object { $_.FullName -notmatch "\\.venv\\|\\.git\\|\\data\\|\\docs\\screenshots\\" }
foreach ($f in $badFiles) { $hits += "FORBIDDEN FILE: $($f.FullName)" }

if ($hits.Count -gt 0) {
    $hits | Select-Object -Unique | ForEach-Object { Write-Host $_ }
    throw "Secret scan failed: remove tokens, private keys, .env or key material before release."
}
Write-Host "[secrets] OK: no obvious token, private key, .env or certificate key file."
