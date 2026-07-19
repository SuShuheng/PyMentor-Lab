# check-docker.ps1
# Bootstrapper helper: verifies Docker Desktop is installed and the daemon is
# running before the backend deployment kit is unpacked.
#
# Exit codes:
#   0 = Docker engine + compose plugin are OK.
#   1 = docker executable not found on PATH (Docker Desktop not installed).
#   2 = docker present but daemon not running (Docker Desktop not started).
#   3 = docker compose plugin missing.
#   4 = unexpected error during the check.

$ErrorActionPreference = 'Stop'

try {
    $null = Get-Command docker -ErrorAction Stop
} catch {
    Write-Host "Docker not found on PATH."
    exit 1
}

try {
    $null = docker info 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker daemon not running. Start Docker Desktop."
        exit 2
    }

    $null = docker compose version 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "docker compose plugin missing."
        exit 3
    }

    Write-Host "Docker OK."
    exit 0
} catch {
    Write-Host "Docker check failed: $_"
    exit 4
}
