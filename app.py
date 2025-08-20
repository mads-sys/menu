import os
import html
import posixpath
import platform
import shlex
import subprocess
from multiprocessing import Pool, cpu_count

import paramiko
from flask import Flask, jsonify, request
from flask_cors import CORS
from waitress import serve

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens (front-end)
CORS(app)

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
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
    # Timeout de 1000ms (1 segundo) para o ping
    command = ["ping", param, "1", timeout_param, "1000", ip]

    try:
        # Timeout de 2 segundos para o processo completo
        result = subprocess.run(command, capture_output=True, text=True, timeout=2, check=False)
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

    # Usa 'find' para listar apenas os diretórios de backup, que é mais robusto que 'ls'.
    # -mindepth 1/-maxdepth 1: para pegar apenas o primeiro nível de subdiretórios.
    # O comando agora busca por arquivos .desktop e imprime o caminho relativo (ex: Desktop/MeuAtalho.desktop)
    # Isso permite agrupar por pasta no frontend.
    command = 'if [ -d "$HOME/atalhos_desativados" ]; then find "$HOME/atalhos_desativados" -type f -name "*.desktop" -printf "%P\\n"; fi'

    try:
        with paramiko.SSHClient() as ssh:
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=SSH_USERNAME, password=password, timeout=10)
            _, stdout, stderr = ssh.exec_command(command, timeout=10)
            output = stdout.read().decode('utf-8').strip()
            error = stderr.read().decode('utf-8').strip()

            if error:
                return jsonify({"success": False, "message": "Erro ao listar backups.", "details": error}), 200

            # Processa a saída para agrupar arquivos por diretório
            output_lines = [line for line in output.split('\n') if line]
            backups = {}
            for line in output_lines:
                parts = line.split('/', 1)
                if len(parts) == 2:
                    directory, filename = parts
                    backups.setdefault(directory, []).append(filename)
            return jsonify({"success": True, "backups": backups}), 200

    except Exception as e:
        return jsonify({"success": False, "message": "Erro de conexão ao listar backups.", "details": str(e)}), 200

# --- Funções Construtoras de Comandos Dinâmicos ---

def build_restore_command(data):
    """Constrói o comando para restaurar atalhos selecionados."""
    backup_files = data.get('backup_files', [])
    if not backup_files:
        return None, ({"success": False, "message": "Nenhum atalho foi selecionado para restauração."}, 400)

    # Parte 1: Script estático que define a função e encontra o diretório de destino.
    setup_and_function_def_script = """
        # Função para processar um único arquivo.
        # Argumento 1: Caminho do arquivo de backup relativo a '~/atalhos_desativados/'
        process_one_file() {
            local FILE_PATH_FROM_SOURCE="$1"
            local FILENAME_ONLY
            FILENAME_ONLY=$(basename "$FILE_PATH_FROM_SOURCE")
            
            # Busca o arquivo pelo nome em qualquer subdiretório de backup.
            # Isso torna a restauração independente do nome da pasta de origem.
            local ACTUAL_BACKUP_PATH
            ACTUAL_BACKUP_PATH=$(find "$HOME/atalhos_desativados" -type f -name "$FILENAME_ONLY" | head -n 1)

            echo '---'
            echo "Processando: $FILENAME_ONLY"
            if [ -n "$ACTUAL_BACKUP_PATH" ] && [ -f "$ACTUAL_BACKUP_PATH" ]; then
                mv -f "$ACTUAL_BACKUP_PATH" "$TARGET_DESKTOP_DIR/"
                if [ -f "$TARGET_DESKTOP_DIR/$FILENAME_ONLY" ]; then
                    echo "  -> Sucesso: Arquivo restaurado para $TARGET_DESKTOP_DIR."
                else
                    echo "  -> ERRO: Falha ao mover o arquivo."
                fi
            else
                echo "  -> ERRO: Arquivo de backup '$FILENAME_ONLY' não foi encontrado."
            fi
        }

        echo "Verificando diretório de destino da Área de Trabalho...";
        # Tenta obter o diretório da Área de Trabalho de forma dinâmica com xdg-user-dir
        TARGET_DESKTOP_DIR=$(xdg-user-dir DESKTOP 2>/dev/null)

        # Se xdg-user-dir falhar ou não retornar um diretório válido, tenta uma lista de nomes comuns
        if [ -z "$TARGET_DESKTOP_DIR" ] || [ ! -d "$TARGET_DESKTOP_DIR" ]; then
            # Loop compatível com sh (POSIX) para máxima compatibilidade entre sistemas.
            for dir in "$HOME/Área de Trabalho" "$HOME/Desktop" "$HOME/Área de trabalho" "$HOME/Escritorio"; do
                if [ -d "$dir" ]; then
                    TARGET_DESKTOP_DIR="$dir"
                    break # Usa o primeiro que encontrar
                fi
            done
        fi

        # Se nenhum diretório de desktop foi encontrado, falha.
        if [ -z "$TARGET_DESKTOP_DIR" ] || [ ! -d "$TARGET_DESKTOP_DIR" ]; then
            echo "ERRO: Nenhum diretório de Área de Trabalho válido foi encontrado para restauração.";
            exit 1
        fi
        
        # Garante que o diretório de destino exista
        mkdir -p "$TARGET_DESKTOP_DIR"
        echo "Diretório de destino encontrado: $TARGET_DESKTOP_DIR"
    """

    # Parte 2: Gera as chamadas à função para cada arquivo.
    call_parts = []
    for file_path in backup_files:
        safe_file_path = shlex.quote(file_path)
        call_parts.append(f"process_one_file {safe_file_path}")

    # Parte 3: Junta tudo.
    final_script_parts = [
        setup_and_function_def_script,
        *call_parts, # Desempacota a lista de chamadas
        'echo "---"; echo "Restauração concluída. Verifique os logs acima."'
    ]
    
    command = "\n".join(final_script_parts)
    return command, None

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
    password = data.get('password')
    if not password:
        return None, ({"success": False, "message": "Senha é necessária para a autenticação SSH."}, 400)

    safe_password = shlex.quote(password)
    command = f"echo {safe_password} | sudo -S -p '' {base_command}"
    return command, None


# --- Rota Principal para Gerenciar Ações via SSH ---
@app.route('/gerenciar_atalhos_ip', methods=['POST'])
def gerenciar_atalhos_ip():
    """
    Recebe as informações do frontend, conecta via SSH e executa o comando apropriado.
    """
    # --- Script de Setup de Ambiente para Comandos GSettings ---
    # Este bloco é prependido a todos os comandos que interagem com a interface gráfica
    # para garantir que o ambiente D-Bus do usuário seja encontrado e configurado corretamente.
    GSETTINGS_ENV_SETUP = """
# --- BEGIN GSETTINGS ENVIRONMENT SETUP ---
USER_ID=$(id -u)
if [ -z "$USER_ID" ]; then echo "FATAL: Não foi possível obter o USER_ID."; exit 1; fi

export XDG_RUNTIME_DIR="/run/user/$USER_ID"
if [ ! -d "$XDG_RUNTIME_DIR" ]; then echo "FATAL: Diretório XDG_RUNTIME_DIR não encontrado em $XDG_RUNTIME_DIR."; exit 1; fi

# Tentativa 1: Usar o caminho padrão do socket D-Bus, que é o método mais comum.
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

# Se o socket não existir no caminho padrão, tenta encontrá-lo no ambiente do processo da sessão.
if [ ! -S "$XDG_RUNTIME_DIR/bus" ]; then
    SESSION_PID=$(pgrep -f -u "$USER_ID" -n cinnamon-session)
    if [ -n "$SESSION_PID" ]; then
        DBUS_ADDRESS_FROM_PROC=$(grep -z DBUS_SESSION_BUS_ADDRESS /proc/$SESSION_PID/environ | cut -d= -f2- | tr -d '\\0')
        if [ -n "$DBUS_ADDRESS_FROM_PROC" ]; then
            export DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDRESS_FROM_PROC"
        else
            echo "FATAL: cinnamon-session encontrado (PID: $SESSION_PID), mas a variável DBUS_SESSION_BUS_ADDRESS não foi encontrada em seu ambiente.";
            exit 1;
        fi
    else
        echo "FATAL: Não foi possível encontrar o socket D-Bus em '$XDG_RUNTIME_DIR/bus' nem encontrar um processo 'cinnamon-session' ativo.";
        exit 1;
    fi
fi

# Teste final de comunicação para garantir que o gsettings pode se conectar.
gsettings get org.cinnamon.desktop.interface clock-show-date > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "FATAL: A comunicação com o D-Bus falhou. Verifique as permissões ou se a sessão gráfica está corrompida. DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS";
    exit 1;
fi
# --- END GSETTINGS ENVIRONMENT SETUP ---
"""

    # --- Dicionário de Comandos (Padrão de Dispatch) ---
    # Centraliza os comandos, tornando o código mais limpo e fácil de manter.
    # Usa funções lambda para adiar a construção de comandos que precisam de dados da requisição.
    COMMANDS = {
        'desativar': """
            mkdir -p "$HOME/atalhos_desativados";
            
            # Tenta obter o diretório da Área de Trabalho de forma dinâmica com xdg-user-dir
            DESKTOP_DIR=$(xdg-user-dir DESKTOP 2>/dev/null)

            # Se xdg-user-dir falhar ou não retornar um diretório válido, tenta uma lista de nomes comuns
            if [ -z "$DESKTOP_DIR" ] || [ ! -d "$DESKTOP_DIR" ]; then
                echo "xdg-user-dir não encontrou a Área de Trabalho, tentando caminhos comuns...";
                # Adicione outros nomes de pasta comuns aqui se necessário
                # Loop compatível com sh (POSIX) para máxima compatibilidade entre sistemas.
                for dir in "$HOME/Área de Trabalho" "$HOME/Desktop" "$HOME/Área de trabalho" "$HOME/Escritorio"; do
                    if [ -d "$dir" ]; then
                        DESKTOP_DIR="$dir";
                        echo "Usando diretório de fallback: $DESKTOP_DIR";
                        break; # Usa o primeiro que encontrar
                    fi;
                done;
            fi

            # Se um diretório de desktop foi encontrado, move os atalhos
            if [ -n "$DESKTOP_DIR" ] && [ -d "$DESKTOP_DIR" ]; then
                # O nome do subdiretório de backup é o nome real da pasta (ex: 'Área de Trabalho')
                BACKUP_SUBDIR="$HOME/atalhos_desativados/$(basename "$DESKTOP_DIR")";
                mkdir -p "$BACKUP_SUBDIR";
                find "$DESKTOP_DIR" -maxdepth 1 -type f -name "*.desktop" -exec mv -t "$BACKUP_SUBDIR/" {} + 2>/dev/null;
                echo "Operação de desativação concluída para o diretório '$DESKTOP_DIR'.";
            else
                echo "ERRO: Nenhum diretório de Área de Trabalho válido foi encontrado.";
                exit 1;
            fi
        """,
        'ativar': build_restore_command,
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

    command_builder = COMMANDS.get(action)
    if not command_builder:
        return jsonify({"success": False, "message": "Ação desconhecida."}), 400

    # Constrói o comando (se for uma função) ou usa a string diretamente
    if callable(command_builder):
        command, error_response = command_builder(data)
        if error_response:
            return jsonify(error_response[0]), error_response[1]
    else:
        command = command_builder

    # --- Conexão e Execução SSH ---
    try:
        with paramiko.SSHClient() as ssh:
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=SSH_USERNAME, password=password, timeout=10)

            stdin, stdout, stderr = ssh.exec_command(command, timeout=20)
            output = stdout.read().decode('utf-8').strip()
            error = stderr.read().decode('utf-8').strip()

            if error:
                # Prioriza a mensagem de erro se houver uma
                return jsonify({"success": False, "message": "Ocorreu um erro no dispositivo remoto.", "details": error}), 200

            return jsonify({"success": True, "message": output or "Ação executada com sucesso."}), 200

    except paramiko.AuthenticationException:
        return jsonify({"success": False, "message": "Falha na autenticação. Verifique a senha."}), 200
    except paramiko.SSHException as e:
        return jsonify({"success": False, "message": "Erro de SSH.", "details": str(e)}), 200
    except Exception as e:
        return jsonify({"success": False, "message": "Erro inesperado.", "details": str(e)}), 200


# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    HOST = "0.0.0.0"
    PORT = 5000
    print(f"🚀 Servidor iniciado em http://{HOST}:{PORT}")
    serve(app, host=HOST, port=PORT)
