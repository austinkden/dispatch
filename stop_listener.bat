@echo off
title Stop Trace Dispatch Listener
echo Stopping background audio slicer processes...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Trace Dispatch*" >nul 2>&1
taskkill /F /IM ffmpeg.exe >nul 2>&1
echo Done! Background listener stopped.
timeout /t 2 >nul
exit
