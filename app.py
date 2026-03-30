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
from typing import Dict, Optional, Any, Tuple
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from multiprocessing import Pool, cpu_count
import json
import binascii

from flask import Flask, jsonify, request, send_from_directory, Response, Blueprint

import paramiko
from flask_cors import CORS
from waitress import serve

# --- Importações dos Módulos de Serviço Refatorados ---
from command_builder import COMMANDS, COMMAND_METADATA, _get_command_builder, CommandExecutionError, _parse_system_info
from ssh_service import ssh_connect, _handle_ssh_exception, _execute_for_each_user, _execute_shell_command, _stream_shell_command, list_sftp_backups, _handle_cleanup_wallpaper
from network_service import NetworkScanner, get_local_ip_and_range, is_valid_ip
from vnc_service import start_vnc_tunnel, find_free_port

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens (front-end)
CORS(app)

# Define o diretório raiz para servir arquivos estáticos (frontend)
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Configurações de Segurança ---
# Regex para sanitizar nomes de processos e evitar Command Injection
SAFE_PROCESS_NAME = re.compile(r'^[a-zA-Z0-9._-]+$')
FORCE_STATIC_RANGE = os.getenv("FORCE_STATIC_RANGE", "false").lower() == "true"
IP_PREFIX = os.getenv("IP_PREFIX", "192.168.1.")
IP_START = 1
IP_END = 254
IP_EXCLUSION_LIST = os.getenv("IP_EXCLUSION_LIST", "").split(",") if os.getenv("IP_EXCLUSION_LIST") else []
SSH_USER = os.getenv("SSH_USER", "aluno")
NOVNC_DIR = 'novnc'
BACKUP_ROOT_DIR = "atalhos_desativados"
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "qwe123")

def get_request_password(data: Dict) -> str:
    """Extrai a senha da requisição ou retorna a senha padrão."""
    if not data:
        return DEFAULT_PASSWORD
    return data.get('password') or DEFAULT_PASSWORD

class StorageManager:
    """Gerencia a persistência de dados de forma segura para threads."""
    def __init__(self, root_path):
        self.root = Path(root_path)
        self.files = {
            'macs': self.root / 'known_macs.json',
            'blocklist': self.root / 'ip_blocklist.json',
            'aliases': self.root / 'device_aliases.json'
        }
        self.lock = threading.Lock()
        self.data = {'macs': {}, 'blocklist': set(), 'aliases': {}}
        self.load_all()

    def load_all(self):
        try:
            if self.files['macs'].exists():
                with open(self.files['macs'], 'r') as f: self.data['macs'] = json.load(f)
            if self.files['blocklist'].exists():
                with open(self.files['blocklist'], 'r') as f: self.data['blocklist'] = set(json.load(f))
            if self.files['aliases'].exists():
                with open(self.files['aliases'], 'r') as f: self.data['aliases'] = json.load(f)
        except Exception as e:
            print(f"Erro ao carregar dados: {e}")

    def save(self, key):
        with self.lock:
            file_path = self.files[key]
            temp_data = self.data[key]
            if key == 'blocklist': temp_data = list(temp_data)
            
            if file_path.exists():
                shutil.copy2(file_path, str(file_path) + ".bak")
            
            with open(file_path, 'w') as f:
                json.dump(temp_data, f, indent=4, sort_keys=(key != 'blocklist'))

storage = StorageManager(APP_ROOT)

# Vinculando variáveis globais aos dados do StorageManager para compatibilidade
known_macs = storage.data['macs']
ip_blocklist = storage.data['blocklist']
device_aliases = storage.data['aliases']

def save_known_macs(): storage.save('macs')
def save_ip_blocklist(): storage.save('blocklist')
def save_aliases(): storage.save('aliases')

@app.route('/import-macs', methods=['POST'])
def import_macs():
    """Importa uma lista de mapeamentos IP -> MAC para o cache (known_macs)."""
    data = request.get_json()
    entries = data.get('entries', [])
    
    if not entries:
        return jsonify({"success": False, "message": "Nenhum dado fornecido para importação."}), 400

    imported_count = 0
    for entry in entries:
        ip = entry.get('ip')
        mac = entry.get('mac')
        
        if ip and mac and is_valid_ip(ip):
            # Normaliza o MAC: converte para minúsculas e substitui '-' por ':'
            mac_normalized = mac.replace('-', ':').lower().strip()
            # Validação simples de formato MAC (6 pares de hexadecimais)
            if re.match(r"^([0-9a-f]{2}[:]){5}([0-9a-f]{2})$", mac_normalized):
                known_macs[ip] = mac_normalized
                imported_count += 1
    
    if imported_count > 0:
        save_known_macs()
        return jsonify({"success": True, "message": f"{imported_count} endereços MAC importados e salvos com sucesso."})
    else:
        return jsonify({"success": False, "message": "Nenhum par IP/MAC válido encontrado para importar."}), 400

def _harvest_macs_from_arp():
    """Lê a tabela ARP do sistema para atualizar o cache de MACs (via network_service)."""
    # Implementação simplificada chamando o scanner
    pass

# --- Rota para Descobrir IPs ---
@app.route('/discover-ips', methods=['GET'])
def discover_ips():
    """
    Escaneia a rede e retorna a lista de IPs com a porta 22 aberta.
    """
    ip_prefix, _, _, server_ip, gateway_ip = get_local_ip_and_range()
    
    try:
        scanner = NetworkScanner(app.logger)
        active_ips = scanner.scan()
    except Exception as e:
        app.logger.error(f"Erro durante a descoberta paralela de IPs: {e}")
        return jsonify({"success": False, "message": f"Erro ao escanear a rede: {e}"}), 500

    # Filtra os IPs descobertos para garantir que respeitem o intervalo IP_START e IP_END
    # definido no ambiente, evitando capturar dispositivos indesejados na mesma sub-rede.
    if active_ips:
        active_ips = [
            item for item in active_ips 
            if is_valid_ip(item['ip']) and 
            IP_START <= int(item['ip'].split('.')[-1]) <= IP_END
        ]

    # Cria uma lista de exclusão abrangente para evitar que IPs indesejados apareçam.
    # Usar um set (conjunto) é mais eficiente para verificações de 'in'.
    comprehensive_exclusion_list = set(IP_EXCLUSION_LIST) | ip_blocklist # Usa a blocklist carregada
    if server_ip:
        comprehensive_exclusion_list.add(server_ip)
    if gateway_ip:
        comprehensive_exclusion_list.add(gateway_ip)

    # Filtra os IPs ativos e os da lista de exclusão manual.
    initial_count = len(active_ips)
    active_ips = [item for item in active_ips if item['ip'] not in comprehensive_exclusion_list]
    removed_count = initial_count - len(active_ips)
    if removed_count > 0:
        app.logger.info(f"Removidos {removed_count} IPs da lista de exclusão (servidor, gateway, manual).")

    # Tenta colher MACs da tabela ARP do sistema para IPs descobertos (especialmente se usou nmap)
    _harvest_macs_from_arp()

    # Adiciona IPs conhecidos do cache que não foram detectados como online.
    # Isso permite que apareçam na lista para que a ação "Ligar" (Wake-on-LAN) possa ser usada.
    online_ips_set = {item['ip'] for item in active_ips}
    for ip in known_macs.keys():
        if ip not in online_ips_set and ip not in comprehensive_exclusion_list:
            # Adiciona IPs do cache como offline para permitir WoL.
            # Agora filtramos pelo prefixo atual para evitar que IPs de redes antigas
            # ou de outras interfaces (como VPNs) apareçam na lista.
            if ip.startswith(ip_prefix):
                if IP_START <= int(ip.split('.')[-1]) <= IP_END:
                    active_ips.append({'ip': ip, 'type': 'offline'})

    # Ordena a lista final de IPs, se houver, pelo último octeto.
    if active_ips:
        # Ordenação robusta usando ipaddress (funciona corretamente com múltiplas sub-redes)
        active_ips.sort(key=lambda item: ipaddress.ip_address(item['ip']))

    return jsonify({"success": True, "ips": active_ips}), 200

@app.route('/block-ip', methods=['POST'])
def block_ip():
    """Adiciona um IP à blocklist permanente e o remove do cache de MACs."""
    data = request.get_json()
    ip_to_block = data.get('ip')

    if not ip_to_block:
        return jsonify({"success": False, "message": "Nenhum IP fornecido."}), 400

    global ip_blocklist, known_macs

    # Adiciona à blocklist em memória
    ip_blocklist.add(ip_to_block)
    # Salva a blocklist no disco
    save_ip_blocklist()

    # Remove do cache de MACs em memória, se existir
    if ip_to_block in known_macs:
        del known_macs[ip_to_block]
        # Salva o cache de MACs atualizado no disco
        save_known_macs()
    
    app.logger.info(f"IP {ip_to_block} adicionado à blocklist e removido do cache.")
    return jsonify({"success": True, "message": f"IP {ip_to_block} foi bloqueado e não aparecerá mais."})

@app.route('/get-blocklist', methods=['GET'])
def get_blocklist():
    """Retorna a lista de IPs atualmente na blocklist."""
    # A blocklist já está em memória, então apenas a retornamos.
    # Convertemos o set para uma lista para que seja serializável em JSON e a ordenamos.
    return jsonify({"success": True, "blocklist": sorted(list(ip_blocklist))})

@app.route('/unblock-ip', methods=['POST'])
def unblock_ip():
    """Remove um IP da blocklist permanente."""
    data = request.get_json()
    ip_to_unblock = data.get('ip')

    if not ip_to_unblock:
        return jsonify({"success": False, "message": "Nenhum IP fornecido."}), 400

    global ip_blocklist
    if ip_to_unblock in ip_blocklist:
        ip_blocklist.remove(ip_to_unblock)
        save_ip_blocklist()
        app.logger.info(f"IP {ip_to_unblock} removido da blocklist.")
        return jsonify({"success": True, "message": f"IP {ip_to_unblock} foi desbloqueado."})
    else:
        return jsonify({"success": False, "message": f"IP {ip_to_unblock} não encontrado na blocklist."}), 404

@app.route('/get-aliases', methods=['GET'])
def get_aliases():
    """Retorna todos os apelidos configurados."""
    return jsonify({"success": True, "aliases": device_aliases})

@app.route('/set-alias', methods=['POST'])
def set_alias():
    """Define ou remove um apelido para um IP."""
    data = request.get_json()
    ip = data.get('ip')
    alias = data.get('alias')

    if not ip:
        return jsonify({"success": False, "message": "IP é obrigatório."}), 400

    if alias and alias.strip():
        device_aliases[ip] = alias.strip()
    else:
        # Se o alias estiver vazio, removemos a entrada
        if ip in device_aliases:
            del device_aliases[ip]
    
    save_aliases()
    return jsonify({"success": True, "message": "Apelido atualizado."})

@app.route('/api/metadata', methods=['GET'])
def get_metadata():
    """Retorna os metadados das ações para o frontend configurar o streaming dinamicamente."""
    return jsonify({"success": True, "metadata": COMMAND_METADATA})

@app.route('/check-status', methods=['POST'])
def check_status():
    """
    Verifica rapidamente o status da conexão SSH para uma lista de IPs.
    """
    data = request.get_json()
    ips = data.get('ips', [])
    password = get_request_password(data)

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
            # Otimização: Verifica se a porta 22 está aberta antes de tentar o handshake SSH completo.
            if not is_port_open(ip, 22):
                return ip, {'status': 'offline', 'user_count': 0}

            # Usa um timeout curto para uma verificação rápida.
            with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
                # MELHORIA: Contamos o número total de sessões (who | wc -l) em vez de usuários únicos.
                # Isso garante que o ícone de multiusuário apareça em sistemas multiseat
                # mesmo quando todos os terminais usam o mesmo login de usuário.
                stdin, stdout, stderr = ssh.exec_command("who | wc -l", timeout=5)
                count_str = stdout.read().decode().strip()
                user_count = int(count_str) if count_str.isdigit() else 1
                
                return ip, {'status': 'online', 'user_count': user_count}
        except paramiko.AuthenticationException:
            # A máquina está online, mas a senha está errada.
            return ip, {'status': 'auth_error', 'user_count': 0}
        except Exception:
            # Qualquer outra exceção (timeout, conexão recusada) significa offline.
            return ip, {'status': 'offline', 'user_count': 0}

    # Usa ThreadPoolExecutor para limitar o número de threads simultâneas (ex: 30)
    with ThreadPoolExecutor(max_workers=30) as executor:
        future_to_ip = {executor.submit(check_single_ip, ip): ip for ip in ips}
        for future in as_completed(future_to_ip):
            ip, status = future.result()
            statuses[ip] = status

    return jsonify({"success": True, "statuses": statuses})
# --- Rota para servir o Frontend e o noVNC ---

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
        return {"success": False, "message": "Ação desconhecida."}
        return {"success": False, "message": "Ação desconhecida. Tente reiniciar o servidor backend.", "details": f"A ação '{action}' não consta na lista de comandos carregados. Isso ocorre quando o código é atualizado mas o servidor não foi reiniciado."}

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

@app.route('/stream-action', methods=['POST'])
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

    try:
        with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
            backups_by_dir = list_sftp_backups(ssh, BACKUP_ROOT_DIR)
            return jsonify({"success": True, "backups": backups_by_dir}), 200

    except (paramiko.AuthenticationException, paramiko.SSHException, Exception) as e:
        response, status_code = _handle_ssh_exception(e, ip, 'list-backups', app.logger)
        return jsonify(response), status_code

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
    
    # Ação de Wake-on-LAN (Ligar)
    if action == 'ligar':
        success, msg = send_wake_on_lan(ip)
        return jsonify({"success": success, "message": msg}), 200 if success else 404

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
            # Procura a ação no dicionário de manipuladores.
            handler = ACTION_HANDLERS.get(action)

            if handler == _execute_for_each_user:
                # Se o manipulador for para ações por usuário, chama-o.
                result_dict = _execute_for_each_user(ssh, action, data, app.logger)
                return jsonify(result_dict), 200 if result_dict.get('success') else 207 # 207 para Multi-Status
            elif handler == _handle_cleanup_wallpaper:
                 # Manipulador específico para cleanup_wallpaper.
                message, _, errors = _handle_cleanup_wallpaper(ssh, data)
                return jsonify({"success": not errors, "message": message, "details": errors}), 200 if not errors else 500
            else:
                # Se a ação não estiver no dicionário, trata como uma ação shell genérica (de sistema).
                result = _handle_shell_action(ssh, None, action, data)
                
                # _handle_shell_action agora retorna um dicionário.
                status_code = 500 if not result.get('success') else 200
                if not result.get('success'):
                    # Retorna 400 (Bad Request) se a ação for desconhecida, para diferenciar de erro de servidor (500)
                    status_code = 400 if "Ação desconhecida" in result.get('message', '') else 500
                else:
                    status_code = 200
                
                return jsonify(result), status_code # jsonify o dicionário aqui.

    except (paramiko.SSHException, socket.error) as e:
        # Captura todas as exceções de SSH e de socket (como timeouts de conexão)
        # e as delega para o manipulador de exceções padronizado.
        response, status_code = _handle_ssh_exception(e, ip, action, app.logger)
        return jsonify(response), status_code
    except Exception as e:
        # Captura qualquer outro erro inesperado para evitar que o servidor trave.
        app.logger.error(f"Erro inesperado e não tratado na rota /gerenciar_atalhos_ip: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Ocorreu um erro interno inesperado no servidor."}), 500

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
            'grid_view.html', 'grid_view.js',
            'app.py', 'command_builder.py', 'ssh_service.py', # Inclui os módulos Python
            'actions.sh',
            'novnc/' # Inclui a pasta novnc inteira
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
        backup_path = os.path.join(backup_dir, backup_filename)

        if not os.path.isfile(backup_path):
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
        source_dir = os.path.dirname(os.path.abspath(__file__))
        backup_dir = os.path.join(source_dir, 'backups_app')
        backup_path = os.path.join(backup_dir, backup_filename)

        # Medida de segurança: verifica se o caminho é realmente dentro do diretório de backups
        # e se o nome do arquivo não contém '..' para evitar path traversal.
        normalized_backup_path = os.path.normpath(backup_path)
        if not os.path.abspath(normalized_backup_path).startswith(os.path.abspath(backup_dir)):
            app.logger.warning(f"Tentativa de exclusão de arquivo inválida: {backup_filename}")
            return jsonify({'success': False, 'message': 'Nome de arquivo inválido.'}), 400

        if not os.path.isfile(backup_path):
            return jsonify({'success': False, 'message': 'Arquivo de backup não encontrado.'}), 404

        os.remove(backup_path)
        app.logger.info(f"Backup da aplicação excluído com sucesso: {backup_filename}")
        return jsonify({'success': True, 'message': 'Backup excluído com sucesso.'})

    except Exception as e:
        app.logger.error(f"Erro ao excluir backup da aplicação: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Falha ao excluir o backup: {e}'}), 500

# --- Rotas para Visualização de Tela (VNC) ---

@app.route('/start-vnc', methods=['POST'])
def start_vnc():
    """
    Inicia uma sessão VNC em um cliente e cria um túnel SSH para ela.
    """
    data = request.get_json()
    ip = data.get('ip')
    password = get_request_password(data)

    if ip and not is_valid_ip(ip):
        return jsonify({"success": False, "message": "Endereço IP inválido."}), 400

    if not all([ip, password]):
        return jsonify({"success": False, "message": "IP e senha são obrigatórios."}), 400

    local_port = find_free_port()
    success, message = start_vnc_tunnel(ip, SSH_USER, password, local_port, app.logger)

    if success:
        server_host = request.host.split(':')[0]
        # Usa 'vnc_lite.html' que é otimizado para ser embutido (sem a barra de controle superior).
        # Adiciona o parâmetro 'autoconnect=true' para iniciar a conexão automaticamente.
        vnc_url = f"/novnc/vnc_lite.html?host={server_host}&port={local_port}&path=websockify&autoconnect=true&token={ip}"
        return jsonify({"success": True, "url": vnc_url, "port": local_port, "token": ip})
    else:
        return jsonify({"success": False, "message": message}), 500

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
        print("----------------------------------------\n")
        # Lista de arquivos do frontend para observar.
        # Quando um desses arquivos for alterado, o servidor reiniciará.
        frontend_files = [
            os.path.join(APP_ROOT, 'index.html'),
            os.path.join(APP_ROOT, 'grid_view.html'),
            os.path.join(APP_ROOT, 'grid_view.js'),
        ]
        print(f"DEBUG: Chamando app.run() em modo de desenvolvimento. Host={HOST}, Port={PORT}")
        try:
            # Removido 'extra_files=frontend_files' para aumentar a estabilidade no WSL.
            # A observação de arquivos em sistemas de arquivos montados (/mnt/c) pode ser instável.
            app.run(host=HOST, port=PORT, debug=True, use_reloader=False)
        except Exception as e:
            print(f"ERRO CRÍTICO: app.run() falhou com exceção: {e}", flush=True)
    else:
        # Em modo de produção, usa o servidor Waitress, que é mais robusto.
        THREADS = 16
        print(f"--> Servidor de produção (Waitress) iniciado em http://{HOST}:{PORT} com {THREADS} threads.")
        print("--> Pressione Ctrl+C para encerrar.")
        print("----------------------------------------\n")
        try:
            serve(app, host=HOST, port=PORT, threads=THREADS)
        except Exception as e:
            print(f"ERRO CRÍTICO: serve() (Waitress) falhou com exceção: {e}", flush=True)
    print("DEBUG: app.py está encerrando.")
