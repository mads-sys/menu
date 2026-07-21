# services/vnc_service.py

import socket
import threading
import time
import logging
from typing import Dict, Optional, Any
import paramiko

from ssh_service import ssh_connect

logger = logging.getLogger(__name__)

_VNC_SESSIONS: Dict[str, Dict[str, Any]] = {}
_VNC_LOCK = threading.Lock()

def _is_port_open(ip: str, port: int = 5900, timeout: float = 2.0) -> bool:
    """Verifica se a porta VNC está aberta no host remoto."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (socket.timeout, socket.error):
        return False

import subprocess

_WEBSOCKIFY_PROCS: Dict[int, subprocess.Popen] = {}

def start_websockify_proxy(target_ip: str, target_port: int = 5900, ws_port: int = 6080) -> Optional[int]:
    """Inicia o websockify na porta ws_port ligando ao TCP target_ip:target_port."""
    import sys, os

    # Encerra processo anterior nesta porta, se houver
    with _VNC_LOCK:
        if ws_port in _WEBSOCKIFY_PROCS:
            proc = _WEBSOCKIFY_PROCS[ws_port]
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    proc.kill()
            _WEBSOCKIFY_PROCS.pop(ws_port, None)

    # Usa o websockify do mesmo ambiente virtual do Python
    venv_bin = os.path.dirname(sys.executable)
    websockify_bin = os.path.join(venv_bin, "websockify")
    if not os.path.isfile(websockify_bin):
        # Fallback: módulo python -m websockify
        cmd = [sys.executable, "-m", "websockify", "--log-file", "/tmp/websockify.log",
               str(ws_port), f"{target_ip}:{target_port}"]
    else:
        cmd = [websockify_bin, "--log-file", "/tmp/websockify.log",
               str(ws_port), f"{target_ip}:{target_port}"]

    try:
        logger.info(f"Iniciando websockify: {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with _VNC_LOCK:
            _WEBSOCKIFY_PROCS[ws_port] = proc

        # Aguarda até 3 segundos para o websockify abrir a porta
        for _ in range(6):
            time.sleep(0.5)
            if proc.poll() is not None:
                logger.error(f"websockify terminou prematuramente (exit={proc.returncode})")
                return None
            if _is_port_open("127.0.0.1", ws_port, timeout=0.5):
                logger.info(f"websockify pronto na porta {ws_port} -> {target_ip}:{target_port}")
                return ws_port

        logger.warning(f"Timeout aguardando websockify na porta {ws_port}")
        return ws_port  # Retorna mesmo assim — pode demorar um pouco mais

    except Exception as e:
        logger.error(f"Erro ao iniciar websockify na porta {ws_port}: {e}")
        return None



def ensure_remote_vnc_server(ip: str, username: str, password: str, logger: logging.Logger) -> Dict[str, Any]:
    """
    Garante que um servidor VNC (x11vnc) esteja em execução na máquina remota.
    Detecta automaticamente o display X11 ativo e o XAUTHORITY correto.
    """
    vnc_ready = False
    if _is_port_open(ip, 5900, timeout=1.5):
        logger.info(f"Porta VNC 5900 já está aberta em {ip}.")
        vnc_ready = True
    else:
        logger.info(f"Porta VNC 5900 fechada em {ip}. Iniciando x11vnc via SSH...")
        try:
            with ssh_connect(ip, username, password, logger) as ssh:
                # Instala x11vnc se necessário
                stdin, stdout, stderr = ssh.exec_command(
                    "which x11vnc >/dev/null 2>&1 || (sudo apt-get install -y x11vnc 2>/dev/null | tail -1)",
                    timeout=30
                )
                stdout.channel.recv_exit_status()

                # Detecta display e XAUTHORITY ativos automaticamente:
                # 1. Procura processos Xorg/:X em qualquer display (:0, :1, :2...)
                # 2. Encontra o arquivo .Xauthority do usuário dono da sessão
                # 3. Inicia x11vnc com esses parâmetros
                vnc_cmd = r"""
set -e

# Para se já estiver rodando
pgrep -x x11vnc >/dev/null 2>&1 && exit 0

# Detecta display ativo (tenta :0, :1, :2)
DISPLAY_NUM=""
for d in 0 1 2 3; do
    if xdpyinfo -display ":$d" >/dev/null 2>&1; then
        DISPLAY_NUM=":$d"
        break
    fi
done

# Fallback: pega display do processo Xorg/Xwayland
if [ -z "$DISPLAY_NUM" ]; then
    DISPLAY_NUM=$(ps aux | grep -E '[Xx]org|[Xx]wayland' | grep -oP ':\d+' | head -1)
fi

# Ainda sem display: usa :0 como padrão
DISPLAY_NUM="${DISPLAY_NUM:-:0}"

# Encontra XAUTHORITY do usuário logado na sessão gráfica
XAUTH_FILE=""
for f in /run/user/*/gdm/Xauthority /run/user/*/.mutter-Xwaylandauth.* /tmp/.X*-lock /home/*/.Xauthority /root/.Xauthority; do
    [ -r "$f" ] && XAUTH_FILE="$f" && break
done

# Tenta com -auth auto (deixa x11vnc achar sozinho)
export DISPLAY="$DISPLAY_NUM"
if [ -n "$XAUTH_FILE" ]; then
    nohup x11vnc -display "$DISPLAY_NUM" -auth "$XAUTH_FILE" -forever -shared -nopw -bg -rfbport 5900 -noipv6 >/tmp/x11vnc.log 2>&1 &
else
    nohup x11vnc -display "$DISPLAY_NUM" -auth auto -forever -shared -nopw -bg -rfbport 5900 -noipv6 >/tmp/x11vnc.log 2>&1 &
fi

echo "x11vnc iniciado no display $DISPLAY_NUM"
"""
                stdin, stdout, stderr = ssh.exec_command(vnc_cmd, timeout=20)
                out = stdout.read().decode('utf-8', errors='ignore').strip()
                err = stderr.read().decode('utf-8', errors='ignore').strip()
                logger.info(f"x11vnc stdout: {out}")
                if err:
                    logger.warning(f"x11vnc stderr: {err}")

            # Aguarda até 5s pela porta 5900 abrir
            for _ in range(10):
                time.sleep(0.5)
                if _is_port_open(ip, 5900, timeout=1.0):
                    logger.info(f"x11vnc ativo em {ip}:5900.")
                    vnc_ready = True
                    break

            if not vnc_ready:
                # Tenta ler o log remoto para diagnóstico
                try:
                    with ssh_connect(ip, username, password, logger) as ssh2:
                        _, log_out, _ = ssh2.exec_command("cat /tmp/x11vnc.log 2>/dev/null | tail -20", timeout=5)
                        log_content = log_out.read().decode('utf-8', errors='ignore').strip()
                        if log_content:
                            logger.error(f"Log x11vnc em {ip}:\n{log_content}")
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Erro SSH ao iniciar VNC em {ip}: {e}")
            return {"success": False, "message": f"Falha SSH: {str(e)}"}

    if vnc_ready:
        ws_port = start_websockify_proxy(ip, 5900, 6080)
        if ws_port:
            return {
                "success": True,
                "message": "Servidor VNC e websockify prontos.",
                "ws_port": ws_port,
                "target_ip": ip
            }
        return {"success": False, "message": "VNC ativo mas falha ao iniciar websockify."}

    return {
        "success": False,
        "message": (
            f"Não foi possível iniciar o x11vnc em {ip}. "
            "Possíveis causas: nenhuma sessão gráfica ativa, display bloqueado, "
            "ou x11vnc sem permissão para o display. "
            "Verifique /tmp/x11vnc.log na máquina remota."
        )
    }


def close_vnc_session(sid: str):
    """Fecha a conexão de socket TCP VNC associada ao ID da sessão WebSocket."""
    with _VNC_LOCK:
        sess = _VNC_SESSIONS.pop(sid, None)
        if sess:
            sess['active'] = False
            tcp_sock = sess.get('tcp_socket')
            if tcp_sock:
                try:
                    tcp_sock.close()
                except Exception:
                    pass

def connect_vnc_proxy(sid: str, target_ip: str, target_port: int, socketio_app) -> bool:
    """
    Conecta um socket TCP puro à máquina remota (target_ip:target_port)
    e inicia uma thread que lê pacotes RFB e os emite via SocketIO ('vnc_output').
    """
    close_vnc_session(sid)

    try:
        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.settimeout(10.0)
        tcp_sock.connect((target_ip, target_port))
        tcp_sock.settimeout(None)

        with _VNC_LOCK:
            _VNC_SESSIONS[sid] = {
                'tcp_socket': tcp_sock,
                'active': True,
                'target': f"{target_ip}:{target_port}"
            }

        def read_vnc_stream(sid_target, sock):
            while True:
                with _VNC_LOCK:
                    sess = _VNC_SESSIONS.get(sid_target)
                    if not sess or not sess.get('active'):
                        break
                try:
                    data = sock.recv(8192)
                    if not data:
                        break
                    socketio_app.emit('vnc_output', data, room=sid_target)
                except Exception:
                    break

            socketio_app.emit('vnc_disconnected', {"status": "disconnected"}, room=sid_target)
            close_vnc_session(sid_target)

        socketio_app.start_background_task(read_vnc_stream, sid_target=sid, sock=tcp_sock)
        return True

    except Exception as e:
        logger.error(f"Erro na ponte TCP VNC para {target_ip}:{target_port} - {e}")
        close_vnc_session(sid)
        return False

def send_vnc_input(sid: str, data: bytes):
    """Envia pacotes binários do cliente noVNC para o socket TCP do servidor VNC."""
    with _VNC_LOCK:
        sess = _VNC_SESSIONS.get(sid)
        if sess and sess.get('active'):
            tcp_sock = sess.get('tcp_socket')
            if tcp_sock:
                try:
                    tcp_sock.sendall(data)
                except Exception as e:
                    logger.debug(f"Erro ao enviar dados VNC TCP: {e}")