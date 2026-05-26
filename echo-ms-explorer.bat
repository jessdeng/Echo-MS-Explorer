@echo off
REM echo-ms-explorer - double-click launcher for Windows
REM
REM Just double-click this file in Explorer. It will:
REM   1. Switch to this folder
REM   2. Make sure dependencies are installed via uv
REM   3. Launch the app in a native window

setlocal

REM Switch to the directory containing this script
cd /d "%~dp0"

REM Make sure uv is on PATH (default install puts it under %USERPROFILE%\.local\bin)
set PATH=%USERPROFILE%\.local\bin;%PATH%

where uv >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: 'uv' is not installed.
    echo.
    echo Install it once by opening PowerShell and running:
    echo   powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo.
    echo Then close this window and double-click the launcher again.
    echo.
    pause
    exit /b 1
)

echo Checking dependencies...
uv sync --quiet
if errorlevel 1 (
    echo.
    echo Failed to install dependencies. See messages above.
    pause
    exit /b 1
)

echo Launching echo-ms-explorer...
uv run python launch.py

if errorlevel 1 (
    echo.
    echo Something went wrong.
    pause
)

endlocal
