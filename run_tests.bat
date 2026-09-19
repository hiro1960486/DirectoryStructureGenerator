@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Directory Structure Generator - Tests

set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%APP_PYTHON%" (
    echo The private environment was not found.
    echo Run START_APP.bat or setup_dev.bat first.
    pause
    exit /b 1
)

"%APP_PYTHON%" -m unittest discover -s "%~dp0tests" -v
set "TEST_EXIT=%ERRORLEVEL%"
echo.
if "%TEST_EXIT%"=="0" echo ALL TESTS PASSED
if not "%TEST_EXIT%"=="0" echo TESTS FAILED
pause
exit /b %TEST_EXIT%
