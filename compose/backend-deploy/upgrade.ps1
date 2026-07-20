# ===========================================================================
#  PyMentor Lab - Upgrade (Windows / PowerShell)
#  --------------------------------------------------------------------------
#  Pulls/Builds new images, performs a rolling recreate of services, and
#  runs a healthcheck. Data volumes are preserved.
#
#  Usage:
#      .\upgrade.ps1                # rebuild + recreate + healthcheck
#      .\upgrade.ps1 -NoBuild       # reuse existing images
# ===========================================================================
[CmdletBinding()]
param([switch]$NoBuild)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "==> PyMentor Lab upgrade starting..." -ForegroundColor Cyan
if (-not (Test-Path .env)) { Write-Error ".env missing."; exit 1 }

if (-not $NoBuild) {
    Write-Host "    Building new images..." -ForegroundColor Cyan
    docker compose build
    if ($LASTEXITCODE -ne 0) { Write-Error "build failed"; exit 1 }
}

Write-Host "    Recreating services (no volume loss)..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { Write-Error "up failed"; exit 1 }

Write-Host "    Running healthcheck..." -ForegroundColor Cyan
& "$PSScriptRoot\healthcheck.ps1"
