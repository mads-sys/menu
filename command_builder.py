# services/command_builder.py

import html
import shlex
import re
import logging
from typing import Dict, Tuple, Optional, Any

COMMANDS = {}
COMMAND_METADATA = {}

def register_command(name, label, category, icon='terminal', command_or_func=None, validation_pattern=None, **kwargs):
    """Decorador para registrar comandos e metadados automaticamente."""
    meta = {
        'label': label,
        'category': category,
        'icon': icon,
        'is_streaming': kwargs.get('is_streaming', False),
        'is_dangerous': kwargs.get('is_dangerous', False),
        'description': kwargs.get('description', ''),
        'require_field': kwargs.get('require_field', None),
        'validation_pattern': validation_pattern
    }
    COMMAND_METADATA[name] = meta

    def decorator(func):
        COMMANDS[name] = func
        return func

    if command_or_func is not None:
        COMMANDS[name] = command_or_func
        return command_or_func
    return decorator

@register_command('kill_process', 'Finalizar Processo por Nome', 'Gerenciamento de Processos', icon='x-circle', require_field='process-name-group')
def _build_kill_process_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    process_name = data.get('process_name')
    # Validação rigorosa para evitar injeção de comandos via caracteres especiais
    if not process_name or not re.match(r'^[a-zA-Z0-9._-]+$', process_name):
        return None, {"success": False, "message": "O nome do processo não pode estar vazio."}
    return f"pkill -f {shlex.quote(process_name)}", None

def validate_payload(action: str, data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Valida se o payload contém os campos necessários para a ação antes da execução."""
    meta = COMMAND_METADATA.get(action)
    if not meta:
        return True, None
        
    field = meta.get('require_field')
    if field:
        # Extrai o nome da chave do payload baseando-se no grupo (simplificado)
        key = field.replace('-group', '').replace('-', '_')
        if not data.get(key):
            return False, f"O campo '{key}' é obrigatório para esta ação."
    return True, None

class CommandExecutionError(Exception):
    """Exceção lançada quando um comando shell falha."""
    def __init__(self, message, details=None, warnings=None):
        super().__init__(message)
        self.details = details
        self.warnings = warnings

_SCRIPT_CACHE = {}

# --- Carregar Scripts Externos ---
def _load_script(filename: str) -> str:
    """Carrega um script de um arquivo, com fallback e log de erro para stderr."""
    if filename in _SCRIPT_CACHE:
        return _SCRIPT_CACHE[filename]
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
            _SCRIPT_CACHE[filename] = content
            return content
    except (FileNotFoundError, IOError) as e:
        logging.error(f"Não foi possível carregar o script {filename}: {e}")
        return f"echo 'ERRO FATAL: Script {filename} ausente no servidor'; exit 1;"

# Scripts são carregados uma vez quando o módulo é importado
# A dependência do 'current_app' foi removida para evitar erros de contexto de aplicação.
GSETTINGS_ENV_SETUP = _load_script('setup_gsettings_env.sh')
MANAGE_RIGHT_CLICK_SCRIPT = _load_script('manage_right_click.sh')
MANAGE_PERIPHERALS_SCRIPT = _load_script('manage_peripherals.sh')
X11_ENV_SETUP = _load_script('setup_x11_env.sh')
UPDATE_MANAGER_SCRIPT = _load_script('update_manager.py')

# --- Funções auxiliares para construir comandos shell ---
def _parse_system_info(output: str) -> Dict[str, str]:
    """Analisa a saída estruturada do comando de informações do sistema."""
    info = {}
    
    # Mapeamento de marcadores para campos de informação
    markers = {
        'cpu': (r'---CPU_USAGE---', r'----MEMORY----'),
        'memory': (r'----MEMORY----', r'----DISK----'),
        'disk': (r'----DISK----', r'----UPTIME----'),
        'uptime': (r'----UPTIME----', r'----REMOTE_TIME----'),
        'remote_time': (r'----REMOTE_TIME----', r'----END----')
    }

    for key, (start, end) in markers.items():
        pattern = f"{start}(.*?){end}"
        match = re.search(pattern, output, re.DOTALL)
        info[key] = match.group(1).strip() if match else "N/A"
        
    return info

def build_send_message_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Constrói o comando 'zenity' para enviar uma mensagem, usando o ambiente X11 padronizado."""
    message = data.get('message')
    if not message:
        return None, {"success": False, "message": "O campo de mensagem não pode estar vazio."}

    escaped_message = html.escape(message)
    # Usa Pango markup para deixar o texto grande e em negrito para maior impacto.
    pango_message = f"<span font_size='xx-large' font_weight='bold'>{escaped_message}</span>"
    safe_message = shlex.quote(pango_message)

    # Reutiliza o script de setup do ambiente X11 para consistência e robustez.
    core_logic = f"""
        if ! command -v zenity &> /dev/null; then
            echo "ERRO: O comando 'zenity' não foi encontrado na máquina remota." >&2
            exit 1
        fi
        # Usa 'zenity --error' para um diálogo modal e bloqueante.
        # A ausência de 'nohup' e '&' faz com que o script espere o usuário clicar em 'OK'.
        # A saída é redirecionada para /dev/null para manter o log limpo.
        zenity --error --title="Mensagem do Administrador" --text={safe_message} --width=500 --height=200 > /dev/null 2>&1
        echo "Mensagem confirmada pelo usuário."
    """
    
    full_command = X11_ENV_SETUP + core_logic
    return full_command, None

def _build_fire_and_forget_command(data: Dict[str, Any], base_command: str, message: str) -> Tuple[str, None]:
    """
    Constrói um comando que será executado em segundo plano e não aguardará uma resposta.
    Ideal para ações como 'reboot' ou 'shutdown' que encerram a conexão SSH.
    """
    password = data.get('password')
    safe_password = shlex.quote(password)
    command = f"echo {safe_password} | sudo -S nohup {base_command} > /dev/null 2>&1 & disown"
    return command, None
def build_sudo_command(data: Dict[str, Any], base_command: str, message: str) -> Tuple[str, None]:
    """Constrói um comando que requer 'sudo'."""
    # O 'sudo' agora é tratado centralmente pela função de execução (_execute_shell_command).
    # Esta função agora atua como um pass-through para manter a estrutura dos lambdas.
    return base_command, None

@register_command('get_system_info', 'Informações do Sistema', 'Monitoramento', icon='info')
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
        echo "----REMOTE_TIME----"
        date +"%H:%M:%S"
        echo "----END----"
    """
    return command, None

@register_command('check_ssh_config', 'Verificar Configuração SSH', 'Monitoramento', icon='settings')
def _build_check_ssh_config_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Verifica se o SSH está configurado para permitir túneis e encaminhamentos."""
    return r"""
        echo "--- CONFIGURAÇÃO SSH (/etc/ssh/sshd_config) ---"
        # Busca pelas diretivas e indica se estão comentadas (usando padrão) ou explícitas
        for opt in AllowTcpForwarding GatewayPorts X11Forwarding PermitTunnel; do
            grep -Ei "^#?\\s*$opt" /etc/ssh/sshd_config | while read -r line; do
                if [[ "$line" =~ ^# ]]; then
                    echo -e "$opt: \e[33m[COMENTADO]\e[0m $line (Usa padrão do sistema)"
                else
                    echo -e "$opt: \e[32m[ATIVO]\e[0m $line"
                fi
            done | tail -n 1
            # Se não encontrar nada, avisa que está no padrão total
            if [ ${PIPESTATUS[0]} -ne 0 ]; then echo "$opt: [Não encontrado] (Padrão)"; fi
        done
        echo ""
        echo "--- STATUS DO SERVIÇO SSH ---"
        systemctl is-active ssh || service ssh status | grep "Active:"
    """, None

@register_command('enable_tcp_forwarding', 'Habilitar TCP Forwarding SSH', 'Gerenciamento do Sistema', icon='share-2', is_dangerous=True)
def _build_enable_tcp_forwarding_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Descomenta ou adiciona a permissão de túnel SSH na máquina remota."""
    return """
        # Remove comentários de qualquer linha que contenha AllowTcpForwarding e força 'yes'
        sudo sed -i 's/^[# ]*AllowTcpForwarding.*/AllowTcpForwarding yes/' /etc/ssh/sshd_config
        
        # Se a linha não existir de forma alguma, adiciona ao final
        if ! grep -iq "^AllowTcpForwarding yes" /etc/ssh/sshd_config; then
            echo "AllowTcpForwarding yes" | sudo tee -a /etc/ssh/sshd_config > /dev/null
        fi
        
        echo "Configuração aplicada. Reiniciando serviço SSH..."
        sudo systemctl restart ssh || sudo service ssh restart
    """, None

@register_command('atualizar_sistema', 'Atualizar Sistema', 'Gerenciamento do Sistema', icon='refresh-cw', is_streaming=True)
def _build_update_system_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói um comando que transfere e executa o script update_manager.py na máquina remota.
    """
    quoted_script_content = shlex.quote(UPDATE_MANAGER_SCRIPT)
    script_runner = f"""
        set -e
        SCRIPT_PATH="/tmp/update_manager.py"
        echo {quoted_script_content} > "$SCRIPT_PATH"
        chmod +x "$SCRIPT_PATH"
        /usr/bin/python3 -u "$SCRIPT_PATH"
    """
    return script_runner, None

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

# --- Comandos para Multiseat (loginctl) ---
@register_command('info_multiseat', 'Informações Multiseat (CLI)', 'Multiseat', icon='activity')
def _build_multiseat_info_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Coleta informações para configuração de Multiseat."""
    command = """
        echo "--- Placas de Vídeo (lspci) ---"
        lspci | grep -E "VGA|3D"
        echo ""
        echo "--- Árvore USB (lsusb -t) ---"
        lsusb -t
        echo ""
        echo "--- Seats Atuais ---"
        loginctl list-seats
    """
    return command, None

@register_command('scan_multiseat', 'Gerenciador Gráfico Multiseat', 'Multiseat', icon='search')
def _build_multiseat_scan_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói um script Python para ser executado remotamente.
    Este script descobre GPUs e dispositivos USB e retorna um JSON para a interface gráfica.
    """
    remote_script = r"""
import os
import json
import re
import subprocess
import sys
import shlex

# Cache para mapeamento do loginctl
LOGINCTL_MAP = {}

def load_loginctl_map():
    try:
        # Obtém lista de seats
        seats_out = subprocess.check_output(['loginctl', 'list-seats', '--no-legend'], stderr=subprocess.DEVNULL).decode()
        for seat in seats_out.splitlines():
            seat = seat.strip()
            if not seat: continue
            try:
                # Para cada seat, pega os dispositivos associados
                status_out = subprocess.check_output(['loginctl', 'seat-status', seat], stderr=subprocess.DEVNULL).decode()
                for line in status_out.splitlines():
                    # Regex para capturar caminhos /sys/ ignorando caracteres de arvore (├─, │, espaços)
                    match = re.search(r'(/sys/\S+)', line)
                    if match:
                        path = match.group(1)
                        LOGINCTL_MAP[path] = seat
                        try:
                            LOGINCTL_MAP[os.path.realpath(path)] = seat
                        except: pass
            except: pass
    except: pass

def get_device_seat(device_path):
    # Consulta o udev para descobrir a qual seat o dispositivo pertence.
    udev_seat = None
    try:
        # --query=property retorna pares CHAVE=VALOR. Buscamos ID_SEAT.
        out = subprocess.check_output(['udevadm', 'info', '--query=property', '--path', device_path], stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            if line.startswith('ID_SEAT='):
                val = line.split('=', 1)[1].strip()
                if val != 'seat0': return val # Se jÃ¡ for seat1, retorna.
                udev_seat = val # Se for seat0, guarda mas continua verificando filhos.
    except: pass
    
    # Fallback: Verifica se o dispositivo (ou seus filhos) está no mapa do loginctl
    if device_path in LOGINCTL_MAP: return LOGINCTL_MAP[device_path]
    
    for path, seat in LOGINCTL_MAP.items():
        if seat == 'seat0': continue
        # Se o caminho registrado no loginctl (ex: drm/card1) é filho deste dispositivo (ex: pci.../01:00.0)
        if path.startswith(device_path):
            return seat
        
        # NOVO: Se o caminho registrado no loginctl é PAI deste dispositivo (ex: Hub USB atribuído, mouse filho)
        # Adiciona '/' para garantir que não haja match parcial de nomes (ex: usb1 vs usb10)
        if device_path.startswith(path + '/'):
            return seat
            
    return udev_seat if udev_seat else 'seat0'

def scan_devices():
    load_loginctl_map()
    devices = []
    
    # 1. Scan GPUs (PCI)
    try:
        lspci_out = subprocess.check_output(['lspci', '-Dmm']).decode()
        for line in lspci_out.splitlines():
            # Usa shlex para dividir corretamente respeitando as aspas
            parts = shlex.split(line)
            if len(parts) >= 4:
                slot = parts[0]
                cls = parts[1]
                vendor = parts[2]
                device_name = parts[3]
                
                # Tenta capturar o Subsystem Vendor (fabricante da placa) para melhor identificação
                sub_vendor = parts[4] if len(parts) > 4 else ""
                
                # Filtra VGA, 3D, Display e Audio
                if "VGA" in cls or "3D" in cls or "Display" in cls or "Audio" in cls:
                    # Tenta obter o caminho canônico via udevadm, que é o padrão exigido pelo loginctl/systemd
                    try:
                        udev_path = subprocess.check_output(['udevadm', 'info', '-q', 'path', '-p', f"/sys/bus/pci/devices/{slot}"], stderr=subprocess.DEVNULL).decode().strip()
                        sys_path = f"/sys{udev_path}"
                    except:
                        # Fallback se udevadm falhar
                        sys_path = os.path.realpath(f"/sys/bus/pci/devices/{slot}")
                    
                    seat = get_device_seat(sys_path)
                    
                    # Limpeza robusta do nome do dispositivo
                    clean_name = device_name.replace('"', '')
                    # Regex para remover flags do lspci como -rXX ou -pXX no final
                    clean_name = re.sub(r'\s-(r|p)[0-9a-fA-F]+.*$', '', clean_name).strip()
                    
                    # Constrói um nome mais descritivo com o Sub-vendor se disponível
                    full_name = f"{vendor} {clean_name}"
                    if sub_vendor and sub_vendor != vendor and sub_vendor != device_name:
                        full_name += f" ({sub_vendor})"
                    
                    type_label = 'GPU'
                    if "Audio" in cls: type_label = 'Áudio'
                    
                    devices.append({'type': type_label, 'name': full_name, 'path': sys_path, 'seat': seat, 'id': slot})
    except:
        pass

    # 2. Scan USB Devices
    usb_root = '/sys/bus/usb/devices'
    if os.path.exists(usb_root):
        for d in os.listdir(usb_root):
            path = os.path.join(usb_root, d)
            # Verifica se é um dispositivo físico (tem idVendor) para ignorar interfaces puras
            if os.path.exists(os.path.join(path, 'idVendor')):
                try:
                    product = ""
                    mfg = ""
                    # Leitura segura dos nomes com fallback
                    if os.path.exists(os.path.join(path, 'product')):
                        try:
                            with open(os.path.join(path, 'product'), 'r') as f: product = f.read().strip()
                        except: pass
                    
                    if os.path.exists(os.path.join(path, 'manufacturer')):
                        try:
                            with open(os.path.join(path, 'manufacturer'), 'r') as f: mfg = f.read().strip()
                        except: pass
                    
                    # Se não conseguiu ler nomes, usa IDs
                    if not mfg:
                        with open(os.path.join(path, 'idVendor'), 'r') as f: mfg = f"ID:{f.read().strip()}"
                    if not product:
                        with open(os.path.join(path, 'idProduct'), 'r') as f: product = f"ID:{f.read().strip()}"
                    
                    full_name = f"{mfg} {product}".strip()
                    real_path = os.path.realpath(path) # Resolve links simbólicos para o caminho real /sys/devices/...
                    seat = get_device_seat(real_path)

                    # Tenta identificar o tipo (Keyboard/Mouse/Audio) olhando as interfaces filhas
                    dev_type = 'USB'
                    found_mouse = False
                    found_kb = False
                    found_audio = False

                    # Verifica se é um Hub na raiz do dispositivo
                    if os.path.exists(os.path.join(path, 'bDeviceClass')):
                        try:
                            with open(os.path.join(path, 'bDeviceClass'), 'r') as f:
                                if f.read().strip() == '09': dev_type = 'Hub USB'
                        except: pass

                    for root, dirs, files in os.walk(path):
                        if 'bInterfaceClass' in files:
                            try:
                                with open(os.path.join(root, 'bInterfaceClass'), 'r') as f:
                                    cls = f.read().strip()
                                    if cls == '01': found_audio = True
                            except: pass

                        if 'bInterfaceProtocol' in files: # Heurística simples
                            try:
                                with open(os.path.join(root, 'bInterfaceProtocol'), 'r') as f:
                                    proto = f.read().strip()
                                    if proto == '01': found_kb = True
                                    elif proto == '02': found_mouse = True
                            except: pass
                    
                    if found_audio: dev_type = 'Áudio'
                    elif found_mouse: dev_type = 'Mouse'
                    elif found_kb: dev_type = 'Teclado'
                    
                    devices.append({'type': dev_type, 'name': full_name, 'path': real_path, 'seat': seat, 'id': d})
                except:
                    continue

    print(json.dumps(devices, ensure_ascii=False))

scan_devices()
    """
    # Envolve em python3 -c para execução segura
    command = f"python3 -c {shlex.quote(remote_script)}"
    return command, None

@register_command('anexar_dispositivo_seat', 'Anexar Dispositivo ao Seat', 'Multiseat', icon='link', require_field='device-path-group')
def _build_attach_seat_device_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Constrói o comando para anexar um dispositivo a um seat específico."""
    device_path = data.get('device_path')
    # O padrão é 'seat0' para segurança. Se um dispositivo for movido para um lugar inválido, ele volta para o principal.
    target_seat = data.get('target_seat', 'seat0')

    if not device_path:
        return None, {"success": False, "message": "O caminho do dispositivo é obrigatório."}
    
    safe_path = shlex.quote(device_path)
    safe_seat = shlex.quote(target_seat)
    
    command = f"""
    DEVICE_PATH={safe_path}
    TARGET_SEAT={safe_seat}
    # Garante o formato correto do DEVPATH (inicia com /devices)
    REL_PATH="${{DEVICE_PATH#/sys}}"
    [[ "$REL_PATH" != /* ]] && REL_PATH="/$REL_PATH"
    
    SAFE_NAME=$(echo "$DEVICE_PATH" | tr -cd '[:alnum:]._-')
    RULE_FILE="/etc/udev/rules.d/90-multiseat-$SAFE_NAME.rules"

    # Detecta se é um dispositivo de vídeo
    IS_VIDEO=0
    if echo "$DEVICE_PATH" | grep -qi -E "pci|drm|graphics|vga|nvidia"; then IS_VIDEO=1; fi

    # Criamos a regra:
    # 1. TAG-=\\"seat\\" remove a placa do seat0 (impede o modo estendido)
    # 2. TAG+=\"master-of-seat\" e ID_AUTOSEAT força a criação do novo assento
    # 3. TAG+=\"uaccess\" garante que o usuário do seat1 possa acessar a GPU
    # 4. Adicionado o curinga * no DEVPATH para garantir que interfaces filhas (HID) herdem a regra
    OPTS="TAG-=\"seat\", TAG+=\"seat\", TAG+=\"uaccess\", ENV{{ID_SEAT}}=\"$TARGET_SEAT\", ENV{{ID_FOR_SEAT}}=\"$TARGET_SEAT\", ENV{{GUD_SEAT}}=\"$TARGET_SEAT\""
    
    if [ "$IS_VIDEO" -eq 1 ]; then
        OPTS="$OPTS, TAG+=\"master-of-seat\", ENV{{ID_AUTOSEAT}}=\"1\""
    fi

    if [ "$TARGET_SEAT" = "seat0" ]; then
        # Se o destino for o assento padrão, removemos a regra customizada
        rm -f "$RULE_FILE"
        echo "Regra customizada para $DEVICE_PATH removida (voltando ao assento padrão)."
    else
        # Usamos Heredoc (cat <<EOF) para evitar problemas com pipes (|) e aspas no shell
        if [ "$IS_VIDEO" -eq 1 ]; then
            cat <<EOF > "$RULE_FILE"
ACTION=="add|change", DEVPATH="$REL_PATH*", TAG-="seat", TAG+="seat", TAG+="uaccess", ENV{{ID_SEAT}}:="$TARGET_SEAT", ENV{{ID_FOR_SEAT}}:="$TARGET_SEAT", ENV{{GUD_SEAT}}:="$TARGET_SEAT", TAG+="master-of-seat", ENV{{ID_AUTOSEAT}}="1"
EOF
        else
            cat <<EOF > "$RULE_FILE"
ACTION=="add|change", DEVPATH="$REL_PATH*", TAG-="seat", TAG+="seat", TAG+="uaccess", ENV{{ID_SEAT}}:="$TARGET_SEAT", ENV{{ID_FOR_SEAT}}:="$TARGET_SEAT", ENV{{GUD_SEAT}}:="$TARGET_SEAT"
EOF
        fi
        echo "Regra udev gravada em $RULE_FILE"
    fi

    udevadm control --reload-rules
    udevadm trigger --action=change "$DEVICE_PATH"
    udevadm trigger --action=change --parent-match="$DEVICE_PATH"
    udevadm settle
    
    # Inteligência: Aguarda proativamente até que o udev propague a tag 'seat'
    echo "Verificando aplicação da configuração no sistema..."
    MAX_RETRIES=15
    COUNT=0
    SUCCESS=0
    while [ $COUNT -lt $MAX_RETRIES ]; do
        if udevadm info --query=property --path="$DEVICE_PATH" | grep -qE "ID_SEAT=$TARGET_SEAT|TAGS=.*:seat:"; then
            echo "Configuração detectada com sucesso pelo udev."
            SUCCESS=1
            break
        fi
        echo "Aguardando udev (tentativa $((COUNT+1))/$MAX_RETRIES)..."
        sleep 1
        ((COUNT++))
        udevadm trigger --action=change "$DEVICE_PATH"
    done

    [ $SUCCESS -eq 0 ] && echo "AVISO: A tag seat não foi detectada pelo udevadm, mas tentaremos o loginctl mesmo assim."
    
    if loginctl attach "$TARGET_SEAT" "$DEVICE_PATH"; then
        echo "Sucesso: Dispositivo atribuído ao $TARGET_SEAT com sucesso."
    else
        echo "ERRO: Falha ao anexar o dispositivo $DEVICE_PATH ao $TARGET_SEAT via loginctl." >&2
        echo "DICA: A regra udev pode não ter sido aplicada a tempo. Tente novamente ou verifique journalctl -xe." >&2
        exit 1 # Força a falha do script se loginctl attach falhar
    fi
    
    echo "DICA: Se o vídeo ainda estiver estendido, reinicie a máquina para que o seat0 pare de 'sequestrar' esta placa."
    """
    return command, None

# Registro de comandos simples e baseados em strings
register_command('mostrar_sistema', 'Mostrar Ícones do Sistema', 'Gerenciamento do Sistema', icon='eye', command_or_func=_build_gsettings_visibility_command(True))
register_command('ocultar_sistema', 'Ocultar Ícones do Sistema', 'Gerenciamento do Sistema', icon='eye-off', command_or_func=_build_gsettings_visibility_command(False))
register_command('desativar', 'Desativar Atalhos (Backup)', 'Controle da Interface', icon='file-minus')
register_command('ativar', 'Restaurar Atalhos', 'Controle da Interface', icon='file-plus')
register_command('desativar_barra_tarefas', 'Ocultar Barra de Tarefas', 'Controle da Interface', icon='minimize-2', command_or_func=_build_panel_autohide_command(True))
register_command('ativar_barra_tarefas', 'Restaurar Barra de Tarefas', 'Controle da Interface', icon='maximize-2', command_or_func=_build_panel_autohide_command(False))
register_command('bloquear_barra_tarefas', 'Bloquear Barra de Tarefas', 'Controle da Interface', icon='lock', command_or_func=GSETTINGS_ENV_SETUP + """
        gsettings get org.cinnamon enabled-applets > "$HOME/.applet_config_backup"
        gsettings set org.cinnamon enabled-applets "[]"
        echo "Barra de tarefas bloqueada (applets removidos).";
    """)
register_command('desbloquear_barra_tarefas', 'Desbloquear Barra de Tarefas', 'Controle da Interface', icon='unlock', command_or_func=GSETTINGS_ENV_SETUP + """
        BACKUP_FILE="$HOME/.applet_config_backup"
        if [ -f "$BACKUP_FILE" ]; then
            gsettings set org.cinnamon enabled-applets "$(cat "$BACKUP_FILE")";
            rm "$BACKUP_FILE";
            echo "Barra de tarefas desbloqueada (applets restaurados).";
        else
            echo "Nenhum backup da barra de tarefas encontrado para restaurar.";
        fi;
    """)
register_command('definir_firefox_padrao', 'Firefox como Padrão', 'Configurações do Navegador', icon='globe', command_or_func=_build_xdg_default_browser_command('firefox.desktop'))
register_command('definir_chrome_padrao', 'Chrome como Padrão', 'Configurações do Navegador', icon='globe', command_or_func=_build_xdg_default_browser_command('google-chrome.desktop'))
register_command('desativar_perifericos', 'Desativar Mouse e Teclado', 'Controle de Periféricos', icon='mouse-pointer', command_or_func=_build_x_command_builder(MANAGE_PERIPHERALS_SCRIPT, 'disable', 'xinput'))
register_command('ativar_perifericos', 'Ativar Mouse e Teclado', 'Controle de Periféricos', icon='mouse-pointer', command_or_func=_build_x_command_builder(MANAGE_PERIPHERALS_SCRIPT, 'enable', 'xinput'))
register_command('desativar_botao_direito', 'Desativar Botão Direito', 'Controle de Periféricos', icon='slash', command_or_func=_build_x_command_builder(MANAGE_RIGHT_CLICK_SCRIPT, 'disable', 'xinput'))
register_command('ativar_botao_direito', 'Ativar Botão Direito', 'Controle de Periféricos', icon='mouse-pointer', command_or_func=_build_x_command_builder(MANAGE_RIGHT_CLICK_SCRIPT, 'enable', 'xinput'))

@register_command('bloquear_config_rede', 'Bloquear Alteração de Rede', 'Configurações de Rede', icon='lock')
def _build_block_network_settings(data: Dict[str, Any]) -> Tuple[str, None]:
    """Cria uma regra de Polkit para impedir que o usuário 'aluno' modifique a rede."""
    # A regra Polkit será mais abrangente para cobrir diversas ações do NetworkManager
    script = """
        sudo mkdir -p /etc/polkit-1/rules.d
        cat <<EOF | sudo tee /etc/polkit-1/rules.d/99-disable-network.rules > /dev/null
polkit.addRule(function(action, subject) {
    // Aplica a regra apenas para o usuário 'aluno'
    if (subject.user == "aluno") {
        // Bloqueia todas as ações relacionadas ao NetworkManager
        if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0) {
            return polkit.Result.NO;
        }
        // Ações específicas do NetworkManager que podem ser usadas para bypass
        if (action.id == "org.freedesktop.NetworkManager.settings.modify.system" ||
            action.id == "org.freedesktop.NetworkManager.settings.modify.own" || // Para conexões específicas do usuário
            action.id == "org.freedesktop.NetworkManager.settings.save" ||
            action.id == "org.freedesktop.NetworkManager.network-control" || // Controle geral da rede
            action.id == "org.freedesktop.NetworkManager.enable-disable-network" ||
            action.id == "org.freedesktop.NetworkManager.enable-disable-wifi" ||
            action.id == "org.freedesktop.NetworkManager.enable-disable-wwan" ||
            action.id == "org.freedesktop.NetworkManager.enable-disable-wimax" ||
            action.id == "org.freedesktop.NetworkManager.sleep" || // Suspender/retomar rede
            action.id == "org.freedesktop.NetworkManager.wifi.share.protected" ||
            action.id == "org.freedesktop.NetworkManager.wifi.share.open" ||
            action.id == "org.freedesktop.NetworkManager.settings.modify.hostname") {
            return polkit.Result.NO;
        }
        // Bloqueia ações de gerenciamento de unidades do systemd que afetam a rede
        if (action.id.indexOf("org.freedesktop.systemd1.manage-units") !== -1 &&
            (action.lookup("unit") == "NetworkManager.service" || action.lookup("unit") == "network.service")) {
            return polkit.Result.NO;
        }
        // Bloqueia a modificação de configurações de rede via udisks2 (montagem de dispositivos de rede)
        if (action.id.indexOf("org.freedesktop.udisks2.filesystem-mount-system") !== -1) {
            return polkit.Result.NO;
        }
        // Bloqueia a execução de nmcli (se o usuário tentar usar pkexec nmcli)
        if (action.id == "org.freedesktop.policykit.exec" && action.lookup("program") == "nmcli") {
            return polkit.Result.NO;
        }
    }
    // Permite outras ações por padrão
    return polkit.Result.YES;
});
EOF
        # Força o Polkit a recarregar as regras reiniciando o serviço
        sudo systemctl restart polkit.service || true # Tenta reiniciar, mas não falha se não conseguir
        
        echo "Regras Polkit para bloquear alterações de rede para o usuário 'aluno' aplicadas."
    """
    return script.strip(), None

@register_command('desbloquear_config_rede', 'Desbloquear Alteração de Rede', 'Configurações de Rede', icon='unlock')
def _build_unblock_network_settings(data: Dict[str, Any]) -> Tuple[str, None]:
    """Remove a regra de Polkit que bloqueia a alteração de rede."""
    script = """
        sudo rm -f /etc/polkit-1/rules.d/99-disable-network.rules
        sudo systemctl restart polkit.service || true # Reinicia Polkit para remover a regra
        echo "Alteração de configurações de rede permitida novamente."
    """
    return script.strip(), None

@register_command('bloquear_terminal', 'Bloquear Terminal', 'Controle da Interface', icon='terminal')
def _build_block_terminal_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Bloqueia a execução do terminal e linha de comando via gsettings."""
    script = GSETTINGS_ENV_SETUP + """
        gsettings set org.cinnamon.desktop.lockdown disable-command-line true 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.terminal "[]" 2>/dev/null || true
        gsettings set org.gnome.desktop.lockdown disable-command-line true 2>/dev/null || true
        echo "Acesso ao terminal e linha de comando bloqueado."
    """
    return script.strip(), None

@register_command('desbloquear_terminal', 'Desbloquear Terminal', 'Controle da Interface', icon='terminal')
def _build_unblock_terminal_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Restaura o acesso ao terminal via gsettings."""
    script = GSETTINGS_ENV_SETUP + """
        gsettings set org.cinnamon.desktop.lockdown disable-command-line false 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.terminal "['<Primary><Alt>t']" 2>/dev/null || true
        gsettings set org.gnome.desktop.lockdown disable-command-line false 2>/dev/null || true
        echo "Acesso ao terminal restaurado."
    """
    return script.strip(), None

@register_command('bloquear_dconf', 'Bloquear dconf-editor', 'Controle da Interface', icon='shield')
def _build_block_dconf_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Impede que o usuário 'aluno' execute o dconf-editor via permissões de arquivo."""
    script = """
        DCONF_BIN=$(which dconf-editor)
        if [ -z "$DCONF_BIN" ]; then
            echo "dconf-editor não está instalado."
        else
            # Tenta aplicar ACL para bloquear especificamente o usuário 'aluno'
            sudo setfacl -m u:aluno:--- "$DCONF_BIN" 2>/dev/null || sudo chmod 700 "$DCONF_BIN"
            echo "Acesso ao dconf-editor bloqueado para o usuário 'aluno'."
        fi
    """
    return script.strip(), None

@register_command('desbloquear_dconf', 'Desbloquear dconf-editor', 'Controle da Interface', icon='shield-off')
def _build_unblock_dconf_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Restaura o acesso ao dconf-editor para o usuário 'aluno'."""
    script = """
        DCONF_BIN=$(which dconf-editor)
        if [ -n "$DCONF_BIN" ]; then
            # Remove a restrição da ACL e volta permissão padrão
            sudo setfacl -x u:aluno "$DCONF_BIN" 2>/dev/null
            sudo chmod 755 "$DCONF_BIN"
            echo "Acesso ao dconf-editor restaurado."
        fi
    """
    return script.strip(), None

@register_command('deslogar_todos', 'Deslogar Todos os Usuários', 'Ações Remotas', icon='user-x', is_dangerous=True)
def _build_logout_all_users_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Localiza e encerra todas as sessões gráficas (X11/Wayland) ativas na máquina."""
    script = """
        echo "Identificando sessões ativas para encerramento..."
        # Obtém os IDs de todas as sessões registradas no sistema
        SIDS=$(loginctl list-sessions --no-legend | awk '{print $1}')
        
        COUNT=0
        for ID in $SIDS; do
            # Verifica o tipo de sessão (x11, wayland, tty, etc)
            TYPE=$(loginctl show-session "$ID" -p Type --value 2>/dev/null)
            
            if [[ "$TYPE" == "x11" || "$TYPE" == "wayland" ]]; then
                USER=$(loginctl show-session "$ID" -p Name --value 2>/dev/null)
                echo "Encerrando sessão $ID (Usuário: $USER, Tipo: $TYPE)..."
                sudo loginctl terminate-session "$ID"
                ((COUNT++))
            fi
        done
        echo "Total de $COUNT sessões gráficas encerradas com sucesso."
    """
    return script.strip(), None

@register_command('remover_todos_bloqueios', 'Remover TODOS os Bloqueios', 'Ações Remotas', icon='unlock', is_dangerous=True)
def _build_remove_all_blocks_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Script abrangente para reverter todas as restrições do sistema e do usuário."""
    script = GSETTINGS_ENV_SETUP + r"""
        echo "--- INICIANDO DESBLOQUEIO TOTAL DE EMERGÊNCIA ---"
        
        # 1. Rede e Polkit
        echo "[1/5] Restaurando DNS e permissões de rede..."
        CONN_UUID=$(nmcli -t -f UUID,TYPE,STATE connection show --active | grep -E ":802-3-ethernet|:802-11-wireless" | head -n1 | cut -d: -f1)
        if [ -n "$CONN_UUID" ]; then
            sudo nmcli connection modify "$CONN_UUID" ipv4.dns "" ipv4.ignore-auto-dns no
            sudo nmcli connection up "$CONN_UUID"
        fi
        sudo rm -f /etc/polkit-1/rules.d/99-disable-network.rules
        sudo systemctl restart polkit.service || true

        # 2. Bloqueios de Sites e Whitelist
        echo "[2/5] Removendo filtros de sites (Hosts/dnsmasq)..."
        sudo systemctl stop dnsmasq || true
        sudo rm -f /etc/dnsmasq.d/whitelist.conf
        sudo sed -i '/^127.0.0.1 [^l]*/d' /etc/hosts
        if ! grep -q "127.0.0.1 localhost" /etc/hosts; then
            echo "127.0.0.1 localhost" | sudo tee -a /etc/hosts > /dev/null
        fi

        # 3. Terminal e dconf-editor
        echo "[3/5] Restaurando acesso ao Terminal e Dconf..."
        gsettings set org.cinnamon.desktop.lockdown disable-command-line false 2>/dev/null || true
        gsettings set org.cinnamon.desktop.keybindings.terminal "['<Primary><Alt>t']" 2>/dev/null || true
        gsettings set org.gnome.desktop.lockdown disable-command-line false 2>/dev/null || true
        DCONF_BIN=$(which dconf-editor)
        if [ -n "$DCONF_BIN" ]; then
            sudo setfacl -x u:aluno "$DCONF_BIN" 2>/dev/null || true
            sudo chmod 755 "$DCONF_BIN" 2>/dev/null || true
        fi

        # 4. Interface (Ícones e Barra de Tarefas)
        echo "[4/5] Restaurando visual da interface e barra de tarefas..."
        gsettings set org.nemo.desktop computer-icon-visible true 2>/dev/null || true
        gsettings set org.nemo.desktop home-icon-visible true 2>/dev/null || true
        gsettings set org.nemo.desktop trash-icon-visible true 2>/dev/null || true
        gsettings set org.nemo.desktop network-icon-visible true 2>/dev/null || true
        gsettings set org.cinnamon.desktop.background show-desktop-icons true 2>/dev/null || true
        
        PANEL_IDS=$(gsettings get org.cinnamon panels-enabled 2>/dev/null | grep -o -P "'\d+:\d+:\w+'" | sed "s/'//g" | cut -d: -f1);
        if [ -n "$PANEL_IDS" ]; then
            for id in $PANEL_IDS; do
                gsettings set org.cinnamon panels-autohide "['$id:false']" 2>/dev/null || true
            done
        fi
        if [ -f "$HOME/.applet_config_backup" ]; then
            gsettings set org.cinnamon enabled-applets "$(cat "$HOME/.applet_config_backup")" 2>/dev/null || true
            rm "$HOME/.applet_config_backup"
        fi

        # 5. Periféricos e Filtro de Conteúdo
        echo "[5/5] Reativando periféricos e limpando filtros adicionais..."
        gsettings set org.gnome.desktop.content-control policy 'none' 2>/dev/null || true
        
        echo "--- DESBLOQUEIO CONCLUÍDO COM SUCESSO ---"
    """
    return script.strip(), None

@register_command('ocultar_icone_rede', 'Ocultar Ícone de Rede', 'Controle da Interface', icon='eye-off')
def _build_hide_network_icon_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Oculta o ícone de rede no Cinnamon para o usuário."""
    script = GSETTINGS_ENV_SETUP + """
        gsettings set org.cinnamon.desktop.background show-desktop-icons false 2>/dev/null || true
        echo "Ícone de rede ocultado."
    """
    return script.strip(), None

@register_command('mostrar_icone_rede', 'Mostrar Ícone de Rede', 'Controle da Interface', icon='eye')
def _build_show_network_icon_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Mostra o ícone de rede no Cinnamon para o usuário."""
    script = GSETTINGS_ENV_SETUP + """
        gsettings set org.cinnamon.desktop.background show-desktop-icons true 2>/dev/null || true
        echo "Ícone de rede mostrado."
    """
    return script.strip(), None


register_command('ativar_deep_lock', 'Ativar Deep Lock', 'Controle da Interface', icon='lock', command_or_func=lambda d: build_sudo_command(d, "freeze start all", "Ativando o Deep Lock..."))
register_command('desativar_deep_lock', 'Desativar Deep Lock', 'Controle da Interface', icon='unlock', command_or_func=lambda d: build_sudo_command(d, "freeze stop all", "Desativando o Deep Lock..."))
register_command('backup_aplicacao', 'Backup da Aplicação', 'Gerenciamento do Sistema', icon='archive') # Ação local tratada no app.py
register_command('restaurar_backup_aplicacao', 'Restaurar Backup da Aplicação', 'Gerenciamento do Sistema', icon='upload-cloud') # Ação local tratada no app.py
register_command('shutdown_server', 'Desligar Servidor (Backend)', 'Ações Remotas', icon='stop-circle', is_dangerous=True)

def _get_command_builder(action: str):
    """Retorna o construtor de comando para a ação especificada."""
    return COMMANDS.get(action)

@register_command('ativar_dns_familia', 'Ativar DNS Familiar', 'Configurações de Rede', icon='shield')
def _build_enable_family_dns(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Configura o Cloudflare Family DNS (1.1.1.3) para bloquear malware e conteúdo adulto.
    Usa nmcli para modificar a conexão ativa.
    """
    script = """
        # Localiza a conexão ativa principal (ignorando loopback e veth)
        CONN_UUID=$(nmcli -t -f UUID,TYPE,STATE connection show --active | grep -E ":802-3-ethernet|:802-11-wireless" | head -n1 | cut -d: -f1)
        
        if [ -z "$CONN_UUID" ]; then
            echo "Erro: Nenhuma conexão Ethernet ou Wi-Fi ativa encontrada." >&2
            exit 1
        fi

        echo "Configurando DNS Familiar na conexão: $CONN_UUID"
        sudo nmcli connection modify "$CONN_UUID" ipv4.dns "1.1.1.3 1.0.0.3"
        sudo nmcli connection modify "$CONN_UUID" ipv4.ignore-auto-dns yes
        sudo nmcli connection up "$CONN_UUID"
        
        echo "DNS Familiar (Cloudflare) ativado com sucesso. Conteúdo adulto e malware agora estão bloqueados."
    """
    return script.strip(), None

@register_command('desativar_dns_familia', 'Desativar DNS Familiar', 'Configurações de Rede', icon='shield-off')
def _build_disable_family_dns(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Remove a configuração de DNS fixo e volta a aceitar o DNS automático da rede (DHCP).
    """
    script = """
        CONN_UUID=$(nmcli -t -f UUID,TYPE,STATE connection show --active | grep -E ":802-3-ethernet|:802-11-wireless" | head -n1 | cut -d: -f1)
        
        if [ -z "$CONN_UUID" ]; then
            echo "Erro: Nenhuma conexão ativa encontrada para restaurar DNS." >&2
            exit 1
        fi

        echo "Restaurando DNS automático na conexão: $CONN_UUID"
        sudo nmcli connection modify "$CONN_UUID" ipv4.dns ""
        sudo nmcli connection modify "$CONN_UUID" ipv4.ignore-auto-dns no
        sudo nmcli connection up "$CONN_UUID"
        
        echo "DNS Familiar desativado. A máquina agora utiliza as configurações padrão da rede."
    """
    return script.strip(), None

@register_command('desbloquear_config_rede', 'Desbloquear Alteração de Rede', 'Configurações de Rede', icon='unlock')
def _build_unblock_network_settings(data: Dict[str, Any]) -> Tuple[str, None]:
    """Remove a regra de Polkit que bloqueia a alteração de rede."""
    script = """
        sudo rm -f /etc/polkit-1/rules.d/99-disable-network.rules
        echo "Alteração de configurações de rede permitida novamente."
    """
    return script.strip(), None

@register_command('ativar_whitelist_sites', 'Ativar Whitelist de Sites', 'Configurações de Rede', icon='check-square', require_field='whitelist-sites-group')
def _build_enable_whitelist_sites_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Configura dnsmasq para permitir acesso apenas a sites específicos (whitelist).
    Bloqueia todo o resto e define o DNS do sistema para 127.0.0.1.
    """
    sites_raw = data.get('sites', '')
    site_list = [s.strip() for s in re.split(r'[,\s\n]+', sites_raw) if s.strip()]

    if not site_list:
        return None, {"success": False, "message": "A lista de sites para a whitelist não pode estar vazia."}

    # Constrói a configuração do dnsmasq
    dnsmasq_config_lines = [
        "# Configuração de Whitelist gerada pelo Gerenciador de Atalhos",
        "no-resolv",  # dnsmasq não usará /etc/resolv.conf para upstreams
        "no-hosts",   # dnsmasq não usará /etc/hosts para nomes locais (opcional, mas mais seguro para whitelist estrita)
        "strict-order", # Garante que as regras sejam processadas em ordem
        "server=1.1.1.1", # Servidor DNS padrão para domínios permitidos (Cloudflare)
        "server=1.0.0.1", # Servidor DNS secundário para domínios permitidos
        "address=/#/127.0.0.1", # Bloqueia todos os domínios não explicitamente permitidos
    ]
    for site in site_list:
        # Permite o domínio e seus subdomínios, encaminhando para o Cloudflare
        dnsmasq_config_lines.append(f"server=/{site}/1.1.1.1")
        # Também permite a versão com www. se não foi fornecida
        if not site.startswith('www.'):
            dnsmasq_config_lines.append(f"server=/www.{site}/1.1.1.1")

    dnsmasq_config_content = "\n".join(dnsmasq_config_lines)

    script = f"""
        set -e
        CONN_UUID=$(nmcli -t -f UUID,TYPE,STATE connection show --active | grep -E ":802-3-ethernet|:802-11-wireless" | head -n1 | cut -d: -f1)
        if [ -z "$CONN_UUID" ]; then echo "Erro: Conexão ativa (Ethernet/Wi-Fi) não encontrada." >&2; exit 1; fi

        echo "Verificando e instalando dnsmasq..."
        if ! command -v dnsmasq &> /dev/null; then
            sudo apt-get update -qq && sudo apt-get install -y dnsmasq
        fi

        echo "Parando dnsmasq e fazendo backup das configurações existentes..."
        sudo systemctl stop dnsmasq || true
        sudo mkdir -p /etc/dnsmasq.d.bak/
        sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak.$(date +%Y%m%d%H%M%S) || true
        sudo mv /etc/dnsmasq.d/* /etc/dnsmasq.d.bak/ || true # Move todos os arquivos para backup

        echo "Criando arquivo de configuração de whitelist para dnsmasq..."
        echo {shlex.quote(dnsmasq_config_content)} | sudo tee /etc/dnsmasq.d/whitelist.conf > /dev/null

        echo "Configurando DNS do sistema para 127.0.0.1 (localhost)..."
        sudo nmcli connection modify "$CONN_UUID" ipv4.dns "127.0.0.1"
        sudo nmcli connection modify "$CONN_UUID" ipv4.ignore-auto-dns yes
        sudo nmcli connection up "$CONN_UUID"

        echo "Iniciando dnsmasq..."
        sudo systemctl start dnsmasq

        echo "Whitelist de sites ativada com sucesso. Apenas os sites permitidos serão acessíveis."
        echo "--- Teste de Resolução ---"
        # Testa um site permitido (google.com)
        if nslookup google.com 127.0.0.1 | grep -q "Address: "; then
            echo "✅ Teste de resolução de site permitido (google.com) via dnsmasq: SUCESSO."
        else
            echo "❌ Teste de resolução de site permitido (google.com) via dnsmasq: FALHA."
        fi
        # Testa um site não permitido (badsite.com)
        if nslookup badsite.com 127.0.0.1 | grep -q "Address: 127.0.0.1"; then
            echo "✅ Teste de bloqueio de site não permitido (badsite.com) via dnsmasq: SUCESSO."
        else
            echo "❌ Teste de bloqueio de site não permitido (badsite.com) via dnsmasq: FALHA."
        fi
    """
    return script.strip(), None

@register_command('desativar_whitelist_sites', 'Desativar Whitelist de Sites', 'Configurações de Rede', icon='x-square')
def _build_disable_whitelist_sites_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Desativa a whitelist de sites, restaurando as configurações de DNS e dnsmasq.
    """
    script = f"""
        set -e
        CONN_UUID=$(nmcli -t -f UUID,TYPE,STATE connection show --active | grep -E ":802-3-ethernet|:802-11-wireless" | head -n1 | cut -d: -f1)
        if [ -z "$CONN_UUID" ]; then echo "Erro: Conexão ativa (Ethernet/Wi-Fi) não encontrada." >&2; exit 1; fi

        echo "Parando dnsmasq e restaurando configurações..."
        sudo systemctl stop dnsmasq || true
        sudo rm -f /etc/dnsmasq.d/whitelist.conf

        # Restaura arquivos de backup se existirem
        if [ -f /etc/dnsmasq.conf.bak.* ]; then
            sudo mv $(ls -t /etc/dnsmasq.conf.bak.* | head -1) /etc/dnsmasq.conf
        fi
        if [ -d /etc/dnsmasq.d.bak/ ]; then
            sudo mv /etc/dnsmasq.d.bak/* /etc/dnsmasq.d/ || true
            sudo rmdir /etc/dnsmasq.d.bak/ || true
        fi

        echo "Restaurando DNS do sistema para automático..."
        sudo nmcli connection modify "$CONN_UUID" ipv4.dns ""
        sudo nmcli connection modify "$CONN_UUID" ipv4.ignore-auto-dns no
        sudo nmcli connection up "$CONN_UUID"

        echo "Iniciando dnsmasq (se estava ativo antes)..."
        sudo systemctl start dnsmasq || true # Inicia dnsmasq se ele já estava rodando antes

        echo "Whitelist de sites desativada. O sistema agora utiliza as configurações padrão da rede."
    """
    return script.strip(), None

@register_command('verificar_whitelist_sites', 'Verificar Status da Whitelist', 'Configurações de Rede', icon='list')
def _build_check_whitelist_status_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Verifica se o dnsmasq está rodando, se o arquivo de whitelist existe e lista os sites.
    """
    script = """
        echo "--- STATUS DO SERVIÇO ---"
        if systemctl is-active --quiet dnsmasq; then
            echo "✅ dnsmasq está ATIVO."
        else
            echo "❌ dnsmasq está PARADO ou não instalado."
        fi

        echo -e "\\n--- ARQUIVO DE CONFIGURAÇÃO ---"
        CONF_FILE="/etc/dnsmasq.d/whitelist.conf"
        if [ -f "$CONF_FILE" ]; then
            echo "✅ Arquivo encontrado: $CONF_FILE"
            echo -e "\\n--- SITES PERMITIDOS NA LISTA ---"
            grep "^server=/" "$CONF_FILE" | cut -d'/' -f2 | sort -u | sed 's/^/  • /'
        else
            echo "❌ Arquivo de whitelist não encontrado."
        fi

        echo -e "\\n--- DNS ATUAL DO SISTEMA ---"
        nmcli dev show | grep 'IP4.DNS' | awk '{print "DNS detectado: " $2}'
    """
    return script.strip(), None

@register_command('bloquear_sites', 'Bloquear Sites Específicos', 'Configurações de Rede', icon='shield', require_field='sites-group')
def _build_block_sites_command(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Adiciona entradas ao /etc/hosts para bloquear acesso a domínios específicos."""
    sites_raw = data.get('sites', '')
    # Divide por espaços, vírgulas ou novas linhas e limpa
    site_list = [s.strip() for s in re.split(r'[,\s\n]+', sites_raw) if s.strip()]
    
    if not site_list:
        return None, {"success": False, "message": "A lista de sites não pode estar vazia."}

    # Constrói o comando de forma a não duplicar entradas
    lines = []
    for site in site_list:
        safe_site = shlex.quote(site)
        lines.append(f"if ! grep -q '127.0.0.1 {safe_site}' /etc/hosts; then echo '127.0.0.1 {safe_site}' | sudo tee -a /etc/hosts > /dev/null; fi")
        # Bloqueia também a versão com www. se não foi fornecida
        if not site.startswith('www.'):
            www_site = shlex.quote(f"www.{site}")
            lines.append(f"if ! grep -q '127.0.0.1 {www_site}' /etc/hosts; then echo '127.0.0.1 {www_site}' | sudo tee -a /etc/hosts > /dev/null; fi")

    script = "\n".join(lines) + "\necho 'Sites bloqueados com sucesso no arquivo hosts.'"
    return script, None

@register_command('desbloquear_sites', 'Remover Bloqueio de Sites', 'Configurações de Rede', icon='shield-off')
def _build_unblock_sites_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """Remove as entradas de bloqueio (127.0.0.1) criadas, preservando o localhost."""
    script = """
        # Remove linhas que começam com 127.0.0.1 MAS ignora a linha do localhost
        sudo sed -i '/^127.0.0.1 [^l]*/d' /etc/hosts
        # Garante que o localhost ainda existe (caso o comando acima tenha sido agressivo demais)
        if ! grep -q "127.0.0.1 localhost" /etc/hosts; then
            echo "127.0.0.1 localhost" | sudo tee -a /etc/hosts > /dev/null
        fi
        echo "Todos os bloqueios manuais de sites foram removidos."
    """
    return script.strip(), None

register_command('limpar_imagens', 'Limpar Pasta de Imagens', 'Gerenciamento do Sistema', icon='trash-2', command_or_func="""
        IMG_DIR="$HOME/Imagens"
        if [ ! -d "$IMG_DIR" ]; then
            echo "Pasta de Imagens não encontrada."
            exit 0
        fi
        
        if ! command -v gio &> /dev/null; then
            echo "AVISO: Comando 'gio' não encontrado. Usando 'rm' para exclusão permanente." >&2
            # -mindepth 1 para não remover o próprio diretório Imagens
            find "$IMG_DIR" -mindepth 1 -delete
            echo "Pasta de Imagens foi limpa (exclusão permanente)."
        else
            # Move todos os arquivos e pastas dentro de Imagens para a lixeira
            # O '|| true' evita que o script falhe se não houver nada para mover
            gio trash "$IMG_DIR"/* || true
            echo "Conteúdo da pasta de Imagens foi movido para a lixeira."
        fi
    """)

register_command('wake_on_lan', 'Ligar (Wake-on-LAN)', 'Ações Remotas', icon='zap')
register_command('reiniciar', 'Reiniciar Máquina', 'Ações Remotas', icon='rotate-ccw', command_or_func=lambda d: _build_fire_and_forget_command(d, "reboot", "Reiniciando..."), is_dangerous=True)
register_command('desligar', 'Desligar Máquina', 'Ações Remotas', icon='power', command_or_func=lambda d: _build_fire_and_forget_command(d, "shutdown now", "Desligando..."), is_dangerous=True)

register_command('disable_sleep_button', 'Desativar Suspensão', 'Controle da Interface', icon='moon', command_or_func=lambda d: build_sudo_command(d,
        "systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target && echo 'Modos de suspensão (sleep) foram desativados.'",
        "Desativando modos de suspensão..."
    ))
register_command('enable_sleep_button', 'Ativar Suspensão', 'Controle da Interface', icon='sun', command_or_func=lambda d: build_sudo_command(d,
        "systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target && echo 'Modos de suspensão (sleep) foram reativados.'",
        "Ativando modos de suspensão..."
    ))
register_command('resetar_multiseat', 'Resetar Seats', 'Multiseat', icon='trash', command_or_func=lambda d: ("loginctl flush-devices && echo 'Todas as configurações de dispositivos de seat foram limpas (flush).'", None))
register_command('status_multiseat', 'Status do Seat1', 'Multiseat', icon='activity', command_or_func=lambda d: ("loginctl seat-status seat1 || echo 'Seat1 não está ativo ou não encontrado.'", None))

# --- Comandos que requerem scripts mais complexos ---

# Script para remover o Nemo
remove_nemo_script = """
    set -e
    export DEBIAN_FRONTEND=noninteractive
    echo "W: Removendo Nemo, Cinnamon e suas configurações..." >&2
    apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" purge nemo* cinnamon* >&2
    apt-get autoremove -y >&2
    echo "Nemo e Cinnamon foram removidos com sucesso."
"""
register_command('remover_nemo', 'Remover Nemo e Cinnamon', 'Gerenciamento do Sistema', icon='file-minus', command_or_func=lambda d: build_sudo_command(d, remove_nemo_script.strip(), "Removendo Nemo e Cinnamon..."), is_dangerous=True)

# Script para instalar o Nemo
install_nemo_script = """
    set -e
    export DEBIAN_FRONTEND=noninteractive
    echo -e "W: Atualizando a lista de pacotes..." >&2
    apt-get update
    echo -e "W: Instalando o gerenciador de arquivos Nemo e o ambiente Cinnamon..." >&2
    apt-get install -y --reinstall nemo cinnamon
    echo "Nemo e Cinnamon foram instalados com sucesso."
"""
register_command('instalar_nemo', 'Instalar Nemo e Cinnamon', 'Gerenciamento do Sistema', icon='file-plus', command_or_func=lambda d: build_sudo_command(d, install_nemo_script.strip(), "Instalando Nemo e Cinnamon..."), is_streaming=True)

# Script para desinstalar o ScratchJR
uninstall_scratchjr_script = """
    set -e
    export DEBIAN_FRONTEND=noninteractive
    # Verifica se o pacote está instalado antes de tentar remover.
    # O comando 'dpkg-query -W' retorna um status 0 se o pacote estiver instalado.
    if dpkg-query -W -f='${Status}' scratchjr 2>/dev/null | grep -q "install ok installed"; then
        echo "W: Pacote 'scratchjr' encontrado. Removendo..." >&2
        # Adiciona '|| true' para garantir que o script não falhe se o apt-get retornar um erro
        # (por exemplo, se o pacote for removido entre a verificação e a execução).
        apt-get remove -y scratchjr >&2 || true
        echo "Tentativa de remoção do ScratchJR concluída."
    else
        # Se o pacote não estiver instalado, a operação é considerada um sucesso.
        echo "ScratchJR já não estava instalado no dispositivo."
    fi
"""
register_command('desinstalar_scratchjr', 'Desinstalar ScratchJR', 'Gerenciamento do Sistema', icon='package', command_or_func=lambda d: build_sudo_command(d, uninstall_scratchjr_script.strip(), "Desinstalando ScratchJR..."), is_streaming=True)

# Script para instalar o ScratchJR
install_scratchjr_script = """
    set -e
    export DEBIAN_FRONTEND=noninteractive
    
    # Procura pelo arquivo .deb na pasta Documentos do usuário.
    # A variável $HOME é definida corretamente pelo 'sudo -u <username>'.
    DEB_FILENAME="scratchjr_1.3.6_amd64_linux_funcionando.deb"
    DEB_PATH="$HOME/Documentos/$DEB_FILENAME"

    if [ -f "$DEB_PATH" ]; then
        # Movido para stdout para aparecer na ordem correta no log.
        echo "Instalando o ScratchJR a partir de '$DEB_PATH'..."
        # Executa os comandos de instalação com 'sudo' para obter privilégios de root.
        # A senha é passada via stdin para o sudo interno usando a flag -S,
        # pois o script é executado como um usuário não-root que precisa escalar privilégios.
        # A variável SUDO_PASSWORD é exportada pelo comando que chama este script.
        echo "$SUDO_PASSWORD" | sudo -S dpkg -i "$DEB_PATH" || \
        echo "$SUDO_PASSWORD" | sudo -S apt-get install -f -y
        echo "ScratchJR foi instalado com sucesso."
    else
        echo "ERRO: O arquivo '$DEB_FILENAME' não foi encontrado na pasta Documentos do usuário." >&2
        exit 1
    fi
"""
# A ação 'instalar_scratchjr' é específica do usuário, então o comando é o próprio script.
def _build_install_scratchjr_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói o comando para instalar o ScratchJR, exportando a senha
    para que o sudo interno possa usá-la.
    """
    password = data.get('password', '')
    safe_password = shlex.quote(password)
    # Injeta a senha via stdin para o bloco de script, evitando visibilidade em variáveis de ambiente globais.
    command = f"echo {safe_password} | (read -r SUDO_PASSWORD; export SUDO_PASSWORD; {install_scratchjr_script.strip()})"
    return command, None

@register_command('ativar_dns_familia', 'Ativar DNS Familiar', 'Configurações de Rede', icon='shield')
def _build_enable_family_dns(data: Dict[str, Any]) -> Tuple[str, None]:
    """Configura o Cloudflare Family DNS na conexão ativa."""
    script = """
        CONN_UUID=$(nmcli -t -f UUID,TYPE,STATE connection show --active | grep -E ":802-3-ethernet|:802-11-wireless" | head -n1 | cut -d: -f1)
        if [ -z "$CONN_UUID" ]; then echo "Erro: Conexão ativa não encontrada." >&2; exit 1; fi

        echo "Configurando IPs 1.1.1.3 e 1.0.0.3..."
        sudo nmcli connection modify "$CONN_UUID" ipv4.dns "1.1.1.3 1.0.0.3"
        sudo nmcli connection modify "$CONN_UUID" ipv4.ignore-auto-dns yes
        sudo nmcli connection up "$CONN_UUID"
        echo "DNS Familiar configurado com sucesso."
    """
    return script.strip(), None

@register_command('desativar_dns_familia', 'Desativar DNS Familiar', 'Configurações de Rede', icon='shield-off')
def _build_disable_family_dns(data: Dict[str, Any]) -> Tuple[str, None]:
    """Restaura o DNS automático (DHCP)."""
    script = """
        CONN_UUID=$(nmcli -t -f UUID,TYPE,STATE connection show --active | grep -E ":802-3-ethernet|:802-11-wireless" | head -n1 | cut -d: -f1)
        if [ -z "$CONN_UUID" ]; then echo "Erro: Conexão ativa não encontrada." >&2; exit 1; fi

        sudo nmcli connection modify "$CONN_UUID" ipv4.dns ""
        sudo nmcli connection modify "$CONN_UUID" ipv4.ignore-auto-dns no
        sudo nmcli connection up "$CONN_UUID"
        echo "DNS automático restaurado."
    """
    return script.strip(), None

@register_command('verificar_dns_familia', 'Testar Filtro DNS', 'Configurações de Rede', icon='check-circle')
def _build_verify_family_dns(data: Dict[str, Any]) -> Tuple[str, None]:
    """Verifica se o sistema está resolvendo nomes através do filtro da Cloudflare."""
    script = """
        echo "--- STATUS DA CONFIGURAÇÃO ---"
        nmcli dev show | grep 'IP4.DNS' | awk '{print "DNS detectado: " $2}'
        
        echo -e "\\n--- TESTE DE RESOLUÇÃO (Cloudflare TXT Check) ---"
        if ! command -v nslookup &> /dev/null; then
            echo "⚠️ nslookup não instalado. Tentando instalar dnsutils..."
            sudo apt-get update -qq && sudo apt-get install -y dnsutils > /dev/null 2>&1
        fi

        if command -v nslookup &> /dev/null; then
            # Captura o token de verificação dinâmico, limpando aspas e espaços extras
            CHECK=$(nslookup -type=txt family.cloudflare-dns.com 2>/dev/null | grep "text =" | sed 's/.*text = //' | tr -d '"' | tr -d ' ' || true)
            # Teste definitivo: Tenta resolver um domínio de malware. Se retornar 0.0.0.0, a filtragem está ativa.
            MALWARE_BLOCK=$(nslookup malware.testcategory.com 2>/dev/null | grep "Address: 0.0.0.0" || true)

            if [[ -n "$CHECK" ]] || [[ -n "$MALWARE_BLOCK" ]]; then
                echo "✅ SUCESSO: O filtro Cloudflare Family está ATIVO."
                [[ -n "$MALWARE_BLOCK" ]] && echo "🛡️ Bloqueio verificado: malware.testcategory.com -> 0.0.0.0"
                [[ -n "$CHECK" ]] && echo "ID de Resolução detectado: $CHECK"
            else
                echo "❌ FALHA: O sistema não está filtrando o tráfego via Cloudflare Family."
                echo "DICA: Se o DNS detectado acima estiver correto, seu provedor de internet pode estar interceptando o DNS (Porta 53)."
            fi
        else
            ping -c 1 1.1.1.3 > /dev/null && echo "✅ Servidor 1.1.1.3 está acessível." || echo "❌ Servidor 1.1.1.3 está inacessível."
        fi
    """
    return script.strip(), None

register_command('instalar_scratchjr', 'Instalar ScratchJR', 'Gerenciamento do Sistema', icon='package', command_or_func=_build_install_scratchjr_command, is_streaming=True)

def _build_install_gcompris_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói um comando para instalar o GCompris via Flatpak.
    """
    script = """
        set -e
        export DEBIAN_FRONTEND=noninteractive
        echo "W: Atualizando lista de pacotes e instalando Flatpak..." >&2
        apt-get update
        apt-get install -y flatpak

        echo "W: Adicionando o repositório Flathub (system-wide)..." >&2
        flatpak remote-add --system --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

        echo "W: Instalando GCompris via Flatpak (system-wide)... Isso pode levar vários minutos." >&2
        flatpak install --system -y flathub org.kde.gcompris

        echo "GCompris foi instalado com sucesso."
    """
    return script, None

register_command('instalar_gcompris', 'Instalar GCompris', 'Gerenciamento do Sistema', icon='package', command_or_func=_build_install_gcompris_command, is_streaming=True)

def _build_uninstall_gcompris_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói um comando para desinstalar o GCompris (via Flatpak e APT).
    """
    script = """
        set -e
        export DEBIAN_FRONTEND=noninteractive
        echo "W: Verificando instalações do GCompris..." >&2

        # 1. Tenta remover via APT (Nativo)
        if dpkg -l | grep -q 'gcompris'; then
            echo "W: Removendo GCompris via APT..." >&2
            apt-get purge -y gcompris* || true
            apt-get autoremove -y || true
            echo "GCompris removido via APT."
        fi

        # 2. Tenta remover via Flatpak
        if command -v flatpak &> /dev/null; then
            if flatpak list --system --app | grep -q 'org.kde.gcompris'; then
                echo "W: Desinstalando GCompris via Flatpak..." >&2
                flatpak uninstall --system -y org.kde.gcompris
                echo "GCompris removido via Flatpak."
            fi
        fi
        echo "Processo de desinstalação concluído."
    """
    return script, None

register_command('desinstalar_gcompris', 'Desinstalar GCompris', 'Gerenciamento do Sistema', icon='package', command_or_func=_build_uninstall_gcompris_command, is_streaming=True)

def _build_install_tuxpaint_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói um comando para instalar o Tux Paint via Flatpak.
    """
    script = """
        set -e
        export DEBIAN_FRONTEND=noninteractive
        echo "W: Atualizando lista de pacotes e instalando Flatpak..." >&2
        apt-get update
        apt-get install -y flatpak

        echo "W: Adicionando o repositório Flathub (system-wide)..." >&2
        flatpak remote-add --system --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

        echo "W: Instalando Tux Paint via Flatpak (system-wide)... Isso pode levar vários minutos." >&2
        flatpak install --system -y flathub org.tuxpaint.Tuxpaint

        echo "Tux Paint foi instalado com sucesso."
    """
    return script, None

register_command('instalar_tuxpaint', 'Instalar Tux Paint', 'Gerenciamento do Sistema', icon='package', command_or_func=_build_install_tuxpaint_command, is_streaming=True)

def _build_uninstall_tuxpaint_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói um comando para desinstalar o Tux Paint (via Flatpak e APT).
    """
    script = """
        set -e
        export DEBIAN_FRONTEND=noninteractive
        echo "W: Verificando instalações do Tux Paint..." >&2

        # 1. Tenta remover via APT (Nativo)
        if dpkg -l | grep -q 'tuxpaint'; then
            echo "W: Removendo Tux Paint via APT..." >&2
            apt-get purge -y tuxpaint* || true
            apt-get autoremove -y || true
            echo "Tux Paint removido via APT."
        fi

        # 2. Tenta remover via Flatpak
        if command -v flatpak &> /dev/null; then
            if flatpak list --system --app | grep -q 'org.tuxpaint.Tuxpaint'; then
                echo "W: Desinstalando Tux Paint via Flatpak..." >&2
                flatpak uninstall --system -y org.tuxpaint.Tuxpaint
                echo "Tux Paint removido via Flatpak."
            fi
        fi
        echo "Processo de desinstalação concluído."
    """
    return script, None

register_command('desinstalar_tuxpaint', 'Desinstalar Tux Paint', 'Gerenciamento do Sistema', icon='package', command_or_func=_build_uninstall_tuxpaint_command, is_streaming=True)

def _build_install_libreoffice_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói um comando para instalar o LibreOffice via apt-get.
    """
    script = """
        set -e
        export DEBIAN_FRONTEND=noninteractive
        
        # Verifica espaço em disco (requer ~1GB = 1048576 KB)
        AVAILABLE_SPACE=$(df /var/cache/apt/archives/ --output=avail | tail -n 1)
        if [ "$AVAILABLE_SPACE" -lt 1048576 ]; then
            echo "ERRO: Espaço em disco insuficiente. Requer 1GB livre." >&2
            exit 1
        fi

        echo "W: Atualizando lista de pacotes..." >&2
        apt-get update
        echo "W: Instalando LibreOffice e pacote de idioma PT-BR..." >&2
        apt-get install -y libreoffice libreoffice-l10n-pt-br libreoffice-help-pt-br
        echo "LibreOffice foi instalado com sucesso."
    """
    return script, None

register_command('instalar_libreoffice', 'Instalar LibreOffice', 'Gerenciamento do Sistema', icon='file-text', command_or_func=_build_install_libreoffice_command, is_streaming=True)

def _build_uninstall_libreoffice_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói um comando para desinstalar o LibreOffice.
    """
    script = """
        set -e
        export DEBIAN_FRONTEND=noninteractive
        echo "W: Removendo LibreOffice..." >&2
        apt-get remove -y --purge libreoffice*
        apt-get autoremove -y
        echo "LibreOffice foi desinstalado com sucesso."
    """
    return script, None

register_command('desinstalar_libreoffice', 'Desinstalar LibreOffice', 'Gerenciamento do Sistema', icon='file-minus', command_or_func=_build_uninstall_libreoffice_command, is_streaming=True)

def _build_install_calculator_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói um comando para instalar a Calculadora (gnome-calculator).
    """
    script = """
        set -e
        export DEBIAN_FRONTEND=noninteractive
        echo "W: Atualizando lista de pacotes..." >&2
        apt-get update
        echo "W: Instalando Gnome Calculator..." >&2
        apt-get install -y gnome-calculator
        echo "Calculadora foi instalada com sucesso."
    """
    return script, None

def _build_uninstall_calculator_command(data: Dict[str, Any]) -> Tuple[str, None]:
    """
    Constrói um comando para desinstalar a Calculadora.
    """
    script = """
        set -e
        export DEBIAN_FRONTEND=noninteractive
        echo "W: Removendo Gnome Calculator..." >&2
        apt-get remove -y gnome-calculator
        apt-get autoremove -y
        echo "Calculadora foi desinstalada com sucesso."
    """
    return script, None

register_command('instalar_calculadora', 'Instalar Calculadora', 'Gerenciamento do Sistema', icon='plus-square', command_or_func=_build_install_calculator_command, is_streaming=True)
register_command('desinstalar_calculadora', 'Desinstalar Calculadora', 'Gerenciamento do Sistema', icon='minus-square', command_or_func=_build_uninstall_calculator_command, is_streaming=True)

# Outros comandos baseados em strings/funções locais
register_command('ativar_deep_lock', 'Ativar Deep Lock', 'Controle da Interface', icon='lock', command_or_func=lambda d: build_sudo_command(d, "freeze start all", "Ativando o Deep Lock..."))
register_command('desativar_deep_lock', 'Desativar Deep Lock', 'Controle da Interface', icon='unlock', command_or_func=lambda d: build_sudo_command(d, "freeze stop all", "Desativando o Deep Lock..."))
register_command('backup_aplicacao', 'Backup da Aplicação', 'Gerenciamento do Sistema', icon='archive') # Ação local tratada no app.py
register_command('restaurar_backup_aplicacao', 'Restaurar Backup da Aplicação', 'Gerenciamento do Sistema', icon='upload-cloud') # Ação local tratada no app.py
register_command('shutdown_server', 'Desligar Servidor (Backend)', 'Ações Remotas', icon='stop-circle', is_dangerous=True)

def _get_command_builder(action: str):
    """Retorna o construtor de comando para a ação especificada."""
    return COMMANDS.get(action)