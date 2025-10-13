import os
import html
import base64
import posixpath  # Para manipulação de caminhos em sistemas não-Windows
import platform
import stat
import re
import shlex
import subprocess
import threading
import webbrowser
from typing import List, Dict, Tuple, Optional, Any, Generator


from contextlib import contextmanager
from multiprocessing import Pool, cpu_count
import paramiko
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from waitress import serve

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens (front-end)
CORS(app)

# Define o diretório raiz para servir arquivos estáticos (frontend)
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Carregar Scripts Externos ---
# Carrega o script de setup do ambiente GSettings a partir de um arquivo externo
# para manter o código Python mais limpo e o script shell mais fácil de manter.
try:
    with open('setup_gsettings_env.sh', 'r', encoding='utf-8') as f:
        GSETTINGS_ENV_SETUP = f.read()
except FileNotFoundError:
    app.logger.critical("FATAL: O script 'setup_gsettings_env.sh' não foi encontrado. As ações de GSettings irão falhar.")
    GSETTINGS_ENV_SETUP = "echo 'FATAL: setup_gsettings_env.sh not found'; exit 1;"

try:
    with open('manage_right_click.sh', 'r', encoding='utf-8') as f:
        MANAGE_RIGHT_CLICK_SCRIPT = f.read()
except FileNotFoundError:
    app.logger.critical("FATAL: O script 'manage_right_click.sh' não foi encontrado. As ações de clique direito irão falhar.")
    MANAGE_RIGHT_CLICK_SCRIPT = "echo 'FATAL: manage_right_click.sh not found'; exit 1;"

try:
    with open('manage_peripherals.sh', 'r', encoding='utf-8') as f:
        MANAGE_PERIPHERALS_SCRIPT = f.read()
except FileNotFoundError:
    app.logger.critical("FATAL: O script 'manage_peripherals.sh' não foi encontrado. As ações de periféricos irão falhar.")
    MANAGE_PERIPHERALS_SCRIPT = "echo 'FATAL: manage_peripherals.sh not found'; exit 1;"

try:
    with open('setup_x11_env.sh', 'r', encoding='utf-8') as f:
        X11_ENV_SETUP = f.read()
except FileNotFoundError:
    app.logger.critical("FATAL: O script 'setup_x11_env.sh' não foi encontrado. As ações de xinput/x11 irão falhar.")
    X11_ENV_SETUP = "echo 'FATAL: setup_x11_env.sh not found'; exit 1;"

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

# --- Função auxiliar para conexão SSH ---
@contextmanager
def ssh_connect(ip: str, username: str, password: Optional[str] = None) -> Generator[paramiko.SSHClient, None, None]:
    """
    Gerencia uma conexão SSH com tratamento de exceções e fechamento automático.
    AVISO: Esta configuração confia automaticamente em qualquer chave de host,
    o que é conveniente para redes locais, mas inseguro em redes não confiáveis.
    """
    ssh = paramiko.SSHClient()
    # AVISO DE SEGURANÇA: AutoAddPolicy() confia em qualquer chave de host.
    # Isso é conveniente para redes locais, mas inseguro em redes não confiáveis,
    # pois é vulnerável a ataques man-in-the-middle.
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(ip, username=username, password=password, timeout=10)
        yield ssh
    finally:
        ssh.close()


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
            with ssh.open_sftp() as sftp:
                home_dir = sftp.normalize('.')
                backup_root = posixpath.join(home_dir, BACKUP_ROOT_DIR)

                try:
                    # Verifica se o diretório de backup existe
                    sftp.stat(backup_root)
                except FileNotFoundError:
                    # Nenhum backup, retorna uma estrutura vazia com sucesso.
                    return jsonify({"success": True, "backups": {}}), 200

                # Lista os subdiretórios (ex: 'Área de Trabalho', 'Desktop')
                backup_dirs = [d for d in sftp.listdir(backup_root) if stat.S_ISDIR(sftp.stat(posixpath.join(backup_root, d)).st_mode)]

                # Monta a estrutura de backups para o frontend
                backups_by_dir = {}
                for directory in backup_dirs:
                    dir_path = posixpath.join(backup_root, directory)
                    files = [f for f in sftp.listdir(dir_path) if f.endswith('.desktop')]
                    if files:
                        backups_by_dir[directory] = files

                return jsonify({"success": True, "backups": backups_by_dir}), 200

    except paramiko.AuthenticationException:
        return jsonify({"success": False, "message": "Falha na autenticação. Verifique a senha."}), 401
    except paramiko.SSHException as e:
        response, status_code = _handle_ssh_exception(e, ip, 'list-backups')
        return jsonify(response), status_code
    except Exception as e:
        app.logger.error(f"Erro inesperado ao listar backups em {ip}: {e}")
        return jsonify({"success": False, "message": "Ocorreu um erro interno no servidor."}), 500


# --- Funções de Ação (Lógica de Negócio) ---

def _handle_ssh_exception(e: Exception, ip: str, action: str) -> Tuple[Dict[str, Any], int]:
    """Analisa exceções de SSH e retorna uma resposta JSON padronizada."""
    error_str = str(e).lower()
    app.logger.error(f"Erro de SSH na ação '{action}' em {ip}: {error_str}")

    if "timed out" in error_str or "timeout" in error_str or "connection timed out" in error_str:
        message = "A conexão SSH expirou (timeout)."
        details = "O dispositivo remoto não respondeu a tempo. Verifique se o serviço SSH está ativo e se não há um firewall bloqueando a porta 22."
        return {"success": False, "message": message, "details": details}, 504 # Gateway Timeout

    if "host key for server" in error_str and "does not match" in error_str:
        message = "Alerta de segurança: A chave do host mudou."
        details = (f"A chave do host para {ip} é diferente da que está salva em 'known_hosts'. "
                   "Isso pode significar que o sistema operacional foi reinstalado ou, em casos raros, que há um ataque 'man-in-the-middle'.\n\n"
                   f"Para resolver, remova a chave antiga executando no terminal onde o backend está rodando:\nssh-keygen -R {ip}")
        return {"success": False, "message": message, "details": details}, 409 # Conflict

    # Para outros erros de SSH, retorna uma mensagem genérica, mas com os detalhes técnicos.
    return {"success": False, "message": "Erro de comunicação SSH.", "details": str(e)}, 502

def _get_remote_desktop_path(ssh: paramiko.SSHClient, sftp: paramiko.SFTPClient, username: str) -> Optional[str]:
    """Descobre o caminho da Área de Trabalho na máquina remota, usando uma conexão sftp existente."""
    # 1. Tenta com xdg-user-dir (padrão)
    # A senha não é necessária aqui, pois o comando é executado dentro de um shell que já terá
    # privilégios de sudo da chamada principal em _execute_shell_command.
    _, stdout, _ = ssh.exec_command(f"sudo -u {username} xdg-user-dir DESKTOP") # Não precisa de -S aqui
    desktop_path = stdout.read().decode(errors='ignore').strip()
    if desktop_path and not desktop_path.startswith('/'): # Garante que seja um caminho absoluto
        # Usa o sftp para obter o diretório home de forma mais confiável
        home_dir = sftp.normalize('.')
        desktop_path = posixpath.join(home_dir, desktop_path)

    # 2. Se falhar, tenta uma lista de nomes comuns
    if not desktop_path:
        home_dir = sftp.normalize('.')
        possible_dirs = ["Área de Trabalho", "Desktop", "Área de trabalho", "Escritorio"]
        for p_dir in possible_dirs:
            full_path = posixpath.join(home_dir, p_dir)
            try:
                # Verifica se o diretório existe
                sftp.stat(full_path)
                desktop_path = full_path
                break
            except FileNotFoundError:
                continue
    return desktop_path

def _normalize_shortcut_name(filename: str) -> str:
    """Normaliza o nome de um atalho removendo dígitos para permitir correspondência flexível."""
    if not filename.endswith('.desktop'):
        return filename # Não mexe em arquivos que não são atalhos

    # Usa fatiamento para ser mais seguro que .replace()
    name_part = filename[:-len('.desktop')]
    # Remove um sufixo numérico opcional (ex: '-123') do final do nome.
    # Isso garante que 'App-123.desktop' e 'App.desktop' sejam normalizados para o mesmo nome.
    normalized_name_part = re.sub(r'[-_]?\d+$', '', name_part)

    # Se a normalização resultar em um nome vazio (ex: "123.desktop") ou apenas com hífens,
    # retorna o nome original para evitar erros. Ele não corresponderá a outras
    # máquinas, mas não quebrará a restauração nesta.
    if not normalized_name_part.strip(' -_'):
        return filename

    return normalized_name_part + ".desktop"

def sftp_disable_shortcuts(ssh: paramiko.SSHClient, username: str) -> Tuple[str, Optional[str]]:
    """Desativa atalhos usando SFTP para mover os arquivos."""
    with ssh.open_sftp() as sftp:
        desktop_path = _get_remote_desktop_path(ssh, sftp, username)
        if not desktop_path:
            return "ERRO: Nenhum diretório de Área de Trabalho válido foi encontrado.", None

        home_dir = sftp.normalize('.')
        backup_root = posixpath.join(home_dir, BACKUP_ROOT_DIR)
        desktop_basename = posixpath.basename(desktop_path)
        backup_subdir = posixpath.join(backup_root, desktop_basename)

        # Cria os diretórios de backup
        try:
            sftp.mkdir(backup_root)
        except IOError: # Já existe
            pass
        try:
            sftp.mkdir(backup_subdir)
        except IOError: # Já existe
            pass

        # Move os arquivos
        files_moved = 0
        for filename in sftp.listdir(desktop_path):
            if filename.endswith('.desktop'):
                source = posixpath.join(desktop_path, filename)
                destination = posixpath.join(backup_subdir, filename)
                sftp.rename(source, destination)
                files_moved += 1

    return f"Operação de desativação concluída. {files_moved} atalhos movidos para backup.", None

def sftp_restore_shortcuts(ssh: paramiko.SSHClient, username: str, backup_files_to_match: List[str]) -> Tuple[str, Optional[str], Optional[str]]:
    """Restaura atalhos selecionados usando SFTP com correspondência flexível."""
    with ssh.open_sftp() as sftp:
        desktop_path = _get_remote_desktop_path(ssh, sftp, username)
        if not desktop_path:
            # Retorna 3 valores para consistência com o fluxo principal
            return "ERRO: Nenhum diretório de Área de Trabalho válido foi encontrado para restauração.", None, None

        home_dir = sftp.normalize('.')
        backup_root = posixpath.join(home_dir, BACKUP_ROOT_DIR)

        files_restored = 0
        errors = []
        warnings = []

        # 1. Construir um mapa de todos os backups disponíveis na máquina remota.
        #    A chave é o caminho normalizado, o valor é o caminho real (ambos relativos ao backup_root).
        available_backups_map = {}
        try:
            # Itera sobre os diretórios dentro da pasta de backup (ex: 'Área de Trabalho')
            for directory_name in sftp.listdir(backup_root):
                backup_dir_path = posixpath.join(backup_root, directory_name)
                try:
                    # Garante que é um diretório
                    if not stat.S_ISDIR(sftp.lstat(backup_dir_path).st_mode):
                        continue
                except FileNotFoundError:
                    continue # Ignora se o item desapareceu

                # Itera sobre os arquivos de atalho dentro do diretório de backup
                for filename in sftp.listdir(backup_dir_path):
                    if filename.endswith('.desktop'):
                        normalized_name = _normalize_shortcut_name(filename)
                        # O caminho normalizado e o real são relativos, mas incluem o diretório de backup
                        # Ex: 'Area de Trabalho/WebApp-ElefanteLetrado.desktop'
                        normalized_path = posixpath.join(directory_name, normalized_name)
                        real_path = posixpath.join(directory_name, filename)
                        available_backups_map[normalized_path] = real_path
        except FileNotFoundError:
            # Retorna 3 valores para consistência com o fluxo principal
            return f"ERRO: Diretório de backup '{BACKUP_ROOT_DIR}' não encontrado na máquina remota.", None, None

        # 2. Iterar sobre os arquivos que o usuário quer restaurar (caminhos vêm do frontend).
        for path_from_request in backup_files_to_match:
            # Para a busca, normalizamos o caminho recebido do frontend
            # para que ele corresponda às chaves do nosso mapa de backups.
            dir_name = posixpath.dirname(path_from_request)
            file_name = posixpath.basename(path_from_request)
            normalized_file_name = _normalize_shortcut_name(file_name)
            lookup_key = posixpath.join(dir_name, normalized_file_name)

            # 3. Encontrar o caminho real correspondente no mapa usando a chave normalizada.
            real_path_to_restore = available_backups_map.get(lookup_key)

            if real_path_to_restore:
                # Constrói os caminhos absolutos para a operação de renomear
                filename_to_restore = posixpath.basename(real_path_to_restore)
                source = posixpath.join(backup_root, real_path_to_restore)
                destination = posixpath.join(desktop_path, filename_to_restore)
                try:
                    sftp.rename(source, destination)
                    files_restored += 1
                except IOError as e:
                    errors.append(f"Falha ao restaurar {filename_to_restore}: {e}")
            else:
                # O atalho solicitado não foi encontrado (mesmo após normalização) na máquina atual.
                warnings.append(f"Atalho '{file_name}' não encontrado no backup desta máquina.")

    message = f"Restauração concluída. {files_restored} atalhos restaurados."
    error_details = "\n".join(errors) if errors else None
    warning_details = "\n".join(warnings) if warnings else None
    return message, error_details, warning_details

def _handle_set_wallpaper(ssh: paramiko.SSHClient, username: str, data: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Faz o upload de uma imagem e a define como papel de parede na máquina remota.
    """
    wallpaper_data_url = data.get('wallpaper_data')
    wallpaper_filename = data.get('wallpaper_filename')
    password = data.get('password')

    if not all([wallpaper_data_url, wallpaper_filename, password]):
        return "ERRO: Dados da imagem, nome do arquivo e senha são necessários.", None, None

    try:
        # Decodifica a imagem a partir do Data URL (Base64)
        header, encoded = wallpaper_data_url.split(",", 1)
        image_data = base64.b64decode(encoded)

        with ssh.open_sftp() as sftp:
            # Obtém o diretório home do usuário alvo
            # Não precisa de sudo aqui, pois getent é legível por todos.
            # A execução é rápida e não justifica a complexidade de passar a senha.
            _, stdout, _ = ssh.exec_command(f"getent passwd {username} | cut -d: -f6")
            user_home = stdout.read().decode().strip()
            images_dir = posixpath.join(user_home, 'Imagens')
            remote_path = posixpath.join(images_dir, wallpaper_filename)

            # Garante que o diretório ~/Imagens exista
            try:
                sftp.stat(images_dir)
            except FileNotFoundError:
                sftp.mkdir(images_dir)

            # Faz o upload do arquivo
            with sftp.open(remote_path, 'wb') as f:
                f.write(image_data)

        # Constrói e executa o comando para definir o papel de parede
        # A URI completa (incluindo file://) deve ser passada como um único argumento
        # para gsettings. shlex.quote() garante que a URI seja tratada como um
        # único argumento pelo shell, mesmo que contenha espaços ou caracteres especiais.
        uri = f"file://{remote_path}"
        safe_uri_arg = shlex.quote(uri) # O comando gsettings será executado via sudo, então não precisa de quote aqui
        command = f"""
            gsettings set org.cinnamon.desktop.background picture-uri {safe_uri_arg};
            echo "Papel de parede definido com sucesso.";
        """
        return _execute_shell_command(ssh, command, password, username=username)

    except Exception as e:
        return f"ERRO: Falha ao processar o papel de parede: {e}", None, None

def _parse_system_info(output: str) -> Dict[str, str]:
    """Analisa a saída estruturada do comando de informações do sistema."""
    info = {}
    # Usamos re.DOTALL para que '.' corresponda a novas linhas
    # Usamos non-greedy '.*?' para evitar que a correspondência vá até o final do arquivo
    cpu_match = re.search(r'---CPU_USAGE---(.*?)\n----MEMORY----', output, re.DOTALL)
    mem_match = re.search(r'----MEMORY----(.*?)\n----DISK----', output, re.DOTALL)
    disk_match = re.search(r'----DISK----(.*?)\n----UPTIME----', output, re.DOTALL)
    uptime_match = re.search(r'----UPTIME----(.*?)\n----END----', output, re.DOTALL)

    # .strip() remove espaços em branco e novas linhas extras
    info['cpu'] = cpu_match.group(1).strip() if cpu_match else "N/A"
    info['memory'] = mem_match.group(1).strip() if mem_match else "N/A"
    info['disk'] = disk_match.group(1).strip() if disk_match else "N/A"
    info['uptime'] = uptime_match.group(1).strip() if uptime_match else "N/A"
    return info

def _build_kill_process_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Tuple[Dict[str, Any], int]]]:
    """Constrói o comando 'pkill' para finalizar um processo pelo nome."""
    process_name = data.get('process_name')
    if not process_name:
        return None, ({"success": False, "message": "O nome do processo não pode estar vazio."}, 400)

    safe_process_name = shlex.quote(process_name)
    escaped_process_name = html.escape(process_name)

    command = f"""
        if pkill -f {safe_process_name}; then
            echo "Sinal de finalização enviado para processo(s) contendo '{escaped_process_name}'."
        else
            echo "Nenhum processo encontrado contendo '{escaped_process_name}'."
        fi
    """
    return command, None

def build_send_message_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Tuple[Dict[str, Any], int]]]:
    """Constrói o comando 'zenity' para enviar uma mensagem, usando o ambiente X11 padronizado."""
    message = data.get('message')
    if not message:
        return None, ({"success": False, "message": "O campo de mensagem não pode estar vazio."}, 400)

    escaped_message = html.escape(message)
    pango_message = f"<span font_size='xx-large'>{escaped_message}</span>"
    safe_message = shlex.quote(pango_message)

    # Reutiliza o script de setup do ambiente X11 para consistência e robustez.
    core_logic = f"""
        if ! command -v zenity &> /dev/null; then
            echo "Erro: O comando 'zenity' não foi encontrado na máquina remota." >&2
            exit 1
        fi
        zenity --info --title="Mensagem do Administrador" --text={safe_message} --width=500;
        echo "Mensagem enviada com sucesso."
    """
    
    full_command = X11_ENV_SETUP + core_logic
    return full_command, None

def build_sudo_command(data: Dict[str, Any], base_command: str, message: str) -> Tuple[str, None]:
    """Constrói um comando que requer 'sudo'."""
    # O comando 'sudo' é invocado com a flag '-S' para que ele leia a senha
    # a partir do stdin, em vez de tentar ler de um terminal interativo.
    # A senha é então enviada para o stdin do processo do comando.
    command = f"sudo -S {base_command}"
    return command, None

def _execute_shell_command(ssh: paramiko.SSHClient, command: str, password: str, timeout: int = 20, username: Optional[str] = None) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Executa um comando shell via SSH, tratando sudo e separando warnings de erros.
    Se 'username' for fornecido, executa o comando no contexto desse usuário via 'sudo -u'.
    Retorna uma tupla (output, warnings, errors).
    """
    if username:
        # Envolve o comando com 'sudo -S -u' para executá-lo como o usuário alvo.
        # O -S é crucial para que o sudo leia a senha do stdin.
        final_command = f"sudo -S -u {username} bash -c {shlex.quote(command)}"
    else:
        # Para comandos de sistema, apenas adiciona 'sudo -S' se não estiver presente.
        final_command = command if command.strip().startswith("sudo -S") else f"sudo -S {command}"

    stdin, stdout, stderr = ssh.exec_command(final_command, timeout=timeout)

    if "sudo -S" in final_command:
        stdin.write(password + '\n')
        stdin.flush()

    output = stdout.read().decode('utf-8', errors='ignore').strip()
    error_output = stderr.read().decode('utf-8', errors='ignore').strip()

    # O sudo pode imprimir o prompt de senha no stderr mesmo quando usa -S.
    # Filtramos essa mensagem para não a tratar como um erro real, usando uma
    # expressão regular para lidar com diferentes idiomas (ex: 'senha' ou 'password').
    sudo_prompt_regex = r'\[sudo\] (senha|password) para .*:'
    cleaned_error_output = re.sub(sudo_prompt_regex, '', error_output).strip()

    if not cleaned_error_output:
        return output, None, None

    warnings = [line for line in cleaned_error_output.splitlines() if line.strip().startswith('W:')]
    errors = [line for line in cleaned_error_output.splitlines() if not line.strip().startswith('W:') and line.strip()]

    return output, "\n".join(warnings) if warnings else None, "\n".join(errors) if errors else None

# --- Funções auxiliares para construir comandos shell ---

def _build_get_system_info_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Constrói um comando shell para coletar informações vitais do sistema de forma robusta."""
    command = """
        # Verifica se os comandos necessários existem para evitar erros.
        for cmd in top free df uptime; do
            if ! command -v $cmd &> /dev/null; then
                echo "Erro: O comando '$cmd' não foi encontrado na máquina remota." >&2
                exit 1
            fi
        done

        echo "---CPU_USAGE---"
        LC_ALL=C top -bn1 | grep 'Cpu(s)' | sed -E 's/.*, *([0-9.]+) id.*/\\1/' | awk '{printf "%.1f%%", 100 - $1}'
        echo "----MEMORY----"
        LC_ALL=C free -h | grep '^Mem:' | awk '{print $3 "/" $2 " (Disp: " $7 ")"}'
        echo "----DISK----"
        LC_ALL=C df -h / | tail -n 1 | awk '{print $3 "/" $2 " (" $5 " uso)"}'
        echo "----UPTIME----"
        uptime -p
        echo "----END----"
    """
    return command, None


def _build_gsettings_visibility_command(visible: bool) -> str:
    """Constrói um comando para mostrar/ocultar ícones do sistema."""
    visibility_str = "true" if visible else "false"
    message = "ativados" if visible else "ocultados"
    return GSETTINGS_ENV_SETUP + f"""
        gsettings set org.nemo.desktop computer-icon-visible {visibility_str};
        gsettings set org.nemo.desktop home-icon-visible {visibility_str};
        gsettings set org.nemo.desktop trash-icon-visible {visibility_str};
        gsettings set org.nemo.desktop network-icon-visible {visibility_str};
        echo "Ícones do sistema foram {message}.";
    """

def _build_xdg_default_browser_command(browser_desktop_file: str) -> str:
    """Constrói um comando para definir o navegador padrão usando xdg-settings."""
    # Extrai o nome do navegador do nome do arquivo para a mensagem de sucesso.
    browser_name = browser_desktop_file.split('.')[0].replace('-', ' ').title()
    return GSETTINGS_ENV_SETUP + f"""
        if command -v xdg-settings &> /dev/null; then
            xdg-settings set default-web-browser {browser_desktop_file};
            echo "{browser_name} definido como navegador padrão.";
        else
            echo "Erro: O comando 'xdg-settings' não foi encontrado.";
            exit 1;
        fi;
    """

def _build_panel_autohide_command(enable_autohide: bool) -> str:
    """Constrói um comando para ativar/desativar o auto-ocultar da barra de tarefas."""
    autohide_str = "true" if enable_autohide else "false"
    message = "configurada para se ocultar automaticamente" if enable_autohide else "restaurada para o modo visível"
    return GSETTINGS_ENV_SETUP + f"""
        PANEL_IDS=$(gsettings get org.cinnamon panels-enabled | grep -o -P "'\\d+:\\d+:\\w+'" | sed "s/'//g" | cut -d: -f1);
        if [ -z "$PANEL_IDS" ]; then echo "Nenhum painel do Cinnamon encontrado."; exit 1; fi;
        AUTOHIDE_LIST=""
        for id in $PANEL_IDS; do
            AUTOHIDE_LIST+="'$id:{autohide_str}',"
        done;
        AUTOHIDE_LIST=${{AUTOHIDE_LIST%,}}
        gsettings set org.cinnamon panels-autohide "[$AUTOHIDE_LIST]";
        echo "Barra de tarefas {message}.";
    """

def _build_x_command_builder(script_to_run: str, action: str, required_command: str) -> callable:
    """
    Constrói uma função 'builder' que gera um comando para ser executado em um ambiente X11.
    """
    def builder(data: Dict[str, Any]) -> Tuple[str, None]:
        quoted_script = shlex.quote(script_to_run)
        core_logic = f"bash -c {quoted_script} -- {shlex.quote(action)}"

        full_command = X11_ENV_SETUP + f"""
            if ! command -v {required_command} &> /dev/null; then
                echo "Erro: O comando '{required_command}' não foi encontrado na máquina remota." >&2
                exit 1
            fi

            {core_logic}
        """
        return full_command, None
    return builder


# --- Dicionário de Comandos (Padrão de Dispatch) ---
# Centraliza os comandos, tornando o código mais limpo e fácil de manter.
# Usa funções lambda para adiar a construção de comandos que precisam de dados da requisição.
COMMANDS = {
        'mostrar_sistema': _build_gsettings_visibility_command(True),
        'ocultar_sistema': _build_gsettings_visibility_command(False),
        'desativar_barra_tarefas': _build_panel_autohide_command(True),
        'ativar_barra_tarefas': _build_panel_autohide_command(False),
        'bloquear_barra_tarefas': GSETTINGS_ENV_SETUP + """
            # Em vez de remover o painel (o que causa uma notificação),
            # esvaziamos seu conteúdo (applets), tornando-o inútil.

            # Salva a configuração atual dos applets em um arquivo de backup.
            gsettings get org.cinnamon enabled-applets > "$HOME/.applet_config_backup"

            # Define a lista de applets habilitados como vazia.
            gsettings set org.cinnamon enabled-applets "[]"

            echo "Barra de tarefas bloqueada (applets removidos).";
        """,
        'desbloquear_barra_tarefas': GSETTINGS_ENV_SETUP + """
            BACKUP_FILE="$HOME/.applet_config_backup"
            if [ -f "$BACKUP_FILE" ]; then
                # Restaura a configuração dos applets a partir do arquivo de backup.
                gsettings set org.cinnamon enabled-applets "$(cat "$BACKUP_FILE")";
                rm "$BACKUP_FILE";
                echo "Barra de tarefas desbloqueada (applets restaurados).";
            else
                echo "Nenhum backup da barra de tarefas encontrado para restaurar.";
            fi;
        """,
        'definir_firefox_padrao': _build_xdg_default_browser_command('firefox.desktop'),
        'definir_chrome_padrao': _build_xdg_default_browser_command('google-chrome.desktop'),
        'desativar_perifericos': _build_x_command_builder(MANAGE_PERIPHERALS_SCRIPT, 'disable', 'xinput'),
        'ativar_perifericos': _build_x_command_builder(MANAGE_PERIPHERALS_SCRIPT, 'enable', 'xinput'),
        'desativar_botao_direito': _build_x_command_builder(MANAGE_RIGHT_CLICK_SCRIPT, 'disable', 'xinput'),
        'ativar_botao_direito': _build_x_command_builder(MANAGE_RIGHT_CLICK_SCRIPT, 'enable', 'xinput'),
        'limpar_imagens': """
            if [ -d "$HOME/Imagens" ]; then
                rm -rf "$HOME/Imagens"/*; # Cuidado: isso remove tudo dentro de Imagens
                echo "Pasta de Imagens foi limpa.";
            else
                echo "Pasta de Imagens não encontrada.";
            fi;
        """,
        'enviar_mensagem': build_send_message_command,
        'reiniciar': lambda d: build_sudo_command(d, "reboot", "Reiniciando a máquina..."),
        'desligar': lambda d: build_sudo_command(d, "shutdown now", "Desligando a máquina..."),
        'kill_process': _build_kill_process_command,
        'get_system_info': _build_get_system_info_command
    }
# Script de atualização do sistema, para ser executado com sh -c
update_script = """
        # --- Script de Atualização Multi-Distro ---
        set -e # Sair imediatamente se um comando falhar.

        # 1. Detecta o gerenciador de pacotes disponível e executa a atualização apropriada.
        if command -v apt-get &> /dev/null; then
            # --- Debian/Ubuntu (apt) ---
            echo "W: Gerenciador de pacotes 'apt' detectado." >&2 # 'W:' é usado para logs de aviso
            
            # Verifica se fuser existe. Se não, tenta instalar psmisc automaticamente.
            if ! command -v fuser &> /dev/null; then
                echo "W: Comando 'fuser' não encontrado. Tentando instalar 'psmisc'..." >&2
                export DEBIAN_FRONTEND=noninteractive
                
                echo "W: Atualizando lista de pacotes para instalar dependências..." >&2
                if ! apt-get update; then
                    echo "Erro: 'apt-get update' falhou. Verifique a configuração dos repositórios (sources.list)." >&2
                    exit 1
                fi

                echo "W: Instalando 'psmisc'..." >&2
                if ! apt-get install -y psmisc; then # -y para não pedir confirmação
                    echo "Erro: Falha ao instalar 'psmisc'." >&2
                    exit 1
                fi
            fi
            
            # Verifica se o apt está em uso.
            echo "W: Verificando locks do gerenciador de pacotes..." >&2
            # fuser retorna 0 se o arquivo estiver em uso
            if fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1; then
                echo "Erro: O gerenciador de pacotes (apt) já está em uso por outro processo." >&2
                exit 1
            fi
            
            # Executa a atualização principal.
            export DEBIAN_FRONTEND=noninteractive
            
            echo "W: Reinstalando certificados..." >&2
            apt-get -y install --reinstall ca-certificates
            
            echo "W: Atualizando lista de pacotes principal..." >&2
            apt-get update

            echo "W: Atualizando pacotes do sistema..." >&2
            apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" upgrade

            echo "Sistema (APT) atualizado com sucesso."

        elif command -v dnf &> /dev/null; then
            # --- Fedora/CentOS 8+/RHEL 8+ (dnf) ---
            echo "W: Gerenciador de pacotes 'dnf' detectado." >&2
            dnf upgrade -y
            echo "Sistema (DNF) atualizado com sucesso."

        elif command -v yum &> /dev/null; then
            # --- CentOS 7/RHEL 7 (yum) ---
            echo "W: Gerenciador de pacotes 'yum' detectado." >&2
            yum update -y
            echo "Sistema (YUM) atualizado com sucesso."
            
        elif command -v pacman &> /dev/null; then
            # --- Arch Linux (pacman) ---
            echo "W: Gerenciador de pacotes 'pacman' detectado." >&2
            if [ -f /var/lib/pacman/db.lck ]; then
                echo "Erro: O gerenciador de pacotes (pacman) já está em uso (lockfile db.lck encontrado)." >&2
                exit 1
            fi
            pacman -Syu --noconfirm
            echo "Sistema (Pacman) atualizado com sucesso."

        else
            echo "Erro: Nenhum gerenciador de pacotes suportado (apt, dnf, yum, pacman) foi encontrado." >&2
            exit 1
        fi
    """
# Usa shlex.quote para passar o script de forma segura para o shell
update_command = f"sh -c {shlex.quote(update_script.strip())}"
COMMANDS['atualizar_sistema'] = lambda d: build_sudo_command(d, update_command, "Atualizando o sistema...")

# --- Funções de Manipulação de Ações (Refatoradas de 'gerenciar_atalhos_ip') ---

def _handle_sftp_action(ssh: paramiko.SSHClient, username: str, action: str, data: Dict[str, Any]):
    """Lida com ações que usam o protocolo SFTP (desativar/ativar atalhos)."""
    if action == 'desativar':
        # Passo 1: Desativar atalhos da área de trabalho via SFTP.
        sftp_message, sftp_details = sftp_disable_shortcuts(ssh, username)

        if "ERRO:" in sftp_message:
            return {"success": False, "message": sftp_message, "details": sftp_details}

        # Passo 2: Ocultar ícones do sistema (Computador, Lixeira, etc.) usando gsettings.
        password = data.get('password')
        hide_icons_command = _build_gsettings_visibility_command(False)
        gsettings_output, gsettings_warnings, gsettings_errors = _execute_shell_command(
            ssh, hide_icons_command, password, username=username
        )

        # Passo 3: Combinar os resultados de ambas as operações.
        final_messages = [sftp_message]
        all_details = []
        success = True

        if gsettings_errors:
            success = False
            final_messages.append("Falha ao ocultar ícones do sistema.")
            all_details.append(f"Erros (ícones do sistema): {gsettings_errors}")
        else:
            final_messages.append(gsettings_output)

        if sftp_details: all_details.append(f"Detalhes (atalhos): {sftp_details}")
        if gsettings_warnings: all_details.append(f"Avisos (ícones do sistema): {gsettings_warnings}")

        return {"success": success, "message": " ".join(final_messages), "details": "\n".join(all_details) if all_details else None}

    elif action == 'ativar':
        backup_files = data.get('backup_files', [])
        if not backup_files:
            return {"success": False, "message": "Nenhum atalho selecionado para restauração."}

        message, error_details, warning_details = sftp_restore_shortcuts(ssh, username, backup_files)

        # Combina todos os detalhes para a resposta JSON
        all_details = []
        if warning_details: all_details.append(warning_details)
        if error_details: all_details.append(error_details)
        details_for_json = "\n".join(all_details) if all_details else None

        # A operação falha apenas se houver erros reais (ex: falha de permissão)
        if error_details or "ERRO:" in message:
            return {"success": False, "message": message, "details": details_for_json}

        # A operação é um sucesso mesmo com avisos (atalhos não encontrados)
        return {"success": True, "message": message, "details": details_for_json}

    # Retorno de segurança, não deve ser alcançado em uso normal.
    return {"success": False, "message": "Ação SFTP interna desconhecida."}

def _handle_shell_action(ssh: paramiko.SSHClient, username: Optional[str], action: str, data: Dict[str, Any]):
    """Lida com ações que executam comandos shell."""
    ip = data.get('ip')
    password = data.get('password')
    command_builder = COMMANDS.get(action)

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

    # Executa o comando shell e obtém o resultado e os erros limpos.
    # Para ações de sistema (sem usuário), username é None. Para ações de usuário, ele é passado.
    output, warnings, errors = _execute_shell_command(ssh, command, password, timeout=timeout, username=username)

    if errors:
        app.logger.error(f"Erro no comando '{action}' em {ip}: {errors}")
        # Combina warnings e errors para um log de detalhes completo
        details = f"Warnings:\n{warnings}\n\nErrors:\n{errors}" if warnings else errors

        # Se o erro for sobre senha incorreta, damos uma mensagem mais clara.
        # A verificação de "falhou" foi removida por ser muito genérica e causar
        # diagnósticos incorretos quando um script falha por outros motivos.
        if "incorrect password attempt" in errors:
            return {"success": False, "message": "Falha na autenticação do sudo. A senha pode estar incorreta.", "details": details}
        return {"success": False, "message": "Ocorreu um erro no dispositivo remoto.", "details": details}

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

def _execute_for_each_user(ssh: paramiko.SSHClient, action: str, data: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """
    Encontra usuários na máquina remota e executa uma ação específica para cada um.
    Retorna um dicionário de resposta e um código de status HTTP.
    """
    # Comando para listar usuários "humanos" com diretório em /home e shell de login.
    list_users_cmd = r"getent passwd | awk -F: '$6 ~ /^\/home\// && $7 !~ /nologin|false/ {print $1}'"
    _, stdout, stderr = ssh.exec_command(list_users_cmd)
    users = stdout.read().decode().strip().splitlines()
    err = stderr.read().decode().strip()

    if err or not users:
        return {"success": False, "message": "Não foi possível encontrar usuários na máquina remota.", "details": err}, 500

    results = {}
    sftp_shortcut_actions = ['desativar', 'ativar']

    for user in users:
        result = {}
        if action == 'definir_papel_de_parede':
            message, warnings, errors = _handle_set_wallpaper(ssh, user, data)
            success = not (errors or "ERRO:" in message)
            details = []
            if warnings: details.append(f"Warnings: {warnings}")
            if errors: details.append(f"Errors: {errors}")
            result = {"success": success, "message": message, "details": "\n".join(details) if details else None}
        elif action in sftp_shortcut_actions:
            result = _handle_sftp_action(ssh, user, action, data)
        else:  # Outras ações de shell por usuário
            result = _handle_shell_action(ssh, user, action, data)
        results[user] = result

    # Agrega os resultados para uma resposta final
    final_success = all(r['success'] for r in results.values())
    final_message = f"Ação '{action}' executada para {len(users)} usuário(s)."
    details_list = [f"Usuário '{u}': {r.get('message')} {r.get('details') or ''}".strip() for u, r in results.items()]
    final_details = "\n".join(details_list)

    return {
        "success": final_success,
        "message": final_message,
        "details": final_details
    }, 200 if final_success else 500


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
        'desativar_botao_direito', 'ativar_botao_direito', 'enviar_mensagem',
        'definir_papel_de_parede'
    ]

    try:
        with ssh_connect(ip, SSH_USER, password) as ssh:
            if action in user_specific_actions:
                # Delega a lógica para a nova função
                response_data, status_code = _execute_for_each_user(ssh, action, data)
                return jsonify(response_data), status_code
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
        return jsonify({"success": False, "message": "Falha na autenticação. Verifique a senha."}), 401
    except paramiko.SSHException as e:
        response, status_code = _handle_ssh_exception(e, ip, action)
        return jsonify(response), status_code
    except Exception as e:
        app.logger.error(f"Erro inesperado na ação '{action}' em {ip}: {e}")
        return jsonify({"success": False, "message": "Ocorreu um erro interno no servidor."}), 500


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
