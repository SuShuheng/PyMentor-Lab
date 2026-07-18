param(
  [switch]$SkipMake,
  [switch]$SkipPackagedSmoke
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
  throw 'INT-006 Windows package acceptance must run on Windows.'
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$desktopRoot = Join-Path $repositoryRoot 'apps\desktop'
$rootBin = Join-Path $repositoryRoot 'node_modules\.bin'
$desktopBin = Join-Path $desktopRoot 'node_modules\.bin'

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Executable,
    [Parameter(Mandatory = $true)]
    [string[]]$Arguments,
    [Parameter(Mandatory = $true)]
    [string]$WorkingDirectory
  )

  Push-Location $WorkingDirectory
  try {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
      throw "Command failed with exit code ${LASTEXITCODE}: $Executable $($Arguments -join ' ')"
    }
  } finally {
    Pop-Location
  }
}

Invoke-Checked `
  -Executable (Join-Path $desktopBin 'vitest.cmd') `
  -Arguments @('run') `
  -WorkingDirectory $desktopRoot
Invoke-Checked `
  -Executable (Join-Path $desktopBin 'tsc.cmd') `
  -Arguments @('--noEmit') `
  -WorkingDirectory $desktopRoot

if (-not $SkipMake) {
  Invoke-Checked `
    -Executable (Join-Path $rootBin 'electron-forge.cmd') `
    -Arguments @('make', '--platform', 'win32', '--arch', 'x64') `
    -WorkingDirectory $desktopRoot
}

$application = Get-ChildItem -LiteralPath (Join-Path $desktopRoot 'out') -Recurse -File |
  Where-Object { $_.Name -eq 'PyMentorLab.exe' -and $_.FullName -notmatch '\\make\\' } |
  Select-Object -First 1
$setup = Get-ChildItem -LiteralPath (Join-Path $desktopRoot 'out\make') -Recurse -File |
  Where-Object { $_.Name -eq 'PyMentorLab-Setup.exe' } |
  Select-Object -First 1
if ($null -eq $application -or $null -eq $setup) {
  throw 'Expected Windows package and Squirrel Setup artifacts were not found.'
}

Invoke-Checked `
  -Executable (Join-Path $rootBin 'electron-fuses.cmd') `
  -Arguments @('read', '--app', $application.FullName) `
  -WorkingDirectory $repositoryRoot

$setupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $setup.FullName).Hash
$setupSignature = Get-AuthenticodeSignature -LiteralPath $setup.FullName
$applicationSignature = Get-AuthenticodeSignature -LiteralPath $application.FullName
Write-Output "SETUP_SHA256=$setupHash"
Write-Output "SETUP_SIGNATURE=$($setupSignature.Status)"
Write-Output "APPLICATION_SIGNATURE=$($applicationSignature.Status)"
foreach ($name in @(
    'WIN_CSC_LINK',
    'WIN_CSC_KEY_PASSWORD',
    'CSC_LINK',
    'CSC_KEY_PASSWORD',
    'GITHUB_TOKEN'
  )) {
  $present = $null -ne [Environment]::GetEnvironmentVariable($name)
  Write-Output "$name=$(if ($present) { 'PRESENT' } else { 'MISSING' })"
}

if (-not $SkipPackagedSmoke) {
  Invoke-Checked `
    -Executable 'node' `
    -Arguments @('--test', 'tests/electron/packaged-smoke.test.mjs') `
    -WorkingDirectory $repositoryRoot
}
