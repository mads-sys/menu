# ==============================================================================
# Script para criar Atalhos do Menu Admin no Desktop e Menu Iniciar
# ==============================================================================

$WshShell = New-Object -ComObject WScript.Shell
$ProjectDir = (Get-Item -Path $PSScriptRoot).FullName
$DesktopPath = [Environment]::GetFolderPath('Desktop')
$StartMenuPath = [Environment]::GetFolderPath('Programs')

$LauncherVbs = Join-Path $ProjectDir "start_backend_background.vbs"
$StopBat = Join-Path $ProjectDir "stop_backend.bat"
$IconFile = Join-Path $ProjectDir "assets\icon.ico"

if (-not (Test-Path $IconFile)) {
    $IconFile = Join-Path $ProjectDir "novnc\app\images\icons\novnc.ico"
}

if (-not (Test-Path $IconFile)) {
    $IconLocation = "shell32.dll,14"
} else {
    $IconLocation = "$IconFile,0"
}

# 1. Atalho no Desktop para INICIAR em Segundo Plano
$ShortcutDesktop = $WshShell.CreateShortcut((Join-Path $DesktopPath "Menu Admin.lnk"))
$ShortcutDesktop.TargetPath = "wscript.exe"
$ShortcutDesktop.Arguments = "`"$LauncherVbs`""
$ShortcutDesktop.WorkingDirectory = $ProjectDir
$ShortcutDesktop.IconLocation = $IconLocation
$ShortcutDesktop.Description = "Iniciar Menu Admin em Segundo Plano"
$ShortcutDesktop.Save()
Write-Host "[OK] Atalho criado na Area de Trabalho: Menu Admin.lnk" -ForegroundColor Green

# 2. Atalho no Desktop para PARAR Backend
$ShortcutStop = $WshShell.CreateShortcut((Join-Path $DesktopPath "Parar Menu Admin.lnk"))
$ShortcutStop.TargetPath = $StopBat
$ShortcutStop.WorkingDirectory = $ProjectDir
$ShortcutStop.IconLocation = "shell32.dll,131" # Red Stop Icon
$ShortcutStop.Description = "Encerrar Menu Admin Backend"
$ShortcutStop.Save()
Write-Host "[OK] Atalho criado na Area de Trabalho: Parar Menu Admin.lnk" -ForegroundColor Green

# 3. Atalho no Menu Iniciar
if (Test-Path $StartMenuPath) {
    $ShortcutStartMenu = $WshShell.CreateShortcut((Join-Path $StartMenuPath "Menu Admin.lnk"))
    $ShortcutStartMenu.TargetPath = "wscript.exe"
    $ShortcutStartMenu.Arguments = "`"$LauncherVbs`""
    $ShortcutStartMenu.WorkingDirectory = $ProjectDir
    $ShortcutStartMenu.IconLocation = $IconLocation
    $ShortcutStartMenu.Description = "Iniciar Menu Admin em Segundo Plano"
    $ShortcutStartMenu.Save()
    Write-Host "[OK] Atalho criado no Menu Iniciar: Menu Admin.lnk" -ForegroundColor Green
}

Write-Host "`n--> Para fixar na Barra de Tarefas:" -ForegroundColor Cyan
Write-Host "    Clique com o botao direito no atalho 'Menu Admin' na Area de Trabalho e selecione 'Fixar na barra de tarefas'." -ForegroundColor Yellow
