@echo off
setlocal
taskkill /im causia-agent.exe /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v CausiaAgente /f >nul 2>&1
rmdir /s /q "%LOCALAPPDATA%\CausiaAgente" >nul 2>&1
echo Agente Causia removido.
pause
