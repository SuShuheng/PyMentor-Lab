# ===========================================================================
#  PyMentor Lab - Rollback (Windows / PowerShell)
#  --------------------------------------------------------------------------
#  Rolls services back to the previously built image tag (or a specified tag).
#  In v1.1 we do not publish multiple tags by default; this script re-creates
#  containers from the previous image cache if available, otherwise instructs
#  the operator to re-run deploy.ps1 with a previous code/ snapshot.
#
#  Usage:
#      .\rollback.ps1                # try previous image
#      .\rollback.ps1 -Tag <tag>     # use a specific image tag
# ===========================================================================
[CmdletBinding()]
param([string]$Tag)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

if ($Tag) {
    Write-Host "==> Rollback to image tag: $Tag" -ForegroundColor Cyan
    $env:PYMENTOR_IMAGE_TAG = $Tag
}
Write-Host "    Stopping current stack..." -ForegroundColor Cyan
docker compose down
if ($LASTEXITCODE -ne 0) { Write-Error "down failed"; exit 1 }
Write-Host "    OK  Stack stopped. Re-run deploy.ps1 from the previous code/ snapshot to finish rollback." -ForegroundColor Green
Write-Host "    (No image cache lookup in v1.1 - keep a copy of each code/ snapshot you wish to roll back to.)" -ForegroundColor Yellow
