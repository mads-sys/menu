import os
import html
import posixpath  # Para manipulação de caminhos em sistemas não-Windows
import platform
import stat
import re
import shlex
import subprocess
from contextlib import contextmanager
from multiprocessing import Pool, cpu_count

import paramiko
from flask import Flask, jsonify, request
from flask_cors import CORS
from waitress import serve

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens (front-end)
CORS(app)

# --- Carregar Scripts Externos ---
# Carrega o script de setup do ambiente GSettings a partir de um arquivo externo
# para manter o código Python mais limpo e o script shell mais fácil de manter.
try:
    with open('setup_gsettings_env.sh', 'r', encoding='utf-8') as f:
        GSETTINGS_ENV_SETUP = f.read()
except FileNotFoundError:
    app.logger.critical("FATAL: O script 'setup_gsettings_env.sh' não foi encontrado. As ações de GSettings irão falhar.")
    GSETTINGS_ENV_SETUP = "echo 'FATAL: setup_gsettings_env.sh not found'; exit 1;"

# --- Configurações Lidas do Ambiente (com valores padrão) ---
IP_PREFIX = os.getenv("IP_PREFIX", "192.168.0.")
IP_START = int(os.getenv("IP_START", 100))
IP_END = int(os.getenv("IP_END", 125))
SSH_USERNAME = os.getenv("SSH_USERNAME", "aluno")


# --- Função auxiliar para pingar um único IP ---
def ping_ip(ip):
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
    except (subprocess.TimeoutExpired, Exception) as e:
        app.logger.warning(f"Erro ao pingar {ip}: {e}")
        return None
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


# --- Função auxiliar para conexão SSH ---
@contextmanager
def ssh_connect(ip, username, password):
    """Gerencia uma conexão SSH com tratamento de exceções e fechamento automático."""
    ssh = paramiko.SSHClient()
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
        with ssh_connect(ip, SSH_USERNAME, password) as ssh:
            with ssh.open_sftp() as sftp:
                home_dir = sftp.normalize('.')
                backup_root = posixpath.join(home_dir, 'atalhos_desativados')

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
        app.logger.error(f"Erro de SSH ao listar backups em {ip}: {e}")
        return jsonify({"success": False, "message": "Erro de comunicação com o dispositivo remoto."}), 502
    except Exception as e:
        app.logger.error(f"Erro inesperado ao listar backups em {ip}: {e}")
        return jsonify({"success": False, "message": "Ocorreu um erro interno no servidor."}), 500


# --- Funções de Ação (Lógica de Negócio) ---

def _get_remote_desktop_path(ssh, sftp):
    """Descobre o caminho da Área de Trabalho na máquina remota, usando uma conexão sftp existente."""
    # 1. Tenta com xdg-user-dir (padrão)
    _, stdout, _ = ssh.exec_command("xdg-user-dir DESKTOP")
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

def _normalize_shortcut_name(filename):
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

def sftp_disable_shortcuts(ssh):
    """Desativa atalhos usando SFTP para mover os arquivos."""
    with ssh.open_sftp() as sftp:
        desktop_path = _get_remote_desktop_path(ssh, sftp)
        if not desktop_path:
            return "ERRO: Nenhum diretório de Área de Trabalho válido foi encontrado.", None

        home_dir = sftp.normalize('.')
        backup_root = posixpath.join(home_dir, 'atalhos_desativados')
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

def sftp_restore_shortcuts(ssh, backup_files_to_match):
    """Restaura atalhos selecionados usando SFTP com correspondência flexível."""
    with ssh.open_sftp() as sftp:
        desktop_path = _get_remote_desktop_path(ssh, sftp)
        if not desktop_path:
            # Retorna 3 valores para consistência com o fluxo principal
            return "ERRO: Nenhum diretório de Área de Trabalho válido foi encontrado para restauração.", None, None

        home_dir = sftp.normalize('.')
        backup_root = posixpath.join(home_dir, 'atalhos_desativados')

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
            return "ERRO: Diretório de backup 'atalhos_desativados' não encontrado na máquina remota.", None, None

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

def build_send_message_command(data):
    """Constrói o comando 'zenity' para enviar uma mensagem."""
    message = data.get('message')
    if not message:
        return None, ({"success": False, "message": "O campo de mensagem não pode estar vazio."}, 400)

    escaped_message = html.escape(message)
    pango_message = f"<span font_size='xx-large'>{escaped_message}</span>"
    safe_message = shlex.quote(pango_message)

    command = f"""
        export DISPLAY=:0;
        if [ -f "$HOME/.Xauthority" ]; then
            export XAUTHORITY="$HOME/.Xauthority";
        else
            export XAUTHORITY=$(find /run/user/$(id -u) -name ".Xauthority" 2>/dev/null | head -n 1);
        fi
        if [ -n "$XAUTHORITY" ]; then
            zenity --info --title="Mensagem do Administrador" --text={safe_message} --width=500;
            echo "Mensagem enviada com sucesso."
        else
            echo "Erro: Não foi possível encontrar o arquivo de autorização X11 para exibir a mensagem.";
            exit 1;
        fi
    """
    return command, None

def build_sudo_command(data, base_command, message):
    """Constrói um comando que requer 'sudo'."""
    # O comando 'sudo' é invocado com a flag '-S' para que ele leia a senha
    # a partir do stdin, em vez de tentar ler de um terminal interativo.
    # A senha é então enviada para o stdin do processo do comando.
    command = f"sudo -S {base_command}"
    return command, None

def _execute_shell_command(ssh, command, password):
    """Executa um comando shell via SSH, tratando sudo e parsing de erros."""
    stdin, stdout, stderr = ssh.exec_command(command, timeout=20)

    # Se o comando usa 'sudo -S', ele espera a senha no stdin.
    if command.strip().startswith("sudo -S"):
        stdin.write(password + '\n')
        stdin.flush()

    output = stdout.read().decode('utf-8').strip()
    error = stderr.read().decode('utf-8').strip()

    # O sudo pode imprimir o prompt de senha no stderr mesmo quando usa -S.
    # Filtramos essa mensagem para não a tratar como um erro real, usando uma
    # expressão regular para lidar com diferentes idiomas (ex: 'senha' ou 'password').
    sudo_prompt_regex = r'\[sudo\] (senha|password) para .*:'
    cleaned_error = re.sub(sudo_prompt_regex, '', error).strip()

    return output, cleaned_error


# --- Rota Principal para Gerenciar Ações via SSH ---
@app.route('/gerenciar_atalhos_ip', methods=['POST'])
def gerenciar_atalhos_ip():
    """
    Recebe as informações do frontend, conecta via SSH e executa o comando apropriado.
    """
    # --- Dicionário de Comandos (Padrão de Dispatch) ---
    # Centraliza os comandos, tornando o código mais limpo e fácil de manter.
    # Usa funções lambda para adiar a construção de comandos que precisam de dados da requisição.
    COMMANDS = {
        'mostrar_sistema': GSETTINGS_ENV_SETUP + """
            gsettings set org.nemo.desktop computer-icon-visible true;
            gsettings set org.nemo.desktop home-icon-visible true;
            gsettings set org.nemo.desktop trash-icon-visible true;
            gsettings set org.nemo.desktop network-icon-visible true;
            echo "Ícones do sistema foram ativados.";
        """,
        'ocultar_sistema': GSETTINGS_ENV_SETUP + """
            gsettings set org.nemo.desktop computer-icon-visible false;
            gsettings set org.nemo.desktop home-icon-visible false;
            gsettings set org.nemo.desktop trash-icon-visible false;
            gsettings set org.nemo.desktop network-icon-visible false;
            echo "Ícones do sistema foram ocultados.";
        """,
        'desativar_barra_tarefas': GSETTINGS_ENV_SETUP + """
            PANEL_IDS=$(gsettings get org.cinnamon panels-enabled | grep -o -P "'\\d+:\\d+:\\w+'" | sed "s/'//g" | cut -d: -f1);
            if [ -z "$PANEL_IDS" ]; then echo "Nenhum painel do Cinnamon encontrado."; exit 1; fi;

            AUTOHIDE_LIST=""
            for id in $PANEL_IDS; do
                AUTOHIDE_LIST+="'$id:true',"
            done;
            AUTOHIDE_LIST=${AUTOHIDE_LIST%,}
            gsettings set org.cinnamon panels-autohide "[$AUTOHIDE_LIST]";
            echo "Barra de tarefas configurada para se ocultar automaticamente.";
        """,
        'ativar_barra_tarefas': GSETTINGS_ENV_SETUP + """
            PANEL_IDS=$(gsettings get org.cinnamon panels-enabled | grep -o -P "'\\d+:\\d+:\\w+'" | sed "s/'//g" | cut -d: -f1);
            if [ -z "$PANEL_IDS" ]; then echo "Nenhum painel do Cinnamon encontrado."; exit 1; fi;

            AUTOHIDE_LIST=""
            for id in $PANEL_IDS; do
                AUTOHIDE_LIST+="'$id:false',"
            done;
            AUTOHIDE_LIST=${AUTOHIDE_LIST%,}
            gsettings set org.cinnamon panels-autohide "[$AUTOHIDE_LIST]";
            echo "Barra de tarefas restaurada para o modo visível.";
        """,
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
        'desativar_perifericos': """
            export DISPLAY=:0;
            if [ -f "$HOME/.Xauthority" ]; then export XAUTHORITY="$HOME/.Xauthority"; else export XAUTHORITY=$(find /run/user/$(id -u) -name ".Xauthority" 2>/dev/null | head -n 1); fi;
            if [ -z "$XAUTHORITY" ]; then echo "Erro: Não foi possível encontrar o arquivo de autorização X11."; exit 1; fi;
            DEVICE_IDS=$(xinput list | grep -i -E 'mouse|keyboard' | grep 'slave' | sed -n 's/.*id=\\([0-9]*\\).*/\\1/p');
            if [ -n "$DEVICE_IDS" ]; then for id in $DEVICE_IDS; do xinput disable $id; done; echo "Mouse e Teclado desativados."; else echo "Nenhum dispositivo de mouse ou teclado encontrado."; fi;
        """,
        'ativar_perifericos': """
            export DISPLAY=:0;
            if [ -f "$HOME/.Xauthority" ]; then export XAUTHORITY="$HOME/.Xauthority"; else export XAUTHORITY=$(find /run/user/$(id -u) -name ".Xauthority" 2>/dev/null | head -n 1); fi;
            if [ -z "$XAUTHORITY" ]; then echo "Erro: Não foi possível encontrar o arquivo de autorização X11."; exit 1; fi;
            DEVICE_IDS=$(xinput list | grep -i -E 'mouse|keyboard' | grep 'slave' | sed -n 's/.*id=\\([0-9]*\\).*/\\1/p');
            if [ -n "$DEVICE_IDS" ]; then for id in $DEVICE_IDS; do xinput enable $id; done; echo "Mouse e Teclado ativados."; else echo "Nenhum dispositivo de mouse ou teclado encontrado."; fi;
        """,
        'limpar_imagens': """
            if [ -d "$HOME/Imagens" ]; then
                rm -rf "$HOME/Imagens"/*;
                echo "Pasta de Imagens foi limpa.";
            else
                echo "Pasta de Imagens não encontrada.";
            fi;
        """,
        'enviar_mensagem': build_send_message_command,
        'reiniciar': lambda data: build_sudo_command(data, "reboot", "Reiniciando a máquina..."),
        'desligar': lambda data: build_sudo_command(data, "shutdown now", "Desligando a máquina...")
    }

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Requisição inválida."}), 400

    ip = data.get('ip')
    action = data.get('action')
    password = data.get('password')

    if not all([ip, action, password]):
        return jsonify({"success": False, "message": "IP, ação e senha são obrigatórios."}), 400

    # --- Conexão e Execução SSH ---
    # Ações que usam SFTP e não um comando shell
    sftp_actions = ['desativar', 'ativar']

    try:
        with ssh_connect(ip, SSH_USERNAME, password) as ssh:
            # Lógica de Despacho de Ação

            # 1. Ações baseadas em SFTP (manipulação de arquivos)
            if action in sftp_actions:
                if action == 'desativar':
                    message, details = sftp_disable_shortcuts(ssh)
                    if details or "ERRO:" in message:
                        return jsonify({"success": False, "message": message, "details": details}), 500
                    return jsonify({"success": True, "message": message}), 200

                elif action == 'ativar':
                    backup_files = data.get('backup_files', [])
                    if not backup_files:
                        return jsonify({"success": False, "message": "Nenhum atalho selecionado para restauração."}), 400
                    message, error_details, warning_details = sftp_restore_shortcuts(ssh, backup_files)

                    # Combina todos os detalhes para a resposta JSON
                    all_details = []
                    if warning_details: all_details.append(warning_details)
                    if error_details: all_details.append(error_details)
                    details_for_json = "\n".join(all_details) if all_details else None

                    # A operação falha apenas se houver erros reais (ex: falha de permissão)
                    if error_details or "ERRO:" in message:
                        return jsonify({"success": False, "message": message, "details": details_for_json}), 500
                    
                    # A operação é um sucesso mesmo com avisos (atalhos não encontrados)
                    return jsonify({"success": True, "message": message, "details": details_for_json}), 200

            # 2. Ações baseadas em Comandos Shell
            command_builder = COMMANDS.get(action)
            if command_builder:
                # Constrói o comando (se for uma função) ou usa a string diretamente
                if callable(command_builder):
                    command, error_response = command_builder(data)
                    if error_response:
                        return jsonify(error_response[0]), error_response[1]
                else:
                    command = command_builder

                # Executa o comando shell e obtém o resultado e os erros limpos.
                output, cleaned_error = _execute_shell_command(ssh, command, password)

                if cleaned_error:
                    app.logger.error(f"Erro no comando '{action}' em {ip}: {cleaned_error}")
                    # Se o erro for sobre senha incorreta, damos uma mensagem mais clara.
                    if "incorrect password attempt" in cleaned_error:
                        return jsonify({"success": False, "message": "Falha na autenticação do sudo. A senha pode estar incorreta.", "details": cleaned_error}), 401
                    return jsonify({"success": False, "message": "Ocorreu um erro no dispositivo remoto.", "details": cleaned_error}), 500

                return jsonify({"success": True, "message": output or "Ação executada com sucesso."}), 200

            # 3. Se a ação não foi encontrada em nenhuma das categorias acima
            return jsonify({"success": False, "message": "Ação desconhecida."}), 400

    except paramiko.AuthenticationException:
        return jsonify({"success": False, "message": "Falha na autenticação. Verifique a senha."}), 401
    except paramiko.SSHException as e:
        app.logger.error(f"Erro de SSH na ação '{action}' em {ip}: {e}")
        return jsonify({"success": False, "message": "Erro de comunicação com o dispositivo remoto."}), 502
    except Exception as e:
        app.logger.error(f"Erro inesperado na ação '{action}' em {ip}: {e}")
        # Não expor detalhes de exceções genéricas
        return jsonify({"success": False, "message": "Ocorreu um erro interno no servidor."}), 500


# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    HOST = "0.0.0.0"
    PORT = 5000
    print(f"🚀 Servidor iniciado em http://{HOST}:{PORT}")
    serve(app, host=HOST, port=PORT)
