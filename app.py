import os
import platform
import subprocess
import socket
import threading
import webbrowser
from typing import Dict, Optional, Any
from contextlib import contextmanager
from multiprocessing import Pool, cpu_count

import paramiko
from flask import Flask, jsonify, request, send_from_directory, Response, Blueprint
from flask_cors import CORS
from waitress import serve

# --- Importações dos Módulos de Serviço Refatorados ---
from command_builder import COMMANDS, _get_command_builder, CommandExecutionError, _parse_system_info
from ssh_service import ssh_connect, _handle_ssh_exception, _execute_for_each_user, _execute_shell_command, _stream_shell_command, list_sftp_backups, _handle_cleanup_wallpaper

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens (front-end)
CORS(app)

# Define o diretório raiz para servir arquivos estáticos (frontend)
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Configuração da Faixa de IPs ---
# Para forçar a busca na faixa estática abaixo, defina FORCE_STATIC_RANGE como True.
FORCE_STATIC_RANGE = True
# Define uma faixa de IPs estática para a busca.
IP_PREFIX = "192.168.0."
IP_START = 101
IP_END = 125

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

# --- Funções de Detecção de Rede ---
def get_local_ip_and_range() -> tuple[str, str, list[str]]:
    """
    Detecta dinamicamente o IP local do servidor e define a faixa de busca para a sub-rede correspondente.
    Se a detecção falhar, recorre à faixa estática como fallback.
    """
    if not FORCE_STATIC_RANGE:
        # Cria um socket para se conectar a um IP externo (não estabelece a conexão, apenas para obter o IP local).
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        
        # Extrai o prefixo da rede (ex: "192.168.0.") do IP local.
        ip_prefix = ".".join(local_ip.split('.')[:-1]) + "."
        app.logger.info(f"Sub-rede local detectada dinamicamente: {ip_prefix}0/24")
        nmap_range = f"{ip_prefix}{IP_START}-{IP_END}"
        ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
        return ip_prefix, nmap_range, ips_to_check
    else:
        app.logger.info(f"Forçando o uso da faixa de IP estática: {IP_PREFIX}{IP_START}-{IP_END}")
        ip_prefix = IP_PREFIX
        nmap_range = f"{ip_prefix}{IP_START}-{IP_END}"
        ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
        return ip_prefix, nmap_range, ips_to_check

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

def discover_ips_with_nmap(ip_range: str, ip_prefix: str) -> Optional[list[str]]:
    """Usa o nmap para uma descoberta de rede rápida e eficiente."""
    try:
        # -sn: Ping Scan - desabilita a varredura de portas
        # -T4: Agressivo - acelera a varredura
        # -oG -: Saída em formato "grepável" para o stdout
        command = ["nmap", "-sn", "-T4", "-oG", "-", ip_range]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        
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
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        app.logger.warning(f"Falha ao usar nmap ({e}). Usando método de fallback (verificação de porta).")
        # Retorna None para indicar que o método de fallback deve ser usado
        return None

def discover_ips_with_arp_scan(ips_to_check: list[str]) -> Optional[list[str]]:
    """Usa o arp-scan para uma descoberta de rede local extremamente rápida."""
    try:
        # Usa --localnet para escanear toda a sub-rede local, que é o método mais
        # rápido e confiável para o arp-scan. O script filtrará os resultados depois.
        command = ["sudo", "arp-scan", "--localnet", "--numeric", "--quiet"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)

        active_ips = []
        # A saída do arp-scan é geralmente "IP_address\tMAC_address"
        for line in result.stdout.splitlines():
            parts = line.split()
            # Garante que a linha tenha pelo menos duas partes e que a primeira parte
            # se pareça com um endereço IP (contém 3 pontos).
            # Isso filtra cabeçalhos como "Interface: eth0..."
            if len(parts) >= 2 and parts[0].count('.') == 3:
                ip = parts[0]
                # Filtra os IPs para garantir que estejam dentro da faixa desejada (IP_START a IP_END).
                try:
                    last_octet = int(ip.split('.')[-1])
                    # Verifica se o IP pertence à faixa configurada.
                    # A verificação do prefixo já é feita implicitamente pelo --localnet.
                    if IP_START <= last_octet <= IP_END:
                        active_ips.append(ip)
                except (ValueError, IndexError):
                    # Ignora linhas que não podem ser analisadas.
                    continue
        return active_ips

    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        app.logger.warning(f"Falha ao usar arp-scan ({e}). Tentando próximo método.")
        return None


# --- Rota para Descobrir IPs ---
@app.route('/discover-ips', methods=['GET'])
def discover_ips():
    """
    Escaneia a rede usando múltiplos métodos em paralelo e retorna o primeiro resultado bem-sucedido.
    """
    ip_prefix, nmap_range, ips_to_check = get_local_ip_and_range()
    app.logger.info(f"Iniciando busca de IPs na faixa de {IP_START} a {IP_END}...")

    active_ips = []
    try:
        # Cria um pool de processos para executar os métodos de descoberta em paralelo.
        # Usamos apply_async para que possamos obter o primeiro resultado que terminar.
        with Pool(processes=3) as pool:
            results = [
                pool.apply_async(discover_ips_with_arp_scan, (ips_to_check,)),
                pool.apply_async(discover_ips_with_nmap, (nmap_range, ip_prefix,)),
                pool.apply_async(lambda: [res for res in pool.map(check_ssh_port, ips_to_check) if res], ())
            ]

            # Espera até que um dos processos retorne uma lista não vazia de IPs.
            for res in results:
                result_ips = res.get(timeout=60) # Timeout de 60s para cada método
                if result_ips: # Se encontrou IPs, usa esse resultado e para de esperar.
                    active_ips = result_ips
                    break

    except Exception as e:
        app.logger.error(f"Erro durante a descoberta paralela de IPs: {e}")
        return jsonify({"success": False, "message": f"Erro ao escanear a rede: {e}"}), 500

    # Ordena a lista final de IPs, se houver, pelo último octeto.
    if active_ips:
        active_ips.sort(key=lambda ip: int(ip.split('.')[-1]))

    return jsonify({"success": True, "ips": active_ips}), 200

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


    # Ações que são executadas por usuário
    user_specific_actions = [
        'desativar', 'ativar', 'mostrar_sistema', 'ocultar_sistema',
        'limpar_imagens', 'desativar_barra_tarefas', 'ativar_barra_tarefas',
        'bloquear_barra_tarefas', 'desbloquear_barra_tarefas', 'definir_firefox_padrao',
        'definir_chrome_padrao', 'desativar_perifericos', 'ativar_perifericos',
        'desativar_botao_direito', 'ativar_botao_direito', 'enviar_mensagem', 'ativar_deep_lock',
        'definir_papel_de_parede', 'instalar_scratchjr',
        'cleanup_wallpaper' # Adiciona a ação de limpeza
    ]
    
    # Ações que devem usar a rota de streaming para feedback em tempo real.
    streaming_actions = [
        'atualizar_sistema'
    ]

    # Passa a função de manipulação de shell para o payload para evitar importação circular.
    data['shell_action_handler'] = _handle_shell_action

    try:
        with ssh_connect(ip, SSH_USER, password) as ssh:
            if action in user_specific_actions:
                # Delega a lógica para a nova função
                response_data, status_code = _execute_for_each_user(ssh, action, data, app.logger)
                return jsonify(response_data), status_code
            elif action == 'cleanup_wallpaper':
                # Ação de limpeza não é por usuário, é por máquina.
                message, _, errors = _handle_cleanup_wallpaper(ssh, data)
                return jsonify({"success": not errors, "message": message, "details": errors}), 200 if not errors else 500
            elif action in streaming_actions:
                # Esta rota não lida mais com streaming. O frontend deve chamar /stream-action.
                return jsonify({"success": False, "message": "Ação de streaming deve ser chamada via /stream-action."}), 400
            else: # Ações de sistema
                # Ações de sistema (não específicas do usuário, como 'reiniciar', 'atualizar_sistema', 'get_system_info')
                # _handle_shell_action retorna um dict, que precisa ser convertido em um response JSON.
                result = _handle_shell_action(ssh, None, action, data)
                status_code = 200
                if not result.get('success'):
                    status_code = 500
                    if "autenticação" in result.get('message', ''):
                        status_code = 401

                return jsonify(result), status_code

    except paramiko.AuthenticationException:
        response, status_code = _handle_ssh_exception(paramiko.AuthenticationException("Authentication failed."), ip, action, app.logger)
        return jsonify(response), status_code

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
    
    # Função para ser executada em uma thread para cada IP
    def check_ip_thread(ip, local_port):
        # Se já existe um processo para este IP, encerra-o primeiro.
        if ip in vnc_processes:
            try:
                vnc_processes[ip].terminate()
                vnc_processes[ip].wait(timeout=2)
            except subprocess.TimeoutExpired:
                vnc_processes[ip].kill()
            del vnc_processes[ip]

        remote_vnc_port = 5900
        remote_ws_port = 6080

        # O comando remoto agora imprime uma mensagem de sucesso quando o websockify inicia.
        # Usamos 'stdbuf -oL' para garantir que a saída não seja bufferizada.
        remote_command = (
            f"killall -q x11vnc websockify; "
            f"x11vnc -display :0 -nopw -listen localhost -rfbport {remote_vnc_port} -xkb -ncache 10 -ncache_cr -forever > /dev/null 2>&1 & "
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
                # Garante que o processo seja encerrado se o servidor Flask cair
                preexec_fn=os.setsid if platform.system() != 'Windows' else None,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if platform.system().lower() == 'windows' else 0
            )
            vnc_processes[ip] = proc

            # --- Lógica de Verificação do Túnel ---
            # Espera por uma linha de saída que indique sucesso ou falha por até 15 segundos.
            success = False
            error_message = f"Timeout: A conexão com {ip} demorou muito."
            
            # Usamos um iterador com timeout para ler a saída
            from queue import Queue, Empty
            q = Queue()

            def read_output(out, queue):
                for line in iter(out.readline, ''):
                    queue.put(line)
                out.close()

            # Threads para ler stdout e stderr sem bloquear
            stdout_thread = threading.Thread(target=read_output, args=(proc.stdout, q))
            stderr_thread = threading.Thread(target=read_output, args=(proc.stderr, q))
            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()

            # Loop de verificação com timeout
            import time
            timeout = 15
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    # Usamos um pequeno timeout no get() para evitar busy-waiting
                    line = q.get(timeout=0.1)
                    if "listening on" in line:
                        success = True
                        error_message = "Túnel estabelecido."
                        break
                    # Verifica por erros comuns de SSH
                    if "Permission denied" in line or "Authentication failed" in line:
                        error_message = "Falha de autenticação (senha incorreta?)."
                        break
                    if "Connection refused" in line:
                        error_message = "Conexão recusada pelo host."
                        break
                except Empty:
                    # Se a fila estiver vazia, continua o loop
                    pass

            results.append({"ip": ip, "port": local_port, "success": success, "message": error_message})

        except Exception as e:
            app.logger.error(f"Erro ao iniciar VNC em grade para {ip}: {e}")
            results.append({"ip": ip, "port": None, "success": False, "message": str(e)})

    # Inicia uma thread para cada IP para processamento paralelo
    for ip in ips:
        local_port = find_free_port()
        thread = threading.Thread(target=check_ip_thread, args=(ip, local_port))
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

    # Se já existe um processo para este IP, encerra-o primeiro.
    if ip in vnc_processes:
        # Se já existe um processo para este IP, encerra-o primeiro.
        if ip in vnc_processes:
            vnc_processes[ip].terminate()
            vnc_processes[ip].wait()
            del vnc_processes[ip]

    try:
        # Encontra uma porta livre no servidor para o túnel SSH.
        local_port = find_free_port()
        
        # Comando para iniciar o servidor VNC e o proxy WebSocket no cliente.
        # O x11vnc escuta apenas localmente por segurança.
        # O websockify expõe o VNC via WebSocket, também localmente.
        remote_vnc_port = 5900
        remote_ws_port = 6080
        remote_command = (
            f"killall x11vnc websockify; " # Garante que sessões antigas sejam encerradas
            # O x11vnc escuta apenas localmente por segurança.
            f"x11vnc -display :0 -nopw -listen localhost -rfbport {remote_vnc_port} -xkb -ncache 10 -ncache_cr -forever & "
            # O websockify apenas faz o proxy da conexão, sem servir arquivos web (--web foi removido).
            f"websockify -v {remote_ws_port} localhost:{remote_vnc_port}"
        )

        # Comando para criar o túnel SSH reverso.
        # Encaminha a porta do WebSocket do cliente para a porta local livre no servidor.
        # Usamos 'sshpass' para fornecer a senha para o comando SSH de forma não interativa.        
        tunnel_command = [
            "sshpass", "-p", password,
            "ssh",
            "-o", "StrictHostKeyChecking=no", # Aceita novas chaves de host automaticamente
            "-o", "UserKnownHostsFile=/dev/null", # Evita problemas com chaves de host antigas
            "-L", f"0.0.0.0:{local_port}:localhost:{remote_ws_port}",
            f"{SSH_USER}@{ip}",
            remote_command
        ]

        # Inicia o processo de túnel SSH em segundo plano.
        # O stdout/stderr são redirecionados para o log do servidor para depuração,
        # em vez de travarem o processo.
        # Usamos Popen para não bloquear o servidor Flask.
        proc = subprocess.Popen(tunnel_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if platform.system().lower() == 'windows' else 0)
        vnc_processes[ip] = proc

        # Constrói a URL do noVNC que o frontend irá abrir.
        # O token é apenas um identificador.
        # Usa request.host para obter dinamicamente o endereço que o cliente usou para acessar o servidor.
        # Isso garante que funcione com 'localhost', '127.0.0.1' ou o IP de rede.
        server_host = request.host.split(':')[0]
        vnc_url = f"/novnc/vnc.html?host={server_host}&port={local_port}&path=websockify&token={ip}"

        return jsonify({"success": True, "url": vnc_url})

    except Exception as e:
        app.logger.error(f"Erro ao iniciar VNC para {ip}: {e}")
        return jsonify({"success": False, "message": f"Erro ao iniciar sessão VNC: {e}"}), 500

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
        print("--> Modo de desenvolvimento ativado. Abrindo o navegador...")
        threading.Timer(1.5, open_browser).start()

    if DEV_MODE:
        # Em modo de desenvolvimento, usa o servidor do Flask com debug e reloader ativados.
        # Isso recarrega o servidor automaticamente quando o código é alterado.
        print(f"--> Servidor de desenvolvimento iniciado em http://{HOST}:{PORT}")
        print("--> O servidor irá recarregar automaticamente após alterações no código.")
        print("--> Pressione Ctrl+C para encerrar.")
        print("----------------------------------------\n")
        app.run(host=HOST, port=PORT, debug=True)
    else:
        # Em modo de produção, usa o servidor Waitress, que é mais robusto.
        THREADS = 16
        print(f"--> Servidor de produção (Waitress) iniciado em http://{HOST}:{PORT} com {THREADS} threads.")
        print("--> Pressione Ctrl+C para encerrar.")
        print("----------------------------------------\n")
        serve(app, host=HOST, port=PORT, threads=THREADS)
