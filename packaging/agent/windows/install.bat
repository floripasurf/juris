@echo off
REM packaging/agent/windows/install.bat — instala o Agente Causia no perfil do usuário.
REM Sem admin, sem abrir porta (o agente só disca para fora). SmartScreen pode avisar
REM em .exe nao assinado: "Mais informacoes" -> "Executar assim mesmo" (esperado).
setlocal
set DEST=%LOCALAPPDATA%\CausiaAgente
echo Instalando em %DEST% ...
if exist "%DEST%" rmdir /s /q "%DEST%"
xcopy /e /i /y "%~dp0causia-agent" "%DEST%" >nul
REM auto-start no login (Run key do usuario — nao precisa de admin)
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v CausiaAgente ^
  /t REG_SZ /d "\"%DEST%\causia-agent.exe\"" /f >nul
echo Iniciando o agente...
start "" "%DEST%\causia-agent.exe"
echo.
echo Pronto! Agora abra causia.com.br -^> Acervo -^> Conectar agente local.
pause
