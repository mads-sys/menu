#!/usr/bin/env bash
# Script para liberar portas no Firewall do Windows e configurar Port Forwarding diretamente pelo WSL

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}====================================================================${NC}"
echo -e "${GREEN}  CONFIGURANDO ACESSO DE REDE LOCAL (PORTA 5950 E VNC)${NC}"
echo -e "${GREEN}====================================================================${NC}\n"

if [ -x "/init" ] && [ -x "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" ]; then
    POWERSHELL_BIN="/init /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
elif command -v powershell.exe &>/dev/null; then
    POWERSHELL_BIN="powershell.exe"
else
    POWERSHELL_BIN="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
fi

# 1. Obter IP do WSL
WSL_IP=$(hostname -I | awk '{print $1}')
echo -e "${YELLOW}--> IP interno do WSL detectado:${NC} $WSL_IP"

# 2. Obter IP da placa de rede Windows (LAN)
WIN_LAN_IP=$($POWERSHELL_BIN -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.InterfaceAlias -match 'Ethernet|Wi-Fi' -and \$_.IPAddress -notlike '169.254*' -and \$_.IPAddress -notlike '127.*' -and \$_.IPAddress -notlike '172.*' } | Select-Object -First 1).IPAddress" 2>/dev/null | tr -d '\r\n')

if [ -z "$WIN_LAN_IP" ]; then
    WIN_LAN_IP="192.168.0.4"
fi
echo -e "${YELLOW}--> IP da rede local do Windows (LAN):${NC} $WIN_LAN_IP"

echo -e "\n${YELLOW}--> Solicitando autorizacao do Windows (UAC) para aplicar regras de Firewall e Portproxy...${NC}"

# Comando PowerShell que roda elevado (Administrador) no Windows
PS_ADMIN_CMD="
    Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -Command \"
        netsh advfirewall firewall delete rule name=\\\"Menu Servidor 5950\\\" 2>\$null
        netsh advfirewall firewall add rule name=\\\"Menu Servidor 5950\\\" dir=in action=allow protocol=TCP localport=5950
        netsh advfirewall firewall delete rule name=\\\"Menu Servidor 5050\\\" 2>\$null
        netsh advfirewall firewall add rule name=\\\"Menu Servidor 5050\\\" dir=in action=allow protocol=TCP localport=5050
        netsh advfirewall firewall delete rule name=\\\"Menu VNC Websockify 5900-7500\\\" 2>\$null
        netsh advfirewall firewall add rule name=\\\"Menu VNC Websockify 5900-7500\\\" dir=in action=allow protocol=TCP localport=5900-7500
        netsh interface portproxy delete v4tov4 listenport=5950 listenaddress=0.0.0.0 2>\$null
        netsh interface portproxy add v4tov4 listenport=5950 listenaddress=0.0.0.0 connectport=5950 connectaddress=$WSL_IP
        netsh interface portproxy delete v4tov4 listenport=5050 listenaddress=0.0.0.0 2>\$null
        netsh interface portproxy add v4tov4 listenport=5050 listenaddress=0.0.0.0 connectport=5050 connectaddress=$WSL_IP
        netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0 2>\$null
        netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=$WSL_IP
    \"'
"

$POWERSHELL_BIN -NoProfile -Command "$PS_ADMIN_CMD"

echo -e "\n${GREEN}====================================================================${NC}"
echo -e "${GREEN}  CONCLUIDO!${NC}"
echo -e "${GREEN}====================================================================${NC}"
echo -e "Uma janela de permissao do Windows foi aberta. Clique em ${YELLOW}'Sim'${NC} para confirmar."
echo -e "\nApos confirmar, o painel estara acessivel de qualquer computador na rede em:"
echo -e "  --> ${GREEN}http://${WIN_LAN_IP}:5950/${NC}\n"
