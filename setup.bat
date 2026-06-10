@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: =============================================================================
:: OfflineAgent - Windows Setup & Launcher (Domain-User Friendly)
:: =============================================================================
:: No admin rights required. No C: drive writes. No registry changes.
::
:: Usage:
::   setup.bat              Interactive launch menu
::   setup.bat cli           Start CLI mode directly
::   setup.bat web           Start Web server mode directly
::   setup.bat check         Run config check only
:: =============================================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Remove trailing backslash
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

echo.
echo   ==============================================
echo     OfflineAgent v5 - Portable AI Assistant
echo   ==============================================
echo.
echo   Working directory: %SCRIPT_DIR%
echo.

:: ---------------------------------------------------------------------------
:: Step 1: Find Python
:: ---------------------------------------------------------------------------

set "PYTHON_EXE="

:: Priority 1: Portable Python in .\python\
if exist "%SCRIPT_DIR%\python\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%\python\python.exe"
    echo   [OK] Found portable Python: .\python\python.exe
    goto :python_found
)

:: Priority 2: System Python (python3 or python)
where python3 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%i in ('where python3 2^>nul') do set "PYTHON_EXE=%%i"
    echo   [OK] Found system Python (python3)
    goto :python_found
)

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%i in ('where python 2^>nul') do set "PYTHON_EXE=%%i"
    echo   [OK] Found system Python (python)
    goto :python_found
)

:: No Python found
echo   [FAIL] Python not found!
echo.
echo   Please do one of the following:
echo     1. Install Python 3.8+ from python.org
echo     2. Or put a portable Python in: %SCRIPT_DIR%\python\
echo        (Download embeddable zip from python.org, extract here)
echo.
pause
exit /b 1

:python_found

:: ---------------------------------------------------------------------------
:: Step 2: Check Python version
:: ---------------------------------------------------------------------------

"%PYTHON_EXE%" -c "import sys; v=sys.version_info; exit(0 if v>=(3,8) else 1)" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo   [FAIL] Python 3.8+ is required.
    "%PYTHON_EXE%" --version
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('"%PYTHON_EXE%" --version 2^>^&1') do set "PY_VER=%%v"
echo   Python version: %PY_VER%
echo.

:: ---------------------------------------------------------------------------
:: Step 3: Check for Playwright (optional)
:: ---------------------------------------------------------------------------

if exist "%SCRIPT_DIR%\browsers\chromium-*" (
    set "PLAYWRIGHT_BROWSERS_PATH=%SCRIPT_DIR%\browsers"
    echo   [OK] Playwright browsers found: .\browsers\
    echo.
) else (
    echo   [INFO] No Playwright browsers found at .\browsers\
    echo          Browser automation will be unavailable.
    echo          See MANUAL.md for offline Playwright setup.
    echo.
)

:: ---------------------------------------------------------------------------
:: Step 4: Check config.yaml
:: ---------------------------------------------------------------------------

if not exist "%SCRIPT_DIR%\config.yaml" (
    echo   [FAIL] config.yaml not found!
    pause
    exit /b 1
)

echo   [OK] config.yaml found.
echo.

:: ---------------------------------------------------------------------------
:: Step 5: Set environment and launch
:: ---------------------------------------------------------------------------

:: Set workspace paths (relative to script dir)
set "OFFLINEAGENT_HOME=%SCRIPT_DIR%"
set "PLAYWRIGHT_BROWSERS_PATH=%SCRIPT_DIR%\browsers"

:: If portable Python, add it to PATH for subprocess calls
set "PATH=%SCRIPT_DIR%\python;%PATH%"

:: Parse command-line argument or show menu
if /i "%~1"=="cli" goto :launch_cli
if /i "%~1"=="web" goto :launch_web
if /i "%~1"=="check" goto :run_check

:show_menu
echo   Select launch mode:
echo.
echo     [1] CLI mode      (python agent.py)
echo     [2] Web mode      (python server.py, open http://localhost:8999)
echo     [C] Config check  (validate settings)
echo     [Q] Quit
echo.
set /p CHOICE="   Choice: "

if /i "%CHOICE%"=="1" goto :launch_cli
if /i "%CHOICE%"=="2" goto :launch_web
if /i "%CHOICE%"=="c" goto :run_check
if /i "%CHOICE%"=="C" goto :run_check
if /i "%CHOICE%"=="q" goto :quit
if /i "%CHOICE%"=="Q" goto :quit

echo   Invalid choice.
goto :show_menu

:run_check
echo.
echo   Running configuration check...
echo.
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, '%SCRIPT_DIR%\..'); from Offlineagent.evaluation.config_validator import run_self_check; from Offlineagent.agent import load_config; from pathlib import Path; cfg = load_config(Path('%SCRIPT_DIR%/config.yaml')); issues = run_self_check(cfg, Path('%SCRIPT_DIR%')); print('\n'.join(issues))"
echo.
pause
goto :show_menu

:launch_cli
echo.
echo   Starting OfflineAgent CLI...
echo   Type /help for commands, /exit to quit.
echo   ==============================================
echo.
"%PYTHON_EXE%" "%SCRIPT_DIR%\agent.py" %2 %3 %4 %5
goto :quit

:launch_web
echo.
echo   Starting OfflineAgent Web Server...
echo   Open http://localhost:8999 in your browser.
echo   ==============================================
echo.
"%PYTHON_EXE%" "%SCRIPT_DIR%\server.py" %2 %3 %4 %5
goto :quit

:quit
endlocal
