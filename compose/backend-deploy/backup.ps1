# ===========================================================================
#  PyMentor Lab - Backup (Windows / PowerShell)
#  --------------------------------------------------------------------------
#  Dumps the PostgreSQL database to backups/pymentor-YYYYMMDD-HHMMSS.sql.gz.
#  MinIO data is not dumped (use object-store lifecycle policies for that).
# ===========================================================================
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path $PSScriptRoot 'backups'
if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Path $backupDir | Out-Null }
$outFile = Join-Path $backupDir "pymentor-$stamp.sql.gz"

Write-Host "==> Dumping PostgreSQL -> $outFile" -ForegroundColor Cyan

# pg_dump runs inside the postgres container; output is piped through gzip.
docker compose exec -T postgres pg_dump -U pymentor pymentor 2>$null | gzip > $outFile
if (-not (Test-Path $outFile) -or (Get-Item $outFile).Length -eq 0) {
    Write-Error "Backup failed: $outFile is empty or missing"
    exit 1
}

$sizeKb = [math]::Round((Get-Item $outFile).Length / 1KB, 1)
Write-Host "    OK  Backup written ($sizeKb KB)." -ForegroundColor Green
