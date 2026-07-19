@echo off
REM ===========================================================================
REM  PyMentor Lab artifact builder (compose_mee.bat)
REM  --------------------------------------------------------------------------
REM  Builds three artifacts and places them under dist\V1.1\:
REM    1. PyMentorLab-Setup.exe        - student Electron app (unsigned)
REM    2. PyMentorLab-Bootstrapper.exe - Inno Setup bootstrapper (embeds
REM                                      student exe + backend deploy zip)
REM    3. pymentor-backend-v1.1.zip    - self-contained backend deployment kit
REM
REM  Prerequisites (must be on PATH or at the default locations):
REM    - Node.js + pnpm (workspace install)
REM    - Python 3.13 + Pillow (for icon generation)
REM    - Inno Setup 6 at F:\Tools\Inno-Setup6\ISCC.exe
REM
REM  Output: dist\V1.1\
REM  ASCII-only to avoid codepage issues on Windows.
REM ===========================================================================

setlocal enabledelayedexpansion

set "VERSION=V1.1"
set "DIST_DIR=%~dp0dist\%VERSION%"
set "ROOT=%~dp0"
set "ISCC=F:\Tools\Inno-Setup6\ISCC.exe"
set "PYTHON=.venv\Scripts\python.exe"
set "EXITCODE=0"

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
if not exist "%ROOT%%PYTHON%" (
    echo ERROR: %PYTHON% not found. Install Python 3.13 + Pillow first:
    echo        %PYTHON% -m pip install Pillow
    set "EXITCODE=1"
    goto :end
)
"%ROOT%%PYTHON%" "%ROOT%infra\icons\generate-icons.py"
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
node "%ROOT%dist\build-dist.mjs"
if errorlevel 1 (
    echo ERROR: build-dist.mjs failed
    set "EXITCODE=1"
    goto :end
)
if not exist "%ROOT%dist\backend-deploy\pymentor-backend-v1.1.zip" (
    echo ERROR: pymentor-backend-v1.1.zip not found after build
    set "EXITCODE=1"
    goto :end
)
copy /y "%ROOT%dist\backend-deploy\pymentor-backend-v1.1.zip" "%DIST_DIR%\pymentor-backend-v1.1.zip" >nul
echo     -^> %DIST_DIR%\pymentor-backend-v1.1.zip
echo.

REM 4. Copy assets for Inno Setup embedding
echo [4/6] Preparing Inno Setup assets...
if not exist "%ROOT%dist\installer-source\installer-assets" mkdir "%ROOT%dist\installer-source\installer-assets"
copy /y "%ROOT%apps\desktop\out\make\squirrel.windows\x64\PyMentorLab-Setup.exe" "%ROOT%dist\installer-source\installer-assets\PyMentorLab-Setup.exe" >nul
copy /y "%ROOT%dist\backend-deploy\pymentor-backend-v1.1.zip" "%ROOT%dist\installer-source\installer-assets\backend-deploy.zip" >nul
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
"%ISCC%" "%ROOT%dist\installer-source\bootstrapper.iss"
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
