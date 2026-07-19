# PyMentor Lab v1.1 - backend deployment entrypoint (Windows PowerShell).
#
# Behaviour:
#   1. Verifies `docker compose` is available (errors with an install hint otherwise).
#   2. If `.env` is missing, copies `.env.example` to `.env`, prints clear
#      instructions to fill in the three [REQUIRED] secrets, and EXITS 0.
#      It will never auto-start with default secrets.
#   3. If `.env` exists, runs `docker compose -p pymentor-prod --env-file .env
#      up --build -d` from the `code\` directory, then waits for the API
#      healthcheck (loop curl on /health up to 180s) and prints the admin URL.
#
# Usage:
#   PowerShell> .\deploy.ps1
# Requires PowerShell 5.1+ or PowerShell 7+. If script execution is blocked,
# run once:  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$EnvFile        = '.env'
$EnvExample     = '.env.example'
$ProjectName    = 'pymentor-prod'
$HealthUrl      = 'http://localhost:8000/health'
$HealthTimeout  = 180   # seconds

function Write-Log    { param([string]$Msg) Write-Host "[deploy] $Msg" }
function Write-ErrLog { param([string]$Msg) Write-Host "[deploy][ERROR] $Msg" -ForegroundColor Red }

# --- 1. docker compose availability ------------------------------------------------
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-ErrLog 'Docker engine is not installed or not on PATH.'
    Write-ErrLog 'Install Docker Desktop: https://www.docker.com/products/docker-desktop'
    exit 1
}

$composeOk = $false
try {
    docker compose version *> $null
    if ($LASTEXITCODE -eq 0) { $composeOk = $true }
} catch { }

if (-not $composeOk) {
    Write-ErrLog "'docker compose' (Compose V2 plugin) is not available."
    Write-ErrLog 'Enable it in Docker Desktop Settings: "Use Docker Compose V2".'
    Write-ErrLog 'Or install the plugin: https://docs.docker.com/compose/install/'
    exit 1
}

# --- 2. .env handling ---------------------------------------------------------------
if (-not (Test-Path $EnvFile)) {
    if (-not (Test-Path $EnvExample)) {
        Write-ErrLog "Neither $EnvFile nor $EnvExample exists in $PSScriptRoot."
        exit 1
    }
    Copy-Item -Path $EnvExample -Destination $EnvFile -Force
    Write-Log "Created $EnvFile from $EnvExample."

    Write-Host ''
    Write-Host '=============================================================================='
    Write-Host '  ACTION REQUIRED - edit .env before deploying'
    Write-Host '=============================================================================='
    Write-Host "  Open  $PSScriptRoot\$EnvFile  and set the three [REQUIRED] secrets:"
    Write-Host ''
    Write-Host '    PYMENTOR_PROVIDER_MASTER_KEY      encryption key for provider credentials'
    Write-Host '    PYMENTOR_INITIAL_ADMIN_EMAIL      first admin login email (deliverable)'
    Write-Host '    PYMENTOR_INITIAL_ADMIN_PASSWORD   first admin login password'
    Write-Host ''
    Write-Host '  Generation commands are documented inline in .env. Recommended:'
    Write-Host ''
    Write-Host '    python -c "import base64,secrets; `'
    Write-Host '      print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"'
    Write-Host ''
    Write-Host '  Also rotate the default dev values for:'
    Write-Host '    POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD,'
    Write-Host '    PYMENTOR_JWT_SECRET, PYMENTOR_WORKER_INTERNAL_SECRET, PYMENTOR_SANDBOX_SECRET'
    Write-Host ''
    Write-Host '  Then re-run this script:'
    Write-Host '    .\deploy.ps1'
    Write-Host '=============================================================================='
    exit 0
}

# --- 3. build + start ---------------------------------------------------------------
if (-not (Test-Path 'code')) {
    Write-ErrLog "Missing 'code\' directory. This zip should have shipped with full source under code\. Re-extract the archive."
    exit 1
}

Write-Log "Building and starting the stack (project: $ProjectName). First build may take several minutes..."
Push-Location 'code'
try {
    docker compose -p $ProjectName --env-file ../.env up --build -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

# --- 4. wait for API health ---------------------------------------------------------
Write-Log "Waiting for API health at $HealthUrl (up to $HealthTimeout s)..."
$elapsed = 0
$healthy = $false
while ($elapsed -lt $HealthTimeout) {
    try {
        $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch {
        # service not ready yet; keep waiting
    }
    Start-Sleep -Seconds 5
    $elapsed += 5
    Write-Host -NoNewline '.'
}
Write-Host ''

if (-not $healthy) {
    Write-ErrLog "API did not become healthy within $HealthTimeout s."
    Write-ErrLog "Inspect logs with:  Push-Location code; docker compose -p $ProjectName logs --tail=200 api; Pop-Location"
    Write-ErrLog "Check container status:  Push-Location code; docker compose -p $ProjectName ps; Pop-Location"
    exit 1
}

Write-Log 'Stack is healthy.'
Write-Host ''
Write-Host '=============================================================================='
Write-Host '  PyMentor Lab v1.1 is up'
Write-Host '=============================================================================='
Write-Host '  API docs (Swagger):   http://localhost:8000/docs'
Write-Host '  Admin login:          http://localhost:8000/docs#/Auth/login_api_v1_auth_login_post'
Write-Host '  Web app:              http://localhost:4173'
Write-Host '  Admin app:            http://localhost:4174'
Write-Host '  MinIO console:        http://localhost:9001'
Write-Host '  Postgres (psql):      localhost:5432  (user/db: pymentor)'
Write-Host ''
Write-Host '  Admin credentials are the ones you set in .env:'
Write-Host '    PYMENTOR_INITIAL_ADMIN_EMAIL'
Write-Host '    PYMENTOR_INITIAL_ADMIN_PASSWORD'
Write-Host ''
Write-Host '  Useful commands:'
Write-Host '    .\healthcheck.ps1               verify the stack is still healthy'
Write-Host '    .\backup.ps1                    take a gzipped SQL backup into .\backups\'
Write-Host '    .\upgrade.ps1                   rebuild + restart on a new source drop'
Write-Host "    docker compose -p $ProjectName logs -f      tail service logs"
Write-Host '=============================================================================='
