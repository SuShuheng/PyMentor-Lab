# PyMentor Lab v1.1 - rollback (Windows PowerShell).
#
# HONEST ROLLBACK MODEL
# ---------------------
# This deployment package builds images locally (no registry). That means there
# are no per-version image tags to switch back to. A real image-tag rollback
# requires pushing images to a registry; we have not done that here.
#
# What this script actually does:
#   1. Stops the running stack (docker compose down) - volumes are preserved.
#   2. Restores Postgres from a backup file. By default the newest file under
#      .\backups\. Pass an explicit path to choose a different one:
#          .\rollback.ps1 backups\pymentor-20260719-103015.sql.gz
#
# To roll back the CODE (not just the data), drop the previous backend-deploy
# archive in place of code\, then run .\upgrade.ps1. Always .\backup.ps1 first.

[CmdletBinding()]
param(
    [string]$BackupFile = ''
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$EnvFile     = '.env'
$ProjectName = 'pymentor-prod'
$BackupsDir  = 'backups'

function Write-Log    { param([string]$Msg) Write-Host "[rollback] $Msg" }
function Write-ErrLog { param([string]$Msg) Write-Host "[rollback][ERROR] $Msg" -ForegroundColor Red }

if (-not (Test-Path $EnvFile)) {
    Write-ErrLog '.env not found. Run .\deploy.ps1 first.'
    exit 1
}
if (-not (Test-Path 'code')) {
    Write-ErrLog "Missing 'code\' directory."
    exit 1
}

# Resolve the backup file: either the explicit arg, or the newest in .\backups.
if (-not $BackupFile) {
    if (-not (Test-Path $BackupsDir)) {
        Write-ErrLog "No backup specified and no $BackupsDir\ directory exists. Nothing to roll back to."
        exit 1
    }
    $candidates = Get-ChildItem -Path $BackupsDir -Filter '*.sql.gz' -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTime -Descending
    if (-not $candidates) {
        Write-ErrLog "No *.sql.gz files found in $BackupsDir\. Pass an explicit path: .\rollback.ps1 -BackupFile <file.sql.gz>"
        exit 1
    }
    $BackupFile = $candidates[0].FullName
}
if (-not (Test-Path $BackupFile)) {
    Write-ErrLog "Backup file not found: $BackupFile"
    exit 1
}

Write-Log 'This will:'
Write-Log '  1. Stop the running stack (volumes preserved).'
Write-Log "  2. Restore Postgres from: $BackupFile"
Write-Log 'This is DESTRUCTIVE - current DB contents will be overwritten.'
$answer = Read-Host 'Proceed? [y/N]'
if ($answer -notmatch '^(y|yes)$') {
    Write-Log 'Aborted.'
    exit 0
}

# --- 1. stop stack ------------------------------------------------------------------
Write-Log "Stopping stack (project: $ProjectName)..."
Push-Location 'code'
try {
    docker compose -p $ProjectName down
    if ($LASTEXITCODE -ne 0) { throw "docker compose down failed with exit code $LASTEXITCODE" }

    # --- 2. bring up just postgres so we can pipe a restore in -------------------------
    Write-Log 'Starting postgres only...'
    docker compose -p $ProjectName --env-file ../.env up -d postgres
    if ($LASTEXITCODE -ne 0) { throw "docker compose up postgres failed with exit code $LASTEXITCODE" }

    # Wait for postgres to be ready.
    Write-Log 'Waiting for postgres to accept connections...'
    for ($i = 0; $i -lt 60; $i++) {
        docker compose -p $ProjectName exec -T postgres pg_isready -U pymentor *> $null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }

    # --- 3. restore ---------------------------------------------------------------------
    # PowerShell pipe does not preserve raw bytes reliably across docker exec;
    # use cmd.exe to stream the gunzip | psql pipe through the container.
    Write-Log "Restoring from $BackupFile ..."
    $absBackup = (Resolve-Path $BackupFile).Path
    # Use a subshell that pipes bytes losslessly.
    cmd /c "gunzip -c `"$absBackup`" | docker compose -p $ProjectName exec -T postgres psql -U pymentor pymentor"
    if ($LASTEXITCODE -ne 0) { throw "restore failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

Write-Log 'Restore complete.'
Write-Host ''
Write-Host '=============================================================================='
Write-Host '  Rollback finished'
Write-Host '=============================================================================='
Write-Host '  Postgres has been restored to the snapshot in:'
Write-Host "    $BackupFile"
Write-Host ''
Write-Host '  The application services are still stopped. To bring the full stack back up'
Write-Host '  with the restored data, run:'
Write-Host '    .\deploy.ps1'
Write-Host ''
Write-Host '  If you also need to revert CODE to a previous version, replace code\ with the'
Write-Host '  previous backend-deploy archive source, then run .\upgrade.ps1.'
Write-Host '=============================================================================='
