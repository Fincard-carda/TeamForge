@echo off
REM TeamForge one-click setup launcher for Windows.
REM Runs install.ps1 with ExecutionPolicy Bypass so users don't
REM have to deal with PowerShell signing prompts.

setlocal
cd /d "%~dp0"

echo Starting TeamForge installer...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"

set EXITCODE=%ERRORLEVEL%
echo.
if %EXITCODE% NEQ 0 (
    echo Installer exited with code %EXITCODE%.
    pause
)
endlocal
