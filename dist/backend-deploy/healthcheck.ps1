# PyMentor Lab v1.1 - healthcheck (Windows PowerShell).
#
# Polls the API /health endpoint and prints `docker compose ps` for the
# pymentor-prod project. Exits 0 when healthy, non-zero after the timeout.
#
#   .\healthcheck.ps1 [-TimeoutSeconds 120]

[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$ProjectName = 'pymentor-prod'
$HealthUrl   = 'http://localhost:8000/health'

function Write-Log    { param([string]$Msg) Write-Host "[health] $Msg" }
function Write-ErrLog { param([string]$Msg) Write-Host "[health][ERROR] $Msg" -ForegroundColor Red }

$elapsed = 0
while ($elapsed -lt $TimeoutSeconds) {
    try {
        $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Write-Log "API healthy ($HealthUrl, waited ${elapsed}s)."
            if ((Test-Path 'code')) {
                Push-Location 'code'
                try { docker compose -p $ProjectName ps } finally { Pop-Location }
            }
            exit 0
        }
    } catch {
        # not ready yet
    }
    Start-Sleep -Seconds 3
    $elapsed += 3
    Write-Host -NoNewline '.'
}
Write-Host ''

Write-ErrLog "API not healthy after $TimeoutSeconds s."
if (Test-Path 'code') {
    Push-Location 'code'
    try {
        docker compose -p $ProjectName ps
        Write-ErrLog 'Recent API logs:'
        docker compose -p $ProjectName logs --tail=40 api
    } finally { Pop-Location }
}
exit 1
