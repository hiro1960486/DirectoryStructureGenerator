@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Directory Structure Generator - Development Setup

set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
set "SETUP_LOG=%~dp0setup_error.log"
>"%SETUP_LOG%" echo [%date% %time%] Setup started.

echo [1/3] Checking Python...
where py >nul 2>&1
if not errorlevel 1 (
    set "PY_COMMAND=py -3"
    goto python_found
)
where python >nul 2>&1
if errorlevel 1 goto setup_failed
set "PY_COMMAND=python"

:python_found
%PY_COMMAND% --version >>"%SETUP_LOG%" 2>&1
if errorlevel 1 goto setup_failed

echo [2/3] Preparing the private environment...
if not exist "%APP_PYTHON%" (
    %PY_COMMAND% -m venv "%~dp0.venv" >>"%SETUP_LOG%" 2>&1
    if errorlevel 1 goto setup_failed
)

echo [3/3] Installing required packages...
"%APP_PYTHON%" -m pip install --upgrade pip >>"%SETUP_LOG%" 2>&1
if errorlevel 1 goto setup_failed
"%APP_PYTHON%" -m pip install -r "%~dp0requirements-build.txt" >>"%SETUP_LOG%" 2>&1
if errorlevel 1 goto setup_failed

echo.
echo SETUP COMPLETED SUCCESSFULLY
echo You can now run START_APP.bat or build_exe.bat.
pause
exit /b 0

:setup_failed
echo.
echo Setup failed. Details are saved in setup_error.log.
echo.
type "%SETUP_LOG%"
pause
exit /b 1
