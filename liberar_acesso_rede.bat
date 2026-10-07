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
echo   CONFIGURANDO ACESSO DE REDE LOCAL (PORTA 5950, 5050 E VNC)
echo ====================================================================
echo.

set WSL_IP=
for /f "tokens=1" %%a in ('wsl.exe -e hostname -I 2^>nul') do (
    set WSL_IP=%%a
    goto :wsl_done
)
:wsl_done
if "%WSL_IP%"=="" set WSL_IP=172.28.31.100
echo [1/3] IP do WSL detectado: %WSL_IP%

echo [2/3] Liberando portas no Firewall do Windows...
netsh advfirewall firewall delete rule name="Menu Servidor 5950" >nul 2>&1
netsh advfirewall firewall add rule name="Menu Servidor 5950" dir=in action=allow protocol=TCP localport=5950 >nul 2>&1

netsh advfirewall firewall delete rule name="Menu Servidor 5050" >nul 2>&1
netsh advfirewall firewall add rule name="Menu Servidor 5050" dir=in action=allow protocol=TCP localport=5050 >nul 2>&1

netsh advfirewall firewall delete rule name="Menu VNC Websockify 5900-7500" >nul 2>&1
netsh advfirewall firewall add rule name="Menu VNC Websockify 5900-7500" dir=in action=allow protocol=TCP localport=5900-7500 >nul 2>&1
echo   -> Portas 5950, 5050 e 5900-7500 liberadas no Firewall!

echo.
echo [3/3] Configurando Port Forwarding (Portproxy) do Windows para o WSL...
netsh interface portproxy delete v4tov4 listenport=5950 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy add v4tov4 listenport=5950 listenaddress=0.0.0.0 connectport=5950 connectaddress=%WSL_IP% >nul 2>&1

netsh interface portproxy delete v4tov4 listenport=5050 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy add v4tov4 listenport=5050 listenaddress=0.0.0.0 connectport=5050 connectaddress=%WSL_IP% >nul 2>&1

netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=%WSL_IP% >nul 2>&1
echo   -> Redirecionamento 0.0.0.0:5950 -> %WSL_IP%:5950 configurado com sucesso!

set LOCAL_IP=192.168.0.4
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4" /c:"Endereco IPv4"') do (
    set LOCAL_IP=%%a
    goto :ip_done
)
:ip_done
set LOCAL_IP=%LOCAL_IP: =%

echo.
echo ====================================================================
echo   SUCESSO! ACESSO DE REDE LOCAL LIBERADO
echo ====================================================================
echo.
echo   Voce ja pode acessar de qualquer computador ou celular na rede:
echo   -> http://%LOCAL_IP%:5950/
echo.
echo ====================================================================
echo.
pause
