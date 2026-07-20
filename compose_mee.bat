@echo off
REM ===========================================================================
REM  PyMentor Lab artifact builder (compose_mee.bat)
REM  --------------------------------------------------------------------------
REM  Builds three artifacts and places them under dist\<VERSION>\:
REM    1. PyMentorLab-Setup.exe        - student Electron app (unsigned)
REM    2. PyMentorLab-Bootstrapper.exe - Inno Setup bootstrapper (embeds
REM                                      student exe + backend deploy zip)
REM    3. pymentor-backend-<ver>.zip   - self-contained backend deployment kit
REM
REM  Usage:
REM      compose_mee.bat              -> dist\V1.1\       (default)
REM      compose_mee.bat V1.1.4       -> dist\V1.1.4\
REM      compose_mee.bat V2.0         -> dist\V2.0\
REM
REM  Prerequisites (must be on PATH or at the default locations):
REM    - Node.js + pnpm (workspace install)
REM    - Python 3.13 + Pillow (for icon generation)
REM    - Inno Setup 6 at F:\Tools\Inno-Setup6\ISCC.exe
REM
REM  Output: dist\<VERSION>\
REM  ASCII-only to avoid codepage issues on Windows.
REM ===========================================================================

setlocal enabledelayedexpansion

REM Version: first CLI arg overrides the default. Strip a leading "/" or "-"
REM if present so callers can write either `V1.1.4` or `/V1.1.4`. A leading "V"
REM (the version prefix itself) is NOT stripped.
set "VERSION=V1.1"
if not "%~1"=="" (
    set "ARG=%~1"
    set "FIRST=!ARG:~0,1!"
    if "!FIRST!"=="/" set "ARG=!ARG:~1!"
    if "!FIRST!"=="-" set "ARG=!ARG:~1!"
    set "VERSION=!ARG!"
)
set "DIST_DIR=%~dp0dist\%VERSION%"
set "ROOT=%~dp0"
set "ISCC=F:\Tools\Inno-Setup6\ISCC.exe"
set "PYTHON=.venv\Scripts\python.exe"
set "EXITCODE=0"

REM Derive the bare version (no leading "V") for the zip filename, e.g.
REM VERSION=V1.1.4 -> ZIPVER=1.1.4. Falls back to VERSION if no "V" prefix.
set "ZIPVER=!VERSION!"
if /I "!ZIPVER:~0,1!"=="V" set "ZIPVER=!ZIPVER:~1!"

echo ========================================
echo Building PyMentor Lab %VERSION% artifacts
echo Output: %DIST_DIR%
echo ========================================
echo.

REM 0. Clean + create output dir
echo [0/6] Preparing output directory...
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
mkdir "%DIST_DIR%" 2>nul
if errorlevel 1 (
    echo ERROR: cannot create %DIST_DIR%
    set "EXITCODE=1"
    goto :end
)

REM 1. Generate icon FIRST (required by make:win + Inno Setup)
echo [1/6] Generating brand icon (required before EXE build)...
REM Ensure Python venv exists (uv creates it without pip; use uv for deps)
if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo Creating Python venv via uv...
    call uv sync --frozen --extra dev
    if errorlevel 1 (
        echo ERROR: uv sync failed. Is uv installed?
        set "EXITCODE=1"
        goto :end
    )
)
REM Ensure Pillow is installed (icon generation dependency)
"%ROOT%.venv\Scripts\python.exe" -c "import PIL" 2>nul
if errorlevel 1 (
    echo Installing Pillow for icon generation...
    call uv pip install Pillow
    if errorlevel 1 (
        echo ERROR: failed to install Pillow. Try manually: uv pip install Pillow
        set "EXITCODE=1"
        goto :end
    )
)
"%ROOT%.venv\Scripts\python.exe" "%ROOT%infra\icons\generate-icons.py"
if errorlevel 1 (
    echo ERROR: icon generation failed
    set "EXITCODE=1"
    goto :end
)
if not exist "%ROOT%apps\desktop\build\icon.ico" (
    echo ERROR: apps\desktop\build\icon.ico not generated
    set "EXITCODE=1"
    goto :end
)
echo     -^> apps\desktop\build\icon.ico
echo.

REM 2. Build student EXE (Electron Forge make:win)
echo [2/6] Building student EXE (Electron Forge)...
pushd "%ROOT%apps\desktop"

REM Configure Electron mirror BEFORE make:win so Forge can fetch the
REM prebuilt binary + checksums from the Chinese mirror when github.com is
REM unreachable (common behind the GFW). If github.com IS reachable, Forge
REM will still prefer the cache; the mirror is only a fallback.
REM
REM   ELECTRON_MIRROR          - base URL for the electron binary itself
REM   ELECTRON_BUILDER_BINARIES_MIRROR - for electron-builder helpers (not used
REM                                      by Forge, set for completeness)
REM Set them inside the pushed directory so they apply only to make:win.
set "ELECTRON_MIRROR=https://registry.npmmirror.com/-/binary/electron/"
set "ELECTRON_BUILDER_BINARIES_MIRROR=https://registry.npmmirror.com/-/binary/electron-builder-binaries/"

call pnpm install --frozen-lockfile
if errorlevel 1 (
    echo ERROR: pnpm install failed for apps/desktop
    popd
    set "EXITCODE=1"
    goto :end
)
call pnpm run make:win
if errorlevel 1 (
    echo ERROR: pnpm make:win failed
    echo        If the failure was a network timeout to github.com,
    echo        verify ELECTRON_MIRROR is reachable:
    echo            curl -sI %ELECTRON_MIRROR%
    echo        Or clear Forge's stale state:
    echo            rmdir /s /q apps\desktop\out
    popd
    set "EXITCODE=1"
    goto :end
)
popd
if not exist "%ROOT%apps\desktop\out\make\squirrel.windows\x64\PyMentorLab-Setup.exe" (
    echo ERROR: PyMentorLab-Setup.exe not found after build
    set "EXITCODE=1"
    goto :end
)
copy /y "%ROOT%apps\desktop\out\make\squirrel.windows\x64\PyMentorLab-Setup.exe" "%DIST_DIR%\PyMentorLab-Setup.exe" >nul
echo     -^> %DIST_DIR%\PyMentorLab-Setup.exe
echo.

REM 3. Build backend deploy zip (self-contained full source)
echo [3/6] Building backend deployment zip...
node "%ROOT%compose\build-dist.mjs" "%VERSION%"
if errorlevel 1 (
    echo ERROR: build-dist.mjs failed
    set "EXITCODE=1"
    goto :end
)
REM build-dist.mjs normalizes "V1.1.4" -> "v1.1.4" for the zip filename.
set "ZIP_NAME=pymentor-backend-v!ZIPVER!.zip"
if not exist "%ROOT%dist\backend-deploy\!ZIP_NAME!" (
    echo ERROR: !ZIP_NAME! not found after build
    set "EXITCODE=1"
    goto :end
)
copy /y "%ROOT%dist\backend-deploy\!ZIP_NAME!" "%DIST_DIR%\!ZIP_NAME!" >nul
echo     -^> %DIST_DIR%\!ZIP_NAME!
echo.

REM 4. Copy assets for Inno Setup embedding
echo [4/6] Preparing Inno Setup assets...
if not exist "%ROOT%dist\installer-source\installer-assets" mkdir "%ROOT%dist\installer-source\installer-assets"
copy /y "%ROOT%apps\desktop\out\make\squirrel.windows\x64\PyMentorLab-Setup.exe" "%ROOT%dist\installer-source\installer-assets\PyMentorLab-Setup.exe" >nul
copy /y "%ROOT%dist\backend-deploy\!ZIP_NAME!" "%ROOT%dist\installer-source\installer-assets\backend-deploy.zip" >nul
REM Ensure bootstrapper icon is current
if exist "%ROOT%apps\desktop\build\icon.ico" copy /y "%ROOT%apps\desktop\build\icon.ico" "%ROOT%dist\installer-source\icon.ico" >nul
echo.

REM 5. Build bootstrapper EXE (Inno Setup)
echo [5/6] Building bootstrapper EXE (Inno Setup)...
if not exist "%ISCC%" (
    echo ERROR: ISCC.exe not found at %ISCC%
    echo        Install Inno Setup 6 or update the ISCC variable in this script.
    set "EXITCODE=1"
    goto :end
)
"%ISCC%" "%ROOT%compose\bootstrapper.iss"
if errorlevel 1 (
    echo ERROR: ISCC compile failed
    set "EXITCODE=1"
    goto :end
)
if not exist "%ROOT%dist\installer\PyMentorLab-Bootstrapper.exe" (
    echo ERROR: PyMentorLab-Bootstrapper.exe not found after ISCC
    set "EXITCODE=1"
    goto :end
)
copy /y "%ROOT%dist\installer\PyMentorLab-Bootstrapper.exe" "%DIST_DIR%\PyMentorLab-Bootstrapper.exe" >nul
echo     -^> %DIST_DIR%\PyMentorLab-Bootstrapper.exe
echo.

REM Done
echo [6/6] Build complete.
echo ========================================
echo Artifacts in %DIST_DIR%:
dir /b "%DIST_DIR%"
echo ========================================

:end
if not "%EXITCODE%"=="0" (
    echo BUILD FAILED with exit code %EXITCODE%
)
endlocal & exit /b %EXITCODE%
