@echo off
REM echo-ms-explorer — double-click launcher for Windows
REM
REM Opens the app in a native window. Just double-click this file in Explorer.
REM Safe to re-run anytime: any previous server is stopped first.
REM
REM The virtual environment is stored in %LOCALAPPDATA%\echo-ms-explorer\venv
REM (NOT in the project folder) to avoid corruption from OneDrive/Dropbox sync.

setlocal EnableDelayedExpansion

REM Switch to the directory containing this script
cd /d "%~dp0"

REM venv lives outside any synced folder (per-user, per-machine)
set "VENV_DIR=%LOCALAPPDATA%\echo-ms-explorer\venv"
set "UV_PROJECT_ENVIRONMENT=%VENV_DIR%"

REM Make sure uv is on PATH (default install locations)
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"

where uv >nul 2>&1
if errorlevel 1 (
    echo.
    echo ======================================================
    echo   echo-ms-explorer: first-time setup needed
    echo ======================================================
    echo.
    echo   'uv' is not installed ^(Python package manager^).
    echo.
    echo   Open PowerShell and run:
    echo.
    echo       powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo.
    echo   Then close this window and double-click the launcher again.
    echo.
    pause
    exit /b 1
)

REM ── 1. Clean up stale state from previous runs ──────────────────────────
if exist ".server-port" del /q ".server-port"
if exist ".server.log" del /q ".server.log"

REM ── 2. Kill any old server still bound to our port range ────────────────
echo Cleaning up any previous instance...
for %%P in (8765 8766 8767 8768 8769 8770) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr "127.0.0.1:%%P " ^| findstr "LISTENING" 2^>nul') do (
        if not "%%A"=="0" (
            echo   stopping process on port %%P: PID %%A
            taskkill /PID %%A /F >nul 2>&1
        )
    )
)
timeout /t 1 /nobreak >nul

REM ── 3. Sync dependencies (fast no-op after first install) ───────────────
if not exist "%VENV_DIR%" (
    echo First-time setup — installing dependencies ^(this may take 1-2 minutes^)...
    if not exist "%LOCALAPPDATA%\echo-ms-explorer" mkdir "%LOCALAPPDATA%\echo-ms-explorer"
    uv sync --python 3.12
) else (
    echo Checking dependencies...
    uv sync --quiet
)
if errorlevel 1 (
    echo.
    echo ======================================================
    echo   Dependency setup failed.
    echo ======================================================
    echo.
    echo   Some packages ^(pynumpress, lxml^) need a C compiler.
    echo   If you see "Microsoft Visual C++ 14.0 is required":
    echo.
    echo   1. Download Visual Studio Build Tools from:
    echo      https://visualstudio.microsoft.com/visual-cpp-build-tools/
    echo   2. Run the installer and select:
    echo      "Desktop development with C++"
    echo   3. Restart your computer, then double-click this launcher again.
    echo.
    pause
    exit /b 1
)

REM ── 4. Launch the app ───────────────────────────────────────────────────
REM On Windows, launch.py blocks until the pywebview window is closed,
REM so no background/detach logic is needed (unlike the macOS launcher).
echo Starting echo-ms-explorer...
uv run python launch.py

if errorlevel 1 (
    echo.
    echo ======================================================
    echo   Something went wrong. Check the output above.
    echo ======================================================
    echo.
    pause
    exit /b 1
)

endlocal
