# services/ssh_service.py

import posixpath
import platform
import subprocess
import stat

# --- Suprime janelas de console piscando no Windows para subprocessos ---
if platform.system() == "Windows":
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
import socket
import re
import shlex
import base64
import binascii
import logging
import paramiko
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, ExitStack
import time
from typing import List, Dict, Tuple, Optional, Any, Generator

from command_builder import CommandExecutionError

logger = logging.getLogger(__name__)

class SSHConnectionManager:
    """
    Gerenciador thread-safe de pool de conexões SSH de alta performance com:
    - Mutex por host para evitar handshakes duplicados simultâneos
    - Validação ativa de saúde de socket/keep-alive com TCP_NODELAY
    - Heartbeat worker em background para manter conexões quentes e ativas durante a aula
    - TTL de inatividade estendido (600s / 10 min)
    - Reabertura transparente em caso de desconexão
    """
    def __init__(self, max_idle_seconds: int = 600):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._host_locks: Dict[str, threading.Lock] = {}
        self._in_use: Dict[str, int] = {}
        self.max_idle_seconds = max_idle_seconds
        self._start_heartbeat_worker()

    def _start_heartbeat_worker(self):
        """Inicia thread em segundo plano para manter conexões do pool ativas via keep-alive contínuo."""
        def _heartbeat_loop():
            while True:
                time.sleep(15)
                now = time.time()
                to_prune = []
                with self._lock:
                    for key, entry in list(self._cache.items()):
                        client = entry.get('client')
                        last_used = entry.get('last_used', 0)
                        is_active = self._in_use.get(key, 0) > 0
                        
                        # Expira se passar do tempo limite sem uso
                        if not is_active and (now - last_used > self.max_idle_seconds):
                            to_prune.append(key)
                            continue
                            
                        # Keep-alive ativo no transport
                        if client:
                            try:
                                transport = client.get_transport()
                                if transport and transport.is_active():
                                    transport.send_ignore()
                                else:
                                    to_prune.append(key)
                            except Exception:
                                to_prune.append(key)
                                
                    for key in to_prune:
                        self._evict_nolock(key)

        t = threading.Thread(target=_heartbeat_loop, name="SSH-Pool-Heartbeat", daemon=True)
        t.start()

    def _get_host_lock(self, cache_key: str) -> threading.Lock:
        with self._lock:
            if cache_key not in self._host_locks:
                self._host_locks[cache_key] = threading.Lock()
            return self._host_locks[cache_key]

    def acquire(self, cache_key: str):
        """Registra que uma operação está ativamente usando esta conexão SSH."""
        with self._lock:
            self._in_use[cache_key] = self._in_use.get(cache_key, 0) + 1
            if cache_key in self._cache:
                self._cache[cache_key]['last_used'] = time.time()

    def release(self, cache_key: str):
        """Libera o registro de uso ativo da conexão SSH."""
        with self._lock:
            if cache_key in self._in_use:
                self._in_use[cache_key] -= 1
                if self._in_use[cache_key] <= 0:
                    del self._in_use[cache_key]
            if cache_key in self._cache:
                self._cache[cache_key]['last_used'] = time.time()

    def touch(self, cache_key: str):
        """Renova o timestamp de atividade da conexão para evitar expiração."""
        with self._lock:
            if cache_key in self._cache:
                self._cache[cache_key]['last_used'] = time.time()

    def is_alive(self, client: Optional[paramiko.SSHClient]) -> bool:
        """Verifica se a conexão SSH e seu transport continuam ativos e responsivos."""
        if not client:
            return False
        try:
            transport = client.get_transport()
            if not transport or not transport.is_active():
                return False
            # Envia pacote leve para checar conectividade real do socket
            transport.send_ignore()
            return True
        except Exception:
            return False

    def get_connection(self, cache_key: str) -> Optional[paramiko.SSHClient]:
        """Obtém uma conexão válida do pool se existente e funcional."""
        with self._lock:
            entry = self._cache.get(cache_key)
            if not entry:
                return None
            
            client = entry['client']
            last_used = entry['last_used']

            # Se a conexão está ativa em uma sessão/stream, nunca expira por idle
            is_active = self._in_use.get(cache_key, 0) > 0

            if not is_active and (time.time() - last_used > self.max_idle_seconds):
                self._evict_nolock(cache_key)
                return None

        if self.is_alive(client):
            with self._lock:
                if cache_key in self._cache:
                    self._cache[cache_key]['last_used'] = time.time()
            return client
        else:
            self.evict(cache_key)
            return None

    def store_connection(self, cache_key: str, client: paramiko.SSHClient):
        """Armazena ou atualiza uma conexão SSH no pool com keep-alive habilitado."""
        try:
            transport = client.get_transport()
            if transport and transport.is_active():
                transport.set_keepalive(10)  # Pacote keep-alive a cada 10s
        except Exception:
            pass

        with self._lock:
            self._cache[cache_key] = {
                'client': client,
                'last_used': time.time()
            }

    def evict(self, cache_key: str):
        """Remove e fecha a conexão com segurança."""
        with self._lock:
            self._evict_nolock(cache_key)

    def _evict_nolock(self, cache_key: str):
        entry = self._cache.pop(cache_key, None)
        self._in_use.pop(cache_key, None)
        if entry:
            client = entry.get('client')
            if client:
                try:
                    client.close()
                except Exception:
                    pass

    def prune(self, logger=None):
        """Limpador de conexões mortas ou inativas por tempo excessivo (TTL)."""
        now = time.time()
        to_remove = []
        with self._lock:
            for key, entry in list(self._cache.items()):
                # NUNCA expurga conexões que estão atualmente em uso
                if self._in_use.get(key, 0) > 0:
                    continue
                if now - entry['last_used'] > self.max_idle_seconds:
                    to_remove.append(key)
            for key in to_remove:
                self._evict_nolock(key)

# Instância global do pool de conexões
_ssh_pool = SSHConnectionManager(max_idle_seconds=600)
_SSH_CACHE = _ssh_pool._cache
_CACHE_LOCK = _ssh_pool._lock

def prune_ssh_cache(logger):
    """Fecha e remove conexões SSH inativas do cache global para liberar recursos."""
    _ssh_pool.prune(logger)

def _fix_host_key(ip: str, logger) -> bool:
    """Executa 'ssh-keygen -R <ip>' para remover uma chave de host antiga."""
    try:
        command = ["ssh-keygen", "-R", ip]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        if result.returncode == 0:
            logger.info(f"Chave SSH para {ip} removida automaticamente com sucesso.")
            return True
        else:
            logger.error(f"Falha ao remover automaticamente a chave SSH para {ip}: {result.stderr.strip()}")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.error(f"Exceção ao tentar remover a chave SSH para {ip}: {e}")
        return False

def _is_port_open(ip: str, port: int = 22, timeout: float = 1.2) -> bool:
    """Verifica rapidamente se a porta SSH está acessível via socket nativo sem handshake pesado."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.close()
        return True
    except (socket.timeout, socket.error):
        return False

@contextmanager
def ssh_connect(ip: str, username: str, password: str, logger, auto_fix_key: bool = True) -> Generator[paramiko.SSHClient, None, None]:
    """
    Gerencia uma conexão SSH com pooling de alto desempenho, keep-alive ativo e mutex por host.
    """
    cache_key = f"{username}@{ip}"
    host_lock = _ssh_pool._get_host_lock(cache_key)

    with host_lock:
        cached_client = _ssh_pool.get_connection(cache_key)
        if cached_client:
            logger.debug(f"Reutilizando conexão SSH do pool para {cache_key}")
            _ssh_pool.acquire(cache_key)
            try:
                yield cached_client
            finally:
                _ssh_pool.release(cache_key)
            return

        if not _is_port_open(ip, 22, timeout=0.15):
            logger.debug(f"Tentativa de conexão ignorada (Porta 22 fechada em {ip})")
            raise socket.error(f"Porta 22 inacessível (Host offline ou firewall ativo).")

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            logger.info(f"Estabelecendo nova conexão SSH via Pool: {username}@{ip}")
            # Cria socket nativo otimizado com TCP_NODELAY para latência mínima em LAN
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(3.5)
            sock.connect((ip, 22))

            if password:
                ssh.connect(ip, username=username, password=password, timeout=3.5, banner_timeout=10, sock=sock, look_for_keys=False, allow_agent=False)
            else:
                ssh.connect(ip, username=username, timeout=3.5, banner_timeout=10, sock=sock, look_for_keys=True, allow_agent=True)

            logger.debug(f"Conexão SSH estabelecida e salva no pool para {ip}")
            _ssh_pool.store_connection(cache_key, ssh)
            _ssh_pool.acquire(cache_key)
            try:
                yield ssh
            finally:
                _ssh_pool.release(cache_key)
        except paramiko.SSHException as e:
            error_str = str(e).lower()
            is_key_error = "host key for server" in error_str and "does not match" in error_str

            if is_key_error and auto_fix_key:
                logger.warning(f"Chave de host para {ip} inválida. Tentando corrigir automaticamente...")
                if _fix_host_key(ip, logger):
                    logger.info(f"Tentando reconectar a {ip} após a correção da chave...")
                    ssh.connect(ip, username=username, password=password, timeout=3.5, banner_timeout=10, look_for_keys=False)
                    _ssh_pool.store_connection(cache_key, ssh)
                    _ssh_pool.acquire(cache_key)
                    try:
                        yield ssh
                    finally:
                        _ssh_pool.release(cache_key)
                else:
                    _ssh_pool.evict(cache_key)
                    raise e
            else:
                _ssh_pool.evict(cache_key)
                raise e
        except Exception:
            _ssh_pool.evict(cache_key)
            raise

def warm_up_ssh_pool(ips: List[str], username: str, password: str, logger):
    """
    Pré-aquece conexões SSH em paralelo para uma lista de IPs.
    Garante que quando o professor executar ações em lote, as conexões já estejam ativas no pool.
    """
    if not ips:
        return

    def _warmup_single(ip):
        try:
            with ssh_connect(ip, username, password, logger):
                pass
        except Exception:
            pass

    max_workers = min(35, max(1, len(ips)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_warmup_single, ip) for ip in ips]
        for f in as_completed(futures):
            try: f.result()
            except Exception: pass

def _handle_ssh_exception(e: Exception, ip: str, action: str, logger) -> Tuple[Dict[str, Any], int]:
    """Analisa exceções de SSH e retorna uma resposta JSON padronizada."""
    error_str = str(e).lower()
    logger.error(f"Erro de SSH na ação '{action}' em {ip}: {error_str}")

    if isinstance(e, paramiko.AuthenticationException) or "authentication failed" in error_str:
        return {"success": False, "message": "Falha na autenticação. Verifique a senha."}, 401

    if "inacessível" in error_str:
        message = "Porta SSH (22) inacessível."
        details = "A máquina responde ao Ping, mas a porta 22 está fechada ou o firewall bloqueou a conexão."
        return {"success": False, "message": message, "details": details}, 503

    if "timed out" in error_str or "timeout" in error_str or "connection timed out" in error_str:
        message = "A conexão SSH expirou (timeout)."
        details = "O dispositivo demorou demais para responder. Isso geralmente ocorre em redes Wi-Fi congestionadas ou com sinal muito baixo."
        return {"success": False, "message": message, "details": details}, 504

    # Adicionado para tratar erros de conexão mais específicos
    if "unable to connect" in error_str or "connection refused" in error_str:
        message = "Host offline ou serviço SSH inativo."
        details = f"Não foi possível estabelecer uma conexão SSH com {ip}. O dispositivo pode estar desligado ou o serviço SSH (sshd) não está em execução."
        return {"success": False, "message": message, "details": details}, 503

    if "host key for server" in error_str and "does not match" in error_str:
        message = "Alerta de segurança: A chave do host mudou."
        details = (f"A chave do host para {ip} é diferente da que está salva em 'known_hosts'. "
                   "A correção automática falhou. Isso pode significar que o sistema operacional foi reinstalado ou, em casos raros, que há um ataque 'man-in-the-middle'.\n\n"
                   f"Para resolver manualmente, execute no terminal do servidor: ssh-keygen -R {ip}")
        return {"success": False, "message": message, "details": details}, 409

    if "error reading ssh protocol banner" in error_str:
        message = "Erro no protocolo SSH."
        details = (f"O servidor SSH em {ip} não respondeu com o banner de protocolo esperado. "
                   "Isso pode indicar que o serviço SSH não está rodando corretamente, "
                   "que há um serviço diferente na porta 22, ou um problema de rede/firewall mais profundo.")
        return {"success": False, "message": message, "details": details}, 502

    if "server not found in known_hosts" in error_str:
        message = "Host desconhecido. A chave do servidor não foi encontrada."
        details = f"Por segurança, a conexão foi rejeitada. Para confiar neste host, execute o seguinte comando no terminal onde o backend está rodando e tente novamente:\nssh-keyscan -H {ip} >> ~/.ssh/known_hosts"
        return {"success": False, "message": message, "details": details}, 409

    # Para outros erros de SSH ou exceções genéricas
    logger.error(f"Erro inesperado na ação '{action}' em {ip}: {e}")
    return {"success": False, "message": f"Erro de comunicação/execução SSH em {ip}.", "details": str(e)}, 502

def _execute_shell_command(ssh: paramiko.SSHClient, command: str, password: str, timeout: int = 20, username: Optional[str] = None, use_sudo: bool = True) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Executa um comando shell via SSH, tratando sudo e separando warnings de erros.
    """
    ssh_transport_user = None
    try:
        if ssh.get_transport():
            ssh_transport_user = ssh.get_transport().get_username()
    except Exception:
        pass

    # Para scripts multi-linha ou com caracteres especiais, codifica em Base64 para garantir execução 100% limpa no bash
    if '\n' in command:
        import base64
        b64_str = base64.b64encode(command.encode('utf-8')).decode('utf-8')
        target_cmd = f"echo {b64_str} | base64 -d | bash"
    else:
        target_cmd = command

    if not use_sudo or (username and ssh_transport_user and username.strip() == ssh_transport_user.strip()):
        final_command = target_cmd
    else:
        if username:
            final_command = f"sudo -S -H -u {username} bash -c {shlex.quote(target_cmd)}"
        else:
            final_command = f"sudo -S -H -p '' bash -c {shlex.quote(target_cmd)}"

    start_time = time.time()
    logger.debug(f"Executando comando remoto em {ssh.get_transport().getpeername()[0]}: {final_command[:100]}...")

    try:
        stdin, stdout, stderr = ssh.exec_command(final_command, timeout=timeout)

        if "sudo -S" in final_command:
            stdin.write(password + '\n')
            stdin.flush()

        output = stdout.read().decode('utf-8', errors='ignore').strip()
        error_output = stderr.read().decode('utf-8', errors='ignore').strip()
        exit_status = stdout.channel.recv_exit_status()
    except (socket.timeout, TimeoutError, Exception) as err:
        if "Timeout" in type(err).__name__ or "timeout" in str(err).lower():
            logger.warning(f"Timeout tratado ao ler resposta remota em {ssh.get_transport().getpeername()[0]}: {err}")
            return "Comando executado em segundo plano.", "", ""
        raise err

    duration = time.time() - start_time
    logger.debug(f"Comando finalizado em {duration:.2f}s com status {exit_status}")

    sudo_prompt_regex = r'\[sudo\] (senha|password) para .*:'
    cleaned_error_output = re.sub(sudo_prompt_regex, '', error_output).strip()

    all_error_lines = cleaned_error_output.splitlines()
    warnings = [line for line in all_error_lines if line.strip().startswith('W:')]
    errors = [line for line in all_error_lines if not line.strip().startswith('W:') and line.strip()]

    if exit_status != 0:
        error_details = "\n".join(errors) if errors else cleaned_error_output
        raise CommandExecutionError(
            message=f"O comando falhou com o código de saída {exit_status}.",
            details=error_details,
            warnings="\n".join(warnings) if warnings else None
        )

    return output, "\n".join(warnings) if warnings else None, "\n".join(errors) if errors else None

def _stream_shell_command(ssh: paramiko.SSHClient, command: str, password: str, timeout: int = 1800, use_sudo: bool = True) -> Generator[str, None, int]:
    """
    Executa um comando shell via SSH e transmite a saída (stdout e stderr) em tempo real.
    Retorna o código de saída do comando.
    """
    # Se o comando for um script multi-linha (como o de atualização), ele já será
    # complexo. Se for um comando simples, garantimos que 'sudo -S' seja adicionado.
    if not use_sudo:
        final_command = command
    elif '\n' in command or "sudo -S" in command:
        # Para scripts multi-linha ou que já contêm sudo, o sudo deve envolver o bash.
        # A flag -H é importante para definir a variável de ambiente HOME para o usuário root.
        # Usamos 'bash -c' para executar o script, e o sudo eleva o bash.
        final_command = f"sudo -S -H -p '' bash -c {shlex.quote(command)}" 
    else:
        # Para comandos simples que não precisam de um shell complexo.
        final_command = f"sudo -S -p '' {command}" 

    channel = ssh.get_transport().open_session()
    channel.set_combine_stderr(True)  # Combina stdout e stderr em um único fluxo.
    channel.get_pty() # Solicita um pseudo-terminal, necessário para algumas interações.
    
    try:
        channel.exec_command(final_command)

        # Envia a senha para o prompt do sudo.
        if use_sudo and "sudo -S" in final_command:
            channel.sendall(password + '\n')

        # Lê a saída linha por linha enquanto o comando estiver em execução.
        start_time = time.time()
        while not channel.exit_status_ready():
            # Checagem de segurança contra estouro de tempo estipulado
            if time.time() - start_time > timeout:
                yield f"\n⚠️ Tempo limite de execução ({timeout}s / {int(timeout/60)}min) atingido para esta operação.\n"
                channel.close()
                return -1

            # Verifica se há dados para ler para evitar bloqueio.
            if channel.recv_ready():
                line = channel.recv(1024).decode('utf-8', errors='ignore')
                # Remove o prompt de senha da saída para não exibi-lo no frontend.
                cleaned_line = re.sub(r'\[sudo\].*?password for.*?:', '', line, flags=re.IGNORECASE)
                # Remove o eco da própria senha se o terminal PTY a refletir
                if password and password.strip():
                    cleaned_line = cleaned_line.replace(password.strip(), '')
                cleaned_line = cleaned_line.strip()
                if cleaned_line:
                    yield cleaned_line + '\n' # Adiciona nova linha para o streaming
            else:
                # Pequena pausa para evitar uso excessivo de CPU em loop busy-wait
                time.sleep(0.05)
        
        # Retorna o código de saída final.
        return channel.recv_exit_status()
    finally:
        channel.close()

def _get_remote_desktop_path(ssh: paramiko.SSHClient, sftp: paramiko.SFTPClient, username: str) -> Optional[str]:
    """Descobre o caminho da Área de Trabalho na máquina remota."""
    _, stdout, _ = ssh.exec_command(f"sudo -u {username} xdg-user-dir DESKTOP")
    desktop_path = stdout.read().decode(errors='ignore').strip()
    
    # Obtém o diretório home correto do usuário alvo para evitar erros de caminho (ex: /home/aluno vs /home/aluno1)
    _, stdout_home, _ = ssh.exec_command(f"getent passwd {username} | cut -d: -f6")
    target_home = stdout_home.read().decode().strip()
    base_dir = target_home if target_home else sftp.normalize('.')

    if desktop_path and not desktop_path.startswith('/'):
        desktop_path = posixpath.join(base_dir, desktop_path)

    if not desktop_path:
        possible_dirs = ["Área de Trabalho", "Desktop", "Área de trabalho", "Escritorio"]
        for p_dir in possible_dirs:
            full_path = posixpath.join(base_dir, p_dir)
            try:
                sftp.stat(full_path)
                desktop_path = full_path
                break
            except FileNotFoundError:
                continue
    return desktop_path

def _normalize_shortcut_name(filename: str) -> str:
    """Normaliza o nome de um atalho removendo dígitos para permitir correspondência flexível."""
    if not filename.endswith('.desktop'):
        return filename
    name_part = filename[:-len('.desktop')]
    normalized_name_part = re.sub(r'[-_]?\d+$', '', name_part)
    if not normalized_name_part.strip(' -_'):
        return filename
    return normalized_name_part + ".desktop"

def shell_disable_shortcuts(ssh: paramiko.SSHClient, username: str, password: str, backup_root_dir: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Desativa atalhos usando comandos Shell (sudo) para evitar erros de permissão."""
    script = f"""
        # Define diretórios
        DESKTOP_DIR=$(xdg-user-dir DESKTOP)
        if [ -z "$DESKTOP_DIR" ] || [ ! -d "$DESKTOP_DIR" ]; then DESKTOP_DIR="$HOME/Área de Trabalho"; fi
        if [ ! -d "$DESKTOP_DIR" ]; then DESKTOP_DIR="$HOME/Desktop"; fi
        
        if [ ! -d "$DESKTOP_DIR" ]; then
            echo "ERRO: Diretório da Área de Trabalho não encontrado."
            exit 1
        fi

        BACKUP_ROOT="$HOME/{backup_root_dir}"
        # Cria subpasta com o mesmo nome da pasta desktop (ex: Área de Trabalho)
        TARGET_DIR="$BACKUP_ROOT/$(basename "$DESKTOP_DIR")"
        mkdir -p "$TARGET_DIR"

        count=0
        # Habilita nullglob para o loop não rodar se não houver arquivos
        shopt -s nullglob
        for file in "$DESKTOP_DIR"/*.desktop; do
            mv "$file" "$TARGET_DIR/"
            ((count++))
        done
        echo "Operação de desativação concluída. $count atalhos movidos para backup."
    """
    output, warnings, errors = _execute_shell_command(ssh, script, password, username=username)
    return output, warnings, errors

def shell_restore_shortcuts(ssh: paramiko.SSHClient, username: str, password: str, backup_files: Optional[List[str]] = None, backup_root_dir: str = "backup_shortcuts") -> Tuple[str, Optional[str], Optional[str]]:
    """Restaura atalhos da pasta de backup para a Área de Trabalho (suporta restauração total e seletiva em múltiplas pastas de backup)."""
    backup_files = backup_files or []
    payload_json = json.dumps({
        "backup_files": backup_files,
        "backup_root_dir": backup_root_dir
    })
    
    python_script = f"""import os, sys, glob, shutil, subprocess, json

payload = json.loads({repr(payload_json)})
req_files = payload.get('backup_files', [])
custom_root = payload.get('backup_root_dir', 'backup_shortcuts')

home = os.path.expanduser('~')

# 1. Descobre a Área de Trabalho de destino
desk_dirs = []
try:
    p = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, timeout=2)
    out = p.stdout.strip()
    if out and os.path.isdir(out):
        desk_dirs.append(out)
except Exception:
    pass

for cand in [
    os.path.join(home, 'Área de Trabalho'),
    os.path.join(home, 'Desktop'),
    os.path.join(home, 'area de trabalho'),
    os.path.join(home, 'desktop')
]:
    if os.path.isdir(cand) and cand not in desk_dirs:
        desk_dirs.append(cand)

if not desk_dirs:
    target_desk = os.path.join(home, 'Área de Trabalho')
    try:
        os.makedirs(target_desk, exist_ok=True)
    except Exception:
        pass
else:
    target_desk = desk_dirs[0]

# 2. Descobre todas as pastas candidatas de backup
candidate_roots = [
    os.path.join(home, custom_root),
    os.path.join(home, 'backup_shortcuts'),
    os.path.join(home, 'atalhos_desativados'),
    os.path.join(home, 'Desktop_Backup'),
    os.path.join(home, 'Área de Trabalho_Backup'),
    os.path.join(home, '.backup_shortcuts')
]

seen_roots = []
for r in candidate_roots:
    if os.path.isdir(r) and r not in seen_roots:
        seen_roots.append(r)

restored_count = 0
restored_names = []

if not req_files:
    # Restauração TOTAL: encontra todos os arquivos em todas as pastas de backup
    for b_root in seen_roots:
        for root, dirs, files in os.walk(b_root):
            for f in files:
                src = os.path.join(root, f)
                dst = os.path.join(target_desk, f)
                try:
                    shutil.move(src, dst)
                    restored_count += 1
                    restored_names.append(f)
                except Exception:
                    try:
                        shutil.copy2(src, dst)
                        os.remove(src)
                        restored_count += 1
                        restored_names.append(f)
                    except Exception:
                        pass
else:
    # Restauração SELETIVA: restaura apenas os arquivos requisitados
    for req in req_files:
        fname = os.path.basename(req)
        found = False
        for b_root in seen_roots:
            # 1. Tenta caminho relativo exato
            exact_cand = os.path.join(b_root, req)
            if os.path.isfile(exact_cand):
                try:
                    shutil.move(exact_cand, os.path.join(target_desk, fname))
                    restored_count += 1
                    restored_names.append(fname)
                    found = True
                    break
                except Exception:
                    pass
            # 2. Tenta na raiz do backup
            root_cand = os.path.join(b_root, fname)
            if os.path.isfile(root_cand):
                try:
                    shutil.move(root_cand, os.path.join(target_desk, fname))
                    restored_count += 1
                    restored_names.append(fname)
                    found = True
                    break
                except Exception:
                    pass
            # 3. Busca recursivamente pelo nome do arquivo
            for root, dirs, files in os.walk(b_root):
                if fname in files:
                    src = os.path.join(root, fname)
                    try:
                        shutil.move(src, os.path.join(target_desk, fname))
                        restored_count += 1
                        restored_names.append(fname)
                        found = True
                        break
                    except Exception:
                        pass
            if found:
                break

# 3. Aplica permissões de execução e marcação confiável (gio/chmod)
if os.path.isdir(target_desk):
    for f in os.listdir(target_desk):
        if f.endswith('.desktop'):
            fpath = os.path.join(target_desk, f)
            try:
                os.chmod(fpath, 0o755)
            except Exception:
                pass
            try:
                subprocess.run(['gio', 'set', fpath, 'metadata::trusted', 'true'], timeout=1, capture_output=True)
                subprocess.run(['gio', 'set', fpath, 'metadata::trusted', 'yes'], timeout=1, capture_output=True)
            except Exception:
                pass

# 4. Limpa pastas de backup vazias
for b_root in seen_roots:
    for root, dirs, files in os.walk(b_root, topdown=False):
        for d in dirs:
            d_full = os.path.join(root, d)
            try:
                if not os.listdir(d_full):
                    os.rmdir(d_full)
            except Exception:
                pass
    try:
        if not os.listdir(b_root):
            os.rmdir(b_root)
    except Exception:
        pass

# 5. Força refresh visual em tempo real no Cinnamon/Nemo
try:
    subprocess.run(['touch', target_desk], timeout=1, capture_output=True)
    subprocess.run(['killall', '-HUP', 'nemo-desktop'], timeout=1, capture_output=True)
except Exception:
    pass

if restored_count > 0:
    nomes_str = ', '.join(restored_names[:5]) + ('...' if len(restored_names) > 5 else '')
    print(f"Restauração concluída. {{restored_count}} atalho(s) restaurado(s) com sucesso ({{nomes_str}}).")
else:
    print("Restauração concluída. 0 atalhos encontrados nas pastas de backup.")
"""
    script = f"python3 -c {shlex.quote(python_script)}"
    output, warnings, errors = _execute_shell_command(ssh, script, password, username=username)
    return output, warnings, errors

def shell_list_desktop_shortcuts(ssh: paramiko.SSHClient, username: str, password: str) -> List[Dict[str, Any]]:
    """Lista todos os atalhos (.desktop e executáveis) presentes na Área de Trabalho do usuário remoto."""
    script = """
python3 -c "
import os, glob, json, subprocess

desktop_dirs = []
try:
    p = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, timeout=2)
    out = p.stdout.strip()
    if out and os.path.isdir(out):
        desktop_dirs.append(out)
except Exception:
    pass

home = os.path.expanduser('~')
for cand in [
    os.path.join(home, 'Área de Trabalho'),
    os.path.join(home, 'Desktop'),
    os.path.join(home, 'area de trabalho')
]:
    if os.path.isdir(cand) and cand not in desktop_dirs:
        desktop_dirs.append(cand)

shortcuts = []
seen = set()

for d in desktop_dirs:
    if not os.path.exists(d):
        continue
    try:
        for f in os.listdir(d):
            full_path = os.path.join(d, f)
            if f in seen or not os.path.isfile(full_path):
                continue
            seen.add(f)
            is_desktop = f.endswith('.desktop')
            item = {
                'filename': f,
                'path': full_path,
                'name': f,
                'exec': '',
                'icon': '',
                'type': 'Application' if is_desktop else 'File',
                'url': '',
                'comment': '',
                'terminal': False,
                'is_desktop': is_desktop,
                'size': os.path.getsize(full_path),
                'mtime': int(os.path.getmtime(full_path))
            }
            if is_desktop:
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as fp:
                        for line in fp:
                            line = line.strip()
                            if line.startswith('Name=') and item['name'] == f:
                                item['name'] = line[5:].strip()
                            elif line.startswith('Exec='):
                                item['exec'] = line[5:].strip()
                            elif line.startswith('Icon='):
                                item['icon'] = line[5:].strip()
                            elif line.startswith('Type='):
                                item['type'] = line[5:].strip()
                            elif line.startswith('URL='):
                                item['url'] = line[4:].strip()
                            elif line.startswith('Comment='):
                                item['comment'] = line[8:].strip()
                            elif line.startswith('Terminal='):
                                item['terminal'] = line[9:].strip().lower() == 'true'
                except Exception:
                    pass
            shortcuts.append(item)
    except Exception:
        pass

shortcuts.sort(key=lambda x: x['name'].lower())
print('JSON_START' + json.dumps(shortcuts, ensure_ascii=False) + 'JSON_END')
" 2>/dev/null || true
"""
    try:
        stdin, stdout, stderr = ssh.exec_command(f"bash -c {shlex.quote(script)}", timeout=12)
        raw_out = stdout.read().decode('utf-8', errors='ignore').strip()
        if 'JSON_START' in raw_out and 'JSON_END' in raw_out:
            json_str = raw_out.split('JSON_START')[1].split('JSON_END')[0].strip()
            data = json.loads(json_str)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"Falha ao extrair atalhos via python: {e}")

    # Fallback básico via shell simples
    try:
        fallback_cmd = """
            for f in "$HOME/Área de Trabalho"/*.desktop "$HOME/Desktop"/*.desktop; do
                if [ -f "$f" ]; then
                    fname=$(basename "$f")
                    name=$(grep -m1 "^Name=" "$f" 2>/dev/null | cut -d= -f2- || echo "$fname")
                    exec_cmd=$(grep -m1 "^Exec=" "$f" 2>/dev/null | cut -d= -f2- || echo "")
                    icon=$(grep -m1 "^Icon=" "$f" 2>/dev/null | cut -d= -f2- || echo "")
                    echo "ITEM|$fname|$name|$exec_cmd|$icon"
                fi
            done
        """
        stdin, stdout, stderr = ssh.exec_command(f"bash -c {shlex.quote(fallback_cmd)}", timeout=8)
        lines = stdout.read().decode('utf-8', errors='ignore').strip().splitlines()
        res = []
        for line in lines:
            if line.startswith("ITEM|"):
                parts = line.split("|")
                if len(parts) >= 5:
                    res.append({
                        "filename": parts[1],
                        "path": parts[1],
                        "name": parts[2] or parts[1],
                        "exec": parts[3],
                        "icon": parts[4],
                        "type": "Application",
                        "url": "",
                        "comment": "",
                        "terminal": False,
                        "is_desktop": True,
                        "size": 0,
                        "mtime": 0
                    })
        return res
    except Exception:
        return []

def shell_create_desktop_shortcut(ssh: paramiko.SSHClient, username: str, password: str, shortcut: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    """Cria um arquivo .desktop na Área de Trabalho com permissões executáveis e confiáveis."""
    name = shortcut.get('name', 'Novo Atalho').strip()
    stype = shortcut.get('type', 'app')
    exec_cmd = shortcut.get('exec', '').strip()
    url = shortcut.get('url', '').strip()
    icon = shortcut.get('icon', 'application-x-executable').strip()
    comment = shortcut.get('comment', '').strip()
    terminal = "true" if shortcut.get('terminal') else "false"
    kiosk = bool(shortcut.get('kiosk', False))

    safe_name = re.sub(r'[^a-zA-Z0-9_\-áéíóúÁÉÍÓÚãõÃÕâêîôûÂÊÎÔÛçÇ ]', '', name).strip().replace(' ', '_')
    if not safe_name:
        safe_name = "atalho"
    filename = f"{safe_name}.desktop"

    if stype == 'url' and url:
        if kiosk:
            exec_line = f"google-chrome-stable --kiosk --app={shlex.quote(url)} || firefox --kiosk {shlex.quote(url)} || xdg-open {shlex.quote(url)}"
        else:
            exec_line = f"google-chrome-stable --app={shlex.quote(url)} || firefox {shlex.quote(url)} || xdg-open {shlex.quote(url)}"
        entry_type = "Application"
    else:
        exec_line = exec_cmd if exec_cmd else "x-terminal-emulator"
        entry_type = "Application"

    desktop_content = f"""[Desktop Entry]
Version=1.0
Type={entry_type}
Name={name}
Comment={comment}
Exec={exec_line}
Icon={icon}
Terminal={terminal}
Categories=Education;Development;Utility;
StartupNotify=true
"""

    encoded_content = base64.b64encode(desktop_content.encode('utf-8')).decode('ascii')

    script = f"""
        DESK_DIR=$(xdg-user-dir DESKTOP 2>/dev/null || true)
        if [ -z "$DESK_DIR" ] || [ ! -d "$DESK_DIR" ]; then DESK_DIR="$HOME/Área de Trabalho"; fi
        if [ ! -d "$DESK_DIR" ]; then DESK_DIR="$HOME/Desktop"; fi
        mkdir -p "$DESK_DIR"

        TARGET_FILE="$DESK_DIR/{filename}"
        echo "{encoded_content}" | base64 -d > "$TARGET_FILE"
        chmod +x "$TARGET_FILE"
        chmod 755 "$TARGET_FILE" 2>/dev/null || true
        
        gio set "$TARGET_FILE" metadata::trusted true 2>/dev/null || true
        gio set "$TARGET_FILE" metadata::trusted yes 2>/dev/null || true

        # Dispara refresh visual em tempo real na tela do aluno (Nemo / Desktop)
        touch "$DESK_DIR" 2>/dev/null || true
        if pgrep -f "nemo-desktop" >/dev/null 2>&1; then
            killall -HUP nemo-desktop 2>/dev/null || true
        fi

        echo "Atalho '$name' criado com sucesso em '$TARGET_FILE'."
    """
    try:
        stdin, stdout, stderr = ssh.exec_command(f"bash -c {shlex.quote(script)}", timeout=10)
        out = stdout.read().decode('utf-8', errors='ignore').strip()
        err = stderr.read().decode('utf-8', errors='ignore').strip()
        return out, None, err if err else None
    except Exception as e:
        return f"Erro ao criar atalho: {str(e)}", None, str(e)

def shell_delete_desktop_shortcuts(ssh: paramiko.SSHClient, username: str, password: str, filenames: List[str], backup: bool = True, backup_root_dir: str = "backup_shortcuts") -> Tuple[str, Optional[str], Optional[str]]:
    """Remove ou move atalhos específicos da Área de Trabalho para a pasta de backup (varre todas as pastas Desktop e usuários)."""
    if not filenames:
        return "Nenhum arquivo especificado.", None, None

    payload_json = json.dumps({
        "filenames": filenames,
        "backup": backup,
        "backup_root_dir": backup_root_dir
    })

    python_script = f"""import os, sys, glob, shutil, subprocess, json

payload = json.loads({repr(payload_json)})
target_files = payload.get('filenames', [])
do_backup = payload.get('backup', True)
b_root_name = payload.get('backup_root_dir', 'backup_shortcuts')

norm_targets = set()
for t in target_files:
    norm_targets.add(t.strip().lower())
    if t.lower().endswith('.desktop'):
        norm_targets.add(t[:-8].strip().lower())

home = os.path.expanduser('~')
all_homes = [home]
if os.path.isdir('/home'):
    for u in os.listdir('/home'):
        uhome = os.path.join('/home', u)
        if os.path.isdir(uhome) and uhome not in all_homes:
            all_homes.append(uhome)

deleted_count = 0
deleted_names = []

for u_home in all_homes:
    desk_dirs = [
        os.path.join(u_home, 'Área de Trabalho'),
        os.path.join(u_home, 'Desktop'),
        os.path.join(u_home, 'area de trabalho'),
        os.path.join(u_home, 'desktop')
    ]
    u_backup_dir = os.path.join(u_home, b_root_name, 'removidos')
    if do_backup:
        try:
            os.makedirs(u_backup_dir, exist_ok=True)
        except Exception:
            pass

    for d in desk_dirs:
        if not os.path.isdir(d):
            continue
        try:
            for f in os.listdir(d):
                f_path = os.path.join(d, f)
                if not os.path.isfile(f_path):
                    continue
                f_norm = f.lower()
                f_no_ext = f_norm[:-8] if f_norm.endswith('.desktop') else f_norm
                
                display_name = ""
                if f.endswith('.desktop'):
                    try:
                        with open(f_path, 'r', encoding='utf-8', errors='ignore') as fp:
                            for line in fp:
                                if line.startswith('Name='):
                                    display_name = line[5:].strip().lower()
                                    break
                    except Exception:
                        pass

                should_delete = False
                if f in target_files or f_norm in norm_targets or f_no_ext in norm_targets:
                    should_delete = True
                elif display_name and display_name in norm_targets:
                    should_delete = True

                if should_delete:
                    if do_backup:
                        try:
                            shutil.move(f_path, os.path.join(u_backup_dir, f))
                            deleted_count += 1
                            deleted_names.append(f)
                        except Exception:
                            try:
                                shutil.copy2(f_path, os.path.join(u_backup_dir, f))
                                os.remove(f_path)
                                deleted_count += 1
                                deleted_names.append(f)
                            except Exception:
                                pass
                    else:
                        try:
                            os.remove(f_path)
                            deleted_count += 1
                            deleted_names.append(f)
                        except Exception:
                            pass
            
            try:
                subprocess.run(['touch', d], timeout=1, capture_output=True)
            except Exception:
                pass
        except Exception:
            pass

try:
    subprocess.run(['killall', '-HUP', 'nemo-desktop'], timeout=1, capture_output=True)
    subprocess.run(['killall', '-HUP', 'nautilus'], timeout=1, capture_output=True)
except Exception:
    pass

if deleted_count > 0:
    nomes_str = ', '.join(list(set(deleted_names))[:5])
    print(f"{deleted_count} atalho(s) removido(s) com sucesso ({nomes_str}).")
else:
    print("0 atalhos removidos.")
"""
    script = f"python3 -c {shlex.quote(python_script)}"
    output, warnings, errors = _execute_shell_command(ssh, script, password, username=username)
    return output, warnings, errors

def shell_keep_only_desktop_shortcuts(ssh: paramiko.SSHClient, username: str, password: str, keep_names: List[str], backup_removed: bool = True) -> Tuple[str, Optional[str], Optional[str]]:
    """Mantém estritamente os atalhos permitidos (ex: Matific e Elefante Letrado), cria-os se faltarem e remove/arquiva TODOS os outros atalhos da Área de Trabalho em todas as contas locais."""
    payload_json = json.dumps({
        "keep_names": keep_names,
        "backup": backup_removed
    })

    python_script = f"""import os, sys, glob, shutil, subprocess, json

payload = json.loads({repr(payload_json)})
allowed = payload.get('keep_names', [])
do_backup = payload.get('backup', True)

allowed_norms = set()
for a in allowed:
    a_clean = a.strip().lower()
    allowed_norms.add(a_clean)
    if a_clean.endswith('.desktop'):
        allowed_norms.add(a_clean[:-8].strip())

home = os.path.expanduser('~')
all_homes = [home]
if os.path.isdir('/home'):
    for u in os.listdir('/home'):
        uhome = os.path.join('/home', u)
        if os.path.isdir(uhome) and uhome not in all_homes:
            all_homes.append(uhome)

removed_count = 0
kept_count = 0
created_count = 0

# Template de atalhos padrão pré-configurados
STANDARD_SHORTCUTS = {{
    "elefante letrado": \"\"\"[Desktop Entry]
Version=1.0
Type=Application
Name=Elefante Letrado
Comment=Biblioteca digital e incentivo à leitura
Exec=google-chrome-stable --no-first-run --no-default-browser-check --disable-session-crashed-bubble --disable-infobars --kiosk https://login.elefanteletrado.com.br/student || firefox --kiosk https://login.elefanteletrado.com.br/student || xdg-open https://login.elefanteletrado.com.br/student
Icon=google-chrome
Terminal=false
Categories=Education;
StartupNotify=true
\"\"\",
    "matific": \"\"\"[Desktop Entry]
Version=1.0
Type=Application
Name=Matific
Comment=Jogos matemáticos e atividades pedagógicas
Exec=google-chrome-stable --kiosk --app=https://www.matific.com/login || firefox --kiosk https://www.matific.com/login || xdg-open https://www.matific.com/login
Icon=google-chrome
Terminal=false
Categories=Education;
StartupNotify=true
\"\"\"
}}

for u_home in all_homes:
    desk_dirs = [
        os.path.join(u_home, 'Área de Trabalho'),
        os.path.join(u_home, 'Desktop'),
        os.path.join(u_home, 'area de trabalho'),
        os.path.join(u_home, 'desktop')
    ]
    u_backup_dir = os.path.join(u_home, 'backup_shortcuts', 'limpeza_padrao')
    if do_backup:
        try:
            os.makedirs(u_backup_dir, exist_ok=True)
        except Exception:
            pass

    main_desk = None
    for d in desk_dirs:
        if os.path.isdir(d):
            main_desk = d
            break
    if not main_desk:
        main_desk = desk_dirs[0]
        try:
            os.makedirs(main_desk, exist_ok=True)
        except Exception:
            pass

    existing_allowed_in_home = set()

    for d in desk_dirs:
        if not os.path.isdir(d):
            continue
        try:
            for f in os.listdir(d):
                f_path = os.path.join(d, f)
                if not os.path.isfile(f_path):
                    continue
                f_norm = f.lower()
                f_no_ext = f_norm[:-8] if f_norm.endswith('.desktop') else f_norm
                
                display_name = ""
                if f.endswith('.desktop'):
                    try:
                        with open(f_path, 'r', encoding='utf-8', errors='ignore') as fp:
                            for line in fp:
                                if line.startswith('Name='):
                                    display_name = line[5:].strip().lower()
                                    break
                    except Exception:
                        pass

                is_allowed = False
                matched_key = None
                for a in allowed_norms:
                    if a == f_norm or a == f_no_ext or (display_name and a == display_name) or (len(a) >= 4 and (a in f_norm or a in display_name)):
                        is_allowed = True
                        matched_key = a
                        break

                if is_allowed:
                    kept_count += 1
                    if matched_key:
                        existing_allowed_in_home.add(matched_key)
                    try:
                        os.chmod(f_path, 0o755)
                        subprocess.run(['gio', 'set', f_path, 'metadata::trusted', 'true'], timeout=1, capture_output=True)
                        subprocess.run(['gio', 'set', f_path, 'metadata::trusted', 'yes'], timeout=1, capture_output=True)
                    except Exception:
                        pass
                else:
                    removed_count += 1
                    if do_backup:
                        try:
                            shutil.move(f_path, os.path.join(u_backup_dir, f))
                        except Exception:
                            try:
                                shutil.copy2(f_path, os.path.join(u_backup_dir, f))
                                os.remove(f_path)
                            except Exception:
                                pass
                    else:
                        try:
                            os.remove(f_path)
                        except Exception:
                            pass
        except Exception:
            pass

    # Garante que os atalhos autorizados padrão existam no desktop principal do usuário
    for a_req in allowed_norms:
        for t_key, t_content in STANDARD_SHORTCUTS.items():
            if (a_req == t_key or t_key in a_req or a_req in t_key) and not any(t_key in e or e in t_key for e in existing_allowed_in_home):
                target_fname = f"{{t_key.title().replace(' ', '_')}}.desktop"
                target_fpath = os.path.join(main_desk, target_fname)
                try:
                    with open(target_fpath, 'w', encoding='utf-8') as tf:
                        tf.write(t_content)
                    os.chmod(target_fpath, 0o755)
                    subprocess.run(['gio', 'set', target_fpath, 'metadata::trusted', 'true'], timeout=1, capture_output=True)
                    subprocess.run(['gio', 'set', target_fpath, 'metadata::trusted', 'yes'], timeout=1, capture_output=True)
                    created_count += 1
                    kept_count += 1
                    existing_allowed_in_home.add(t_key)
                except Exception:
                    pass

    for d in desk_dirs:
        if os.path.isdir(d):
            try:
                subprocess.run(['touch', d], timeout=1, capture_output=True)
            except Exception:
                pass

try:
    subprocess.run(['killall', '-HUP', 'nemo-desktop'], timeout=1, capture_output=True)
    subprocess.run(['killall', '-HUP', 'nautilus'], timeout=1, capture_output=True)
except Exception:
    pass

msg = f"Padronização concluída! {{kept_count}} atalho(s) mantido(s)/criado(s) e {{removed_count}} atalho(s) arquivado(s)."
print(msg)
"""
    script = f"python3 -c {shlex.quote(python_script)}"
    output, warnings, errors = _execute_shell_command(ssh, script, password, username=username)
    return output, warnings, errors

def shell_fix_desktop_shortcuts_permissions(ssh: paramiko.SSHClient, username: str, password: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Aplica permissões de execução (chmod +x / 755) e marcação confiável (gio metadata::trusted) em todos os atalhos da Área de Trabalho."""
    python_script = """import os, sys, subprocess

home = os.path.expanduser('~')
desk_dirs = []
try:
    p = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, timeout=2)
    out = p.stdout.strip()
    if out and os.path.isdir(out):
        desk_dirs.append(out)
except Exception:
    pass

for cand in [os.path.join(home, 'Área de Trabalho'), os.path.join(home, 'Desktop'), os.path.join(home, 'area de trabalho')]:
    if os.path.isdir(cand) and cand not in desk_dirs:
        desk_dirs.append(cand)

fixed_count = 0
fixed_files = []

for d in desk_dirs:
    if not os.path.exists(d):
        continue
    for f in os.listdir(d):
        if f.endswith('.desktop') or f.endswith('.sh'):
            fpath = os.path.join(d, f)
            try:
                os.chmod(fpath, 0o755)
            except Exception:
                pass
            try:
                subprocess.run(['gio', 'set', fpath, 'metadata::trusted', 'true'], timeout=1, capture_output=True)
                subprocess.run(['gio', 'set', fpath, 'metadata::trusted', 'yes'], timeout=1, capture_output=True)
            except Exception:
                pass
            fixed_count += 1
            fixed_files.append(f)

if fixed_count > 0:
    nomes = ', '.join(fixed_files[:4]) + ('...' if len(fixed_files) > 4 else '')
    print(f"Permissões corrigidas com sucesso em {fixed_count} atalho(s) ({nomes}).")
else:
    print("Nenhum atalho encontrado na Área de Trabalho para ajustar permissões.")
"""
    script = f"python3 -c {shlex.quote(python_script)}"
    output, warnings, errors = _execute_shell_command(ssh, script, password, username=username)
    return output, warnings, errors

def shell_clean_broken_shortcuts(ssh: paramiko.SSHClient, username: str, password: str, backup_broken: bool = True) -> Tuple[str, Optional[str], Optional[str]]:
    """Identifica e move/remove atalhos da Área de Trabalho cujos executáveis ou arquivos não existem no sistema."""
    python_script = f"""import os, sys, shutil, subprocess, json

home = os.path.expanduser('~')
desk_dirs = []
try:
    p = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, timeout=2)
    out = p.stdout.strip()
    if out and os.path.isdir(out):
        desk_dirs.append(out)
except Exception:
    pass

for cand in [os.path.join(home, 'Área de Trabalho'), os.path.join(home, 'Desktop'), os.path.join(home, 'area de trabalho')]:
    if os.path.isdir(cand) and cand not in desk_dirs:
        desk_dirs.append(cand)

broken_dir = os.path.join(home, 'backup_shortcuts', 'atalhos_quebrados')
if {repr(backup_broken)}:
    os.makedirs(broken_dir, exist_ok=True)

broken_count = 0
broken_names = []

def is_cmd_available(cmd_str):
    if not cmd_str:
        return True
    first_tok = cmd_str.strip().split()[0].strip('"' + "'")
    if first_tok.startswith('env') or first_tok.startswith('sh') or first_tok.startswith('bash'):
        parts = cmd_str.strip().split()
        if len(parts) > 1:
            first_tok = parts[1].strip('"' + "'")
    if '/' in first_tok:
        return os.path.exists(first_tok)
    # Verifica no PATH do sistema
    p = subprocess.run(['which', first_tok], capture_output=True, timeout=1)
    if p.returncode == 0:
        return True
    if 'flatpak' in cmd_str:
        return True
    return False

for d in desk_dirs:
    if not os.path.exists(d):
        continue
    for f in os.listdir(d):
        if not f.endswith('.desktop'):
            continue
        fpath = os.path.join(d, f)
        exec_val = ""
        type_val = "Application"
        url_val = ""
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
                for line in fp:
                    line = line.strip()
                    if line.startswith('Exec='):
                        exec_val = line[5:].strip()
                    elif line.startswith('Type='):
                        type_val = line[5:].strip()
                    elif line.startswith('URL='):
                        url_val = line[4:].strip()
        except Exception:
            continue

        is_broken = False
        if type_val == 'Link' and not url_val:
            is_broken = True
        elif type_val == 'Application' and exec_val:
            if not is_cmd_available(exec_val):
                is_broken = True

        if is_broken:
            broken_count += 1
            broken_names.append(f)
            if {repr(backup_broken)}:
                try:
                    shutil.move(fpath, os.path.join(broken_dir, f))
                except Exception:
                    pass
            else:
                try:
                    os.remove(fpath)
                except Exception:
                    pass

if broken_count > 0:
    nomes = ', '.join(broken_names[:5]) + ('...' if len(broken_names) > 5 else '')
    print(f"Limpeza concluída. {broken_count} atalho(s) quebrado(s) arquivado(s): {nomes}")
else:
    print("Nenhum atalho quebrado foi detectado na Área de Trabalho.")
"""
    script = f"python3 -c {shlex.quote(python_script)}"
    output, warnings, errors = _execute_shell_command(ssh, script, password, username=username)
    return output, warnings, errors

def shell_empty_shortcut_backups(ssh: paramiko.SSHClient, username: str, password: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Esvazia com segurança todas as pastas de backup de atalhos e lixeira."""
    python_script = """import os, shutil

home = os.path.expanduser('~')
target_dirs = [
    os.path.join(home, 'backup_shortcuts'),
    os.path.join(home, 'atalhos_desativados'),
    os.path.join(home, 'Desktop_Backup'),
    os.path.join(home, 'Área de Trabalho_Backup'),
    os.path.join(home, '.backup_shortcuts')
]

deleted_files = 0
for d in target_dirs:
    if os.path.isdir(d):
        for root, dirs, files in os.walk(d):
            deleted_files += len(files)
        try:
            shutil.rmtree(d)
        except Exception:
            pass

print(f"Lixeira e backups esvaziados com sucesso ({deleted_files} arquivo(s) removido(s)).")
"""
    script = f"python3 -c {shlex.quote(python_script)}"
    output, warnings, errors = _execute_shell_command(ssh, script, password, username=username)
    return output, warnings, errors

def shell_list_shortcut_backups_detailed(ssh: paramiko.SSHClient, username: str, password: str, backup_root_dir: str = "backup_shortcuts") -> List[Dict[str, Any]]:
    """Lista detalhada de atalhos contidos nas pastas de backup com metadados parseados."""
    python_script = f"""
import os, glob, json

home = os.path.expanduser('~')
candidate_roots = [
    os.path.join(home, '{backup_root_dir}'),
    os.path.join(home, 'backup_shortcuts'),
    os.path.join(home, 'atalhos_desativados'),
    os.path.join(home, 'Desktop_Backup'),
    os.path.join(home, 'Área de Trabalho_Backup'),
    os.path.join(home, '.backup_shortcuts')
]

seen_roots = []
for r in candidate_roots:
    if os.path.isdir(r) and r not in seen_roots:
        seen_roots.append(r)

backups = []
seen_files = set()

for backup_root in seen_roots:
    for root, dirs, files in os.walk(backup_root):
        for f in files:
            full_path = os.path.join(root, f)
            if full_path in seen_files:
                continue
            seen_files.add(full_path)
            rel_path = os.path.relpath(full_path, backup_root)
            is_desktop = f.endswith('.desktop')
            item = {{
                'filename': f,
                'rel_path': rel_path.replace(os.sep, '/'),
                'folder': os.path.basename(root) or os.path.basename(backup_root),
                'backup_source': os.path.basename(backup_root),
                'name': f,
                'exec': '',
                'icon': '',
                'type': 'Application' if is_desktop else 'File',
                'url': '',
                'comment': '',
                'is_desktop': is_desktop,
                'size': os.path.getsize(full_path),
                'mtime': int(os.path.getmtime(full_path))
            }}
            if is_desktop:
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as fp:
                        for line in fp:
                            line = line.strip()
                            if line.startswith('Name=') and item['name'] == f:
                                item['name'] = line[5:].strip()
                            elif line.startswith('Exec='):
                                item['exec'] = line[5:].strip()
                            elif line.startswith('Icon='):
                                item['icon'] = line[5:].strip()
                            elif line.startswith('Type='):
                                item['type'] = line[5:].strip()
                            elif line.startswith('URL='):
                                item['url'] = line[4:].strip()
                            elif line.startswith('Comment='):
                                item['comment'] = line[8:].strip()
                except Exception:
                    pass
            backups.append(item)

backups.sort(key=lambda x: x['name'].lower())
print('JSON_START' + json.dumps(backups, ensure_ascii=False) + 'JSON_END')
"""
    cmd = f"python3 -c {shlex.quote(python_script)}"
    try:
        if username:
            cmd = f"sudo -S -H -u {username} bash -c {shlex.quote(cmd)}"
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=10)
        if username and "sudo -S" in cmd:
            stdin.write(password + '\n')
            stdin.flush()
        raw_out = stdout.read().decode('utf-8', errors='ignore').strip()
        if 'JSON_START' in raw_out and 'JSON_END' in raw_out:
            json_str = raw_out.split('JSON_START')[1].split('JSON_END')[0].strip()
            data = json.loads(json_str)
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []

def list_sftp_backups(ssh: paramiko.SSHClient, backup_root_dir: str) -> Dict[str, List[str]]:
    """Lista os backups de atalhos disponíveis via SFTP."""
    with ssh.open_sftp() as sftp:
        home_dir = sftp.normalize('.')
        backup_root = posixpath.join(home_dir, backup_root_dir)
        try:
            sftp.stat(backup_root)
        except FileNotFoundError:
            return {}

        backup_dirs = [d for d in sftp.listdir(backup_root) if stat.S_ISDIR(sftp.stat(posixpath.join(backup_root, d)).st_mode)]
        backups_by_dir = {}
        for directory in backup_dirs:
            dir_path = posixpath.join(backup_root, directory)
            files = [f for f in sftp.listdir(dir_path) if f.endswith('.desktop')]
            if files:
                backups_by_dir[directory] = files
        return backups_by_dir

def _handle_sftp_action(ssh: paramiko.SSHClient, username: str, action: str, data: Dict[str, Any], backup_root_dir: str, logger) -> Dict[str, Any]:
    """Lida com ações de atalhos convertendo para comandos shell (sudo) para garantir permissões."""
    password = data.get('password')
    remote_ip = ssh.get_transport().getpeername()[0]
    
    if action == 'desativar':
        message, warnings, errors = shell_disable_shortcuts(ssh, username, password, backup_root_dir)
        details = []
        if warnings: details.append(f"Avisos:\n{warnings}")
        if errors: details.append(f"Erros não fatais:\n{errors}")
        return {"success": True, "message": message, "details": "\n\n".join(details) if details else None}

    elif action == 'ativar':
        backup_files = data.get('backup_files', [])
        message, warnings, errors = shell_restore_shortcuts(ssh, username, password, backup_files, backup_root_dir)
        details = []
        if warnings: details.append(f"Avisos:\n{warnings}")
        if errors: details.append(f"Erros não fatais:\n{errors}")
        return {"success": True, "message": message, "details": "\n\n".join(details) if details else None}

    return {"success": False, "message": "Ação interna desconhecida."}

def _handle_set_wallpaper_for_user(ssh: paramiko.SSHClient, username: str, password: str, remote_image_path: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Define o papel de parede para um usuário específico usando um arquivo já existente na máquina remota."""
    # This function is already well-defined, it just needs to be called by the dispatcher.
    from command_builder import GSETTINGS_ENV_SETUP
    
    safe_uri = shlex.quote(f"file://{remote_image_path}")
    set_wallpaper_script = f"""
        if gsettings list-schemas | grep -q 'org.cinnamon.desktop.background'; then
            gsettings set org.cinnamon.desktop.background picture-uri {safe_uri}
            echo "Papel de parede definido com sucesso (Cinnamon)."
        elif gsettings list-schemas | grep -q 'org.gnome.desktop.background'; then
            gsettings set org.gnome.desktop.background picture-uri {safe_uri}
            echo "Papel de parede definido com sucesso (GNOME Fallback)."
        else
            echo "Erro: Nenhum schema de papel de parede compatível (Cinnamon ou GNOME) foi encontrado." >&2
            exit 1
        fi
    """
    command = GSETTINGS_ENV_SETUP + set_wallpaper_script
    return _execute_shell_command(ssh, command, password, username=username)

def _handle_cleanup_wallpaper(ssh: paramiko.SSHClient, data: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    """Remove o arquivo de papel de parede temporário da máquina remota usando um comando simples."""
    # This function is already well-defined, it just needs to be called by the dispatcher.
    wallpaper_filename = data.get('wallpaper_filename')
    if not wallpaper_filename:
        raise CommandExecutionError("Nome do arquivo de papel de parede não fornecido para limpeza.")

    remote_temp_path = posixpath.join("/tmp", wallpaper_filename)
    command = f"rm -f {shlex.quote(remote_temp_path)}"

    # Executa um comando simples de remoção que não requer sudo.
    _, _, stderr = ssh.exec_command(command)
    error_output = stderr.read().decode('utf-8', errors='ignore').strip()

    return "Limpeza concluída.", None, error_output if error_output else None

# --- Helper functions for _execute_for_each_user ---

def _process_wallpaper_action_for_user(ssh: paramiko.SSHClient, user: str, action: str, data: Dict[str, Any], logger) -> Dict[str, Any]:
    """Handles the 'definir_papel_de_parede' action for a single user."""
    remote_temp_path = data.get('remote_wallpaper_path') # This should be passed from app.py
    password = data.get('password')
    if not all([remote_temp_path, password]):
        return {"success": False, "message": "Caminho remoto do papel de parede ou senha ausentes."}
    try:
        message, warnings, errors = _handle_set_wallpaper_for_user(ssh, user, password, remote_temp_path)
        success = not errors
        details = []
        if warnings: details.append(f"Avisos:\n{warnings}")
        if errors: details.append(f"Erros:\n{errors}")
        return {"success": success, "message": message, "details": "\n".join(details) if details else None}
    except CommandExecutionError as e:
        logger.error(f"Erro na ação '{action}' para o usuário '{user}': {e.details}")
        details = []
        if e.warnings: details.append(f"Avisos: {e.warnings}")
        if e.details: details.append(f"Erros: {e.details}")
        return {"success": False, "message": "Ocorreu um erro no dispositivo remoto.", "details": "\n".join(details)}
    except Exception as e:
        logger.error(f"Exceção inesperada na ação '{action}' para o usuário '{user}': {e}")
        return {"success": False, "message": "Ocorreu uma exceção inesperada no servidor.", "details": str(e)}

def _process_sftp_shortcut_action_for_user(ssh: paramiko.SSHClient, user: str, action: str, data: Dict[str, Any], logger) -> Dict[str, Any]:
    """Handles SFTP shortcut actions ('desativar', 'ativar') for a single user."""
    backup_root_dir = data.get('backup_root_dir', 'atalhos_desativados')
    try:
        return _handle_sftp_action(ssh, user, action, data, backup_root_dir, logger)
    except CommandExecutionError as e:
        logger.error(f"Erro na ação '{action}' para o usuário '{user}': {e.details}")
        details = []
        if e.warnings: details.append(f"Avisos: {e.warnings}")
        if e.details: details.append(f"Erros: {e.details}")
        return {"success": False, "message": "Ocorreu um erro no dispositivo remoto.", "details": "\n".join(details)}
    except Exception as e:
        logger.error(f"Exceção inesperada na ação '{action}' para o usuário '{user}': {e}")
        return {"success": False, "message": "Ocorreu uma exceção inesperada no servidor.", "details": str(e)}

def _process_generic_shell_action_for_user(ssh: paramiko.SSHClient, user: str, action: str, data: Dict[str, Any], logger) -> Dict[str, Any]:
    """Handles generic shell actions for a single user."""
    try:
        handler = data.get('shell_action_handler')
        if not handler:
            from app import _handle_shell_action
            handler = _handle_shell_action
        return handler(ssh, user, action, data)
    except CommandExecutionError as e:
        logger.error(f"Erro na ação '{action}' para o usuário '{user}': {e.details}")
        details = []
        if e.warnings: details.append(f"Avisos: {e.warnings}")
        if e.details: details.append(f"Erros: {e.details}")
        return {"success": False, "message": "Ocorreu um erro no dispositivo remoto.", "details": "\n".join(details)}
    except Exception as e:
        logger.error(f"Exceção inesperada na ação '{action}' para o usuário '{user}': {e}", exc_info=True)
        return {"success": False, "message": "Ocorreu uma exceção inesperada no servidor.", "details": str(e)}

# Dispatch table for user-specific actions
USER_ACTION_HANDLERS = {
    'definir_papel_de_parede': _process_wallpaper_action_for_user,
    'desativar': _process_sftp_shortcut_action_for_user,
    'ativar': _process_sftp_shortcut_action_for_user,
    'ocultar_icone_rede': _process_generic_shell_action_for_user,
    'mostrar_icone_rede': _process_generic_shell_action_for_user,
    'bloquear_terminal': _process_generic_shell_action_for_user,
    'desbloquear_terminal': _process_generic_shell_action_for_user,
    'bloquear_dconf': _process_generic_shell_action_for_user,
    'desbloquear_dconf': _process_generic_shell_action_for_user,
    'bloquear_combinacoes_teclas': _process_generic_shell_action_for_user,
    'desbloquear_combinacoes_teclas': _process_generic_shell_action_for_user,
    'bloquear_tela_mensagem': _process_generic_shell_action_for_user,
    'desbloquear_tela_mensagem': _process_generic_shell_action_for_user,
    'limpar_tela': _process_generic_shell_action_for_user,
    'deslogar_navegadores': _process_generic_shell_action_for_user,
    'remover_todos_bloqueios': _process_generic_shell_action_for_user,
    'limpar_imagens': _process_generic_shell_action_for_user,
}

# Ações que já possuem iterador interno de multiseat/displays ou são aplicadas no host inteiro
MULTISEAT_BROADCAST_ACTIONS = {
    'pedir_silencio', 'sintetizar_voz', 'enviar_mensagem', 'fechar_mensagem',
    'abrir_site',
    'bloquear_tela_mensagem', 'desbloquear_tela_mensagem', 'limpar_tela',
    'deslogar_navegadores', 'iniciar_modo_demo', 'parar_modo_demo',
    'desativar_perifericos', 'ativar_perifericos', 'remover_todos_bloqueios',
    'ativar_protecao_tela', 'desativar_protecao_tela', 'configurar_protecao_tela',
    'bloquear_terminal', 'desbloquear_terminal', 'bloquear_dconf', 'desbloquear_dconf',
    'bloquear_combinacoes_teclas', 'desbloquear_combinacoes_teclas',
    'desativar_barra_tarefas', 'ativar_barra_tarefas', 'bloquear_barra_tarefas', 'desbloquear_barra_tarefas',
    'definir_firefox_padrao', 'definir_chrome_padrao', 'desativar_botao_direito', 'ativar_botao_direito',
    'instalar_scratchjr', 'limpar_imagens', 'semaforo_ruido', 'celebrar_turma_nota_10'
}

# Esta função é um dispatcher para ações que precisam ser executadas para cada usuário logado
# na máquina remota. Ela é chamada pelo `gerenciar_atalhos_ip` em `app.py` quando a ação
# é configurada para ser executada por usuário.
def _execute_for_each_user(ssh: paramiko.SSHClient, action: str, data: Dict[str, Any], logger) -> Dict[str, Any]:
    """
    Encontra e executa uma ação para os usuários logados na máquina remota com Fast-Path Pipeline:
    - Se a ação for de broadcast multiseat, despacha em 1 ÚNICO round-trip SSH.
    - Se for direcionada a um usuário específico, executa diretamente sem varredura prévia.
    - Se for ação de atalho SFTP, descobre usuários e paraleliza.
    """
    target_user = data.get('target_user')
    
    # ── FAST-PATH 1: Ação direcionada a usuário específico ──
    if target_user and str(target_user).strip():
        user = str(target_user).strip()
        handler = USER_ACTION_HANDLERS.get(action, _process_generic_shell_action_for_user)
        res = handler(ssh, user, action, data, logger)
        return {
            "success": res.get("success", False),
            "message": res.get("message", f"Ação '{action}' concluída para {user}."),
            "user_results": {user: res}
        }

    # ── FAST-PATH 2: Ação de broadcast multiseat (Zero Round-Trips extras de descoberta) ──
    if action in MULTISEAT_BROADCAST_ACTIONS:
        res = _process_generic_shell_action_for_user(ssh, None, action, data, logger)
        return {
            "success": res.get("success", False),
            "message": res.get("message", f"Ação '{action}' executada em todas as sessões da máquina."),
            "user_results": {"all_sessions": res}
        }

    # ── FALLBACK: Ações de arquivo SFTP que exigem iteração de usuários (/home/aluno) ──
    # Prioriza usuários ativamente logados no sistema (via who, sessões /run/user/ e processos gráficos de multiseat)
    list_active_cmd = r"""
        (
            who 2>/dev/null | awk '{print $1}'
            ls -d /run/user/[0-9]* 2>/dev/null | while read d; do getent passwd "$(basename "$d")" 2>/dev/null | cut -d: -f1; done
            ps -ef 2>/dev/null | grep -E "session|desktop|Xorg|Xephyr|lightdm|gdm|kdm|sddm|openbox|xfce" | awk '{print $1}'
        ) | grep -v -E "^$|root|daemon|nobody|rtkit|syslog|messagebus" | sort -u
    """
    try:
        _, stdout, _ = ssh.exec_command(list_active_cmd, timeout=3)
        users = [u.strip() for u in stdout.read().decode().strip().splitlines() if u.strip()]
    except Exception:
        users = []

    # Fallback se nenhuma sessão ativa for retornada
    if not users:
        try:
            list_all_cmd = r"getent passwd | awk -F: '$6 ~ /^\/home\// && $7 !~ /nologin|false/ {print $1}'"
            _, stdout, _ = ssh.exec_command(list_all_cmd, timeout=3)
            users = [u.strip() for u in stdout.read().decode().strip().splitlines() if u.strip()]
        except Exception:
            users = []

    if not users:
        users = ['aluno']

    results = {}
    
    def run_user_action(user):
        try:
            handler = USER_ACTION_HANDLERS.get(action, _process_generic_shell_action_for_user)
            return user, handler(ssh, user, action, data, logger)
        except Exception as e:
            logger.error(f"Exceção na ação '{action}' para o usuário '{user}': {e}")
            return user, {"success": False, "message": "Erro na execução.", "details": str(e)}

    # Execução paralela das ações por usuário (Max 10 threads por host)
    with ThreadPoolExecutor(max_workers=max(1, min(len(users), 10))) as executor:
        future_to_user = {executor.submit(run_user_action, user): user for user in users}
        for future in as_completed(future_to_user):
            user, result = future.result()
            results[user] = result

    success_count = sum(1 for r in results.values() if r.get('success', False))
    has_success = (success_count > 0)

    summary_message = f"Ação '{action}' concluída para {success_count} de {len(users)} usuário(s)."

    return {
        "success": has_success,
        "message": summary_message,
        "user_results": results
    }

def execute_ssh_batch(
    ips: List[str], 
    username: str, 
    password: str, 
    action_func, 
    logger, 
    max_workers: int = 10
) -> Dict[str, Any]:
    """
    Executa uma função de ação SSH em paralelo para uma lista de IPs usando ThreadPoolExecutor.
    Aproveita o SSHConnectionManager para otimizar conexões ativas e reaproveitar sockets.
    """
    results = {}
    if not ips:
        return results

    with ThreadPoolExecutor(max_workers=min(max_workers, len(ips))) as executor:
        future_to_ip = {
            executor.submit(action_func, ip, username, password, logger): ip 
            for ip in ips
        }
        for future in as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                res = future.result()
                results[ip] = res
            except Exception as e:
                logger.error(f"[SSH Batch] Exceção em {ip}: {e}")
                results[ip] = {"success": False, "message": f"Erro de execução: {str(e)}"}
    return results