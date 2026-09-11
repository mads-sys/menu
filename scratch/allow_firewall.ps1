netsh advfirewall firewall add rule name="Menu Servidor 5050" dir=in action=allow protocol=TCP localport=5050
netsh advfirewall firewall add rule name="Menu VNC Websockify 5900-7500" dir=in action=allow protocol=TCP localport=5900-7500
Write-Host "Regras do Firewall (Portas 5050 e 5900-7500) liberadas com sucesso!" -ForegroundColor Green
Start-Sleep -Seconds 3
