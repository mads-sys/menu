from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import platform
import paramiko
import os
import html
import shlex
from multiprocessing import Pool, cpu_count

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens (front-end)
CORS(app)

# --- Configurações Lidas do Ambiente ---
IP_PREFIX = os.getenv("IP_PREFIX", "192.168.0.")
IP_START = int(os.getenv("IP_START", 100))
IP_END = int(os.getenv("IP_END", 125))
SSH_USERNAME = os.getenv("SSH_USERNAME", "aluno")

# --- Função auxiliar para pingar um único IP ---
def ping_ip(ip):
    """
    Tenta pingar um único IP e retorna o IP se for bem-sucedido.
    """
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
    command = ["ping", param, "1", timeout_param, "1000", ip]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return ip
    except (subprocess.TimeoutExpired, Exception):
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
        with Pool(processes=cpu_count()) as pool:
            ping_results = pool.map(ping_ip, ips_to_check)
        
        # Ordena os IPs pelo último octeto para uma exibição consistente.
        active_ips = sorted([ip for ip in ping_results if ip is not None], key=lambda ip: int(ip.split('.')[-1]))

    except Exception as e:
        app.logger.error(f"Erro no pool de processos: {e}")
        return jsonify({"success": False, "message": "Erro ao escanear a rede."}), 500

    if active_ips:
        return jsonify({"success": True, "ips": active_ips}), 200
    else:
        return jsonify({"success": True, "ips": [], "message": "Nenhum dispositivo encontrado na rede."}), 200

# --- Rota para Gerenciar Atalhos via SSH ---
@app.route('/gerenciar_atalhos_ip', methods=['POST'])
def gerenciar_atalhos():
    """
    Recebe as informações do frontend, conecta via SSH e executa o comando.
    """
    data = request.json

    if not data or 'ip' not in data or 'password' not in data or 'action' not in data:
        return jsonify({"success": False, "message": "Dados inválidos. IP, senha e ação são obrigatórios."}), 400
    
    ip = data.get('ip')
    password = data.get('password')
    action = data.get('action')

    # --- Dicionário de Comandos (Padrão de Dispatch) ---
    # Centraliza os comandos, tornando o código mais limpo e fácil de manter.
    COMMANDS = {
        'desativar': """
            mkdir -p "$HOME/atalhos_desativados"
            POSSIBLE_DIRS=("$HOME/Área de Trabalho" "$HOME/Desktop" "$HOME/Área de trabalho")
            for dir in "${POSSIBLE_DIRS[@]}"; do
                if [ -d "$dir" ]; then
                    BACKUP_SUBDIR="$HOME/atalhos_desativados/$(basename "$dir")"
                    mkdir -p "$BACKUP_SUBDIR"
                    find "$dir" -maxdepth 1 -type f -name "*.desktop" -exec mv -t "$BACKUP_SUBDIR/" {} + 2>/dev/null
                fi
            done
            echo "Operação de desativação concluída.";
        """,
        'ativar': """
            if [ -d "$HOME/atalhos_desativados" ]; then
                for backup_subdir in "$HOME"/atalhos_desativados/*/; do
                    if [ -d "$backup_subdir" ]; then
                        original_path="$HOME/$(basename "$backup_subdir")"
                        mkdir -p "$original_path"
                        find "$backup_subdir" -maxdepth 1 -type f -name "*.desktop" -exec mv -t "$original_path/" {} + 2>/dev/null
                    fi
                done
            fi
            echo "Operação de ativação concluída.";
        """,
        'mostrar_sistema': """
            gsettings set org.nemo.desktop computer-icon-visible true;
            gsettings set org.nemo.desktop home-icon-visible true;
            gsettings set org.nemo.desktop trash-icon-visible true;
            gsettings set org.nemo.desktop network-icon-visible true;
            echo "Ícones do sistema foram ativados."
        """,
        'ocultar_sistema': """
            gsettings set org.nemo.desktop computer-icon-visible false;
            gsettings set org.nemo.desktop home-icon-visible false;
            gsettings set org.nemo.desktop trash-icon-visible false;
            gsettings set org.nemo.desktop network-icon-visible false;
            echo "Ícones do sistema foram ocultados."
        """,
        'desativar_perifericos': """
            export DISPLAY=:0;
            # Tenta encontrar o arquivo de autorização X11 correto
            if [ -f "$HOME/.Xauthority" ]; then
                export XAUTHORITY="$HOME/.Xauthority";
            else
                export XAUTHORITY=$(find /run/user/$(id -u) -name ".Xauthority" 2>/dev/null | head -n 1);
            fi
            if [ -z "$XAUTHORITY" ]; then
                echo "Erro: Não foi possível encontrar o arquivo de autorização X11.";
                exit 1;
            fi
            DEVICE_IDS=$(xinput list | grep -i -E 'mouse|keyboard' | grep 'slave' | sed -n 's/.*id=\\([0-9]*\\).*/\\1/p');
            if [ -n "$DEVICE_IDS" ]; then
                for id in $DEVICE_IDS; do
                    xinput disable $id;
                done;
                echo "Mouse e Teclado desativados com sucesso.";
            else
                echo "Nenhum dispositivo de mouse ou teclado encontrado.";
            fi
        """,
        'ativar_perifericos': """
            export DISPLAY=:0;
            # Tenta encontrar o arquivo de autorização X11 correto
            if [ -f "$HOME/.Xauthority" ]; then
                export XAUTHORITY="$HOME/.Xauthority";
            else
                export XAUTHORITY=$(find /run/user/$(id -u) -name ".Xauthority" 2>/dev/null | head -n 1);
            fi
            if [ -z "$XAUTHORITY" ]; then
                echo "Erro: Não foi possível encontrar o arquivo de autorização X11.";
                exit 1;
            fi
            DEVICE_IDS=$(xinput list | grep -i -E 'mouse|keyboard' | grep 'slave' | sed -n 's/.*id=\\([0-9]*\\).*/\\1/p');
            if [ -n "$DEVICE_IDS" ]; then
                for id in $DEVICE_IDS; do
                    xinput enable $id;
                done;
                echo "Mouse e Teclado ativados com sucesso.";
            else
                echo "Nenhum dispositivo de mouse ou teclado encontrado.";
            fi
        """,
        'reiniciar': f"""
            echo "Máquina será reiniciada em 5 segundos...";
            echo {shlex.quote(password)} | sudo -S /sbin/reboot
        """,
        'desligar': f"""
            echo "Máquina será desligada em 5 segundos...";
            echo {shlex.quote(password)} | sudo -S /sbin/shutdown -h now
        """,
        'limpar_imagens': """
            POSSIBLE_DIRS=("$HOME/Imagens" "$HOME/Pictures");
            for dir in "${POSSIBLE_DIRS[@]}"; do
                if [ -d "$dir" ]; then
                    # Deleta todos os arquivos dentro da pasta, mas não os subdiretórios.
                    find "$dir" -maxdepth 1 -type f -delete;
                fi;
            done;
            echo "Arquivos da pasta de imagens foram removidos.";
        """,
    }

    command = COMMANDS.get(action)

    if command is None:
        # Lógica especial para ações que não estão no dicionário, como 'enviar_mensagem'
        if action == 'enviar_mensagem':
            message = data.get('message')
            if not message:
                return jsonify({"success": False, "message": "O campo de mensagem não pode estar vazio."}), 400
            
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
                fi
            """
        else:
            # Se a ação for verdadeiramente desconhecida
            return jsonify({"success": False, "message": "Ação desconhecida."}), 400

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        client.connect(hostname=ip, username=SSH_USERNAME, password=password, timeout=10)
        
        stdin, stdout, stderr = client.exec_command(command, timeout=15)
        
        stdout_output = stdout.read().decode('utf-8', errors='ignore').strip()
        stderr_output = stderr.read().decode('utf-8', errors='ignore').strip()
        
        client.close()
        
        # --- Verificação Crítica: Checa se houve erro na execução do comando ---
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
        return jsonify({"success": False, "message": "Falha na autenticação SSH.", "details": "Verifique o usuário e a senha."}), 401
    except paramiko.SSHException as ssh_ex:
        return jsonify({"success": False, "message": "Erro de conexão SSH.", "details": str(ssh_ex)}), 500
    except Exception as e:
        return jsonify({"success": False, "message": "Erro inesperado no servidor.", "details": str(e)}), 500

# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    # Usa o servidor Waitress, que é adequado para produção.
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000)
