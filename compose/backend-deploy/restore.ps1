# ===========================================================================
#  PyMentor Lab - Restore (Windows / PowerShell)
#  --------------------------------------------------------------------------
#  Restores a gzipped PostgreSQL dump produced by backup.ps1.
#
#  Usage:
#      .\restore.ps1 -File backups\pymentor-20260719-120000.sql.gz
# ===========================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$File
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not (Test-Path $File)) { Write-Error "Backup file not found: $File"; exit 1 }

Write-Host "==> Restoring PostgreSQL from $File..." -ForegroundColor Cyan
# gunzip the dump, then feed it to psql inside the postgres container.
gunzip -c $File | docker compose exec -T postgres psql -U pymentor pymentor
if ($LASTEXITCODE -ne 0) { Write-Error "restore failed"; exit 1 }
Write-Host "    OK  Restore complete." -ForegroundColor Green
