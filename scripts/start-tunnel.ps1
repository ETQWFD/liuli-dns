# Local launcher for the Go tunnel supervisor (Windows).
param([string]$Config = "$env:LOCALAPPDATA\LiuliDNS\server\tunnel\tunnel.json")
$ErrorActionPreference = "Stop"
$bin = Join-Path $PSScriptRoot "..\build-tools\tunnel-dist\liuli-tunnel.exe"
if (-not (Test-Path $bin)) { throw "liuli-tunnel.exe not found: $bin" }
if (-not (Test-Path $Config)) { throw "tunnel config not found: $Config" }
& $bin run --config $Config
