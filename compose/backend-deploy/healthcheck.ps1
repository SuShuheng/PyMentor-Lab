# ===========================================================================
#  PyMentor Lab - Healthcheck (Windows / PowerShell)
#  --------------------------------------------------------------------------
#  Probes all compose services and reports their status. Exits 0 when every
#  service is healthy, non-zero otherwise.
# ===========================================================================
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not (Test-Path .env)) { Write-Error ".env missing. Run deploy.ps1 first."; exit 1 }

$status = docker compose ps --format '{{.Name}} {{.Status}}' 2>$null
$unhealthy = $status | Where-Object { $_ -notmatch '(healthy|running)' -and $_ -ne '' }

Write-Host "Service status:"
$status | ForEach-Object { Write-Host "  $_" }

if ($unhealthy) {
    Write-Host ""
    Write-Host "Unhealthy services:" -ForegroundColor Red
    $unhealthy | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    exit 1
}
Write-Host ""
Write-Host "All services healthy." -ForegroundColor Green
exit 0
