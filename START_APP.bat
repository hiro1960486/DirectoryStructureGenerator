@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Directory Structure Generator Ver.2.9.0

set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
set "STARTUP_LOG=%~dp0startup_error.log"

echo ============================================================
echo Directory Structure Generator Ver.2.9.0
echo Safe launcher and automatic setup
echo ============================================================
echo.

>"%STARTUP_LOG%" echo [%date% %time%] Startup check started.
>>"%STARTUP_LOG%" echo Working directory: %CD%

if not exist "%~dp0app.py" goto missing_files
if not exist "%~dp0requirements.txt" goto missing_files

echo [1/4] Checking Python...
where py >nul 2>&1
if not errorlevel 1 (
    set "PY_COMMAND=py -3"
    goto python_found
)
where python >nul 2>&1
if errorlevel 1 goto python_missing
set "PY_COMMAND=python"

:python_found
%PY_COMMAND% --version >>"%STARTUP_LOG%" 2>&1
if errorlevel 1 goto python_missing

echo [2/4] Checking the private environment...
if not exist "%APP_PYTHON%" (
    echo Creating .venv. This may take a moment...
    %PY_COMMAND% -m venv "%~dp0.venv" >>"%STARTUP_LOG%" 2>&1
    if errorlevel 1 goto setup_failed
)

echo [3/4] Checking PySide6 and Pillow...
"%APP_PYTHON%" -c "import PySide6, PIL; print(PySide6.__version__, PIL.__version__)" >>"%STARTUP_LOG%" 2>&1
if errorlevel 1 (
    echo Installing PySide6 and Pillow. This may take several minutes...
    "%APP_PYTHON%" -m pip install --upgrade pip >>"%STARTUP_LOG%" 2>&1
    if errorlevel 1 goto setup_failed
    "%APP_PYTHON%" -m pip install -r "%~dp0requirements.txt" >>"%STARTUP_LOG%" 2>&1
    if errorlevel 1 goto setup_failed
)

echo [4/4] Starting the application...
>>"%STARTUP_LOG%" echo Environment check completed. Starting app.py.
"%APP_PYTHON%" "%~dp0app.py" >>"%STARTUP_LOG%" 2>&1
set "APP_EXIT=%ERRORLEVEL%"

if "%APP_EXIT%"=="0" goto normal_end

echo.
echo ============================================================
echo The application could not start.
echo Exit code: %APP_EXIT%
echo ============================================================
echo.
type "%STARTUP_LOG%"
echo.
echo Please keep startup_error.log for diagnosis.
pause
exit /b %APP_EXIT%

:normal_end
echo.
echo The application closed normally.
pause
exit /b 0

:missing_files
echo Required files were not found.
echo Extract the ZIP completely, then place this BAT beside app.py.
>>"%STARTUP_LOG%" echo ERROR: app.py or requirements.txt was not found.
pause
exit /b 2

:python_missing
echo Python 3 was not found.
echo Install Python 3.13 with Python Launcher enabled.
>>"%STARTUP_LOG%" echo ERROR: Python 3 was not found.
pause
exit /b 3

:setup_failed
echo.
echo Setup failed. Check the internet connection.
echo Details are saved in startup_error.log.
echo.
type "%STARTUP_LOG%"
pause
exit /b 4
