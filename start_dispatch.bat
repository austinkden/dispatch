@echo off
title Trace Dispatch - Emergency Audio Indexer
cd /d "%~dp0"

echo ===================================================
echo   TRACE DISPATCH - STARTING BACKGROUND LISTENER
echo ===================================================

:: Start background Python audio listener
start /b "" "C:\Users\austi\AppData\Local\Python\pythoncore-3.14-64\python.exe" -u slicer.py

:: Wait 1 second and open dashboard in default browser
timeout /t 1 /nobreak >nul
start "" "%~dp0index.html"

echo Listener is running in the background.
echo Dashboard opened in your browser.
exit
