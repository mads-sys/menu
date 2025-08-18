from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import platform
import paramiko
from multiprocessing import Pool, cpu_count

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens (front-end)
CORS(app)

# --- Configurações Editáveis ---
IP_PREFIX = "192.168.0."
IP_START = 100
IP_END = 125
SSH_USERNAME = "aluno"  # IMPORTANTE: Altere para o seu usuário SSH

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
        
        active_ips = [ip for ip in ping_results if ip is not None]

    except Exception as e:
        print(f"Erro no pool de processos: {e}")
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

    # --- Definição dos comandos finais e robustos ---
    # Esta lógica lida com múltiplos nomes de atalho (.desktop) e de pastas, tornando-a mais adaptável.
    if action == 'desativar':
        command = """
            # Cria um diretório de backup principal.
            mkdir -p "$HOME/atalhos_desativados"
            # Lista de possíveis nomes para a pasta da Área de Trabalho.
            POSSIBLE_DIRS=("$HOME/Área de Trabalho" "$HOME/Desktop" "$HOME/Área de trabalho")
            for dir in "${POSSIBLE_DIRS[@]}"; do
                # Se o diretório existir...
                if [ -d "$dir" ]; then
                    # ...cria um subdiretório de backup com o mesmo nome (ex: atalhos_desativados/Desktop)
                    BACKUP_SUBDIR="$HOME/atalhos_desativados/$(basename "$dir")"
                    mkdir -p "$BACKUP_SUBDIR"
                    # e move os atalhos para lá, preservando a origem.
                    find "$dir" -maxdepth 1 -type f -name "*.desktop" -exec mv -t "$BACKUP_SUBDIR/" {} + 2>/dev/null
                fi
            done
            echo "Operação de desativação concluída.";
        """
    elif action == 'ativar':
        command = """
            # Verifica se a pasta de backup principal existe.
            if [ -d "$HOME/atalhos_desativados" ]; then
                # Itera sobre cada subdiretório dentro da pasta de backup (ex: Desktop, Área de Trabalho).
                for backup_subdir in "$HOME"/atalhos_desativados/*/; do
                    if [ -d "$backup_subdir" ]; then
                        # Recria o caminho original e move os arquivos de volta para seu local de origem exato.
                        original_path="$HOME/$(basename "$backup_subdir")"
                        mkdir -p "$original_path"
                        find "$backup_subdir" -maxdepth 1 -type f -name "*.desktop" -exec mv -t "$original_path/" {} + 2>/dev/null
                    fi
                done
            fi
            echo "Operação de ativação concluída.";
        """
    else:
        return jsonify({"success": False, "message": "Ação desconhecida."}), 400

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        client.connect(hostname=ip, username=SSH_USERNAME, password=password, timeout=10)
        
        stdin, stdout, stderr = client.exec_command(command, timeout=15)
        
        stdout_output = stdout.read().decode('utf-8').strip()
        stderr_output = stderr.read().decode('utf-8').strip()
        
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
    # Para produção, considere usar um servidor WSGI como Gunicorn ou Waitress.
    app.run(host='0.0.0.0', port=5000, debug=False)