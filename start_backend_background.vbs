' ==============================================================================
' Launcher em Segundo Plano com Ícone na Bandeja (Tray) - Menu Admin
' Executa o Tray Manager silenciosamente via pythonw sem tela de prompt.
' ==============================================================================

Option Explicit
Dim WshShell, fso, currentDir, pythonwExe, trayScript, http, isRunning, url

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonwExe = currentDir & "\.venv\Scripts\pythonw.exe"
trayScript = currentDir & "\tray_manager.py"
url = "http://127.0.0.1:8000/"

WshShell.CurrentDirectory = currentDir

If Not fso.FileExists(pythonwExe) Then
    pythonwExe = "pythonw.exe"
End If

' Inicia o Tray Manager em segundo plano
WshShell.Run """" & pythonwExe & """ """ & trayScript & """", 0, False

' Abre a URL no navegador
WshShell.Run url, 1, False
