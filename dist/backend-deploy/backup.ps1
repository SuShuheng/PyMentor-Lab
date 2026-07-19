# PyMentor Lab v1.1 - Postgres backup (Windows PowerShell).
#
# Runs pg_dump inside the postgres container and writes a gzipped SQL dump to
# .\backups\pymentor-YYYYMMDD-HHMMSS.sql.gz. Safe to run while the stack is up.

[CmdletBinding()]
param(
    [string]$DbUser = 'pymentor',
    [string]$DbName = 'pymentor'
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$ProjectName = 'pymentor-prod'
$BackupsDir  = 'backups'

function Write-Log    { param([string]$Msg) Write-Host "[backup] $Msg" }
function Write-ErrLog { param([string]$Msg) Write-Host "[backup][ERROR] $Msg" -ForegroundColor Red }

# Read overrides from .env if present (powershell does not auto-source it).
if (Test-Path .env) {
    foreach ($line in Get-Content .env) {
        if ($line -match '^\s*POSTGRES_USER\s*=\s*(.+)$') { $DbUser = $Matches[1].Trim() }
        if ($line -match '^\s*POSTGRES_DB\s*=\s*(.+)$')   { $DbName = $Matches[1].Trim() }
    }
}

docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-ErrLog "'docker compose' is not available. Install the Compose V2 plugin."
    exit 1
}
if (-not (Test-Path 'code')) {
    Write-ErrLog "Missing 'code\' directory. Run from the backend-deploy folder."
    exit 1
}

if (-not (Test-Path $BackupsDir)) {
    New-Item -ItemType Directory -Path $BackupsDir | Out-Null
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outfile   = Join-Path $BackupsDir "pymentor-$timestamp.sql.gz"

Write-Log "Running pg_dump (user=$DbUser db=$DbName) inside the postgres container..."
Push-Location 'code'
try {
    # Pipe pg_dump through gzip inside the container to keep the byte stream
    # lossless and avoid host-side gzip dependency on Windows.
    docker compose -p $ProjectName exec -T postgres sh -c "pg_dump -U $DbUser $DbName | gzip" > $outfile
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

if (-not (Test-Path $outfile) -or (Get-Item $outfile).Length -eq 0) {
    Write-ErrLog "Backup file is empty - did the postgres container come up?"
    Write-ErrLog "Check:  Push-Location code; docker compose -p $ProjectName ps postgres; Pop-Location"
    exit 1
}

$size = (Get-Item $outfile).Length
$sizeKB = [math]::Round($size / 1KB, 1)
Write-Log 'Backup complete.'
Write-Host ''
Write-Host "  path:  $outfile"
Write-Host "  size:  $sizeKB KB"
Write-Host ''
