@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_simulation.ps1" %*
set "simulationExit=%errorlevel%"
if not "%simulationExit%"=="0" pause
exit /b %simulationExit%
