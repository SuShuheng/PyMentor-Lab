param(
  [string]$ProjectName = 'pymentor-int007',
  [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$probeDatabase = 'pymentor_int007_restore_probe'

function Invoke-Compose {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Arguments,
    [switch]$ExpectFailure
  )

  Push-Location $repositoryRoot
  try {
    & docker compose -p $ProjectName @Arguments
    $exitCode = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  if ($ExpectFailure) {
    if ($exitCode -eq 0) {
      throw "Expected Compose command to fail: $($Arguments -join ' ')"
    }
    return
  }
  if ($exitCode -ne 0) {
    throw "Compose command failed (${exitCode}): $($Arguments -join ' ')"
  }
}

function Wait-Healthy {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Services,
    [int]$TimeoutSeconds = 120
  )

  $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
  do {
    $allHealthy = $true
    foreach ($service in $Services) {
      Push-Location $repositoryRoot
      try {
        $raw = & docker compose -p $ProjectName ps $service --format json
      } finally {
        Pop-Location
      }
      if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) {
        $allHealthy = $false
        break
      }
      $rows = @($raw | ConvertFrom-Json)
      if ($rows.Count -ne 1 -or $rows[0].Health -ne 'healthy') {
        $allHealthy = $false
        break
      }
    }
    if ($allHealthy) {
      return
    }
    Start-Sleep -Seconds 1
  } while ([DateTimeOffset]::UtcNow -lt $deadline)

  throw "Services did not become healthy: $($Services -join ', ')"
}

Invoke-Compose -Arguments @('config', '--quiet')
if (-not $SkipBuild) {
  Invoke-Compose -Arguments @('up', '--build', '-d')
} else {
  Invoke-Compose -Arguments @('up', '-d')
}
$services = @('postgres', 'redis', 'minio', 'worker', 'sandbox', 'api', 'web', 'admin')
Wait-Healthy -Services $services -TimeoutSeconds 180

Invoke-Compose -Arguments @('exec', '-T', 'api', 'alembic', '-c', 'backend/migrations/alembic.ini', 'current')
Invoke-Compose -Arguments @('exec', '-T', 'api', 'alembic', '-c', 'backend/migrations/alembic.ini', 'heads')
Invoke-Compose -Arguments @(
  'exec', '-T', 'api', 'alembic', '-c', 'backend/migrations/alembic.ini', 'upgrade', 'int007-missing-revision'
) -ExpectFailure
Invoke-Compose -Arguments @('exec', '-T', 'api', 'alembic', '-c', 'backend/migrations/alembic.ini', 'current')

Invoke-Compose -Arguments @(
  'exec', '-T', 'postgres', 'sh', '-ec',
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" -Fc -f /tmp/int007.dump'
)
Invoke-Compose -Arguments @(
  'exec', '-T', 'postgres', 'sh', '-ec',
  "PGPASSWORD=`"`$POSTGRES_PASSWORD`" dropdb -U `"`$POSTGRES_USER`" --if-exists $probeDatabase; PGPASSWORD=`"`$POSTGRES_PASSWORD`" createdb -U `"`$POSTGRES_USER`" $probeDatabase; PGPASSWORD=`"`$POSTGRES_PASSWORD`" pg_restore -U `"`$POSTGRES_USER`" -d $probeDatabase /tmp/int007.dump"
)
Invoke-Compose -Arguments @(
  'exec', '-T', 'api', 'sh', '-ec',
  "export PYMENTOR_DATABASE_URL=`"`${PYMENTOR_DATABASE_URL%/*}/$probeDatabase`"; alembic -c backend/migrations/alembic.ini downgrade -1"
)
Invoke-Compose -Arguments @(
  'exec', '-T', 'api', 'sh', '-ec',
  "export PYMENTOR_DATABASE_URL=`"`${PYMENTOR_DATABASE_URL%/*}/$probeDatabase`"; alembic -c backend/migrations/alembic.ini upgrade head"
)
Invoke-Compose -Arguments @(
  'exec', '-T', 'postgres', 'sh', '-ec',
  "PGPASSWORD=`"`$POSTGRES_PASSWORD`" psql -U `"`$POSTGRES_USER`" -d $probeDatabase -tAc 'select count(*) from alembic_version' | grep -qx 1; PGPASSWORD=`"`$POSTGRES_PASSWORD`" dropdb -U `"`$POSTGRES_USER`" $probeDatabase; rm -f /tmp/int007.dump"
)

Invoke-Compose -Arguments @('restart', 'redis')
Wait-Healthy -Services @('redis', 'worker') -TimeoutSeconds 90
Invoke-Compose -Arguments @('restart', 'api')
Wait-Healthy -Services @('api', 'web', 'admin') -TimeoutSeconds 120

& (Join-Path $repositoryRoot '.venv\Scripts\python.exe') `
  (Join-Path $repositoryRoot 'scripts\acceptance\int007-runtime-probe.py')
if ($LASTEXITCODE -ne 0) {
  throw "Runtime probe failed after service restart: $LASTEXITCODE"
}

Write-Output 'INT-007 deployment/recovery gate: PASS'
