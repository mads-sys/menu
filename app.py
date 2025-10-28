import os
import platform
import subprocess
import socket
import threading
import re
import time
import webbrowser
import signal
from typing import Dict, Optional, Any, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import Pool, cpu_count

import paramiko
from flask import Flask, jsonify, request, send_from_directory, Response, Blueprint
from flask_cors import CORS
from waitress import serve

# --- Importações dos Módulos de Serviço Refatorados ---
from command_builder import COMMANDS, _get_command_builder, CommandExecutionError, _parse_system_info
from ssh_service import ssh_connect, _handle_ssh_exception, _execute_for_each_user, _execute_shell_command, _stream_shell_command, list_sftp_backups, list_system_backups, _handle_cleanup_wallpaper

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens (front-end)
CORS(app)

# Define o diretório raiz para servir arquivos estáticos (frontend)
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Configuração da Faixa de IPs ---
# Para forçar a busca na faixa estática abaixo, defina FORCE_STATIC_RANGE como True.
FORCE_STATIC_RANGE = False
# Define uma faixa de IPs estática para a busca.
IP_PREFIX = "192.168.0."
IP_START = 1
IP_END = 254
# Lista de IPs a serem sempre excluídos dos resultados da busca (ex: gateway, servidor).
# Adicione aqui os IPs que você não quer que apareçam na lista.
IP_EXCLUSION_LIST = ["192.168.0.1"]


# --- Configurações Lidas do Ambiente (com valores padrão) ---
SSH_USER = os.getenv("SSH_USER", "aluno") # Usuário padrão para conexão, que deve ter privilégios sudo.
NOVNC_DIR = 'novnc' # Caminho relativo para o Blueprint

# --- Verificação Crítica de Ambiente ---
# Garante que o diretório e o arquivo principal do noVNC existam.
if not os.path.isdir(os.path.join(APP_ROOT, NOVNC_DIR)) or not os.path.isfile(os.path.join(APP_ROOT, NOVNC_DIR, 'vnc.html')):
    print(f"FATAL: O diretório '{NOVNC_DIR}' ou o arquivo '{os.path.join(NOVNC_DIR, 'vnc.html')}' não foi encontrado.")
    print("Verifique se a pasta 'novnc' com os arquivos do cliente noVNC está no mesmo diretório que app.py.")
    exit(1)

# --- Gerenciamento de Processos e Portas ---
vnc_processes: Dict[str, subprocess.Popen] = {}
BACKUP_ROOT_DIR = "atalhos_desativados"

# --- Detecção de Ambiente ---
IS_WSL = 'microsoft' in platform.uname().release.lower()

def _get_default_gateway() -> Optional[str]:
    """
    Tenta encontrar o endereço IP do gateway padrão da rede em diferentes sistemas operacionais.
    """
    system = platform.system()
    try:
        if system == "Linux":
            # Executa 'ip route' e filtra a linha que começa com 'default'
            result = subprocess.run(['ip', 'route'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if line.startswith('default via'):
                    # Extrai o IP, que é a terceira palavra. Ex: 'default via 192.168.1.1 dev ...'
                    return line.split()[2]
        elif system == "Windows":
            # Executa 'route print' e procura pela rota padrão '0.0.0.0'
            result = subprocess.run(['route', 'print', '0.0.0.0'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                # A linha relevante contém '0.0.0.0' duas vezes e o gateway
                if '0.0.0.0' in line and 'On-link' not in line:
                    parts = line.split()
                    if len(parts) > 3:
                        # O gateway é geralmente o terceiro item não vazio
                        return parts[3]
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError) as e:
        app.logger.warning(f"Não foi possível obter o gateway padrão com o método principal: {e}")
    return None

def _get_windows_host_ip() -> Optional[str]:
    """Executa ipconfig.exe dentro do WSL para encontrar o IP do host Windows."""
    try:
        # Executa o ipconfig do Windows e captura a saída
        result = subprocess.run(['ipconfig.exe'], capture_output=True, text=True, check=True, encoding='cp850')
        # Procura por adaptadores Ethernet ou Wi-Fi
        for line in result.stdout.splitlines():
            if 'IPv4 Address' in line or 'Endereço IPv4' in line:
                # Extrai o endereço IP da linha
                ip = line.split(':')[-1].strip()
                # Ignora os IPs da rede virtual do WSL
                if not ip.startswith('172.'):
                    return ip
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError) as e:
        app.logger.warning(f"Falha ao obter o IP do host Windows via ipconfig.exe: {e}")
    return None

# --- Funções de Detecção de Rede ---
def get_local_ip_and_range() -> tuple[str, str, list[str], Optional[str], Optional[str]]:
    """
    Detecta dinamicamente o IP local do servidor e define a faixa de busca para a sub-rede correspondente.
    Se a detecção falhar, recorre à faixa estática como fallback.
    Retorna (ip_prefix, nmap_range, ips_to_check, server_ip, gateway_ip).
    server_ip é o IP da interface do servidor na rede local.
    """
    base_ip = None
    if not FORCE_STATIC_RANGE:
        if IS_WSL:
            app.logger.info("Ambiente WSL detectado. Tentando obter o IP do host Windows...")
            base_ip = _get_windows_host_ip()
            log_source = "host Windows (ipconfig.exe)"
        else:
            log_source = "IP local do servidor"
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                base_ip = s.getsockname()[0]

        if base_ip:
            gateway_ip = _get_default_gateway() # Obtém o IP do gateway
            ip_prefix = ".".join(base_ip.split('.')[:-1]) + "."
            nmap_range = f"{ip_prefix}0/24" # Ex: 192.168.1.0/24
            app.logger.info(f"Sub-rede detectada via {log_source}: {nmap_range}")
            ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
            return ip_prefix, nmap_range, ips_to_check, base_ip, gateway_ip
    
    # Fallback para a faixa estática se a detecção dinâmica falhar ou for forçada
    app.logger.warning(f"Usando faixa de IP estática como fallback: {IP_PREFIX}{IP_START}-{IP_END}")
    gateway_ip = _get_default_gateway() # Tenta obter o gateway mesmo no fallback
    ip_prefix = IP_PREFIX
    nmap_range = f"{ip_prefix}0/24"
    ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
    return ip_prefix, nmap_range, ips_to_check, None, gateway_ip

# --- Função auxiliar para descobrir IPs ---
def check_ssh_port(ip: str) -> Optional[str]:
    """
    Tenta estabelecer uma conexão de socket na porta 22 (SSH) para verificar se um host está ativo.
    Este método é mais confiável do que o ping, que pode ser bloqueado por firewalls.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)  # Aumenta o timeout para 1.5 segundos para mais confiabilidade
    try:
        # Tenta conectar na porta 22
        if sock.connect_ex((ip, 22)) == 0:
            return ip
    except socket.error:
        pass  # Ignora erros de conexão, pois estamos apenas testando
    finally:
        sock.close()
    return None

def _find_windows_nmap() -> str:
    """
    No WSL, tenta encontrar o executável do Nmap no Windows.
    Procura primeiro no PATH, depois em locais de instalação comuns.
    Retorna o comando a ser usado (seja 'nmap' ou o caminho completo).
    """
    # Script PowerShell para encontrar o caminho do nmap.exe
    ps_command = """
        $nmap_path = (Get-Command nmap.exe -ErrorAction SilentlyContinue).Source
        if (!$nmap_path) { $nmap_path = Resolve-Path "C:\\Program Files (x86)\\Nmap\\nmap.exe" -ErrorAction SilentlyContinue }
        if (!$nmap_path) { $nmap_path = Resolve-Path "C:\\Program Files\\Nmap\\nmap.exe" -ErrorAction SilentlyContinue }
        Write-Output $nmap_path
    """
    result = subprocess.run(["powershell.exe", "-Command", ps_command], capture_output=True, text=True, encoding='utf-8')
    found_path = result.stdout.strip()
    # Se um caminho foi encontrado, o envolve em aspas para segurança.
    # Caso contrário, usa 'nmap.exe', que o PowerShell pode encontrar se estiver no PATH.
    return f'"{found_path}"' if found_path else "nmap.exe"

def discover_ips_with_nmap(ip_range: str, ip_prefix: str) -> Optional[list[str]]:
    """Usa o nmap para uma descoberta de rede rápida e eficiente."""
    try:
        # Define a codificação correta com base no ambiente.
        # O PowerShell no Windows geralmente usa a codificação de console 'cp850'.
        encoding = 'cp850' if IS_WSL else 'utf-8'

        if IS_WSL:
            # Abordagem robusta para WSL:
            # 1. Encontra o caminho do nmap.exe de forma inteligente.
            # 2. Executa o Nmap via PowerShell, capturando a saída diretamente.
            nmap_executable = _find_windows_nmap()
            # O Nmap é instruído a enviar a saída para o stdout ('-oG -'), que é capturado pelo subprocess.
            nmap_command_str = f"& {nmap_executable} -sn -T4 -oG - {ip_range}"
            command = ["powershell.exe", "-Command", nmap_command_str]
        else:
            # Em um ambiente Linux nativo, o comportamento padrão é mantido.
            # -oG - : Saída em formato "grepável" para o stdout
            command = ["nmap", "-sn", "-T4", "-oG", "-", ip_range]

        # Executa o comando, especificando a codificação correta para decodificar a saída.
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, encoding=encoding)
        
        # --- DEBUGGING: Loga a saída bruta do Nmap ---
        if IS_WSL:
            app.logger.debug(f"Nmap (via PowerShell) stdout:\n{result.stdout}")
            app.logger.debug(f"Nmap (via PowerShell) stderr:\n{result.stderr}")
        # --- FIM DEBUGGING ---

        # Verificação específica para o erro "comando não encontrado" no PowerShell
        if IS_WSL and result.stderr and ("não é reconhecido" in result.stderr or "is not recognized" in result.stderr):
            error_message = (
                "O comando 'nmap' não foi encontrado pelo PowerShell. "
                "Isso significa que o Nmap não está instalado no Windows ou não foi adicionado ao PATH do sistema. "
                "Por favor, instale o Nmap para Windows (https://nmap.org/download.html) e garanta que a opção "
                "para adicioná-lo ao PATH esteja marcada durante a instalação."
            )
            app.logger.error(error_message)
            return None # Usa o método de fallback

        active_ips = []
        for line in result.stdout.splitlines():
            # Procura por linhas que indicam um host ativo
            if "Host:" in line and "Status: Up" in line:
                # Extrai o IP da linha. Ex: "Host: 192.168.0.101 () Status: Up"
                parts = line.split()
                if len(parts) > 1:
                    ip = parts[1]
                    # Valida se o IP pertence à sub-rede detectada
                    if ip.startswith(ip_prefix):
                        active_ips.append(ip)
        
        return active_ips
    except PermissionError as e:
        error_message = (
            "Permissão negada ao tentar executar 'nmap.exe'. "
            "Isso geralmente ocorre no WSL quando o drive do Windows está montado com a opção 'noexec'. "
            "Verifique seu arquivo /etc/wsl.conf e reinicie o WSL."
        )
        app.logger.error(f"Falha de permissão ao usar nmap: {e}. Detalhes: {error_message}")
        return None # Usa o método de fallback
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        app.logger.warning(f"Falha ao usar nmap ({e}). Usando método de fallback (verificação de porta).")
        # Retorna None para indicar que o método de fallback deve ser usado
        return None

def discover_ips_with_arp_scan(ips_to_check: list[str]) -> Optional[list[str]]:
    """Usa o arp-scan para uma descoberta de rede local extremamente rápida."""
    # arp-scan não funciona corretamente na rede NAT do WSL2 para descobrir a LAN física.
    if IS_WSL:
        app.logger.info("PULANDO arp-scan: não é eficaz no ambiente WSL2.")
        return None

    try:
        # Usa --localnet para escanear toda a sub-rede local, que é o método mais
        # rápido e confiável para o arp-scan. O script filtrará os resultados depois.
        command = ["sudo", "arp-scan", "--localnet", "--numeric", "--quiet"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)

        active_ips = []
        # A saída do arp-scan é geralmente "IP_address\tMAC_address"
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].count('.') == 3:
                ip = parts[0]
                active_ips.append(ip)
        return active_ips

    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        app.logger.warning(f"Falha ao usar arp-scan ({e}). Tentando próximo método.")
        return None

def _check_ssh_ports_in_parallel(ips_to_check: list[str]) -> list[str]:
    """Função auxiliar de nível superior para verificar portas SSH em paralelo."""
    # Usa um pool de processos para verificar as portas SSH.
    with Pool(processes=cpu_count()) as pool:
        return [res for res in pool.imap_unordered(check_ssh_port, ips_to_check) if res]

# --- Rota para Descobrir IPs ---
@app.route('/discover-ips', methods=['GET'])
def discover_ips():
    """
    Escaneia a rede usando múltiplos métodos em paralelo e retorna o primeiro resultado bem-sucedido.
    """
    ip_prefix, nmap_range, ips_to_check, server_ip, gateway_ip = get_local_ip_and_range()
    app.logger.info(f"Iniciando busca de IPs na faixa de {IP_START} a {IP_END}...")

    active_ips = []
    # Timeout global para a descoberta, evitando que a aplicação fique presa.
    # 30 segundos é um limite seguro para a maioria das redes locais.
    DISCOVERY_TIMEOUT = 30

    # Lista das funções de descoberta a serem executadas em paralelo.
    discovery_tasks = {
        discover_ips_with_arp_scan: (ips_to_check,),
        discover_ips_with_nmap: (nmap_range, ip_prefix,),
        _check_ssh_ports_in_parallel: (ips_to_check,)
    }

    try:
        # Usa ProcessPoolExecutor para uma API mais moderna e robusta.
        with ProcessPoolExecutor(max_workers=len(discovery_tasks)) as executor:
            # Submete todas as tarefas e cria um dicionário de futuros para resultados.
            future_to_task = {executor.submit(func, *args): func for func, args in discovery_tasks.items()}

            # 'as_completed' retorna os futuros à medida que eles terminam.
            for future in as_completed(future_to_task, timeout=DISCOVERY_TIMEOUT):
                result_ips = future.result()
                if result_ips:  # Se o resultado não for vazio
                    active_ips = result_ips
                    break  # Sai do loop assim que o primeiro resultado válido for encontrado.

    except Exception as e:
        app.logger.error(f"Erro durante a descoberta paralela de IPs: {e}")
        return jsonify({"success": False, "message": f"Erro ao escanear a rede: {e}"}), 500

    # Filtra o IP do próprio servidor da lista de resultados.
    if server_ip and active_ips and server_ip in active_ips:
        app.logger.info(f"Removendo o IP do próprio servidor ({server_ip}) da lista de resultados.")
        active_ips.remove(server_ip)

    # Filtra o IP do gateway da lista de resultados.
    if gateway_ip and active_ips and gateway_ip in active_ips:
        app.logger.info(f"Removendo o IP do gateway ({gateway_ip}) da lista de resultados.")
        active_ips.remove(gateway_ip)
    
    # Filtra quaisquer IPs da lista de exclusão manual.
    if active_ips and IP_EXCLUSION_LIST:
        initial_count = len(active_ips)
        active_ips = [ip for ip in active_ips if ip not in IP_EXCLUSION_LIST]
        app.logger.info(f"Removidos {initial_count - len(active_ips)} IPs da lista de exclusão manual.")

    # Ordena a lista final de IPs, se houver, pelo último octeto.
    if active_ips:
        active_ips.sort(key=lambda ip: int(ip.split('.')[-1]))

    return jsonify({"success": True, "ips": active_ips}), 200

@app.route('/check-status', methods=['POST'])
def check_status():
    """
    Verifica rapidamente o status da conexão SSH para uma lista de IPs.
    """
    data = request.get_json()
    ips = data.get('ips', [])
    password = data.get('password')

    if not ips:
        return jsonify({"success": False, "message": "Nenhuma lista de IPs fornecida."}), 400

    statuses = {}
    threads = []

    def check_single_ip(ip):
        """Função executada em uma thread para verificar um único IP."""
        try:
            # Usa um timeout curto para uma verificação rápida.
            with ssh_connect(ip, SSH_USER, password) as ssh:
                # Se a conexão for bem-sucedida, o host está online.
                statuses[ip] = 'online'
        except paramiko.AuthenticationException:
            # A máquina está online, mas a senha está errada.
            statuses[ip] = 'auth_error'
        except Exception:
            # Qualquer outra exceção (timeout, conexão recusada) significa offline.
            statuses[ip] = 'offline'

    for ip in ips:
        thread = threading.Thread(target=check_single_ip, args=(ip,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    return jsonify({"success": True, "statuses": statuses})
# --- Rota para servir o Frontend e o noVNC ---

# Cria um Blueprint para servir os arquivos estáticos do noVNC.
# Esta é a maneira mais robusta de servir um diretório inteiro sob um prefixo de URL.
novnc_bp = Blueprint('novnc_bp', __name__, static_folder=NOVNC_DIR, static_url_path='/novnc')
app.register_blueprint(novnc_bp)

@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def serve_frontend(path: str):
    """
    Serve o index.html para a rota raiz e outros arquivos estáticos (CSS, JS).
    """
    return send_from_directory(APP_ROOT, path)


# --- Funções de Manipulação de Ações (Refatoradas de 'gerenciar_atalhos_ip') ---

def _handle_shell_action(ssh: paramiko.SSHClient, username: Optional[str], action: str, data: Dict[str, Any]):
    """Lida com ações que executam comandos shell."""
    ip = data.get('ip')
    password = data.get('password')
    command_builder = _get_command_builder(action)

    if not command_builder:
        return jsonify({"success": False, "message": "Ação desconhecida."}), 400

    # Constrói o comando
    if callable(command_builder):
        command, error_response = command_builder(data)
        if error_response:
            return jsonify(error_response[0]), error_response[1]
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
        output, warnings, _ = _execute_shell_command(ssh, command, password, timeout=timeout, username=username)
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

    # A operação é um sucesso mesmo com avisos.
    return {"success": True, "message": output or "Ação executada com sucesso.", "details": warnings}

@app.route('/stream-action', methods=['POST'])
def stream_action():
    """
    Executa uma ação e transmite a saída em tempo real.
    Ideal para comandos de longa duração como 'atualizar_sistema'.
    """
    data = request.get_json()
    ip = data.get('ip')
    action = data.get('action')
    password = data.get('password')

    if not all([ip, action, password]):
        return Response("IP, ação e senha são obrigatórios.", status=400, mimetype='text/plain')

    command_builder = _get_command_builder(action)
    if not command_builder:
        return Response("Ação desconhecida.", status=400, mimetype='text/plain')

    command, _ = command_builder(data)

    def generate_stream():
        try:
            with ssh_connect(ip, SSH_USER, password) as ssh:
                # Usa a função de streaming do ssh_service
                exit_code = yield from _stream_shell_command(ssh, command, password)
                
                # Envia um marcador de finalização com o código de saída
                yield f"__STREAM_END__:{exit_code}\n"

        except Exception as e:
            logger.error(f"Erro de streaming na ação '{action}' em {ip}: {e}")
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
    password = data.get('password')

    if not all([ip, password]):
        return jsonify({"success": False, "message": "IP e senha são obrigatórios."}), 400

    try:
        with ssh_connect(ip, SSH_USER, password) as ssh:
            backups_by_dir = list_sftp_backups(ssh, BACKUP_ROOT_DIR)
            return jsonify({"success": True, "backups": backups_by_dir}), 200

    except (paramiko.AuthenticationException, paramiko.SSHException, Exception) as e:
        response, status_code = _handle_ssh_exception(e, ip, 'list-backups', app.logger)
        return jsonify(response), status_code

# --- Rota para Listar Backups de Sistema ---
@app.route('/list-system-backups', methods=['POST'])
def list_system_backups_route():
    """
    Conecta a um IP e lista os arquivos de backup de sistema disponíveis.
    """
    data = request.get_json()
    ip = data.get('ip')
    password = data.get('password')

    if not all([ip, password]):
        return jsonify({"success": False, "message": "IP e senha são obrigatórios."}), 400

    try:
        with ssh_connect(ip, SSH_USER, password) as ssh:
            backup_files = list_system_backups(ssh)
            return jsonify({"success": True, "backups": backup_files}), 200
    except (paramiko.AuthenticationException, paramiko.SSHException, Exception) as e:
        response, status_code = _handle_ssh_exception(e, ip, 'list-system-backups', app.logger)
        return jsonify(response), status_code

# --- Rota Principal para Gerenciar Ações via SSH ---
@app.route('/gerenciar_atalhos_ip', methods=['POST'])
def gerenciar_atalhos_ip():
    """
    Recebe as informações do frontend, conecta via SSH e despacha a ação apropriada.
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Requisição inválida."}), 400

    ip = data.get('ip')
    action = data.get('action')
    password = data.get('password')

    if not all([ip, action, password]):
        return jsonify({"success": False, "message": "IP, ação e senha são obrigatórios."}), 400
    
    # Ações locais que não precisam de IP ou conexão SSH são tratadas primeiro.
    if action == 'backup_aplicacao':
        # Chama a função de backup diretamente e retorna o resultado.
        return backup_application()


    # Ações que são executadas por usuário
    user_specific_actions = [
        'desativar', 'ativar', 'mostrar_sistema', 'ocultar_sistema',
        'limpar_imagens', 'desativar_barra_tarefas', 'ativar_barra_tarefas',
        'bloquear_barra_tarefas', 'desbloquear_barra_tarefas', 'definir_firefox_padrao',
        'definir_chrome_padrao', 'desativar_perifericos', 'ativar_perifericos',
        'desativar_botao_direito', 'ativar_botao_direito', 'enviar_mensagem', 'ativar_deep_lock',
        'definir_papel_de_parede', 'instalar_scratchjr', 'restaurar_backup_sistema', 'get_system_info',
        'cleanup_wallpaper'
    ]
    
    # Ações que devem usar a rota de streaming para feedback em tempo real.
    streaming_actions = [
        'atualizar_sistema'
    ]

    # Passa a função de manipulação de shell para o payload para evitar importação circular.
    data['shell_action_handler'] = _handle_shell_action

    try:
        with ssh_connect(ip, SSH_USER, password) as ssh:
            # Ações de streaming são tratadas de forma diferente pelo frontend
            if action in streaming_actions:
                return jsonify({"success": False, "message": "Ação de streaming deve ser chamada via /stream-action."}), 400
            
            # Ação de limpeza de papel de parede é por máquina, não por usuário
            if action == 'cleanup_wallpaper':
                # Ação de limpeza não é por usuário, é por máquina.
                message, _, errors = _handle_cleanup_wallpaper(ssh, data)
                return jsonify({"success": not errors, "message": message, "details": errors}), 200 if not errors else 500

            # Se a ação for específica do usuário, executa para cada um.
            if action in user_specific_actions:
                response_data, status_code = _execute_for_each_user(ssh, action, data, app.logger)
                return jsonify(response_data), status_code
            else: # Caso contrário, trata como uma ação de sistema (não específica de usuário)
                result = _handle_shell_action(ssh, None, action, data)
                status_code = 200
                if not result.get('success'):
                    status_code = 500
                    if "autenticação" in result.get('message', ''):
                        status_code = 401
                return jsonify(result), status_code

    except paramiko.AuthenticationException:
        response, status_code = _handle_ssh_exception(paramiko.AuthenticationException("Falha na autenticação."), ip, action, app.logger)
        return jsonify(response), status_code

@app.route('/backup-application', methods=['POST'])
def backup_application():
    """
    Cria um backup .zip do diretório da aplicação, excluindo arquivos desnecessários.
    Esta é uma ação local, executada no servidor onde o backend está rodando.
    """
    try:
        project_root = os.path.dirname(os.path.abspath(__file__))
        backup_dir = os.path.join(project_root, 'backups')
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_filename = f"gerenciador-atalhos-backup-{timestamp}.zip"
        backup_path = os.path.join(backup_dir, backup_filename)

        command = [
            # Usa o caminho absoluto para o arquivo de saída para evitar ambiguidades.
            'zip', '-r', backup_path, '.', # '.' significa o diretório atual
            '-x', 'venv/*',
            '-x', 'backups/*',
            '-x', '__pycache__/*',
            '-x', '*.pyc',
            '-x', 'novnc.zip',
            '-x', 'noVNC-master/*'
        ]
        subprocess.run(command, check=True, cwd=project_root, capture_output=True, text=True)
        return jsonify({"success": True, "message": "Backup da aplicação criado com sucesso.", "path": backup_path}), 200
    except (subprocess.CalledProcessError, FileNotFoundError, Exception) as e:
        error_details = e.stderr if isinstance(e, subprocess.CalledProcessError) else str(e)
        app.logger.error(f"Erro ao criar backup da aplicação: {error_details}")
        return jsonify({"success": False, "message": "Falha ao criar o backup da aplicação.", "details": error_details}), 500

@app.route('/start-vnc-grid', methods=['POST'])
def start_vnc_grid():
    """
    Inicia sessões VNC e túneis SSH para uma lista de IPs.
    Retorna um mapeamento de IP para a porta local do túnel.
    """
    data = request.get_json()
    ips = data.get('ips')
    # O nome de usuário é global, mas a senha vem da requisição.
    username = SSH_USER # Usa o usuário global
    password = data.get('password')

    if not all([ips, password]):
        return jsonify({"success": False, "message": "Lista de IPs e senha são obrigatórios."}), 400

    results = []
    threads = []
    
    def process_single_ip(ip):
        local_port = find_free_port()
        success, message = _start_vnc_tunnel(ip, username, password, local_port, is_grid_view=True)
        results.append({"ip": ip, "port": local_port, "success": success, "message": message})

    # Inicia uma thread para cada IP para processamento paralelo
    for ip in ips:
        thread = threading.Thread(target=process_single_ip, args=(ip,))
        threads.append(thread)
        thread.start()

    # Espera todas as threads terminarem
    for thread in threads:
        thread.join()

    return jsonify({"success": True, "results": results})


# --- Rotas para Visualização de Tela (VNC) ---

def find_free_port() -> int:
    """Encontra uma porta TCP livre no servidor."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def _start_vnc_tunnel(ip: str, username: str, password: str, local_port: int, is_grid_view: bool = False) -> Tuple[bool, str]:
    """
    Inicia um túnel SSH para VNC e espera pela confirmação de que o websockify está ativo.
    Retorna (success, message).
    """
    # Se já existe um processo para este IP, encerra-o primeiro.
    if ip in vnc_processes:
        try:
            app.logger.info(f"Encerrando processo VNC existente para {ip}...")
            vnc_processes[ip].terminate()
            vnc_processes[ip].wait(timeout=2)
        except subprocess.TimeoutExpired:
            app.logger.warning(f"Processo VNC para {ip} não encerrou, forçando kill.")
            vnc_processes[ip].kill()
        del vnc_processes[ip]

    remote_vnc_port = 5900
    remote_ws_port = 6080

    # O comando remoto agora imprime uma mensagem de sucesso quando o websockify inicia.
    # Usamos 'stdbuf -oL' para garantir que a saída não seja bufferizada.
    # x11vnc é backgrounded e sua saída é redirecionada para /dev/null.
    # websockify é executado em primeiro plano e sua saída é capturada.
    remote_command = (
        f"killall -q x11vnc websockify; "
        f"x11vnc -auth guess -display :0 -nopw -listen localhost -rfbport {remote_vnc_port} -xkb -ncache 10 -ncache_cr -forever > /dev/null 2>&1 & "
        f"stdbuf -oL websockify --run-once -v {remote_ws_port} localhost:{remote_vnc_port}"
    )

    tunnel_command = [
        "sshpass", "-p", password,
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=10", # Adiciona um timeout de conexão
        "-o", "ServerAliveInterval=15", # Mantém a conexão viva
        "-L", f"0.0.0.0:{local_port}:localhost:{remote_ws_port}",
        f"{username}@{ip}",
        remote_command
    ]

    try:
        # Inicia o processo de túnel SSH em segundo plano.
        proc = subprocess.Popen(
            tunnel_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid if platform.system() != 'Windows' else None,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if platform.system().lower() == 'windows' else 0
        )
        vnc_processes[ip] = proc

        # --- Lógica de Verificação do Túnel ---
        success = False
        error_message = f"Timeout: A conexão com {ip} demorou muito."
        all_output_lines = []

        from queue import Queue, Empty
        q = Queue()

        def read_output_to_queue(stream, queue):
            for line in iter(stream.readline, ''):
                queue.put(line)
            stream.close()

        stdout_thread = threading.Thread(target=read_output_to_queue, args=(proc.stdout, q))
        stderr_thread = threading.Thread(target=read_output_to_queue, args=(proc.stderr, q))
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()

        timeout = 20 # Aumenta o timeout para 20 segundos
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                line = q.get(timeout=0.1)
                all_output_lines.append(line.strip())
                app.logger.debug(f"[{ip}] SSH Tunnel Output: {line.strip()}")

                if "WebSocket server started" in line or "listening on" in line:
                    success = True
                    error_message = "Túnel estabelecido."
                    break
                # Check for common SSH errors
                if "Permission denied" in line or "Authentication failed" in line:
                    error_message = "Falha de autenticação (senha incorreta?)."
                    break
                if "Connection refused" in line:
                    error_message = "Conexão recusada pelo host (verifique o serviço SSH)."
                    break
                if "No route to host" in line:
                    error_message = "Sem rota para o host (verifique a conectividade de rede)."
                    break
                if "ssh: connect to host" in line and "port 22: Connection timed out" in line:
                    error_message = "Conexão SSH expirou (host pode estar offline ou firewall bloqueando)."
                    break
                if "sshpass: command not found" in line:
                    error_message = "Erro: 'sshpass' não encontrado no servidor backend. Instale-o (ex: sudo apt install sshpass)."
                    break
                if "x11vnc: command not found" in line or "websockify: command not found" in line:
                    error_message = "Erro: 'x11vnc' ou 'websockify' não encontrado na máquina remota. Instale-os."
                    break
                if "x11vnc: no display found" in line:
                    error_message = "Erro: 'x11vnc' não encontrou um display ativo na máquina remota."
                    break
                if "Host key verification failed" in line:
                    error_message = "Verificação da chave do host falhou. Use o botão 'Corrigir Chaves SSH'."
                    break
                if "Bad configuration option: ServerAliveInterval" in line:
                    error_message = "Erro de configuração SSH: 'ServerAliveInterval' não é suportado. Verifique a versão do SSH."
                    break
                if "Bad configuration option: ConnectTimeout" in line:
                    error_message = "Erro de configuração SSH: 'ConnectTimeout' não é suportado. Verifique a versão do SSH."

            except Empty:
                pass

        # After the loop, if not successful, try to find more specific errors from collected output
        if not success:
            full_output = "\n".join(all_output_lines)
            if "sshpass: command not found" in full_output:
                error_message = "Erro: 'sshpass' não encontrado no servidor backend. Instale-o (ex: sudo apt install sshpass)."
            elif "x11vnc: command not found" in full_output or "websockify: command not found" in full_output:
                error_message = "Erro: 'x11vnc' ou 'websockify' não encontrado na máquina remota. Instale-os."
            elif "x11vnc: no display found" in full_output:
                error_message = "Erro: 'x11vnc' não encontrou um display ativo na máquina remota."
            elif "Permission denied" in full_output or "Authentication failed" in full_output:
                error_message = "Falha de autenticação (senha incorreta?)."
            elif "Connection refused" in full_output:
                error_message = "Conexão recusada pelo host (verifique o serviço SSH)."
            elif "No route to host" in full_output:
                error_message = "Sem rota para o host (verifique a conectividade de rede)."
            elif "ssh: connect to host" in full_output and "port 22: Connection timed out" in full_output:
                error_message = "Conexão SSH expirou (host pode estar offline ou firewall bloqueando)."
            elif "Host key verification failed" in full_output:
                error_message = "Verificação da chave do host falhou. Use o botão 'Corrigir Chaves SSH'."
            elif "Bad configuration option: ServerAliveInterval" in full_output:
                error_message = "Erro de configuração SSH: 'ServerAliveInterval' não é suportado. Verifique a versão do SSH."
            elif "Bad configuration option: ConnectTimeout" in full_output:
                error_message = "Erro de configuração SSH: 'ConnectTimeout' não é suportado. Verifique a versão do SSH."
            elif full_output: # If there's any output but no specific error, just report it
                error_message = f"Erro desconhecido: {full_output[:500]}..." # Truncate long output

        if not success:
            # Se falhou, encerra o processo do túnel para liberar recursos.
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
            if ip in vnc_processes:
                del vnc_processes[ip]

        return success, error_message

    except Exception as e:
        app.logger.error(f"Erro inesperado ao iniciar túnel VNC para {ip}: {e}")
        # Garante que o processo seja limpo em caso de exceção antes mesmo do Popen.
        if ip in vnc_processes:
            try:
                vnc_processes[ip].terminate()
                vnc_processes[ip].wait(timeout=1)
            except subprocess.TimeoutExpired:
                vnc_processes[ip].kill()
            del vnc_processes[ip]
        return False, f"Erro interno do servidor: {str(e)}"

@app.route('/start-vnc', methods=['POST'])
def start_vnc():
    """
    Inicia uma sessão VNC em um cliente e cria um túnel SSH para ela.
    """
    data = request.get_json()
    ip = data.get('ip')
    password = data.get('password')

    if not all([ip, password]):
        return jsonify({"success": False, "message": "IP e senha são obrigatórios."}), 400

    local_port = find_free_port()
    success, message = _start_vnc_tunnel(ip, SSH_USER, password, local_port)

    if success:
        # Constrói a URL do noVNC que o frontend irá abrir.
        # O token é apenas um identificador.
        # Usa request.host para obter dinamicamente o endereço que o cliente usou para acessar o servidor.
        # Isso garante que funcione com 'localhost', '127.0.0.1' ou o IP de rede.
        server_host = request.host.split(':')[0]
        vnc_url = f"/novnc/vnc.html?host={server_host}&port={local_port}&path=websockify&token={ip}"
        return jsonify({"success": True, "url": vnc_url})
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
        app.run(host=HOST, port=PORT, debug=True)
    else:
        # Em modo de produção, usa o servidor Waitress, que é mais robusto.
        THREADS = 16
        print(f"--> Servidor de produção (Waitress) iniciado em http://{HOST}:{PORT} com {THREADS} threads.")
        print("--> Pressione Ctrl+C para encerrar.")
        print("----------------------------------------\n")
        serve(app, host=HOST, port=PORT, threads=THREADS)
