
@echo off
title Greed Roster Bot Maintenance Toggle

fltmc >nul 2>&1
if errorlevel 1 (
    echo Requesting Administrator privileges...
    powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Greed_Bot_Toggle.ps1"

echo.
pause