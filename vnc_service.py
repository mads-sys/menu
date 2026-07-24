# services/vnc_service.py

import socket
import threading
import time
import logging
import shlex
import os
import sys
import tempfile
import subprocess
import base64
from typing import Dict, Optional, Any
import paramiko

from ssh_service import ssh_connect

logger = logging.getLogger(__name__)

_WEBSOCKIFY_PROCS: Dict[int, subprocess.Popen] = {}
_VNC_LOCK = threading.Lock()

def _is_port_open(ip: str, port: int = 5900, timeout: float = 2.0) -> bool:
    """Verifica se a porta TCP está aberta no host especificado."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (socket.timeout, socket.error):
        return False

def find_free_ws_port(preferred_port: int = 6080, start_port: int = 6080, max_port: int = 6200) -> int:
    """Retorna uma porta TCP local livre para o websockify, priorizando a porta preferida."""
    if not _is_port_open("127.0.0.1", preferred_port, timeout=0.2):
        return preferred_port
    for port in range(start_port, max_port):
        if not _is_port_open("127.0.0.1", port, timeout=0.2):
            return port
    return preferred_port


def stop_websockify_proxy(ws_port: int):
    """Encerra um processo websockify rodando em determinada porta."""
    with _VNC_LOCK:
        proc = _WEBSOCKIFY_PROCS.pop(ws_port, None)
        if proc:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.5)
                    except Exception:
                        proc.kill()
            except Exception as e:
                logger.warning(f"Erro ao encerrar websockify na porta {ws_port}: {e}")

def start_websockify_proxy(target_ip: str, target_port: int = 5900, ws_port: int = 6080) -> Optional[int]:
    """Inicia o proxy websockify local ligando ws_port (WebSocket) -> target_ip:target_port (RFB TCP)."""
    stop_websockify_proxy(ws_port)

    log_path = os.path.join(tempfile.gettempdir(), f"websockify_{ws_port}.log")
    
    # Determina o executável do websockify no ambiente virtual ou via módulo
    venv_bin = os.path.dirname(sys.executable)
    websockify_bin = os.path.join(venv_bin, "websockify.exe" if os.name == 'nt' else "websockify")
    
    if os.path.isfile(websockify_bin):
        cmd = [websockify_bin, "--log-file", log_path, str(ws_port), f"{target_ip}:{target_port}"]
    else:
        cmd = [sys.executable, "-m", "websockify", "--log-file", log_path, str(ws_port), f"{target_ip}:{target_port}"]

    try:
        logger.info(f"Iniciando websockify: {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with _VNC_LOCK:
            _WEBSOCKIFY_PROCS[ws_port] = proc

        # Aguarda até 3 segundos para a porta ficar ativa localmente
        for _ in range(6):
            time.sleep(0.5)
            if proc.poll() is not None:
                logger.error(f"websockify encerrou prematuramente (code={proc.returncode}). Log: {log_path}")
                return None
            if _is_port_open("127.0.0.1", ws_port, timeout=0.5):
                logger.info(f"websockify ativo na porta local {ws_port} -> {target_ip}:{target_port}")
                return ws_port

        logger.warning(f"Timeout aguardando porta {ws_port} do websockify. Retornando porta assim mesmo.")
        return ws_port

    except Exception as e:
        logger.error(f"Exceção ao iniciar websockify na porta {ws_port}: {e}")
        return None


def ensure_remote_vnc_server(ip: str, username: str, password: str, logger: logging.Logger, target_display: Optional[str] = None) -> Dict[str, Any]:
    """
    Garante que um servidor x11vnc esteja rodando na máquina remota.
    Detecta displays X11 (:0, :1, etc), descobre a chave Xauthority e inicia o x11vnc se necessário.
    """
    try:
        with ssh_connect(ip, username, password, logger) as ssh:
            # 1. Detectar displays X11 e sockets ativos no host remoto
            detect_cmd = r"""
            DISPLAYS=$( { ps aux | grep -E '[Xx]org|[Xx]wayland|/usr/lib/Xorg|/usr/bin/X' | grep -v grep | awk '{for(i=1;i<=NF;i++) if($i ~ /^:[0-9]+$/) print $i}'; ls /tmp/.X11-unix/X* 2>/dev/null | sed 's/.*X/:/'; } | sort -u | tr '\n' ' ' )
            echo "DISPLAYS=$DISPLAYS"
            """
            detect_cmd = detect_cmd.replace('\r', '')
            stdin, stdout, stderr = ssh.exec_command(detect_cmd, timeout=10)
            out = stdout.read().decode('utf-8', errors='ignore').strip()
            
            displays = []
            for line in out.split('\n'):
                if line.startswith('DISPLAYS='):
                    disp_str = line.split('=', 1)[1].strip()
                    displays = [d for d in disp_str.split(' ') if d.startswith(':')]
            
            if not displays:
                displays = [":0"]
            
            logger.info(f"Displays detectados em {ip}: {displays}")
            
            # Se a máquina tiver múltiplos assentos e nenhum foi especificado
            if target_display is None:
                if len(displays) > 1:
                    return {
                        "success": True,
                        "multiseat": True,
                        "displays": [{"display": d, "label": f"Tela/Assento {d}"} for d in displays]
                    }
                else:
                    target_display = displays[0]

            try:
                disp_num = int(target_display.replace(':', ''))
            except ValueError:
                disp_num = 0
                target_display = ":0"
            
            rfbport = 5900 + disp_num
            ws_port = find_free_ws_port(preferred_port=6080 + disp_num)

            vnc_ready = False
            if _is_port_open(ip, rfbport, timeout=1.5):
                logger.info(f"Porta VNC {rfbport} (Display {target_display}) já está acessível em {ip}.")
                vnc_ready = True
            else:
                logger.info(f"Porta VNC {rfbport} fechada em {ip}. Tentando iniciar x11vnc via SSH...")
                
                # Instala x11vnc se necessário
                install_cmd = f"which x11vnc >/dev/null 2>&1 || timeout 45 bash -c \"echo '{password}' | sudo -S apt-get update >/dev/null 2>&1; echo '{password}' | sudo -S apt-get install -y x11vnc >/dev/null 2>&1\""
                install_cmd = install_cmd.replace('\r', '')
                ssh.exec_command(install_cmd, timeout=15)

                # Script remoto para encontrar Xauthority (incluindo LightDM/GDM) e iniciar x11vnc
                script_body = f"""
export DISPLAY={shlex.quote(target_display)}
pkill -f "[x]11vnc.*-rfbport {rfbport}" 2>/dev/null || true
rm -f /tmp/x11vnc_{rfbport}.log

# 1. Extrai Xauthority do comando Xorg correspondente ao display alvo
XAUTH=$(ps aux | grep -E '[Xx]org|[Xx]wayland|/usr/lib/Xorg|/usr/bin/X' | grep -F "{target_display}" | grep -oP '(?<=-auth\\s)\\S+' | head -n 1)

# 2. Se não achar especificamente para o display, busca arquivos contendo a referência do display
if [ -z "$XAUTH" ] || [ ! -f "$XAUTH" ]; then
    XAUTH=$(find /var/run/lightdm /run/user /var/run/gdm3 /var/run/gdm ~/.Xauthority /home/*/.Xauthority -name "*Xauthority*" -o -name ":*" 2>/dev/null | grep -F "{target_display}" | head -n 1)
fi

# 3. Fallback genérico de locais conhecidos
if [ -z "$XAUTH" ] || [ ! -f "$XAUTH" ]; then
    XAUTH=$(find /var/run/lightdm /run/user /var/run/gdm3 /var/run/gdm ~/.Xauthority /home/*/.Xauthority -name "*Xauthority*" -o -name ":*" 2>/dev/null | head -n 1)
fi

echo "XAUTHORITY detectada: '$XAUTH'"

if [ -n "$XAUTH" ] && [ -f "$XAUTH" ]; then
    x11vnc -display {shlex.quote(target_display)} -auth "$XAUTH" -forever -shared -nopw -bg -rfbport {rfbport} -noipv6 -o /tmp/x11vnc_{rfbport}.log
else
    x11vnc -display {shlex.quote(target_display)} -auth guess -forever -shared -nopw -bg -rfbport {rfbport} -noipv6 -o /tmp/x11vnc_{rfbport}.log
fi

chmod 666 /tmp/x11vnc_{rfbport}.log 2>/dev/null || true
"""
                b64_script = base64.b64encode(script_body.encode('utf-8')).decode('utf-8')
                vnc_cmd = f"echo {shlex.quote(password)} | sudo -S -p '' bash -c 'echo {b64_script} | base64 -d | bash'"
                vnc_cmd = vnc_cmd.replace('\r', '')
                stdin, stdout, stderr = ssh.exec_command(vnc_cmd, get_pty=True, timeout=15)
                cmd_out = stdout.read().decode('utf-8', errors='ignore').strip()
                logger.debug(f"SSH Output ({ip}): {cmd_out}")

                # Aguarda até 5 segundos para a porta VNC abrir
                for _ in range(10):
                    time.sleep(0.5)
                    if _is_port_open(ip, rfbport, timeout=1.0):
                        logger.info(f"x11vnc ativado com sucesso em {ip}:{rfbport}.")
                        vnc_ready = True
                        break

                if not vnc_ready:
                    log_content = cmd_out or ""
                    try:
                        _, log_file_out, _ = ssh.exec_command(f"cat /tmp/x11vnc_{rfbport}.log 2>/dev/null", timeout=5)
                        file_out = log_file_out.read().decode('utf-8', errors='ignore').strip()
                        if file_out:
                            log_content += f"\n[Arquivo Log]: {file_out}"
                    except Exception:
                        pass
                    
                    if not log_content:
                        log_content = "Comando executado mas a porta 5900 não abriu e nenhum log foi gerado."

                    return {
                        "success": False,
                        "message": f"Não foi possível iniciar o x11vnc no display {target_display} em {ip}.\nLog: {log_content[-500:]}"
                    }

    except Exception as e:
        logger.error(f"Falha de conexão SSH ao iniciar VNC em {ip}: {e}")
        return {"success": False, "message": f"Falha SSH: {str(e)}"}

    if vnc_ready:
        final_ws_port = start_websockify_proxy(ip, rfbport, ws_port)
        if final_ws_port:
            return {
                "success": True,
                "message": f"Servidor VNC pronto no display {target_display}.",
                "ws_port": final_ws_port,
                "target_ip": ip,
                "display": target_display
            }
        return {"success": False, "message": "x11vnc ativo na máquina remota, mas falhou ao iniciar o proxy websockify local."}

    return {"success": False, "message": f"Falha desconhecida ao iniciar VNC em {ip}."}