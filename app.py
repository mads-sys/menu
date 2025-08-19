import os
import html
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


# --- Funções Construtoras de Comandos Dinâmicos ---

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
        return None, ({"success": False, "message": "Senha é necessária para esta ação."}, 400)

    safe_password = shlex.quote(password)
    command = f"""
        echo "{message}";
        echo {safe_password} | sudo -S {base_command}
    """
    return command, None


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
        'desativar': """
            mkdir -p "$HOME/atalhos_desativados";
            POSSIBLE_DIRS=("$HOME/Área de Trabalho" "$HOME/Desktop" "$HOME/Área de trabalho");
            for dir in "${POSSIBLE_DIRS[@]}"; do
                if [ -d "$dir" ]; then
                    BACKUP_SUBDIR="$HOME/atalhos_desativados/$(basename "$dir")";
                    mkdir -p "$BACKUP_SUBDIR";
                    find "$dir" -maxdepth 1 -type f -name "*.desktop" -exec mv -t "$BACKUP_SUBDIR/" {} + 2>/dev/null;
                fi;
            done;
            echo "Operação de desativação concluída.";
        """,
        'ativar': """
            if [ -d "$HOME/atalhos_desativados" ]; then
                for backup_subdir in "$HOME"/atalhos_desativados/*/; do
                    if [ -d "$backup_subdir" ]; then
                        original_path="$HOME/$(basename "$backup_subdir")";
                        mkdir -p "$original_path";
                        find "$backup_subdir" -maxdepth 1 -type f -name "*.desktop" -exec mv -t "$original_path/" {} + 2>/dev/null;
                    fi;
                done;
            fi;
            echo "Operação de ativação concluída.";
        """,
        'mostrar_sistema': """
            gsettings set org.nemo.desktop computer-icon-visible true;
            gsettings set org.nemo.desktop home-icon-visible true;
            gsettings set org.nemo.desktop trash-icon-visible true;
            gsettings set org.nemo.desktop network-icon-visible true;
            echo "Ícones do sistema foram ativados.";
        """,
        'ocultar_sistema': """
            gsettings set org.nemo.desktop computer-icon-visible false;
            gsettings set org.nemo.desktop home-icon-visible false;
            gsettings set org.nemo.desktop trash-icon-visible false;
            gsettings set org.nemo.desktop network-icon-visible false;
            echo "Ícones do sistema foram ocultados.";
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
            POSSIBLE_DIRS=("$HOME/Imagens" "$HOME/Pictures");
            for dir in "${POSSIBLE_DIRS[@]}"; do
                if [ -d "$dir" ]; then find "$dir" -maxdepth 1 -type f -delete; fi;
            done;
            echo "Arquivos da pasta de imagens foram removidos.";
        """,
        'enviar_mensagem': build_send_message_command,
        'reiniciar': lambda data: build_sudo_command(data, "/sbin/reboot", "Máquina será reiniciada em 5 segundos..."),
        'desligar': lambda data: build_sudo_command(data, "/sbin/shutdown -h now", "Máquina será desligada em 5 segundos..."),
    }

    data = request.json
    if not data or 'ip' not in data or 'password' not in data or 'action' not in data:
        return jsonify({"success": False, "message": "Dados inválidos. IP, senha e ação são obrigatórios."}), 400

    ip = data.get('ip')
    action = data.get('action')
    handler = COMMANDS.get(action)

    if handler is None:
        return jsonify({"success": False, "message": "Ação desconhecida."}), 400

    command = None
    error_response = None

    if callable(handler):
        command, error_response = handler(data)
    else:
        command = handler

    if error_response:
        return jsonify(error_response[0]), error_response[1]

    if command is None:
        return jsonify({"success": False, "message": "Não foi possível construir o comando para a ação."}), 500

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=ip, username=SSH_USERNAME, password=data.get('password'), timeout=10)

        stdin, stdout, stderr = client.exec_command(command, timeout=15)

        stdout_output = stdout.read().decode('utf-8', errors='ignore').strip()
        stderr_output = stderr.read().decode('utf-8', errors='ignore').strip()

        client.close()

        if stderr_output:
            return jsonify({
                "success": False,
                "message": "Ocorreu um erro no dispositivo remoto.",
                "details": stderr_output
            }), 200
        else:
            return jsonify({
                "success": True,
                "message": "Ação executada com sucesso!",
                "details": stdout_output if stdout_output else "Nenhuma saída do comando."
            }), 200

    except paramiko.AuthenticationException:
        return jsonify({"success": False, "message": "Falha na autenticação SSH.", "details": "Verifique o usuário e a senha."}), 200
    except paramiko.SSHException as ssh_ex:
        app.logger.error(f"Erro de SSH para o IP {ip}: {ssh_ex}")
        return jsonify({"success": False, "message": "Erro de conexão SSH.", "details": str(ssh_ex)}), 200
    except Exception as e:
        app.logger.error(f"Erro inesperado para o IP {ip} com ação {action}: {e}")
        return jsonify({"success": False, "message": "Erro inesperado no servidor.", "details": str(e)}), 200


# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    # Usa o servidor Waitress, que é adequado para produção em Windows e outros sistemas.
    print("Servidor iniciado em http://127.0.0.1:5000")
    serve(app, host='0.0.0.0', port=5000)

