# PyMentor Lab v1.1 - upgrade / rebuild (Windows PowerShell).
#
# Pulls latest base images, rebuilds every service image from the code\ tree,
# and restarts the stack with the existing volumes intact (so Postgres, Redis,
# and MinIO data survive).
#
# IMPORTANT: take a backup BEFORE upgrading:
#   .\backup.ps1
# If anything goes wrong, see rollback.ps1 (local-build rollback = DB restore).

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$EnvFile     = '.env'
$ProjectName = 'pymentor-prod'

function Write-Log    { param([string]$Msg) Write-Host "[upgrade] $Msg" }
function Write-ErrLog { param([string]$Msg) Write-Host "[upgrade][ERROR] $Msg" -ForegroundColor Red }

if (-not (Test-Path $EnvFile)) {
    Write-ErrLog '.env not found. Run .\deploy.ps1 first to create it from .env.example.'
    exit 1
}
if (-not (Test-Path 'code')) {
    Write-ErrLog "Missing 'code\' directory. Re-extract the new backend-deploy archive over this folder."
    exit 1
}

Write-Log 'Pulling base images and rebuilding services from code\ ...'
Push-Location 'code'
try {
    docker compose -p $ProjectName --env-file ../.env build --pull
    if ($LASTEXITCODE -ne 0) { throw "docker compose build failed with exit code $LASTEXITCODE" }
    docker compose -p $ProjectName --env-file ../.env up -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

Write-Log 'Upgrade complete.'
Write-Host ''
Write-Host '=============================================================================='
Write-Host '  Upgrade finished - next steps'
Write-Host '=============================================================================='
Write-Host '  Verify health:    .\healthcheck.ps1'
Write-Host "  Tail logs:        Push-Location code; docker compose -p $ProjectName logs -f; Pop-Location"
Write-Host ''
Write-Host '  ROLLBACK: local builds have no image registry tags, so rollback is'
Write-Host '  database restore, not image re-tag. If you need to undo this upgrade:'
Write-Host '    1. .\rollback.ps1          (runs docker compose down + restore latest backup)'
Write-Host '    2. OR .\restore.ps1 backups\<latest>.sql.gz'
Write-Host '  Always run .\backup.ps1 BEFORE upgrading.'
Write-Host '=============================================================================='
