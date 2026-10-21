@echo off
setlocal EnableDelayedExpansion
title Liberar Acesso Windows Direto - Menu Admin

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
echo   CONFIGURANDO ACESSO DIRETO WINDOWS NATIVO (SEM INTERMEDIACAO WSL)
echo ====================================================================
echo.

echo [1/2] Liberando portas no Firewall do Windows...
netsh advfirewall firewall delete rule name="Menu Servidor 5950" >nul 2>&1
netsh advfirewall firewall add rule name="Menu Servidor 5950" dir=in action=allow protocol=TCP localport=5950 >nul 2>&1

netsh advfirewall firewall delete rule name="Menu Servidor 5050" >nul 2>&1
netsh advfirewall firewall add rule name="Menu Servidor 5050" dir=in action=allow protocol=TCP localport=5050 >nul 2>&1

netsh advfirewall firewall delete rule name="Menu VNC Websockify 6080" >nul 2>&1
netsh advfirewall firewall add rule name="Menu VNC Websockify 6080" dir=in action=allow protocol=TCP localport=6080 >nul 2>&1

netsh advfirewall firewall delete rule name="Menu VNC Websockify 5900-7500" >nul 2>&1
netsh advfirewall firewall add rule name="Menu VNC Websockify 5900-7500" dir=in action=allow protocol=TCP localport=5900-7500 >nul 2>&1
echo   -> Portas 5950, 5050, 6080 e 5900-7500 liberadas no Firewall!

echo.
echo [2/2] Removendo redirecionamentos Portproxy do WSL (para execucao nativa no Windows)...
netsh interface portproxy delete v4tov4 listenport=5950 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=5050 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=6080 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0 >nul 2>&1
echo   -> Portproxy limpo: As conexoes agora vao diretamente para o Python no Windows!

set LOCAL_IP=192.168.0.4
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4" /c:"Endereco IPv4"') do (
    set LOCAL_IP=%%a
    goto :ip_done
)
:ip_done
set LOCAL_IP=%LOCAL_IP: =%

echo.
echo ====================================================================
echo   SUCESSO! O SERVIDOR WINDOWS ESTA LIBERADO NA REDE LOCAL
echo ====================================================================
echo.
echo   Acesse de qualquer maquina da rede em:
echo   -> http://%LOCAL_IP%:5950/
echo   -> Grid VNC: http://%LOCAL_IP%:5950/grid_view.html
echo.
echo ====================================================================
echo.
pause
