import os
import platform
import subprocess
import threading
import webbrowser
from typing import Dict, Optional, Any
from contextlib import contextmanager
from multiprocessing import Pool, cpu_count

import paramiko
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from waitress import serve

# --- Importações dos Módulos de Serviço Refatorados ---
from command_builder import COMMANDS, _get_command_builder, CommandExecutionError, _parse_system_info
from ssh_service import ssh_connect, _handle_ssh_exception, _execute_for_each_user, _execute_shell_command, list_sftp_backups, _handle_cleanup_wallpaper

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens (front-end)
CORS(app)

# Define o diretório raiz para servir arquivos estáticos (frontend)
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Configurações Lidas do Ambiente (com valores padrão) ---
IP_PREFIX = os.getenv("IP_PREFIX", "192.168.0.")
IP_START = int(os.getenv("IP_START", 100))
IP_END = int(os.getenv("IP_END", 125))
SSH_USER = os.getenv("SSH_USER", "aluno") # Usuário padrão para conexão, que deve ter privilégios sudo.
BACKUP_ROOT_DIR = "atalhos_desativados"

# --- Função auxiliar para pingar um único IP ---
def ping_ip(ip: str) -> Optional[str]:
    """
    Tenta pingar um único IP e retorna o IP se for bem-sucedido.
    Usa parâmetros otimizados para Windows e Linux.
    """
    is_windows = platform.system().lower() == 'windows'
    param = '-n' if is_windows else '-c'
    # Timeout de 1 segundo (1000ms para Windows, 1s para Linux)
    timeout_param = '-w' if is_windows else '-W'
    timeout_value = '1000' if is_windows else '1'
    command = ["ping", param, "1", timeout_param, timeout_value, ip]

    try:
        # Timeout de 2 segundos para o processo completo
        # Adicionado creationflags para não abrir janela de console no Windows
        result = subprocess.run(command, capture_output=True, text=True, timeout=2, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if is_windows else 0)
        if result.returncode == 0:
            return ip
    except (subprocess.TimeoutExpired, OSError) as e:
        app.logger.warning(f"Erro ao executar o ping para {ip}: {e}")
    return None

# --- Rota para Descobrir IPs ---
@app.route('/discover-ips', methods=['GET'])
def discover_ips():
    """
    Escaneia a rede usando ping de forma paralela e retorna uma lista de IPs ativos.
    """
    ips_to_check = [f"{IP_PREFIX}{i}" for i in range(IP_START, IP_END + 1)]

    try:
        # Usa um pool de processos para acelerar a verificação de IPs
        with Pool(processes=cpu_count() * 2) as pool:
            ping_results = pool.map(ping_ip, ips_to_check)

        # Filtra IPs nulos e ordena pelo último octeto para uma exibição consistente.
        active_ips = sorted(
            [ip for ip in ping_results if ip is not None],
            key=lambda ip: int(ip.split('.')[-1])
        )

    except Exception as e:
        app.logger.error(f"Erro no pool de processos ao descobrir IPs: {e}")
        return jsonify({"success": False, "message": "Erro ao escanear a rede."}), 500

    return jsonify({"success": True, "ips": active_ips}), 200

# --- Rota para servir o Frontend (arquivos estáticos) ---
@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def serve_frontend(path: str):
    """
    Serve o index.html para a rota raiz e outros arquivos estáticos (CSS, JS, etc.).
    Isso consolida as rotas de frontend em uma única função mais robusta.
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
            else:
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

    # Aumenta o número de threads para lidar com mais requisições simultâneas
    # vindas do frontend, reduzindo o tempo de espera na fila.
    THREADS = 16
    print(f"--> Servidor iniciado em http://{HOST}:{PORT} com {THREADS} threads.")
    serve(app, host=HOST, port=PORT, threads=THREADS)
