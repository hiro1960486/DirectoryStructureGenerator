@echo off
setlocal
cd /d "%~dp0"
title Directory Structure Generator - Fast Test Build

echo ============================================================
echo Fast test build: EXE only, ZIP creation is skipped
echo ============================================================
echo.

call "%~dp0build_exe.bat" nozip
exit /b %ERRORLEVEL%
