import os
import platform
import subprocess
import shutil

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
import ipaddress
import threading

# Configura limite de tamanho de stack por thread para 512 KB (padrão Linux é 8 MB)
# Evita consumo excessivo de memória virtual quando dezenas de conexões SSH/VNC são abertas
try:
    threading.stack_size(512 * 1024)
except Exception:
    pass

import re
import shlex
from pathlib import Path
import time
from datetime import datetime
import webbrowser
import signal
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import sqlite3
from multiprocessing import Pool, cpu_count
import json
import logging
from logging.handlers import RotatingFileHandler
import binascii

from flask import Flask, jsonify, request, send_from_directory, Response, Blueprint
from flask_socketio import SocketIO, emit, disconnect

import paramiko
from flask_cors import CORS
from waitress import serve

# --- Importações dos Módulos de Serviço Refatorados ---
from command_builder import COMMANDS, COMMAND_METADATA, _get_command_builder, CommandExecutionError, _parse_system_info
from ssh_service import ssh_connect, prune_ssh_cache, warm_up_ssh_pool, _handle_ssh_exception, _execute_for_each_user, _execute_shell_command, _stream_shell_command, list_sftp_backups, _handle_cleanup_wallpaper
from network_service import NetworkScanner, get_local_ip_and_range, is_valid_ip, check_host_online, send_wake_on_lan, send_batch_wake_on_lan, get_windows_arp_table, discover_ips_with_arp_scan, resolve_remote_hostname, clear_dns_cache, IS_WSL
from vnc_service import ensure_remote_vnc_server, stop_websockify_proxy, get_remote_screenshot
from schedule_service import ClassScheduleManager


# --- Configuração da Aplicação Flask & SocketIO ---
app = Flask(__name__)
# Permite requisições de diferentes origens com suporte a métodos específicos e headers
CORS(app, resources={r"/*": {
    "origins": "*", 
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', logger=False, engineio_logger=False, ping_interval=25, ping_timeout=60, permessage_deflate=True)

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

@app.after_request
def add_no_cache_headers(response):
    if request.path.endswith('.js') or request.path.endswith('.css') or request.path == '/' or request.path.endswith('.html'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

FORCE_STATIC_RANGE = os.getenv("FORCE_STATIC_RANGE", "false").lower() == "true"
IP_PREFIX = os.getenv("IP_PREFIX", "192.168.50.")
IP_START = int(os.getenv("IP_START", "1"))
IP_END = int(os.getenv("IP_END", "254"))
IP_EXCLUSION_LIST = os.getenv("IP_EXCLUSION_LIST", "").split(",") if os.getenv("IP_EXCLUSION_LIST") else []
SSH_USER = os.getenv("SSH_USER", "aluno")
BACKUP_ROOT_DIR = "atalhos_desativados"
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "qwe123")

def get_request_password(data: Dict) -> str:
    """Extrai a senha da requisição ou retorna a senha padrão."""
    if not data:
        return DEFAULT_PASSWORD
    return data.get('password') or DEFAULT_PASSWORD

class DatabaseManager:
    """Gerencia a persistência em SQLite com foco em integridade e concorrência."""
    def __init__(self, root_path):
        self.db_path = Path(root_path) / 'app_data.db'
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Usa journal_mode=DELETE para compatibilidade com OneDrive/WSL
            # (WAL cria arquivos -shm/-wal que causam disk I/O errors nestes filesystems)
            try:
                conn.execute("PRAGMA journal_mode=DELETE")
            except sqlite3.OperationalError:
                pass
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS frequent_ip_ranges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    range_start TEXT,
                    range_end TEXT,
                    range_str TEXT UNIQUE,
                    usage_count INTEGER DEFAULT 1,
                    last_used DATETIME DEFAULT CURRENT_TIMESTAMP
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
            try:
                conn.execute("ALTER TABLE devices ADD COLUMN hostname TEXT")
            except sqlite3.OperationalError: pass
            try:
                conn.execute("ALTER TABLE devices ADD COLUMN group_name TEXT")
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
            return {row[0]: row[1] for row in cursor if row[1]}

    def update_alias(self, ip, alias):
        with sqlite3.connect(self.db_path) as conn:
            if not alias:
                conn.execute("UPDATE devices SET alias = NULL WHERE ip = ?", (ip,))
            else:
                conn.execute("INSERT INTO devices (ip, alias) VALUES (?, ?) ON CONFLICT(ip) DO UPDATE SET alias=excluded.alias", (ip, alias))

    def get_hostnames(self) -> Dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT ip, hostname FROM devices WHERE hostname IS NOT NULL")
            return {row[0]: row[1] for row in cursor if row[1]}

    def update_hostname(self, ip, hostname):
        with sqlite3.connect(self.db_path) as conn:
            if not hostname:
                conn.execute("UPDATE devices SET hostname = NULL WHERE ip = ?", (ip,))
            else:
                conn.execute("INSERT INTO devices (ip, hostname) VALUES (?, ?) ON CONFLICT(ip) DO UPDATE SET hostname=excluded.hostname", (ip, hostname))

    def get_all_devices_metadata(self) -> Dict[str, Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT ip, mac, alias, hostname, is_blocked, group_name FROM devices")
            res = {}
            for row in cursor.fetchall():
                d = dict(row)
                res[d['ip']] = d
            return res

    def get_all_devices(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT ip, mac, alias, hostname, is_blocked, group_name FROM devices")
            return [dict(row) for row in cursor.fetchall()]

    def update_group(self, ip: str, group_name: Optional[str]):
        with sqlite3.connect(self.db_path) as conn:
            grp = group_name.strip() if group_name and group_name.strip() else None
            conn.execute("INSERT INTO devices (ip, group_name) VALUES (?, ?) ON CONFLICT(ip) DO UPDATE SET group_name=excluded.group_name", (ip, grp))

    def batch_update_groups(self, ips: List[str], group_name: Optional[str]):
        with sqlite3.connect(self.db_path) as conn:
            grp = group_name.strip() if group_name and group_name.strip() else None
            for ip in ips:
                conn.execute("INSERT INTO devices (ip, group_name) VALUES (?, ?) ON CONFLICT(ip) DO UPDATE SET group_name=excluded.group_name", (ip, grp))

    def get_groups_summary(self) -> Dict[str, List[str]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT ip, group_name FROM devices WHERE group_name IS NOT NULL AND group_name != ''")
            groups: Dict[str, List[str]] = {}
            for ip, grp in cursor.fetchall():
                groups.setdefault(grp, []).append(ip)
            return groups

    def delete_group(self, group_name: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("UPDATE devices SET group_name = NULL WHERE group_name = ?", (group_name.strip(),))
            return cursor.rowcount

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

    def record_ip_range(self, range_start: str, range_end: str, range_str: str):
        """Grava ou incrementa o uso de uma faixa de IP no banco de dados."""
        if not range_str:
            return
        range_str = range_str.strip()
        range_start = (range_start or '').strip()
        range_end = (range_end or '').strip()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO frequent_ip_ranges (range_start, range_end, range_str, usage_count, last_used)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(range_str) DO UPDATE SET
                    range_start = excluded.range_start,
                    range_end = excluded.range_end,
                    usage_count = usage_count + 1,
                    last_used = CURRENT_TIMESTAMP
            """, (range_start, range_end, range_str))

    def get_frequent_ip_ranges(self, limit=10) -> List[Dict[str, Any]]:
        """Retorna as faixas de IP mais usadas ordenadas por frequência e recência."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT range_start, range_end, range_str, usage_count, last_used
                FROM frequent_ip_ranges
                ORDER BY usage_count DESC, last_used DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor]

    def delete_frequent_ip_range(self, range_str: str):
        """Remove uma faixa de IP do histórico."""
        if not range_str:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM frequent_ip_ranges WHERE range_str = ?", (range_str.strip(),))

db = DatabaseManager(APP_ROOT)

def start_scheduler():
    """Inicia o thread de segundo plano para executar tarefas agendadas."""
    def run_scheduler():
        app.logger.info("Agendador de tarefas em segundo plano iniciado.")
        
        # Recuperação de falhas: Reseta tarefas que não terminaram na última execução do servidor
        db.reset_orphaned_tasks()

        while True:
            try:
                # Manutenção de recursos: limpa conexões SSH mortas do pool
                prune_ssh_cache(app.logger)

                # Limpa miniaturas expiradas do cache de thumbnails
                now_ts = time.time()
                with _THUMBNAIL_LOCK:
                    expired_keys = [k for k, v in _THUMBNAIL_CACHE.items() if (now_ts - v[0]) > 60]
                    for k in expired_keys:
                        _THUMBNAIL_CACHE.pop(k, None)

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
def list_scheduled_tasks():
    """Retorna a lista de tarefas agendadas."""
    tasks = db.get_all_scheduled_tasks()
    return jsonify({"success": True, "tasks": tasks})

@app.route('/api/scheduled-tasks/<int:task_id>', methods=['DELETE'])
def delete_scheduled_task(task_id):
    """Remove uma tarefa agendada."""
    db.delete_scheduled_task(task_id)
    return jsonify({"success": True, "message": "Agendamento cancelado com sucesso."})

@app.route('/import-macs', methods=['POST'])
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

@app.route('/api/devices', methods=['GET'])
def get_devices_metadata():
    """Retorna metadados completos de todos os dispositivos registrados no banco."""
    devices = db.get_all_devices_metadata()
    return jsonify({"success": True, "devices": devices})


@app.route('/api/stats', methods=['GET'])
def get_lab_stats():
    """Retorna estatísticas resumidas em tempo real do laboratório."""
    try:
        macs = db.get_known_macs() if hasattr(db, 'get_known_macs') else {}
        aliases = db.get_aliases() if hasattr(db, 'get_aliases') else {}
        blocklist = db.get_blocklist() if hasattr(db, 'get_blocklist') else set()
        
        all_ips = set(macs.keys()) | set(aliases.keys()) | set(blocklist)
        total_count = len(all_ips)
        
        return jsonify({
            "success": True,
            "total": total_count,
            "blocked_count": len(blocklist),
            "macs_count": len(macs),
            "aliases_count": len(aliases)
        })
    except Exception as e:
        return jsonify({
            "success": True,
            "total": 0,
            "blocked_count": 0,
            "macs_count": 0,
            "aliases_count": 0
        })

@app.route('/api/device/group', methods=['POST'])
def set_device_group():
    """Define o grupo/laboratório para um ou mais endereços IP."""
    data = request.get_json() or {}
    ips = data.get('ips')
    ip = data.get('ip')
    group_name = data.get('group_name')

    target_ips = ips if ips and isinstance(ips, list) else ([ip] if ip else [])
    if not target_ips:
        return jsonify({"success": False, "message": "Nenhum IP fornecido."}), 400

    valid_ips = [i for i in target_ips if is_valid_ip(i)]
    if not valid_ips:
        return jsonify({"success": False, "message": "Nenhum IP válido fornecido."}), 400

    db.batch_update_groups(valid_ips, group_name)
    msg = f"Grupo '{group_name}' atribuído a {len(valid_ips)} dispositivo(s)." if group_name else f"Grupo removido de {len(valid_ips)} dispositivo(s)."
    return jsonify({"success": True, "message": msg, "count": len(valid_ips)})

@app.route('/api/groups', methods=['GET'])
def get_groups_summary():
    """Retorna o resumo de todos os grupos e dispositivos associados."""
    groups = db.get_groups_summary()
    return jsonify({"success": True, "groups": groups})

@app.route('/api/groups/<path:group_name>', methods=['DELETE'])
@app.route('/api/group/delete', methods=['POST'])
def delete_group_route(group_name=None):
    """Remove um grupo/laboratório desvinculando todos os dispositivos associados."""
    if not group_name and request.is_json:
        group_name = (request.get_json() or {}).get('group_name')

    if not group_name or not str(group_name).strip():
        return jsonify({"success": False, "message": "Nome do grupo não fornecido."}), 400

    target_group = str(group_name).strip()
    count = db.delete_group(target_group)
    return jsonify({"success": True, "message": f"Grupo '{target_group}' removido de {count} dispositivo(s).", "count": count})


# --- Integração com o Horário Escolar & Alertas de Fim de Aula ---
def _is_valid_student_target_ip(ip_str: str) -> bool:
    """Valida se o IP é um endereço unicast de aluno (ignora multicast, broadcast, loopback e roteadores), suportando especificações multiseat (ex: 192.168.0.101/aluno1)."""
    try:
        clean_ip = str(ip_str).split('/')[0].split(':')[0].strip()
        ip_obj = ipaddress.ip_address(clean_ip)
        if ip_obj.is_multicast or ip_obj.is_loopback or ip_obj.is_reserved or ip_obj.is_unspecified:
            return False
        octets = clean_ip.split('.')
        if len(octets) == 4:
            last = int(octets[3])
            if last in (0, 1, 255):  # Descarta subnet .0, gateway/roteador .1 e broadcast .255
                return False
        return True
    except Exception:
        return False

def _get_all_network_target_ips() -> List[str]:
    """Retorna a lista de computadores/estações multiseat identificados e que estão atualmente ONLINE na rede."""
    try:
        devices = db.get_all_devices_metadata()
        candidate_specs = list(devices.keys()) if devices else []
    except Exception:
        candidate_specs = []

    # Fallback para a faixa IP configurada se o banco ainda estiver sem dispositivos cadastrados
    if not candidate_specs:
        candidate_specs = [f"{IP_PREFIX}{i}" for i in range(IP_START, IP_END + 1)]

    # 1. Filtra apenas especificações/IPs de alunos válidos
    valid_specs = [spec for spec in candidate_specs if _is_valid_student_target_ip(spec)]

    # 2. Testa em paralelo (50 threads) quais máquinas estão ativas na porta SSH (22)
    def check_online(spec):
        try:
            host_ip = str(spec).split('/')[0].split(':')[0].strip()
            with socket.create_connection((host_ip, 22), timeout=0.25):
                return spec
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(20, max(1, len(valid_specs)))) as executor:
        results = executor.map(check_online, valid_specs)
        online_specs = [spec for spec in results if spec is not None]

    return sorted(online_specs)

def _send_schedule_warning_batch(message: str, target_ips: Optional[List[str]] = None) -> Dict[str, Any]:
    """Envia mensagem de aviso de fim de aula para todos os computadores/estações multiseat online via SSH."""
    try:
        from ssh_service import _execute_for_each_user

        if not target_ips:
            target_ips = _get_all_network_target_ips()

        app.logger.info(f"[ScheduleAlert] Disparando aviso de fim de aula para {len(target_ips)} estações da rede...")
        
        def send_to_one(target_spec):
            try:
                if '/' in target_spec:
                    host_ip, target_user = target_spec.split('/', 1)
                else:
                    host_ip, target_user = target_spec, None

                with ssh_connect(host_ip, SSH_USER, DEFAULT_PASSWORD, app.logger) as ssh:
                    if ssh:
                        payload = {'message': message, 'password': DEFAULT_PASSWORD}
                        if target_user:
                            payload['target_user'] = target_user
                        _execute_for_each_user(ssh, 'enviar_mensagem', payload, app.logger)
                        return target_spec, True
            except Exception as err:
                app.logger.debug(f"[ScheduleAlert] Host indisponível em {target_spec}: {err}")
            return target_spec, False

        results = {}
        with ThreadPoolExecutor(max_workers=min(15, max(1, len(target_ips)))) as executor:
            futures = [executor.submit(send_to_one, spec) for spec in target_ips]
            for f in as_completed(futures):
                spec, ok = f.result()
                if ok:
                    results[spec] = True

        return {"success": True, "delivered_count": len(results), "delivered_ips": list(results.keys())}
    except Exception as e:
        app.logger.error(f"[ScheduleAlert] Erro no envio batch: {e}")
        return {"success": False, "message": str(e)}

def _send_schedule_end_class_actions(clean_screen: bool = True, lock_screen: bool = True, lock_message: str = "", target_ips: Optional[List[str]] = None) -> Dict[str, Any]:
    """Executa a limpeza de tela e bloqueio de tela/periféricos para todas as estações multiseat usando o mesmo despachante do Grid VNC (_execute_for_each_user)."""
    try:
        from ssh_service import _execute_for_each_user

        if not target_ips:
            target_ips = _get_all_network_target_ips()

        msg = lock_message or "🔒 AULA ENCERRADA: Por favor, aguarde orientações do professor."
        app.logger.info(f"[ScheduleEndClass] Executando ações de fim de aula para TODOS os {len(target_ips)} alvos da rede. Clean={clean_screen}, Lock={lock_screen}")

        def send_actions_to_one(target_spec):
            try:
                if '/' in target_spec:
                    host_ip, target_user = target_spec.split('/', 1)
                else:
                    host_ip, target_user = target_spec, None

                with ssh_connect(host_ip, SSH_USER, DEFAULT_PASSWORD, app.logger) as ssh:
                    if ssh:
                        payload_clean = {'password': DEFAULT_PASSWORD}
                        payload_lock = {'message': msg, 'lock_message': msg, 'password': DEFAULT_PASSWORD}
                        if target_user:
                            payload_clean['target_user'] = target_user
                            payload_lock['target_user'] = target_user

                        if clean_screen:
                            _execute_for_each_user(ssh, 'limpar_tela', payload_clean, app.logger)
                        if lock_screen:
                            _execute_for_each_user(ssh, 'bloquear_tela_mensagem', payload_lock, app.logger)
                        return target_spec, True
            except Exception as err:
                app.logger.debug(f"[ScheduleEndClass] Host indisponível em {target_spec}: {err}")
            return target_spec, False

        results = {}
        with ThreadPoolExecutor(max_workers=min(15, max(1, len(target_ips)))) as executor:
            futures = [executor.submit(send_actions_to_one, spec) for spec in target_ips]
            for f in as_completed(futures):
                spec, ok = f.result()
                if ok:
                    results[spec] = True

        return {"success": True, "delivered_count": len(results), "delivered_ips": list(results.keys())}
    except Exception as e:
        app.logger.error(f"[ScheduleEndClass] Erro na execução de fim de aula: {e}")
        return {"success": False, "message": str(e)}

schedule_manager = ClassScheduleManager(
    db_manager=db,
    socketio=socketio,
    batch_executor=_send_schedule_warning_batch,
    end_class_executor=_send_schedule_end_class_actions
)
schedule_manager.start_loop()

@app.route('/api/schedule/config', methods=['GET', 'POST'])
def handle_schedule_config():
    """Obtém ou atualiza as configurações dos alertas de fim de aula e escola ativa."""
    if request.method == 'POST':
        data = request.get_json() or {}
        if 'selected_school' in data and data['selected_school']:
            schedule_manager.set_school(str(data['selected_school']).strip())
        if 'schools' in data and isinstance(data['schools'], dict):
            schedule_manager.schools.update(data['schools'])
            schedule_manager.periods = list(schedule_manager.schools.get(schedule_manager.selected_school, {}).get("periods", []))
        if 'periods' in data and isinstance(data['periods'], list):
            schedule_manager.update_school_periods(schedule_manager.selected_school, data['periods'])

        if 'enabled' in data:
            schedule_manager.enabled = bool(data['enabled'])
        if 'minutes_before' in data:
            schedule_manager.minutes_before = int(data['minutes_before'])
        if 'custom_message' in data and data['custom_message']:
            schedule_manager.custom_message = str(data['custom_message']).strip()
        if 'play_sound' in data:
            schedule_manager.play_sound = bool(data['play_sound'])
        if 'auto_clean_screen' in data:
            schedule_manager.auto_clean_screen = bool(data['auto_clean_screen'])
        if 'auto_lock_screen' in data:
            schedule_manager.auto_lock_screen = bool(data['auto_lock_screen'])
        if 'auto_unlock_screen' in data:
            schedule_manager.auto_unlock_screen = bool(data['auto_unlock_screen'])
        if 'auto_unlock_minutes' in data:
            schedule_manager.auto_unlock_minutes = int(data['auto_unlock_minutes'])
        if 'lock_message' in data and data['lock_message']:
            schedule_manager.lock_message = str(data['lock_message']).strip()
        if 'recreio_message' in data and data['recreio_message']:
            schedule_manager.recreio_message = str(data['recreio_message']).strip()
        if 'entrada_message' in data and data['entrada_message']:
            schedule_manager.entrada_message = str(data['entrada_message']).strip()
        
        schedule_manager.save_config()
        return jsonify({
            "success": True,
            "message": "Configurações de alerta e escola salvas com sucesso!",
            "enabled": schedule_manager.enabled,
            "minutes_before": schedule_manager.minutes_before,
            "custom_message": schedule_manager.custom_message,
            "play_sound": schedule_manager.play_sound,
            "auto_clean_screen": schedule_manager.auto_clean_screen,
            "auto_lock_screen": schedule_manager.auto_lock_screen,
            "auto_unlock_screen": schedule_manager.auto_unlock_screen,
            "auto_unlock_minutes": schedule_manager.auto_unlock_minutes,
            "lock_message": schedule_manager.lock_message,
            "recreio_message": schedule_manager.recreio_message,
            "entrada_message": schedule_manager.entrada_message,
            "selected_school": schedule_manager.selected_school,
            "schools": schedule_manager.schools,
            "periods": schedule_manager.periods,
            "upcoming_alerts": schedule_manager.get_upcoming_alerts()
        })

    return jsonify({
        "success": True,
        "enabled": schedule_manager.enabled,
        "minutes_before": schedule_manager.minutes_before,
        "custom_message": schedule_manager.custom_message,
        "play_sound": schedule_manager.play_sound,
        "auto_clean_screen": schedule_manager.auto_clean_screen,
        "auto_lock_screen": schedule_manager.auto_lock_screen,
        "auto_unlock_screen": schedule_manager.auto_unlock_screen,
        "auto_unlock_minutes": schedule_manager.auto_unlock_minutes,
        "lock_message": schedule_manager.lock_message,
        "recreio_message": schedule_manager.recreio_message,
        "entrada_message": schedule_manager.entrada_message,
        "selected_school": schedule_manager.selected_school,
        "schools": schedule_manager.schools,
        "periods": schedule_manager.periods,
        "upcoming_alerts": schedule_manager.get_upcoming_alerts()
    })

@app.route('/api/schedule/sync', methods=['POST'])
def sync_schedule_web():
    """Sincroniza os horários das aulas a partir da URL da escola ativa."""
    data = request.get_json(silent=True) or {}
    school_id = data.get('school_id') or schedule_manager.selected_school
    res = schedule_manager.fetch_schedule_from_web(school_id=school_id)
    return jsonify(res)

@app.route('/api/schedule/test', methods=['POST'])
def test_schedule_alert():
    """Dispara um alerta de teste imediato para todos os computadores online da rede."""
    data = request.get_json() or {}
    target_ips = data.get('ips')
    if not target_ips:
        target_ips = _get_all_network_target_ips()
    msg_text = data.get('message')
    res = schedule_manager.trigger_test_alert(target_ips=target_ips, message_text=msg_text)
    return jsonify(res)

@app.route('/api/schedule/test-end', methods=['POST'])
def test_schedule_end_class():
    """Dispara o teste de Limpeza e Bloqueio de fim de aula imediato para todos os computadores online da rede."""
    data = request.get_json() or {}
    target_ips = data.get('ips')
    if not target_ips:
        target_ips = _get_all_network_target_ips()
    res = schedule_manager.trigger_test_end_class(target_ips=target_ips)
    return jsonify(res)

@app.route('/api/schedule/test-unlock', methods=['POST'])
def test_schedule_unlock():
    """Dispara o desbloqueio em lote imediato para encerrar o teste de fim de aula."""
    data = request.get_json() or {}
    target_ips = data.get('ips')
    if not target_ips:
        target_ips = _get_all_network_target_ips()
    res = schedule_manager.trigger_test_unlock(target_ips=target_ips)
    return jsonify(res)

@app.route('/api/schedule/test-close-alert', methods=['POST'])
def test_schedule_close_alert():
    """Fecha o pop-up de aviso de teste de todos os computadores."""
    data = request.get_json() or {}
    target_ips = data.get('ips')
    if not target_ips:
        target_ips = _get_all_network_target_ips()
    res = schedule_manager.trigger_test_close_alert(target_ips=target_ips)
    return jsonify(res)


# =========================================================================
# ROTAS DO SISTEMA DE DISCIPLINA POR RUÍDO / DECIBÉIS (SALA DE AULA)
# =========================================================================

@app.route('/api/noise/warn', methods=['POST'])
def api_noise_warn():
    """Envia mensagem de aviso de ruído para as máquinas dos alunos na sala de aula."""
    data = request.get_json() or {}
    infraction = data.get('infraction', 1)
    threshold = data.get('threshold', 75)
    custom_msg = data.get('message')
    if not custom_msg:
        if infraction == 1:
            custom_msg = f"📢 ATENÇÃO: Nível de barulho excedeu o limite ({threshold} dB)!\n(1º Aviso de 2). Por favor, mantenham o silêncio na sala de aula."
        else:
            custom_msg = f"⚠️ ÚLTIMO AVISO DE RUÍDO: Limite ({threshold} dB) ultrapassado pela 2ª vez!\nSe o barulho persistir, todos os computadores serão travados automaticamente por 1 minuto."
    
    target_ips = data.get('ips')
    if not target_ips:
        target_ips = _get_all_network_target_ips()
        
    app.logger.info(f"[NoiseDiscipline] Enviando aviso de ruído #{infraction} para {len(target_ips)} estações...")
    res = _send_schedule_warning_batch(message=custom_msg, target_ips=target_ips)
    return jsonify(res)


@app.route('/api/noise/lock', methods=['POST'])
def api_noise_lock():
    """Trava a tela das máquinas dos alunos após atingir a 3ª infração de barulho."""
    data = request.get_json() or {}
    infraction = data.get('infraction', 3)
    custom_msg = data.get('message')
    if not custom_msg:
        custom_msg = f"🔒 COMPUTADORES BLOQUEADOS POR EXCESSO DE BARULHO (Infração #{infraction})!\nO limite de ruído foi ultrapassado 3 vezes.\nAs máquinas permanecerão bloqueadas por 1 minuto e só voltarão após a sala fazer silêncio."
    
    target_ips = data.get('ips')
    if not target_ips:
        target_ips = _get_all_network_target_ips()
        
    app.logger.info(f"[NoiseDiscipline] TRAVANDO TELAS por excesso de ruído (#{infraction}) em {len(target_ips)} estações...")
    res = _send_schedule_end_class_actions(clean_screen=False, lock_screen=True, lock_message=custom_msg, target_ips=target_ips)
    return jsonify(res)


@app.route('/api/noise/unlock', methods=['POST'])
def api_noise_unlock():
    """Desbloqueia as máquinas dos alunos quando o silêncio é restabelecido."""
    data = request.get_json() or {}
    target_ips = data.get('ips')
    if not target_ips:
        target_ips = _get_all_network_target_ips()
        
    app.logger.info(f"[NoiseDiscipline] Desbloqueando telas após retorno do silêncio em {len(target_ips)} estações...")
    res = schedule_manager.trigger_test_unlock(target_ips=target_ips)
    return jsonify(res)





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
        arp_items = discover_ips_with_arp_scan()
        if arp_items:
            app.logger.debug(f"Deep ARP Scan: Encontrados {len(arp_items)} dispositivos.")
            for item in arp_items:
                ip, mac = item['ip'], item.get('mac')
                if mac and mac != "00:00:00:00:00:00" and known_macs.get(ip) != mac:
                    db.update_mac(ip, mac)

        # --- 2. Coleta Reativa (Fallback) ---
        if os.path.exists('/proc/net/arp'):
            with open('/proc/net/arp', 'r') as f:
                next(f)
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4:
                        ip, mac = parts[0], parts[3]
                        if mac != "00:00:00:00:00:00" and mac != "ff:ff:ff:ff:ff:ff" and known_macs.get(ip) != mac:
                            db.update_mac(ip, mac)

        try:
            cmd = ['arp', '-an'] if platform.system() != 'Windows' else ['arp', '-a']
            result = subprocess.run(cmd, capture_output=True, text=True, errors='ignore', timeout=6)
            for line in result.stdout.splitlines():
                match = re.search(r'(\d{1,3}(?:\.\d{1,3}){3}).*?(([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2})', line)
                if match:
                    ip, mac = match.group(1), match.group(2).replace('-', ':').lower()
                    if mac != "00:00:00:00:00:00" and known_macs.get(ip) != mac:
                        db.update_mac(ip, mac)
        except subprocess.TimeoutExpired:
            app.logger.debug("Coleta da tabela ARP concluída via fallback.")
    except Exception as e:
        app.logger.error(f"Erro ao coletar MACs da tabela ARP: {e}")


# --- Rota para Descobrir IPs (HTTP + Streaming via Socket.IO) ---
@app.route('/discover-ips', methods=['POST'])
def discover_ips():
    """
    Escaneia a rede e retorna IPs descobertos.
    Emite eventos Socket.IO progressivos (ip_found) conforme hosts são descobertos.
    """
    try:
        clear_dns_cache()
        data = request.get_json() or {}
        custom_range = data.get('custom_range')
        sid = data.get('sid')  # Socket.IO session ID para emissão progressiva
        ip_prefix, _, _, server_ip, gateway_ip = get_local_ip_and_range(app.logger)
        app.logger.info(f"Iniciando varredura. Gateway: {gateway_ip}")

        if custom_range:
            parts = custom_range.replace('x', '0').split('/')[0].split('.')
            if len(parts) >= 3:
                ip_prefix = ".".join(parts[:3]) + "."
            # Grava a faixa no histórico de faixas mais usadas
            r_parts = custom_range.split(' a ') if ' a ' in custom_range else [custom_range, '']
            db.record_ip_range(r_parts[0], r_parts[1] if len(r_parts) > 1 else '', custom_range)

        ip_blocklist = db.get_blocklist()
        comprehensive_exclusion_list = set(IP_EXCLUSION_LIST) | ip_blocklist
        if server_ip: comprehensive_exclusion_list.add(server_ip)
        if gateway_ip: comprehensive_exclusion_list.add(gateway_ip)

        # Limites numéricos para filtragem
        low_bound, high_bound = IP_START, IP_END
        if custom_range and ' a ' in custom_range:
            try:
                r_parts = custom_range.split(' a ')
                low_bound = int(r_parts[0].split('.')[-1])
                high_bound = int(r_parts[1].split('.')[-1])
            except (ValueError, IndexError):
                pass

        scanner = NetworkScanner(app.logger)
        active_ips = scanner.scan(custom_range)

        if active_ips:
            active_ips = [item for item in active_ips if is_valid_ip(item['ip'])]

        active_ips = [item for item in active_ips if item['ip'] not in comprehensive_exclusion_list]

        # Harvest MACs em thread background (não bloqueia a resposta)
        threading.Thread(target=_harvest_macs_from_arp, daemon=True).start()
        known_macs = db.get_known_macs()
        db_devices = {d['ip']: d.get('hostname') for d in db.get_all_devices() if d.get('hostname')}

        if active_ips:
            with ThreadPoolExecutor(max_workers=min(30, max(5, len(active_ips)))) as executor:
                future_to_item = {
                    executor.submit(resolve_remote_hostname, item['ip'], 0.35): item 
                    for item in active_ips if isinstance(item, dict) and 'ip' in item
                }
                for future in as_completed(future_to_item):
                    item = future_to_item[future]
                    try:
                        ip = item['ip']
                        item['mac'] = known_macs.get(ip)
                        name = future.result()
                        db_name = db_devices.get(ip)
                        if db_name:
                            item['hostname'] = db_name
                        elif name:
                            item['hostname'] = name
                            db.update_hostname(ip, name)
                        else:
                            item['hostname'] = None
                    except Exception:
                        item['hostname'] = db_devices.get(item.get('ip'))

        if active_ips:
            active_ips.sort(key=lambda item: ipaddress.ip_address(item['ip']))

        return jsonify({
            "success": True,
            "ips": active_ips,
            "range": f"{ip_prefix}x",
            "server_ip": server_ip,
            "detection_failed": server_ip is None
        }), 200

    except Exception as e:
        app.logger.error(f"Erro crítico na descoberta de IPs: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Erro interno: {e}"}), 500


@app.route('/block-ip', methods=['POST'])
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
def get_blocklist():
    """Retorna a lista de IPs atualmente na blocklist."""
    ip_blocklist = db.get_blocklist()
    return jsonify({"success": True, "blocklist": sorted(list(ip_blocklist))})

@app.route('/unblock-ip', methods=['POST'])
def unblock_ip():
    """Remove um IP da blocklist permanente."""
    data = request.get_json()
    ip_to_unblock = data.get('ip')

    if not ip_to_unblock:
        return jsonify({"success": False, "message": "Nenhum IP fornecido."}), 400

    db.set_blocked(ip_to_unblock, False)
    app.logger.info(f"IP {ip_to_unblock} removido da blocklist.")
    return jsonify({"success": True, "message": f"IP {ip_to_unblock} foi desbloqueado."})

@app.route('/api/ip-ranges', methods=['GET'])
def get_ip_ranges():
    """Retorna as faixas de IP mais utilizadas."""
    ranges = db.get_frequent_ip_ranges(limit=15)
    return jsonify({"success": True, "ranges": ranges})

@app.route('/api/ip-ranges', methods=['POST'])
def save_ip_range():
    """Grava ou incrementa o uso de uma faixa de IP."""
    data = request.get_json() or {}
    start = (data.get('start') or '').strip()
    end = (data.get('end') or '').strip()
    range_str = data.get('range_str') or data.get('custom_range')
    
    if not range_str:
        if start and end:
            range_str = f"{start} a {end}"
        elif start:
            range_str = start

    if not range_str:
        return jsonify({"success": False, "message": "Faixa inválida."}), 400

    db.record_ip_range(start, end, range_str)
    return jsonify({"success": True, "message": f"Faixa '{range_str}' gravada com sucesso."})

@app.route('/api/ip-ranges', methods=['DELETE'])
def delete_ip_range():
    """Remove uma faixa de IP do histórico."""
    data = request.get_json() or {}
    range_str = data.get('range_str')
    if not range_str:
        return jsonify({"success": False, "message": "Faixa é obrigatória."}), 400

    db.delete_frequent_ip_range(range_str)
    return jsonify({"success": True, "message": f"Faixa '{range_str}' removida."})

@app.route('/get-aliases', methods=['GET'])
def get_aliases():
    """Retorna todos os apelidos e nomes de host configurados."""
    aliases = db.get_aliases()
    hostnames = db.get_hostnames()
    return jsonify({"success": True, "aliases": aliases, "hostnames": hostnames})

@app.route('/set-alias', methods=['POST'])
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

_GIT_INFO_CACHE = None

def _get_git_info():
    global _GIT_INFO_CACHE
    if _GIT_INFO_CACHE is not None:
        return _GIT_INFO_CACHE

    version = "Desconhecida"
    branch = "Desconhecida"
    commit_date = None
    commit_msg = None
    commit_hash = None
    try:
        version = subprocess.check_output(
            ['git', 'describe', '--tags', '--always'],
            stderr=subprocess.STDOUT,
            cwd=APP_ROOT
        ).decode('utf-8').strip()

        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            stderr=subprocess.STDOUT,
            cwd=APP_ROOT
        ).decode('utf-8').strip()

        commit_date = subprocess.check_output(
            ['git', 'log', '-1', '--format=%cd', '--date=format:%d/%m/%Y %H:%M:%S'],
            stderr=subprocess.STDOUT,
            cwd=APP_ROOT
        ).decode('utf-8').strip()

        commit_hash = subprocess.check_output(
            ['git', 'log', '-1', '--format=%h'],
            stderr=subprocess.STDOUT,
            cwd=APP_ROOT
        ).decode('utf-8').strip()

        commit_msg = subprocess.check_output(
            ['git', 'log', '-1', '--format=%s'],
            stderr=subprocess.STDOUT,
            cwd=APP_ROOT
        ).decode('utf-8').strip()

    except Exception:
        pass

    _GIT_INFO_CACHE = {
        "version": version,
        "branch": branch,
        "commit_date": commit_date,
        "commit_msg": commit_msg,
        "commit_hash": commit_hash
    }
    return _GIT_INFO_CACHE

@app.route('/api/metadata', methods=['GET'])
def get_metadata():
    """Retorna os metadados das ações e informações detalhadas da versão Git (branch, commit, data/hora)."""
    git_info = _get_git_info()
    return jsonify({
        "success": True, 
        "metadata": COMMAND_METADATA, 
        **git_info
    })

@app.route('/check-status', methods=['POST'])
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
                return ip, {'status': 'offline', 'user_count': 0, 'os_type': 'unknown'}

            os_type = host_info.get('os_type', 'unknown')

            # Se skip_ssh for True, apenas confirmamos que a porta 22 está aberta sem logar
            if host_info['type'] == 'ssh' and not skip_ssh:
                # Usa um timeout curto para uma verificação rápida.
                with ssh_connect(ip, SSH_USER, password, app.logger, auto_fix_key=True) as ssh:
                    # Comando para obter hostname remoto, lista de usuários, contagem de usuários e sinal
                    cmd = "echo '---HN---'; (cat /etc/hostname 2>/dev/null || hostname 2>/dev/null); echo '---USERS---'; who | awk '{print $1}' | sort -u | tr '\n' ',' | sed 's/,$//'; echo ''; echo '---STAT---'; who | wc -l; IFACE=$(ip route | grep default | awk '{print $5}' | head -n1); [ -d /sys/class/net/$IFACE/wireless ] && awk 'NR==3 {print int($3*100/70)}' /proc/net/wireless || echo 100"
                    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=5)
                    raw = stdout.read().decode('utf-8', errors='ignore').strip()
                    
                    hn = None
                    users_str = None
                    user_count = 1
                    signal = 100
                    
                    if '---HN---' in raw:
                        hn_part = raw.split('---HN---')[1]
                        if '---USERS---' in hn_part:
                            hn_section, users_section = hn_part.split('---USERS---', 1)
                            hn_val = hn_section.strip()
                            if hn_val and hn_val != ip and len(hn_val) < 64:
                                hn = hn_val.splitlines()[0].strip()
                                try:
                                    db.update_hostname(ip, hn)
                                except Exception: pass
                            
                            if '---STAT---' in users_section:
                                u_part, stat_part = users_section.split('---STAT---', 1)
                                users_str = u_part.strip().replace(',', ', ')
                                stat_lines = stat_part.strip().splitlines()
                                user_count = int(stat_lines[0]) if stat_lines and stat_lines[0].isdigit() else 1
                                signal = int(stat_lines[1]) if len(stat_lines) > 1 and stat_lines[1].isdigit() else 100
                    else:
                        lines = raw.splitlines()
                        user_count = int(lines[0]) if lines and lines[0].isdigit() else 1
                        signal = int(lines[1]) if len(lines) > 1 and lines[1].isdigit() else 100

                    res = {'status': 'online', 'user_count': user_count, 'signal': signal, 'os_type': os_type}
                    if hn:
                        res['hostname'] = hn
                    elif host_info.get('hostname'):
                        res['hostname'] = host_info['hostname']
                    if users_str:
                        res['users'] = users_str
                    return ip, res
            elif host_info['type'] == 'ssh' and skip_ssh:
                # Retorna online sem detalhes extras para ganhar velocidade
                return ip, {'status': 'online', 'user_count': 0, 'os_type': os_type}
            else:
                # Host online via Ping, mas porta 22 (SSH) fechada
                return ip, {'status': 'online', 'user_count': 0, 'type': 'ping', 'os_type': os_type}

        except paramiko.AuthenticationException:
            # A máquina está online, mas a senha está errada.
            return ip, {'status': 'auth_error', 'user_count': 0, 'os_type': 'unknown'}
        except Exception:
            # Qualquer outra exceção (timeout, conexão recusada) significa offline.
            return ip, {'status': 'offline', 'user_count': 0, 'os_type': 'unknown'}

    # Usa pool controlado de no máximo 20 workers para garantir alta velocidade e baixo consumo de memória
    with ThreadPoolExecutor(max_workers=min(20, max(5, len(ips)))) as executor:
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
    file_path = Path(APP_ROOT) / path
    if not file_path.exists() or file_path.is_dir():
        if path == 'favicon.ico':
            return '', 204
        # Se for um arquivo estático não encontrado (ex: logo.png), retorna 404 limpo sem exceção
        if '.' in path and not path.endswith('.html'):
            return jsonify({"success": False, "message": "Arquivo não encontrado."}), 404
        return send_from_directory(APP_ROOT, 'index.html')
    return send_from_directory(APP_ROOT, path)

@app.route('/favicon.ico')
def favicon():
    """Silencia o erro 404 para o favicon.ico, que o navegador solicita por padrão."""
    return '', 204


# --- Funções de Manipulação de Ações (Refatoradas de 'gerenciar_atalhos_ip') ---

def _handle_shell_action(ssh: paramiko.SSHClient, username: Optional[str], action: str, data: Dict[str, Any]):
    """Lida com ações que executam comandos shell."""
    ip = data.get('ip')
    password = data.get('password') or ''
    command_builder = _get_command_builder(action)

    if not command_builder:
        app.logger.warning(f"Ação solicitada '{action}' não encontrada. Comandos carregados: {list(COMMANDS.keys())}")
        return {"success": False, "message": "Ação desconhecida. Tente reiniciar o servidor backend.", "details": f"A ação '{action}' não consta na lista de comandos carregados."}

    # Constrói o comando
    if callable(command_builder):
        command, error_response = command_builder(data)
        if error_response:
            return error_response # Retorna o dicionário de erro diretamente.
    else:
        command = command_builder

    meta = COMMAND_METADATA.get(action) or {}
    use_sudo = not meta.get('no_sudo', False)
    is_fire_and_forget = meta.get('fire_and_forget', False) or action in (
        'reiniciar', 'desligar', 'suspender',
        'reiniciar_maquinas', 'desligar_maquinas', 'suspender_maquinas'
    )

    # Define o timeout da execução
    if action in ('atualizar_sistema', 'update_system'):
        timeout = 1800
    elif is_fire_and_forget:
        timeout = 10
    else:
        timeout = 30

    # Ações que não esperam resposta estendida (fire-and-forget)
    if is_fire_and_forget:
        try:
            out, _, _ = _execute_shell_command(ssh, command, password, timeout=timeout, username=username, use_sudo=use_sudo)
            msg = out.strip() if out else f"Sinal de '{action}' enviado com sucesso."
        except Exception as e:
            app.logger.info(f"Sinal de '{action}' em {ip} finalizado/desconectado: {e}")
            msg = f"Sinal de '{action}' enviado com sucesso."
        return {"success": True, "message": msg}

    try:
        # Executa o comando shell. Se falhar, uma exceção CommandExecutionError será lançada.
        output, warnings, errors = _execute_shell_command(ssh, command, password, timeout=timeout, username=username, use_sudo=use_sudo)
    except CommandExecutionError as e:
        app.logger.error(f"Erro na ação '{action}' em {ip}: {e.details}")
        # Combina warnings e errors nos detalhes para um log completo no frontend.
        details = []
        # Usa os avisos da exceção, se houver.
        if e.warnings: details.append(f"Avisos: {e.warnings}")
        if e.details: details.append(f"Erros: {e.details}")
        
        # Retorna sucesso como False, mas inclui todos os detalhes.
        return {"success": False, "message": "Ocorreu um erro no dispositivo remoto.", "details": "\n".join(details)}


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
def stream_action():
    """
    Executa uma ação e transmite a saída em tempo real.
    Ideal para comandos de longa duração como 'atualizar_sistema'.
    """
    data = request.get_json() or {}
    raw_ip = data.get('ip')
    ip = raw_ip
    
    if raw_ip and '/' in raw_ip:
        parts = raw_ip.split('/', 1)
        ip = parts[0].strip()
        target_user_suffix = parts[1].strip()
        if target_user_suffix:
            data['target_user'] = target_user_suffix
            data['ip'] = ip

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
                # Usa a função de streaming do ssh_service com timeout expandido de 30 minutos (1800s)
                stream_timeout = 1800 if action in ('atualizar_sistema', 'update_system') else 300
                exit_code = yield from _stream_shell_command(ssh, command, password, timeout=stream_timeout)
                
                # Envia um marcador de finalização com o código de saída
                yield f"__STREAM_END__:{exit_code}\n"

        except (socket.error, OSError, paramiko.SSHException) as e:
            app.logger.warning(f"Erro de conexão SSH no streaming para '{action}' em {ip}: {e}")
            yield f"__STREAM_ERROR__:Erro de conexão ou execução: {str(e)}\n"
        except Exception as e:
            app.logger.error(f"Erro de streaming na ação '{action}' em {ip}: {e}", exc_info=True)
            yield f"__STREAM_ERROR__:Erro de conexão ou execução: {str(e)}\n"

    # Retorna uma resposta de streaming. O mimetype 'text/event-stream' é comum,
    # mas 'text/plain' funciona bem para o nosso caso de uso simples.
    return Response(generate_stream(), mimetype='text/plain')

# --- Rota para Listar Backups de Atalhos ---
@app.route('/list-backups', methods=['POST'])
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
    'bloquear_combinacoes_teclas': _execute_for_each_user,
    'desbloquear_combinacoes_teclas': _execute_for_each_user,
    'bloquear_terminal': _execute_for_each_user,
    'desbloquear_terminal': _execute_for_each_user,
    'bloquear_dconf': _execute_for_each_user,
    'desbloquear_dconf': _execute_for_each_user,
    'definir_firefox_padrao': _execute_for_each_user,
    'definir_chrome_padrao': _execute_for_each_user,
    'desativar_perifericos': _execute_for_each_user,
    'ativar_perifericos': _execute_for_each_user,
    'bloquear_tela_mensagem': _execute_for_each_user,
    'desbloquear_tela_mensagem': _execute_for_each_user,
    'limpar_tela': _execute_for_each_user,
    'deslogar_navegadores': _execute_for_each_user,
    'iniciar_modo_demo': _execute_for_each_user,
    'parar_modo_demo': _execute_for_each_user,
    'desativar_botao_direito': _execute_for_each_user,
    'ativar_botao_direito': _execute_for_each_user,
    'enviar_mensagem': _execute_for_each_user,
    'fechar_mensagem': _execute_for_each_user,
    'pedir_silencio': _execute_for_each_user,
    'definir_papel_de_parede': _execute_for_each_user,
    'instalar_scratchjr': _execute_for_each_user,
    'remover_todos_bloqueios': _execute_for_each_user,
    'ativar_protecao_tela': _execute_for_each_user,
    'desativar_protecao_tela': _execute_for_each_user,
    'configurar_protecao_tela': _execute_for_each_user,
    'cleanup_wallpaper': _handle_cleanup_wallpaper, # Ação por máquina, não por usuário
}

# --- Rota Principal para Gerenciar Ações via SSH ---
@app.route('/gerenciar_atalhos_ip', methods=['POST'])
def gerenciar_atalhos_ip():
    """
    Recebe as informações do frontend, conecta via SSH e despacha a ação apropriada.
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Requisição inválida."}), 400

    action = data.get('action')
    password = get_request_password(data)

    # Processa o IP para verificar se há uma flag de usuário (ex: 192.168.0.10/aluno1)
    raw_ip = data.get('ip')
    ip = raw_ip
    
    if raw_ip:
        if '/' in raw_ip:
            parts = raw_ip.split('/', 1)
            ip = parts[0].strip()
            # Apenas atribui target_user se a ação for explicitamente por usuário
            if parts[1].strip() and action in ACTION_HANDLERS and ACTION_HANDLERS[action] == _execute_for_each_user:
                data['target_user'] = parts[1].strip()
            else:
                data.pop('target_user', None)
        if '__' in ip:
            ip = ip.split('__', 1)[0].strip()
        elif ':' in ip:
            ip = ip.split(':', 1)[0].strip()
        data['ip'] = ip

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
                    status_code = 400 if "Ação desconhecida" in result.get('message', '') else 422
                else:
                    status_code = 200
                
            return jsonify(result), status_code

    except (paramiko.SSHException, socket.error, OSError, TimeoutError) as e:
        response, status_code = _handle_ssh_exception(e, ip, action, app.logger)
        return jsonify(response), status_code
    except Exception as e:
        app.logger.error(f"Erro inesperado na rota /gerenciar_atalhos_ip para {ip}: {e}", exc_info=True)
        response, status_code = _handle_ssh_exception(e, ip, action, app.logger)
        if status_code == 500:
            status_code = 502
            response["message"] = f"Falha ao executar ação em {ip}: {str(e)}"
@app.route('/api/warmup-ssh', methods=['POST'])
def warmup_ssh():
    """Pré-aquece e abre conexões SSH no pool em paralelo para máquinas ativas do Grid."""
    try:
        data = request.get_json() or {}
        ips = data.get('ips', [])
        password = data.get('password') or SSH_PASSWORD
        
        if not ips:
            return jsonify({"success": True, "message": "Nenhum IP para aquecer."})

        threading.Thread(
            target=warm_up_ssh_pool,
            args=(ips, SSH_USER, password, app.logger),
            daemon=True
        ).start()

        return jsonify({"success": True, "message": f"Aquecimento SSH iniciado para {len(ips)} máquinas."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/batch-wake-on-lan', methods=['POST'])
def batch_wake_on_lan():
    """Envia o sinal Magic Packet (WoL) para múltiplos IPs em lote."""
    try:
        data = request.get_json() or {}
        target_ips = data.get('ips', [])

        if not target_ips:
            return jsonify({"success": False, "message": "Nenhum IP foi especificado."}), 400

        known_macs = db.get_known_macs()
        ip_mac_map = {}
        missing_macs = []

        for ip in target_ips:
            mac = known_macs.get(ip)
            if mac:
                ip_mac_map[ip] = mac
            else:
                missing_macs.append(ip)

        db.add_audit_log(request.remote_addr, "batch_wake_on_lan", target_ips, "processando")

        if not ip_mac_map:
            return jsonify({
                "success": False,
                "message": f"Nenhum dos {len(target_ips)} IPs selecionados possui endereço MAC gravado no sistema.",
                "missing_macs": missing_macs
            }), 400

        # Executa disparo em lote
        wol_results = send_batch_wake_on_lan(list(ip_mac_map.values()), app.logger)

        sent_ips = [ip for ip, mac in ip_mac_map.items() if wol_results.get(mac)]
        failed_ips = [ip for ip, mac in ip_mac_map.items() if not wol_results.get(mac)]

        msg = f"Sinal Wake-on-LAN enviado para {len(sent_ips)} dispositivo(s)."
        if missing_macs:
            msg += f" ({len(missing_macs)} sem MAC)"

        return jsonify({
            "success": True,
            "message": msg,
            "sent_count": len(sent_ips),
            "sent_ips": sent_ips,
            "failed_ips": failed_ips,
            "missing_macs": missing_macs
        }), 200

    except Exception as e:
        app.logger.error(f"Erro ao executar Wake-on-LAN em lote: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Erro interno: {str(e)}"}), 500

@app.route('/backup-application', methods=['POST'])
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

# --- Handlers para Web SSH Terminal (Flask-SocketIO + Paramiko) ---
_WEB_SSH_SESSIONS: Dict[str, Dict[str, Any]] = {}
_WEB_SSH_LOCK = threading.Lock()

def _close_web_ssh_session(sid: str):
    """Fecha a sessão de terminal SSH associada ao ID do Socket."""
    with _WEB_SSH_LOCK:
        sess = _WEB_SSH_SESSIONS.pop(sid, None)
        if sess:
            sess['active'] = False
            chan = sess.get('channel')
            client = sess.get('client')
            if chan:
                try:
                    chan.close()
                except Exception:
                    pass
            if client:
                try:
                    client.close()
                except Exception:
                    pass

@socketio.on('connect_ssh')
def handle_connect_ssh(data):
    """Evento para iniciar uma conexão SSH interativa (PTY)."""
    sid = request.sid
    _close_web_ssh_session(sid)

    ip = data.get('ip')
    username = data.get('username')
    password = data.get('password')
    cols = data.get('cols', 80)
    rows = data.get('rows', 24)

    if not ip or not username:
        emit('ssh_output', "\r\n\x1b[31m[ERRO] IP e Usuário são obrigatórios.\x1b[0m\r\n")
        return

    emit('ssh_output', f"\r\n\x1b[33mConectando via SSH a {username}@{ip}...\x1b[0m\r\n")

    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        ssh_client.connect(
            ip, 
            username=username, 
            password=password if password else None, 
            timeout=15, 
            banner_timeout=30,
            look_for_keys=True,
            allow_agent=True
        )

        channel = ssh_client.invoke_shell(term='xterm-256color', width=int(cols), height=int(rows))
        channel.settimeout(0.0)

        with _WEB_SSH_LOCK:
            _WEB_SSH_SESSIONS[sid] = {
                'client': ssh_client,
                'channel': channel,
                'active': True
            }

        emit('ssh_connected', {"status": "connected", "ip": ip, "username": username})

        def read_output(sid_target, chan):
            while True:
                with _WEB_SSH_LOCK:
                    sess = _WEB_SSH_SESSIONS.get(sid_target)
                    if not sess or not sess.get('active'):
                        break
                try:
                    if chan.recv_ready():
                        out = chan.recv(4096)
                        if not out:
                            break
                        socketio.emit('ssh_output', out.decode('utf-8', errors='replace'), room=sid_target)
                    elif chan.exit_status_ready():
                        break
                    else:
                        time.sleep(0.02)
                except Exception as ex:
                    app.logger.debug(f"Loop SSH de leitura encerrado: {ex}")
                    break

            socketio.emit('ssh_output', "\r\n\x1b[33mConexão SSH encerrada.\x1b[0m\r\n", room=sid_target)
            socketio.emit('ssh_disconnected', {"status": "disconnected"}, room=sid_target)
            _close_web_ssh_session(sid_target)

        socketio.start_background_task(read_output, sid_target=sid, chan=channel)

    except paramiko.AuthenticationException:
        emit('ssh_output', f"\r\n\x1b[31m[ERRO] Autenticação SSH falhou para {username}@{ip}.\x1b[0m\r\n")
        emit('ssh_disconnected', {"status": "error", "message": "Falha de Autenticação"})
    except Exception as e:
        app.logger.error(f"Erro na conexão Web SSH para {ip}: {e}")
        emit('ssh_output', f"\r\n\x1b[31m[ERRO] Falha ao conectar: {str(e)}\x1b[0m\r\n")
        emit('ssh_disconnected', {"status": "error", "message": str(e)})

@socketio.on('ssh_input')
def handle_ssh_input(data):
    """Envia entrada do teclado do usuário para a sessão PTY."""
    sid = request.sid
    with _WEB_SSH_LOCK:
        sess = _WEB_SSH_SESSIONS.get(sid)
        if sess and sess.get('channel'):
            try:
                input_data = data.get('data', '') if isinstance(data, dict) else data
                sess['channel'].send(input_data)
            except Exception as e:
                app.logger.debug(f"Erro ao enviar entrada SSH: {e}")

@socketio.on('ssh_resize')
def handle_ssh_resize(data):
    """Redimensiona o tamanho do PTY SSH (cols x rows)."""
    sid = request.sid
    cols = data.get('cols', 80)
    rows = data.get('rows', 24)
    with _WEB_SSH_LOCK:
        sess = _WEB_SSH_SESSIONS.get(sid)
        if sess and sess.get('channel'):
            try:
                sess['channel'].resize_pty(width=int(cols), height=int(rows))
            except Exception as e:
                app.logger.debug(f"Erro ao redimensionar PTY SSH: {e}")

@socketio.on('disconnect_ssh')
def handle_disconnect_ssh():
    """Fecha a sessão SSH associada explicitamente."""
    sid = request.sid
    _close_web_ssh_session(sid)

@socketio.on('disconnect')
def handle_socket_disconnect():
    """Fecha a sessão SSH associada quando o cliente se desconecta do WebSocket."""
    sid = request.sid
    _close_web_ssh_session(sid)

# --- Gerenciamento de Ações em Lote via WebSocket (Socket.IO) ---
_ACTIVE_BATCH_CANCELLATIONS: Dict[str, threading.Event] = {}
_ACTIVE_BATCH_LOCK = threading.Lock()

@socketio.on('cancel_batch_action')
def handle_cancel_batch_action(data):
    """Sinaliza o cancelamento de uma execução em lote em andamento."""
    batch_id = data.get('batch_id') if isinstance(data, dict) else data
    if batch_id:
        with _ACTIVE_BATCH_LOCK:
            cancel_event = _ACTIVE_BATCH_CANCELLATIONS.get(batch_id)
            if cancel_event:
                cancel_event.set()
                app.logger.info(f"[BatchAction] Cancelamento solicitado para o lote: {batch_id}")

@socketio.on('start_batch_action')
def handle_start_batch_action(data):
    """
    Executa ações em lote com paralelismo real no backend via ThreadPoolExecutor.
    Elimina o gargalo do navegador (limite de 6 conexões HTTP/1.1 por host)
    e transmite o status e o streaming de cada máquina em tempo real via Socket.IO.
    """
    sid = request.sid
    data = data or {}
    batch_id = data.get('batch_id') or f"batch_{int(time.time() * 1000)}"
    action = data.get('action')
    ips = data.get('ips') or []
    password = get_request_password(data)
    payload = data.get('payload') or {}

    if not action or not ips:
        socketio.emit('batch_error', {
            'batch_id': batch_id,
            'message': 'Ação e lista de IPs são obrigatórios.'
        }, room=sid)
        return

    cancel_event = threading.Event()
    with _ACTIVE_BATCH_LOCK:
        _ACTIVE_BATCH_CANCELLATIONS[batch_id] = cancel_event

    def run_batch():
        app.logger.info(f"[BatchAction] Lote {batch_id} iniciado para ação '{action}' em {len(ips)} máquinas.")
        streaming_actions = [k for k, v in COMMAND_METADATA.items() if v.get('is_streaming')]
        is_streaming = action in streaming_actions or 'atualizar' in action or 'install' in action

        # Caso especial: Wake-on-LAN
        if action in ['wake_on_lan', 'ligar']:
            known_macs = db.get_known_macs()
            for raw_ip_spec in ips:
                if cancel_event.is_set():
                    break
                base_ip = str(raw_ip_spec).split('/')[0].strip()
                mac = known_macs.get(base_ip)
                if not mac:
                    socketio.emit('batch_item_result', {
                        'batch_id': batch_id,
                        'ip': raw_ip_spec,
                        'result': {'success': False, 'message': f'Endereço MAC não encontrado para {base_ip}.'}
                    }, room=sid)
                    continue
                ok = send_wake_on_lan(mac, app.logger)
                socketio.emit('batch_item_result', {
                    'batch_id': batch_id,
                    'ip': raw_ip_spec,
                    'result': {
                        'success': ok,
                        'message': f'Comando Wake-on-LAN enviado ({mac}).' if ok else 'Falha ao enviar pacote Wake-on-LAN.'
                    }
                }, room=sid)
            socketio.emit('batch_completed', {'batch_id': batch_id, 'total': len(ips)}, room=sid)
            with _ACTIVE_BATCH_LOCK:
                _ACTIVE_BATCH_CANCELLATIONS.pop(batch_id, None)
            return

        def execute_single_target(raw_ip_spec):
            if cancel_event.is_set():
                socketio.emit('batch_item_result', {
                    'batch_id': batch_id,
                    'ip': raw_ip_spec,
                    'result': {'success': False, 'message': 'Operação cancelada pelo usuário.'}
                }, room=sid)
                return

            raw_str = str(raw_ip_spec).strip()
            parts = raw_str.split('/', 1)
            ip = parts[0].strip()
            target_user = parts[1].strip() if len(parts) > 1 else None

            if not is_valid_ip(ip):
                socketio.emit('batch_item_result', {
                    'batch_id': batch_id,
                    'ip': raw_ip_spec,
                    'result': {'success': False, 'message': 'Endereço IP inválido.'}
                }, room=sid)
                return

            item_data = dict(payload)
            item_data['ip'] = ip
            item_data['action'] = action
            item_data['password'] = password
            if target_user:
                item_data['target_user'] = target_user

            if is_streaming:
                command_builder = _get_command_builder(action)
                if not command_builder:
                    socketio.emit('batch_item_result', {
                        'batch_id': batch_id,
                        'ip': raw_ip_spec,
                        'result': {'success': False, 'message': 'Ação desconhecida.'}
                    }, room=sid)
                    return

                command, _ = command_builder(item_data)
                stream_timeout = 1800 if action in ('atualizar_sistema', 'update_system') else 300

                try:
                    with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
                        gen = _stream_shell_command(ssh, command, password, timeout=stream_timeout)
                        exit_code = 0
                        try:
                            while not cancel_event.is_set():
                                line = next(gen)
                                socketio.emit('batch_stream_line', {
                                    'batch_id': batch_id,
                                    'ip': raw_ip_spec,
                                    'line': line
                                }, room=sid)
                        except StopIteration as e:
                            exit_code = e.value if e.value is not None else 0

                        if cancel_event.is_set():
                            socketio.emit('batch_item_result', {
                                'batch_id': batch_id,
                                'ip': raw_ip_spec,
                                'result': {'success': False, 'message': 'Operação cancelada pelo usuário.'}
                            }, room=sid)
                        else:
                            success = (exit_code == 0)
                            msg = "Ação concluída com sucesso." if success else f"Ação falhou com código de saída {exit_code}."
                            socketio.emit('batch_item_result', {
                                'batch_id': batch_id,
                                'ip': raw_ip_spec,
                                'result': {'success': success, 'message': msg}
                            }, room=sid)
                except Exception as e:
                    app.logger.warning(f"[BatchAction] Erro no streaming de {ip}: {e}")
                    socketio.emit('batch_item_result', {
                        'batch_id': batch_id,
                        'ip': raw_ip_spec,
                        'result': {'success': False, 'message': f"Erro: {str(e)}"}
                    }, room=sid)
            else:
                try:
                    with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
                        item_data['shell_action_handler'] = _handle_shell_action
                        result = _dispatch_ssh_action(ssh, ip, action, item_data, app.logger)
                        socketio.emit('batch_item_result', {
                            'batch_id': batch_id,
                            'ip': raw_ip_spec,
                            'result': result
                        }, room=sid)
                except Exception as e:
                    app.logger.warning(f"[BatchAction] Erro ao executar ação em {ip}: {e}")
                    socketio.emit('batch_item_result', {
                        'batch_id': batch_id,
                        'ip': raw_ip_spec,
                        'result': {'success': False, 'message': f"Falha na execução: {str(e)}"}
                    }, room=sid)

        max_workers = min(32, max(2, len(ips)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(execute_single_target, target_ip) for target_ip in ips]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    app.logger.error(f"[BatchAction] Erro no worker do lote: {exc}")

        socketio.emit('batch_completed', {'batch_id': batch_id, 'total': len(ips)}, room=sid)
        with _ACTIVE_BATCH_LOCK:
            _ACTIVE_BATCH_CANCELLATIONS.pop(batch_id, None)

    socketio.start_background_task(run_batch)

# --- Rotas para Área de Trabalho Remota (noVNC) ---
@app.route('/novnc/<path:filename>')
def serve_novnc(filename):
    """Servidor estático para a biblioteca noVNC."""
    return send_from_directory(os.path.join(APP_ROOT, 'novnc'), filename)

@app.route('/api/start-vnc', methods=['POST'])
def api_start_vnc():
    """Prepara o ambiente VNC remoto (x11vnc) via SSH e inicia websockify local."""
    data = request.json or {}
    ip = data.get('ip')
    password = data.get('password')
    username = data.get('username', 'aluno')

    if not ip:
        return jsonify({"success": False, "message": "IP da máquina alvo é obrigatório."}), 400

    display = data.get('display')
    res = ensure_remote_vnc_server(ip, username, password, app.logger, target_display=display)
    return jsonify(res)

@app.route('/api/stop-vnc', methods=['POST'])
def api_stop_vnc():
    """Encerra o proxy websockify local associado à porta."""
    data = request.json or {}
    ws_port = data.get('ws_port', 6080)
    stop_websockify_proxy(int(ws_port))
    return jsonify({"success": True, "message": f"Websockify encerrado na porta {ws_port}."})

# --- Gerenciamento Físico de URLs Pré-cadastradas (Grid View / Catálogo Educativo) ---
PRESET_URLS_FILE = os.path.join(APP_ROOT, "preset_urls.json")
DEFAULT_PRESET_URLS = [
    {
        "id": "scratch",
        "title": "Scratch MIT",
        "url": "https://scratch.mit.edu",
        "category": "Programação",
        "icon": "🐱",
        "desc": "Programação em blocos e criação de jogos",
        "badge": "Popular"
    },
    {
        "id": "kahoot",
        "title": "Kahoot! Jogos",
        "url": "https://kahoot.it",
        "category": "Jogos & Quizzes",
        "icon": "🎮",
        "desc": "Quizzes interativos e gincanas ao vivo",
        "badge": "Interativo"
    },
    {
        "id": "classroom",
        "title": "Google Sala de Aula",
        "url": "https://classroom.google.com",
        "category": "Geral",
        "icon": "🏫",
        "desc": "Turmas, tarefas e atividades Classroom",
        "badge": "Oficial"
    },
    {
        "id": "geogebra",
        "title": "GeoGebra",
        "url": "https://www.geogebra.org",
        "category": "Matemática",
        "icon": "📐",
        "desc": "Geometria dinâmica, álgebra e gráficos 3D",
        "badge": "Matemática"
    },
    {
        "id": "canva",
        "title": "Canva Educação",
        "url": "https://www.canva.com",
        "category": "Criatividade",
        "icon": "🎨",
        "desc": "Apresentações, infográficos e cartazes",
        "badge": "Design"
    },
    {
        "id": "youtube_edu",
        "title": "YouTube Educativo",
        "url": "https://www.youtube.com",
        "category": "Vídeo & Aulas",
        "icon": "▶️",
        "desc": "Vídeo-aulas, documentários e tutoriais",
        "badge": "Multimídia"
    },
    {
        "id": "matific",
        "title": "Matific Aluno",
        "url": "https://www.matific.com/bra/pt-br/login-page/",
        "category": "Matemática",
        "icon": "🔢",
        "desc": "Jogos e desafios pedagógicos de matemática",
        "badge": "Gamificado"
    },
    {
        "id": "elefante",
        "title": "Elefante Letrado",
        "url": "https://login.elefanteletrado.com.br/student",
        "category": "Alfabetização",
        "icon": "🐘",
        "desc": "Biblioteca digital e incentivo à leitura",
        "badge": "Leitura"
    },
    {
        "id": "code_org",
        "title": "Code.org",
        "url": "https://code.org",
        "category": "Programação",
        "icon": "💻",
        "desc": "Hora do Código e Ciência da Computação",
        "badge": "Programação"
    },
    {
        "id": "wordwall",
        "title": "Wordwall",
        "url": "https://wordwall.net/pt",
        "category": "Jogos & Quizzes",
        "icon": "🧩",
        "desc": "Jogos pedagógicos, roletas e palavras-cruzadas",
        "badge": "Atividades"
    },
    {
        "id": "duolingo",
        "title": "Duolingo",
        "url": "https://www.duolingo.com",
        "category": "Idiomas",
        "icon": "🦉",
        "desc": "Aprendizado de idiomas de forma gamificada",
        "badge": "Idiomas"
    },
    {
        "id": "tinkercad",
        "title": "Tinkercad 3D",
        "url": "https://www.tinkercad.com",
        "category": "Criatividade",
        "icon": "🧊",
        "desc": "Modelagem 3D, robótica e circuitos",
        "badge": "Maker / 3D"
    },
    {
        "id": "phet",
        "title": "PhET Simulações",
        "url": "https://phet.colorado.edu",
        "category": "Ciências",
        "icon": "🔬",
        "desc": "Simulações interativas de física e química",
        "badge": "Laboratório"
    }
]

@app.route('/api/preset-urls', methods=['GET'])
def get_preset_urls():
    """Retorna a lista de URLs e Catálogo Educativo salvo no arquivo físico preset_urls.json."""
    try:
        if os.path.exists(PRESET_URLS_FILE):
            with open(PRESET_URLS_FILE, 'r', encoding='utf-8') as f:
                urls = json.load(f)
                if isinstance(urls, list) and urls:
                    return jsonify({"success": True, "urls": urls, "catalog": DEFAULT_PRESET_URLS})
        with open(PRESET_URLS_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_PRESET_URLS, f, indent=2, ensure_ascii=False)
        return jsonify({"success": True, "urls": DEFAULT_PRESET_URLS, "catalog": DEFAULT_PRESET_URLS})
    except Exception as e:
        app.logger.error(f"Erro ao ler {PRESET_URLS_FILE}: {e}")
        return jsonify({"success": False, "urls": DEFAULT_PRESET_URLS, "catalog": DEFAULT_PRESET_URLS, "error": str(e)}), 500

@app.route('/api/preset-urls', methods=['POST'])
def save_preset_urls():
    """Salva a nova lista de URLs/Itens educativos no arquivo físico preset_urls.json."""
    try:
        data = request.get_json() or {}
        urls = data.get('urls')
        if not isinstance(urls, list):
            return jsonify({"success": False, "message": "O campo 'urls' deve ser uma lista."}), 400

        cleaned_items = []
        for u in urls:
            if isinstance(u, dict):
                url_val = (u.get('url') or '').strip()
                if not url_val:
                    continue
                if not url_val.startswith('http://') and not url_val.startswith('https://'):
                    url_val = 'https://' + url_val
                u['url'] = url_val
                cleaned_items.append(u)
            elif isinstance(u, str) and u.strip():
                val = u.strip()
                if not val.startswith('http://') and not val.startswith('https://'):
                    val = 'https://' + val
                cleaned_items.append({
                    "title": val.replace('https://', '').replace('http://', '').split('/')[0],
                    "url": val,
                    "category": "Personalizados",
                    "icon": "🌐",
                    "desc": "Link adicionado pelo professor",
                    "custom": True
                })

        with open(PRESET_URLS_FILE, 'w', encoding='utf-8') as f:
            json.dump(cleaned_items, f, indent=2, ensure_ascii=False)

        app.logger.info(f"[PresetURLs] Catálogo Educativo atualizado em {PRESET_URLS_FILE} ({len(cleaned_items)} itens).")
        return jsonify({"success": True, "urls": cleaned_items})
    except Exception as e:
        app.logger.error(f"Erro ao salvar em {PRESET_URLS_FILE}: {e}")
        return jsonify({"success": False, "message": f"Erro ao salvar arquivo: {str(e)}"}), 500



_THUMBNAIL_CACHE = {}
_THUMBNAIL_CACHE_MAX = 60  # Limite máximo de miniaturas em memória para evitar consumo excessivo de RAM
_THUMBNAIL_LOCK = threading.Lock()

def _thumbnail_cache_set(key, value):
    """Insere ou atualiza um item no cache de thumbnails com limite de tamanho LRU."""
    with _THUMBNAIL_LOCK:
        if key not in _THUMBNAIL_CACHE and len(_THUMBNAIL_CACHE) >= _THUMBNAIL_CACHE_MAX:
            try:
                # Remove o item mais antigo
                oldest_key = min(_THUMBNAIL_CACHE, key=lambda k: _THUMBNAIL_CACHE[k][0])
                del _THUMBNAIL_CACHE[oldest_key]
            except Exception:
                _THUMBNAIL_CACHE.clear()
        _THUMBNAIL_CACHE[key] = value

@app.route('/api/thumbnail/<path:target_spec>', methods=['GET'])
def api_thumbnail(target_spec):
    """
    Retorna uma miniatura JPEG em tempo real do host/assento remoto especificado.
    Suporta formato IP ou IP/usuario (ex: /api/thumbnail/192.168.0.101 ou /api/thumbnail/192.168.0.101/aluno1).
    """
    now = time.time()
    with _THUMBNAIL_LOCK:
        if target_spec in _THUMBNAIL_CACHE:
            ts, cached_bytes, is_error = _THUMBNAIL_CACHE[target_spec]
            # Cache de 12s para erros/offline e 6s para imagens válidas
            cache_ttl = 12.0 if is_error else 6.0
            if now - ts < cache_ttl:
                if is_error or not cached_bytes:
                    return Response("Host offline ou porta SSH inacessível.", status=503, mimetype='text/plain')
                response = Response(cached_bytes, mimetype='image/jpeg')
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                return response

    password = request.args.get('password') or request.headers.get('X-App-Password') or ''
    
    parts = target_spec.split('/', 1)
    ip = parts[0].strip()
    target_display = parts[1].strip() if len(parts) > 1 else None

    if not is_valid_ip(ip):
        return Response("IP inválido.", status=400, mimetype='text/plain')

    try:
        image_bytes = get_remote_screenshot(ip, SSH_USER, password, app.logger, target_display=target_display)
        _thumbnail_cache_set(target_spec, (now, image_bytes, False))
        response = Response(image_bytes, mimetype='image/jpeg')
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response
    except Exception as e:
        err_msg = str(e)
        if "Porta 22" in err_msg or "offline" in err_msg.lower() or "timeout" in err_msg.lower():
            app.logger.info(f"Host {target_spec} indisponível para thumbnail: {err_msg}")
        else:
            app.logger.warning(f"Falha ao capturar thumbnail para {target_spec}: {err_msg}")
            
        _thumbnail_cache_set(target_spec, (now, None, True))
            
        return Response(f"Host indisponível para thumbnail: {err_msg}", status=503, mimetype='text/plain')


@app.route('/api/ping-check', methods=['POST'])
def api_ping_check():
    """
    Verificação rápida de alcançabilidade de uma lista de IPs.
    Testa porta 22 (SSH) e 5900 (VNC) sem abrir sessão SSH completa.
    Ideal para pré-verificação do Grid VNC antes de tentar conectar.
    """
    data = request.json or {}
    ips = data.get('ips', [])

    if not ips:
        return jsonify({"success": False, "message": "Lista de IPs obrigatória."}), 400

    ips = [ip for ip in ips if is_valid_ip(ip)]

    def check_ip(ip):
        ssh_open = False
        vnc_open = False
        try:
            with socket.create_connection((ip, 22), timeout=1.0):
                ssh_open = True
        except (socket.timeout, socket.error):
            pass
        try:
            with socket.create_connection((ip, 5900), timeout=0.5):
                vnc_open = True
        except (socket.timeout, socket.error):
            pass

        if ssh_open:
            return ip, {"reachable": True, "ssh": True, "vnc": vnc_open}
        else:
            # Fallback: tenta ICMP via ping do sistema
            try:
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", "1", ip],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2
                )
                ping_ok = result.returncode == 0
            except Exception:
                ping_ok = False
            return ip, {"reachable": ping_ok, "ssh": False, "vnc": vnc_open}

    results = {}
    with ThreadPoolExecutor(max_workers=min(20, max(1, len(ips)))) as executor:
        for ip, status in executor.map(check_ip, ips):
            results[ip] = status

    return jsonify({"success": True, "results": results})


@app.route('/api/check-child-protection', methods=['POST'])
def api_check_child_protection():
    """
    Varre via SSH as máquinas conectadas/selecionadas para verificar se a
    Proteção Total Infantil está ativada.
    """
    data = request.json or {}
    ips = data.get('ips', [])
    password = get_request_password(data)

    if not ips:
        db = DatabaseManager(app.root_path)
        devices = db.get_all_devices()
        ips = [d['ip'] for d in devices if d.get('ip') and is_valid_ip(d['ip'])]

    ips = [ip for ip in ips if is_valid_ip(ip)]

    if not ips:
        return jsonify({
            "success": True,
            "is_protected": False,
            "protected_count": 0,
            "unprotected_count": 0,
            "total": 0,
            "details": {}
        })

    check_cmd = (
        "if [ -f /etc/child_protection_active ] || "
        "grep -q 'BEGIN BLOCK_CHILD_PROTECTION' /etc/hosts 2>/dev/null || "
        "[ -f /etc/chromium/policies/managed/kiosk_child_policy.json ] || "
        "[ -f /etc/opt/chrome/policies/managed/kiosk_child_policy.json ]; then "
        "echo 'PROTECTED'; else echo 'UNPROTECTED'; fi"
    )

    details = {}
    protected_count = 0

    def check_ip(ip_addr):
        try:
            with ssh_connect(ip_addr, SSH_USER, password, app.logger) as ssh:
                _, stdout, _ = ssh.exec_command(check_cmd, timeout=4)
                out = stdout.read().decode('utf-8', errors='ignore').strip()
                is_prot = "PROTECTED" in out
                return ip_addr, is_prot
        except Exception:
            return ip_addr, False

    with ThreadPoolExecutor(max_workers=min(25, max(1, len(ips)))) as executor:
        futures = [executor.submit(check_ip, ip) for ip in ips]
        for future in as_completed(futures):
            ip_addr, is_prot = future.result()
            details[ip_addr] = is_prot
            if is_prot:
                protected_count += 1

    total = len(ips)
    is_overall_protected = protected_count > 0 and (protected_count >= total / 2)

    return jsonify({
        "success": True,
        "is_protected": is_overall_protected,
        "protected_count": protected_count,
        "unprotected_count": total - protected_count,
        "total": total,
        "details": details
    })


@app.route('/api/quick-action', methods=['POST'])
def api_quick_action():
    """Executa uma ação rápida do menu de contexto do tray em todas as máquinas da rede."""
    data = request.json or {}
    action = data.get('action')

    if not action:
        return jsonify({"success": False, "message": "Ação não especificada."}), 400

    if action in ('wake_on_lan', 'ligar'):
        ip_mac_map = db.get_known_macs()
        if not ip_mac_map:
            return jsonify({"success": True, "message": "Nenhum MAC cadastrado, transmitindo WoL por broadcast."})
        wol_results = send_batch_wake_on_lan(list(ip_mac_map.values()), app.logger)
        return jsonify({"success": True, "message": f"Sinal WoL enviado para {len(wol_results)} máquinas."})

    return jsonify({"success": True, "message": f"Comando '{action}' recebido."})


@app.route('/execute-action', methods=['POST'])
def api_execute_action():
    """
    Executa uma ação em lote sobre uma lista de computadores em paralelo via SSH.
    """
    data = request.json or {}
    action = data.get('action')
    target_ips = data.get('target_ips') or data.get('ips') or []
    password = get_request_password(data)

    if not action:
        return jsonify({"success": False, "message": "Ação não especificada."}), 400

    if not target_ips:
        return jsonify({"success": False, "message": "Nenhum computador alvo especificado."}), 400

    target_ips = [ip for ip in target_ips if is_valid_ip(str(ip).split('/')[0].strip())]

    command_builder = _get_command_builder(action)
    if not command_builder:
        return jsonify({"success": False, "message": f"Ação '{action}' desconhecida."}), 400

    if callable(command_builder):
        command, err_resp = command_builder(data)
        if err_resp:
            return jsonify(err_resp), 400
    else:
        command = command_builder

    results = {}
    success_count = 0

    def run_single_target(ip_spec):
        ip_addr = str(ip_spec).split('/')[0].strip()
        try:
            with ssh_connect(ip_addr, SSH_USER, password, app.logger) as ssh:
                _, stdout, stderr = ssh.exec_command(command, timeout=10)
                out = stdout.read().decode('utf-8', errors='ignore').strip()
                err = stderr.read().decode('utf-8', errors='ignore').strip()
                msg = out or err or "Comando executado com sucesso."
                return ip_addr, True, msg
        except Exception as e:
            return ip_addr, False, str(e)

    with ThreadPoolExecutor(max_workers=min(25, max(1, len(target_ips)))) as executor:
        futures = [executor.submit(run_single_target, ip) for ip in target_ips]
        for future in as_completed(futures):
            ip_addr, ok, msg = future.result()
            results[ip_addr] = {"success": ok, "message": msg}
            if ok:
                success_count += 1

    return jsonify({
        "success": success_count > 0,
        "total": len(target_ips),
        "success_count": success_count,
        "results": results
    })


# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    # Configurações do servidor
    HOST = "0.0.0.0"
    PORT = int(os.getenv("FLASK_PORT", "5050"))

    DEV_MODE = os.getenv("DEV_MODE", "false").lower() in ("true", "1", "t")

    print(f"DEBUG: DEV_MODE (env var check) is {DEV_MODE}")
    def open_browser():
        """Abre o navegador padrão na URL da aplicação."""
        webbrowser.open_new(f'http://127.0.0.1:{PORT}/')

    if DEV_MODE:
        print(f"--> Servidor de desenvolvimento iniciado em http://{HOST}:{PORT}")
        print("--> O servidor irá recarregar automaticamente após alterações no código.")
        print("--> Pressione Ctrl+C para encerrar.")
        if not os.environ.get('WERKZEUG_RUN_MAIN'):
            threading.Timer(1.5, open_browser).start()
            start_scheduler()
        print("----------------------------------------\n")
        should_reload = False 
        
        print(f"DEBUG: Chamando socketio.run(). Host={HOST}, Port={PORT}")
        try:
            socketio.run(app, host=HOST, port=PORT, debug=True, use_reloader=should_reload, allow_unsafe_werkzeug=True)
        except Exception as e:
            print(f"ERRO CRÍTICO: socketio.run() falhou com exceção: {e}", flush=True)
    else:
        print(f"--> Servidor em execução em http://{HOST}:{PORT} (SocketIO Web SSH ativado).")
        print("--> Pressione Ctrl+C para encerrar.")
        start_scheduler()
        print("----------------------------------------\n")
        try:
            socketio.run(app, host=HOST, port=PORT, debug=False, allow_unsafe_werkzeug=True)
        except Exception as e:
            print(f"ERRO CRÍTICO: socketio.run() falhou com exceção: {e}", flush=True)
    print("DEBUG: app.py está encerrando.")

