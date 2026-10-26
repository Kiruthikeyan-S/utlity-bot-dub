@echo off
title Utility Bot Server
cd /d "%~dp0"
echo ============================================================
echo Starting Utility Bot Server...
echo ============================================================

if exist "C:\Python314\python.exe" (
    "C:\Python314\python.exe" run.py
) else (
    python run.py
)
pause
