@echo off
setlocal
title Encerrando Menu Admin Backend e Tray Icon
chcp 65001 >nul

echo ======================================================
echo    Encerrando Menu Admin (Porta 8000 + Bandeja)...
echo ======================================================

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$conns = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue; " ^
    "if ($conns) { " ^
    "    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique; " ^
    "    foreach ($p in $pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }; " ^
    "}; " ^
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*app.py*' -or $_.CommandLine -like '*tray_manager.py*' } | ForEach-Object { " ^
    "    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; " ^
    "}; " ^
    "Write-Host '--> Servidor e Icone da Bandeja finalizados com sucesso.' -ForegroundColor Green"

ping 127.0.0.1 -n 2 >nul
