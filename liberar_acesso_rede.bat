@echo off
setlocal EnableDelayedExpansion
title Liberar Acesso de Rede - Menu Admin

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ====================================================================
    echo   SOLICITANDO PERMISSAO DE ADMINISTRADOR...
    echo ====================================================================
    echo.
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo.
echo ====================================================================
echo   CONFIGURANDO ACESSO DE REDE LOCAL (WSL MODO ESPELHADO)
echo ====================================================================
echo.

echo [1/3] Liberando portas no Firewall do Windows...
netsh advfirewall firewall delete rule name="Menu Servidor 5050" >nul 2>&1
netsh advfirewall firewall add rule name="Menu Servidor 5050" dir=in action=allow protocol=TCP localport=5050 >nul 2>&1

netsh advfirewall firewall delete rule name="Menu VNC Websockify 5900-7500" >nul 2>&1
netsh advfirewall firewall add rule name="Menu VNC Websockify 5900-7500" dir=in action=allow protocol=TCP localport=5900-7500 >nul 2>&1
echo   -> Portas 5050 e 5900-7500 liberadas no Firewall!

echo.
echo [2/3] Liberando a porta 5050 no Windows (Limpando conflitos antigos de portproxy)...
netsh interface portproxy delete v4tov4 listenport=5050 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0 >nul 2>&1
for /L %%p in (6080,1,6150) do (
    netsh interface portproxy delete v4tov4 listenport=%%p listenaddress=0.0.0.0 >nul 2>&1
)
net stop iphlpsvc >nul 2>&1
net start iphlpsvc >nul 2>&1
echo   -> Porta 5050 liberada e desimpedida com sucesso!

set LOCAL_IP=192.168.0.139
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4" /c:"Endereco IPv4"') do (
    set LOCAL_IP=%%a
    goto :ip_done
)
:ip_done
set LOCAL_IP=%LOCAL_IP: =%

echo.
echo ====================================================================
echo   SUCESSO! TUDO PRONTO PARA O BACKEND
echo ====================================================================
echo.
echo   Agora voce pode executar no WSL:
echo   -> ./run_backend.sh
echo.
echo   E acessar de qualquer computador na rede:
echo   -> http://%LOCAL_IP%:5050/
echo.
echo ====================================================================
echo.
pause
