# ===========================================================================
#  PyMentor Lab - Backend deploy (Windows / PowerShell)
#  --------------------------------------------------------------------------
#  Usage (from this folder, after editing .env):
#      .\deploy.ps1                # build + port check + start + healthcheck
#      .\deploy.ps1 -NoBuild       # reuse existing images (faster)
#      .\deploy.ps1 -FreshDatabase # WARNING: deletes volumes + reseeds
#      .\deploy.ps1 -ForcePort     # auto-kill any process on a required port
#
#  Prerequisites:
#      - Docker Desktop running (with the Compose plugin).
#      - .env present and at least these keys set:
#          PYMENTOR_PROVIDER_MASTER_KEY
#          PYMENTOR_INITIAL_ADMIN_EMAIL
#          PYMENTOR_INITIAL_ADMIN_PASSWORD
#
#  Port convention: every service binds to 127.0.0.1:<port>. If a port is
#  already in use, the script asks whether to stop the offender and proceeds
#  only after the port is free (or -ForcePort is passed).
#
#  Non-interactive mode: when invoked by a parent process without an
#  interactive console (e.g. the Inno Setup bootstrapper), the port-kill
#  prompt is bypassed and -ForcePort behavior is implied. A marker file
#  (.deploy-done.marker) is written on every exit path so the parent can
#  detect completion + read the exit code without polling the process.
# ===========================================================================

[CmdletBinding()]
param(
    [switch]$NoBuild,
    [switch]$FreshDatabase,
    [switch]$ForcePort
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# When invoked by a non-interactive parent (Inno Setup bootstrapper, CI,
# redirected subprocess), $Host.UI.RawUI.WindowVisible is false. In that mode
# Read-Host either throws PSInvalidOperationException (under 'Stop') or hangs
# reading a closed pipe. Default to -ForcePort behavior so the script can
# complete unattended. Interactive callers still get the prompt.
$NonInteractive = -not $Host.UI.RawUI.WindowVisible
if ($NonInteractive -and -not $ForcePort) {
    $ForcePort = $true
}

# Marker file: written on EVERY exit path (success or failure) so the parent
# process can detect completion + read the exit code without waiting on the
# process handle. Cleared at start so a stale marker from a prior run cannot
# fool the parent into thinking we already finished.
$MarkerFile = Join-Path $ScriptDir '.deploy-done.marker'
Remove-Item $MarkerFile -Force -ErrorAction SilentlyContinue

function Write-Marker($code) {
    try { "$code" | Set-Content -Path $MarkerFile -NoNewline -Encoding ascii } catch {}
}

# Progress helpers. [Console]::Out.Flush() forces line-buffered flushing so
# redirected output (the bootstrapper tails this via *>logfile) appears in
# near-real-time instead of large buffered chunks.
function Write-Step($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan;      [Console]::Out.Flush() }
function Write-Ok($msg)    { Write-Host "    OK  $msg" -ForegroundColor Green;  [Console]::Out.Flush() }
function Write-Warn($msg)  { Write-Host "    !!  $msg" -ForegroundColor Yellow; [Console]::Out.Flush() }
function Write-Err($msg)   { Write-Host "    ERR $msg" -ForegroundColor Red;    [Console]::Out.Flush() }

# Required host ports. Names map to the service in docker-compose.yml.
$RequiredPorts = @(
    @{ Name = 'postgres'; Port = 5432 },
    @{ Name = 'redis';    Port = 6379 },
    @{ Name = 'minio';    Port = 9000 },
    @{ Name = 'minio-console'; Port = 9001 },
    @{ Name = 'api';      Port = 8000 },
    @{ Name = 'worker';   Port = 8081 },
    @{ Name = 'student-web'; Port = 4173 },
    @{ Name = 'admin-web';   Port = 4174 }
)

function Get-PortOwner($port) {
    # Returns the owning process if the port is bound, otherwise $null.
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return $null }
    $proc = $conns | Select-Object -First 1
    $owner = Get-Process -Id $proc.OwningProcess -ErrorAction SilentlyContinue
    return @{ Pid = $proc.OwningProcess; ProcessName = if ($owner) { $owner.ProcessName } else { '<unknown>' }; LocalAddress = $proc.LocalAddress }
}

function Stop-PortOwner($port) {
    $owner = Get-PortOwner $port
    if (-not $owner) { return $true }
    try {
        Stop-Process -Id $owner.Pid -Force -ErrorAction Stop
        Start-Sleep -Milliseconds 500
    } catch {
        Write-Err "Failed to stop PID $($owner.Pid) ($($owner.ProcessName)): $_"
        return $false
    }
    return (-not (Get-PortOwner $port))
}

# ===========================================================================
# Main body. Wrapped in a script block + try/catch/finally so EVERY exit path
# (success, early-return, or uncaught exception) writes the marker file.
# Internal control flow uses `$script:ExitCode = N; return` instead of bare
# `exit N` (which would skip the finally block).
# ===========================================================================
$script:ExitCode = 0

$DeployMain = {
    # --- 0. Sanity checks --------------------------------------------------
    Write-Step "Checking prerequisites..."

    try { $null = Get-Command docker -ErrorAction Stop } catch {
        Write-Err "Docker not found on PATH. Install Docker Desktop first."
        $script:ExitCode = 1; return
    }
    $null = docker info 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Docker daemon is not running. Start Docker Desktop, then re-run."
        $script:ExitCode = 1; return
    }
    $null = docker compose version 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "docker compose plugin missing. Update Docker Desktop to a recent version."
        $script:ExitCode = 1; return
    }
    Write-Ok "Docker + Compose available."

    if (-not (Test-Path "$ScriptDir\.env")) {
        if (Test-Path "$ScriptDir\.env.example") {
            Write-Warn ".env not found. Copying .env.example -> .env for first-time setup."
            Copy-Item "$ScriptDir\.env.example" "$ScriptDir\.env"
            Write-Err ".env created with default values. Edit it (set the three REQUIRED keys), then re-run deploy.ps1."
            Write-Host "    Required keys:" -ForegroundColor Yellow
            Write-Host "      PYMENTOR_PROVIDER_MASTER_KEY"    -ForegroundColor Yellow
            Write-Host "      PYMENTOR_INITIAL_ADMIN_EMAIL"    -ForegroundColor Yellow
            Write-Host "      PYMENTOR_INITIAL_ADMIN_PASSWORD" -ForegroundColor Yellow
            $script:ExitCode = 2; return
        } else {
            Write-Err ".env and .env.example both missing. The deployment kit is incomplete."
            $script:ExitCode = 1; return
        }
    }

    # Confirm the three required keys are set (non-empty) in .env.
    $envContent = Get-Content "$ScriptDir\.env" -Raw
    $missing = @()
    foreach ($key in 'PYMENTOR_PROVIDER_MASTER_KEY','PYMENTOR_INITIAL_ADMIN_EMAIL','PYMENTOR_INITIAL_ADMIN_PASSWORD') {
        if ($envContent -notmatch "(?m)^$key=.+") { $missing += $key }
    }
    if ($missing.Count -gt 0) {
        Write-Err ".env is missing or has empty values for required keys:"
        $missing | ForEach-Object { Write-Host "      $_" -ForegroundColor Yellow }
        Write-Host "    Edit $ScriptDir\.env and re-run." -ForegroundColor Yellow
        $script:ExitCode = 2; return
    }
    Write-Ok ".env present and required keys set."

    # --- 1. Port occupancy check ------------------------------------------
    Write-Step "Checking required ports..."
    $busy = @()
    foreach ($entry in $RequiredPorts) {
        $owner = Get-PortOwner $entry.Port
        if ($owner) {
            $busy += [PSCustomObject]@{
                Service = $entry.Name
                Port    = $entry.Port
                Pid     = $owner.Pid
                Owner   = $owner.ProcessName
            }
        }
    }
    if ($busy.Count -gt 0) {
        Write-Warn "The following ports are already in use:"
        $busy | Format-Table Service, Port, Pid, Owner -AutoSize | Out-String | Write-Host

        if ($ForcePort) {
            Write-Warn "-ForcePort: stopping offenders without prompting..."
        } else {
            $choice = Read-Host "Stop the listed process(es) now so the stack can bind? (Y/N, default N)"
            if ($choice -notmatch '^[Yy]') {
                Write-Err "Deploy aborted. Free the ports above (or rerun with -ForcePort) and try again."
                $script:ExitCode = 3; return
            }
        }

        foreach ($b in $busy) {
            Write-Host "    Stopping PID $($b.Pid) ($($b.Owner)) on port $($b.Port)..." -NoNewline
            if (Stop-PortOwner $b.Port) {
                Write-Host " OK" -ForegroundColor Green
            } else {
                Write-Host " FAILED" -ForegroundColor Red
                Write-Err "Could not free port $($b.Port). Stop the process manually and re-run."
                $script:ExitCode = 3; return
            }
        }
    } else {
        Write-Ok "All required ports free."
    }

    # --- 2. Optional fresh database ---------------------------------------
    if ($FreshDatabase) {
        Write-Step "FreshDatabase: removing containers + volumes..."
        docker compose down -v
        if ($LASTEXITCODE -ne 0) { Write-Err "docker compose down -v failed"; $script:ExitCode = 1; return }
        Write-Ok "Volumes removed. Next build will reseed from scratch."
    }

    # --- 3. Build (or reuse) + start --------------------------------------
    if (-not $NoBuild) {
        Write-Step "Building images (docker compose build)..."
        docker compose build
        if ($LASTEXITCODE -ne 0) { Write-Err "docker compose build failed"; $script:ExitCode = 1; return }
        Write-Ok "Images built."
    }

    Write-Step "Starting stack (docker compose up -d)..."
    docker compose up -d
    if ($LASTEXITCODE -ne 0) { Write-Err "docker compose up -d failed"; $script:ExitCode = 1; return }
    Write-Ok "Stack started."

    # --- 4. Healthcheck ----------------------------------------------------
    Write-Step "Waiting for services to become healthy (up to 120s)..."
    $start = Get-Date
    $deadline = $start.AddSeconds(120)
    $allHealthy = $false
    while ((Get-Date) -lt $deadline) {
        $ps = docker compose ps --format '{{.Name}} {{.Status}}' 2>$null
        $unhealthy = $ps | Where-Object { $_ -notmatch '(healthy|running)' -and $_ -ne '' }
        if (-not $unhealthy) { $allHealthy = $true; break }
        Start-Sleep -Seconds 5
    }
    if (-not $allHealthy) {
        Write-Warn "Not all services reported healthy within 120s. Inspect with: docker compose ps"
        docker compose ps
    } else {
        Write-Ok "All services healthy."
    }

    # --- 5. Done ------------------------------------------------------------
    Write-Host ""
    Write-Host "==============================================================" -ForegroundColor Green
    Write-Host "  PyMentor Lab backend deployed" -ForegroundColor Green
    Write-Host "==============================================================" -ForegroundColor Green
    Write-Host "  API:     http://127.0.0.1:8000  (docs: /docs)"            -ForegroundColor White
    Write-Host "  Student: http://127.0.0.1:4173"                             -ForegroundColor White
    Write-Host "  Admin:   http://127.0.0.1:4174"                             -ForegroundColor White
    Write-Host "  MinIO:   http://127.0.0.1:9001"                             -ForegroundColor White
    Write-Host ""
    Write-Host "  Next:"                                                       -ForegroundColor White
    Write-Host "    - Log in to the admin panel with the initial admin email/password" -ForegroundColor White
    Write-Host "    - Ensure PYMENTOR_DESKTOP_WEB_URL=http://127.0.0.1:4173"   -ForegroundColor White
    Write-Host "      is set as a system environment variable (the Bootstrapper" -ForegroundColor White
    Write-Host "      does this automatically), then restart the desktop app."  -ForegroundColor White
    Write-Host "==============================================================" -ForegroundColor Green
}

try {
    & $DeployMain
} catch {
    Write-Err "Unhandled exception: $_"
    Write-Err $_.ScriptStackTrace
    $script:ExitCode = 99
} finally {
    Write-Marker $script:ExitCode
    [Console]::Out.Flush()
}

exit $script:ExitCode
