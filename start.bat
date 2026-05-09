@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "PLUGIN_DIR=D:\ai\skill_agent"
set "LOG=%PLUGIN_DIR%\plugin.log"
set "ERR=%PLUGIN_DIR%\plugin.err"

echo ========================================
echo   Skill Agent - Remote Debug Launcher
echo ========================================

:: 1. Kill old python processes (filtered by command line containing skill_agent + main)
echo.
echo [1/4] Cleaning old processes...
powershell -Command "Get-WmiObject Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -like '*skill_agent*' -and $_.CommandLine -like '*main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host '  Terminated PID:' $_.ProcessId }" 2>nul

:: 2. Clean Python caches
echo.
echo [2/4] Cleaning Python caches...
for %%d in ("%PLUGIN_DIR%\__pycache__" "%PLUGIN_DIR%\tools\__pycache__" "%PLUGIN_DIR%\utils\__pycache__") do (
    if exist %%d (
        rmdir /s /q %%d
        echo   Cleaned: %%~d
    )
)

:: 3. Validate .env
echo.
echo [3/4] Checking .env...
if not exist "%PLUGIN_DIR%\.env" (
    echo   FAIL: .env not found
    pause & exit /b 1
)
findstr /c:"INSTALL_METHOD=remote" "%PLUGIN_DIR%\.env" >nul 2>&1 || (
    echo   FAIL: INSTALL_METHOD is not remote
    pause & exit /b 1
)
for /f "tokens=2 delims==" %%k in ('findstr /r "^REMOTE_INSTALL_KEY=" "%PLUGIN_DIR%\.env"') do set "KEY=%%k"
if "!KEY!"=="" (
    echo   FAIL: REMOTE_INSTALL_KEY missing
    pause & exit /b 1
)
echo   Key: !KEY:~0,8!...  OK

:: 4. Clear logs and start
echo.
echo [4/4] Starting remote debug...
type nul > "%LOG%" 2>nul
type nul > "%ERR%" 2>nul

set PYTHONUNBUFFERED=1
cd /d "%PLUGIN_DIR%"
start /b "" python -m main > "%LOG%" 2> "%ERR%"

timeout /t 3 /nobreak >nul

findstr /c:"Installed tool" "%LOG%" >nul 2>&1
if errorlevel 1 (
    echo   Process started, waiting for Dify handshake...
) else (
    echo   SUCCESS - Plugin installed to Dify
)

echo.
echo   stdout: %LOG%
echo   stderr: %ERR%
echo.
pause
