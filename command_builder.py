# services/command_builder.py

import html
import shlex
import re
from typing import Dict, Tuple, Optional, Any

# --- Exceção Personalizada ---
class CommandExecutionError(Exception):
    """Exceção lançada quando um comando shell falha."""
    def __init__(self, message, details=None, warnings=None):
        super().__init__(message)
        self.details = details
        self.warnings = warnings

# --- Carregar Scripts Externos ---
def _load_script(filename: str) -> str:
    """Carrega um script de um arquivo, com fallback e log de erro."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        # Em vez de um logger, imprime para stderr, que é visível no console do servidor.
        import sys
        print(f"FATAL: O script '{filename}' não foi encontrado. As ações dependentes irão falhar.", file=sys.stderr)
        return f"echo 'FATAL: {filename} not found'; exit 1;"

# Scripts são carregados uma vez quando o módulo é importado
# A dependência do 'current_app' foi removida para evitar erros de contexto de aplicação.
# O carregamento agora é mais robusto e independente do Flask.
GSETTINGS_ENV_SETUP = _load_script('setup_gsettings_env.sh')
MANAGE_RIGHT_CLICK_SCRIPT = _load_script('manage_right_click.sh')
MANAGE_PERIPHERALS_SCRIPT = _load_script('manage_peripherals.sh')
X11_ENV_SETUP = _load_script('setup_x11_env.sh')
UPDATE_MANAGER_SCRIPT = _load_script('update_manager.py')

# --- Funções auxiliares para construir comandos shell ---

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
        nohup zenity --info --title="Mensagem do Administrador" --text={safe_message} --width=500 > /dev/null 2>&1 &
        echo "Sinal para exibir mensagem foi enviado com sucesso."
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
    command = f"sudo -S {base_command}"
    return command, None

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
        /usr/bin/python3 "$SCRIPT_PATH"
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

# --- Dicionário de Comandos (Padrão de Dispatch) ---
COMMANDS = {
    'mostrar_sistema': _build_gsettings_visibility_command(True),
    'ocultar_sistema': _build_gsettings_visibility_command(False),
    'desativar_barra_tarefas': _build_panel_autohide_command(True),
    'ativar_barra_tarefas': _build_panel_autohide_command(False),
    'bloquear_barra_tarefas': GSETTINGS_ENV_SETUP + """
        gsettings get org.cinnamon enabled-applets > "$HOME/.applet_config_backup"
        gsettings set org.cinnamon enabled-applets "[]"
        echo "Barra de tarefas bloqueada (applets removidos).";
    """,
    'desbloquear_barra_tarefas': GSETTINGS_ENV_SETUP + """
        BACKUP_FILE="$HOME/.applet_config_backup"
        if [ -f "$BACKUP_FILE" ]; then
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
            rm -rf "$HOME/Imagens"/*;
            echo "Pasta de Imagens foi limpa.";
        else
            echo "Pasta de Imagens não encontrada.";
        fi;
    """,
    'enviar_mensagem': build_send_message_command,
    'reiniciar': lambda d: _build_fire_and_forget_command(d, "reboot", "Reiniciando a máquina..."),
    'desligar': lambda d: _build_fire_and_forget_command(d, "shutdown now", "Desligando a máquina..."),
    'kill_process': _build_kill_process_command,
    'get_system_info': _build_get_system_info_command,
    'disable_sleep_button': lambda d: build_sudo_command(d,
        "systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target && echo 'Modos de suspensão (sleep) foram desativados.'",
        "Desativando modos de suspensão..."
    ),
    'enable_sleep_button': lambda d: build_sudo_command(d,
        "systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target && echo 'Modos de suspensão (sleep) foram reativados.'",
        "Ativando modos de suspensão..."
    ),
    'ativar_deep_lock': lambda d: build_sudo_command(d,
        "freeze start all",
        "Ativando o Deep Lock (freeze)..."
    ),
    'desativar_deep_lock': lambda d: build_sudo_command(d,
        "freeze stop all",
        "Desativando o Deep Lock (freeze)..."
    ),
    'atualizar_sistema': _build_update_system_command,
}

# --- Comandos que requerem scripts mais complexos ---

# Script para remover o Nemo
remove_nemo_script = """
    set -e
    export DEBIAN_FRONTEND=noninteractive
    echo "W: Removendo o gerenciador de arquivos Nemo e suas configurações..." >&2
    apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" purge nemo* >&2
    echo "Nemo foi removido com sucesso."
"""
remove_nemo_command = f"sh -c {shlex.quote(remove_nemo_script.strip())}"
COMMANDS['remover_nemo'] = lambda d: build_sudo_command(d, remove_nemo_command, "Removendo Nemo...")

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
install_nemo_command = f"sh -c {shlex.quote(install_nemo_script.strip())}"
COMMANDS['instalar_nemo'] = lambda d: build_sudo_command(d, install_nemo_command, "Instalando Nemo...")

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
uninstall_scratchjr_command = f"sh -c {shlex.quote(uninstall_scratchjr_script.strip())}"
COMMANDS['desinstalar_scratchjr'] = lambda d: build_sudo_command(d, uninstall_scratchjr_command, "Desinstalando ScratchJR...")

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
    # Exporta a senha para uma variável de ambiente que o script interno pode usar.
    command = f"export SUDO_PASSWORD={safe_password}; {install_scratchjr_script.strip()}"
    return command, None

COMMANDS['instalar_scratchjr'] = _build_install_scratchjr_command

def _get_command_builder(action: str):
    """Retorna o construtor de comando para a ação especificada."""
    return COMMANDS.get(action)