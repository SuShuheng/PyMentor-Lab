# PyMentor Lab v1.1 - Postgres restore (Windows PowerShell).
#
# Restores Postgres from a gzipped SQL dump produced by .\backup.ps1.
#
#   .\restore.ps1 -BackupFile backups\pymentor-20260719-103015.sql.gz
#
# DESTRUCTIVE: overwrites current DB contents. The stack must be running
# (.\deploy.ps1) so the postgres container is up; non-API services do not need
# to be stopped, but for a clean restore you may want to stop the API first:
#   Push-Location code; docker compose -p pymentor-prod stop api worker; Pop-Location

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$BackupFile,

    [string]$DbUser = 'pymentor',
    [string]$DbName = 'pymentor'
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$ProjectName = 'pymentor-prod'

function Write-Log    { param([string]$Msg) Write-Host "[restore] $Msg" }
function Write-ErrLog { param([string]$Msg) Write-Host "[restore][ERROR] $Msg" -ForegroundColor Red }

# Read overrides from .env if present.
if (Test-Path .env) {
    foreach ($line in Get-Content .env) {
        if ($line -match '^\s*POSTGRES_USER\s*=\s*(.+)$') { $DbUser = $Matches[1].Trim() }
        if ($line -match '^\s*POSTGRES_DB\s*=\s*(.+)$')   { $DbName = $Matches[1].Trim() }
    }
}

if (-not (Test-Path $BackupFile)) {
    Write-ErrLog "Backup file not found: $BackupFile"
    exit 1
}

docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-ErrLog "'docker compose' is not available."
    exit 1
}
if (-not (Test-Path 'code')) {
    Write-ErrLog "Missing 'code\' directory."
    exit 1
}

Write-Log "About to restore Postgres from: $BackupFile"
Write-Log "Target database: user=$DbUser db=$DbName"
Write-Log "DESTRUCTIVE: current data in '$DbName' will be overwritten."
$answer = Read-Host 'Proceed? [y/N]'
if ($answer -notmatch '^(y|yes)$') {
    Write-Log 'Aborted.'
    exit 0
}

Write-Log 'Restoring...'
$absBackup = (Resolve-Path $BackupFile).Path
Push-Location 'code'
try {
    # PowerShell's pipe mangles binary streams across docker exec; use cmd.exe
    # to keep the gunzip | psql byte stream lossless.
    cmd /c "gunzip -c `"$absBackup`" | docker compose -p $ProjectName exec -T postgres psql -U $DbUser $DbName"
    if ($LASTEXITCODE -ne 0) { throw "restore failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

Write-Log 'Restore complete. Verify with:'
Write-Log '  Invoke-WebRequest http://localhost:8000/health -UseBasicParsing'
Write-Log "  Push-Location code; docker compose -p $ProjectName exec -T postgres psql -U $DbUser $DbName -c '\dt'; Pop-Location"
