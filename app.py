import os
import platform
import subprocess
import shutil
import socket
import ipaddress
import threading
import re
import shlex
from pathlib import Path
import time
from datetime import datetime
import webbrowser
import signal
import hashlib
import base64
import secrets
from functools import wraps
from typing import Dict, Optional, Any, Tuple
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import sqlite3
from multiprocessing import Pool, cpu_count
import json
import logging
from logging.handlers import RotatingFileHandler
import binascii

from flask import Flask, jsonify, request, send_from_directory, Response, Blueprint

import paramiko
from flask_cors import CORS
from waitress import serve

# --- Importações dos Módulos de Serviço Refatorados ---
from command_builder import COMMANDS, COMMAND_METADATA, _get_command_builder, CommandExecutionError, _parse_system_info
from ssh_service import ssh_connect, prune_ssh_cache, _handle_ssh_exception, _execute_for_each_user, _execute_shell_command, _stream_shell_command, list_sftp_backups, _handle_cleanup_wallpaper
from network_service import NetworkScanner, get_local_ip_and_range, is_valid_ip, check_host_online, send_wake_on_lan, get_windows_arp_table, discover_ips_with_arp_scan, IS_WSL
from nic_speed_service import get_remote_nic_speed

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens com suporte a métodos específicos e headers
CORS(app, resources={r"/*": {
    "origins": "*", 
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})

# --- Configuração de Logging Avançado ---
def setup_backend_logging(app):
    log_dir = Path(app.root_path) / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / 'backend.log'

    # Formato: [Data Hora] NÍVEL em módulo: Mensagem
    log_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s [%(threadName)s]: %(message)s'
    )

    # Handler para arquivo (5MB por arquivo, mantém os últimos 5)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)

    # Handler para console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)

    # Configura o logger da aplicação
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)

    # Silencia logs excessivos de bibliotecas externas
    logging.getLogger('paramiko').setLevel(logging.WARNING)
    logging.getLogger('waitress').setLevel(logging.INFO)

    app.logger.info("--- Sistema de Logging Iniciado ---")

setup_backend_logging(app)

# --- Centralização de Erros e Respostas ---
@app.errorhandler(Exception)
def handle_exception(e):
    """Captura qualquer erro não tratado e retorna JSON estruturado."""
    if isinstance(e, CommandExecutionError):
        app.logger.warning(f"Erro de execução de comando remoto não tratado: {e}")
        details = []
        if e.warnings: details.append(f"Avisos: {e.warnings}")
        if e.details: details.append(f"Erros: {e.details}")
        return jsonify({
            "success": False,
            "message": f"Erro no dispositivo remoto: {str(e)}",
            "details": "\n".join(details) if details else None
        }), 400

    app.logger.error(f"Erro não tratado: {str(e)}", exc_info=True)
    return jsonify({
        "success": False,
        "message": "Ocorreu um erro interno no servidor.",
        "details": str(e) if app.debug else None
    }), 500

# Define o diretório raiz para servir arquivos estáticos (frontend)
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Configurações de Segurança ---
# Regex para sanitizar nomes de processos e evitar Command Injection
SAFE_PROCESS_NAME = re.compile(r'^[a-zA-Z0-9._-]+$')

@app.before_request
def log_request_info():
    """Loga detalhes de cada requisição recebida."""
    app.logger.debug(f"Request: {request.method} {request.path} | Source: {request.remote_addr}")
    if request.is_json and request.path != '/check-status': # Evita floodar o log com status checks
        app.logger.debug(f"Payload: {json.dumps(request.get_json())}")

FORCE_STATIC_RANGE = os.getenv("FORCE_STATIC_RANGE", "false").lower() == "true"
IP_PREFIX = os.getenv("IP_PREFIX", "192.168.50.")
IP_START = int(os.getenv("IP_START", "1"))
IP_END = int(os.getenv("IP_END", "254"))
IP_EXCLUSION_LIST = os.getenv("IP_EXCLUSION_LIST", "").split(",") if os.getenv("IP_EXCLUSION_LIST") else []
SSH_USER = os.getenv("SSH_USER", "aluno")
BACKUP_ROOT_DIR = "atalhos_desativados"
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "qwe123")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SESSION_TOKEN = secrets.token_hex(24)

def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)
        
        auth_header = request.headers.get('Authorization')
        token = None
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            
        if not token or token != SESSION_TOKEN:
            app.logger.warning(f"Acesso negado de {request.remote_addr} para {request.path}")
            return jsonify({"success": False, "message": "Acesso não autorizado."}), 401
            
        return f(*args, **kwargs)
    return decorated_function

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    password = data.get('password')
    if password == ADMIN_PASSWORD:
        app.logger.info("Login administrativo bem-sucedido.")
        return jsonify({"success": True, "token": SESSION_TOKEN})
    app.logger.warning("Tentativa de login administrativo falhou.")
    return jsonify({"success": False, "message": "Senha incorreta."}), 401

@app.route('/api/validate-token', methods=['POST'])
def api_validate_token():
    data = request.get_json() or {}
    token = data.get('token')
    if token == SESSION_TOKEN:
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Token inválido."}), 401
def get_request_password(data: Dict) -> str:
    """Extrai a senha da requisição ou retorna a senha padrão."""
    if not data:
        return DEFAULT_PASSWORD
    return data.get('password') or DEFAULT_PASSWORD

# --- Lógica de Cache de Varredura e WebSocket Nativo ---
is_scan_running = False
scan_lock = threading.Lock()
cached_scan_result = None
CACHE_FILE = Path(APP_ROOT) / "scan_cache.json"

def load_scan_cache():
    global cached_scan_result
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                cached_scan_result = json.load(f)
        except Exception:
            cached_scan_result = None

# Servidor WebSocket e gerenciamento de conexões
active_clients = set()
clients_lock = threading.Lock()

def send_text_frame(sock, text):
    try:
        payload = text.encode('utf-8')
        length = len(payload)
        header = bytearray()
        header.append(0x81) # FIN + Text Frame
        if length <= 125:
            header.append(length)
        elif length <= 65535:
            header.append(126)
            header.extend(length.to_bytes(2, byteorder='big'))
        else:
            header.append(127)
            header.extend(length.to_bytes(8, byteorder='big'))
        sock.sendall(header + payload)
        return True
    except OSError:
        return False

def broadcast_ws_message(msg_dict):
    msg_str = json.dumps(msg_dict)
    with clients_lock:
        closed_clients = set()
        for client in active_clients:
            if not send_text_frame(client, msg_str):
                closed_clients.add(client)
        for client in closed_clients:
            active_clients.discard(client)

def handle_ws_client(client_socket):
    try:
        request_data = client_socket.recv(4096).decode('utf-8', errors='ignore')
        if not request_data:
            client_socket.close()
            return

        lines = request_data.split('\r\n')
        if not lines:
            client_socket.close()
            return

        first_line = lines[0]
        parts = first_line.split(' ')
        if len(parts) < 2:
            client_socket.close()
            return

        path = parts[1]
        token = None
        if '?token=' in path:
            token = path.split('?token=')[1].split('&')[0]

        if not token or token != SESSION_TOKEN:
            reject_response = (
                "HTTP/1.1 401 Unauthorized\r\n"
                "Content-Type: text/plain\r\n"
                "Connection: close\r\n\r\n"
                "Acesso não autorizado."
            )
            client_socket.sendall(reject_response.encode('utf-8'))
            client_socket.close()
            return

        headers = {}
        for line in lines:
            if ': ' in line:
                key, val = line.split(': ', 1)
                headers[key.lower()] = val

        if 'sec-websocket-key' in headers:
            ws_key = headers['sec-websocket-key']
            guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
            accept_val = base64.b64encode(hashlib.sha1((ws_key + guid).encode('utf-8')).digest()).decode('utf-8')
            
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: {}\r\n\r\n"
            ).format(accept_val)
            
            client_socket.sendall(response.encode('utf-8'))
            
            with clients_lock:
                active_clients.add(client_socket)
            
            # Mantém conectado, lê descartando para monitorar fechamento da conexão
            while True:
                data = client_socket.recv(1024)
                if not data:
                    break
        else:
            client_socket.close()
    except Exception:
        pass
    finally:
        with clients_lock:
            active_clients.discard(client_socket)
        try:
            client_socket.close()
        except OSError:
            pass

def run_websocket_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind(('0.0.0.0', 5001))
        server_socket.listen(10)
        app.logger.info("Servidor WebSocket nativo escutando na porta 5001")
    except Exception as e:
        app.logger.error(f"Erro ao iniciar servidor WebSocket na porta 5001: {e}")
        return

    while True:
        try:
            client_sock, _ = server_socket.accept()
            threading.Thread(target=handle_ws_client, args=(client_sock,), daemon=True).start()
        except Exception:
            break

class DatabaseManager:
    """Gerencia a persistência em SQLite com foco em integridade e concorrência."""
    def __init__(self, root_path):
        self.db_path = Path(root_path) / 'app_data.db'
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Ativa o modo WAL para melhor suporte a concorrência entre threads
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    ip TEXT PRIMARY KEY,
                    mac TEXT,
                    alias TEXT,
                    is_blocked INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT,
                    ips TEXT,
                    execution_time TEXT,
                    status TEXT DEFAULT 'pending'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    source_ip TEXT,
                    action TEXT,
                    targets TEXT,
                    status TEXT
                )
            """)
            # Migração para garantir colunas necessárias para o sistema completo
            try:
                conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN password TEXT")
            except sqlite3.OperationalError: pass
            try:
                conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN payload TEXT")
            except sqlite3.OperationalError: pass
            try:
                conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP")
            except sqlite3.OperationalError: pass

    def add_audit_log(self, source_ip, action, targets, status):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO audit_logs (source_ip, action, targets, status) VALUES (?, ?, ?, ?)",
                         (source_ip, action, json.dumps(targets), status))

    def get_known_macs(self) -> Dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT ip, mac FROM devices WHERE mac IS NOT NULL")
            return {row[0]: row[1] for row in cursor}

    def update_mac(self, ip, mac):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO devices (ip, mac) VALUES (?, ?) ON CONFLICT(ip) DO UPDATE SET mac=excluded.mac", (ip, mac))

    def get_blocklist(self) -> set:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT ip FROM devices WHERE is_blocked = 1")
            return {row[0] for row in cursor}

    def set_blocked(self, ip, state=True):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO devices (ip, is_blocked) VALUES (?, ?) ON CONFLICT(ip) DO UPDATE SET is_blocked=excluded.is_blocked", (ip, 1 if state else 0))

    def get_aliases(self) -> Dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT ip, alias FROM devices WHERE alias IS NOT NULL")
            return {row[0]: row[1] for row in cursor}

    def update_alias(self, ip, alias):
        with sqlite3.connect(self.db_path) as conn:
            if not alias:
                conn.execute("UPDATE devices SET alias = NULL WHERE ip = ?", (ip,))
            else:
                conn.execute("INSERT INTO devices (ip, alias) VALUES (?, ?) ON CONFLICT(ip) DO UPDATE SET alias=excluded.alias", (ip, alias))

    def add_scheduled_task(self, action, ips, execution_time, password=None, payload=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO scheduled_tasks (action, ips, execution_time, password, payload) VALUES (?, ?, ?, ?, ?)",
                (action, ips, execution_time, password, payload)
            )

    def get_pending_tasks(self, now):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id, action, ips, password, payload FROM scheduled_tasks WHERE status = 'pending' AND execution_time <= ?",
                (now,)
            )
            return cursor.fetchall()

    def get_all_scheduled_tasks(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT id, action, ips, execution_time, status, created_at FROM scheduled_tasks ORDER BY execution_time DESC LIMIT 50")
            return [dict(row) for row in cursor.fetchall()]

    def delete_scheduled_task(self, task_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))

    def mark_task_done(self, task_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE scheduled_tasks SET status = 'completed' WHERE id = ?", (task_id,))

    def mark_task_processing(self, task_id):
        """Marca a tarefa como em execução para evitar duplicidade e permitir recuperação."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE scheduled_tasks SET status = 'processing' WHERE id = ?", (task_id,))

    def reset_orphaned_tasks(self):
        """Recupera tarefas que ficaram presas em 'processing' devido a uma queda do servidor."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE scheduled_tasks SET status = 'pending' WHERE status = 'processing'")

db = DatabaseManager(APP_ROOT)

def run_status_monitor():
    app.logger.info("Monitor de status em segundo plano iniciado.")
    last_statuses = {}
    
    while True:
        try:
            # Obtém a lista de todos os IPs no cache
            ips = []
            if cached_scan_result:
                ips = [item['ip'] for item in cached_scan_result.get('ips', [])]
            
            if ips:
                # Função interna para checar um único IP
                def check_single_ip(ip):
                    try:
                        host_info = check_host_online(ip)
                        if not host_info:
                            return ip, {'status': 'offline', 'user_count': 0}

                        password = DEFAULT_PASSWORD
                        if host_info['type'] == 'ssh':
                            try:
                                with ssh_connect(ip, SSH_USER, password, app.logger, auto_fix_key=True) as ssh:
                                    cmd = "who | wc -l; IFACE=$(ip route | grep default | awk '{print $5}' | head -n1); [ -d /sys/class/net/$IFACE/wireless ] && awk 'NR==3 {print int($3*100/70)}' /proc/net/wireless || echo 100"
                                    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=3)
                                    lines = stdout.read().decode().strip().splitlines()
                                    user_count = int(lines[0]) if lines and lines[0].isdigit() else 1
                                    signal = int(lines[1]) if len(lines) > 1 and lines[1].isdigit() else 100
                                    return ip, {'status': 'online', 'user_count': user_count, 'signal': signal}
                            except paramiko.AuthenticationException:
                                return ip, {'status': 'auth_error', 'user_count': 0}
                            except Exception:
                                return ip, {'status': 'online', 'user_count': 0}
                        else:
                            return ip, {'status': 'online', 'user_count': 0, 'type': 'ping'}
                    except Exception:
                        return ip, {'status': 'offline', 'user_count': 0}

                # Executa em paralelo
                with ThreadPoolExecutor(max_workers=30) as executor:
                    future_to_ip = {executor.submit(check_single_ip, ip): ip for ip in ips}
                    for future in as_completed(future_to_ip):
                        ip, status_data = future.result()
                        
                        # Verifica se mudou para notificar os clientes conectados
                        prev = last_statuses.get(ip)
                        if prev != status_data:
                            last_statuses[ip] = status_data
                            broadcast_ws_message({
                                "type": "status_update",
                                "ip": ip,
                                "status": status_data['status'],
                                "user_count": status_data['user_count'],
                                "signal": status_data.get('signal', 100),
                                "connection_type": status_data.get('type', 'ssh')
                            })
        except Exception as e:
            app.logger.error(f"Erro no monitor de status em segundo plano: {e}")
            
        time.sleep(15)

def start_websocket_and_monitor():
    # Inicializa o cache a partir do arquivo
    load_scan_cache()
    
    # Inicia o servidor WebSocket
    threading.Thread(target=run_websocket_server, daemon=True).start()
    
    # Inicia o monitor de status
    threading.Thread(target=run_status_monitor, daemon=True).start()

def start_scheduler():
    """Inicia o thread de segundo plano para executar tarefas agendadas."""
    # Inicia o servidor WebSocket e o monitor de status em segundo plano
    start_websocket_and_monitor()

    def run_scheduler():
        app.logger.info("Agendador de tarefas em segundo plano iniciado.")
        
        # Recuperação de falhas: Reseta tarefas que não terminaram na última execução do servidor
        db.reset_orphaned_tasks()

        while True:
            try:
                # Manutenção de recursos: limpa conexões SSH mortas do pool
                prune_ssh_cache(app.logger)

                # Formato do datetime-local do HTML: YYYY-MM-DDTHH:MM
                now = datetime.now().strftime('%Y-%m-%dT%H:%M')
                tasks = db.get_pending_tasks(now)
                
                for task in tasks:
                    task_id, action, ips_json, task_password, payload_json = task
                    db.mark_task_processing(task_id)
                    ips = json.loads(ips_json)
                    payload = json.loads(payload_json) if payload_json else {}
                    app.logger.info(f"[Agendador] Executando tarefa {task_id}: {action} para {len(ips)} máquinas.")
                    
                    if action in ['wake_on_lan', 'ligar']:
                        known_macs = db.get_known_macs()
                        for ip in ips:
                            mac = known_macs.get(ip)
                            if mac:
                                if send_wake_on_lan(mac, app.logger):
                                    app.logger.info(f"[Agendador] Magic Packet enviado para {ip} ({mac})")
                                else:
                                    app.logger.error(f"[Agendador] Falha ao enviar Magic Packet para {ip}")
                            else:
                                app.logger.warning(f"[Agendador] MAC não encontrado para o IP {ip}")
                    else:
                        # Ações via SSH (Shutdown, Reboot, etc)
                        pwd = task_password or DEFAULT_PASSWORD
                        for ip in ips:
                            if not is_valid_ip(ip): continue
                            try:
                                with ssh_connect(ip, SSH_USER, pwd, app.logger) as ssh:
                                    # Prepara o payload para o dispatcher
                                    payload.update({"ip": ip, "password": pwd, "action": action, "shell_action_handler": _handle_shell_action})
                                    res = _dispatch_ssh_action(ssh, ip, action, payload, app.logger)
                                    app.logger.info(f"[Agendador] IP {ip}: {res.get('message')}")
                            except Exception as e:
                                app.logger.error(f"[Agendador] Falha ao executar '{action}' em {ip}: {str(e)}")

                    db.mark_task_done(task_id)
            except Exception as e:
                app.logger.error(f"[Agendador Erro] {e}")
            time.sleep(30)

    threading.Thread(target=run_scheduler, daemon=True).start()

@app.route('/api/schedule', methods=['POST'])
@require_admin
def schedule_action():
    data = request.get_json()
    action = data.get('action')
    ips = data.get('ips')
    execution_time = data.get('execution_time')
    password = data.get('password')

    if not all([action, ips, execution_time]):
        return jsonify({"success": False, "message": "Dados de agendamento incompletos."}), 400

    # Removemos as chaves de controle para salvar apenas o payload da ação no banco
    payload = data.copy()
    for k in ['ips', 'execution_time']: payload.pop(k, None)

    db.add_scheduled_task(action, json.dumps(ips), execution_time, password, json.dumps(payload))
    return jsonify({"success": True, "message": f"Ação '{action}' agendada para {execution_time}."})

@app.route('/api/scheduled-tasks', methods=['GET'])
@require_admin
def list_scheduled_tasks():
    """Retorna a lista de tarefas agendadas."""
    tasks = db.get_all_scheduled_tasks()
    return jsonify({"success": True, "tasks": tasks})

@app.route('/api/scheduled-tasks/<int:task_id>', methods=['DELETE'])
@require_admin
def delete_scheduled_task(task_id):
    """Remove uma tarefa agendada."""
    db.delete_scheduled_task(task_id)
    return jsonify({"success": True, "message": "Agendamento cancelado com sucesso."})

@app.route('/import-macs', methods=['POST'])
@require_admin
def import_macs():
    data = request.get_json()
    entries = data.get('entries', [])
    if not entries: return jsonify({"success": False, "message": "Nenhum dado fornecido."}), 400

    count = 0
    for entry in entries:
        ip, mac = entry.get('ip'), entry.get('mac')
        if ip and mac and is_valid_ip(ip):
            mac_normalized = mac.replace('-', ':').lower().strip()
            if re.match(r"^([0-9a-f]{2}[:]){5}([0-9a-f]{2})$", mac_normalized):
                db.update_mac(ip, mac_normalized)
                count += 1
    
    return jsonify({"success": True, "message": f"{count} endereços MAC importados."}) if count > 0 else (jsonify({"success": False, "message": "Dados inválidos."}), 400)

def _harvest_macs_from_arp():
    """Lê a tabela ARP do sistema para atualizar o cache de MACs (via network_service)."""
    known_macs = db.get_known_macs()
    try:
        # --- 0. Tabela ARP do Windows (Prioridade máxima para WSL) ---
        if IS_WSL:
            app.logger.debug("WSL detectado: Coletando MACs da tabela ARP do Windows...")
            win_arp = get_windows_arp_table()
            for item in win_arp:
                ip, mac = item['ip'], item['mac']
                if mac and mac != "00:00:00:00:00:00" and known_macs.get(ip) != mac:
                    db.update_mac(ip, mac)

        # --- 1. Varredura Proativa (Deep ARP Scan) ---
        # Tenta usar o arp-scan para forçar a descoberta de MACs de máquinas que ignoram pings.
        arp_items = discover_ips_with_arp_scan()
        if arp_items:
            app.logger.debug(f"Deep ARP Scan: Encontrados {len(arp_items)} dispositivos.")
            for item in arp_items:
                ip, mac = item['ip'], item.get('mac')
                if mac and mac != "00:00:00:00:00:00" and known_macs.get(ip) != mac:
                    db.update_mac(ip, mac)

        # --- 2. Coleta Reativa (Fallback) ---
        if os.path.exists('/proc/net/arp'):
            app.logger.debug("Tentando coletar MACs de /proc/net/arp (Linux)...")
            with open('/proc/net/arp', 'r') as f:
                next(f) # Pula cabeçalho
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4:
                        ip, mac = parts[0], parts[3]
                        if mac != "00:00:00:00:00:00" and mac != "ff:ff:ff:ff:ff:ff" and known_macs.get(ip) != mac:
                            db.update_mac(ip, mac)
                            app.logger.debug(f"ARP (Linux) - MAC {mac} para IP {ip} atualizado/adicionado.")
        
        cmd = ['arp', '-a']
        app.logger.debug(f"Tentando coletar MACs via '{' '.join(cmd)}'...")
        result = subprocess.run(cmd, capture_output=True, text=True, errors='ignore')
        for line in result.stdout.splitlines():
            match = re.search(r'(\d{1,3}(?:\.\d{1,3}){3}).*?(([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2})', line)
            if match:
                ip, mac = match.group(1), match.group(2).replace('-', ':').lower()
                if mac != "00:00:00:00:00:00" and known_macs.get(ip) != mac:
                    db.update_mac(ip, mac)
                    app.logger.debug(f"ARP (Windows/Generic) - MAC {mac} para IP {ip} atualizado/adicionado.")
    except Exception as e:
        app.logger.error(f"Erro ao coletar MACs da tabela ARP: {e}", exc_info=True)

# --- Lógica de Varredura em Background ---
def run_background_scan(custom_range):
    global is_scan_running, cached_scan_result
    with scan_lock:
        if is_scan_running:
            return
        is_scan_running = True

    try:
        ip_prefix, _, _, server_ip, gateway_ip = get_local_ip_and_range(app.logger)
        
        if custom_range:
            parts = custom_range.replace('x', '0').split('/')[0].split('.')
            if len(parts) >= 3:
                ip_prefix = ".".join(parts[:3]) + "."
        
        scanner = NetworkScanner(app.logger)
        active_ips = scanner.scan(custom_range) or []

        # Determinamos os limites numéricos (bounds) para filtragem
        low_bound, high_bound = IP_START, IP_END
        if custom_range and ' a ' in custom_range:
            try:
                r_parts = custom_range.split(' a ')
                low_bound = int(r_parts[0].split('.')[-1])
                high_bound = int(r_parts[1].split('.')[-1])
            except (ValueError, IndexError):
                pass

        # Aplica a filtragem de prefixo e range numérico em todos os casos
        if active_ips:
            active_ips = [
                item for item in active_ips 
                if is_valid_ip(item['ip']) and
                item['ip'].startswith(ip_prefix) and
                low_bound <= int(item['ip'].split('.')[-1]) <= high_bound
            ]

        ip_blocklist = db.get_blocklist()
        comprehensive_exclusion_list = set(IP_EXCLUSION_LIST) | ip_blocklist
        if server_ip: comprehensive_exclusion_list.add(server_ip)
        if gateway_ip: comprehensive_exclusion_list.add(gateway_ip)

        active_ips = [item for item in active_ips if item['ip'] not in comprehensive_exclusion_list]
        
        _harvest_macs_from_arp()
        known_macs = db.get_known_macs()
        online_ips_set = {item['ip'] for item in active_ips}
        
        for ip in known_macs.keys():
            if ip not in online_ips_set and ip not in comprehensive_exclusion_list:
                # Agora validamos o prefixo E os limites numéricos para os IPs offline
                if ip.startswith(ip_prefix):
                    try:
                        last_octet = int(ip.split('.')[-1])
                        if low_bound <= last_octet <= high_bound:
                            active_ips.append({'ip': ip, 'type': 'offline'})
                    except ValueError: continue

        # Adiciona o endereço MAC conhecido para cada item retornado
        for item in active_ips:
            item['mac'] = known_macs.get(item['ip'])

        if active_ips:
            active_ips.sort(key=lambda item: ipaddress.ip_address(item['ip']))

        result = {
            "ips": active_ips,
            "range": f"{ip_prefix}x",
            "server_ip": server_ip,
            "detection_failed": server_ip is None
        }
        
        # Salva em memória e arquivo de cache
        cached_scan_result = result
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(result, f)
        except Exception as e:
            app.logger.error(f"Erro ao salvar arquivo de cache: {e}")

        # Broadcast via WebSocket
        broadcast_ws_message({
            "type": "ip_list",
            "ips": active_ips,
            "range": f"{ip_prefix}x",
            "server_ip": server_ip,
            "detection_failed": server_ip is None
        })

    except Exception as e:
        app.logger.error(f"Erro crítico na varredura em segundo plano: {e}", exc_info=True)
    finally:
        with scan_lock:
            is_scan_running = False

# --- Rota para Descobrir IPs ---
@app.route('/discover-ips', methods=['POST'])
@require_admin
def discover_ips():
    """
    Retorna o cache atual instantaneamente e inicia uma nova varredura em background.
    """
    try:
        data = request.get_json() or {}
        custom_range = data.get('custom_range')

        # Dispara varredura real em segundo plano
        threading.Thread(target=run_background_scan, args=(custom_range,), daemon=True).start()

        if cached_scan_result:
            return jsonify({
                "success": True, 
                "ips": cached_scan_result.get("ips", []), 
                "range": cached_scan_result.get("range", ""),
                "server_ip": cached_scan_result.get("server_ip", None),
                "detection_failed": cached_scan_result.get("detection_failed", False),
                "is_cached": True
            }), 200

        return jsonify({
            "success": True, 
            "ips": [], 
            "range": "",
            "server_ip": None,
            "detection_failed": False,
            "is_cached": False,
            "message": "Nenhum cache encontrado. Busca iniciada."
        }), 200

    except Exception as e:
        app.logger.error(f"Erro crítico na descoberta de IPs: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Erro interno: {e}"}), 500

@app.route('/discover-slow-nics', methods=['POST'])
@require_admin
def discover_slow_nics():
    """
    Escaneia a rede, descobre dispositivos ativos e filtra aqueles
    cuja velocidade de interface (NIC speed) seja menor que 1000 Mbps.
    """
    try:
        data = request.get_json() or {}
        custom_range = data.get('custom_range')
        password = get_request_password(data)
        
        # 1. Escaneia a rede para encontrar IPs online
        ip_prefix, _, _, server_ip, gateway_ip = get_local_ip_and_range(app.logger)
        app.logger.info(f"Iniciando varredura para NIC speed. Gateway: {gateway_ip}")

        if custom_range:
            parts = custom_range.replace('x', '0').split('/')[0].split('.')
            if len(parts) >= 3:
                ip_prefix = ".".join(parts[:3]) + "."
        
        scanner = NetworkScanner(app.logger)
        active_ips = scanner.scan(custom_range) or []

        # Filtros de limites
        low_bound, high_bound = IP_START, IP_END
        if custom_range and ' a ' in custom_range:
            try:
                r_parts = custom_range.split(' a ')
                low_bound = int(r_parts[0].split('.')[-1])
                high_bound = int(r_parts[1].split('.')[-1])
            except (ValueError, IndexError):
                pass

        if active_ips:
            active_ips = [
                item for item in active_ips 
                if is_valid_ip(item['ip']) and
                item['ip'].startswith(ip_prefix) and
                low_bound <= int(item['ip'].split('.')[-1]) <= high_bound
            ]

        # Evita escanear o próprio servidor, gateway ou blocklist
        ip_blocklist = db.get_blocklist()
        comprehensive_exclusion_list = set(IP_EXCLUSION_LIST) | ip_blocklist
        if server_ip: comprehensive_exclusion_list.add(server_ip)
        if gateway_ip: comprehensive_exclusion_list.add(gateway_ip)

        active_ips = [item for item in active_ips if item['ip'] not in comprehensive_exclusion_list]
        
        # Coleta MACs conhecidos
        _harvest_macs_from_arp()
        known_macs = db.get_known_macs()

        slow_devices = []
        total_scanned = len(active_ips)

        def check_device_speed(item):
            ip = item['ip']
            mac = item.get('mac') or known_macs.get(ip)
            
            # Se não for tipo 'ssh' ou a porta 22 estiver fechada, não conseguiremos rodar o comando
            if item.get('type') != 'ssh':
                # Faz verificação rápida se a porta 22 está aberta de qualquer forma
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                try:
                    if sock.connect_ex((ip, 22)) != 0:
                        return None
                except Exception:
                    return None
                finally:
                    sock.close()

            try:
                with ssh_connect(ip, SSH_USER, password, app.logger, auto_fix_key=True) as ssh:
                    iface, speed_mbps = get_remote_nic_speed(ssh, password, app.logger)
                    if speed_mbps is not None and speed_mbps < 1000.0:
                        return {
                            "ip": ip,
                            "mac": mac,
                            "iface": iface,
                            "speed_mbps": speed_mbps,
                            "status": "online"
                        }
            except Exception as e:
                app.logger.warning(f"Falha ao conectar ou ler velocidade da NIC em {ip}: {e}")
            return None

        # Executa em paralelo para evitar lentidão extrema
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = [executor.submit(check_device_speed, item) for item in active_ips]
            for future in as_completed(futures):
                res = future.result()
                if res:
                    slow_devices.append(res)

        # Ordena pelo IP
        if slow_devices:
            slow_devices.sort(key=lambda item: ipaddress.ip_address(item['ip']))

        app.logger.info(f"NIC speed scan concluído. {len(slow_devices)} dispositivos lentos encontrados de {total_scanned} escaneados.")
        
        return jsonify({
            "success": True,
            "ips": slow_devices,
            "total_scanned": total_scanned,
            "slow_count": len(slow_devices)
        }), 200

    except Exception as e:
        app.logger.error(f"Erro crítico no escaneamento de velocidades de rede: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Erro interno: {e}"}), 500

@app.route('/block-ip', methods=['POST'])
@require_admin
def block_ip():
    """Adiciona um IP à blocklist permanente e o remove do cache de MACs."""
    data = request.get_json()
    ip_to_block = data.get('ip')

    if not ip_to_block:
        return jsonify({"success": False, "message": "Nenhum IP fornecido."}), 400

    # Adiciona à blocklist no banco de dados
    db.set_blocked(ip_to_block, True)
    # Remove o MAC conhecido para este IP (opcional, dependendo da sua política de limpeza)
    db.update_mac(ip_to_block, None)
    
    app.logger.info(f"IP {ip_to_block} adicionado à blocklist e removido do cache.")
    return jsonify({"success": True, "message": f"IP {ip_to_block} foi bloqueado e não aparecerá mais."})

@app.route('/get-blocklist', methods=['GET'])
@require_admin
def get_blocklist():
    """Retorna a lista de IPs atualmente na blocklist."""
    ip_blocklist = db.get_blocklist()
    return jsonify({"success": True, "blocklist": sorted(list(ip_blocklist))})

@app.route('/unblock-ip', methods=['POST'])
@require_admin
def unblock_ip():
    """Remove um IP da blocklist permanente."""
    data = request.get_json()
    ip_to_unblock = data.get('ip')

    if not ip_to_unblock:
        return jsonify({"success": False, "message": "Nenhum IP fornecido."}), 400

    db.set_blocked(ip_to_unblock, False)
    app.logger.info(f"IP {ip_to_unblock} removido da blocklist.")
    return jsonify({"success": True, "message": f"IP {ip_to_unblock} foi desbloqueado."})

@app.route('/get-aliases', methods=['GET'])
@require_admin
def get_aliases():
    """Retorna todos os apelidos configurados."""
    aliases = db.get_aliases()
    return jsonify({"success": True, "aliases": aliases})

@app.route('/set-alias', methods=['POST'])
@require_admin
def set_alias():
    """Define ou remove um apelido para um IP."""
    data = request.get_json()
    ip = data.get('ip')
    alias = data.get('alias')

    if not ip:
        return jsonify({"success": False, "message": "IP é obrigatório."}), 400

    db.update_alias(ip, alias.strip() if alias else None)
    return jsonify({"success": True, "message": "Apelido atualizado."})

@app.route('/set-mac', methods=['POST'])
@require_admin
def set_mac():
    """Define manualmente um endereço MAC para um IP."""
    data = request.get_json()
    ip = data.get('ip')
    mac = data.get('mac')
    if not ip or not mac or not is_valid_ip(ip):
        return jsonify({"success": False, "message": "Dados inválidos."}), 400
    
    mac_normalized = mac.replace('-', ':').lower().strip()
    if not re.match(r"^([0-9a-f]{2}[:]){5}([0-9a-f]{2})$", mac_normalized):
        return jsonify({"success": False, "message": "Formato de MAC inválido (ex: AA:BB:CC:DD:EE:FF)."}), 400

    db.update_mac(ip, mac_normalized)
    return jsonify({"success": True, "message": f"Endereço MAC para {ip} atualizado."})

@app.route('/api/metadata', methods=['GET'])
def get_metadata():
    """Retorna os metadados das ações para o frontend configurar o streaming dinamicamente."""
    version = "Desconhecida"
    branch = "Desconhecida"
    try:
        # Tenta obter a tag mais recente ou o hash do commit curto via Git
        version = subprocess.check_output(
            ['git', 'describe', '--tags', '--always'],
            stderr=subprocess.STDOUT,
            cwd=APP_ROOT
        ).decode('utf-8').strip()

        # Tenta obter o nome da branch atual
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            stderr=subprocess.STDOUT,
            cwd=APP_ROOT
        ).decode('utf-8').strip()
    except Exception:
        pass

    return jsonify({"success": True, "metadata": COMMAND_METADATA, "version": version, "branch": branch})

@app.route('/check-status', methods=['POST'])
@require_admin
def check_status():
    """
    Verifica rapidamente o status da conexão SSH para uma lista de IPs.
    """
    data = request.get_json()
    ips = data.get('ips', [])
    password = get_request_password(data)
    skip_ssh = data.get('skip_ssh', False)

    if not ips:
        return jsonify({"success": False, "message": "Nenhuma lista de IPs fornecida."}), 400

    # Filtra apenas IPs válidos para evitar erros ou injeção
    ips = [ip for ip in ips if is_valid_ip(ip)]

    statuses = {}

    def is_port_open(ip, port, timeout=1.0):
        """Verifica se uma porta está aberta usando socket puro (rápido)."""
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def check_single_ip(ip):
        """Função executada em uma thread para verificar um único IP."""
        try:
            # Usa a lógica unificada que tenta SSH e depois Ping como fallback
            host_info = check_host_online(ip)
            if not host_info:
                return ip, {'status': 'offline', 'user_count': 0}

            # Se skip_ssh for True, apenas confirmamos que a porta 22 está aberta sem logar
            if host_info['type'] == 'ssh' and not skip_ssh:
                # Usa um timeout curto para uma verificação rápida.
                with ssh_connect(ip, SSH_USER, password, app.logger, auto_fix_key=True) as ssh:
                    # Comando para obter contagem de usuários e qualidade do sinal (Wireless vs Ethernet)
                    cmd = "who | wc -l; IFACE=$(ip route | grep default | awk '{print $5}' | head -n1); [ -d /sys/class/net/$IFACE/wireless ] && awk 'NR==3 {print int($3*100/70)}' /proc/net/wireless || echo 100"
                    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=5)
                    lines = stdout.read().decode().strip().splitlines()
                    
                    user_count = int(lines[0]) if lines and lines[0].isdigit() else 1
                    signal = int(lines[1]) if len(lines) > 1 and lines[1].isdigit() else 100
                    
                    return ip, {'status': 'online', 'user_count': user_count, 'signal': signal}
            elif host_info['type'] == 'ssh' and skip_ssh:
                # Retorna online sem detalhes extras para ganhar velocidade
                return ip, {'status': 'online', 'user_count': 0}
            else:
                # Host online via Ping, mas porta 22 (SSH) fechada
                return ip, {'status': 'online', 'user_count': 0, 'type': 'ping'}

        except paramiko.AuthenticationException:
            # A máquina está online, mas a senha está errada.
            return ip, {'status': 'auth_error', 'user_count': 0}
        except Exception:
            # Qualquer outra exceção (timeout, conexão recusada) significa offline.
            return ip, {'status': 'offline', 'user_count': 0}

    # Aumentado para 50 workers para lidar com varreduras maiores de forma mais fluida
    with ThreadPoolExecutor(max_workers=50) as executor:
        future_to_ip = {executor.submit(check_single_ip, ip): ip for ip in ips}
        for future in as_completed(future_to_ip):
            ip, status = future.result()
            statuses[ip] = status

    return jsonify({"success": True, "statuses": statuses})
# --- Rota para servir o Frontend ---

@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def serve_frontend(path: str):
    """
    Serve o index.html para a rota raiz e outros arquivos estáticos (CSS, JS).
    """
    return send_from_directory(APP_ROOT, path)

@app.route('/favicon.ico')
def favicon():
    """Silencia o erro 404 para o favicon.ico, que o navegador solicita por padrão."""
    return '', 204


# --- Funções de Manipulação de Ações (Refatoradas de 'gerenciar_atalhos_ip') ---

def _handle_shell_action(ssh: paramiko.SSHClient, username: Optional[str], action: str, data: Dict[str, Any]):
    """Lida com ações que executam comandos shell."""
    ip = data.get('ip')
    password = data.get('password')
    command_builder = _get_command_builder(action)

    if not command_builder:
        app.logger.warning(f"Ação solicitada '{action}' não encontrada. Comandos carregados: {list(COMMANDS.keys())}")
        # Retorna um dicionário para consistência, a camada superior fará o jsonify.
        return {"success": False, "message": "Ação desconhecida. Tente reiniciar o servidor backend.", "details": f"A ação '{action}' não consta na lista de comandos carregados."}

    # Constrói o comando
    if callable(command_builder):
        command, error_response = command_builder(data)
        if error_response:
            return error_response # Retorna o dicionário de erro diretamente.
    else:
        command = command_builder

    # Define um timeout maior para a ação de atualização, que pode demorar.
    timeout = 300 if action == 'atualizar_sistema' else 20

    # Ações que não esperam resposta (fire-and-forget)
    fire_and_forget_actions = ['reiniciar', 'desligar']
    if action in fire_and_forget_actions:
        # Para essas ações, apenas executamos o comando sem esperar por uma saída.
        # A conexão será encerrada pelo comando de qualquer maneira.
        ssh.exec_command(command, timeout=5) # Timeout curto, apenas para enviar o comando.
        return {"success": True, "message": f"Sinal de '{action}' enviado com sucesso."}

    try:
        # Executa o comando shell. Se falhar, uma exceção CommandExecutionError será lançada.
        output, warnings, errors = _execute_shell_command(ssh, command, password, timeout=timeout, username=username)
    except CommandExecutionError as e:
        app.logger.error(f"Erro na ação '{action}' em {ip}: {e.details}")
        # Combina warnings e errors nos detalhes para um log completo no frontend.
        details = []
        # Usa os avisos da exceção, se houver.
        if e.warnings: details.append(f"Avisos: {e.warnings}")
        if e.details: details.append(f"Erros: {e.details}")
        
        # Retorna sucesso como False, mas inclui todos os detalhes.
        return {"success": False, "message": f"Ocorreu um erro no dispositivo remoto: {str(e)}", "details": "\n".join(details)}


    # Lógica especial para a ação de obter informações do sistema
    if action == 'get_system_info':
        parsed_data = _parse_system_info(output)
        return {
            "success": True,
            "message": "Informações do sistema obtidas.",
            "data": parsed_data,
            "details": warnings
        }

    # Combina avisos e erros não fatais nos detalhes
    details_list = []
    if warnings: details_list.append(f"Avisos:\n{warnings}")
    if errors: details_list.append(f"Erros não fatais:\n{errors}")
    final_details = "\n\n".join(details_list) if details_list else None

    # A operação é um sucesso mesmo com avisos.
    return {"success": True, "message": output or "Ação executada com sucesso.", "details": final_details}

def _dispatch_ssh_action(ssh, ip, action, data, logger):
    """Centraliza a lógica de despacho para evitar duplicação entre rota e agendador."""
    handler = ACTION_HANDLERS.get(action)

    if handler == _execute_for_each_user:
        return _execute_for_each_user(ssh, action, data, logger)
    elif handler == _handle_cleanup_wallpaper:
        message, _, errors = _handle_cleanup_wallpaper(ssh, data)
        return {"success": not errors, "message": message, "details": errors}
    else:
        return _handle_shell_action(ssh, None, action, data)

@app.route('/stream-action', methods=['POST'])
@require_admin
def stream_action():
    """
    Executa uma ação e transmite a saída em tempo real.
    Ideal para comandos de longa duração como 'atualizar_sistema'.
    """
    data = request.get_json()
    ip = data.get('ip')
    action = data.get('action')
    password = get_request_password(data)

    if ip and not is_valid_ip(ip):
        return Response("Endereço IP inválido.", status=400, mimetype='text/plain')

    if not all([ip, action, password]):
        return Response("IP, ação e senha são obrigatórios.", status=400, mimetype='text/plain')

    command_builder = _get_command_builder(action)
    if not command_builder:
        return Response("Ação desconhecida.", status=400, mimetype='text/plain')

    command, _ = command_builder(data)

    def generate_stream():
        try:
            with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
                # Usa a função de streaming do ssh_service
                exit_code = yield from _stream_shell_command(ssh, command, password)
                
                # Envia um marcador de finalização com o código de saída
                yield f"__STREAM_END__:{exit_code}\n"

        except Exception as e:
            app.logger.error(f"Erro de streaming na ação '{action}' em {ip}: {e}", exc_info=True)
            yield f"__STREAM_ERROR__:Erro de conexão ou execução: {str(e)}\n"

    # Retorna uma resposta de streaming. O mimetype 'text/event-stream' é comum,
    # mas 'text/plain' funciona bem para o nosso caso de uso simples.
    return Response(generate_stream(), mimetype='text/plain')

# --- Rota para Teste de Velocidade em Tempo Real ---
@app.route('/stream-speedtest', methods=['POST'])
@require_admin
def stream_speedtest():
    """
    Conecta ao dispositivo e executa o teste de velocidade de forma incremental,
    transmitindo a saída para o frontend.
    """
    data = request.get_json()
    ip = data.get('ip')
    password = get_request_password(data)

    if ip and not is_valid_ip(ip):
        return Response("Endereço IP inválido.", status=400, mimetype='text/plain')

    if not all([ip, password]):
        return Response("IP e senha são obrigatórios.", status=400, mimetype='text/plain')

    command_builder = _get_command_builder('testar_velocidade')
    if not command_builder:
        return Response("Ação de teste de velocidade indisponível.", status=400, mimetype='text/plain')

    command, _ = command_builder({'ip': ip, 'password': password})

    def generate_stream():
        try:
            with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
                exit_code = yield from _stream_shell_command(ssh, command, password)
                yield f"__STREAM_END__:{exit_code}\n"
        except Exception as e:
            app.logger.error(f"Erro no teste de velocidade para {ip}: {e}", exc_info=True)
            yield f"__STREAM_ERROR__:Erro de conexão ou execução: {str(e)}\n"

    return Response(generate_stream(), mimetype='text/plain')

# --- Rota para Listar Backups de Atalhos ---
@app.route('/list-backups', methods=['POST'])
@require_admin
def list_backups():
    """
    Conecta a um IP e lista os diretórios de backup de atalhos disponíveis.
    """
    data = request.get_json()
    ip = data.get('ip')
    password = get_request_password(data)

    if not all([ip, password]):
        return jsonify({"success": False, "message": "IP e senha são obrigatórios."}), 400

    with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
        backups_by_dir = list_sftp_backups(ssh, BACKUP_ROOT_DIR)
        return jsonify({"success": True, "backups": backups_by_dir}), 200

# --- Dicionário de Manipuladores de Ação (Action Dispatcher) ---
# Este dicionário centraliza o roteamento de ações, tornando o código mais limpo e extensível.
# Cada entrada mapeia uma 'action' (string) para a função que deve manipulá-la.
ACTION_HANDLERS = {
    # Ações que são executadas para cada usuário na máquina remota
    'desativar': _execute_for_each_user,
    'ativar': _execute_for_each_user,
    'mostrar_sistema': _execute_for_each_user,
    'ocultar_sistema': _execute_for_each_user,
    'limpar_imagens': _execute_for_each_user,
    'desativar_barra_tarefas': _execute_for_each_user,
    'ativar_barra_tarefas': _execute_for_each_user,
    'bloquear_barra_tarefas': _execute_for_each_user,
    'desbloquear_barra_tarefas': _execute_for_each_user,
    'definir_firefox_padrao': _execute_for_each_user,
    'definir_chrome_padrao': _execute_for_each_user,
    'desativar_perifericos': _execute_for_each_user,
    'ativar_perifericos': _execute_for_each_user,
    'desativar_botao_direito': _execute_for_each_user,
    'ativar_botao_direito': _execute_for_each_user,
    'enviar_mensagem': _execute_for_each_user,
    'definir_papel_de_parede': _execute_for_each_user,
    'instalar_scratchjr': _execute_for_each_user,
    'remover_todos_bloqueios': _execute_for_each_user,
    'cleanup_wallpaper': _handle_cleanup_wallpaper, # Ação por máquina, não por usuário
}

# --- Rota Principal para Gerenciar Ações via SSH ---
@app.route('/gerenciar_atalhos_ip', methods=['POST'])
@require_admin
def gerenciar_atalhos_ip():
    """
    Recebe as informações do frontend, conecta via SSH e despacha a ação apropriada.
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Requisição inválida."}), 400

    # Processa o IP para verificar se há uma flag de usuário (ex: 192.168.0.10/aluno1)
    raw_ip = data.get('ip')
    ip = raw_ip
    
    if raw_ip and '/' in raw_ip:
        parts = raw_ip.split('/', 1)
        ip = parts[0].strip()
        target_user_suffix = parts[1].strip()
        # Define o target_user no payload, que será usado pelo ssh_service
        if target_user_suffix:
            data['target_user'] = target_user_suffix
            # Atualiza o IP limpo no dicionário para evitar erros de conexão
            data['ip'] = ip

    action = data.get('action')
    password = get_request_password(data)

    if ip and not is_valid_ip(ip):
        return jsonify({"success": False, "message": "Endereço IP inválido."}), 400

    if not all([ip, action, password]):
        return jsonify({"success": False, "message": "IP, ação e senha são obrigatórios."}), 400
    
    # Ação de Wake-on-LAN (Ligar) - Ação local que não requer SSH
    if action == 'wake_on_lan' or action == 'ligar':
        known_macs = db.get_known_macs()
        mac = known_macs.get(ip)
        db.add_audit_log(request.remote_addr, action, [ip], "enviado")
        if not mac:
            return jsonify({"success": False, "message": f"Endereço MAC não encontrado para {ip}. Ligue a máquina manualmente uma vez para que o sistema aprenda o MAC."}), 404
        
        if send_wake_on_lan(mac, app.logger):
            return jsonify({"success": True, "message": f"Comando Wake-on-LAN enviado para {ip} ({mac})."}), 200
        else:
            return jsonify({"success": False, "message": "Falha ao enviar o pacote Wake-on-LAN."}), 500

    # Ações locais que não precisam de IP ou conexão SSH são tratadas primeiro.
    if action == 'backup_aplicacao':
        # Chama a função de backup diretamente e retorna o resultado.
        return backup_application()
    
    # Verifica se a ação é de streaming via metadados
    streaming_actions = [k for k, v in COMMAND_METADATA.items() if v.get('is_streaming')]
    if action in streaming_actions:
        # O frontend deve chamar a rota /stream-action para essas ações.
        return jsonify({"success": False, "message": "Ação de streaming deve ser chamada via /stream-action."}), 400

    # Passa a função de manipulação de shell para o payload para evitar importação circular.
    data['shell_action_handler'] = _handle_shell_action

    try:
        with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
            result = _dispatch_ssh_action(ssh, ip, action, data, app.logger)
            
            # Determinação do Status Code baseada no resultado unificado
            if result.get('user_results'): # É Multi-Status do _execute_for_each_user
                status_code = 200 if result.get('success') else 207
            else:
                if not result.get('success'):
                    # Retorna 400 (Bad Request) se a ação for desconhecida, para diferenciar de erro de servidor (500)
                    status_code = 400 if "Ação desconhecida" in result.get('message', '') else 500
                else:
                    status_code = 200
                
            return jsonify(result), status_code

    except CommandExecutionError as e:
        app.logger.error(f"Erro de execução de comando remoto na ação '{action}' em {ip}: {e.details}")
        details = []
        if e.warnings: details.append(f"Avisos: {e.warnings}")
        if e.details: details.append(f"Erros: {e.details}")
        return jsonify({
            "success": False,
            "message": f"Erro de execução no dispositivo remoto: {str(e)}",
            "details": "\n".join(details) if details else None
        }), 400
    except (paramiko.SSHException, socket.error) as e:
        # Captura todas as exceções de SSH e de socket (como timeouts de conexão)
        # e as delega para o manipulador de exceções padronizado.
        response, status_code = _handle_ssh_exception(e, ip, action, app.logger)
        return jsonify(response), status_code
    except Exception as e:
        # Captura qualquer outro erro inesperado para evitar que o servidor trave.
        app.logger.error(f"Erro inesperado e não tratado na rota /gerenciar_atalhos_ip: {e}", exc_info=True)
        return jsonify({
            "success": False, 
            "message": "Ocorreu um erro interno inesperado no servidor.",
            "details": str(e) if app.debug else None
        }), 500

@app.route('/backup-application', methods=['POST'])
@require_admin
def backup_application():
    """
    Cria um backup .zip do diretório da aplicação, excluindo arquivos desnecessários.
    Esta é uma ação local, executada no servidor onde o backend está rodando.
    """
    # Importa a biblioteca zipfile apenas quando necessário.
    import zipfile

    try:
        # Diretório raiz do projeto.
        source_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Diretório onde os backups serão salvos.
        backup_parent_dir = os.path.join(source_dir, 'backups_app')
        os.makedirs(backup_parent_dir, exist_ok=True)

        # Nome do arquivo de backup com data e hora.
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        archive_name = f'backup_app_{timestamp}.zip'
        archive_path = os.path.join(backup_parent_dir, archive_name)

        # Lista explícita de arquivos e pastas a serem incluídos no backup.
        # Isso é mais seguro e previsível do que incluir tudo e excluir alguns.
        files_to_backup = [
            'index.html', 'style.css', 'script.js',
            'app.py', 'command_builder.py', 'ssh_service.py', # Inclui os módulos Python
            'actions.sh',
        ]

        # Cria o arquivo .zip e adiciona os arquivos/pastas.
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for item in files_to_backup:
                item_path = os.path.join(source_dir, item)
                if os.path.exists(item_path):
                    if os.path.isdir(item_path):
                        # Adiciona uma pasta e todo o seu conteúdo recursivamente.
                        for root, _, files in os.walk(item_path):
                            for file in files:
                                file_path = os.path.join(root, file)
                                # O segundo argumento (arcname) define o caminho relativo dentro do zip.
                                arcname = os.path.relpath(file_path, source_dir)
                                zipf.write(file_path, arcname)
                    else:
                        # Adiciona um arquivo único.
                        zipf.write(item_path, item)
                else:
                    app.logger.warning(f"Item de backup não encontrado e ignorado: {item_path}")
        
        app.logger.info(f"Backup da aplicação criado com sucesso em: {archive_path}")
        return jsonify({'success': True, 'message': 'Backup da aplicação criado com sucesso.', 'path': archive_path})

    except Exception as e:
        # Loga o erro completo para depuração.
        app.logger.error(f"Erro ao criar backup da aplicação com zipfile: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Falha ao criar o backup: {e}'}), 500

@app.route('/list-application-backups', methods=['GET'])
@require_admin
def list_application_backups():
    """
    Lista os arquivos de backup da aplicação (.zip) encontrados no diretório 'backups_app'.
    """
    try:
        source_dir = os.path.dirname(os.path.abspath(__file__))
        backup_dir = os.path.join(source_dir, 'backups_app')

        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir, exist_ok=True)
            app.logger.info(f"Pasta de backups da aplicação criada em: {backup_dir}")
            return jsonify({'success': True, 'backups': [], 'message': 'Pasta de backups criada. Nenhum arquivo encontrado.'})

        if not os.path.isdir(backup_dir):
            return jsonify({'success': True, 'backups': [], 'message': 'Diretório de backups da aplicação ainda não foi criado.'})

        # Lista todos os arquivos .zip no diretório
        backups = [f for f in os.listdir(backup_dir) if f.endswith('.zip')]
        
        # Ordena os backups do mais recente para o mais antigo com base no nome do arquivo
        backups.sort(reverse=True)

        return jsonify({'success': True, 'backups': backups})

    except Exception as e:
        app.logger.error(f"Erro ao listar backups da aplicação: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Falha ao listar backups: {e}'}), 500

@app.route('/restore-application-backup', methods=['POST'])
@require_admin
def restore_application_backup():
    """
    Restaura a aplicação a partir de um arquivo de backup selecionado e reinicia o servidor.
    """
    import zipfile
    data = request.get_json()
    backup_filename = data.get('backup_file')

    if not backup_filename:
        return jsonify({'success': False, 'message': 'Nome do arquivo de backup não fornecido.'}), 400

    try:
        source_dir = os.path.dirname(os.path.abspath(__file__))
        backup_dir = os.path.join(source_dir, 'backups_app')
        backup_path = Path(backup_dir).joinpath(backup_filename).resolve()

        # Prevenção contra Path Traversal (Igual à rota de delete)
        if not backup_path.is_relative_to(Path(backup_dir).resolve()):
            app.logger.warning(f"Tentativa de Path Traversal bloqueada no restauro! Arquivo: {backup_filename}")
            return jsonify({'success': False, 'message': 'Acesso negado.'}), 403

        if not backup_path.is_file():
            app.logger.error(f"Falha na restauração: Arquivo de backup '{backup_filename}' não encontrado no disco.")
            return jsonify({'success': False, 'message': 'Arquivo de backup não encontrado.'}), 404

        # Extrai o conteúdo do backup para o diretório raiz da aplicação, sobrescrevendo arquivos existentes.
        with zipfile.ZipFile(backup_path, 'r') as zipf:
            zipf.extractall(path=source_dir)

        app.logger.info(f"Aplicação restaurada com sucesso a partir de {backup_filename}. Reiniciando o servidor...")

        # Função para reiniciar o servidor após um pequeno atraso
        def do_restart():
            time.sleep(2) # Aguarda para garantir que a resposta HTTP seja enviada
            os.kill(os.getpid(), signal.SIGINT) # Envia um sinal de interrupção para o processo principal

        threading.Thread(target=do_restart).start()

        return jsonify({'success': True, 'message': 'Aplicação restaurada. O servidor será reiniciado.'})

    except Exception as e:
        app.logger.error(f"Erro ao restaurar backup da aplicação: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Falha ao restaurar o backup: {e}'}), 500

@app.route('/delete-application-backup', methods=['POST'])
@require_admin
def delete_application_backup():
    """
    Exclui um arquivo de backup da aplicação do servidor.
    """
    data = request.get_json()
    backup_filename = data.get('backup_file')

    if not backup_filename:
        return jsonify({'success': False, 'message': 'Nome do arquivo de backup não fornecido.'}), 400

    try:
        backup_dir = Path(APP_ROOT) / 'backups_app'
        backup_path = (backup_dir / backup_filename).resolve()

        # Prevenção robusta contra Path Traversal
        if not backup_path.is_relative_to(backup_dir.resolve()):
             app.logger.warning(f"Tentativa de Path Traversal bloqueada! Arquivo: {backup_filename} | IP Origem: {request.remote_addr}")
             return jsonify({'success': False, 'message': 'Acesso negado.'}), 403

        if not backup_path.exists():
            app.logger.error(f"Tentativa de exclusão falhou: Backup '{backup_filename}' não existe.")
            return jsonify({'success': False, 'message': 'Arquivo de backup não encontrado.'}), 404

        backup_path.unlink()
        app.logger.info(f"Backup da aplicação excluído com sucesso: {backup_filename}")
        return jsonify({'success': True, 'message': 'Backup excluído com sucesso.'})

    except Exception as e:
        app.logger.error(f"Erro ao excluir backup da aplicação: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Falha ao excluir o backup: {e}'}), 500

# --- Rota para Corrigir Chaves SSH ---
@app.route('/fix-ssh-keys', methods=['POST'])
@require_admin
def fix_ssh_keys():
    """
    Remove as chaves de host SSH antigas do arquivo known_hosts do servidor.
    """
    data = request.get_json()
    ips_to_fix = data.get('ips')

    if not ips_to_fix or not isinstance(ips_to_fix, list):
        return jsonify({"success": False, "message": "Lista de IPs é obrigatória."}), 400

    results = {}
    for ip in ips_to_fix:
        try:
            # O comando ssh-keygen -R remove a chave do known_hosts.
            # Não precisa de sudo, pois opera no arquivo do usuário que está rodando o backend.
            command = ["ssh-keygen", "-R", ip]
            # Usamos um timeout para evitar que o processo trave.
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)

            if result.returncode == 0:
                # A saída padrão de sucesso do ssh-keygen é útil.
                results[ip] = {"success": True, "message": result.stdout.strip().replace('\n', ' ')}
            else:
                # A saída de erro também é importante.
                results[ip] = {"success": False, "message": result.stderr.strip().replace('\n', ' ')}
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            error_message = f"Erro ao executar ssh-keygen para {ip}: {e}"
            app.logger.error(error_message)
            results[ip] = {"success": False, "message": error_message}

    all_success = all(r['success'] for r in results.values())
    return jsonify({"success": all_success, "results": results}), 200

@app.route('/shutdown', methods=['POST'])
@require_admin
def shutdown():
    """
    Encerra o servidor Flask de forma segura.
    Por segurança, esta rota só pode ser acessada a partir da própria máquina (localhost).
    """
    # Medida de segurança: apenas permite o desligamento se a requisição vier de 127.0.0.1
    if request.remote_addr != '127.0.0.1':
        app.logger.warning(f"Tentativa de desligamento não autorizada do IP: {request.remote_addr}")
        return jsonify({"success": False, "message": "Acesso negado."}), 403

    def do_shutdown():
        # Aguarda um segundo para garantir que a resposta HTTP seja enviada ao cliente.
        time.sleep(1)
        # Envia o sinal SIGINT para o processo atual, simulando um Ctrl+C.
        # Isso permite que o servidor (Waitress ou Flask dev) encerre de forma limpa.
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=do_shutdown).start()
    return jsonify({"success": True, "message": "O servidor será encerrado em breve."})

# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    # Configurações do servidor
    HOST = "0.0.0.0"
    PORT = 5000
    # Use o modo de desenvolvimento para abrir o navegador automaticamente
    # Defina a variável de ambiente DEV_MODE=true para ativar
    DEV_MODE = os.getenv("DEV_MODE", "false").lower() in ("true", "1", "t")

    print(f"DEBUG: DEV_MODE (env var check) is {DEV_MODE}")
    def open_browser():
        """Abre o navegador padrão na URL da aplicação."""
        webbrowser.open_new(f'http://127.0.0.1:{PORT}/')

    if DEV_MODE:
        # Em modo de desenvolvimento, usa o servidor do Flask com debug e reloader ativados.
        # Isso recarrega o servidor automaticamente quando o código é alterado.
        print(f"--> Servidor de desenvolvimento iniciado em http://{HOST}:{PORT}")
        print("--> O servidor irá recarregar automaticamente após alterações no código.")
        print("--> Pressione Ctrl+C para encerrar.")
        # A verificação 'WERKZEUG_RUN_MAIN' impede que o navegador seja aberto duas vezes
        # quando o reloader do Flask está ativo.
        if not os.environ.get('WERKZEUG_RUN_MAIN'):
            threading.Timer(1.5, open_browser).start()
            start_scheduler()
        print("----------------------------------------\n")

        # O Reloader é desativado para evitar loops infinitos.
        # Como a aplicação grava logs e o banco de dados SQLite no próprio diretório raiz,
        # o monitor de arquivos do Flask interpretaria essas gravações como mudanças no código,
        # reiniciando o servidor continuamente.
        should_reload = False 
        
        print(f"DEBUG: Chamando app.run(). Host={HOST}, Port={PORT}, Reloader={should_reload}")
        try:
            app.run(host=HOST, port=PORT, debug=True, use_reloader=should_reload)
        except Exception as e:
            print(f"ERRO CRÍTICO: app.run() falhou com exceção: {e}", flush=True)
    else:
        # Aumentamos o número de threads para evitar que scans de rede ocupem todos os slots
        THREADS = 32
        print(f"--> Servidor de produção (Waitress) iniciado em http://{HOST}:{PORT} com {THREADS} threads.")
        print("--> Pressione Ctrl+C para encerrar.")
        start_scheduler()
        print("----------------------------------------\n")
        try:
            # connection_limit evita que o SO negue conexões se houver muitos requests simultâneos
            serve(app, host=HOST, port=PORT, threads=THREADS, connection_limit=100, channel_timeout=30)
        except Exception as e:
            print(f"ERRO CRÍTICO: serve() (Waitress) falhou com exceção: {e}", flush=True)
    print("DEBUG: app.py está encerrando.")
