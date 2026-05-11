@echo off
chcp 65001 >nul
title J-Stock Web UI

cd /d "%~dp0"

if not exist "%~dp0start_web.bat" (
    echo [error] start_web.bat not found in %~dp0
    pause
    exit /b 1
)

echo [start] J-Stock Web UI launcher
echo [info] Frontend: http://localhost:5173
echo [info] Backend:  http://localhost:8000
echo.

call "%~dp0start_web.bat"