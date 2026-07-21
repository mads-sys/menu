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



def ensure_remote_vnc_server(ip: str, username: str, password: str, logger: logging.Logger, target_display: str = None) -> Dict[str, Any]:
    """
    Garante que um servidor VNC (x11vnc) esteja em execução na máquina remota.
    Detecta automaticamente o display X11 ativo e o XAUTHORITY correto.
    Se target_display não for fornecido e a máquina for multiseat, retorna a lista de displays.
    """
    try:
        with ssh_connect(ip, username, password, logger) as ssh:
            # 1. Obter a lista de displays ativos de forma precisa (evita falsos positivos como horário 15:05)
            detect_cmd = r"""
            DISPLAYS=$(ps aux | grep -E '[Xx]org|[Xx]wayland|/usr/lib/Xorg|/usr/bin/X' | grep -v grep | awk '{for(i=1;i<=NF;i++) if($i ~ /^:[0-9]+$/) print $i}' | sort -u | tr '\n' ' ')
            echo "DISPLAYS=$DISPLAYS"
            """
            stdin, stdout, stderr = ssh.exec_command(detect_cmd, timeout=10)
            out = stdout.read().decode('utf-8', errors='ignore').strip()
            
            displays = []
            for line in out.split('\n'):
                if line.startswith('DISPLAYS='):
                    disp_str = line.split('=', 1)[1].strip()
                    displays = [d for d in disp_str.split(' ') if d.startswith(':')]
            
            if not displays:
                # Fallback, tenta `:0` se não achar nada
                displays = [":0"]
            
            logger.info(f"Displays detectados em {ip}: {displays}")
            
            # Se target_display for None, verificamos se tem múltiplos
            if target_display is None:
                if len(displays) > 1:
                    # Retorna a lista para o front-end perguntar ao usuário
                    return {
                        "success": True,
                        "multiseat": True,
                        "displays": [{"display": d, "label": f"Assento {d}"} for d in displays]
                    }
                else:
                    target_display = displays[0]
            elif target_display not in displays:
                # O usuário pediu um display que não está ativo, mas tentamos mesmo assim
                pass

            # A partir daqui temos o target_display garantido (ex: ":0", ":1")
            try:
                disp_num_str = target_display.replace(':', '')
                disp_num = int(disp_num_str)
            except ValueError:
                disp_num = 0
                target_display = ":0"
            
            rfbport = 5900 + disp_num
            ws_port = 6080 + disp_num

            vnc_ready = False
            if _is_port_open(ip, rfbport, timeout=1.5):
                logger.info(f"Porta VNC {rfbport} (Display {target_display}) já está aberta em {ip}.")
                vnc_ready = True
            else:
                logger.info(f"Porta VNC {rfbport} fechada em {ip}. Iniciando x11vnc via SSH...")
                
                # Instala x11vnc se necessário com timeout para evitar travar a thread
                install_cmd = f"which x11vnc >/dev/null 2>&1 || timeout 45 bash -c \"echo '{password}' | sudo -S apt-get update >/dev/null 2>&1; echo '{password}' | sudo -S apt-get install -y x11vnc >/dev/null 2>&1\""
                stdin, stdout, stderr = ssh.exec_command(install_cmd, timeout=10)
                # Não usamos recv_exit_status() travado. Lemos com timeout.
                try:
                    stdout.channel.settimeout(50.0)
                    stdout.read()
                except Exception:
                    pass

                # Inicia x11vnc no target_display
                log_file = f"/tmp/vnc_{username}_{rfbport}.log"
                vnc_cmd = f"""
                export DISPLAY="{target_display}"
                pkill -f "x11vnc.*-rfbport {rfbport}" 2>/dev/null || true
                rm -f {log_file}
                echo "INICIANDO SCRIPT VNC PARA {target_display}" > {log_file}

                # Tenta achar XAUTHORITY
                XAUTH_FILE=""
                for f in /run/user/*/gdm/Xauthority /run/user/*/.mutter-Xwaylandauth.* /tmp/.X{disp_num}-lock /home/*/.Xauthority /root/.Xauthority; do
                    if [ -r "$f" ]; then
                        XAUTH_FILE="$f"
                        break
                    fi
                done

                echo "XAUTH_FILE_DETECTED=$XAUTH_FILE" >> {log_file}

                if [ -n "$XAUTH_FILE" ]; then
                    nohup x11vnc -display "{target_display}" -auth "$XAUTH_FILE" -forever -shared -nopw -bg -rfbport {rfbport} -noipv6 >> {log_file} 2>&1 </dev/null &
                else
                    nohup x11vnc -display "{target_display}" -auth auto -forever -shared -nopw -bg -rfbport {rfbport} -noipv6 >> {log_file} 2>&1 </dev/null &
                fi
                sleep 1
                """
                stdin, stdout, stderr = ssh.exec_command(vnc_cmd, timeout=20)
                
                # Aguarda até 5s pela porta abrir
                for _ in range(10):
                    time.sleep(0.5)
                    if _is_port_open(ip, rfbport, timeout=1.0):
                        logger.info(f"x11vnc ativo em {ip}:{rfbport}.")
                        vnc_ready = True
                        break

                if not vnc_ready:
                    # Log remoto
                    log_content = "[Nenhum log de stdout encontrado]"
                    try:
                        _, log_out, log_err = ssh.exec_command(f"cat {log_file}", timeout=10)
                        
                        out_str = log_out.read().decode('utf-8', errors='ignore').strip()
                        err_str = log_err.read().decode('utf-8', errors='ignore').strip()
                        
                        if out_str:
                            log_content = out_str
                        if err_str:
                            log_content += f"\n[ERRO CAT]: {err_str}"
                            
                        # Verifica se x11vnc está instalado
                        _, w_out, _ = ssh.exec_command("which x11vnc", timeout=5)
                        w_res = w_out.read().decode('utf-8', errors='ignore').strip()
                        if not w_res:
                            log_content += "\n[ERRO FATAL] x11vnc NÃO está instalado nesta máquina e o apt-get falhou!"
                            
                    except Exception as ex:
                        log_content = f"Erro ao ler log remotamente: {str(ex)}"
                        logger.error(log_content)
                    
                    if log_content:
                        logger.error(f"Log x11vnc em {ip} (Display {target_display}):\n{log_content}")

                    return {
                        "success": False,
                        "message": (
                            f"Falha ao iniciar display {target_display} em {ip}. Detalhes:\n{log_content[-500:]}"
                        )
                    }

    except Exception as e:
        logger.error(f"Erro SSH ao iniciar VNC em {ip}: {e}")
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
        return {"success": False, "message": "VNC ativo mas falha ao iniciar websockify."}

    return {"success": False, "message": f"Falha desconhecida no VNC em {ip}."}



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