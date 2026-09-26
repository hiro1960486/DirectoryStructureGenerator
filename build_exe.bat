@echo off
setlocal EnableExtensions
title Directory Structure Generator - EXE Build

set "APP_NAME=DirectoryStructureGeneratorGUI"
set "APP_VERSION=2.9.7"
set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
set "BUILD_LOG=%~dp0build_log.txt"
set "DIST_DIR=%~dp0dist\%APP_NAME%"
set "RELEASE_DIR=%~dp0release"
set "ZIP_PATH=%~dp0release\%APP_NAME%_Ver%APP_VERSION%_Windows_x64.zip"
set "CLEAN_BUILD=0"
set "SKIP_ZIP=0"
if /i "%~1"=="clean" set "CLEAN_BUILD=1"
if /i "%~1"=="nozip" set "SKIP_ZIP=1"

echo ============================================================
echo Directory Structure Generator Ver.%APP_VERSION%
echo Automatic Windows EXE Build
echo ============================================================
echo.

>"%BUILD_LOG%" echo [%date% %time%] Build started.
>>"%BUILD_LOG%" echo Project directory: "%~dp0"

if not exist "%~dp0app.py" goto missing_files
if not exist "%~dp0requirements-build.txt" goto missing_files

echo [1/7] Checking Python...
where py >nul 2>&1
if not errorlevel 1 (
    set "PY_COMMAND=py -3"
    goto python_found
)
where python >nul 2>&1
if errorlevel 1 goto python_missing
set "PY_COMMAND=python"

:python_found
%PY_COMMAND% --version >>"%BUILD_LOG%" 2>&1
if errorlevel 1 goto python_missing

echo [2/7] Preparing the private environment...
if not exist "%APP_PYTHON%" (
    echo Creating .venv. This may take a moment...
    %PY_COMMAND% -m venv "%~dp0.venv" >>"%BUILD_LOG%" 2>&1
    if errorlevel 1 goto setup_failed
)

echo [3/7] Checking build packages...
"%APP_PYTHON%" -c "import PySide6, PIL, PyInstaller, hachoir, openpyxl" >>"%BUILD_LOG%" 2>&1
if errorlevel 1 (
    echo Installing PySide6, Pillow and PyInstaller. This may take several minutes...
    "%APP_PYTHON%" -m pip install --upgrade pip >>"%BUILD_LOG%" 2>&1
    if errorlevel 1 goto setup_failed
    "%APP_PYTHON%" -m pip install -r "%~dp0requirements-build.txt" >>"%BUILD_LOG%" 2>&1
    if errorlevel 1 goto setup_failed
)

echo [4/7] Running automatic tests...
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
"%APP_PYTHON%" -m unittest discover -s "%~dp0tests" -v >>"%BUILD_LOG%" 2>&1
if errorlevel 1 goto test_failed

echo [5/7] Preparing build output...
if "%CLEAN_BUILD%"=="1" (
    echo Clean build mode: removing the PyInstaller cache...
    if exist "%~dp0build" rmdir /s /q "%~dp0build"
) else (
    echo Fast build mode: reusing the PyInstaller cache.
)
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"

echo [6/7] Building the Windows application...
echo This step may take several minutes. Please wait...
"%APP_PYTHON%" -m PyInstaller --noconfirm --windowed --onedir --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0build" --collect-submodules hachoir --collect-all openpyxl --icon "%~dp0DirectoryStructureGenerator_AppIcon.ico" --add-data "%~dp0DirectoryStructureGenerator_AppIcon.ico;." --name "%APP_NAME%" "%~dp0app.py" >>"%BUILD_LOG%" 2>&1
if errorlevel 1 goto build_failed

if not exist "%DIST_DIR%\%APP_NAME%.exe" goto exe_missing
if exist "%~dp0README.md" copy /y "%~dp0README.md" "%DIST_DIR%\README.md" >nul
if not exist "%DIST_DIR%\docs" mkdir "%DIST_DIR%\docs"
if exist "%~dp0docs\DirectoryStructureGenerator_AppIcon_512.png" copy /y "%~dp0docs\DirectoryStructureGenerator_AppIcon_512.png" "%DIST_DIR%\docs\" >nul
if exist "%~dp0docs\DirectoryStructureGenerator_Ver%APP_VERSION%_操作マニュアル.pdf" copy /y "%~dp0docs\DirectoryStructureGenerator_Ver%APP_VERSION%_操作マニュアル.pdf" "%DIST_DIR%\docs\" >nul

if "%SKIP_ZIP%"=="1" goto build_completed

echo [7/7] Creating ZIP and SHA256 files...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$exe=Join-Path $env:DIST_DIR ($env:APP_NAME+'.exe'); $hash=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash; Set-Content -LiteralPath (Join-Path $env:DIST_DIR 'SHA256_EXE.txt') -Encoding UTF8 -Value (($env:APP_NAME+'.exe  ')+$hash)" >>"%BUILD_LOG%" 2>&1
if errorlevel 1 goto build_failed

if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"
where tar.exe >nul 2>&1
if errorlevel 1 goto powershell_zip
pushd "%DIST_DIR%"
tar.exe -a -c -f "%ZIP_PATH%" * >>"%BUILD_LOG%" 2>&1
set "ZIP_EXIT=%ERRORLEVEL%"
popd
if not "%ZIP_EXIT%"=="0" goto build_failed
goto zip_created

:powershell_zip
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path (Join-Path $env:DIST_DIR '*') -DestinationPath $env:ZIP_PATH -Force" >>"%BUILD_LOG%" 2>&1
if errorlevel 1 goto build_failed

:zip_created
powershell -NoProfile -ExecutionPolicy Bypass -Command "$hash=(Get-FileHash -LiteralPath $env:ZIP_PATH -Algorithm SHA256).Hash; Set-Content -LiteralPath ($env:ZIP_PATH+'.sha256.txt') -Encoding UTF8 -Value ((Split-Path $env:ZIP_PATH -Leaf)+'  '+$hash)" >>"%BUILD_LOG%" 2>&1
if errorlevel 1 goto build_failed

:build_completed
>>"%BUILD_LOG%" echo [%date% %time%] Build completed successfully.
echo.
echo ============================================================
echo BUILD COMPLETED SUCCESSFULLY
echo ============================================================
echo EXE:
echo "%DIST_DIR%\%APP_NAME%.exe"
if "%SKIP_ZIP%"=="1" (
    echo.
    echo ZIP creation was skipped for this fast test build.
) else (
    echo.
    echo Distribution ZIP:
    echo "%ZIP_PATH%"
)
echo.
if "%SKIP_ZIP%"=="1" (
    explorer "%DIST_DIR%"
) else (
    explorer "%RELEASE_DIR%"
)
pause
exit /b 0

:missing_files
echo Required project files were not found.
echo Place this BAT in the same folder as app.py and requirements-build.txt.
>>"%BUILD_LOG%" echo ERROR: Required project files were not found.
pause
exit /b 2

:python_missing
echo Python 3 was not found.
echo Install Python 3.13 with Python Launcher enabled.
>>"%BUILD_LOG%" echo ERROR: Python 3 was not found.
pause
exit /b 3

:setup_failed
echo.
echo Environment setup failed.
echo Check the internet connection and build_log.txt.
echo.
type "%BUILD_LOG%"
pause
exit /b 4

:test_failed
echo Automatic tests failed. No EXE was created.
echo Details are saved in build_log.txt.
echo.
type "%BUILD_LOG%"
pause
exit /b 5

:exe_missing
echo PyInstaller finished, but the EXE was not found.
echo Details are saved in build_log.txt.
echo.
type "%BUILD_LOG%"
pause
exit /b 6

:build_failed
echo.
echo The EXE build failed.
echo Details are saved in build_log.txt.
echo.
type "%BUILD_LOG%"
pause
exit /b 7
