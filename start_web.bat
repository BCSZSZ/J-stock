@echo off
chcp 65001 >nul
title J-Stock Dashboard

cd /d "%~dp0"

:: Sync dependencies via uv (includes web group)
uv sync --group web

:: Install frontend dependencies if needed
if not exist "web\frontend\node_modules" (
    echo [setup] Installing frontend dependencies ...
    cd web\frontend
    call npm install
    cd /d "%~dp0"
)

:: Launch backend + frontend
echo [start] Starting J-Stock Dashboard ...
uv run --group web python web\start.py

pause
