# Script PowerShell para abrir a porta 5050 e VNC na rede local
$wsliP = (wsl -e hostname -I 2>$null).Trim().Split(" ")[0]
if (-not $wsliP) { $wsliP = "172.31.97.238" }

Write-Host "Configurando Firewall e Portproxy para WSL IP: $wsliP..." -ForegroundColor Cyan

# 1. Regras do Firewall
netsh advfirewall firewall delete rule name="Menu Servidor 5050" 2>$null
netsh advfirewall firewall add rule name="Menu Servidor 5050" dir=in action=allow protocol=TCP localport=5050

netsh advfirewall firewall delete rule name="Menu VNC Websockify 5900-7500" 2>$null
netsh advfirewall firewall add rule name="Menu VNC Websockify 5900-7500" dir=in action=allow protocol=TCP localport=5900-7500

# 2. Portproxy do Windows para o WSL
netsh interface portproxy delete v4tov4 listenport=5050 listenaddress=0.0.0.0 2>$null
netsh interface portproxy add v4tov4 listenport=5050 listenaddress=0.0.0.0 connectport=5050 connectaddress=$wsliP

netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0 2>$null
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=$wsliP

Write-Host "`nRegras aplicadas com sucesso!" -ForegroundColor Green
Write-Host "Verificando tabela Portproxy:" -ForegroundColor Yellow
netsh interface portproxy show v4tov4

Write-Host "`nServidor liberado em: http://192.168.0.139:5050/" -ForegroundColor Green
Start-Sleep -Seconds 5
