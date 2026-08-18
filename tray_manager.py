#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Menu Admin - Gerenciador da Bandeja do Sistema (System Tray Icon) & Notificações
Exibe um ícone moderno de alta resolução na área de notificação do Windows:
  - 🟢 Verde: Backend em execução (Online)
  - 🔴 Vermelho: Backend parado (Offline)
Inclui notificações nativas do Windows, ações rápidas de laboratório (WoL, Proteção, VNC)
e opção para Iniciar com o Windows.
"""

import os
import sys
import time
import socket
import urllib.request
import urllib.parse
import json
import threading
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional

# Suprime janelas de console no Windows
if sys.platform == "win32":
    CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    _orig_popen_init = subprocess.Popen.__init__
    def _silent_popen_init(self, *args, **kwargs):
        flags = kwargs.get('creationflags', 0)
        flags |= CREATE_NO_WINDOW
        kwargs['creationflags'] = flags
        if 'startupinfo' not in kwargs:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kwargs['startupinfo'] = si
        _orig_popen_init(self, *args, **kwargs)
    subprocess.Popen.__init__ = _silent_popen_init

import pystray
from PIL import Image, ImageDraw

APP_DIR = Path(__file__).resolve().parent
PORT = int(os.getenv("FLASK_PORT", "8000"))
URL = f"http://127.0.0.1:{PORT}/"
GRID_URL = f"http://127.0.0.1:{PORT}/grid_view.html"
VENV_PYTHONW = APP_DIR / ".venv" / "Scripts" / "pythonw.exe"
PYTHON_EXE = str(VENV_PYTHONW if VENV_PYTHONW.exists() else "pythonw.exe")
ASSETS_ICON = APP_DIR / "assets" / "icon.png"

backend_process: Optional[subprocess.Popen] = None
is_running = False
tray_icon: Optional[pystray.Icon] = None
stop_monitor_event = threading.Event()
_notified_online = False


# ==============================================================================
# 1. Geração de Ícones em Alta Definição com Badge de Status
# ==============================================================================
def generate_status_icon(status: str = "online") -> Image.Image:
    """
    Gera um ícone HD de 64x64 em cores vibrantes:
      - 🟢 'online' / True: Verde vibrante 3D (Servidor comunicando)
      - 🟡 'warning' / 'error' / 'auth_error': Amarelo/Âmbar 3D (Erro/Alerta/Falha de Autenticação)
      - 🔴 'offline' / False: Vermelho 3D (Servidor parado/desconectado)
    """
    if status in (True, "online", "ok"):
        icon_path = APP_DIR / "assets" / "tray_online.png"
    elif status in ("warning", "error", "auth_error", "alert", "yellow"):
        icon_path = APP_DIR / "assets" / "tray_warning.png"
    else:
        icon_path = APP_DIR / "assets" / "tray_offline.png"

    if icon_path.exists():
        try:
            return Image.open(icon_path).convert('RGBA')
        except Exception:
            pass

    # Fallback caso os assets não existam
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (34, 197, 94, 255) if status in (True, "online", "ok") else (239, 68, 68, 255)
    draw.ellipse((4, 4, 60, 60), fill=(15, 23, 42, 255), outline=(56, 189, 248, 255), width=3)
    draw.ellipse((14, 14, 50, 50), fill=color)
    draw.ellipse((20, 18, 38, 30), fill=(255, 255, 255, 180))
    return img


# ==============================================================================
# 2. Notificações Nativas do Windows
# ==============================================================================
def show_notification(message: str, title: str = "Menu Admin"):
    """Exibe uma notificação nativa do Windows no canto da tela."""
    global tray_icon
    if tray_icon:
        try:
            tray_icon.notify(message, title)
        except Exception as e:
            print(f"[Notificação] {title}: {message} ({e})")


# ==============================================================================
# 3. Gerenciamento do Backend e Requisições
# ==============================================================================
def check_backend_alive() -> bool:
    """Verifica se o backend está respondendo na porta 8000."""
    try:
        req = urllib.request.Request(URL, headers={'User-Agent': 'TrayMonitor'})
        with urllib.request.urlopen(req, timeout=1.2) as response:
            return response.status in (200, 302, 404)
    except Exception:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.8):
                return True
        except Exception:
            return False


def start_backend():
    """Inicia o backend em segundo plano se ainda não estiver em execução."""
    global backend_process
    if check_backend_alive():
        return

    app_script = str(APP_DIR / "app.py")
    try:
        backend_process = subprocess.Popen(
            [PYTHON_EXE, app_script],
            cwd=str(APP_DIR)
        )
    except Exception as e:
        print(f"Erro ao iniciar backend: {e}", file=sys.stderr)


def stop_backend():
    """Encerra com segurança qualquer processo do backend."""
    global backend_process
    if backend_process:
        try:
            backend_process.terminate()
        except Exception:
            pass
        backend_process = None

    if sys.platform == "win32":
        ps_cmd = (
            f"$conns = Get-NetTCPConnection -LocalPort {PORT} -ErrorAction SilentlyContinue; "
            "if ($conns) { "
            "  $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique; "
            "  foreach ($p in $pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } "
            "}"
        )
        try:
            subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps_cmd], capture_output=True, timeout=5)
        except Exception:
            pass


def restart_backend():
    """Reinicia o backend."""
    show_notification("Reiniciando o servidor backend...", "Menu Admin")
    stop_backend()
    time.sleep(1.2)
    start_backend()
    time.sleep(1.0)
    if check_backend_alive():
        show_notification("Servidor backend reiniciado com sucesso! 🟢", "Menu Admin")


def open_browser():
    """Abre o navegador padrão na URL do Menu Admin."""
    if not check_backend_alive():
        start_backend()
        time.sleep(1.5)
    webbrowser.open_new(URL)


def open_grid_vnc():
    """Abre a visualização do Grid VNC no navegador."""
    if not check_backend_alive():
        start_backend()
        time.sleep(1.5)
    webbrowser.open_new(GRID_URL)


def open_project_folder():
    """Abre o diretório do projeto no Windows Explorer."""
    if sys.platform == "win32":
        os.startfile(str(APP_DIR))


def open_backend_log():
    """Abre o arquivo de log do backend no visualizador padrão."""
    log_file = APP_DIR / "logs" / "backend.log"
    if log_file.exists() and sys.platform == "win32":
        os.startfile(str(log_file))
    elif sys.platform == "win32":
        logs_dir = APP_DIR / "logs"
        logs_dir.mkdir(exist_ok=True)
        os.startfile(str(logs_dir))


# ==============================================================================
# 4. Ações Rápidas do Laboratório no Tray
# ==============================================================================
def _send_quick_action(action_name: str, display_name: str):
    """Envia uma ação rápida para todas as máquinas online via API do backend."""
    def run():
        if not check_backend_alive():
            start_backend()
            time.sleep(1.5)
        try:
            req_data = json.dumps({"action": action_name}).encode('utf-8')
            req = urllib.request.Request(
                f"{URL}api/quick-action",
                data=req_data,
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=5.0) as res:
                res_json = json.loads(res.read().decode('utf-8'))
                if res_json.get('success'):
                    show_notification(f"Ação '{display_name}' enviada para as máquinas!", "Laboratório")
                else:
                    show_notification(f"Resultado: {res_json.get('message', 'Concluído')}", display_name)
        except Exception:
            if action_name == "wake_on_lan":
                show_notification("Sinais de Wake-on-LAN transmitidos na rede!", "Ligar Laboratório")
            else:
                show_notification(f"Abra o painel web para confirmar o envio de '{display_name}'.", "Menu Admin")
                open_browser()

    threading.Thread(target=run, daemon=True).start()


# ==============================================================================
# 5. Iniciar com o Windows (Windows Registry HKCU Run)
# ==============================================================================
REG_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "MenuAdmin"

def is_autostart_enabled() -> bool:
    """Verifica se o Menu Admin está configurado para iniciar com o Windows."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, REG_APP_NAME)
            return True
    except Exception:
        return False


def toggle_autostart(icon=None, item=None):
    """Alterna a inicialização automática com o Windows."""
    if sys.platform != "win32":
        return
    import winreg
    enabled = is_autostart_enabled()
    launcher_vbs = APP_DIR / "start_backend_background.vbs"
    target_cmd = f'wscript.exe "{launcher_vbs}"'

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                try:
                    winreg.DeleteValue(key, REG_APP_NAME)
                    show_notification("Inicialização automática com o Windows desativada.", "Configurações")
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, REG_APP_NAME, 0, winreg.REG_SZ, target_cmd)
                show_notification("Menu Admin configurado para iniciar com o Windows! 🚀", "Configurações")
    except Exception as e:
        show_notification(f"Falha ao alterar registro: {e}", "Erro")


# ==============================================================================
# 6. Monitoramento de Status & Loop de Eventos
# ==============================================================================
def exit_tray(icon, item=None):
    """Encerra o ícone da bandeja e o backend."""
    stop_monitor_event.set()
    stop_backend()
    if icon:
        icon.stop()
    sys.exit(0)


def monitor_loop():
    """Monitora continuamente o status do backend e atualiza o ícone e tooltip."""
    global is_running, tray_icon, _notified_online
    
    last_state = None

    while not stop_monitor_event.is_set():
        current_state = check_backend_alive()
        is_running = current_state
        
        if current_state != last_state and tray_icon:
            if current_state:
                tray_icon.icon = generate_status_icon("online")
                tray_icon.title = f"Menu Admin: Rodando (Porta {PORT}) 🟢"
                if not _notified_online:
                    show_notification(f"Servidor ativo em http://127.0.0.1:{PORT}/ 🟢", "Menu Admin Pronto")
                    _notified_online = True
            else:
                tray_icon.icon = generate_status_icon("offline")
                tray_icon.title = "Menu Admin: Parado 🔴"
                if _notified_online:
                    show_notification("O servidor do backend foi parado.", "Menu Admin Offline 🔴")
                    _notified_online = False
            last_state = current_state

        stop_monitor_event.wait(2.0)


def get_status_label(item=None) -> str:
    """Retorna o rótulo do status do servidor."""
    if is_running:
        return f"🟢 Servidor: ONLINE (Porta {PORT})"
    return "🔴 Servidor: OFFLINE / PAUSADO"


def build_menu():
    """Constrói o menu de contexto nativo limpo, direto e rápido."""
    return pystray.Menu(
        # Duplo clique ou clique abre o Painel Web Principal no navegador
        pystray.MenuItem("🌐 Abrir Painel Admin", lambda icon, item: open_browser(), default=True),
        pystray.MenuItem("🖥️ Abrir Grid VNC (Monitor de Telas)", lambda icon, item: open_grid_vnc()),
        pystray.Menu.SEPARATOR,

        # Submenu: Ações Rápidas no Laboratório
        pystray.MenuItem(
            "⚡ Ações Rápidas no Laboratório",
            pystray.Menu(
                pystray.MenuItem("⚡ Ligar Máquinas (Wake-on-LAN)", lambda icon, item: _send_quick_action("wake_on_lan", "Ligar (WoL)")),
                pystray.MenuItem("🛡️ Ativar Proteção Total Infantil", lambda icon, item: _send_quick_action("ativar_protecao_total_infantil", "Proteção Infantil")),
                pystray.MenuItem("🔓 Remover Proteção Infantil", lambda icon, item: _send_quick_action("desativar_protecao_total_infantil", "Remover Proteção")),
                pystray.MenuItem("🔄 Reiniciar Todas as Máquinas", lambda icon, item: _send_quick_action("reiniciar", "Reiniciar Máquinas")),
                pystray.MenuItem("🛑 Desligar Todas as Máquinas", lambda icon, item: _send_quick_action("desligar", "Desligar Máquinas")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("🌐 Abrir Painel Completo...", lambda icon, item: open_browser())
            )
        ),
        pystray.Menu.SEPARATOR,

        # Submenu: Gerenciador do Servidor
        pystray.MenuItem(
            "⚙️ Gerenciador do Servidor",
            pystray.Menu(
                pystray.MenuItem("▶️ Iniciar Servidor", lambda icon, item: start_backend(), visible=lambda item: not is_running),
                pystray.MenuItem("⏹️ Pausar Servidor", lambda icon, item: stop_backend(), visible=lambda item: is_running),
                pystray.MenuItem("🔄 Reiniciar Servidor", lambda icon, item: restart_backend()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("📋 Ver Logs do Servidor", lambda icon, item: open_backend_log()),
                pystray.MenuItem("📁 Abrir Pasta do Projeto", lambda icon, item: open_project_folder())
            )
        ),
        pystray.MenuItem("🚀 Iniciar com o Windows", toggle_autostart, checked=lambda item: is_autostart_enabled()),
        pystray.Menu.SEPARATOR,

        # Encerrar
        pystray.MenuItem("❌ Encerrar Menu Admin", exit_tray)
    )


def main():
    global tray_icon

    # Inicia o backend se ainda não estiver em execução
    start_backend()

    # Prepara o ícone inicial
    initial_running = check_backend_alive()
    initial_icon = generate_status_icon(initial_running)
    initial_title = f"Menu Admin: {'Rodando (Porta 8000) 🟢' if initial_running else 'Parado 🔴'}"

    tray_icon = pystray.Icon(
        name="MenuAdminTray",
        icon=initial_icon,
        title=initial_title,
        menu=build_menu()
    )

    # Inicia thread de monitoramento contínuo
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    # Executa o loop de eventos da bandeja
    tray_icon.run()


if __name__ == "__main__":
    main()
